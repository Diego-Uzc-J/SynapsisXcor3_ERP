"""Pruebas HTTP y RBAC del router del módulo de Contabilidad.

Cubren los contratos de ``specs/accounting_spec.md`` (sección 4) a través de la
API real (``TestClient``): plan de cuentas, ciclo de asientos (borrador →
publicación → reversión), cartera CxC/CxP, pagos atómicos y reportes.

Verifican también la matriz RBAC del manifiesto: 401 sin token, 403 para roles
sin permiso ``accounting`` y 200/201 para ``ACCOUNTING`` y ``ADMINISTRATOR``.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Generator
from datetime import date, timedelta
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
from src.core.security import create_access_token, hash_password  # noqa: E402
from src.main import app  # noqa: E402
from src.modules.accounting.models import (  # noqa: E402
    AccountBalanceStatus,
    AccountPayable,
    AccountReceivable,
    AccountType,
    AccountingPeriod,
    JournalEntryStatus,
)
from src.modules.accounting.service import (  # noqa: E402
    create_account,
    create_journal_entry,
    post_journal_entry,
)
from src.modules.accounting.schemas import (  # noqa: E402
    AccountCreate,
    JournalEntryCreate,
    JournalItemCreate,
)
from src.modules.purchasing.models import Supplier  # noqa: E402
from src.modules.sales.models import Customer  # noqa: E402
from src.modules.users.models import Role, RoleEnum, User  # noqa: E402

ACCOUNTING_URL = "/api/v1/accounting"
_HASHED_PASSWORD = hash_password("Accounting1234!")
_DUE = date.today() + timedelta(days=30)


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
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def accounts(db_session: Session) -> dict[str, User]:
    admin_role = _role(db_session, RoleEnum.ADMINISTRATOR, ["*"])
    accounting_role = _role(
        db_session,
        RoleEnum.ACCOUNTING,
        ["accounting", "sales:read", "purchasing:read"],
    )
    sales_role = _role(db_session, RoleEnum.SALES, ["sales", "inventory:read"])
    db_session.commit()

    return {
        "admin": _user(
            db_session,
            role=admin_role,
            username="contaduria_admin",
            email="contaduria-admin@example.com",
        ),
        "accounting": _user(
            db_session,
            role=accounting_role,
            username="contador",
            email="contador@example.com",
        ),
        "sales": _user(
            db_session,
            role=sales_role,
            username="vendedor",
            email="vendedor@example.com",
        ),
    }


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture()
def admin_headers(accounts: dict[str, User]) -> dict[str, str]:
    return _headers(accounts["admin"])


@pytest.fixture()
def accounting_headers(accounts: dict[str, User]) -> dict[str, str]:
    return _headers(accounts["accounting"])


@pytest.fixture()
def sales_headers(accounts: dict[str, User]) -> dict[str, str]:
    return _headers(accounts["sales"])


@pytest.fixture()
def chart(db_session: Session) -> dict[str, int]:
    """PUC mínimo con los códigos que la automatización espera por defecto."""
    definitions = {
        "cash": ("110505", "Caja General", AccountType.ASSET),
        "receivable": ("130505", "Clientes", AccountType.ASSET),
        "inventory": ("1435", "Inventario", AccountType.ASSET),
        "payable": ("220505", "Proveedores", AccountType.LIABILITY),
        "equity": ("3105", "Capital social", AccountType.EQUITY),
        "revenue": ("4135", "Ventas", AccountType.REVENUE),
        "expense": ("5100", "Gastos", AccountType.EXPENSE),
    }
    return {
        role: create_account(
            db_session,
            AccountCreate(code=code, name=name, account_type=kind),
        ).id
        for role, (code, name, kind) in definitions.items()
    }


@pytest.fixture()
def receivable(db_session: Session) -> AccountReceivable:
    customer = Customer(
        tax_id="900111222-1",
        company_name="Cliente de prueba",
        contact_name="Ana Pérez",
        email="ana@example.com",
        address="Calle 1 # 2-3",
        credit_limit=Decimal("10000.00"),
    )
    db_session.add(customer)
    db_session.commit()
    balance = AccountReceivable(
        customer_id=customer.id,
        total_amount=Decimal("1000.00"),
        paid_amount=Decimal("0.00"),
        due_date=_DUE,
        status=AccountBalanceStatus.PENDING,
    )
    db_session.add(balance)
    db_session.commit()
    db_session.refresh(balance)
    return balance


@pytest.fixture()
def payable(db_session: Session) -> AccountPayable:
    supplier = Supplier(
        tax_id="800999888-1",
        company_name="Proveedor de prueba",
        contact_name="Luis Gómez",
        email="proveedor@example.com",
        address="Carrera 4 # 5-6",
        payment_terms_days=30,
    )
    db_session.add(supplier)
    db_session.commit()
    balance = AccountPayable(
        supplier_id=supplier.id,
        bill_reference="FAC-2026-0001",
        total_amount=Decimal("800.00"),
        paid_amount=Decimal("0.00"),
        due_date=_DUE,
        status=AccountBalanceStatus.PENDING,
    )
    db_session.add(balance)
    db_session.commit()
    db_session.refresh(balance)
    return balance


def _posted_sale(db_session: Session, chart: dict[str, int], amount: str) -> None:
    """Publica una venta al contado directamente en la capa de servicios."""
    entry = create_journal_entry(
        db_session,
        JournalEntryCreate(
            code=f"ASI-HTTP-{amount.replace('.', '')}",
            entry_date=date(2026, 11, 15),
            description="Venta al contado",
            items=[
                JournalItemCreate(
                    account_id=chart["cash"], debit=Decimal(amount)
                ),
                JournalItemCreate(
                    account_id=chart["revenue"], credit=Decimal(amount)
                ),
            ],
        ),
    )
    post_journal_entry(db_session, entry.id)


# --------------------------------------------------------------------------- #
# Documentación OpenAPI
# --------------------------------------------------------------------------- #


def test_openapi_and_docs_expose_accounting_routes(client: TestClient) -> None:
    """Swagger UI responde y el esquema lista todos los grupos del módulo."""
    docs = client.get("/docs")
    assert docs.status_code == 200

    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    paths = schema.json()["paths"]
    expected = [
        "/api/v1/accounting/accounts",
        "/api/v1/accounting/accounts/{account_id}",
        "/api/v1/accounting/journal-entries",
        "/api/v1/accounting/journal-entries/{entry_id}/post",
        "/api/v1/accounting/journal-entries/{entry_id}/void",
        "/api/v1/accounting/journal-entries/{entry_id}/reverse",
        "/api/v1/accounting/receivables",
        "/api/v1/accounting/payables",
        "/api/v1/accounting/payments",
        "/api/v1/accounting/reports/trial-balance",
        "/api/v1/accounting/reports/balance-sheet",
        "/api/v1/accounting/reports/income-statement",
    ]
    for path in expected:
        assert path in paths
    assert paths["/api/v1/accounting/accounts"]["get"]["security"] == [
        {"HTTPBearer": []}
    ]
    assert "HTTPBearer" in schema.json()["components"]["securitySchemes"]


# --------------------------------------------------------------------------- #
# RBAC: autenticación y autorización
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path",
    [
        "/accounts",
        "/journal-entries",
        "/receivables",
        "/payables",
        "/payments",
        "/reports/trial-balance",
        "/reports/balance-sheet",
        "/reports/income-statement",
    ],
)
def test_anonymous_request_is_rejected(client: TestClient, path: str) -> None:
    """Sin token, cualquier recurso de contabilidad responde 401."""
    response = client.get(f"{ACCOUNTING_URL}{path}")
    assert response.status_code == 401


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/accounts"),
        ("POST", "/accounts"),
        ("PATCH", "/accounts/1"),
        ("DELETE", "/accounts/1"),
        ("GET", "/journal-entries"),
        ("POST", "/journal-entries"),
        ("POST", "/journal-entries/1/post"),
        ("POST", "/journal-entries/1/void"),
        ("POST", "/journal-entries/1/reverse"),
        ("GET", "/receivables"),
        ("POST", "/receivables/1/payments"),
        ("GET", "/payables"),
        ("POST", "/payables/1/payments"),
        ("GET", "/payments"),
        ("POST", "/payments"),
        ("GET", "/reports/trial-balance"),
        ("GET", "/reports/balance-sheet"),
        ("GET", "/reports/income-statement"),
    ],
)
def test_role_without_accounting_permission_is_forbidden(
    client: TestClient,
    sales_headers: dict[str, str],
    method: str,
    path: str,
) -> None:
    """El rol ``SALES`` no puede acceder a ningún endpoint de contabilidad."""
    response = client.request(
        method, f"{ACCOUNTING_URL}{path}", headers=sales_headers, json={}
    )
    assert response.status_code == 403


def test_invalid_token_is_rejected(client: TestClient) -> None:
    """Un token malformado responde 401, no 500."""
    response = client.get(
        f"{ACCOUNTING_URL}/accounts",
        headers={"Authorization": "Bearer no-es-un-token"},
    )
    assert response.status_code == 401


@pytest.mark.parametrize("headers_name", ["accounting_headers", "admin_headers"])
def test_authorized_roles_can_list_resources(
    request: pytest.FixtureRequest,
    client: TestClient,
    headers_name: str,
) -> None:
    """``ACCOUNTING`` y ``ADMINISTRATOR`` pueden consultar todos los recursos."""
    headers: dict[str, str] = request.getfixturevalue(headers_name)
    paths = (
        "/accounts",
        "/journal-entries",
        "/receivables",
        "/payables",
        "/payments",
        "/reports/trial-balance",
        "/reports/balance-sheet",
        "/reports/income-statement",
    )
    for path in paths:
        response = client.get(f"{ACCOUNTING_URL}{path}", headers=headers)
        assert response.status_code == 200, response.text


# --------------------------------------------------------------------------- #
# Plan de cuentas por HTTP
# --------------------------------------------------------------------------- #


def test_accounts_crud_over_http(
    client: TestClient, accounting_headers: dict[str, str]
) -> None:
    """Alta, filtro, detalle, actualización y desactivación lógica."""
    created = client.post(
        f"{ACCOUNTING_URL}/accounts",
        headers=accounting_headers,
        json={
            "code": "110599",
            "name": "Caja auxiliar",
            "account_type": "ASSET",
        },
    )
    assert created.status_code == 201, created.text
    account_id = created.json()["id"]
    assert created.json()["is_active"] is True

    listing = client.get(
        f"{ACCOUNTING_URL}/accounts",
        headers=accounting_headers,
        params={"account_type": "ASSET", "code": "110599"},
    )
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [account_id]

    detail = client.get(
        f"{ACCOUNTING_URL}/accounts/{account_id}", headers=accounting_headers
    )
    assert detail.status_code == 200
    assert detail.json()["name"] == "Caja auxiliar"

    patched = client.patch(
        f"{ACCOUNTING_URL}/accounts/{account_id}",
        headers=accounting_headers,
        json={"name": "Caja secundaria"},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Caja secundaria"

    deactivated = client.delete(
        f"{ACCOUNTING_URL}/accounts/{account_id}", headers=accounting_headers
    )
    assert deactivated.status_code == 204
    after = client.get(
        f"{ACCOUNTING_URL}/accounts/{account_id}", headers=accounting_headers
    )
    assert after.json()["is_active"] is False


# --------------------------------------------------------------------------- #
# Libro diario por HTTP
# --------------------------------------------------------------------------- #


def test_journal_entry_lifecycle_over_http(
    client: TestClient,
    accounting_headers: dict[str, str],
    chart: dict[str, int],
) -> None:
    """Borrador → publicación → reversión, con anulación de otro borrador."""
    created = client.post(
        f"{ACCOUNTING_URL}/journal-entries",
        headers=accounting_headers,
        json={
            "code": "ASI-HTTP-0001",
            "entry_date": "2026-11-15",
            "description": "Venta de prueba",
            "items": [
                {"account_id": chart["cash"], "debit": "500.00"},
                {"account_id": chart["revenue"], "credit": "500.00"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    entry_id = created.json()["id"]
    assert created.json()["status"] == JournalEntryStatus.DRAFT.value
    assert created.json()["created_by"] == "contador"
    assert len(created.json()["items"]) == 2

    detail = client.get(
        f"{ACCOUNTING_URL}/journal-entries/{entry_id}", headers=accounting_headers
    )
    assert detail.status_code == 200
    assert detail.json()["code"] == "ASI-HTTP-0001"

    posted = client.post(
        f"{ACCOUNTING_URL}/journal-entries/{entry_id}/post",
        headers=accounting_headers,
    )
    assert posted.status_code == 200, posted.text
    assert posted.json()["status"] == JournalEntryStatus.POSTED.value
    assert posted.json()["total_debit"] == "500.00"
    assert posted.json()["posted_at"] is not None

    # Celosía de inmutabilidad y de estado.
    assert (
        client.post(
            f"{ACCOUNTING_URL}/journal-entries/{entry_id}/post",
            headers=accounting_headers,
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"{ACCOUNTING_URL}/journal-entries/{entry_id}/void",
            headers=accounting_headers,
        ).status_code
        == 400
    )

    reversal = client.post(
        f"{ACCOUNTING_URL}/journal-entries/{entry_id}/reverse",
        headers=accounting_headers,
    )
    assert reversal.status_code == 201, reversal.text
    assert reversal.json()["status"] == JournalEntryStatus.POSTED.value
    assert reversal.json()["reference_document"] == "ASI-HTTP-0001"
    assert reversal.json()["created_by"] == "contador"

    draft = client.post(
        f"{ACCOUNTING_URL}/journal-entries",
        headers=accounting_headers,
        json={
            "code": "ASI-HTTP-0002",
            "description": "Borrador a anular",
            "items": [
                {"account_id": chart["cash"], "debit": "10.00"},
                {"account_id": chart["revenue"], "credit": "10.00"},
            ],
        },
    )
    assert draft.status_code == 201
    voided = client.post(
        f"{ACCOUNTING_URL}/journal-entries/{draft.json()['id']}/void",
        headers=accounting_headers,
    )
    assert voided.status_code == 200
    assert voided.json()["status"] == JournalEntryStatus.VOID.value

    filtered = client.get(
        f"{ACCOUNTING_URL}/journal-entries",
        headers=accounting_headers,
        params={"status": "POSTED", "date_from": "2026-11-01"},
    )
    assert filtered.status_code == 200
    assert {item["id"] for item in filtered.json()} == {entry_id, reversal.json()["id"]}


def test_unbalanced_entry_is_rejected_on_post(
    client: TestClient,
    accounting_headers: dict[str, str],
    chart: dict[str, int],
) -> None:
    """El borrador se acepta, pero publicarlo sin partida doble responde 400."""
    created = client.post(
        f"{ACCOUNTING_URL}/journal-entries",
        headers=accounting_headers,
        json={
            "code": "ASI-HTTP-0003",
            "description": "Asiento desbalanceado",
            "items": [
                {"account_id": chart["cash"], "debit": "500.00"},
                {"account_id": chart["revenue"], "credit": "450.00"},
            ],
        },
    )
    assert created.status_code == 201

    rejected = client.post(
        f"{ACCOUNTING_URL}/journal-entries/{created.json()['id']}/post",
        headers=accounting_headers,
    )
    assert rejected.status_code == 400
    assert "equilibrado" in rejected.json()["detail"]

    detail = client.get(
        f"{ACCOUNTING_URL}/journal-entries/{created.json()['id']}",
        headers=accounting_headers,
    )
    assert detail.json()["status"] == JournalEntryStatus.DRAFT.value


# --------------------------------------------------------------------------- #
# Cartera y pagos por HTTP
# --------------------------------------------------------------------------- #


def test_receivable_payment_flow_over_http(
    client: TestClient,
    admin_headers: dict[str, str],
    chart: dict[str, int],
    receivable: AccountReceivable,
) -> None:
    """Listado, detalle, abono parcial, pago final y validación de exceso."""
    listing = client.get(
        f"{ACCOUNTING_URL}/receivables",
        headers=admin_headers,
        params={"third_party_id": receivable.customer_id, "status": "PENDING"},
    )
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [receivable.id]

    detail = client.get(
        f"{ACCOUNTING_URL}/receivables/{receivable.id}", headers=admin_headers
    )
    assert detail.status_code == 200
    assert detail.json()["total_amount"] == "1000.00"

    partial = client.post(
        f"{ACCOUNTING_URL}/receivables/{receivable.id}/payments",
        headers=admin_headers,
        json={"amount": "400.00", "reference": "COB-001"},
    )
    assert partial.status_code == 201, partial.text
    assert partial.json()["receivable_id"] == receivable.id
    assert partial.json()["amount"] == "400.00"
    assert partial.json()["journal_entry_id"] is not None

    after_partial = client.get(
        f"{ACCOUNTING_URL}/receivables/{receivable.id}", headers=admin_headers
    )
    assert after_partial.json()["paid_amount"] == "400.00"
    assert after_partial.json()["status"] == AccountBalanceStatus.PARTIALLY_PAID.value

    excessive = client.post(
        f"{ACCOUNTING_URL}/payments",
        headers=admin_headers,
        json={"receivable_id": receivable.id, "amount": "700.00"},
    )
    assert excessive.status_code == 400
    assert "excede" in excessive.json()["detail"]

    final = client.post(
        f"{ACCOUNTING_URL}/payments",
        headers=admin_headers,
        json={"receivable_id": receivable.id, "amount": "600.00"},
    )
    assert final.status_code == 201, final.text
    settled = client.get(
        f"{ACCOUNTING_URL}/receivables/{receivable.id}", headers=admin_headers
    )
    assert settled.json()["paid_amount"] == "1000.00"
    assert settled.json()["status"] == AccountBalanceStatus.PAID.value

    history = client.get(
        f"{ACCOUNTING_URL}/payments",
        headers=admin_headers,
        params={"receivable_id": receivable.id},
    )
    assert history.status_code == 200
    assert len(history.json()) == 2


def test_payable_payment_flow_over_http(
    client: TestClient,
    accounting_headers: dict[str, str],
    chart: dict[str, int],
    payable: AccountPayable,
) -> None:
    """La CxP se liquida con un pago y su asiento trazable."""
    listing = client.get(
        f"{ACCOUNTING_URL}/payables",
        headers=accounting_headers,
        params={"supplier_id": payable.supplier_id},
    )
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [payable.id]

    payment = client.post(
        f"{ACCOUNTING_URL}/payables/{payable.id}/payments",
        headers=accounting_headers,
        json={"amount": "800.00", "reference": "PAG-001"},
    )
    assert payment.status_code == 201, payment.text
    assert payment.json()["payable_id"] == payable.id

    detail = client.get(
        f"{ACCOUNTING_URL}/payables/{payable.id}", headers=accounting_headers
    )
    assert detail.json()["paid_amount"] == "800.00"
    assert detail.json()["status"] == AccountBalanceStatus.PAID.value


# --------------------------------------------------------------------------- #
# Reportes por HTTP
# --------------------------------------------------------------------------- #


def test_reports_over_http_respect_posted_entries_and_periods(
    client: TestClient,
    db_session: Session,
    accounting_headers: dict[str, str],
    chart: dict[str, int],
) -> None:
    """Los reportes HTTP solo ven ``POSTED`` y respetan el rango/periodo."""
    _posted_sale(db_session, chart, "1200.00")

    draft = create_journal_entry(
        db_session,
        JournalEntryCreate(
            code="ASI-HTTP-DRAFT",
            entry_date=date(2026, 11, 16),
            description="Borrador que no debe impactar",
            items=[
                JournalItemCreate(account_id=chart["cash"], debit=Decimal("999.00")),
                JournalItemCreate(
                    account_id=chart["revenue"], credit=Decimal("999.00")
                ),
            ],
        ),
    )
    assert draft.status is JournalEntryStatus.DRAFT

    period = AccountingPeriod(
        name="2026-11",
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
        is_closed=False,
    )
    db_session.add(period)
    db_session.commit()

    trial = client.get(
        f"{ACCOUNTING_URL}/reports/trial-balance",
        headers=accounting_headers,
        params={"period_id": period.id},
    )
    assert trial.status_code == 200, trial.text
    assert trial.json()["total_debit"] == "1200.00"
    assert trial.json()["total_credit"] == "1200.00"

    balance = client.get(
        f"{ACCOUNTING_URL}/reports/balance-sheet",
        headers=accounting_headers,
        params={"period_name": "2026-11"},
    )
    assert balance.status_code == 200
    assert balance.json()["total_assets"] == "1200.00"
    assert balance.json()["difference"] == "1200.00"

    income = client.get(
        f"{ACCOUNTING_URL}/reports/income-statement",
        headers=accounting_headers,
        params={"date_from": "2026-11-01", "date_to": "2026-11-30"},
    )
    assert income.status_code == 200
    assert income.json()["total_revenue"] == "1200.00"
    assert income.json()["net_income"] == "1200.00"

    outside = client.get(
        f"{ACCOUNTING_URL}/reports/trial-balance",
        headers=accounting_headers,
        params={"date_from": "2026-12-01", "date_to": "2026-12-31"},
    )
    assert outside.json()["total_debit"] == "0.00"
