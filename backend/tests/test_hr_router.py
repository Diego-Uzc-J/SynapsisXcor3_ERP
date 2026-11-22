"""Pruebas HTTP y RBAC del router del módulo de Recursos Humanos.

Cubren los contratos de ``specs/hr_spec.md`` (sección 4) a través de la API
real (``TestClient``): empleados, contratos, asistencia y nómina, incluida la
aprobación con asiento contable atómico.

Verifican también la matriz RBAC del manifiesto: 401 sin token, 403 para roles
sin permiso ``hr`` y 200/201 para ``HR`` y ``ADMINISTRATOR``.
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
from src.core.security import (
    FORBIDDEN_DETAIL,
    create_access_token,
    hash_password,
)  # noqa: E402
from src.main import app  # noqa: E402
from src.modules.accounting.models import (  # noqa: E402
    AccountType,
    JournalEntry,
    JournalEntryStatus,
)
from src.modules.accounting.schemas import AccountCreate  # noqa: E402
from src.modules.accounting.service import create_account  # noqa: E402
from src.modules.users.models import Role, RoleEnum, User  # noqa: E402

HR_URL = "/api/v1/hr"
_HASHED_PASSWORD = hash_password("Hr1234567!")


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
def users(db_session: Session) -> dict[str, User]:
    admin_role = _role(db_session, RoleEnum.ADMINISTRATOR, ["*"])
    hr_role = _role(db_session, RoleEnum.HR, ["hr"])
    sales_role = _role(db_session, RoleEnum.SALES, ["sales"])
    db_session.commit()

    return {
        "admin": _user(
            db_session,
            role=admin_role,
            username="rrhh_admin",
            email="rrhh-admin@example.com",
        ),
        "hr": _user(
            db_session,
            role=hr_role,
            username="gestor_rrhh",
            email="gestor-rrhh@example.com",
        ),
        "sales": _user(
            db_session,
            role=sales_role,
            username="vendedor_hr",
            email="vendedor-hr@example.com",
        ),
    }


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture()
def hr_headers(users: dict[str, User]) -> dict[str, str]:
    return _headers(users["hr"])


@pytest.fixture()
def admin_headers(users: dict[str, User]) -> dict[str, str]:
    return _headers(users["admin"])


@pytest.fixture()
def sales_headers(users: dict[str, User]) -> dict[str, str]:
    return _headers(users["sales"])


# --------------------------------------------------------------------------- #
# Utilidades de payload
# --------------------------------------------------------------------------- #


def employee_payload(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "identification_number": "900123456-1",
        "first_name": "Ana",
        "last_name": "Pérez",
        "email": "ana.perez@example.com",
        "birth_date": "1990-05-10",
        "hire_date": "2026-01-01",
    }
    data.update(overrides)
    return data


def contract_payload(employee_id: int, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "employee_id": employee_id,
        "contract_type": "INDEFINITE",
        "base_salary": "3000000.00",
        "start_date": "2026-01-01",
    }
    data.update(overrides)
    return data


def attendance_payload(employee_id: int, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "employee_id": employee_id,
        "date": "2026-03-15",
        "status": "PRESENT",
        "overtime_hours": "2.50",
    }
    data.update(overrides)
    return data


def payroll_payload(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "code": "NOM-2026-03",
        "period_start": "2026-03-01",
        "period_end": "2026-03-31",
    }
    data.update(overrides)
    return data


def create_employee_api(client: TestClient, headers: dict[str, str]) -> int:
    response = client.post(f"{HR_URL}/employees", json=employee_payload(), headers=headers)
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def seed_chart(db_session: Session) -> None:
    """PUC mínimo para la contabilización de nómina al aprobar."""
    create_account(
        db_session,
        AccountCreate(
            code="5100", name="Gastos de personal", account_type=AccountType.EXPENSE
        ),
    )
    create_account(
        db_session,
        AccountCreate(
            code="220505",
            name="Cuentas por pagar de nómina",
            account_type=AccountType.LIABILITY,
        ),
    )


PROTECTED_CALLS: list[tuple[str, str]] = [
    ("GET", f"{HR_URL}/employees"),
    ("POST", f"{HR_URL}/employees"),
    ("GET", f"{HR_URL}/employees/1"),
    ("PATCH", f"{HR_URL}/employees/1"),
    ("POST", f"{HR_URL}/contracts"),
    ("GET", f"{HR_URL}/contracts/employee/1"),
    ("POST", f"{HR_URL}/attendance"),
    ("GET", f"{HR_URL}/attendance"),
    ("POST", f"{HR_URL}/payrolls"),
    ("GET", f"{HR_URL}/payrolls"),
    ("GET", f"{HR_URL}/payrolls/1"),
    ("POST", f"{HR_URL}/payrolls/1/approve"),
]


# --------------------------------------------------------------------------- #
# Contratos de API y RBAC
# --------------------------------------------------------------------------- #


EXPECTED_PATHS = {
    "/api/v1/hr/employees",
    "/api/v1/hr/employees/{employee_id}",
    "/api/v1/hr/contracts",
    "/api/v1/hr/contracts/employee/{employee_id}",
    "/api/v1/hr/attendance",
    "/api/v1/hr/payrolls",
    "/api/v1/hr/payrolls/{payroll_run_id}",
    "/api/v1/hr/payrolls/{payroll_run_id}/approve",
}


def test_openapi_documents_hr_routes(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert EXPECTED_PATHS <= set(schema["paths"])

    operations = {
        (method, path)
        for path, methods in schema["paths"].items()
        if path.startswith("/api/v1/hr/")
        for method in methods
    }
    assert {
        ("get", f"{HR_URL}/employees"),
        ("post", f"{HR_URL}/employees"),
        ("get", f"{HR_URL}/employees/{{employee_id}}"),
        ("patch", f"{HR_URL}/employees/{{employee_id}}"),
        ("post", f"{HR_URL}/contracts"),
        ("get", f"{HR_URL}/contracts/employee/{{employee_id}}"),
        ("post", f"{HR_URL}/attendance"),
        ("get", f"{HR_URL}/attendance"),
        ("post", f"{HR_URL}/payrolls"),
        ("get", f"{HR_URL}/payrolls"),
        ("get", f"{HR_URL}/payrolls/{{payroll_run_id}}"),
        ("post", f"{HR_URL}/payrolls/{{payroll_run_id}}/approve"),
    } == operations


@pytest.mark.parametrize(("method", "path"), PROTECTED_CALLS)
def test_rbac_anonymous_request_is_401(
    client: TestClient, method: str, path: str
) -> None:
    response = client.request(method, path, json={})
    assert response.status_code == 401


@pytest.mark.parametrize(("method", "path"), PROTECTED_CALLS)
def test_rbac_unauthorized_role_is_403(
    client: TestClient, sales_headers: dict[str, str], method: str, path: str
) -> None:
    response = client.request(method, path, json={}, headers=sales_headers)
    assert response.status_code == 403
    assert response.json()["detail"] == FORBIDDEN_DETAIL


@pytest.mark.parametrize("headers_name", ["hr_headers", "admin_headers"])
def test_rbac_authorized_roles_can_list_employees(
    client: TestClient, request: pytest.FixtureRequest, headers_name: str
) -> None:
    headers = request.getfixturevalue(headers_name)
    response = client.get(f"{HR_URL}/employees", headers=headers)
    assert response.status_code == 200
    assert response.json() == []


# --------------------------------------------------------------------------- #
# Empleados
# --------------------------------------------------------------------------- #


def test_employee_endpoints_crud_and_domain_errors(
    client: TestClient, hr_headers: dict[str, str]
) -> None:
    created = client.post(
        f"{HR_URL}/employees", json=employee_payload(), headers=hr_headers
    )
    assert created.status_code == 201, created.text
    employee_id = created.json()["id"]

    listing = client.get(f"{HR_URL}/employees", headers=hr_headers)
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [employee_id]

    active = client.get(
        f"{HR_URL}/employees", params={"is_active": "true"}, headers=hr_headers
    )
    assert active.status_code == 200
    assert len(active.json()) == 1
    inactive = client.get(
        f"{HR_URL}/employees", params={"is_active": "false"}, headers=hr_headers
    )
    assert inactive.json() == []

    profile = client.get(f"{HR_URL}/employees/{employee_id}", headers=hr_headers)
    assert profile.status_code == 200
    assert profile.json()["contracts"] == []
    assert profile.json()["attendance_records"] == []

    patched = client.patch(
        f"{HR_URL}/employees/{employee_id}",
        json={"phone": "+57 300 123 4567"},
        headers=hr_headers,
    )
    assert patched.status_code == 200
    assert patched.json()["phone"] == "+57 300 123 4567"

    duplicate = client.post(
        f"{HR_URL}/employees", json=employee_payload(), headers=hr_headers
    )
    assert duplicate.status_code == 400
    assert "900123456-1" in duplicate.json()["detail"]

    missing = client.get(f"{HR_URL}/employees/9999", headers=hr_headers)
    assert missing.status_code == 404
    assert "9999" in missing.json()["detail"]


def test_employee_payload_validation_is_422(
    client: TestClient, hr_headers: dict[str, str]
) -> None:
    extra = client.post(
        f"{HR_URL}/employees",
        json=employee_payload(unexpected="x"),
        headers=hr_headers,
    )
    assert extra.status_code == 422

    bad_dates = client.post(
        f"{HR_URL}/employees",
        json=employee_payload(hire_date="1989-01-01"),
        headers=hr_headers,
    )
    assert bad_dates.status_code == 422

    employee_id = create_employee_api(client, hr_headers)
    empty_patch = client.patch(
        f"{HR_URL}/employees/{employee_id}", json={}, headers=hr_headers
    )
    assert empty_patch.status_code == 422

    bad_path = client.get(f"{HR_URL}/employees/0", headers=hr_headers)
    assert bad_path.status_code == 422


# --------------------------------------------------------------------------- #
# Contratos
# --------------------------------------------------------------------------- #


def test_contract_endpoints(client: TestClient, hr_headers: dict[str, str]) -> None:
    employee_id = create_employee_api(client, hr_headers)

    created = client.post(
        f"{HR_URL}/contracts",
        json=contract_payload(employee_id),
        headers=hr_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["base_salary"] == "3000000.00"

    history = client.get(
        f"{HR_URL}/contracts/employee/{employee_id}", headers=hr_headers
    )
    assert history.status_code == 200
    assert len(history.json()) == 1

    active = client.get(
        f"{HR_URL}/contracts/employee/{employee_id}",
        params={"active_only": "true"},
        headers=hr_headers,
    )
    assert len(active.json()) == 1

    duplicate = client.post(
        f"{HR_URL}/contracts",
        json=contract_payload(employee_id, start_date="2026-02-01"),
        headers=hr_headers,
    )
    assert duplicate.status_code == 400
    assert "contrato vigente" in duplicate.json()["detail"]

    missing = client.get(f"{HR_URL}/contracts/employee/9999", headers=hr_headers)
    assert missing.status_code == 404

    unknown_employee = client.post(
        f"{HR_URL}/contracts", json=contract_payload(9999), headers=hr_headers
    )
    assert unknown_employee.status_code == 404


def test_contract_rejects_float_salary(client: TestClient, hr_headers: dict[str, str]) -> None:
    employee_id = create_employee_api(client, hr_headers)
    response = client.post(
        f"{HR_URL}/contracts",
        json=contract_payload(employee_id, base_salary=3000000.5),
        headers=hr_headers,
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# Asistencia
# --------------------------------------------------------------------------- #


def test_attendance_endpoints(client: TestClient, hr_headers: dict[str, str]) -> None:
    employee_id = create_employee_api(client, hr_headers)

    created = client.post(
        f"{HR_URL}/attendance",
        json=attendance_payload(employee_id),
        headers=hr_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["overtime_hours"] == "2.50"

    by_employee = client.get(
        f"{HR_URL}/attendance", params={"employee_id": employee_id}, headers=hr_headers
    )
    assert by_employee.status_code == 200
    assert len(by_employee.json()) == 1

    by_date = client.get(
        f"{HR_URL}/attendance",
        params={"date": "2026-03-15"},
        headers=hr_headers,
    )
    assert len(by_date.json()) == 1

    by_range = client.get(
        f"{HR_URL}/attendance",
        params={"start_date": "2026-03-01", "end_date": "2026-03-31"},
        headers=hr_headers,
    )
    assert len(by_range.json()) == 1

    outside = client.get(
        f"{HR_URL}/attendance",
        params={"start_date": "2026-04-01"},
        headers=hr_headers,
    )
    assert outside.json() == []

    missing = client.get(
        f"{HR_URL}/attendance", params={"employee_id": 9999}, headers=hr_headers
    )
    assert missing.status_code == 404

    unknown_employee = client.post(
        f"{HR_URL}/attendance",
        json=attendance_payload(9999),
        headers=hr_headers,
    )
    assert unknown_employee.status_code == 404


def test_attendance_payload_validation_is_422(
    client: TestClient, hr_headers: dict[str, str]
) -> None:
    employee_id = create_employee_api(client, hr_headers)

    negative_hours = client.post(
        f"{HR_URL}/attendance",
        json=attendance_payload(employee_id, overtime_hours="-1.00"),
        headers=hr_headers,
    )
    assert negative_hours.status_code == 422

    float_hours = client.post(
        f"{HR_URL}/attendance",
        json=attendance_payload(employee_id, overtime_hours=2.5),
        headers=hr_headers,
    )
    assert float_hours.status_code == 422

    bad_status = client.post(
        f"{HR_URL}/attendance",
        json=attendance_payload(employee_id, status="UNKNOWN"),
        headers=hr_headers,
    )
    assert bad_status.status_code == 422


# --------------------------------------------------------------------------- #
# Nómina
# --------------------------------------------------------------------------- #


def seed_payroll(client: TestClient, hr_headers: dict[str, str]) -> int:
    employee_id = create_employee_api(client, hr_headers)
    contract = client.post(
        f"{HR_URL}/contracts",
        json=contract_payload(employee_id),
        headers=hr_headers,
    )
    assert contract.status_code == 201, contract.text
    run = client.post(
        f"{HR_URL}/payrolls", json=payroll_payload(), headers=hr_headers
    )
    assert run.status_code == 201, run.text
    return int(run.json()["id"])


def test_payroll_endpoints_and_atomic_approval(
    client: TestClient, hr_headers: dict[str, str], db_session: Session
) -> None:
    seed_chart(db_session)
    payroll_id = seed_payroll(client, hr_headers)

    listing = client.get(f"{HR_URL}/payrolls", headers=hr_headers)
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [payroll_id]
    assert listing.json()[0]["status"] == "DRAFT"

    filtered = client.get(
        f"{HR_URL}/payrolls", params={"status": "DRAFT"}, headers=hr_headers
    )
    assert len(filtered.json()) == 1
    adjustments = client.get(
        f"{HR_URL}/payrolls", params={"is_adjustment": "true"}, headers=hr_headers
    )
    assert adjustments.json() == []

    detail = client.get(f"{HR_URL}/payrolls/{payroll_id}", headers=hr_headers)
    assert detail.status_code == 200
    assert len(detail.json()["payslips"]) == 1
    assert detail.json()["total_net"] == "3000000.00"

    duplicate = client.post(
        f"{HR_URL}/payrolls", json=payroll_payload(), headers=hr_headers
    )
    assert duplicate.status_code == 400
    assert "NOM-2026-03" in duplicate.json()["detail"]

    approved = client.post(
        f"{HR_URL}/payrolls/{payroll_id}/approve", headers=hr_headers
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"
    assert approved.json()["approved_at"] is not None

    entry = db_session.scalar(
        select(JournalEntry).where(
            JournalEntry.reference_document == "NOM-2026-03"
        )
    )
    assert entry is not None
    assert entry.status is JournalEntryStatus.POSTED

    reapproved = client.post(
        f"{HR_URL}/payrolls/{payroll_id}/approve", headers=hr_headers
    )
    assert reapproved.status_code == 409

    approved_list = client.get(
        f"{HR_URL}/payrolls", params={"status": "APPROVED"}, headers=hr_headers
    )
    assert len(approved_list.json()) == 1

    missing = client.get(f"{HR_URL}/payrolls/9999", headers=hr_headers)
    assert missing.status_code == 404
    missing_approval = client.post(
        f"{HR_URL}/payrolls/9999/approve", headers=hr_headers
    )
    assert missing_approval.status_code == 404


def test_payroll_approval_rolls_back_without_chart(
    client: TestClient, hr_headers: dict[str, str], db_session: Session
) -> None:
    payroll_id = seed_payroll(client, hr_headers)  # PUC sin sembrar

    response = client.post(
        f"{HR_URL}/payrolls/{payroll_id}/approve", headers=hr_headers
    )
    assert response.status_code == 400
    assert "NOM-2026-03" in response.json()["detail"]

    detail = client.get(f"{HR_URL}/payrolls/{payroll_id}", headers=hr_headers)
    assert detail.json()["status"] == "DRAFT"
    assert detail.json()["approved_at"] is None
    assert (
        db_session.scalar(
            select(JournalEntry).where(
                JournalEntry.reference_document == "NOM-2026-03"
            )
        )
        is None
    )


def test_payroll_payload_validation_is_422(
    client: TestClient, hr_headers: dict[str, str]
) -> None:
    reversed_period = client.post(
        f"{HR_URL}/payrolls",
        json=payroll_payload(period_start="2026-04-01"),
        headers=hr_headers,
    )
    assert reversed_period.status_code == 422

    bad_code = client.post(
        f"{HR_URL}/payrolls",
        json=payroll_payload(code="nom-2026-03"),
        headers=hr_headers,
    )
    assert bad_code.status_code == 422

    extra = client.post(
        f"{HR_URL}/payrolls",
        json=payroll_payload(total_net="100.00"),
        headers=hr_headers,
    )
    assert extra.status_code == 422

    bad_path = client.get(f"{HR_URL}/payrolls/abc", headers=hr_headers)
    assert bad_path.status_code == 422


def test_payroll_totals_use_decimal_precision(
    client: TestClient, hr_headers: dict[str, str], db_session: Session
) -> None:
    seed_chart(db_session)
    employee_id = create_employee_api(client, hr_headers)
    client.post(
        f"{HR_URL}/contracts",
        json=contract_payload(employee_id, base_salary="1000000.01"),
        headers=hr_headers,
    )
    run = client.post(
        f"{HR_URL}/payrolls", json=payroll_payload(code="NOM-DEC-01"), headers=hr_headers
    )
    assert run.status_code == 201
    assert Decimal(run.json()["total_net"]) == Decimal("1000000.01")
