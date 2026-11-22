"""Pruebas de generación y cálculo de nómina del módulo ``hr``.

Cubren los escenarios 1, 3, 5 y 6 de ``specs/hr_spec.md``: cálculo exacto con
``Decimal``, inmutabilidad de periodos aprobados/pagados, unicidad del código
y exclusión de empleados sin contrato activo vigente. SQLite en memoria, igual
que el resto de la suite.
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
from src.modules.accounting.models import AccountType  # noqa: E402
from src.modules.accounting.schemas import AccountCreate  # noqa: E402
from src.modules.accounting.service import (  # noqa: E402
    create_account as create_accounting_account,
)
from src.modules.hr.models import (  # noqa: E402
    AttendanceStatus,
    ContractType,
    Employee,
    PayrollRun,
    PayrollRunStatus,
    Payslip,
)
from src.modules.hr.schemas import (  # noqa: E402
    AttendanceCreate,
    ContractCreate,
    EmployeeCreate,
    EmployeeUpdate,
    PayrollRunCreate,
)
from src.modules.hr.service import (  # noqa: E402
    DuplicatePayrollCodeError,
    HRServiceError,
    ImmutablePayrollRunError,
    InvalidPayrollDataError,
    approve_payroll_run,
    create_attendance,
    create_contract,
    create_employee,
    create_payroll_run,
    get_payroll_run_detail,
    recalculate_payroll_run,
    set_payroll_run_status,
    update_employee,
)

_PERIOD_START = date(2026, 3, 1)
_PERIOD_END = date(2026, 3, 31)


@pytest.fixture()
def db_session() -> Session:
    """Sesión SQLite aislada con el esquema completo del módulo ``hr``."""
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


def employee_payload(index: int = 1, **overrides: Any) -> EmployeeCreate:
    values: dict[str, Any] = {
        "identification_number": f"900000000-{index}",
        "first_name": f"Empleado{index}",
        "last_name": "Prueba",
        "email": f"empleado{index}@example.com",
        "phone": None,
        "birth_date": date(1990, 5, 10),
        "hire_date": date(2026, 1, 1),
    }
    values.update(overrides)
    return EmployeeCreate(**values)


def contract_payload(
    employee_id: int,
    *,
    index: int = 1,
    base_salary: Decimal = Decimal("3000000.00"),
    **overrides: Any,
) -> ContractCreate:
    values: dict[str, Any] = {
        "employee_id": employee_id,
        "contract_type": ContractType.INDEFINITE,
        "base_salary": base_salary,
        "start_date": date(2026, 1, 1),
        "end_date": None,
        "is_active": True,
    }
    values.update(overrides)
    return ContractCreate(**values)


def attendance_payload(
    employee_id: int,
    *,
    day: int = 15,
    hours: str = "0.00",
    status: AttendanceStatus = AttendanceStatus.OVERTIME,
) -> AttendanceCreate:
    return AttendanceCreate(
        employee_id=employee_id,
        date=date(2026, 3, day),
        status=status,
        overtime_hours=Decimal(hours),
    )


def payroll_payload(code: str = "NOM-2026-03", **overrides: Any) -> PayrollRunCreate:
    values: dict[str, Any] = {
        "code": code,
        "period_start": _PERIOD_START,
        "period_end": _PERIOD_END,
        "is_adjustment": False,
    }
    values.update(overrides)
    return PayrollRunCreate(**values)


def count_runs(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(PayrollRun)) or 0)


def count_payslips(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(Payslip)) or 0)


def seed_payroll_accounts(db: Session) -> None:
    """PUC mínimo usado por la integración contable de nómina."""
    create_accounting_account(
        db,
        AccountCreate(
            code="5100", name="Gastos de personal", account_type=AccountType.EXPENSE
        ),
    )
    create_accounting_account(
        db,
        AccountCreate(
            code="220505",
            name="Cuentas por pagar de nómina",
            account_type=AccountType.LIABILITY,
        ),
    )


def test_create_payroll_run_calculates_decimal_payslips_and_totals(
    db_session: Session,
) -> None:
    first = create_employee(db_session, employee_payload(1))
    second = create_employee(db_session, employee_payload(2))
    create_contract(db_session, contract_payload(first.id, index=1))
    create_contract(
        db_session,
        contract_payload(
            second.id, index=2, base_salary=Decimal("1500000.00")
        ),
    )
    create_attendance(db_session, attendance_payload(first.id, hours="6.00"))
    create_attendance(
        db_session,
        attendance_payload(
            first.id, hours="5.00", status=AttendanceStatus.PRESENT
        ),
    )
    create_attendance(
        db_session,
        AttendanceCreate(
            employee_id=first.id,
            date=date(2026, 4, 5),
            status=AttendanceStatus.OVERTIME,
            overtime_hours=Decimal("99.00"),
        ),
    )  # fuera del periodo
    create_attendance(db_session, attendance_payload(second.id, hours="4.00"))

    run = create_payroll_run(
        db_session,
        payroll_payload(),
        bonuses={first.id: Decimal("50000.00")},
        deductions={
            first.id: Decimal("100000.00"),
            second.id: Decimal("20000.00"),
        },
    )

    payslips = {item.employee_id: item for item in run.payslips}
    assert run.status is PayrollRunStatus.DRAFT
    assert run.is_adjustment is False
    assert set(payslips) == {first.id, second.id}

    # Salario mensual completo: el periodo cubre 31 días y se capa a 30.
    assert payslips[first.id].base_salary == Decimal("3000000.00")
    assert payslips[second.id].base_salary == Decimal("1500000.00")

    # Tarifa/hora = salario / (30*8): 12500 y 6250 respectivamente.
    assert payslips[first.id].overtime_pay == Decimal("137500.00")  # 11 h
    assert payslips[second.id].overtime_pay == Decimal("25000.00")  # 4 h
    assert payslips[first.id].bonuses == Decimal("50000.00")
    assert payslips[second.id].bonuses == Decimal("0.00")

    assert payslips[first.id].earnings == Decimal("3187500.00")
    assert payslips[first.id].net_pay == Decimal("3087500.00")
    assert payslips[second.id].earnings == Decimal("1525000.00")
    assert payslips[second.id].net_pay == Decimal("1505000.00")

    assert run.total_earnings == Decimal("4712500.00")
    assert run.total_deductions == Decimal("120000.00")
    assert run.total_net == Decimal("4592500.00")
    assert run.total_net == run.total_earnings - run.total_deductions

    for item in payslips.values():
        assert isinstance(item.earnings, Decimal)
        assert isinstance(item.net_pay, Decimal)
    assert isinstance(run.total_earnings, Decimal)
    assert isinstance(run.total_net, Decimal)


def test_create_payroll_run_prorates_short_periods(db_session: Session) -> None:
    employee = create_employee(db_session, employee_payload(1))
    create_contract(db_session, contract_payload(employee.id))
    create_attendance(db_session, attendance_payload(employee.id, hours="8.00"))

    run = create_payroll_run(
        db_session,
        payroll_payload(
            period_start=date(2026, 3, 1), period_end=date(2026, 3, 15)
        ),
    )

    payslip = run.payslips[0]
    assert payslip.base_salary == Decimal("1500000.00")  # 15/30 del salario
    assert payslip.overtime_pay == Decimal("100000.00")  # 8 h * 12500
    assert payslip.earnings == Decimal("1600000.00")
    assert payslip.net_pay == Decimal("1600000.00")
    assert run.total_net == Decimal("1600000.00")


def test_create_payroll_run_excludes_inactive_or_without_active_contract(
    db_session: Session,
) -> None:
    included = create_employee(db_session, employee_payload(1))
    inactive = create_employee(db_session, employee_payload(2))
    no_contract = create_employee(db_session, employee_payload(3))
    inactive_contract = create_employee(db_session, employee_payload(4))
    future_contract = create_employee(db_session, employee_payload(5))
    ended_contract = create_employee(db_session, employee_payload(6))
    exact_contract = create_employee(db_session, employee_payload(7))

    create_contract(db_session, contract_payload(included.id, index=1))
    create_contract(db_session, contract_payload(inactive.id, index=2))
    update_employee(db_session, inactive.id, EmployeeUpdate(is_active=False))

    create_contract(
        db_session,
        contract_payload(inactive_contract.id, index=4, is_active=False),
    )
    create_contract(
        db_session,
        contract_payload(
            future_contract.id,
            index=5,
            start_date=date(2026, 4, 1),
        ),
    )
    create_contract(
        db_session,
        contract_payload(
            ended_contract.id,
            index=6,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        ),
    )
    create_contract(
        db_session,
        contract_payload(
            exact_contract.id,
            index=7,
            start_date=_PERIOD_START,
            end_date=_PERIOD_END,
        ),
    )

    run = create_payroll_run(db_session, payroll_payload())

    assert {item.employee_id for item in run.payslips} == {
        included.id,
        exact_contract.id,
    }
    assert no_contract.id not in {item.employee_id for item in run.payslips}
    assert run.total_earnings == Decimal("6000000.00")
    assert run.total_net == Decimal("6000000.00")


def test_create_payroll_run_rejects_duplicate_code(db_session: Session) -> None:
    employee = create_employee(db_session, employee_payload(1))
    create_contract(db_session, contract_payload(employee.id))
    create_payroll_run(db_session, payroll_payload())

    with pytest.raises(DuplicatePayrollCodeError) as exc_info:
        create_payroll_run(db_session, payroll_payload())

    assert isinstance(exc_info.value, HRServiceError)
    assert exc_info.value.status_code == 400
    assert count_runs(db_session) == 1
    assert count_payslips(db_session) == 1


def test_payroll_service_validates_data_when_schema_is_bypassed(
    db_session: Session,
) -> None:
    invalid_period = PayrollRunCreate.model_construct(
        code="NOM-2026-03",
        period_start=date(2026, 3, 31),
        period_end=date(2026, 3, 1),
        is_adjustment=False,
    )
    with pytest.raises(InvalidPayrollDataError):
        create_payroll_run(db_session, invalid_period)

    assert count_runs(db_session) == 0


def test_recalculate_draft_payroll_preserves_unspecified_deductions(
    db_session: Session,
) -> None:
    employee = create_employee(db_session, employee_payload(1))
    create_contract(db_session, contract_payload(employee.id))
    create_attendance(db_session, attendance_payload(employee.id, hours="2.00"))

    run = create_payroll_run(
        db_session,
        payroll_payload(),
        deductions={employee.id: Decimal("100000.00")},
    )
    create_attendance(db_session, attendance_payload(employee.id, hours="3.00"))

    updated = recalculate_payroll_run(db_session, run.id)

    assert updated.payslips[0].overtime_pay == Decimal("62500.00")  # 5 h
    assert updated.payslips[0].deductions == Decimal("100000.00")
    assert updated.payslips[0].earnings == Decimal("3062500.00")
    assert updated.payslips[0].net_pay == Decimal("2962500.00")
    assert updated.total_net == Decimal("2962500.00")
    assert count_payslips(db_session) == 1


def test_payroll_run_is_immutable_after_approval_or_paid(
    db_session: Session,
) -> None:
    employee = create_employee(db_session, employee_payload(1))
    create_contract(db_session, contract_payload(employee.id))
    seed_payroll_accounts(db_session)
    run = create_payroll_run(
        db_session,
        payroll_payload(),
        deductions={employee.id: Decimal("100000.00")},
    )
    original_earnings = run.total_earnings
    original_net = run.total_net

    approved = approve_payroll_run(db_session, run.id)
    assert approved.status is PayrollRunStatus.APPROVED
    assert approved.approved_at is not None

    with pytest.raises(ImmutablePayrollRunError) as exc_info:
        recalculate_payroll_run(db_session, run.id)
    assert exc_info.value.status_code == 409
    assert "ajuste" in str(exc_info.value)

    with pytest.raises(ImmutablePayrollRunError):
        approve_payroll_run(db_session, run.id)
    with pytest.raises(ImmutablePayrollRunError):
        set_payroll_run_status(db_session, run.id, PayrollRunStatus.PAID)

    db_session.refresh(run)
    assert run.status is PayrollRunStatus.APPROVED
    assert run.total_earnings == original_earnings
    assert run.total_net == original_net

    # Simular el pago directo y comprobar que la barrera sigue activa.
    run.status = PayrollRunStatus.PAID
    db_session.commit()
    with pytest.raises(ImmutablePayrollRunError):
        recalculate_payroll_run(db_session, run.id)

    detail = get_payroll_run_detail(db_session, run.id)
    assert detail.status is PayrollRunStatus.PAID
    assert detail.total_net == original_net
    assert len(detail.payslips) == 1
    assert isinstance(detail.payslips[0].net_pay, Decimal)


def test_payroll_adjustment_flag_is_recorded(db_session: Session) -> None:
    employee = create_employee(db_session, employee_payload(1))
    create_contract(db_session, contract_payload(employee.id))

    adjustment = create_payroll_run(
        db_session,
        payroll_payload(
            code="NOM-2026-03-AJ", is_adjustment=True
        ),
    )

    assert adjustment.is_adjustment is True
    assert adjustment.status is PayrollRunStatus.DRAFT
    assert [run.code for run in [adjustment]] == ["NOM-2026-03-AJ"]
