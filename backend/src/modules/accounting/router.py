"""Routers FastAPI del módulo de Finanzas y Contabilidad.

Expone los contratos de ``specs/accounting_spec.md`` (sección 4) bajo el prefijo
``/api/v1/accounting`` aplicado en ``src.main``: plan de cuentas, libro diario,
cartera CxC/CxP, pagos y reportes financieros.

Todas las operaciones exigen un token válido y uno de los roles autorizados por
la regla 9 de la spec y por la matriz de ``PROJECT_MANIFEST.md``:
``ACCOUNTING`` o ``ADMINISTRATOR`` (este último pasa por el *superuser bypass*
de :func:`src.core.security.require_roles`).

``accounting_exception_handler`` traduce las excepciones de dominio a respuestas
HTTP usando el ``status_code`` declarado por cada clase (400/404/409).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Path, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.security import require_roles
from src.modules.accounting import service as services
from src.modules.accounting.schemas import (
    AccountBalanceStatus,
    AccountCreate,
    AccountPayableResponse,
    AccountReceivableResponse,
    AccountResponse,
    AccountType,
    AccountUpdate,
    BalanceSheetResponse,
    IncomeStatementResponse,
    JournalEntryCreate,
    JournalEntryPostResponse,
    JournalEntryResponse,
    JournalEntryStatus,
    PaymentCreate,
    PaymentRecordRequest,
    PaymentRecordResponse,
    TrialBalanceResponse,
)
from src.modules.accounting.service import AccountingServiceError
from src.modules.users.models import RoleEnum, User

__all__ = ["accounting_exception_handler", "router"]


# --------------------------------------------------------------------------- #
# Guardia RBAC (spec de users, sección 4.3 / spec de accounting, regla 9)
# --------------------------------------------------------------------------- #

#: ``ADMINISTRATOR`` pasa siempre gracias al bypass interno de ``require_roles``.
require_accounting = require_roles([RoleEnum.ACCOUNTING])


async def accounting_exception_handler(
    _request: Request, exc: AccountingServiceError
) -> JSONResponse:
    """Convierte un error de dominio de contabilidad en una respuesta HTTP."""
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


def _report_window(
    date_from: date | None = Query(
        None, description="Fecha inicial del periodo (inclusive)."
    ),
    date_to: date | None = Query(
        None, description="Fecha final del periodo (inclusive)."
    ),
    period_id: int | None = Query(None, gt=0, description="Id del periodo contable."),
    period_name: str | None = Query(
        None, max_length=100, description="Nombre del periodo contable."
    ),
) -> dict[str, Any]:
    """Parámetros compartidos por los tres reportes financieros."""
    return {
        "date_from": date_from,
        "date_to": date_to,
        "period_id": period_id,
        "period_name": period_name,
    }


# --------------------------------------------------------------------------- #
# Plan de cuentas — /api/v1/accounting/accounts
# --------------------------------------------------------------------------- #

accounts_router = APIRouter(prefix="/accounts", tags=["accounting: accounts"])


@accounts_router.post(
    "",
    response_model=AccountResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar una cuenta del plan contable",
    dependencies=[Depends(require_accounting)],
)
def create_account(
    payload: AccountCreate,
    db: Session = Depends(get_db),
) -> AccountResponse:
    """Registra una cuenta validando código único y cuenta padre existente."""
    return AccountResponse.model_validate(services.create_account(db, payload))


@accounts_router.get(
    "",
    response_model=list[AccountResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar el plan de cuentas",
    dependencies=[Depends(require_accounting)],
)
def list_accounts(
    skip: int = Query(0, ge=0, description="Registros a omitir."),
    limit: int = Query(100, ge=1, le=200, description="Máximo de registros."),
    code: str | None = Query(None, description="Filtro parcial por código."),
    name: str | None = Query(None, description="Filtro parcial por nombre."),
    account_type: AccountType | None = Query(None, description="Filtro por tipo."),
    is_active: bool | None = Query(None, description="Filtro por estado."),
    parent_id: int | None = Query(None, gt=0, description="Filtro por cuenta madre."),
    db: Session = Depends(get_db),
) -> list[AccountResponse]:
    """Lista cuentas con filtros por tipo, código, nombre y estado."""
    accounts = services.list_accounts(
        db,
        skip=skip,
        limit=limit,
        code=code,
        name=name,
        account_type=account_type,
        is_active=is_active,
        parent_id=parent_id,
    )
    return [AccountResponse.model_validate(account) for account in accounts]


@accounts_router.get(
    "/{account_id}",
    response_model=AccountResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener una cuenta contable",
    dependencies=[Depends(require_accounting)],
)
def get_account(
    account_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> AccountResponse:
    """Devuelve el detalle de una cuenta o 404 si no existe."""
    return AccountResponse.model_validate(services.get_account(db, account_id))


@accounts_router.patch(
    "/{account_id}",
    response_model=AccountResponse,
    status_code=status.HTTP_200_OK,
    summary="Actualizar una cuenta contable",
    dependencies=[Depends(require_accounting)],
)
def update_account(
    payload: AccountUpdate,
    account_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> AccountResponse:
    """Actualiza nombre, código, tipo, jerarquía o estado de la cuenta."""
    return AccountResponse.model_validate(
        services.update_account(db, account_id, payload)
    )


@accounts_router.delete(
    "/{account_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Desactivar una cuenta contable",
    dependencies=[Depends(require_accounting)],
)
def deactivate_account(
    account_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> None:
    """Borrado lógico: preserva el historial y bloquea nuevos movimientos."""
    services.deactivate_account(db, account_id)


# --------------------------------------------------------------------------- #
# Libro diario — /api/v1/accounting/journal-entries
# --------------------------------------------------------------------------- #

entries_router = APIRouter(
    prefix="/journal-entries", tags=["accounting: journal entries"]
)


@entries_router.post(
    "",
    response_model=JournalEntryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un asiento en borrador",
)
def create_journal_entry(
    payload: JournalEntryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_accounting),
) -> JournalEntryResponse:
    """Crea el comprobante en ``DRAFT`` con sus líneas de partida doble."""
    if payload.created_by is None:
        payload = payload.model_copy(update={"created_by": current_user.username})
    entry = services.create_journal_entry(db, payload)
    return JournalEntryResponse.model_validate(entry)


@entries_router.get(
    "",
    response_model=list[JournalEntryResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar y filtrar asientos contables",
    dependencies=[Depends(require_accounting)],
)
def list_journal_entries(
    skip: int = Query(0, ge=0, description="Registros a omitir."),
    limit: int = Query(100, ge=1, le=200, description="Máximo de registros."),
    code: str | None = Query(None, description="Filtro parcial por código."),
    status_filter: JournalEntryStatus | None = Query(None, alias="status"),
    date_from: date | None = Query(None, description="Fecha inicial inclusive."),
    date_to: date | None = Query(None, description="Fecha final inclusive."),
    db: Session = Depends(get_db),
) -> list[JournalEntryResponse]:
    """Lista asientos con filtros por código, estado y rango de fechas."""
    entries = services.list_journal_entries(
        db,
        skip=skip,
        limit=limit,
        code=code,
        status=status_filter,
        date_from=date_from,
        date_to=date_to,
    )
    return [JournalEntryResponse.model_validate(entry) for entry in entries]


@entries_router.get(
    "/{entry_id}",
    response_model=JournalEntryResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener el detalle de un asiento",
    dependencies=[Depends(require_accounting)],
)
def get_journal_entry(
    entry_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> JournalEntryResponse:
    """Devuelve el encabezado y las líneas del asiento o 404 si no existe."""
    return JournalEntryResponse.model_validate(
        services.get_journal_entry(db, entry_id)
    )


@entries_router.post(
    "/{entry_id}/post",
    response_model=JournalEntryPostResponse,
    status_code=status.HTTP_200_OK,
    summary="Contabilizar un asiento",
    dependencies=[Depends(require_accounting)],
)
def post_journal_entry(
    entry_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> JournalEntryPostResponse:
    """Publica el borrador validando partida doble, cuentas y periodo abierto."""
    entry = services.post_journal_entry(db, entry_id)
    return services.build_journal_entry_post_response(entry)


@entries_router.post(
    "/{entry_id}/void",
    response_model=JournalEntryResponse,
    status_code=status.HTTP_200_OK,
    summary="Anular un asiento en borrador",
    dependencies=[Depends(require_accounting)],
)
def void_journal_entry(
    entry_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> JournalEntryResponse:
    """Pasa un ``DRAFT`` a ``VOID``; los asientos publicados requieren reversión."""
    return JournalEntryResponse.model_validate(
        services.void_journal_entry(db, entry_id)
    )


@entries_router.post(
    "/{entry_id}/reverse",
    response_model=JournalEntryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generar un asiento de reversión",
)
def reverse_journal_entry(
    entry_id: int = Path(gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_accounting),
) -> JournalEntryResponse:
    """Crea y publica un comprobante trazable que invierte un asiento ``POSTED``."""
    reversal = services.reverse_journal_entry(
        db, entry_id, created_by=current_user.username
    )
    return JournalEntryResponse.model_validate(reversal)


# --------------------------------------------------------------------------- #
# Cartera — /api/v1/accounting/receivables y /payables
# --------------------------------------------------------------------------- #

receivables_router = APIRouter(
    prefix="/receivables", tags=["accounting: receivables"]
)


@receivables_router.get(
    "",
    response_model=list[AccountReceivableResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar cuentas por cobrar",
    dependencies=[Depends(require_accounting)],
)
def list_account_receivables(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    third_party_id: int | None = Query(
        None, gt=0, description="Filtro por cliente (alias de customer_id)."
    ),
    customer_id: int | None = Query(None, gt=0, description="Filtro por cliente."),
    status_filter: AccountBalanceStatus | None = Query(None, alias="status"),
    due_before: date | None = Query(None, description="Vencimiento hasta esta fecha."),
    due_after: date | None = Query(None, description="Vencimiento desde esta fecha."),
    db: Session = Depends(get_db),
) -> list[AccountReceivableResponse]:
    """Lista CxC con filtros por cliente, estado y vencimiento."""
    balances = services.list_account_receivables(
        db,
        skip=skip,
        limit=limit,
        third_party_id=third_party_id,
        customer_id=customer_id,
        status=status_filter,
        due_before=due_before,
        due_after=due_after,
    )
    return [AccountReceivableResponse.model_validate(item) for item in balances]


@receivables_router.get(
    "/{receivable_id}",
    response_model=AccountReceivableResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener una cuenta por cobrar",
    dependencies=[Depends(require_accounting)],
)
def get_account_receivable(
    receivable_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> AccountReceivableResponse:
    """Devuelve el detalle de una CxC o 404 si no existe."""
    return AccountReceivableResponse.model_validate(
        services.get_account_receivable(db, receivable_id)
    )


@receivables_router.post(
    "/{receivable_id}/payments",
    response_model=PaymentRecordResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un abono a una cuenta por cobrar",
)
def register_receivable_payment(
    payload: PaymentRecordRequest,
    receivable_id: int = Path(gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_accounting),
) -> PaymentRecordResponse:
    """Aplica el cobro, actualiza el saldo y publica su asiento en un commit."""
    result = services.register_receivable_payment(
        db,
        receivable_id,
        payload.amount,
        payment_date=payload.payment_date,
        reference=payload.reference,
        created_by=current_user.username,
    )
    return PaymentRecordResponse.model_validate(result.payment)


payables_router = APIRouter(prefix="/payables", tags=["accounting: payables"])


@payables_router.get(
    "",
    response_model=list[AccountPayableResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar cuentas por pagar",
    dependencies=[Depends(require_accounting)],
)
def list_account_payables(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    third_party_id: int | None = Query(
        None, gt=0, description="Filtro por proveedor (alias de supplier_id)."
    ),
    supplier_id: int | None = Query(None, gt=0, description="Filtro por proveedor."),
    status_filter: AccountBalanceStatus | None = Query(None, alias="status"),
    due_before: date | None = Query(None, description="Vencimiento hasta esta fecha."),
    due_after: date | None = Query(None, description="Vencimiento desde esta fecha."),
    db: Session = Depends(get_db),
) -> list[AccountPayableResponse]:
    """Lista CxP con filtros por proveedor, estado y vencimiento."""
    balances = services.list_account_payables(
        db,
        skip=skip,
        limit=limit,
        third_party_id=third_party_id,
        supplier_id=supplier_id,
        status=status_filter,
        due_before=due_before,
        due_after=due_after,
    )
    return [AccountPayableResponse.model_validate(item) for item in balances]


@payables_router.get(
    "/{payable_id}",
    response_model=AccountPayableResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener una cuenta por pagar",
    dependencies=[Depends(require_accounting)],
)
def get_account_payable(
    payable_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> AccountPayableResponse:
    """Devuelve el detalle de una CxP o 404 si no existe."""
    return AccountPayableResponse.model_validate(
        services.get_account_payable(db, payable_id)
    )


@payables_router.post(
    "/{payable_id}/payments",
    response_model=PaymentRecordResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un pago a una cuenta por pagar",
)
def register_payable_payment(
    payload: PaymentRecordRequest,
    payable_id: int = Path(gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_accounting),
) -> PaymentRecordResponse:
    """Aplica el pago, actualiza el saldo y publica su asiento en un commit."""
    result = services.register_payable_payment(
        db,
        payable_id,
        payload.amount,
        payment_date=payload.payment_date,
        reference=payload.reference,
        created_by=current_user.username,
    )
    return PaymentRecordResponse.model_validate(result.payment)


# --------------------------------------------------------------------------- #
# Pagos y cobros — /api/v1/accounting/payments (spec, sección 4.4)
# --------------------------------------------------------------------------- #

payments_router = APIRouter(prefix="/payments", tags=["accounting: payments"])


@payments_router.get(
    "",
    response_model=list[PaymentRecordResponse],
    status_code=status.HTTP_200_OK,
    summary="Consultar el historial de cobros y pagos",
    dependencies=[Depends(require_accounting)],
)
def list_payment_records(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    receivable_id: int | None = Query(None, gt=0),
    payable_id: int | None = Query(None, gt=0),
    date_from: date | None = Query(None, description="Fecha inicial inclusive."),
    date_to: date | None = Query(None, description="Fecha final inclusive."),
    reference: str | None = Query(None, description="Filtro exacto por referencia."),
    db: Session = Depends(get_db),
) -> list[PaymentRecordResponse]:
    """Devuelve el historial de pagos con filtros por fecha y referencia."""
    records = services.list_payment_records(
        db,
        skip=skip,
        limit=limit,
        receivable_id=receivable_id,
        payable_id=payable_id,
        date_from=date_from,
        date_to=date_to,
        reference=reference,
    )
    return [PaymentRecordResponse.model_validate(item) for item in records]


@payments_router.post(
    "",
    response_model=PaymentRecordResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un cobro o pago",
)
def register_payment(
    payload: PaymentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_accounting),
) -> PaymentRecordResponse:
    """Despacha a CxC o CxP según el destino único indicado en el cuerpo."""
    if payload.receivable_id is not None:
        result = services.register_receivable_payment(
            db, payload, created_by=current_user.username
        )
    else:
        result = services.register_payable_payment(
            db, payload, created_by=current_user.username
        )
    return PaymentRecordResponse.model_validate(result.payment)


# --------------------------------------------------------------------------- #
# Reportes financieros — /api/v1/accounting/reports
# --------------------------------------------------------------------------- #

reports_router = APIRouter(prefix="/reports", tags=["accounting: reports"])


@reports_router.get(
    "/trial-balance",
    response_model=TrialBalanceResponse,
    status_code=status.HTTP_200_OK,
    summary="Generar el balance de comprobación",
    dependencies=[Depends(require_accounting)],
)
def trial_balance(
    db: Session = Depends(get_db),
    window: dict[str, Any] = Depends(_report_window),
) -> TrialBalanceResponse:
    """Sumas y saldos por cuenta de los asientos ``POSTED`` del periodo."""
    return services.get_trial_balance(db, **window)


@reports_router.get(
    "/balance-sheet",
    response_model=BalanceSheetResponse,
    status_code=status.HTTP_200_OK,
    summary="Generar el balance general",
    dependencies=[Depends(require_accounting)],
)
def balance_sheet(
    db: Session = Depends(get_db),
    window: dict[str, Any] = Depends(_report_window),
) -> BalanceSheetResponse:
    """Activos frente a pasivos y patrimonio con la ecuación verificada."""
    return services.get_balance_sheet(db, **window)


@reports_router.get(
    "/income-statement",
    response_model=IncomeStatementResponse,
    status_code=status.HTTP_200_OK,
    summary="Generar el estado de resultados",
    dependencies=[Depends(require_accounting)],
)
def income_statement(
    db: Session = Depends(get_db),
    window: dict[str, Any] = Depends(_report_window),
) -> IncomeStatementResponse:
    """Ingresos, gastos y utilidad o pérdida neta del periodo."""
    return services.get_income_statement(db, **window)


# --------------------------------------------------------------------------- #
# Agregación
# --------------------------------------------------------------------------- #

router = APIRouter()
router.include_router(accounts_router)
router.include_router(entries_router)
router.include_router(receivables_router)
router.include_router(payables_router)
router.include_router(payments_router)
router.include_router(reports_router)
