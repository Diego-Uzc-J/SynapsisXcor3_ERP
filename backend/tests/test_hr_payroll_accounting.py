"""Pruebas de integración contable al aprobar nómina (regla 4, escenario 4).

Verifican que ``approve_payroll_run`` cree el asiento en ``accounting`` y marque
el ``PayrollRun`` como ``APPROVED`` en una sola transacción, y que cualquier
fallo deje el periodo en ``DRAFT`` sin asientos parciales.
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
from src.modules.accounting.models import (  # noqa: E402
    Account,
    AccountType,
    JournalEntry,
    JournalEntryStatus,
    JournalItem,
)
from src.modules.accounting.schemas import AccountCreate  # noqa: E402
from src.modules.accounting.service import (  # noqa: E402
    create_account,
)
from src.modules.hr.models import ContractType, PayrollRun, PayrollRunStatus  # noqa: E402
from src.modules.hr.schemas import (  # noqa: E402
    ContractCreate,
    EmployeeCreate,
    PayrollRunCreate,
)
from src.modules.hr import service as hr_service  # noqa: E402
from src.modules.hr.service import (  # noqa: E402
    ImmutablePayrollRunError,
    InvalidPayrollDataError,
    PayrollAccountingError,
    approve_payroll_run,
    create_contract,
    create_employee,
    create_payroll_run,
    set_payroll_run_status,
)


@pytest.fixture()
def db_session() -> Session:
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


def seed_accounts(db: Session) -> None:
    create_account(
        db,
        AccountCreate(
            code="5100", name="Gastos de personal", account_type=AccountType.EXPENSE
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


def seed_payroll(db: Session) -> PayrollRun:
    employee = create_employee(
        db,
        EmployeeCreate(
            identification_number="900123456-1",
            first_name="Ana",
            last_name="Pérez",
            email="ana.perez@example.com",
            birth_date=date(1990, 5, 10),
            hire_date=date(2026, 1, 1),
        ),
    )
    create_contract(
        db,
        ContractCreate(
            employee_id=employee.id,
            contract_type=ContractType.INDEFINITE,
            base_salary=Decimal("3000000.00"),
            start_date=date(2026, 1, 1),
        ),
    )
    return create_payroll_run(
        db,
        PayrollRunCreate(
            code="NOM-2026-03",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
        ),
        deductions={employee.id: Decimal("100000.00")},
    )


def entries_for(db: Session, code: str) -> list[JournalEntry]:
    return list(
        db.scalars(
            select(JournalEntry)
            .where(JournalEntry.reference_document == code)
            .order_by(JournalEntry.id)
        ).all()
    )


def entry_items(db: Session, entry_id: int) -> list[tuple[JournalItem, str]]:
    rows = db.execute(
        select(JournalItem, Account.code)
        .join(Account, JournalItem.account_id == Account.id)
        .where(JournalItem.journal_entry_id == entry_id)
        .order_by(JournalItem.id)
    )
    return [(item, code) for item, code in rows.all()]


def count_entries(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(JournalEntry)) or 0)


def test_approve_payroll_run_posts_journal_entry_and_approves_atomically(
    db_session: Session,
) -> None:
    seed_accounts(db_session)
    run = seed_payroll(db_session)

    # APPROVED no se puede fijar directamente: exige la contabilización.
    with pytest.raises(InvalidPayrollDataError):
        set_payroll_run_status(db_session, run.id, PayrollRunStatus.APPROVED)
    db_session.refresh(run)
    assert run.status is PayrollRunStatus.DRAFT

    approved = approve_payroll_run(db_session, run.id, created_by="hr-test")

    assert approved.status is PayrollRunStatus.APPROVED
    assert approved.approved_at is not None

    entries = entries_for(db_session, approved.code)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.status is JournalEntryStatus.POSTED
    assert entry.posted_at is not None
    assert entry.description == "Nomina NOM-2026-03"
    assert entry.created_by == "hr-test"
    assert entry.entry_date == date(2026, 3, 31)

    items = entry_items(db_session, entry.id)
    debits = [(item, code) for item, code in items if item.debit > 0]
    credits = [(item, code) for item, code in items if item.credit > 0]
    assert len(debits) == 1
    assert debits[0][0].debit == approved.total_earnings
    assert debits[0][1] == "5100"
    assert sorted(item.credit for item, _ in credits) == sorted(
        [approved.total_net, approved.total_deductions]
    )
    assert all(code == "220505" for _, code in credits)
    assert sum((item.credit for item, _ in credits), Decimal("0.00")) == (
        approved.total_earnings
    )

    # Reaprobar está bloqueado y no genera un segundo asiento.
    with pytest.raises(ImmutablePayrollRunError):
        approve_payroll_run(db_session, run.id)
    assert count_entries(db_session) == 1


def test_approve_payroll_run_rolls_back_when_accounting_raises(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_accounts(db_session)
    run = seed_payroll(db_session)
    original = hr_service.post_payroll_run_accounting

    def failing_post(*args: Any, **kwargs: Any) -> Any:
        # El asiento llega a construirse y añadirse a la sesión; la excepción
        # posterior debe hacer que la transacción de RRHH lo descarte.
        result = original(*args, **kwargs)
        raise RuntimeError("fallo forzado en contabilidad")

    monkeypatch.setattr(hr_service, "post_payroll_run_accounting", failing_post)

    with pytest.raises(PayrollAccountingError) as exc_info:
        approve_payroll_run(db_session, run.id)

    assert exc_info.value.status_code == 400
    assert run.code in str(exc_info.value)
    db_session.refresh(run)
    assert run.status is PayrollRunStatus.DRAFT
    assert run.approved_at is None
    assert run.total_net == Decimal("2900000.00")
    assert entries_for(db_session, run.code) == []
    assert count_entries(db_session) == 0


def test_approve_payroll_run_rolls_back_when_chart_of_accounts_is_missing(
    db_session: Session,
) -> None:
    run = seed_payroll(db_session)  # sin cuentas 5100 ni 220505

    with pytest.raises(PayrollAccountingError):
        approve_payroll_run(db_session, run.id)

    db_session.refresh(run)
    assert run.status is PayrollRunStatus.DRAFT
    assert run.approved_at is None
    assert count_entries(db_session) == 0
