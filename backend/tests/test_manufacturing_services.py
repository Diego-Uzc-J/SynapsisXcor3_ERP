"""Pruebas unitarias de los servicios de manufactura.

Cubren las reglas implementadas en ``manufacturing.services`` derivadas de
``specs/manufacturing_spec.md``:

* unicidad del ``code`` de centros de trabajo (alta y actualización) y filtro
  por estado;
* alta de BOM con producto terminado activo y componentes existentes;
* conflicto de ``code`` duplicado y de BOM activa por ``product_id``/``version``
  (regla 5 y escenario 4), permitiendo BOM inactivas duplicadas;
* desactivación y activación controlada de versiones;
* reemplazo de componentes mediante PATCH y atomicidad de los rechazos;
* alta de OP en ``PLANNED`` con BOM activa y con componentes, bodegas existentes
  y cantidad positiva (reglas 5 y 6, escenario 6);
* detalle y listado de OPs con filtros por ``status``/``bom_id``;
* inmutabilidad de OPs ``COMPLETED``/``CANCELLED`` (regla 4, escenario 3) y
  cancelación desde ``PLANNED``;
* inicio atómico ``PLANNED → IN_PROGRESS`` con requerimientos por BOM y merma,
  movimientos ``OUTBOUND``, déficit sin descuento parcial y rollback completo
  ante errores de ``inventory`` (reglas 1 y 2, escenarios 1 y 2).

Se usa SQLite en memoria, igual que el resto de la suite de servicios.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite://")

from src.core.database import Base  # noqa: E402
from src.modules.inventory import services as inventory_services  # noqa: E402
from src.modules.inventory.models import (  # noqa: E402
    MovementType,
    Product,
    Stock,
    StockMovement,
    Warehouse,
)
from src.modules.manufacturing.models import (  # noqa: E402
    BOMItem,
    BillOfMaterials,
    ProductionOrder,
    ProductionOrderStatus,
    WorkCenter,
)
from src.modules.manufacturing.schemas import (  # noqa: E402
    BOMCreate,
    BOMUpdate,
    ProductionOrderCreate,
    ProductionOrderStart,
    ProductionOrderUpdate,
    WorkCenterCreate,
    WorkCenterUpdate,
)
from src.modules.manufacturing.services import (  # noqa: E402
    DuplicateResourceError,
    ImmutableProductionOrderError,
    InactiveBOMError,
    InactiveProductError,
    InsufficientComponentStockError,
    InvalidBOMError,
    InvalidProductionOrderError,
    ResourceNotFoundError,
    activate_bom,
    cancel_production_order,
    create_bom,
    create_production_order,
    create_work_center,
    deactivate_bom,
    ensure_production_order_mutable,
    get_bom,
    get_production_order,
    list_boms,
    list_production_orders,
    list_work_centers,
    start_production_order,
    update_bom,
    update_production_order,
    update_work_center,
)


@pytest.fixture()
def db_session() -> Session:
    """Sesión SQLite aislada con inventario y manufactura creados desde ``Base``."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add_all(
            [
                Product(
                    sku="LAP-IND-001",
                    name="Laptop Industrial",
                    unit_price=Decimal("1899.90"),
                    is_active=True,
                ),
                Product(
                    sku="CHASIS-001",
                    name="Chasis",
                    unit_price=Decimal("100.00"),
                    is_active=True,
                ),
                Product(
                    sku="MB-001",
                    name="Tarjeta Madre",
                    unit_price=Decimal("250.00"),
                    is_active=True,
                ),
                Product(
                    sku="OBSOLETO-001",
                    name="Producto obsoleto",
                    unit_price=Decimal("1.00"),
                    is_active=False,
                ),
                Warehouse(code="WHS-INSUMOS", name="Bodega de insumos"),
                Warehouse(code="WHS-PT", name="Bodega de producto terminado"),
                Warehouse(code="WHS-EXTRA", name="Bodega auxiliar"),
            ]
        )
        session.commit()
        session.add_all(
            [
                Stock(
                    product_id=product_id(session, "CHASIS-001"),
                    warehouse_id=warehouse_id(session, "WHS-INSUMOS"),
                    quantity=50,
                ),
                Stock(
                    product_id=product_id(session, "MB-001"),
                    warehouse_id=warehouse_id(session, "WHS-INSUMOS"),
                    quantity=40,
                ),
            ]
        )
        session.commit()
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def product_id(db: Session, sku: str) -> int:
    """Devuelve el id de un producto sembrado en la fixture."""
    return int(db.scalars(select(Product.id).where(Product.sku == sku)).one())


def count(db: Session, model: type) -> int:
    """Cuenta filas de un modelo para comprobar atomicidad."""
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def work_center_payload(**overrides: Any) -> WorkCenterCreate:
    """Centro de trabajo válido con coste decimal."""
    values: dict[str, Any] = {
        "code": "WC-ENSAMBLE-01",
        "name": "Línea de ensamble A",
        "cost_per_hour": Decimal("150.00"),
        "is_active": True,
    }
    values.update(overrides)
    return WorkCenterCreate(**values)


def bom_payload(
    db: Session,
    *,
    code: str = "BOM-LAP-IND-01",
    version: int = 1,
    is_active: bool = True,
    component_ids: list[int] | None = None,
    scrap_percentages: dict[str, Decimal] | None = None,
) -> BOMCreate:
    """BOM válida para la laptop industrial con dos componentes."""
    if component_ids is None:
        component_ids = [
            product_id(db, "CHASIS-001"),
            product_id(db, "MB-001"),
        ]
    scraps = scrap_percentages or {}
    sku_by_id = {
        product_id(db, "CHASIS-001"): "CHASIS-001",
        product_id(db, "MB-001"): "MB-001",
    }
    items: list[dict[str, Any]] = []
    for pid in component_ids:
        item: dict[str, Any] = {
            "component_product_id": pid,
            "quantity": Decimal("1.00"),
        }
        if sku_by_id.get(pid) in scraps:
            item["scrap_percentage"] = scraps[sku_by_id[pid]]
        items.append(item)
    return BOMCreate(
        code=code,
        product_id=product_id(db, "LAP-IND-001"),
        version=version,
        name="BOM industrial",
        is_active=is_active,
        items=items,
    )


def warehouse_id(db: Session, code: str) -> int:
    """Devuelve el id de una bodega sembrada en la fixture."""
    return int(db.scalars(select(Warehouse.id).where(Warehouse.code == code)).one())


def stock_quantity(db: Session, sku: str, warehouse_code: str) -> int:
    """Devuelve el saldo de un SKU en una bodega de la fixture."""
    value = db.scalar(
        select(Stock.quantity).where(
            Stock.product_id == product_id(db, sku),
            Stock.warehouse_id == warehouse_id(db, warehouse_code),
        )
    )
    return int(value or 0)


def set_stock(db: Session, sku: str, warehouse_code: str, quantity: int) -> None:
    """Ajusta el saldo de un componente para preparar un escenario."""
    db.execute(
        update(Stock)
        .where(
            Stock.product_id == product_id(db, sku),
            Stock.warehouse_id == warehouse_id(db, warehouse_code),
        )
        .values(quantity=quantity)
    )
    db.commit()


def order_payload(db: Session, **overrides: Any) -> ProductionOrderCreate:
    """OP válida; el llamador indica siempre el ``bom_id`` a referenciar."""
    values: dict[str, Any] = {
        "warehouse_source_id": warehouse_id(db, "WHS-INSUMOS"),
        "warehouse_destination_id": warehouse_id(db, "WHS-PT"),
        "quantity_to_produce": Decimal("10.00"),
        "estimated_hours": Decimal("0.00"),
    }
    values.update(overrides)
    return ProductionOrderCreate(**values)


# --------------------------------------------------------------------------- #
# Centros de trabajo
# --------------------------------------------------------------------------- #


def test_create_and_list_work_centers(db_session: Session) -> None:
    active = create_work_center(db_session, work_center_payload())
    inactive = create_work_center(
        db_session,
        work_center_payload(code="WC-PINTURA-02", name="Pintura", is_active=False),
    )

    assert active.id is not None
    assert active.is_active is True
    assert active.cost_per_hour == Decimal("150.00")
    assert [item.id for item in list_work_centers(db_session)] == [active.id]
    assert [item.id for item in list_work_centers(db_session, is_active=None)] == [
        active.id,
        inactive.id,
    ]
    assert [item.id for item in list_work_centers(db_session, is_active=False)] == [
        inactive.id
    ]


def test_work_center_code_is_unique_on_create_and_update(db_session: Session) -> None:
    first = create_work_center(db_session, work_center_payload())

    with pytest.raises(DuplicateResourceError, match="WC-ENSAMBLE-01"):
        create_work_center(db_session, work_center_payload(name="Otra línea"))

    other = create_work_center(db_session, work_center_payload(code="WC-CORTE-03"))
    with pytest.raises(DuplicateResourceError, match="WC-ENSAMBLE-01"):
        update_work_center(db_session, other.id, WorkCenterUpdate(code=first.code))

    updated = update_work_center(
        db_session,
        other.id,
        WorkCenterUpdate(name="Corte láser", cost_per_hour=Decimal("200.50")),
    )
    assert updated.name == "Corte láser"
    assert updated.cost_per_hour == Decimal("200.50")
    assert count(db_session, WorkCenter) == 2


# --------------------------------------------------------------------------- #
# BOM
# --------------------------------------------------------------------------- #


def test_create_bom_persists_items_with_decimal_quantities(db_session: Session) -> None:
    bom = create_bom(db_session, bom_payload(db_session))

    assert bom.id is not None
    assert bom.is_active is True
    assert len(get_bom(db_session, bom.id).items) == 2
    assert all(isinstance(item.quantity, Decimal) for item in bom.items)
    assert all(
        isinstance(item.scrap_percentage, Decimal) for item in bom.items
    )
    assert [item.bom_id for item in bom.items] == [bom.id, bom.id]


def test_create_bom_requires_active_finished_product(db_session: Session) -> None:
    with pytest.raises(ResourceNotFoundError, match="Producto 9999"):
        create_bom(
            db_session,
            BOMCreate(
                code="BOM-INEXISTENTE",
                product_id=9999,
                items=[
                    {
                        "component_product_id": product_id(db_session, "CHASIS-001"),
                        "quantity": Decimal("1.00"),
                    }
                ],
            ),
        )

    with pytest.raises(InactiveProductError, match="inactivo"):
        create_bom(
            db_session,
            BOMCreate(
                code="BOM-OBSOLETO",
                product_id=product_id(db_session, "OBSOLETO-001"),
                items=[
                    {
                        "component_product_id": product_id(db_session, "CHASIS-001"),
                        "quantity": Decimal("1.00"),
                    }
                ],
            ),
        )
    assert count(db_session, BillOfMaterials) == 0


def test_create_bom_with_unknown_component_is_rejected_atomically(
    db_session: Session,
) -> None:
    payload = bom_payload(db_session, code="BOM-COMPONENTE-FANTASMA")
    payload.items[1].component_product_id = 9999

    with pytest.raises(ResourceNotFoundError, match="9999"):
        create_bom(db_session, payload)

    assert count(db_session, BillOfMaterials) == 0
    assert count(db_session, BOMItem) == 0


def test_create_bom_rejects_duplicate_code_and_active_version(
    db_session: Session,
) -> None:
    first = create_bom(db_session, bom_payload(db_session))

    with pytest.raises(DuplicateResourceError, match="código"):
        create_bom(db_session, bom_payload(db_session, code=first.code, version=2))

    with pytest.raises(DuplicateResourceError, match="BOM activa"):
        create_bom(db_session, bom_payload(db_session, code="BOM-OTRA-V1"))

    # Una BOM inactiva para la misma versión sí es admitida: podrá activarse
    # después de desactivar la vigente.
    inactive = create_bom(
        db_session,
        bom_payload(db_session, code="BOM-INACTIVA-V1", is_active=False),
    )
    assert inactive.is_active is False
    assert count(db_session, BillOfMaterials) == 2
    active_boms = list_boms(
        db_session, product_id=inactive.product_id, is_active=True
    )
    assert len(active_boms) == 1


def test_deactivate_then_activate_bom_versions(db_session: Session) -> None:
    old = create_bom(db_session, bom_payload(db_session))
    deactivated = deactivate_bom(db_session, old.id)
    assert deactivated.is_active is False

    new = create_bom(db_session, bom_payload(db_session, code="BOM-LAP-IND-01-V2"))
    assert new.is_active is True

    # Otra versión distinta puede estar activa a la vez.
    newer = create_bom(
        db_session,
        bom_payload(db_session, code="BOM-LAP-IND-01-V3", version=2),
    )
    assert newer.is_active is True

    # Reactivar la v1 original chocaría con la nueva v1 activa.
    with pytest.raises(DuplicateResourceError, match="BOM activa"):
        activate_bom(db_session, old.id)

    deactivate_bom(db_session, new.id)
    reactivated = activate_bom(db_session, old.id)
    assert reactivated.is_active is True
    assert reactivated.id == old.id


def test_update_bom_replaces_items_and_can_activate(db_session: Session) -> None:
    bom = create_bom(
        db_session,
        bom_payload(db_session, code="BOM-BORRADOR", is_active=False),
    )
    only_chassis = product_id(db_session, "CHASIS-001")

    updated = update_bom(
        db_session,
        bom.id,
        BOMUpdate(
            name="Receta definitiva",
            is_active=True,
            items=[
                {
                    "component_product_id": only_chassis,
                    "quantity": Decimal("2.00"),
                    "scrap_percentage": Decimal("5.00"),
                }
            ],
        ),
    )

    assert updated.is_active is True
    assert updated.name == "Receta definitiva"
    assert len(get_bom(db_session, bom.id).items) == 1
    item = get_bom(db_session, bom.id).items[0]
    assert item.component_product_id == only_chassis
    assert item.quantity == Decimal("2.00")
    assert item.scrap_percentage == Decimal("5.00")


def test_activate_bom_validates_product_and_components(db_session: Session) -> None:
    bom = create_bom(
        db_session,
        bom_payload(db_session, code="BOM-REACTIVAR", is_active=False),
    )

    product = db_session.get(Product, bom.product_id)
    assert product is not None
    product.is_active = False
    db_session.commit()

    with pytest.raises(InactiveProductError, match="inactivo"):
        activate_bom(db_session, bom.id)

    product.is_active = True
    db_session.commit()
    db_session.execute(delete(BOMItem).where(BOMItem.bom_id == bom.id))
    db_session.commit()

    with pytest.raises(InvalidBOMError, match="al menos un componente"):
        activate_bom(db_session, bom.id)
    assert get_bom(db_session, bom.id).is_active is False


# --------------------------------------------------------------------------- #
# Órdenes de producción
# --------------------------------------------------------------------------- #


def test_create_production_order_starts_planned(db_session: Session) -> None:
    bom = create_bom(db_session, bom_payload(db_session))

    order = create_production_order(
        db_session, order_payload(db_session, bom_id=bom.id)
    )

    assert order.id is not None
    assert order.status is ProductionOrderStatus.PLANNED
    assert order.code.startswith(f"OP-{datetime.now(timezone.utc).year}-")
    assert order.quantity_to_produce == Decimal("10.00")
    assert order.quantity_produced == Decimal("0.00")
    assert order.estimated_hours == Decimal("0.00")
    assert order.actual_hours == Decimal("0.00")
    assert order.unit_production_cost is None
    assert count(db_session, ProductionOrder) == 1


def test_create_production_order_rejects_inactive_bom(db_session: Session) -> None:
    bom = create_bom(db_session, bom_payload(db_session, is_active=False))

    with pytest.raises(InactiveBOMError, match="inactiva"):
        create_production_order(db_session, order_payload(db_session, bom_id=bom.id))

    assert count(db_session, ProductionOrder) == 0


def test_create_production_order_rejects_bom_without_items(
    db_session: Session,
) -> None:
    bom = create_bom(db_session, bom_payload(db_session))
    db_session.execute(delete(BOMItem).where(BOMItem.bom_id == bom.id))
    db_session.commit()

    with pytest.raises(InvalidBOMError, match="componentes"):
        create_production_order(db_session, order_payload(db_session, bom_id=bom.id))

    assert count(db_session, ProductionOrder) == 0


@pytest.mark.parametrize("quantity", ["0", "-1"])
def test_create_production_order_rejects_non_positive_quantity(
    db_session: Session, quantity: str
) -> None:
    bom = create_bom(db_session, bom_payload(db_session))
    # ``model_construct`` evita el validador de Pydantic para comprobar que la
    # regla también se aplica en la capa de servicio.
    payload = ProductionOrderCreate.model_construct(
        bom_id=bom.id,
        warehouse_source_id=warehouse_id(db_session, "WHS-INSUMOS"),
        warehouse_destination_id=warehouse_id(db_session, "WHS-PT"),
        quantity_to_produce=Decimal(quantity),
        estimated_hours=Decimal("0.00"),
        code=None,
        work_center_id=None,
    )

    with pytest.raises(InvalidProductionOrderError, match="mayor que cero"):
        create_production_order(db_session, payload)

    assert count(db_session, ProductionOrder) == 0


def test_create_production_order_rejects_unknown_references(
    db_session: Session,
) -> None:
    bom = create_bom(db_session, bom_payload(db_session))

    with pytest.raises(ResourceNotFoundError, match="BOM 9999"):
        create_production_order(db_session, order_payload(db_session, bom_id=9999))

    with pytest.raises(ResourceNotFoundError, match="Almacén 9999"):
        create_production_order(
            db_session,
            order_payload(db_session, bom_id=bom.id, warehouse_source_id=9999),
        )

    with pytest.raises(ResourceNotFoundError, match="Almacén 9998"):
        create_production_order(
            db_session,
            order_payload(db_session, bom_id=bom.id, warehouse_destination_id=9998),
        )

    with pytest.raises(ResourceNotFoundError, match="Centro de trabajo 9997"):
        create_production_order(
            db_session,
            order_payload(db_session, bom_id=bom.id, work_center_id=9997),
        )

    same_warehouse = warehouse_id(db_session, "WHS-INSUMOS")
    payload = ProductionOrderCreate.model_construct(
        bom_id=bom.id,
        warehouse_source_id=same_warehouse,
        warehouse_destination_id=same_warehouse,
        quantity_to_produce=Decimal("10.00"),
        estimated_hours=Decimal("0.00"),
        code=None,
        work_center_id=None,
    )
    with pytest.raises(InvalidProductionOrderError, match="distintas"):
        create_production_order(db_session, payload)

    assert count(db_session, ProductionOrder) == 0


def test_create_production_order_rejects_duplicate_code(db_session: Session) -> None:
    bom = create_bom(db_session, bom_payload(db_session))
    first = create_production_order(
        db_session,
        order_payload(db_session, bom_id=bom.id, code="OP-2026-0001"),
    )

    with pytest.raises(DuplicateResourceError, match="OP-2026-0001"):
        create_production_order(
            db_session,
            order_payload(db_session, bom_id=bom.id, code=first.code),
        )

    assert count(db_session, ProductionOrder) == 1


def test_get_and_list_production_orders(db_session: Session) -> None:
    first_bom = create_bom(db_session, bom_payload(db_session, code="BOM-OP-1"))
    second_bom = create_bom(
        db_session,
        bom_payload(db_session, code="BOM-OP-2", version=2),
    )
    work_center = create_work_center(db_session, work_center_payload())
    first = create_production_order(
        db_session,
        order_payload(db_session, bom_id=first_bom.id, work_center_id=work_center.id),
    )
    second = create_production_order(
        db_session,
        order_payload(db_session, bom_id=second_bom.id, code="OP-2026-0002"),
    )

    detail = get_production_order(db_session, first.id)
    assert detail.bom.id == first_bom.id
    assert len(detail.bom.items) == 2
    assert detail.work_center is not None
    assert detail.work_center.id == work_center.id
    assert detail.warehouse_source.code == "WHS-INSUMOS"
    assert detail.warehouse_destination.code == "WHS-PT"

    assert [order.id for order in list_production_orders(db_session)] == [
        first.id,
        second.id,
    ]
    assert [
        order.id for order in list_production_orders(db_session, bom_id=second_bom.id)
    ] == [second.id]
    assert [
        order.id
        for order in list_production_orders(
            db_session, status=ProductionOrderStatus.PLANNED
        )
    ] == [first.id, second.id]
    assert list_production_orders(db_session, status="COMPLETED") == []
    assert list_production_orders(db_session, skip=1, limit=1)[0].id == second.id

    with pytest.raises(InvalidProductionOrderError, match="no válido"):
        list_production_orders(db_session, status="EN_CURSO")
    with pytest.raises(ResourceNotFoundError, match="9999"):
        get_production_order(db_session, 9999)


def test_update_production_order_validates_plan_changes(db_session: Session) -> None:
    bom = create_bom(db_session, bom_payload(db_session))
    work_center = create_work_center(db_session, work_center_payload())
    order = create_production_order(
        db_session,
        order_payload(db_session, bom_id=bom.id, work_center_id=work_center.id),
    )

    updated = update_production_order(
        db_session,
        order.id,
        ProductionOrderUpdate(
            quantity_to_produce=Decimal("20.00"),
            estimated_hours=Decimal("3.50"),
            work_center_id=None,
        ),
    )
    assert updated.quantity_to_produce == Decimal("20.00")
    assert updated.estimated_hours == Decimal("3.50")
    assert updated.work_center_id is None

    with pytest.raises(InvalidProductionOrderError, match="distintas"):
        update_production_order(
            db_session,
            order.id,
            ProductionOrderUpdate(
                warehouse_source_id=order.warehouse_destination_id
            ),
        )
    with pytest.raises(ResourceNotFoundError, match="Almacén 9999"):
        update_production_order(
            db_session,
            order.id,
            ProductionOrderUpdate(warehouse_destination_id=9999),
        )
    with pytest.raises(ResourceNotFoundError, match="Centro de trabajo 9997"):
        update_production_order(
            db_session,
            order.id,
            ProductionOrderUpdate(work_center_id=9997),
        )

    with pytest.raises(ValidationError):
        ProductionOrderUpdate(code="OP-OTRO")
    with pytest.raises(ValidationError):
        ProductionOrderUpdate(status=ProductionOrderStatus.CANCELLED)
    assert get_production_order(db_session, order.id).code == order.code


@pytest.mark.parametrize(
    "status", [ProductionOrderStatus.COMPLETED, ProductionOrderStatus.CANCELLED]
)
def test_closed_orders_are_immutable(
    db_session: Session, status: ProductionOrderStatus
) -> None:
    bom = create_bom(db_session, bom_payload(db_session))
    order = create_production_order(
        db_session, order_payload(db_session, bom_id=bom.id)
    )
    order.status = status
    db_session.commit()

    with pytest.raises(ImmutableProductionOrderError, match="inmutable"):
        update_production_order(
            db_session,
            order.id,
            ProductionOrderUpdate(quantity_to_produce=Decimal("99.00")),
        )
    with pytest.raises(ImmutableProductionOrderError, match="inmutable"):
        cancel_production_order(db_session, order.id)
    with pytest.raises(ImmutableProductionOrderError, match="inmutable"):
        ensure_production_order_mutable(db_session, order.id)

    unchanged = get_production_order(db_session, order.id)
    assert unchanged.status is status
    assert unchanged.quantity_to_produce == Decimal("10.00")


def test_cancel_production_order_from_planned(db_session: Session) -> None:
    bom = create_bom(db_session, bom_payload(db_session))
    order = create_production_order(
        db_session, order_payload(db_session, bom_id=bom.id)
    )

    cancelled = cancel_production_order(db_session, order.id)

    assert cancelled.status is ProductionOrderStatus.CANCELLED
    assert get_production_order(db_session, order.id).status is (
        ProductionOrderStatus.CANCELLED
    )
    with pytest.raises(ImmutableProductionOrderError, match="inmutable"):
        cancel_production_order(db_session, order.id)


def test_cancel_in_progress_order_requires_stock_reversal(
    db_session: Session,
) -> None:
    bom = create_bom(db_session, bom_payload(db_session))
    order = create_production_order(
        db_session, order_payload(db_session, bom_id=bom.id)
    )
    order.status = ProductionOrderStatus.IN_PROGRESS
    db_session.commit()

    with pytest.raises(InvalidProductionOrderError, match="revertir"):
        cancel_production_order(db_session, order.id)

    assert get_production_order(db_session, order.id).status is (
        ProductionOrderStatus.IN_PROGRESS
    )


# --------------------------------------------------------------------------- #
# Inicio de producción (PLANNED -> IN_PROGRESS)
# --------------------------------------------------------------------------- #


def test_start_production_order_consumes_stock_with_scrap(
    db_session: Session,
) -> None:
    bom = create_bom(
        db_session,
        bom_payload(db_session, scrap_percentages={"MB-001": Decimal("5.00")}),
    )
    order = create_production_order(
        db_session, order_payload(db_session, bom_id=bom.id)
    )
    started_at = date(2026, 11, 22)

    started = start_production_order(
        db_session, order.id, ProductionOrderStart(started_at=started_at)
    )

    assert started.status is ProductionOrderStatus.IN_PROGRESS
    assert started.started_at == started_at
    # 1 * 10 = 10; 1 * 1.05 * 10 = 10.5 -> 11 (redondeo por exceso).
    assert stock_quantity(db_session, "CHASIS-001", "WHS-INSUMOS") == 40
    assert stock_quantity(db_session, "MB-001", "WHS-INSUMOS") == 29

    movements = db_session.scalars(
        select(StockMovement).order_by(StockMovement.id)
    ).all()
    assert len(movements) == 2
    assert all(item.movement_type is MovementType.OUTBOUND for item in movements)
    assert all(
        item.warehouse_source_id == order.warehouse_source_id for item in movements
    )
    assert all(item.warehouse_destination_id is None for item in movements)
    assert [item.quantity for item in movements] == [10, 11]
    assert all(item.reference_document == order.code for item in movements)
    assert all(item.created_by == "manufacturing" for item in movements)
    assert "MB-001" in movements[1].notes


def test_start_production_order_defaults_started_at_to_today(
    db_session: Session,
) -> None:
    bom = create_bom(db_session, bom_payload(db_session))
    order = create_production_order(
        db_session, order_payload(db_session, bom_id=bom.id)
    )

    started = start_production_order(db_session, order.id)

    assert started.started_at == date.today()
    assert get_production_order(db_session, order.id).status is (
        ProductionOrderStatus.IN_PROGRESS
    )


def test_start_production_order_deficit_leaves_no_partial_discount(
    db_session: Session,
) -> None:
    bom = create_bom(db_session, bom_payload(db_session))
    order = create_production_order(
        db_session, order_payload(db_session, bom_id=bom.id)
    )
    set_stock(db_session, "CHASIS-001", "WHS-INSUMOS", 5)

    with pytest.raises(InsufficientComponentStockError) as excinfo:
        start_production_order(db_session, order.id)

    error = excinfo.value
    assert error.status_code == 400
    assert error.sku == "CHASIS-001"
    assert error.product_id == product_id(db_session, "CHASIS-001")
    assert (error.available, error.required, error.deficit) == (5, 10, 5)
    assert "CHASIS-001" in str(error)
    assert "déficit 5" in str(error)
    assert stock_quantity(db_session, "CHASIS-001", "WHS-INSUMOS") == 5
    assert stock_quantity(db_session, "MB-001", "WHS-INSUMOS") == 40
    assert count(db_session, StockMovement) == 0
    unchanged = get_production_order(db_session, order.id)
    assert unchanged.status is ProductionOrderStatus.PLANNED
    assert unchanged.started_at is None


def test_start_production_order_rolls_back_after_inventory_failure(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    bom = create_bom(db_session, bom_payload(db_session))
    order = create_production_order(
        db_session, order_payload(db_session, bom_id=bom.id)
    )
    set_stock(db_session, "CHASIS-001", "WHS-INSUMOS", 10)
    set_stock(db_session, "MB-001", "WHS-INSUMOS", 10)

    real_decrease = inventory_services._decrease
    calls = {"count": 0}

    def flaky_decrease(
        stock: Stock, quantity: int, *, allow_negative_stock: bool
    ) -> None:
        calls["count"] += 1
        if calls["count"] == 2:
            raise inventory_services.InsufficientStockError(
                product_id=stock.product_id,
                warehouse_id=stock.warehouse_id,
                available=stock.quantity,
                requested=quantity,
            )
        real_decrease(
            stock, quantity, allow_negative_stock=allow_negative_stock
        )

    monkeypatch.setattr(inventory_services, "_decrease", flaky_decrease)

    # El primer OUTBOUND llega a persistirse en la transacción antes de que el
    # segundo falle: el rollback de inventory debe anularlo también.
    with pytest.raises(InsufficientComponentStockError, match="MB-001"):
        start_production_order(db_session, order.id)

    assert calls["count"] == 2
    assert stock_quantity(db_session, "CHASIS-001", "WHS-INSUMOS") == 10
    assert stock_quantity(db_session, "MB-001", "WHS-INSUMOS") == 10
    assert count(db_session, StockMovement) == 0
    unchanged = get_production_order(db_session, order.id)
    assert unchanged.status is ProductionOrderStatus.PLANNED
    assert unchanged.started_at is None


def test_start_production_order_translates_generic_inventory_error(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    bom = create_bom(db_session, bom_payload(db_session))
    order = create_production_order(
        db_session, order_payload(db_session, bom_id=bom.id)
    )

    def failing_movement(db: Session, data: Any, **kwargs: Any) -> None:
        del data, kwargs
        db.rollback()
        raise inventory_services.InventoryError("fallo simulado de inventario")

    monkeypatch.setattr(
        inventory_services, "create_stock_movement", failing_movement
    )

    with pytest.raises(InvalidProductionOrderError, match="fallo simulado"):
        start_production_order(db_session, order.id)

    assert stock_quantity(db_session, "CHASIS-001", "WHS-INSUMOS") == 50
    assert stock_quantity(db_session, "MB-001", "WHS-INSUMOS") == 40
    assert count(db_session, StockMovement) == 0
    assert get_production_order(db_session, order.id).status is (
        ProductionOrderStatus.PLANNED
    )


@pytest.mark.parametrize(
    "status", [ProductionOrderStatus.COMPLETED, ProductionOrderStatus.CANCELLED]
)
def test_start_production_order_rejects_closed_orders(
    db_session: Session, status: ProductionOrderStatus
) -> None:
    bom = create_bom(db_session, bom_payload(db_session))
    order = create_production_order(
        db_session, order_payload(db_session, bom_id=bom.id)
    )
    order.status = status
    db_session.commit()

    with pytest.raises(ImmutableProductionOrderError, match="inmutable"):
        start_production_order(db_session, order.id)

    assert count(db_session, StockMovement) == 0
    assert stock_quantity(db_session, "CHASIS-001", "WHS-INSUMOS") == 50


def test_start_production_order_rejects_already_in_progress(
    db_session: Session,
) -> None:
    bom = create_bom(db_session, bom_payload(db_session))
    order = create_production_order(
        db_session, order_payload(db_session, bom_id=bom.id)
    )
    order.status = ProductionOrderStatus.IN_PROGRESS
    db_session.commit()

    with pytest.raises(InvalidProductionOrderError, match="PLANNED"):
        start_production_order(db_session, order.id)

    assert count(db_session, StockMovement) == 0
    assert stock_quantity(db_session, "CHASIS-001", "WHS-INSUMOS") == 50


def test_start_production_order_ignores_allow_negative_stock_env(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALLOW_NEGATIVE_STOCK", "true")
    bom = create_bom(db_session, bom_payload(db_session))
    order = create_production_order(
        db_session, order_payload(db_session, bom_id=bom.id)
    )
    seen: list[dict[str, Any]] = []
    real_movement = inventory_services.create_stock_movement

    def spy(db: Session, data: Any, **kwargs: Any) -> Any:
        seen.append(kwargs)
        return real_movement(db, data, **kwargs)

    monkeypatch.setattr(inventory_services, "create_stock_movement", spy)

    start_production_order(db_session, order.id, created_by="usuario-prueba")

    assert len(seen) == 2
    assert all(item["allow_negative_stock"] is False for item in seen)
    assert all(item["commit"] is False for item in seen)
    movements = db_session.scalars(select(StockMovement)).all()
    assert all(item.created_by == "usuario-prueba" for item in movements)
