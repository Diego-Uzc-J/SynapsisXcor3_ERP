"""Servicios de dominio del módulo de Manufactura y Producción.

Implementa la lógica de centros de trabajo, listas de materiales y gestión
inicial de órdenes de producción descrita en ``specs/manufacturing_spec.md``
(secciones 2.1 a 2.4, 3.4 a 3.6 y 4.1 a 4.3).

* **Centros de trabajo:** alta con ``code`` único, listado filtrable por estado
  y actualización parcial conservando la unicidad del código.
* **BOM:** alta exigiendo que el producto terminado exista y esté activo en
  ``inventory``, que todos los componentes existan, que el ``code`` no esté en
  uso y que no haya otra BOM activa para el mismo ``product_id``/``version``
  (regla 5 y escenario 4).
* **Ciclo de versión:** desactivar una BOM y activar otra (la misma versión tras
  desactivar la anterior o una nueva versión) con las comprobaciones de estado
  vigente, producto activo y componentes disponibles.
* **Órdenes de producción:** alta en ``PLANNED`` con BOM activa y con
  componentes, almacenes existentes y cantidad positiva (regla 5 y escenario
  6); detalle con sus relaciones y listado filtrable por ``status``/``bom_id``;
  guardia de inmutabilidad para órdenes ``COMPLETED``/``CANCELLED`` (regla 4 y
  escenario 3) y cancelación desde ``PLANNED`` (regla 6).

Las validaciones que no requieren consultar estado ya viven en ``schemas.py``;
aquí se comprueban las reglas que dependen de la base de datos. Las escrituras
usan :func:`_atomic`, que confirma al finalizar y revierte cualquier error de
negocio o de integridad. Las excepciones derivan de ``fastapi.HTTPException``
con códigos 400/404/409, igual que en ``hr`` y ``purchasing``, por lo que no
requieren un manejador adicional en el router.

La exclusividad de BOM activa se comprueba en servicio y se serializa
bloqueando la fila del producto terminado (``SELECT ... FOR UPDATE``). El
índice único de ``bill_of_materials.code`` es la última barrera contra
duplicados por carrera entre peticiones concurrentes.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, TypeVar

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.modules.inventory.models import Product, Warehouse
from src.modules.manufacturing.models import (
    BOMItem,
    BillOfMaterials,
    ProductionOrder,
    ProductionOrderStatus,
    WorkCenter,
)
from src.modules.manufacturing.schemas import (
    BOMCreate,
    BOMItemCreate,
    BOMUpdate,
    ProductionOrderCreate,
    ProductionOrderUpdate,
    WorkCenterCreate,
    WorkCenterUpdate,
)

__all__ = [
    "DuplicateResourceError",
    "ImmutableProductionOrderError",
    "InactiveBOMError",
    "InactiveProductError",
    "InvalidBOMError",
    "InvalidProductionOrderError",
    "ManufacturingServiceError",
    "ResourceNotFoundError",
    "activate_bom",
    "cancel_production_order",
    "create_bom",
    "create_production_order",
    "create_work_center",
    "deactivate_bom",
    "ensure_production_order_mutable",
    "get_bom",
    "get_production_order",
    "get_work_center",
    "list_boms",
    "list_production_orders",
    "list_work_centers",
    "update_bom",
    "update_production_order",
    "update_work_center",
]


#: Base del advisory lock que serializa la secuencia ``OP-YYYY-XXXX``.
_ORDER_CODE_LOCK_BASE = 8_400_000

#: Estados que cierran una OP y prohiben cualquier modificación (regla 4).
_CLOSED_ORDER_STATUSES = frozenset(
    {ProductionOrderStatus.COMPLETED, ProductionOrderStatus.CANCELLED}
)


# --------------------------------------------------------------------------- #
# Excepciones HTTP de dominio
# --------------------------------------------------------------------------- #


class ManufacturingServiceError(HTTPException):
    """Error base del módulo de manufactura con su equivalencia HTTP."""

    status_code: int = 400

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=self.status_code, detail=detail)

    def __str__(self) -> str:
        """Devuelve solo el mensaje, como las excepciones de dominio del ERP."""
        return str(self.detail)


class ResourceNotFoundError(ManufacturingServiceError):
    """El recurso solicitado no existe (o no existe en inventario)."""

    status_code = 404


class DuplicateResourceError(ManufacturingServiceError):
    """El código o la versión activa ya está en uso (regla 5, escenario 4)."""

    status_code = 409


class InactiveProductError(ManufacturingServiceError):
    """La BOM referencia un producto terminado inactivo en inventario."""

    status_code = 400


class InvalidBOMError(ManufacturingServiceError):
    """La BOM no cumple una regla de negocio (por ejemplo, sin componentes)."""

    status_code = 400


class InactiveBOMError(ManufacturingServiceError):
    """La OP referencia una BOM inactiva (regla 5, escenario 6)."""

    status_code = 400


class InvalidProductionOrderError(ManufacturingServiceError):
    """La OP no cumple una regla de negocio o una transición de estado."""

    status_code = 400


class ImmutableProductionOrderError(ManufacturingServiceError):
    """La OP está ``COMPLETED``/``CANCELLED`` y no admite cambios (regla 4)."""

    status_code = 409


# --------------------------------------------------------------------------- #
# Utilidades internas
# --------------------------------------------------------------------------- #

_Row = TypeVar("_Row", WorkCenter, BillOfMaterials)


@contextmanager
def _atomic(db: Session) -> Iterator[None]:
    """Confirma la unidad de trabajo o revierte cualquier cambio ante un error."""
    try:
        yield
        db.commit()
    except Exception:
        db.rollback()
        raise


def _get_row(
    db: Session,
    model: type[_Row],
    resource_id: int,
    *,
    label: str,
    for_update: bool = False,
) -> _Row:
    """Obtiene una fila por id o lanza ``ResourceNotFoundError``."""
    stmt = select(model).where(model.id == resource_id)
    if for_update:
        stmt = stmt.with_for_update()
    row = db.scalars(stmt).first()
    if row is None:
        raise ResourceNotFoundError(f"{label} {resource_id} no encontrado")
    return row


def _get_product(
    db: Session,
    product_id: int,
    *,
    require_active: bool = False,
    for_update: bool = False,
) -> Product:
    """Obtiene un producto de inventario, opcionalmente exigiendo que esté activo."""
    stmt = select(Product).where(Product.id == product_id)
    if for_update:
        stmt = stmt.with_for_update()
    product = db.scalars(stmt).first()
    if product is None:
        raise ResourceNotFoundError(
            f"Producto {product_id} no encontrado en inventario"
        )
    if require_active and not product.is_active:
        raise InactiveProductError(
            f"El producto terminado {product_id} está inactivo en inventario; "
            "no se puede usar en una BOM"
        )
    return product


def _ensure_unique_work_center_code(
    db: Session, code: str, *, exclude_id: int | None = None
) -> None:
    """Verifica que el código del centro de trabajo no pertenezca a otro registro."""
    stmt = select(WorkCenter.id).where(WorkCenter.code == code)
    if exclude_id is not None:
        stmt = stmt.where(WorkCenter.id != exclude_id)
    if db.execute(stmt.limit(1)).first() is not None:
        raise DuplicateResourceError(
            f"Ya existe un centro de trabajo con el código '{code}'"
        )


def _ensure_unique_bom_code(
    db: Session, code: str, *, exclude_id: int | None = None
) -> None:
    """Verifica que el código de la BOM no esté en uso (regla 5, escenario 4)."""
    stmt = select(BillOfMaterials.id).where(BillOfMaterials.code == code)
    if exclude_id is not None:
        stmt = stmt.where(BillOfMaterials.id != exclude_id)
    if db.execute(stmt.limit(1)).first() is not None:
        raise DuplicateResourceError(f"Ya existe una BOM con el código '{code}'")


def _ensure_active_version_available(
    db: Session,
    product_id: int,
    version: int,
    *,
    exclude_id: int | None = None,
) -> None:
    """Exige una sola BOM activa por ``product_id``/``version`` (regla 5)."""
    stmt = select(BillOfMaterials.id).where(
        BillOfMaterials.product_id == product_id,
        BillOfMaterials.version == version,
        BillOfMaterials.is_active.is_(True),
    )
    if exclude_id is not None:
        stmt = stmt.where(BillOfMaterials.id != exclude_id)
    existing = db.execute(stmt.limit(1)).first()
    if existing is not None:
        raise DuplicateResourceError(
            f"Ya existe una BOM activa (id {existing[0]}) para el producto "
            f"{product_id} versión {version}; desactívala antes de activar otra"
        )


def _ensure_products_exist(
    db: Session, product_ids: set[int], *, label: str
) -> None:
    """Comprueba en una sola consulta que todos los ids existan en inventario."""
    if not product_ids:
        raise InvalidBOMError(f"La BOM debe tener al menos un {label}")
    found = set(db.scalars(select(Product.id).where(Product.id.in_(product_ids))).all())
    missing = sorted(product_ids - found)
    if missing:
        raise ResourceNotFoundError(
            f"{label.capitalize()} no encontrados en inventario: "
            f"{', '.join(str(product_id) for product_id in missing)}"
        )


def _ensure_components_exist(db: Session, items: Sequence[BOMItemCreate]) -> None:
    """Verifica que todos los componentes de la BOM existan en inventario."""
    _ensure_products_exist(
        db,
        {item.component_product_id for item in items},
        label="componente",
    )


def _ensure_bom_components_exist(db: Session, bom_id: int) -> None:
    """Verifica los componentes ya persistidos antes de activar una BOM."""
    component_ids = set(
        db.scalars(
            select(BOMItem.component_product_id).where(BOMItem.bom_id == bom_id)
        ).all()
    )
    _ensure_products_exist(db, component_ids, label="componente")


def _build_items(items: Sequence[BOMItemCreate]) -> list[BOMItem]:
    """Construye las líneas de la BOM sin asignar ``bom_id`` a mano."""
    return [
        BOMItem(
            component_product_id=item.component_product_id,
            quantity=item.quantity,
            scrap_percentage=item.scrap_percentage,
        )
        for item in items
    ]


def _sync_items(bom: BillOfMaterials, items: Sequence[BOMItemCreate]) -> None:
    """Reemplaza las líneas de una BOM existente sin violar su ``UNIQUE``.

    Asignar una lista nueva con ``delete-orphan`` hace que SQLAlchemy intente
    insertar primero y borrar después, chocando con
    ``UNIQUE(bom_id, component_product_id)`` cuando un componente se mantiene.
    Aquí los componentes que continúan se actualizan en su fila, los que sobran
    se marcan como huérfanos y solo los nuevos se insertan.
    """
    existing = {item.component_product_id: item for item in bom.items}
    incoming = {item.component_product_id: item for item in items}

    for component_id, row in existing.items():
        replacement = incoming.get(component_id)
        if replacement is None:
            bom.items.remove(row)
        else:
            row.quantity = replacement.quantity
            row.scrap_percentage = replacement.scrap_percentage

    for component_id, replacement in incoming.items():
        if component_id not in existing:
            bom.items.append(
                BOMItem(
                    component_product_id=replacement.component_product_id,
                    quantity=replacement.quantity,
                    scrap_percentage=replacement.scrap_percentage,
                )
            )


def _raise_bom_integrity_error(
    db: Session, *, data: BOMCreate, exc: IntegrityError
) -> None:
    """Traduce una violación del índice único a un error de dominio legible."""
    _ensure_unique_bom_code(db, data.code)
    if data.is_active:
        _ensure_active_version_available(db, data.product_id, data.version)
    raise DuplicateResourceError(
        "No se pudo crear la BOM por conflicto de integridad"
    ) from exc


# --------------------------------------------------------------------------- #
# Centros de trabajo — /api/v1/manufacturing/work-centers
# --------------------------------------------------------------------------- #


def create_work_center(db: Session, data: WorkCenterCreate) -> WorkCenter:
    """Registra un centro de trabajo validando la unicidad de su código."""
    try:
        with _atomic(db):
            _ensure_unique_work_center_code(db, data.code)
            work_center = WorkCenter(**data.model_dump())
            db.add(work_center)
    except IntegrityError as exc:
        db.rollback()
        _ensure_unique_work_center_code(db, data.code)
        raise DuplicateResourceError(
            "No se pudo crear el centro de trabajo por conflicto de integridad"
        ) from exc
    db.refresh(work_center)
    return work_center


def get_work_center(db: Session, work_center_id: int) -> WorkCenter:
    """Obtiene un centro de trabajo por id o lanza ``ResourceNotFoundError``."""
    return _get_row(
        db, WorkCenter, work_center_id, label="Centro de trabajo"
    )


def list_work_centers(
    db: Session,
    *,
    is_active: bool | None = True,
    skip: int = 0,
    limit: int = 100,
) -> list[WorkCenter]:
    """Lista centros de trabajo; por defecto solo los activos (spec §4.2)."""
    stmt = select(WorkCenter)
    if is_active is not None:
        stmt = stmt.where(WorkCenter.is_active.is_(is_active))
    stmt = stmt.order_by(WorkCenter.id).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


def update_work_center(
    db: Session, work_center_id: int, data: WorkCenterUpdate
) -> WorkCenter:
    """Actualiza parcialmente un centro de trabajo conservando el código único."""
    changes = data.model_dump(exclude_unset=True)
    new_code = changes.get("code")
    try:
        with _atomic(db):
            work_center = _get_row(
                db,
                WorkCenter,
                work_center_id,
                label="Centro de trabajo",
                for_update=True,
            )
            if new_code is not None and new_code != work_center.code:
                _ensure_unique_work_center_code(
                    db, new_code, exclude_id=work_center_id
                )
            for field, value in changes.items():
                setattr(work_center, field, value)
    except IntegrityError as exc:
        db.rollback()
        if new_code is not None:
            _ensure_unique_work_center_code(db, new_code, exclude_id=work_center_id)
        raise DuplicateResourceError(
            "No se pudo actualizar el centro de trabajo por conflicto de integridad"
        ) from exc
    db.refresh(work_center)
    return work_center


# --------------------------------------------------------------------------- #
# Listas de materiales — /api/v1/manufacturing/boms
# --------------------------------------------------------------------------- #


def create_bom(db: Session, data: BOMCreate) -> BillOfMaterials:
    """Crea una BOM con sus líneas aplicando la regla 5 de la spec.

    La fila del producto terminado se bloquea dentro de la transacción para que
    dos peticiones concurrentes no puedan activar cada una una BOM distinta para
    el mismo producto y versión. Si algún componente no existe o hay conflicto
    de código/versión activa, ``_atomic`` revierte antes de propagar el error.
    """
    try:
        with _atomic(db):
            _get_product(db, data.product_id, require_active=True, for_update=True)
            _ensure_unique_bom_code(db, data.code)
            if data.is_active:
                _ensure_active_version_available(db, data.product_id, data.version)
            _ensure_components_exist(db, data.items)

            bom = BillOfMaterials(**data.model_dump(exclude={"items"}))
            bom.items = _build_items(data.items)
            db.add(bom)
    except IntegrityError as exc:
        db.rollback()
        _raise_bom_integrity_error(db, data=data, exc=exc)
    db.refresh(bom)
    return bom


def get_bom(db: Session, bom_id: int) -> BillOfMaterials:
    """Obtiene el detalle de una BOM con todos sus componentes."""
    stmt = (
        select(BillOfMaterials)
        .where(BillOfMaterials.id == bom_id)
        .options(selectinload(BillOfMaterials.items))
    )
    bom = db.scalars(stmt).first()
    if bom is None:
        raise ResourceNotFoundError(f"BOM {bom_id} no encontrada")
    return bom


def list_boms(
    db: Session,
    *,
    product_id: int | None = None,
    is_active: bool | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[BillOfMaterials]:
    """Lista BOMs con filtros opcionales por producto y estado activo."""
    stmt = select(BillOfMaterials)
    if product_id is not None:
        stmt = stmt.where(BillOfMaterials.product_id == product_id)
    if is_active is not None:
        stmt = stmt.where(BillOfMaterials.is_active.is_(is_active))
    stmt = (
        stmt.options(selectinload(BillOfMaterials.items))
        .order_by(BillOfMaterials.id)
        .offset(skip)
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def update_bom(db: Session, bom_id: int, data: BOMUpdate) -> BillOfMaterials:
    """Actualiza parcialmente una BOM, validando el estado efectivo resultante.

    Si se envían ``items``, reemplazan por completo a los anteriores. Activar la
    BOM (o cambiar su producto/versión estando activa) vuelve a comprobar que el
    producto siga activo y que no exista otra versión vigente.
    """
    changes = data.model_dump(exclude_unset=True)
    # ``model_dump`` convierte los esquemas anidados en dicts; conservamos los
    # objetos ``BOMItemCreate`` originales para validarlos y construir las filas.
    new_items = data.items
    try:
        with _atomic(db):
            bom = _get_row(
                db, BillOfMaterials, bom_id, label="BOM", for_update=True
            )
            new_code = changes.get("code", bom.code)
            new_product_id = changes.get("product_id", bom.product_id)
            new_version = changes.get("version", bom.version)
            new_is_active = changes.get("is_active", bom.is_active)

            if new_code != bom.code:
                _ensure_unique_bom_code(db, new_code, exclude_id=bom_id)

            product_locked = False
            if new_product_id != bom.product_id:
                _get_product(
                    db, new_product_id, require_active=True, for_update=True
                )
                product_locked = True

            if new_is_active:
                if not product_locked:
                    _get_product(db, new_product_id, require_active=True)
                _ensure_active_version_available(
                    db, new_product_id, new_version, exclude_id=bom_id
                )

            if new_items is not None:
                _ensure_components_exist(db, new_items)

            editable = ("code", "product_id", "version", "name", "is_active", "notes")
            for field in editable:
                if field in changes:
                    setattr(bom, field, changes[field])
            if new_items is not None:
                _sync_items(bom, new_items)
    except IntegrityError as exc:
        db.rollback()
        _ensure_unique_bom_code(db, changes.get("code", ""), exclude_id=bom_id)
        raise DuplicateResourceError(
            "No se pudo actualizar la BOM por conflicto de integridad"
        ) from exc
    db.refresh(bom)
    return bom


def deactivate_bom(db: Session, bom_id: int) -> BillOfMaterials:
    """Desactiva una BOM para permitir activar otra versión (spec §4.1).

    La operación es idempotente: desactivar una BOM ya inactiva no es un error.
    """
    with _atomic(db):
        bom = _get_row(db, BillOfMaterials, bom_id, label="BOM", for_update=True)
        bom.is_active = False
    db.refresh(bom)
    return bom


def activate_bom(db: Session, bom_id: int) -> BillOfMaterials:
    """Activa una BOM verificando producto activo, componentes y versión única.

    Tras ``deactivate_bom`` se puede activar una nueva versión (o reactivar la
    anterior) sin conflicto, porque la comprobación ignora las BOM inactivas.
    """
    with _atomic(db):
        bom = _get_row(db, BillOfMaterials, bom_id, label="BOM", for_update=True)
        if not bom.is_active:
            _get_product(
                db, bom.product_id, require_active=True, for_update=True
            )
            _ensure_active_version_available(
                db, bom.product_id, bom.version, exclude_id=bom_id
            )
            _ensure_bom_components_exist(db, bom_id)
            bom.is_active = True
    db.refresh(bom)
    return bom


# --------------------------------------------------------------------------- #
# Utilidades de órdenes de producción
# --------------------------------------------------------------------------- #


def _get_warehouse(db: Session, warehouse_id: int) -> Warehouse:
    """Obtiene un almacén de inventario o lanza ``ResourceNotFoundError``."""
    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise ResourceNotFoundError(
            f"Almacén {warehouse_id} no encontrado en inventario"
        )
    return warehouse


def _ensure_warehouses_different(source_id: int, destination_id: int) -> None:
    """Exige bodegas distintas, como en el esquema de entrada."""
    if source_id == destination_id:
        raise InvalidProductionOrderError(
            "La bodega de origen y la de destino deben ser distintas"
        )


def _ensure_positive_quantity(value: Decimal, *, field: str) -> Decimal:
    """Comprueba la cantidad en el servicio, aunque Pydantic ya la valide."""
    try:
        quantity = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidProductionOrderError(
            f"El campo '{field}' debe ser un decimal válido"
        ) from exc
    if not quantity.is_finite() or quantity <= 0:
        raise InvalidProductionOrderError(
            f"El campo '{field}' debe ser mayor que cero"
        )
    return quantity


def _ensure_non_negative_hours(value: Decimal, *, field: str) -> Decimal:
    """Rechaza horas negativas o no finitas en llamadas directas al servicio."""
    try:
        hours = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidProductionOrderError(
            f"El campo '{field}' debe ser un decimal válido"
        ) from exc
    if not hours.is_finite() or hours < 0:
        raise InvalidProductionOrderError(
            f"El campo '{field}' no puede ser negativo"
        )
    return hours


def _get_bom_for_order(db: Session, bom_id: int) -> BillOfMaterials:
    """Obtiene una BOM apta para producir: existente, activa y con ítems.

    La fila se bloquea para que una desactivación concurrente no deje una OP
    apoyada en una receta que deja de estar vigente (reglas 4 y 5).
    """
    stmt = (
        select(BillOfMaterials)
        .where(BillOfMaterials.id == bom_id)
        .options(selectinload(BillOfMaterials.items))
        .with_for_update()
    )
    bom = db.scalars(stmt).first()
    if bom is None:
        raise ResourceNotFoundError(f"BOM {bom_id} no encontrada")
    if not bom.is_active:
        raise InactiveBOMError(
            f"La BOM {bom_id} ('{bom.code}') está inactiva; no se puede usar "
            "en una orden de producción"
        )
    if not bom.items:
        raise InvalidBOMError(
            f"La BOM {bom_id} ('{bom.code}') no tiene componentes; "
            "no se puede usar en una orden de producción"
        )
    return bom


def _ensure_unique_order_code(
    db: Session, code: str, *, exclude_id: int | None = None
) -> None:
    """Verifica que el código de la OP no esté en uso."""
    stmt = select(ProductionOrder.id).where(ProductionOrder.code == code)
    if exclude_id is not None:
        stmt = stmt.where(ProductionOrder.id != exclude_id)
    if db.execute(stmt.limit(1)).first() is not None:
        raise DuplicateResourceError(
            f"Ya existe una orden de producción con el código '{code}'"
        )


def _lock_order_sequence(db: Session, year: int) -> None:
    """Serializa ``OP-YYYY-XXXX`` en PostgreSQL; en SQLite basta el índice único."""
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        db.execute(select(func.pg_advisory_xact_lock(_ORDER_CODE_LOCK_BASE + year)))


def _next_order_code(db: Session, year: int) -> str:
    """Devuelve el siguiente código ``OP-YYYY-XXXX`` para el año indicado."""
    prefix = f"OP-{year}-"
    rows = db.scalars(
        select(ProductionOrder.code).where(ProductionOrder.code.like(f"{prefix}%"))
    ).all()
    max_sequence = 0
    for code in rows:
        suffix = code[len(prefix) :]
        if suffix.isdigit():
            max_sequence = max(max_sequence, int(suffix))
    return f"{prefix}{max_sequence + 1:04d}"


def _get_order_row(
    db: Session, order_id: int, *, for_update: bool = False
) -> ProductionOrder:
    """Obtiene una OP por id o lanza ``ResourceNotFoundError``."""
    stmt = select(ProductionOrder).where(ProductionOrder.id == order_id)
    if for_update:
        stmt = stmt.with_for_update()
    order = db.scalars(stmt).first()
    if order is None:
        raise ResourceNotFoundError(
            f"Orden de producción {order_id} no encontrada"
        )
    return order


def _ensure_mutable_order(order: ProductionOrder) -> None:
    """Bloquea cualquier cambio sobre una OP cerrada (regla 4, escenario 3)."""
    if order.status in _CLOSED_ORDER_STATUSES:
        raise ImmutableProductionOrderError(
            f"La orden '{order.code}' está {order.status.value} y es inmutable; "
            "no se puede modificar ni reabrir"
        )


# --------------------------------------------------------------------------- #
# Órdenes de producción — /api/v1/manufacturing/orders
# --------------------------------------------------------------------------- #


def create_production_order(
    db: Session, data: ProductionOrderCreate
) -> ProductionOrder:
    """Crea una OP en ``PLANNED`` validando BOM, bodegas y cantidad (regla 5).

    Si ``code`` se omite se genera ``OP-YYYY-XXXX`` bajo un advisory lock en
    PostgreSQL. La BOM se bloquea con ``FOR UPDATE`` para no crear órdenes sobre
    una receta que se esté desactivando. Cualquier rechazo revierte la
    transacción, de modo que no quedan órdenes huérfanas.
    """
    code = data.code
    try:
        with _atomic(db):
            year = datetime.now(timezone.utc).year
            if code is None:
                _lock_order_sequence(db, year)
                code = _next_order_code(db, year)
            _ensure_unique_order_code(db, code)
            _ensure_positive_quantity(
                data.quantity_to_produce, field="quantity_to_produce"
            )
            estimated_hours = _ensure_non_negative_hours(
                data.estimated_hours, field="estimated_hours"
            )
            _get_bom_for_order(db, data.bom_id)
            _get_warehouse(db, data.warehouse_source_id)
            _get_warehouse(db, data.warehouse_destination_id)
            _ensure_warehouses_different(
                data.warehouse_source_id, data.warehouse_destination_id
            )
            if data.work_center_id is not None:
                get_work_center(db, data.work_center_id)

            order = ProductionOrder(
                code=code,
                bom_id=data.bom_id,
                work_center_id=data.work_center_id,
                warehouse_source_id=data.warehouse_source_id,
                warehouse_destination_id=data.warehouse_destination_id,
                quantity_to_produce=data.quantity_to_produce,
                quantity_produced=Decimal("0.00"),
                estimated_hours=estimated_hours,
                actual_hours=Decimal("0.00"),
                status=ProductionOrderStatus.PLANNED,
            )
            db.add(order)
    except IntegrityError as exc:
        db.rollback()
        _ensure_unique_order_code(db, code or "")
        raise DuplicateResourceError(
            "No se pudo crear la orden de producción por conflicto de integridad"
        ) from exc
    db.refresh(order)
    return order


def get_production_order(db: Session, order_id: int) -> ProductionOrder:
    """Obtiene el detalle de una OP con BOM, componentes, centro y bodegas."""
    stmt = (
        select(ProductionOrder)
        .where(ProductionOrder.id == order_id)
        .options(
            selectinload(ProductionOrder.bom).selectinload(BillOfMaterials.items),
            selectinload(ProductionOrder.work_center),
            selectinload(ProductionOrder.warehouse_source),
            selectinload(ProductionOrder.warehouse_destination),
        )
    )
    order = db.scalars(stmt).first()
    if order is None:
        raise ResourceNotFoundError(
            f"Orden de producción {order_id} no encontrada"
        )
    return order


def list_production_orders(
    db: Session,
    *,
    status: ProductionOrderStatus | str | None = None,
    bom_id: int | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[ProductionOrder]:
    """Lista OPs con filtros opcionales por estado y BOM (spec §4.3)."""
    stmt = select(ProductionOrder)
    if status is not None:
        try:
            status = ProductionOrderStatus(status)
        except ValueError as exc:
            raise InvalidProductionOrderError(
                f"Estado '{status}' no válido para una orden de producción"
            ) from exc
        stmt = stmt.where(ProductionOrder.status == status)
    if bom_id is not None:
        stmt = stmt.where(ProductionOrder.bom_id == bom_id)
    stmt = (
        stmt.options(selectinload(ProductionOrder.bom))
        .order_by(ProductionOrder.id)
        .offset(skip)
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def update_production_order(
    db: Session, order_id: int, data: ProductionOrderUpdate
) -> ProductionOrder:
    """Actualiza campos de planificación de una OP abierta.

    El guardia de inmutabilidad se aplica antes de tocar ningún campo: una OP
    ``COMPLETED``/``CANCELLED`` siempre responde 409, aunque el PATCH sea
    válido. No se puede cambiar ``bom_id`` ni ``status``: son fijos o se
    alcanzan mediante transiciones (reglas 4 y 6).
    """
    changes = data.model_dump(exclude_unset=True)
    try:
        with _atomic(db):
            order = _get_order_row(db, order_id, for_update=True)
            _ensure_mutable_order(order)

            if "quantity_to_produce" in changes:
                _ensure_positive_quantity(
                    changes["quantity_to_produce"], field="quantity_to_produce"
                )
            if "estimated_hours" in changes:
                _ensure_non_negative_hours(
                    changes["estimated_hours"], field="estimated_hours"
                )

            new_source = changes.get("warehouse_source_id")
            new_destination = changes.get("warehouse_destination_id")
            source_id = (
                new_source if new_source is not None else order.warehouse_source_id
            )
            destination_id = (
                new_destination
                if new_destination is not None
                else order.warehouse_destination_id
            )
            _ensure_warehouses_different(source_id, destination_id)
            if new_source is not None:
                _get_warehouse(db, new_source)
            if new_destination is not None:
                _get_warehouse(db, new_destination)

            if "work_center_id" in data.model_fields_set:
                new_work_center = data.work_center_id
                if (
                    new_work_center is not None
                    and new_work_center != order.work_center_id
                ):
                    get_work_center(db, new_work_center)

            editable = (
                "quantity_to_produce",
                "estimated_hours",
                "warehouse_source_id",
                "warehouse_destination_id",
            )
            for field in editable:
                if field in changes:
                    setattr(order, field, changes[field])
            if "work_center_id" in data.model_fields_set:
                order.work_center_id = data.work_center_id
    except IntegrityError as exc:
        db.rollback()
        raise InvalidProductionOrderError(
            "No se pudo actualizar la orden de producción"
        ) from exc
    db.refresh(order)
    return order


def ensure_production_order_mutable(
    db: Session, order_id: int
) -> ProductionOrder:
    """Obtiene la OP bloqueada y rechaza las cerradas; guardia de transiciones.

    No hace commit: está pensado para invocarse dentro de la transacción que
    después iniciará, completará o cancelará la orden (reglas 4 y 6).
    """
    order = _get_order_row(db, order_id, for_update=True)
    _ensure_mutable_order(order)
    return order


def cancel_production_order(db: Session, order_id: int) -> ProductionOrder:
    """Cancela una OP ``PLANNED``; las cerradas se rechazan por inmutables.

    Cancelar desde ``IN_PROGRESS`` exigiría revertir los insumos ya descontados
    en ``inventory`` (regla 6), integración que se implementa en el siguiente
    hito junto con ``start``/``complete``.
    """
    with _atomic(db):
        order = ensure_production_order_mutable(db, order_id)
        if order.status is not ProductionOrderStatus.PLANNED:
            raise InvalidProductionOrderError(
                f"No se puede cancelar la orden '{order.code}' desde "
                f"{order.status.value} sin revertir los insumos consumidos"
            )
        order.status = ProductionOrderStatus.CANCELLED
    db.refresh(order)
    return order
