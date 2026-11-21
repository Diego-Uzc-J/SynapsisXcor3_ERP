"""Pruebas de servicios de empleados y contratos del módulo ``hr``.

Cubren la regla 1 (exclusividad de contrato activo, escenario 2) y la regla 6
(unicidad del documento de identidad, escenario 5) de ``specs/hr_spec.md``,
además del filtrado por estado, el perfil con historial y la actualización
parcial. Todo usa SQLite en memoria, igual que el resto de la suite.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite://")

from src.core.database import Base  # noqa: E402
from src.modules.hr.models import (  # noqa: E402
    Attendance,
    AttendanceStatus,
    Contract,
    ContractType,
    Employee,
)
from src.modules.hr.schemas import (  # noqa: E402
    ContractCreate,
    EmployeeCreate,
    EmployeeUpdate,
)
from src.modules.hr.service import (  # noqa: E402
    ActiveContractError,
    DuplicateIdentificationError,
    HRServiceError,
    InvalidEmployeeDataError,
    ResourceNotFoundError,
    create_contract,
    create_employee,
    get_active_contract,
    get_employee,
    get_employee_profile,
    list_contracts_by_employee,
    list_employees,
    update_employee,
)

_TODAY = date(2026, 11, 21)


@pytest.fixture()
def db_session() -> Session:
    """Sesión SQLite aislada con el esquema del módulo ``hr``."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def employee_payload(**overrides: Any) -> EmployeeCreate:
    """Empleado válido por defecto, con datos parcialmente sobrescribibles."""
    values: dict[str, Any] = {
        "identification_number": "900123456-1",
        "first_name": "Ana",
        "last_name": "Pérez",
        "email": "ana.perez@example.com",
        "phone": "+57 300 123 4567",
        "birth_date": date(1990, 5, 10),
        "hire_date": date(2026, 1, 1),
    }
    values.update(overrides)
    return EmployeeCreate(**values)


def contract_payload(
    employee_id: int,
    **overrides: Any,
) -> ContractCreate:
    """Contrato activo válido por defecto, con salario estrictamente decimal."""
    values: dict[str, Any] = {
        "employee_id": employee_id,
        "contract_type": ContractType.INDEFINITE,
        "base_salary": Decimal("3500000.00"),
        "start_date": date(2026, 1, 1),
        "end_date": None,
        "is_active": True,
    }
    values.update(overrides)
    return ContractCreate(**values)


def count_employees(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(Employee)) or 0)


def count_contracts(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(Contract)) or 0)


# --------------------------------------------------------------------------- #
# Empleados
# --------------------------------------------------------------------------- #


def test_create_employee_persists_and_defaults_to_active(db_session: Session) -> None:
    employee = create_employee(db_session, employee_payload())

    assert employee.id is not None
    assert employee.is_active is True
    assert employee.identification_number == "900123456-1"
    assert employee.created_at is not None
    assert count_employees(db_session) == 1


def test_create_employee_rejects_duplicate_identification(db_session: Session) -> None:
    create_employee(db_session, employee_payload())

    with pytest.raises(DuplicateIdentificationError) as exc_info:
        create_employee(db_session, employee_payload(first_name="Otro"))

    assert isinstance(exc_info.value, HRServiceError)
    assert exc_info.value.status_code == 400
    assert "identificación" in str(exc_info.value)
    assert count_employees(db_session) == 1


def test_update_employee_rejects_duplicate_identification(db_session: Session) -> None:
    first = create_employee(db_session, employee_payload())
    second = create_employee(
        db_session,
        employee_payload(identification_number="900999999-9", email="otro@example.com"),
    )

    with pytest.raises(DuplicateIdentificationError):
        update_employee(
            db_session,
            second.id,
            EmployeeUpdate(identification_number=first.identification_number),
        )

    db_session.refresh(second)
    assert second.identification_number == "900999999-9"


def test_list_employees_filters_by_active_status(db_session: Session) -> None:
    active = create_employee(db_session, employee_payload())
    inactive = create_employee(
        db_session,
        employee_payload(identification_number="900999999-9", email="otro@example.com"),
    )
    update_employee(db_session, inactive.id, EmployeeUpdate(is_active=False))

    assert [item.id for item in list_employees(db_session, is_active=True)] == [active.id]
    assert [item.id for item in list_employees(db_session, is_active=False)] == [
        inactive.id
    ]
    assert len(list_employees(db_session)) == 2


def test_update_employee_changes_personal_and_contact_data(db_session: Session) -> None:
    employee = create_employee(db_session, employee_payload())

    updated = update_employee(
        db_session,
        employee.id,
        EmployeeUpdate(first_name="Ana María", phone=None, hire_date=date(2026, 2, 1)),
    )

    assert updated.first_name == "Ana María"
    assert updated.phone is None
    assert updated.hire_date == date(2026, 2, 1)


def test_update_employee_validates_effective_dates(db_session: Session) -> None:
    employee = create_employee(db_session, employee_payload())

    with pytest.raises(InvalidEmployeeDataError):
        update_employee(
            db_session,
            employee.id,
            EmployeeUpdate(birth_date=date(2027, 1, 1)),
        )

    db_session.refresh(employee)
    assert employee.birth_date == date(1990, 5, 10)


def test_get_employee_profile_includes_work_history(db_session: Session) -> None:
    employee = create_employee(db_session, employee_payload())
    create_contract(db_session, contract_payload(employee.id))
    db_session.add(
        Attendance(
            employee_id=employee.id,
            date=_TODAY,
            status=AttendanceStatus.PRESENT,
        )
    )
    db_session.commit()

    profile = get_employee_profile(db_session, employee.id)

    assert profile.id == employee.id
    assert len(profile.contracts) == 1
    assert profile.contracts[0].base_salary == Decimal("3500000.00")
    assert len(profile.attendance_records) == 1
    assert profile.attendance_records[0].status is AttendanceStatus.PRESENT


def test_get_missing_employee_raises_404(db_session: Session) -> None:
    with pytest.raises(ResourceNotFoundError) as exc_info:
        get_employee(db_session, 999)

    assert exc_info.value.status_code == 404


# --------------------------------------------------------------------------- #
# Contratos
# --------------------------------------------------------------------------- #


def test_create_contract_requires_existing_employee(db_session: Session) -> None:
    with pytest.raises(ResourceNotFoundError) as exc_info:
        create_contract(db_session, contract_payload(employee_id=999))

    assert exc_info.value.status_code == 404
    assert count_contracts(db_session) == 0


def test_create_contract_rejects_second_active_contract(db_session: Session) -> None:
    employee = create_employee(db_session, employee_payload())
    first = create_contract(db_session, contract_payload(employee.id))

    with pytest.raises(ActiveContractError) as exc_info:
        create_contract(
            db_session,
            contract_payload(
                employee.id,
                contract_type=ContractType.PART_TIME,
                base_salary=Decimal("1500000.00"),
                start_date=date(2026, 6, 1),
            ),
        )

    assert isinstance(exc_info.value, HRServiceError)
    assert exc_info.value.status_code == 400
    assert "contrato vigente" in str(exc_info.value)
    assert count_contracts(db_session) == 1
    assert get_active_contract(db_session, employee.id).id == first.id


def test_inactive_contract_can_coexist_with_active_one(db_session: Session) -> None:
    employee = create_employee(db_session, employee_payload())
    active = create_contract(db_session, contract_payload(employee.id, start_date=date(2026, 1, 1)))
    historic = create_contract(
        db_session,
        contract_payload(
            employee.id,
            contract_type=ContractType.FIXED_TERM,
            base_salary=Decimal("3000000.00"),
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            is_active=False,
        ),
    )

    history = list_contracts_by_employee(db_session, employee.id)

    assert [item.id for item in history] == [active.id, historic.id]
    assert [item.id for item in list_contracts_by_employee(db_session, employee.id, active_only=True)] == [
        active.id
    ]
    assert get_active_contract(db_session, employee.id).id == active.id


def test_contract_service_validates_dates_even_if_schema_is_bypassed(
    db_session: Session,
) -> None:
    employee = create_employee(db_session, employee_payload())
    invalid = ContractCreate.model_construct(
        employee_id=employee.id,
        contract_type=ContractType.FIXED_TERM,
        base_salary=Decimal("1000000.00"),
        start_date=date(2026, 6, 1),
        end_date=date(2026, 5, 1),
        is_active=True,
    )

    with pytest.raises(InvalidEmployeeDataError):
        create_contract(db_session, invalid)

    assert count_contracts(db_session) == 0


def test_list_contracts_by_missing_employee_raises_404(db_session: Session) -> None:
    with pytest.raises(ResourceNotFoundError):
        list_contracts_by_employee(db_session, 999)


def test_get_active_contract_returns_none_when_there_is_none(db_session: Session) -> None:
    employee = create_employee(db_session, employee_payload())
    assert get_active_contract(db_session, employee.id) is None
