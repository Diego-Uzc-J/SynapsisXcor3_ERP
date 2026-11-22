"""Criterios de aceptación del módulo ``hr`` (specs/hr_spec.md, sección 5).

Los siete escenarios BDD se ejecutan con ``pytest`` y ``httpx.AsyncClient``
contra los routers reales registrados en ``src.main`` bajo ``/api/v1/hr``.
La capa HTTP se ejercita con el cliente asíncrono; solo se accede directamente
al servicio cuando el contrato HTTP no expone la operación (deducciones de
nómina) o cuando el escenario exige simular una modificación directa/estado
``PAID`` o un fallo forzado en ``accounting``.
"""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
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
from src.main import app as production_app  # noqa: E402
from src.modules.accounting.models import (  # noqa: E402
    AccountType,
    JournalEntry,
    JournalEntryStatus,
)
from src.modules.accounting.schemas import AccountCreate  # noqa: E402
from src.modules.accounting.service import create_account  # noqa: E402
from src.modules.hr import service as hr_service  # noqa: E402
from src.modules.hr.models import PayrollRun, PayrollRunStatus  # noqa: E402
from src.modules.hr.service import (  # noqa: E402
    ImmutablePayrollRunError,
    recalculate_payroll_run,
    set_payroll_run_status,
)
from src.modules.users.models import Role, RoleEnum, User  # noqa: E402

pytestmark = pytest.mark.anyio

HR_URL = "/api/v1/hr"
_HASHED_PASSWORD = hash_password("Acceptance1234!")


# --------------------------------------------------------------------------- #
# Fixtures de base de datos, app y cliente HTTP asíncrono
# --------------------------------------------------------------------------- #


@pytest.fixture()
def anyio_backend() -> str:
    """Fuerza el backend asyncio; trio no forma parte del stack del ERP."""
    return "asyncio"


@pytest.fixture()
def db_engine() -> Iterator[Engine]:
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
def session_factory(db_engine: Engine) -> sessionmaker[Session]:
    """Fábrica compartida por la app, las siembras y las aserciones."""
    return sessionmaker(bind=db_engine, expire_on_commit=False)


@pytest.fixture()
def app(session_factory: sessionmaker[Session]) -> Iterator[FastAPI]:
    """App de producción con ``get_db`` redirigido a la base de prueba."""

    def override_get_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    production_app.dependency_overrides[get_db] = override_get_db
    try:
        yield production_app
    finally:
        production_app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Cliente HTTP asíncrono contra la app ASGI real."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        timeout=30.0,
    ) as async_client:
        yield async_client


@pytest.fixture()
def users(session_factory: sessionmaker[Session]) -> dict[RoleEnum, uuid.UUID]:
    """Un usuario activo por rol relevante para la matriz RBAC."""
    user_ids: dict[RoleEnum, uuid.UUID] = {}
    with session_factory() as db:
        roles: dict[RoleEnum, Role] = {}
        for role_enum in (
            RoleEnum.ADMINISTRATOR,
            RoleEnum.HR,
            RoleEnum.SALES,
            RoleEnum.ACCOUNTING,
            RoleEnum.INVENTORY,
        ):
            role = db.scalar(select(Role).where(Role.name == role_enum))
            if role is None:
                role = Role(
                    name=role_enum,
                    description=role_enum.value,
                    allowed_modules=["*"] if role_enum is RoleEnum.ADMINISTRATOR else [role_enum.value],
                )
                db.add(role)
                db.flush()
            roles[role_enum] = role

        for role_enum, role in roles.items():
            user = User(
                email=f"{role_enum.value}@hr-acceptance.example.com",
                username=f"{role_enum.value}_hr_acceptance",
                full_name=f"{role_enum.value.title()} HR Acceptance",
                hashed_password=_HASHED_PASSWORD,
                role_id=role.id,
                is_active=True,
            )
            db.add(user)
            db.flush()
            user_ids[role_enum] = user.id
        db.commit()
    return user_ids


@pytest.fixture()
def chart(session_factory: sessionmaker[Session]) -> None:
    """PUC mínimo para la contabilización de nómina al aprobar."""
    with session_factory() as db:
        create_account(
            db,
            AccountCreate(
                code="5100",
                name="Gastos de personal",
                account_type=AccountType.EXPENSE,
            ),
        )
        create_account(
            db,
            AccountCreate(
                code="220505",
                name="Cuentas por pagar de nómina",
                account_type=AccountType.LIABILITY,
            ),
        )


# --------------------------------------------------------------------------- #
# Utilidades HTTP
# --------------------------------------------------------------------------- #


def _auth(user_ids: dict[RoleEnum, uuid.UUID], role: RoleEnum) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_ids[role])}"}


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
        "overtime_hours": "8.00",
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


async def create_employee(
    client: httpx.AsyncClient, headers: dict[str, str], **overrides: Any
) -> int:
    response = await client.post(
        f"{HR_URL}/employees", json=employee_payload(**overrides), headers=headers
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


async def create_contract(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    employee_id: int,
    **overrides: Any,
) -> int:
    response = await client.post(
        f"{HR_URL}/contracts",
        json=contract_payload(employee_id, **overrides),
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


async def create_payroll(
    client: httpx.AsyncClient, headers: dict[str, str], **overrides: Any
) -> int:
    response = await client.post(
        f"{HR_URL}/payrolls", json=payroll_payload(**overrides), headers=headers
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


async def complete_employee(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    identification: str = "900123456-1",
) -> int:
    """Empleado con contrato activo vigente en marzo de 2026."""
    employee_id = await create_employee(
        client, headers, identification_number=identification
    )
    await create_contract(client, headers, employee_id)
    return employee_id


def journal_entries_for(
    session_factory: sessionmaker[Session], code: str
) -> list[JournalEntry]:
    with session_factory() as db:
        return list(
            db.scalars(
                select(JournalEntry)
                .where(JournalEntry.reference_document == code)
                .order_by(JournalEntry.id)
            ).all()
        )


# --------------------------------------------------------------------------- #
# Escenario 1: generación y cálculo exitoso de nómina
# --------------------------------------------------------------------------- #


async def test_scenario_1_payroll_generation_and_payslip_calculation(
    client: httpx.AsyncClient,
    session_factory: sessionmaker[Session],
    users: dict[RoleEnum, uuid.UUID],
) -> None:
    """Dado contrato activo + asistencia, el Payslip refleja base, extra, deducciones y neto."""
    headers = _auth(users, RoleEnum.HR)
    employee_id = await complete_employee(client, headers)

    attendance = await client.post(
        f"{HR_URL}/attendance",
        json=attendance_payload(employee_id, overtime_hours="8.00"),
        headers=headers,
    )
    assert attendance.status_code == 201, attendance.text

    payroll_id = await create_payroll(client, headers)
    detail = await client.get(f"{HR_URL}/payrolls/{payroll_id}", headers=headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "DRAFT"
    assert len(body["payslips"]) == 1

    payslip = body["payslips"][0]
    # 31 días => prorrateo 30/30; 8 h extra => 8 * 3.000.000 / 240 = 100.000.
    assert payslip["base_salary"] == "3000000.00"
    assert payslip["overtime_pay"] == "100000.00"
    assert payslip["earnings"] == "3100000.00"
    assert payslip["deductions"] == "0.00"
    assert payslip["net_pay"] == "3100000.00"

    # El contrato HTTP no expone deducciones (spec no define su fuente): se
    # aplican por servicio para verificar el cálculo del neto a pagar.
    with session_factory() as db:
        recalculate_payroll_run(
            db, payroll_id, deductions={employee_id: Decimal("100000.00")}
        )

    detail = await client.get(f"{HR_URL}/payrolls/{payroll_id}", headers=headers)
    payslip = detail.json()["payslips"][0]
    assert payslip["earnings"] == "3100000.00"
    assert payslip["deductions"] == "100000.00"
    assert payslip["net_pay"] == "3000000.00"
    assert detail.json()["total_earnings"] == "3100000.00"
    assert detail.json()["total_deductions"] == "100000.00"
    assert detail.json()["total_net"] == "3000000.00"


# --------------------------------------------------------------------------- #
# Escenario 2: restricción de múltiples contratos activos
# --------------------------------------------------------------------------- #


async def test_scenario_2_second_active_contract_is_rejected(
    client: httpx.AsyncClient,
    users: dict[RoleEnum, uuid.UUID],
) -> None:
    """Un segundo contrato activo para el mismo empleado debe dar 400."""
    headers = _auth(users, RoleEnum.HR)
    employee_id = await create_employee(client, headers)
    first = await create_contract(client, headers, employee_id)
    assert first > 0

    second = await client.post(
        f"{HR_URL}/contracts",
        json=contract_payload(employee_id, start_date="2026-02-01"),
        headers=headers,
    )
    assert second.status_code == 400
    assert "contrato vigente" in second.json()["detail"]

    # Un contrato inactivo sí es permitido como histórico.
    historic = await client.post(
        f"{HR_URL}/contracts",
        json=contract_payload(
            employee_id,
            start_date="2025-01-01",
            end_date="2025-12-31",
            is_active=False,
        ),
        headers=headers,
    )
    assert historic.status_code == 201


# --------------------------------------------------------------------------- #
# Escenario 3: inmutabilidad de nómina APPROVED / PAID
# --------------------------------------------------------------------------- #


async def test_scenario_3_approved_and_paid_payrolls_are_immutable(
    client: httpx.AsyncClient,
    session_factory: sessionmaker[Session],
    users: dict[RoleEnum, uuid.UUID],
    chart: None,
) -> None:
    """APPROVED y PAID rechazan recálculo, cambio de estado y re-aprobación."""
    headers = _auth(users, RoleEnum.HR)
    await complete_employee(client, headers, identification="900111111-1")
    approved_id = await create_payroll(client, headers, code="NOM-APR-01")

    approved = await client.post(
        f"{HR_URL}/payrolls/{approved_id}/approve", headers=headers
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"

    with session_factory() as db:
        original_totals = (
            db.get(PayrollRun, approved_id).total_net,
        )

    reapproved = await client.post(
        f"{HR_URL}/payrolls/{approved_id}/approve", headers=headers
    )
    assert reapproved.status_code == 409

    with pytest.raises(ImmutablePayrollRunError):
        with session_factory() as db:
            recalculate_payroll_run(
                db, approved_id, deductions={1: Decimal("1.00")}
            )
    with pytest.raises(ImmutablePayrollRunError):
        with session_factory() as db:
            set_payroll_run_status(db, approved_id, PayrollRunStatus.PAID)

    # Un periodo PAID tampoco se puede volver a aprobar ni recalcular.
    paid_id = await create_payroll(
        client,
        headers,
        code="NOM-PAID-01",
        period_start="2026-04-01",
        period_end="2026-04-30",
    )
    with session_factory() as db:
        set_payroll_run_status(db, paid_id, PayrollRunStatus.PAID)

    paid_approval = await client.post(
        f"{HR_URL}/payrolls/{paid_id}/approve", headers=headers
    )
    assert paid_approval.status_code == 409
    with pytest.raises(ImmutablePayrollRunError):
        with session_factory() as db:
            recalculate_payroll_run(db, paid_id)

    with session_factory() as db:
        approved_row = db.get(PayrollRun, approved_id)
        paid_row = db.get(PayrollRun, paid_id)
        assert (approved_row.total_net,) == original_totals
        assert approved_row.status is PayrollRunStatus.APPROVED
        assert paid_row.status is PayrollRunStatus.PAID


# --------------------------------------------------------------------------- #
# Escenario 4: aprobación atómica con rollback
# --------------------------------------------------------------------------- #


async def test_scenario_4_atomic_approval_posts_entry_and_rolls_back_on_failure(
    client: httpx.AsyncClient,
    session_factory: sessionmaker[Session],
    users: dict[RoleEnum, uuid.UUID],
    chart: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /approve publica el asiento y hace rollback completo si falla contabilidad."""
    headers = _auth(users, RoleEnum.HR)
    await complete_employee(client, headers, identification="900222222-2")
    run_id = await create_payroll(client, headers, code="NOM-OK-01")

    approved = await client.post(f"{HR_URL}/payrolls/{run_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"
    assert approved.json()["approved_at"] is not None

    entries = journal_entries_for(session_factory, "NOM-OK-01")
    assert len(entries) == 1
    entry = entries[0]
    assert entry.status is JournalEntryStatus.POSTED
    assert entry.code.startswith("ASI-NOM-")
    assert entry.description == "Nomina NOM-OK-01"

    # Segundo periodo: se fuerza un error DESPUÉS de construir el asiento para
    # comprobar que la transacción de RRHH descarta también ese movimiento.
    failing_id = await create_payroll(
        client,
        headers,
        code="NOM-FAIL-01",
        period_start="2026-04-01",
        period_end="2026-04-30",
    )
    original_post = hr_service.post_payroll_run_accounting

    def failing_post(*args: Any, **kwargs: Any) -> Any:
        result = original_post(*args, **kwargs)
        raise RuntimeError("fallo forzado en accounting")

    monkeypatch.setattr(hr_service, "post_payroll_run_accounting", failing_post)

    failed = await client.post(
        f"{HR_URL}/payrolls/{failing_id}/approve", headers=headers
    )
    assert failed.status_code == 400
    assert "NOM-FAIL-01" in failed.json()["detail"]

    with session_factory() as db:
        rolled_back = db.get(PayrollRun, failing_id)
        assert rolled_back.status is PayrollRunStatus.DRAFT
        assert rolled_back.approved_at is None
    assert journal_entries_for(session_factory, "NOM-FAIL-01") == []

    monkeypatch.undo()
    recovered = await client.post(
        f"{HR_URL}/payrolls/{failing_id}/approve", headers=headers
    )
    assert recovered.status_code == 200, recovered.text
    assert len(journal_entries_for(session_factory, "NOM-FAIL-01")) == 1


# --------------------------------------------------------------------------- #
# Escenario 5: unicidad de identificación y código de periodo
# --------------------------------------------------------------------------- #


async def test_scenario_5_duplicate_identification_and_payroll_code(
    client: httpx.AsyncClient,
    users: dict[RoleEnum, uuid.UUID],
) -> None:
    """Duplicar identification_number o PayrollRun.code se rechaza con 400."""
    headers = _auth(users, RoleEnum.HR)
    employee_id = await create_employee(client, headers)
    assert employee_id > 0

    duplicate_employee = await client.post(
        f"{HR_URL}/employees", json=employee_payload(), headers=headers
    )
    assert duplicate_employee.status_code == 400
    assert "900123456-1" in duplicate_employee.json()["detail"]

    await create_contract(client, headers, employee_id)
    first_run = await create_payroll(client, headers)
    assert first_run > 0

    duplicate_run = await client.post(
        f"{HR_URL}/payrolls", json=payroll_payload(), headers=headers
    )
    assert duplicate_run.status_code == 400
    assert "NOM-2026-03" in duplicate_run.json()["detail"]


# --------------------------------------------------------------------------- #
# Escenario 6: empleados inactivos o sin contrato activo
# --------------------------------------------------------------------------- #


async def test_scenario_6_inactive_or_contractless_employees_are_excluded(
    client: httpx.AsyncClient,
    users: dict[RoleEnum, uuid.UUID],
) -> None:
    """Solo empleados activos con contrato vigente generan Payslip."""
    headers = _auth(users, RoleEnum.HR)

    eligible = await create_employee(
        client, headers, identification_number="900300000-1"
    )
    await create_contract(client, headers, eligible)

    inactive = await create_employee(
        client,
        headers,
        identification_number="900300000-2",
        email="inactivo@example.com",
        is_active=False,
    )
    await create_contract(client, headers, inactive)

    contractless = await create_employee(
        client,
        headers,
        identification_number="900300000-3",
        email="sin-contrato@example.com",
    )

    old_contract = await create_employee(
        client,
        headers,
        identification_number="900300000-4",
        email="contrato-vencido@example.com",
    )
    await create_contract(
        client,
        headers,
        old_contract,
        start_date="2025-01-01",
        end_date="2025-12-31",
        is_active=False,
    )

    run_id = await create_payroll(client, headers, code="NOM-EXCL-01")
    detail = await client.get(f"{HR_URL}/payrolls/{run_id}", headers=headers)
    assert detail.status_code == 200
    payslips = detail.json()["payslips"]
    assert [payslip["employee_id"] for payslip in payslips] == [eligible]
    assert detail.json()["total_net"] == "3000000.00"


# --------------------------------------------------------------------------- #
# Escenario 7: RBAC
# --------------------------------------------------------------------------- #


async def test_scenario_7_rbac_denies_other_roles_and_anonymous_access(
    client: httpx.AsyncClient,
    users: dict[RoleEnum, uuid.UUID],
) -> None:
    """401 sin token y 403 para cualquier rol distinto de HR/ADMINISTRATOR."""
    protected: list[tuple[str, str, dict[str, Any]]] = [
        ("GET", f"{HR_URL}/employees", {}),
        ("POST", f"{HR_URL}/employees", employee_payload()),
        ("GET", f"{HR_URL}/employees/1", {}),
        ("PATCH", f"{HR_URL}/employees/1", {"first_name": "Nuevo"}),
        ("POST", f"{HR_URL}/contracts", contract_payload(1)),
        ("GET", f"{HR_URL}/contracts/employee/1", {}),
        ("POST", f"{HR_URL}/attendance", attendance_payload(1)),
        ("GET", f"{HR_URL}/attendance", {}),
        ("POST", f"{HR_URL}/payrolls", payroll_payload()),
        ("GET", f"{HR_URL}/payrolls", {}),
        ("GET", f"{HR_URL}/payrolls/1", {}),
        ("POST", f"{HR_URL}/payrolls/1/approve", {}),
    ]

    for method, path, payload in protected:
        response = await client.request(method, path, json=payload)
        assert response.status_code == 401, (method, path, response.text)

    for role in (RoleEnum.SALES, RoleEnum.ACCOUNTING, RoleEnum.INVENTORY):
        headers = _auth(users, role)
        for method, path, payload in protected:
            response = await client.request(
                method, path, json=payload, headers=headers
            )
            assert response.status_code == 403, (role, method, path, response.text)
            assert response.json()["detail"] == FORBIDDEN_DETAIL

    # Los roles autorizados sí pueden operar.
    for role in (RoleEnum.HR, RoleEnum.ADMINISTRATOR):
        headers = _auth(users, role)
        listed = await client.get(f"{HR_URL}/employees", headers=headers)
        assert listed.status_code == 200, (role, listed.text)

    created = await client.post(
        f"{HR_URL}/employees",
        json=employee_payload(identification_number="900400000-1"),
        headers=_auth(users, RoleEnum.ADMINISTRATOR),
    )
    assert created.status_code == 201, created.text
