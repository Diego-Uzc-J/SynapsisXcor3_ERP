"""Pruebas HTTP y RBAC del router de manufactura.

Cubren los contratos de ``specs/manufacturing_spec.md`` (sección 4) a través de
la API real (``TestClient``): centros de trabajo, BOMs y órdenes de producción
con sus transiciones ACID.

Verifican también la regla 7 de la spec y la matriz del manifiesto: 401 sin
token, 403 para roles distintos de ``MANUFACTURING``/``ADMINISTRATOR`` y
200/201 para ambos roles autorizados.
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
from sqlalchemy import create_engine, event, select
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
from src.modules.accounting.models import (  # noqa: E402
    Account,
    AccountType,
    JournalEntry,
    JournalEntryStatus,
)
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
from src.modules.users.models import Role, RoleEnum, User  # noqa: E402

BASE_URL = "/api/v1/manufacturing"
_HASHED_PASSWORD = hash_password("Manuf1234567!")


# --------------------------------------------------------------------------- #
# Fixtures de base de datos, API y usuarios
# --------------------------------------------------------------------------- #


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    """Engine SQLite aislado por prueba, sin ``BEGIN`` implícito de pysqlite."""
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
                    sku="LAP-LITE-001",
                    name="Laptop Ligera",
                    unit_price=Decimal("999.00"),
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
    """Cliente HTTP con la sesión de prueba inyectada en ``get_db``."""

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
        "admin": _role(db_session, RoleEnum.ADMINISTRATOR, ["*"]),
        "manufacturing": _role(db_session, RoleEnum.MANUFACTURING, ["manufacturing"]),
        "sales": _role(db_session, RoleEnum.SALES, ["sales"]),
        "hr": _role(db_session, RoleEnum.HR, ["hr"]),
    }
    db_session.commit()
    return {
        name: _user(
            db_session,
            role=role,
            username=f"user_{name}",
            email=f"user-{name}@example.com",
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
# Utilidades
# --------------------------------------------------------------------------- #


def product_id(db: Session, sku: str) -> int:
    return int(db.scalars(select(Product.id).where(Product.sku == sku)).one())


def warehouse_id(db: Session, code: str) -> int:
    return int(db.scalars(select(Warehouse.id).where(Warehouse.code == code)).one())


def stock_quantity(db: Session, sku: str, code: str) -> int:
    return int(
        db.scalar(
            select(Stock.quantity).where(
                Stock.product_id == product_id(db, sku),
                Stock.warehouse_id == warehouse_id(db, code),
            )
        )
        or 0
    )


def work_center_payload(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "code": "WC-ENSAMBLE-01",
        "name": "Línea de ensamble A",
        "cost_per_hour": "150.00",
        "is_active": True,
    }
    data.update(overrides)
    return data


def bom_payload(
    db: Session,
    *,
    sku: str = "LAP-IND-001",
    code: str = "BOM-LAP-IND-01",
    version: int = 1,
    **overrides: Any,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "code": code,
        "product_id": product_id(db, sku),
        "version": version,
        "name": "Receta de prueba",
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
    db: Session,
    *,
    bom_id: int,
    work_center_id: int | None = None,
    sku: str = "LAP-IND-001",
    **overrides: Any,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "code": None,
        "bom_id": bom_id,
        "work_center_id": work_center_id,
        "warehouse_source_id": warehouse_id(db, "WHS-INSUMOS"),
        "warehouse_destination_id": warehouse_id(db, "WHS-PT"),
        "quantity_to_produce": "10.00",
        "estimated_hours": "4.00",
    }
    data.update(overrides)
    return data


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


# --------------------------------------------------------------------------- #
# Registro de rutas y RBAC
# --------------------------------------------------------------------------- #


def test_openapi_documents_manufacturing_routes(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    operations = {
        (method, path)
        for path, methods in schema["paths"].items()
        if path.startswith(f"{BASE_URL}/")
        for method in methods
        if method in {"get", "post", "put", "patch", "delete"}
    }
    assert operations == {
        ("post", f"{BASE_URL}/work-centers"),
        ("get", f"{BASE_URL}/work-centers"),
        ("patch", f"{BASE_URL}/work-centers/{{work_center_id}}"),
        ("post", f"{BASE_URL}/boms"),
        ("get", f"{BASE_URL}/boms"),
        ("get", f"{BASE_URL}/boms/{{bom_id}}"),
        ("patch", f"{BASE_URL}/boms/{{bom_id}}/deactivate"),
        ("post", f"{BASE_URL}/orders"),
        ("get", f"{BASE_URL}/orders"),
        ("get", f"{BASE_URL}/orders/{{order_id}}"),
        ("post", f"{BASE_URL}/orders/{{order_id}}/start"),
        ("post", f"{BASE_URL}/orders/{{order_id}}/complete"),
        ("post", f"{BASE_URL}/orders/{{order_id}}/cancel"),
    }


@pytest.mark.parametrize(("method", "path"), PROTECTED_CALLS)
def test_rbac_anonymous_request_is_401(
    client: TestClient, method: str, path: str
) -> None:
    response = client.request(method, path, json={})
    assert response.status_code == 401


@pytest.mark.parametrize("headers_name", ["sales_headers", "hr_headers"])
@pytest.mark.parametrize(("method", "path"), PROTECTED_CALLS)
def test_rbac_unauthorized_role_is_403(
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


@pytest.mark.parametrize("headers_name", ["manufacturing_headers", "admin_headers"])
def test_rbac_authorized_roles_can_list_work_centers(
    client: TestClient, request: pytest.FixtureRequest, headers_name: str
) -> None:
    headers = request.getfixturevalue(headers_name)
    response = client.get(f"{BASE_URL}/work-centers", headers=headers)
    assert response.status_code == 200
    assert response.json() == []


# --------------------------------------------------------------------------- #
# WorkCenters y BOM
# --------------------------------------------------------------------------- #


def test_work_center_crud_and_validation(
    client: TestClient, manufacturing_headers: dict[str, str]
) -> None:
    created = client.post(
        f"{BASE_URL}/work-centers",
        json=work_center_payload(),
        headers=manufacturing_headers,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["code"] == "WC-ENSAMBLE-01"
    assert body["cost_per_hour"] == "150.00"

    listed = client.get(f"{BASE_URL}/work-centers", headers=manufacturing_headers)
    assert listed.status_code == 200
    assert [item["code"] for item in listed.json()] == ["WC-ENSAMBLE-01"]

    updated = client.patch(
        f"{BASE_URL}/work-centers/{body['id']}",
        json={"name": "Línea B", "cost_per_hour": "175.50"},
        headers=manufacturing_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Línea B"
    assert updated.json()["cost_per_hour"] == "175.50"

    duplicate = client.post(
        f"{BASE_URL}/work-centers",
        json=work_center_payload(),
        headers=manufacturing_headers,
    )
    assert duplicate.status_code == 409

    invalid = client.post(
        f"{BASE_URL}/work-centers",
        json=work_center_payload(code="WC-OTRO", cost_per_hour=150.0),
        headers=manufacturing_headers,
    )
    assert invalid.status_code == 422

    missing = client.patch(
        f"{BASE_URL}/work-centers/999",
        json={"name": "Inexistente"},
        headers=manufacturing_headers,
    )
    assert missing.status_code == 404


def test_bom_create_list_detail_and_deactivate(
    client: TestClient,
    db_session: Session,
    manufacturing_headers: dict[str, str],
) -> None:
    created = client.post(
        f"{BASE_URL}/boms",
        json=bom_payload(db_session),
        headers=manufacturing_headers,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["code"] == "BOM-LAP-IND-01"
    assert len(body["items"]) == 2
    assert body["is_active"] is True

    listed = client.get(
        f"{BASE_URL}/boms",
        params={"product_id": body["product_id"], "is_active": "true"},
        headers=manufacturing_headers,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [body["id"]]

    detail = client.get(
        f"{BASE_URL}/boms/{body['id']}", headers=manufacturing_headers
    )
    assert detail.status_code == 200
    assert detail.json()["items"] == body["items"]

    duplicate = client.post(
        f"{BASE_URL}/boms",
        json=bom_payload(db_session),
        headers=manufacturing_headers,
    )
    assert duplicate.status_code == 409

    deactivated = client.patch(
        f"{BASE_URL}/boms/{body['id']}/deactivate",
        headers=manufacturing_headers,
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False

    missing = client.get(f"{BASE_URL}/boms/999", headers=manufacturing_headers)
    assert missing.status_code == 404


# --------------------------------------------------------------------------- #
# Órdenes de producción
# --------------------------------------------------------------------------- #


def test_production_order_lifecycle_end_to_end(
    client: TestClient,
    db_session: Session,
    manufacturing_headers: dict[str, str],
) -> None:
    center = client.post(
        f"{BASE_URL}/work-centers",
        json=work_center_payload(),
        headers=manufacturing_headers,
    ).json()
    bom = client.post(
        f"{BASE_URL}/boms",
        json=bom_payload(db_session),
        headers=manufacturing_headers,
    ).json()

    created = client.post(
        f"{BASE_URL}/orders",
        json=order_payload(db_session, bom_id=bom["id"], work_center_id=center["id"]),
        headers=manufacturing_headers,
    )
    assert created.status_code == 201
    order = created.json()
    assert order["code"].startswith("OP-")
    assert order["status"] == "PLANNED"

    listed = client.get(
        f"{BASE_URL}/orders",
        params={"status": "PLANNED", "bom_id": bom["id"]},
        headers=manufacturing_headers,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [order["id"]]

    dated = client.get(
        f"{BASE_URL}/orders",
        params={"created_date": date.today().isoformat()},
        headers=manufacturing_headers,
    )
    assert dated.status_code == 200
    assert [item["id"] for item in dated.json()] == [order["id"]]

    detail = client.get(
        f"{BASE_URL}/orders/{order['id']}", headers=manufacturing_headers
    )
    assert detail.status_code == 200
    assert detail.json()["code"] == order["code"]

    started = client.post(
        f"{BASE_URL}/orders/{order['id']}/start",
        json={"started_at": "2026-11-22"},
        headers=manufacturing_headers,
    )
    assert started.status_code == 200
    assert started.json()["status"] == "IN_PROGRESS"
    assert started.json()["started_at"] == "2026-11-22"
    assert stock_quantity(db_session, "CHASIS-001", "WHS-INSUMOS") == 40
    assert stock_quantity(db_session, "MB-001", "WHS-INSUMOS") == 30

    completed = client.post(
        f"{BASE_URL}/orders/{order['id']}/complete",
        json={
            "quantity_produced": "10.00",
            "actual_hours": "2.00",
            "completed_at": "2026-11-23",
        },
        headers=manufacturing_headers,
    )
    assert completed.status_code == 200
    body = completed.json()
    assert body["status"] == "COMPLETED"
    assert body["completed_at"] == "2026-11-23"
    assert body["total_production_cost"] == "3800.00"
    assert body["unit_production_cost"] == "380.00"
    assert stock_quantity(db_session, "LAP-IND-001", "WHS-PT") == 10

    entry = db_session.scalars(select(JournalEntry)).one()
    assert entry.status is JournalEntryStatus.POSTED
    assert entry.reference_document == order["code"]
    assert entry.code.startswith("ASI-PRO-")

    outbound = db_session.scalars(
        select(StockMovement).where(
            StockMovement.reference_document == order["code"],
            StockMovement.movement_type == MovementType.OUTBOUND,
        )
    ).all()
    assert len(outbound) == 2
    assert all(item.created_by == "user_manufacturing" for item in outbound)

    second = client.post(
        f"{BASE_URL}/orders/{order['id']}/complete",
        json={"quantity_produced": "1.00"},
        headers=manufacturing_headers,
    )
    assert second.status_code == 409


def test_cancel_in_progress_order_restores_stock(
    client: TestClient,
    db_session: Session,
    manufacturing_headers: dict[str, str],
) -> None:
    bom = client.post(
        f"{BASE_URL}/boms",
        json=bom_payload(
            db_session, sku="LAP-LITE-001", code="BOM-LAP-LITE-01"
        ),
        headers=manufacturing_headers,
    ).json()
    order = client.post(
        f"{BASE_URL}/orders",
        json=order_payload(
            db_session, bom_id=bom["id"], quantity_to_produce="5.00"
        ),
        headers=manufacturing_headers,
    ).json()

    started = client.post(
        f"{BASE_URL}/orders/{order['id']}/start", headers=manufacturing_headers
    )
    assert started.status_code == 200
    assert stock_quantity(db_session, "CHASIS-001", "WHS-INSUMOS") == 45
    assert stock_quantity(db_session, "MB-001", "WHS-INSUMOS") == 35

    cancelled = client.post(
        f"{BASE_URL}/orders/{order['id']}/cancel", headers=manufacturing_headers
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert stock_quantity(db_session, "CHASIS-001", "WHS-INSUMOS") == 50
    assert stock_quantity(db_session, "MB-001", "WHS-INSUMOS") == 40

    reversals = db_session.scalars(
        select(StockMovement).where(
            StockMovement.reference_document == f"{order['code']}-CANCEL"
        )
    ).all()
    assert [item.quantity for item in reversals] == [5, 5]
    assert all(item.created_by == "user_manufacturing" for item in reversals)

    again = client.post(
        f"{BASE_URL}/orders/{order['id']}/cancel", headers=manufacturing_headers
    )
    assert again.status_code == 409


def test_start_without_stock_returns_400(
    client: TestClient,
    db_session: Session,
    manufacturing_headers: dict[str, str],
) -> None:
    bom = client.post(
        f"{BASE_URL}/boms",
        json=bom_payload(
            db_session, sku="LAP-LITE-001", code="BOM-LAP-LITE-01"
        ),
        headers=manufacturing_headers,
    ).json()
    order = client.post(
        f"{BASE_URL}/orders",
        json=order_payload(
            db_session, bom_id=bom["id"], quantity_to_produce="100.00"
        ),
        headers=manufacturing_headers,
    ).json()

    response = client.post(
        f"{BASE_URL}/orders/{order['id']}/start", headers=manufacturing_headers
    )
    assert response.status_code == 400
    assert "CHASIS-001" in response.json()["detail"]
    assert stock_quantity(db_session, "CHASIS-001", "WHS-INSUMOS") == 50
    assert (
        db_session.scalars(
            select(ProductionOrder.status).where(ProductionOrder.id == order["id"])
        ).one()
        is ProductionOrderStatus.PLANNED
    )
