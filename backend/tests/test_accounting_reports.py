"""Pruebas de los reportes financieros del módulo ``accounting`` (Hito 5).

Verifican que el balance de comprobación, el balance general y el estado de
resultados agreguen **solo** asientos ``POSTED`` dentro del rango de fechas o
del periodo indicado, y que los borradores o anulados no alteren ningún saldo.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
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
    AccountingPeriod,
    JournalEntry,
)
from src.modules.accounting.schemas import (  # noqa: E402
    AccountCreate,
    JournalEntryCreate,
    JournalItemCreate,
)
from src.modules.accounting.service import (  # noqa: E402
    AccountingError,
    ResourceNotFoundError,
    create_account,
    create_journal_entry,
    deactivate_account,
    get_balance_sheet,
    get_income_statement,
    get_trial_balance,
    post_journal_entry,
    void_journal_entry,
)

_NOVEMBER = date(2026, 11, 1)
_OCTOBER_31 = date(2026, 10, 31)
_NOVEMBER_15 = date(2026, 11, 15)
_NOVEMBER_30 = date(2026, 11, 30)


@pytest.fixture()
def db_session() -> Session:
    """Sesión SQLite aislada con el esquema completo del ERP."""
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


@pytest.fixture()
def chart(db_session: Session) -> dict[str, Account]:
    """PUC mínimo con una cuenta de cada tipo."""
    definitions = {
        "cash": ("110505", "Caja General", AccountType.ASSET),
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
        )
        for role, (code, name, kind) in definitions.items()
    }


def make_entry(
    db: Session,
    chart: dict[str, Account],
    code: str,
    debit_role: str,
    credit_role: str,
    amount: str,
    entry_date: date = _NOVEMBER,
    *,
    publish: bool = True,
) -> JournalEntry:
    """Crea un asiento equilibrado de dos líneas y lo publica si se pide."""
    entry = create_journal_entry(
        db,
        JournalEntryCreate(
            code=code,
            entry_date=entry_date,
            description=f"Asiento de prueba {code}",
            items=[
                JournalItemCreate(
                    account_id=chart[debit_role].id, debit=Decimal(amount)
                ),
                JournalItemCreate(
                    account_id=chart[credit_role].id, credit=Decimal(amount)
                ),
            ],
        ),
    )
    return post_journal_entry(db, entry.id) if publish else entry


def line_by_code(lines: list[Any], code: str) -> Any:
    """Busca una línea de reporte por código de cuenta."""
    return next(line for line in lines if line.code == code)


# --------------------------------------------------------------------------- #
# Balance de comprobación
# --------------------------------------------------------------------------- #


def test_trial_balance_only_aggregates_posted_entries(
    db_session: Session, chart: dict[str, Account]
) -> None:
    make_entry(db_session, chart, "ASI-2026-0001", "cash", "revenue", "1000.00")
    make_entry(db_session, chart, "ASI-2026-0002", "expense", "cash", "200.00")

    # Un borrador y un anulado con importes grandes no deben afectar al reporte.
    make_entry(
        db_session, chart, "ASI-2026-0003", "cash", "revenue", "5000.00",
        publish=False,
    )
    voided = make_entry(
        db_session, chart, "ASI-2026-0004", "cash", "revenue", "3000.00",
        publish=False,
    )
    void_journal_entry(db_session, voided.id)

    report = get_trial_balance(db_session)

    assert report.total_debit == Decimal("1200.00")
    assert report.total_credit == Decimal("1200.00")
    assert {line.code for line in report.lines} == {"110505", "4135", "5100"}

    cash = line_by_code(report.lines, "110505")
    revenue = line_by_code(report.lines, "4135")
    expense = line_by_code(report.lines, "5100")
    assert (cash.debit, cash.credit, cash.balance) == (
        Decimal("1000.00"), Decimal("200.00"), Decimal("800.00")
    )
    assert (revenue.debit, revenue.credit, revenue.balance) == (
        Decimal("0.00"), Decimal("1000.00"), Decimal("-1000.00")
    )
    assert (expense.debit, expense.credit, expense.balance) == (
        Decimal("200.00"), Decimal("0.00"), Decimal("200.00")
    )
    assert cash.account_type is AccountType.ASSET
    assert revenue.account_type is AccountType.REVENUE


def test_trial_balance_accepts_date_range_and_accounting_period(
    db_session: Session, chart: dict[str, Account]
) -> None:
    make_entry(
        db_session, chart, "ASI-2026-0001", "cash", "revenue", "100.00",
        _OCTOBER_31,
    )
    make_entry(
        db_session, chart, "ASI-2026-0002", "cash", "revenue", "200.00",
        date(2026, 11, 2),
    )
    make_entry(
        db_session, chart, "ASI-2026-0003", "cash", "revenue", "300.00",
        _NOVEMBER_30,
    )
    period = AccountingPeriod(
        name="2026-11",
        start_date=_NOVEMBER,
        end_date=_NOVEMBER_30,
        is_closed=False,
    )
    db_session.add(period)
    db_session.commit()

    by_dates = get_trial_balance(db_session, _NOVEMBER, _NOVEMBER_30)
    by_period = get_trial_balance(db_session, period_id=period.id)
    by_name = get_trial_balance(db_session, period_name="2026-11")
    assert by_dates.total_debit == Decimal("500.00")
    assert by_period.total_debit == Decimal("500.00")
    assert by_name.total_debit == Decimal("500.00")

    # El rango explícito se intersecta con el periodo.
    intersection = get_trial_balance(
        db_session, _NOVEMBER, _NOVEMBER_15, period_id=period.id
    )
    assert intersection.total_debit == Decimal("200.00")

    with pytest.raises(AccountingError):
        get_trial_balance(db_session, _NOVEMBER_30, _NOVEMBER)
    with pytest.raises(ResourceNotFoundError):
        get_trial_balance(db_session, period_id=9999)
    with pytest.raises(ResourceNotFoundError):
        get_trial_balance(db_session, period_name="2026-12")


# --------------------------------------------------------------------------- #
# Balance General
# --------------------------------------------------------------------------- #


def test_balance_sheet_groups_types_and_verifies_equation(
    db_session: Session, chart: dict[str, Account]
) -> None:
    make_entry(db_session, chart, "ASI-2026-0001", "cash", "equity", "1000.00")
    make_entry(
        db_session, chart, "ASI-2026-0002", "inventory", "payable", "300.00"
    )

    report = get_balance_sheet(db_session)

    assert [line.code for line in report.assets] == ["110505", "1435"]
    assert [line.code for line in report.liabilities] == ["220505"]
    assert [line.code for line in report.equity] == ["3105"]
    assert report.total_assets == Decimal("1300.00")
    assert report.total_liabilities == Decimal("300.00")
    assert report.total_equity == Decimal("1000.00")
    assert report.total_liabilities_and_equity == Decimal("1300.00")
    assert report.difference == Decimal("0.00")


def test_balance_sheet_shows_period_result_when_not_closed_to_equity(
    db_session: Session, chart: dict[str, Account]
) -> None:
    # Asiento de venta: activo por CxC frente a ingreso del periodo.
    make_entry(
        db_session, chart, "ASI-2026-0001", "cash", "revenue", "1200.00"
    )

    report = get_balance_sheet(db_session)
    assert report.total_assets == Decimal("1200.00")
    assert report.total_liabilities_and_equity == Decimal("0.00")
    assert report.difference == Decimal("1200.00")
    assert [line.code for line in report.assets] == ["110505"]


def test_closed_period_entries_are_still_reported(
    db_session: Session, chart: dict[str, Account]
) -> None:
    make_entry(db_session, chart, "ASI-2026-0001", "cash", "equity", "700.00")
    period = AccountingPeriod(
        name="2026-11",
        start_date=_NOVEMBER,
        end_date=_NOVEMBER_30,
        is_closed=True,
    )
    db_session.add(period)
    db_session.commit()

    report = get_balance_sheet(db_session, period_id=period.id)
    assert report.total_assets == Decimal("700.00")
    assert report.total_equity == Decimal("700.00")
    assert report.difference == Decimal("0.00")


# --------------------------------------------------------------------------- #
# Estado de resultados
# --------------------------------------------------------------------------- #


def test_income_statement_computes_net_income(
    db_session: Session, chart: dict[str, Account]
) -> None:
    make_entry(db_session, chart, "ASI-2026-0001", "cash", "revenue", "1000.00")
    make_entry(db_session, chart, "ASI-2026-0002", "expense", "cash", "200.00")
    make_entry(db_session, chart, "ASI-2026-0003", "expense", "cash", "100.00")

    report = get_income_statement(db_session)

    assert [line.code for line in report.revenues] == ["4135"]
    assert [line.code for line in report.expenses] == ["5100"]
    assert report.total_revenue == Decimal("1000.00")
    assert report.total_expenses == Decimal("300.00")
    assert report.net_income == Decimal("700.00")


def test_income_statement_can_report_a_loss(
    db_session: Session, chart: dict[str, Account]
) -> None:
    make_entry(db_session, chart, "ASI-2026-0001", "cash", "revenue", "200.00")
    make_entry(db_session, chart, "ASI-2026-0002", "expense", "cash", "500.00")

    report = get_income_statement(db_session)
    assert report.net_income == Decimal("-300.00")


# --------------------------------------------------------------------------- #
# Exclusión de DRAFT/VOID y casos límite
# --------------------------------------------------------------------------- #


def test_draft_and_void_entries_do_not_change_any_report(
    db_session: Session, chart: dict[str, Account]
) -> None:
    make_entry(db_session, chart, "ASI-2026-0001", "cash", "revenue", "900.00")
    make_entry(db_session, chart, "ASI-2026-0002", "expense", "cash", "100.00")

    before = (
        get_trial_balance(db_session),
        get_balance_sheet(db_session),
        get_income_statement(db_session),
    )

    make_entry(
        db_session, chart, "ASI-2026-0003", "cash", "revenue", "4000.00",
        publish=False,
    )
    voided = make_entry(
        db_session, chart, "ASI-2026-0004", "expense", "cash", "3000.00",
        publish=False,
    )
    void_journal_entry(db_session, voided.id)

    after = (
        get_trial_balance(db_session),
        get_balance_sheet(db_session),
        get_income_statement(db_session),
    )
    assert after == before


def test_reports_keep_inactive_accounts_with_history(
    db_session: Session, chart: dict[str, Account]
) -> None:
    make_entry(db_session, chart, "ASI-2026-0001", "cash", "revenue", "500.00")
    deactivate_account(db_session, chart["revenue"].id)

    trial = get_trial_balance(db_session)
    income = get_income_statement(db_session)
    assert line_by_code(trial.lines, "4135").credit == Decimal("500.00")
    assert income.total_revenue == Decimal("500.00")


def test_empty_reports_return_zero_totals(db_session: Session) -> None:
    trial = get_trial_balance(db_session)
    balance = get_balance_sheet(db_session)
    income = get_income_statement(db_session)

    assert trial.lines == []
    assert trial.total_debit == Decimal("0.00")
    assert trial.total_credit == Decimal("0.00")
    assert balance.assets == [] and balance.liabilities == [] and balance.equity == []
    assert balance.difference == Decimal("0.00")
    assert income.revenues == [] and income.expenses == []
    assert income.net_income == Decimal("0.00")
