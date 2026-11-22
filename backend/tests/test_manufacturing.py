"""Criterios de aceptación BDD de manufactura (spec §5).

Cada escenario se ejecuta contra una base SQLite en memoria aislada: la fixture
crea el esquema, siembra el mínimo inventario/contabilidad necesario y lo
destruye al finalizar. Las dependencias HTTP se sobreescriben con esa sesión y
se limpian después de cada prueba; los ``monkeypatch`` se revierten
automáticamente. Por tanto, la suite no deja datos residuales.

Los escenarios 1, 2, 5, 6, 7 y 8 se ejercitan por HTTP (``TestClient``). En el
escenario 3, la modificación de cantidades/bodegas se valida mediante el
servicio ``update_production_order`` porque el contrato §4.3 no expone un
``PATCH /orders/{id}``; las transiciones sí se comprueban por HTTP.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Generator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ["DATABASE_URL"] = "sqlite://"

from src.core.database import Base, get_db  # noqa: E402
from src.core.security import (  # noqa: E402
    FORBIDDEN_DETAIL,
    create_access_token,
    hash_password,
)
from src.main import app  # noqa: E402
from src.modules.accounting import service as accounting_service  # noqa: E402
from src.modules.accounting.models import (  # noqa: E402
    Account,
    AccountType,
    JournalEntry,
    JournalEntryStatus,
)
from src.modules.inventory import services as inventory_services  # noqa: E402
from src.modules.inventory.models import (  # noqa: E402
    MovementType,
    Product,
    Stock,
    StockMovement,
    Warehouse,
)
from src.modules.manufacturing.models import (  # noqa: E402
    ProductionOrder,
    ProductionOrderStatus,
)
from src.modules.manufacturing.schemas import ProductionOrderUpdate  # noqa: E402
from src.modules.manufacturing.services import (  # noqa: E402
    ImmutableProductionOrderError,
    update_production_order,
)
from src.modules.users.models import Role, RoleEnum, User  # noqa: E402

BASE_URL = "/api/v1/manufacturing"
_HASHED_PASSWORD = hash_password("Bdd1234567!")


# --------------------------------------------------------------------------- #
# Fixtures: base aislada, cliente HTTP y usuarios RBAC
# --------------------------------------------------------------------------- #


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    """Engine SQLite efímero con transacciones explícitas y teardown limpio."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _disable_implicit_begin(
        dbapi_connection: Any, _connection_record: Any
    ) -> None:
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _emit_begin(connection: Any) -> None:
        connection.exec_driver_sql("BEGIN")

    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def db_session(db_engine: Engine) -> Generator[Session, None, None]:
    """Datos mínimos: 2 insumos, 2 bodegas, cuentas PUC y stock inicial."""
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    with factory() as session:
        session.add_all(
            [
                Product(
                    sku="LAP-IND-001",
                    name="Laptop Industrial",
                    unit_price=Decimal("1899.90"),
                ),
                Product(
                    sku="CHASIS-001",
                    name="Chasis",
                    unit_price=Decimal("100.00"),
                ),
                Product(
                    sku="MB-001",
                    name="Tarjeta Madre",
                    unit_price=Decimal("250.00"),
                ),
                Warehouse(code="WHS-INSUMOS", name="Bodega de insumos"),
                Warehouse(code="WHS-PT", name="Bodega de producto terminado"),
                Account(
                    code="1435",
                    name="Inventario de productos",
                    account_type=AccountType.ASSET,
                ),
                Account(
                    code="220505",
                    name="Cuentas por pagar",
                    account_type=AccountType.LIABILITY,
                ),
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


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """Cliente con ``get_db`` apuntando a la sesión efímera de la prueba."""

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)


def _role(db_session: Session, name: RoleEnum, modules: list[str]) -> Role:
    role = db_session.scalar(select(Role).where(Role.name == name))
    if role is None:
        role = Role(name=name, description=name.value, allowed_modules=modules)
        db_session.add(role)
        db_session.flush()
    return role


def _user(
    db_session: Session, *, role: Role, username: str, email: str
) -> User:
    user = User(
        email=email,
        username=username,
        full_name=username.title(),
        hashed_password=_HASHED_PASSWORD,
        role_id=role.id,
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def users(db_session: Session) -> dict[str, User]:
    roles = {
        "manufacturing": _role(
            db_session, RoleEnum.MANUFACTURING, ["manufacturing"]
        ),
        "admin": _role(db_session, RoleEnum.ADMINISTRATOR, ["*"]),
        "sales": _role(db_session, RoleEnum.SALES, ["sales"]),
        "hr": _role(db_session, RoleEnum.HR, ["hr"]),
    }
    db_session.commit()
    return {
        name: _user(
            db_session,
            role=role,
            username=f"bdd_{name}",
            email=f"bdd-{name}@example.com",
        )
        for name, role in roles.items()
    }


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture()
def manufacturing_headers(users: dict[str, User]) -> dict[str, str]:
    return _headers(users["manufacturing"])


@pytest.fixture()
def admin_headers(users: dict[str, User]) -> dict[str, str]:
    return _headers(users["admin"])


@pytest.fixture()
def sales_headers(users: dict[str, User]) -> dict[str, str]:
    return _headers(users["sales"])


@pytest.fixture()
def hr_headers(users: dict[str, User]) -> dict[str, str]:
    return _headers(users["hr"])


# --------------------------------------------------------------------------- #
# Utilidades de siembra y aserción
# --------------------------------------------------------------------------- #


def product_id(db: Session, sku: str) -> int:
    return int(db.scalars(select(Product.id).where(Product.sku == sku)).one())


def warehouse_id(db: Session, code: str) -> int:
    return int(db.scalars(select(Warehouse.id).where(Warehouse.code == code)).one())


def stock_quantity(db: Session, sku: str, warehouse_code: str) -> int:
    return int(
        db.scalar(
            select(Stock.quantity).where(
                Stock.product_id == product_id(db, sku),
                Stock.warehouse_id == warehouse_id(db, warehouse_code),
            )
        )
        or 0
    )


def set_stock(db: Session, sku: str, warehouse_code: str, quantity: int) -> None:
    db.execute(
        update(Stock)
        .where(
            Stock.product_id == product_id(db, sku),
            Stock.warehouse_id == warehouse_id(db, warehouse_code),
        )
        .values(quantity=quantity)
    )
    db.commit()


def movement_count(
    db: Session,
    *,
    movement_type: MovementType | None = None,
    reference: str | None = None,
) -> int:
    stmt = select(func.count()).select_from(StockMovement)
    if movement_type is not None:
        stmt = stmt.where(StockMovement.movement_type == movement_type)
    if reference is not None:
        stmt = stmt.where(StockMovement.reference_document == reference)
    return int(db.scalar(stmt) or 0)


def journal_count(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(JournalEntry)) or 0)


def order_status(db: Session, order_id: int) -> ProductionOrderStatus:
    return ProductionOrderStatus(
        db.scalars(
            select(ProductionOrder.status).where(ProductionOrder.id == order_id)
        ).one()
    )


def work_center_payload(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "code": "WC-ENSAMBLE-01",
        "name": "Línea de ensamble A",
        "cost_per_hour": "150.00",
    }
    data.update(overrides)
    return data


def bom_payload(db: Session, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "code": "BOM-LAP-IND-01",
        "product_id": product_id(db, "LAP-IND-001"),
        "version": 1,
        "is_active": True,
        "items": [
            {
                "component_product_id": product_id(db, "CHASIS-001"),
                "quantity": "1.00",
                "scrap_percentage": "0.00",
            },
            {
                "component_product_id": product_id(db, "MB-001"),
                "quantity": "1.00",
                "scrap_percentage": "0.00",
            },
        ],
    }
    data.update(overrides)
    return data


def order_payload(
    db: Session, *, bom_id: int, work_center_id: int | None = None, **overrides: Any
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "code": None,
        "bom_id": bom_id,
        "work_center_id": work_center_id,
        "warehouse_source_id": warehouse_id(db, "WHS-INSUMOS"),
        "warehouse_destination_id": warehouse_id(db, "WHS-PT"),
        "quantity_to_produce": "10.00",
    }
    data.update(overrides)
    return data


def create_bom(
    client: TestClient,
    db: Session,
    headers: dict[str, str],
    **overrides: Any,
) -> dict[str, Any]:
    response = client.post(
        f"{BASE_URL}/boms", json=bom_payload(db, **overrides), headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_order(
    client: TestClient,
    db: Session,
    headers: dict[str, str],
    bom_id: int,
    **overrides: Any,
) -> dict[str, Any]:
    response = client.post(
        f"{BASE_URL}/orders",
        json=order_payload(db, bom_id=bom_id, **overrides),
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def start_order(
    client: TestClient, order_id: int, headers: dict[str, str]
) -> Any:
    return client.post(
        f"{BASE_URL}/orders/{order_id}/start", headers=headers
    )


def complete_order(
    client: TestClient,
    order_id: int,
    headers: dict[str, str],
    *,
    quantity: str = "10.00",
    hours: str = "2.00",
) -> Any:
    return client.post(
        f"{BASE_URL}/orders/{order_id}/complete",
        json={"quantity_produced": quantity, "actual_hours": hours},
        headers=headers,
    )


# --------------------------------------------------------------------------- #
# Escenario 1 — Ejecución exitosa y transformación de inventario
# --------------------------------------------------------------------------- #


def test_escenario_1_ejecucion_exitosa(
    client: TestClient,
    db_session: Session,
    manufacturing_headers: dict[str, str],
) -> None:
    # Dado un centro, una BOM activa y stock suficiente.
    center = client.post(
        f"{BASE_URL}/work-centers",
        json=work_center_payload(),
        headers=manufacturing_headers,
    ).json()
    bom = create_bom(client, db_session, manufacturing_headers)
    order = create_order(
        client,
        db_session,
        manufacturing_headers,
        bom["id"],
        work_center_id=center["id"],
    )
    assert order["status"] == "PLANNED"

    # Cuando se inicia y se completa por 10 unidades.
    started = start_order(client, order["id"], manufacturing_headers)
    assert started.status_code == 200
    assert started.json()["status"] == "IN_PROGRESS"

    completed = complete_order(client, order["id"], manufacturing_headers)
    assert completed.status_code == 200, completed.text
    result = completed.json()

    # Entonces hay OUTBOUND, INBOUND, costes y OP completada.
    assert result["status"] == "COMPLETED"
    assert result["quantity_produced"] == "10.00"
    assert stock_quantity(db_session, "CHASIS-001", "WHS-INSUMOS") == 40
    assert stock_quantity(db_session, "MB-001", "WHS-INSUMOS") == 30
    assert stock_quantity(db_session, "LAP-IND-001", "WHS-PT") == 10

    assert movement_count(
        db_session,
        movement_type=MovementType.OUTBOUND,
        reference=order["code"],
    ) == 2
    inbound = movement_count(
        db_session,
        movement_type=MovementType.INBOUND,
        reference=order["code"],
    )
    assert inbound == 1

    # 10 * (100 + 250) = 3500 materiales; 2 h * 150 = 300 mano de obra.
    assert result["total_production_cost"] == "3800.00"
    assert result["unit_production_cost"] == "380.00"
    entry = db_session.scalars(select(JournalEntry)).one()
    assert entry.status is JournalEntryStatus.POSTED
    assert entry.reference_document == order["code"]


# --------------------------------------------------------------------------- #
# Escenario 2 — Rechazo por falta de componentes
# --------------------------------------------------------------------------- #


def test_escenario_2_start_rechaza_por_deficit(
    client: TestClient,
    db_session: Session,
    manufacturing_headers: dict[str, str],
) -> None:
    set_stock(db_session, "CHASIS-001", "WHS-INSUMOS", 20)
    bom = create_bom(client, db_session, manufacturing_headers)
    order = create_order(
        client,
        db_session,
        manufacturing_headers,
        bom["id"],
        quantity_to_produce="50.00",
    )

    response = start_order(client, order["id"], manufacturing_headers)

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "CHASIS-001" in detail
    assert "disponible 20" in detail
    assert "requerido 50" in detail
    assert "déficit 30" in detail
    assert order_status(db_session, order["id"]) is ProductionOrderStatus.PLANNED
    assert stock_quantity(db_session, "CHASIS-001", "WHS-INSUMOS") == 20
    assert stock_quantity(db_session, "MB-001", "WHS-INSUMOS") == 40
    assert movement_count(db_session) == 0


# --------------------------------------------------------------------------- #
# Escenario 3 — Inmutabilidad de OPs cerradas
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("status", ["COMPLETED", "CANCELLED"])
def test_escenario_3_orden_cerrada_es_inmutable(
    client: TestClient,
    db_session: Session,
    manufacturing_headers: dict[str, str],
    status: str,
) -> None:
    bom = create_bom(client, db_session, manufacturing_headers)
    order = create_order(client, db_session, manufacturing_headers, bom["id"])

    if status == "COMPLETED":
        started = start_order(client, order["id"], manufacturing_headers)
        assert started.status_code == 200
        assert (
            complete_order(client, order["id"], manufacturing_headers).status_code
            == 200
        )
    else:
        cancelled = client.post(
            f"{BASE_URL}/orders/{order['id']}/cancel", headers=manufacturing_headers
        )
        assert cancelled.status_code == 200

    order_id = order["id"]
    assert order_status(db_session, order_id) is ProductionOrderStatus(status)
    movements_before = movement_count(db_session)
    journals_before = journal_count(db_session)

    # Modificar cantidades o bodegas se rechaza en el servicio (sin PATCH HTTP).
    row = db_session.get(ProductionOrder, order_id)
    quantity_before = row.quantity_to_produce
    source_before = row.warehouse_source_id
    with pytest.raises(ImmutableProductionOrderError) as excinfo:
        update_production_order(
            db_session,
            order_id,
            ProductionOrderUpdate(quantity_to_produce="99.00"),
        )
    assert excinfo.value.status_code == 409
    with pytest.raises(ImmutableProductionOrderError):
        update_production_order(
            db_session,
            order_id,
            ProductionOrderUpdate(warehouse_source_id=source_before),
        )
    db_session.refresh(row)
    assert row.quantity_to_produce == quantity_before
    assert row.warehouse_source_id == source_before

    # Las transiciones por HTTP también se rechazan con 409.
    assert start_order(client, order_id, manufacturing_headers).status_code == 409
    assert complete_order(client, order_id, manufacturing_headers).status_code == 409
    assert (
        client.post(
            f"{BASE_URL}/orders/{order_id}/cancel", headers=manufacturing_headers
        ).status_code
        == 409
    )

    assert order_status(db_session, order_id) is ProductionOrderStatus(status)
    assert movement_count(db_session) == movements_before
    assert journal_count(db_session) == journals_before


# --------------------------------------------------------------------------- #
# Escenario 4 — BOM activa duplicada
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("code", "version", "expected_detail"),
    [
        ("BOM-LAP-IND-V2", 1, "Ya existe una BOM activa"),
        ("BOM-LAP-IND-01", 2, "Ya existe una BOM con el código"),
    ],
)
def test_escenario_4_bom_duplicada_se_rechaza(
    client: TestClient,
    db_session: Session,
    manufacturing_headers: dict[str, str],
    code: str,
    version: int,
    expected_detail: str,
) -> None:
    create_bom(client, db_session, manufacturing_headers)

    response = client.post(
        f"{BASE_URL}/boms",
        json=bom_payload(db_session, code=code, version=version),
        headers=manufacturing_headers,
    )

    assert response.status_code == 409
    assert expected_detail in response.json()["detail"]
    listed = client.get(f"{BASE_URL}/boms", headers=manufacturing_headers)
    assert len(listed.json()) == 1


# --------------------------------------------------------------------------- #
# Escenario 5 — Rollback ACID ante fallos simulados
# --------------------------------------------------------------------------- #


def test_escenario_5_fallo_inventory_en_start_revierte_todo(
    client: TestClient,
    db_session: Session,
    manufacturing_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bom = create_bom(client, db_session, manufacturing_headers)
    order = create_order(client, db_session, manufacturing_headers, bom["id"])
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

    response = start_order(client, order["id"], manufacturing_headers)

    assert calls["count"] == 2
    assert response.status_code == 400
    assert order_status(db_session, order["id"]) is ProductionOrderStatus.PLANNED
    assert stock_quantity(db_session, "CHASIS-001", "WHS-INSUMOS") == 50
    assert stock_quantity(db_session, "MB-001", "WHS-INSUMOS") == 40
    assert movement_count(db_session) == 0
    assert journal_count(db_session) == 0


def test_escenario_5_fallo_inventory_en_complete_revierte_todo(
    client: TestClient,
    db_session: Session,
    manufacturing_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bom = create_bom(client, db_session, manufacturing_headers)
    order = create_order(client, db_session, manufacturing_headers, bom["id"])
    assert start_order(client, order["id"], manufacturing_headers).status_code == 200
    expected_movements = movement_count(db_session)

    def failing_increase(stock: Stock, quantity: int) -> None:
        del stock, quantity
        raise inventory_services.InventoryError("fallo simulado de inventario")

    monkeypatch.setattr(inventory_services, "_increase", failing_increase)

    response = complete_order(client, order["id"], manufacturing_headers)

    assert response.status_code == 400
    assert "fallo simulado de inventario" in response.json()["detail"]
    assert order_status(db_session, order["id"]) is ProductionOrderStatus.IN_PROGRESS
    assert stock_quantity(db_session, "LAP-IND-001", "WHS-PT") == 0
    assert movement_count(db_session) == expected_movements
    assert movement_count(db_session, movement_type=MovementType.INBOUND) == 0
    assert journal_count(db_session) == 0


def test_escenario_5_fallo_accounting_en_complete_revierte_todo(
    client: TestClient,
    db_session: Session,
    manufacturing_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bom = create_bom(client, db_session, manufacturing_headers)
    order = create_order(client, db_session, manufacturing_headers, bom["id"])
    assert start_order(client, order["id"], manufacturing_headers).status_code == 200
    expected_movements = movement_count(db_session)

    def failing_post(db: Session, **kwargs: Any) -> None:
        # Se deja un asiento parcial en sesión para comprobar que el rollback lo
        # elimina junto al INBOUND y a los costes.
        db.add(
            JournalEntry(
                code="ASI-PRO-PARCIAL",
                entry_date=date(2026, 11, 23),
                description="Asiento parcial simulado",
                status=JournalEntryStatus.POSTED,
                created_by="bdd",
            )
        )
        db.flush()
        raise RuntimeError(f"fallo simulado de contabilidad: {kwargs['order_code']}")

    monkeypatch.setattr(
        accounting_service, "post_production_order_accounting", failing_post
    )

    response = complete_order(client, order["id"], manufacturing_headers)

    assert response.status_code == 400
    assert "fallo simulado de contabilidad" in response.json()["detail"]
    assert order_status(db_session, order["id"]) is ProductionOrderStatus.IN_PROGRESS
    assert stock_quantity(db_session, "LAP-IND-001", "WHS-PT") == 0
    assert movement_count(db_session) == expected_movements
    assert movement_count(db_session, movement_type=MovementType.INBOUND) == 0
    assert journal_count(db_session) == 0


# --------------------------------------------------------------------------- #
# Escenario 6 — OP con BOM inactiva
# --------------------------------------------------------------------------- #


def test_escenario_6_orden_con_bom_inactiva_se_rechaza(
    client: TestClient,
    db_session: Session,
    manufacturing_headers: dict[str, str],
) -> None:
    bom = create_bom(client, db_session, manufacturing_headers)
    deactivated = client.patch(
        f"{BASE_URL}/boms/{bom['id']}/deactivate", headers=manufacturing_headers
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False

    response = client.post(
        f"{BASE_URL}/orders",
        json=order_payload(db_session, bom_id=bom["id"]),
        headers=manufacturing_headers,
    )

    assert response.status_code == 400
    assert "inactiva" in response.json()["detail"]
    assert movement_count(db_session) == 0


# --------------------------------------------------------------------------- #
# Escenario 7 — Transición directa PLANNED -> COMPLETED
# --------------------------------------------------------------------------- #


def test_escenario_7_complete_desde_planned_se_rechaza(
    client: TestClient,
    db_session: Session,
    manufacturing_headers: dict[str, str],
) -> None:
    bom = create_bom(client, db_session, manufacturing_headers)
    order = create_order(client, db_session, manufacturing_headers, bom["id"])

    response = complete_order(client, order["id"], manufacturing_headers)

    assert response.status_code == 400
    assert "IN_PROGRESS" in response.json()["detail"]
    assert order_status(db_session, order["id"]) is ProductionOrderStatus.PLANNED
    assert stock_quantity(db_session, "CHASIS-001", "WHS-INSUMOS") == 50
    assert movement_count(db_session) == 0
    assert journal_count(db_session) == 0


# --------------------------------------------------------------------------- #
# Escenario 8 — RBAC
# --------------------------------------------------------------------------- #


PROTECTED_CALLS = [
    ("get", f"{BASE_URL}/work-centers"),
    ("post", f"{BASE_URL}/work-centers"),
    ("patch", f"{BASE_URL}/work-centers/1"),
    ("get", f"{BASE_URL}/boms"),
    ("post", f"{BASE_URL}/boms"),
    ("get", f"{BASE_URL}/boms/1"),
    ("patch", f"{BASE_URL}/boms/1/deactivate"),
    ("get", f"{BASE_URL}/orders"),
    ("post", f"{BASE_URL}/orders"),
    ("get", f"{BASE_URL}/orders/1"),
    ("post", f"{BASE_URL}/orders/1/start"),
    ("post", f"{BASE_URL}/orders/1/complete"),
    ("post", f"{BASE_URL}/orders/1/cancel"),
]


@pytest.mark.parametrize("headers_name", ["sales_headers", "hr_headers"])
@pytest.mark.parametrize(("method", "path"), PROTECTED_CALLS)
def test_escenario_8_rol_no_autorizado_recibe_403(
    client: TestClient,
    request: pytest.FixtureRequest,
    headers_name: str,
    method: str,
    path: str,
) -> None:
    headers = request.getfixturevalue(headers_name)
    response = client.request(method, path, json={}, headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"] == FORBIDDEN_DETAIL


@pytest.mark.parametrize(("method", "path"), PROTECTED_CALLS)
def test_escenario_8_sin_token_recibe_401(
    client: TestClient, method: str, path: str
) -> None:
    assert client.request(method, path, json={}).status_code == 401


@pytest.mark.parametrize("headers_name", ["manufacturing_headers", "admin_headers"])
def test_escenario_8_roles_autorizados_pueden_listar(
    client: TestClient, request: pytest.FixtureRequest, headers_name: str
) -> None:
    headers = request.getfixturevalue(headers_name)
    response = client.get(f"{BASE_URL}/work-centers", headers=headers)
    assert response.status_code == 200
    assert response.json() == []
