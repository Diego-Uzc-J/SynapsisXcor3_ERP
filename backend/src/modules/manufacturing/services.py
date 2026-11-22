"""Servicios de dominio del módulo de Manufactura y Producción.

Implementa la lógica de los centros de trabajo y las listas de materiales
descrita en ``specs/manufacturing_spec.md`` (secciones 2.1 a 2.3, 3.5 y 4.1/4.2).

* **Centros de trabajo:** alta con ``code`` único, listado filtrable por estado
  y actualización parcial conservando la unicidad del código.
* **BOM:** alta exigiendo que el producto terminado exista y esté activo en
  ``inventory``, que todos los componentes existan, que el ``code`` no esté en
  uso y que no haya otra BOM activa para el mismo ``product_id``/``version``
  (regla 5 y escenario 4).
* **Ciclo de versión:** desactivar una BOM y activar otra (la misma versión tras
  desactivar la anterior o una nueva versión) con las comprobaciones de estado
  vigente, producto activo y componentes disponibles.

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
from typing import TypeVar

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.modules.inventory.models import Product
from src.modules.manufacturing.models import BOMItem, BillOfMaterials, WorkCenter
from src.modules.manufacturing.schemas import (
    BOMCreate,
    BOMItemCreate,
    BOMUpdate,
    WorkCenterCreate,
    WorkCenterUpdate,
)

__all__ = [
    "DuplicateResourceError",
    "InactiveProductError",
    "InvalidBOMError",
    "ManufacturingServiceError",
    "ResourceNotFoundError",
    "activate_bom",
    "create_bom",
    "create_work_center",
    "deactivate_bom",
    "get_bom",
    "get_work_center",
    "list_boms",
    "list_work_centers",
    "update_bom",
    "update_work_center",
]


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
