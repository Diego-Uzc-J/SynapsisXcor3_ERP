"""Servicios de dominio del módulo de Finanzas y Contabilidad.

Implementa el Hito 3 de ``specs/accounting_spec.md`` para el Plan de Cuentas y
el libro diario, los hitos 4-5 de automatización contable y cartera, y el
Hito 5 del apéndice de reportes financieros:

* **Cuentas:** alta con ``code`` único, listado filtrable, actualización parcial,
  desactivación (borrado lógico) y bloqueo de borrado físico cuando la cuenta
  tiene movimientos o subcuentas (regla 8).
* **Asientos en borrador:** unicidad de ``code``, existencia y ``is_active`` de
  todas las cuentas referenciadas (regla 4) y líneas no negativas de un solo
  lado (regla 6).
* **Contabilización:** ``post_journal_entry`` comprueba la partida doble exacta,
  cuentas activas y periodo abierto, y escribe estado, ``posted_at`` y líneas en
  un único ``COMMIT`` (reglas 1, 5 y 7).
* **Inmutabilidad y contrapartidas:** los asientos ``POSTED`` no se editan ni se
  borran; los borradores pueden anularse (``VOID``) y los publicados se corrigen
  con un asiento de reversión trazable (regla 2).
* **Automatización:** ``post_sales_invoice_accounting``,
  ``post_sales_credit_note_accounting``, ``post_purchase_receipt_accounting`` y
  ``post_supplier_bill_accounting`` convierten documentos de ``sales`` y
  ``purchasing`` en asientos ``POSTED`` y en CxC/CxP (regla 3).
* **Cartera:** ``register_receivable_payment`` y ``register_payable_payment``
  validan el saldo pendiente, actualizan ``paid_amount``, transicionan el estado
  y dejan un ``PaymentRecord`` con su asiento (reglas 5, 8 y 9 de la spec de
  aceptación).
* **Reportes:** ``get_trial_balance``, ``get_balance_sheet`` y
  ``get_income_statement`` agregan únicamente líneas de asientos ``POSTED``
  dentro del rango de fechas o del periodo indicado (sección 4.6).

Toda operación de escritura usa :func:`_atomic`, que confirma al finalizar y
hace ``rollback`` ante cualquier excepción, de modo que un asiento desbalanceado,
una cuenta inactiva o un fallo al actualizar un saldo no dejan registros
parciales. Las excepciones derivan de ``fastapi.HTTPException`` con
``status_code`` 400/404/409, igual que en ``sales`` y ``purchasing``.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import event, func, inspect, select
from sqlalchemy.orm import Session, selectinload

from src.modules.accounting.models import (
    Account,
    AccountBalanceStatus,
    AccountPayable,
    AccountReceivable,
    AccountType,
    AccountingPeriod,
    JournalEntry,
    JournalEntryStatus,
    JournalItem,
    PaymentRecord,
)
from src.modules.accounting.schemas import (
    AccountCreate,
    AccountUpdate,
    BalanceSheetResponse,
    IncomeStatementResponse,
    JournalEntryCreate,
    JournalEntryPostResponse,
    JournalItemCreate,
    PaymentCreate,
    ReportAccountLine,
    TrialBalanceLine,
    TrialBalanceResponse,
)
from src.modules.purchasing.models import (
    GoodsReceipt,
    GoodsReceiptItem,
    Supplier,
    SupplierBill,
)
from src.modules.sales.models import CreditNote, Invoice

__all__ = [
    "AccountInUseError",
    "AccountingAccounts",
    "AccountingError",
    "AccountingServiceError",
    "AccountingResult",
    "ClosedAccountingPeriodError",
    "DuplicateResourceError",
    "ImmutableJournalEntryError",
    "InactiveAccountError",
    "InvalidJournalEntryError",
    "InvalidJournalEntryStateError",
    "InvalidSourceDocumentError",
    "ParentCycleError",
    "PaymentResult",
    "ResourceNotFoundError",
    "UnbalancedJournalEntryError",
    "build_journal_entry_post_response",
    "create_account",
    "create_journal_entry",
    "deactivate_account",
    "delete_account",
    "delete_journal_entry",
    "ensure_account_active",
    "get_account",
    "get_account_payable",
    "get_account_receivable",
    "get_balance_sheet",
    "get_income_statement",
    "get_journal_entry",
    "get_trial_balance",
    "list_account_payables",
    "list_account_receivables",
    "list_accounts",
    "list_journal_entries",
    "list_payment_records",
    "post_journal_entry",
    "post_production_order_accounting",
    "post_payroll_run_accounting",
    "post_purchase_receipt_accounting",
    "post_sales_credit_note_accounting",
    "post_sales_invoice_accounting",
    "post_supplier_bill_accounting",
    "register_payable_payment",
    "register_receivable_payment",
    "reverse_journal_entry",
    "reject_journal_entry_mutation",
    "update_account",
    "update_journal_entry",
    "void_journal_entry",
]

#: Unidad mínima de los importes monetarios del ERP.
_CENT = Decimal("0.01")

#: Límite de ``Numeric(14, 2)`` expresado como Decimal.
_MAX_MONEY = Decimal("999999999999.99")

#: Clave base del advisory lock que serializa la secuencia ``REV-YYYY-XXXX``.
_REVERSAL_CODE_LOCK_BASE = 8_400_000

#: Bases distintas para que cada prefijo automático tenga su propia secuencia.
_AUTO_CODE_LOCK_BASES: dict[str, int] = {
    "ASI-FAC": 8_410_000,
    "ASI-NC": 8_410_100,
    "ASI-REC": 8_410_200,
    "ASI-FCP": 8_410_300,
    "ASI-COB": 8_410_400,
    "ASI-PAG": 8_410_500,
    "ASI-NOM": 8_410_600,
    "ASI-PRO": 8_410_700,
}

#: Mapeo por defecto de roles contables a códigos del PUC. Se usa solo cuando el
#: llamador no pasa el id de la cuenta; cualquier PUC puede sobrescribirlo.
DEFAULT_ACCOUNT_CODES: dict[str, str] = {
    "receivable": "130505",  # Clientes
    "revenue": "4135",  # Ventas
    "output_tax": "240805",  # IVA generado / por pagar
    "inventory": "1435",  # Inventario de mercancías
    "expense": "5100",  # Costo de ventas / gastos de compra
    "input_tax": "135515",  # IVA descontable
    "payable": "220505",  # Proveedores
    "cash": "110505",  # Caja General
    "bank": "111005",  # Bancos
}

#: Transiciones permitidas desde un borrador.
_DRAFT_TRANSITIONS = frozenset(
    {JournalEntryStatus.POSTED, JournalEntryStatus.VOID}
)


# --------------------------------------------------------------------------- #
# Excepciones HTTP de dominio
# --------------------------------------------------------------------------- #


class AccountingServiceError(HTTPException):
    """Error base del módulo de contabilidad con su equivalencia HTTP."""

    status_code: int = 400

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=self.status_code, detail=detail)

    def __str__(self) -> str:
        """Devuelve solo el mensaje, como las excepciones de dominio del ERP."""
        return str(self.detail)


class ResourceNotFoundError(AccountingServiceError):
    """El recurso solicitado no existe."""

    status_code = 404


class DuplicateResourceError(AccountingServiceError):
    """Se intentó persistir un valor que debe ser único."""

    status_code = 409


class InactiveAccountError(AccountingServiceError):
    """Una línea afecta una cuenta desactivada (regla 4 de la spec)."""

    status_code = 400


class AccountInUseError(AccountingServiceError):
    """La cuenta tiene movimientos o subcuentas y solo puede desactivarse."""

    status_code = 409


class ParentCycleError(AccountingServiceError):
    """La cuenta padre propuesta generaría un ciclo en la jerarquía."""

    status_code = 400


class InvalidJournalEntryError(AccountingServiceError):
    """El comprobante no cumple una regla de líneas o de periodo."""

    status_code = 400


class UnbalancedJournalEntryError(InvalidJournalEntryError):
    """Los débitos y los créditos no coinciden (regla 1 de la spec)."""

    status_code = 400

    def __init__(self, total_debit: Decimal, total_credit: Decimal) -> None:
        self.total_debit = total_debit
        self.total_credit = total_credit
        super().__init__(
            "El comprobante no está sumariamente equilibrado: "
            f"débitos {total_debit} != créditos {total_credit}"
        )


class ClosedAccountingPeriodError(InvalidJournalEntryError):
    """La fecha del asiento pertenece a un periodo contable cerrado."""

    status_code = 400

    def __init__(self, entry_date: date) -> None:
        self.entry_date = entry_date
        super().__init__(
            f"No se puede contabilizar el {entry_date.isoformat()}: "
            "el periodo contable está cerrado"
        )


class InvalidJournalEntryStateError(AccountingServiceError):
    """La operación no es válida para el estado actual del asiento."""

    status_code = 409


class ImmutableJournalEntryError(AccountingServiceError):
    """Un asiento publicado no puede modificarse ni eliminarse (regla 2)."""

    status_code = 400


class InvalidSourceDocumentError(AccountingServiceError):
    """El documento de ``sales``/``purchasing`` no puede contabilizarse."""

    status_code = 400


class AccountingError(AccountingServiceError):
    """Falta configuración contable necesaria para la integración."""

    status_code = 400


# --------------------------------------------------------------------------- #
# Resultados públicos de la automatización y la cartera
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AccountingResult:
    """Asiento publicado y saldo auxiliar afectado por una integración."""

    journal_entry: JournalEntry
    balance: AccountReceivable | AccountPayable | None = None


@dataclass(frozen=True)
class PaymentResult:
    """Asiento, registro de pago y saldo actualizado tras un cobro o pago."""

    journal_entry: JournalEntry
    payment: PaymentRecord
    balance: AccountReceivable | AccountPayable


@dataclass(frozen=True)
class AccountingAccounts:
    """Cuentas del PUC usadas por la automatización contable.

    Todos los campos son opcionales: cuando se omite un id, el servicio intenta
    resolverlo por el código configurable en :data:`DEFAULT_ACCOUNT_CODES`. Los
    campos ``output_tax``/``input_tax`` también pueden omitirse; en ese caso el
    impuesto se integra en la línea de ingresos o de gasto para conservar la
    partida doble.
    """

    receivable: int | None = None
    revenue: int | None = None
    output_tax: int | None = None
    inventory: int | None = None
    expense: int | None = None
    input_tax: int | None = None
    payable: int | None = None
    cash: int | None = None
    bank: int | None = None


# --------------------------------------------------------------------------- #
# Utilidades internas y control transaccional
# --------------------------------------------------------------------------- #


@contextmanager
def _atomic(db: Session) -> Iterator[None]:
    """Confirma la unidad de trabajo o revierte cualquier cambio ante un error."""
    try:
        yield
        db.commit()
    except Exception:
        db.rollback()
        raise


def _as_decimal(value: Any) -> Decimal:
    """Convierte valores de SQLAlchemy/SQLite a ``Decimal`` sin perder escala."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _money(value: Any) -> Decimal:
    """Redondea a dos decimales con ``ROUND_HALF_UP``."""
    return _as_decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def _ensure_money_range(value: Decimal, *, label: str) -> None:
    """Valida que un importe quepa en ``Numeric(14, 2)``."""
    if value.copy_abs() > _MAX_MONEY:
        raise InvalidJournalEntryError(
            f"El {label} excede el máximo permitido (14,2): {value}"
        )


def _as_status(value: Any) -> JournalEntryStatus | Any:
    """Normaliza el valor leído de la BD a ``JournalEntryStatus``."""
    if isinstance(value, JournalEntryStatus):
        return value
    try:
        return JournalEntryStatus(value)
    except (TypeError, ValueError):
        return value


def _get_account(db: Session, account_id: int) -> Account:
    """Obtiene una cuenta por id, sin importar su estado."""
    account = db.get(Account, account_id)
    if account is None:
        raise ResourceNotFoundError(f"Cuenta contable {account_id} no encontrada")
    return account


def ensure_account_active(db: Session, account_id: int) -> Account:
    """Obtiene una cuenta y exige que esté activa para recibir movimientos."""
    account = _get_account(db, account_id)
    if not account.is_active:
        raise InactiveAccountError(
            f"La cuenta {account.code} ('{account.name}') está inactiva y "
            "no admite movimientos contables"
        )
    return account


def _ensure_unique_account_code(
    db: Session, code: str, *, exclude_id: int | None = None
) -> None:
    """Verifica que el código del PUC no pertenezca a otra cuenta."""
    stmt = select(Account.id).where(Account.code == code)
    if exclude_id is not None:
        stmt = stmt.where(Account.id != exclude_id)
    if db.execute(stmt.limit(1)).first() is not None:
        raise DuplicateResourceError(
            f"Ya existe una cuenta contable con el código '{code}'"
        )


def _ensure_unique_entry_code(db: Session, code: str) -> None:
    """Verifica que el código del comprobante no esté en uso (regla 6)."""
    if db.execute(
        select(JournalEntry.id).where(JournalEntry.code == code).limit(1)
    ).first() is not None:
        raise DuplicateResourceError(
            f"Ya existe un asiento contable con el código '{code}'"
        )


def _ensure_no_parent_cycle(db: Session, account_id: int, parent_id: int) -> None:
    """Rechaza padres iguales a la cuenta o descendientes de ella."""
    current = parent_id
    seen: set[int] = set()
    while current is not None and current not in seen:
        if current == account_id:
            raise ParentCycleError(
                "La cuenta padre no puede ser la propia cuenta ni una subcuenta"
            )
        seen.add(current)
        parent = db.get(Account, current)
        if parent is None:
            raise ResourceNotFoundError(
                f"Cuenta padre {current} no encontrada"
            )
        current = parent.parent_id


def _ensure_account_deletable(db: Session, account_id: int) -> None:
    """Bloquea el borrado físico si hay movimientos o subcuentas (regla 8)."""
    has_children = db.execute(
        select(Account.id).where(Account.parent_id == account_id).limit(1)
    ).first()
    if has_children is not None:
        raise AccountInUseError(
            "La cuenta tiene subcuentas; desactívela en lugar de eliminarla"
        )

    has_items = db.execute(
        select(JournalItem.id).where(JournalItem.account_id == account_id).limit(1)
    ).first()
    if has_items is not None:
        raise AccountInUseError(
            "La cuenta tiene movimientos contables; desactívela en lugar de "
            "eliminarla"
        )


def _ensure_accounts_available(
    db: Session, account_ids: Sequence[int]
) -> dict[int, Account]:
    """Devuelve las cuentas referenciadas, exigiendo que existan y estén activas."""
    unique_ids = set(account_ids)
    accounts = {
        account.id: account
        for account in db.scalars(
            select(Account).where(Account.id.in_(list(unique_ids)))
        ).all()
    }
    missing = unique_ids - accounts.keys()
    if missing:
        raise ResourceNotFoundError(
            "Cuentas contables no encontradas: "
            + ", ".join(str(value) for value in sorted(missing))
        )
    inactive = [account for account in accounts.values() if not account.is_active]
    if inactive:
        raise InactiveAccountError(
            "No se permiten movimientos sobre cuentas contables inactivas: "
            + ", ".join(sorted(account.code for account in inactive))
        )
    return accounts


def _build_items(db: Session, data: Sequence[JournalItemCreate]) -> list[JournalItem]:
    """Construye líneas validando importes y cuentas activas."""
    if len(data) < 2:
        raise InvalidJournalEntryError(
            "Un asiento contable debe tener al menos dos líneas"
        )

    _ensure_accounts_available(db, [item.account_id for item in data])
    items: list[JournalItem] = []
    for line in data:
        debit = _money(line.debit)
        credit = _money(line.credit)
        _ensure_money_range(debit, label="débito de la línea")
        _ensure_money_range(credit, label="crédito de la línea")
        if debit < 0 or credit < 0:
            raise InvalidJournalEntryError(
                " Los importes de débito y crédito no pueden ser negativos"
            )
        if debit > 0 and credit > 0:
            raise InvalidJournalEntryError(
                "Una línea no puede tener débito y crédito positivos simultáneamente"
            )
        items.append(
            JournalItem(
                account_id=line.account_id,
                debit=debit,
                credit=credit,
                description=line.description,
            )
        )
    return items


def _items_totals(items: Sequence[JournalItem]) -> tuple[Decimal, Decimal]:
    """Suma débitos y créditos de unas líneas con precisión decimal."""
    total_debit = Decimal("0.00")
    total_credit = Decimal("0.00")
    for item in items:
        total_debit += _money(item.debit)
        total_credit += _money(item.credit)
    return _money(total_debit), _money(total_credit)


def _entry_totals(entry: JournalEntry) -> tuple[Decimal, Decimal]:
    """Suma débitos y créditos de las líneas de un asiento."""
    return _items_totals(entry.items)


def _ensure_balanced(entry: JournalEntry) -> tuple[Decimal, Decimal]:
    """Exige partida doble exacta y devuelve ``(débitos, créditos)``."""
    total_debit, total_credit = _entry_totals(entry)
    if total_debit != total_credit:
        raise UnbalancedJournalEntryError(total_debit, total_credit)
    return total_debit, total_credit


def _ensure_open_period(db: Session, entry_date: date) -> None:
    """Bloquea la contabilización en un periodo cerrado (regla 7).

    Si no existe un periodo que cubra la fecha se permite publicar: la spec
    solo prohíbe hacerlo en un ``AccountingPeriod`` marcado como cerrado.
    """
    closed = db.execute(
        select(AccountingPeriod.id)
        .where(
            AccountingPeriod.is_closed.is_(True),
            AccountingPeriod.start_date <= entry_date,
            AccountingPeriod.end_date >= entry_date,
        )
        .limit(1)
    ).first()
    if closed is not None:
        raise ClosedAccountingPeriodError(entry_date)


def _lock_sequence(db: Session, *, base: int, year: int) -> None:
    """Serializa la generación de códigos en PostgreSQL."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(select(func.pg_advisory_xact_lock(base + year)))


def _next_reversal_code(db: Session, year: int) -> str:
    """Devuelve el siguiente código ``REV-YYYY-XXXX`` para el año indicado."""
    _lock_sequence(db, base=_REVERSAL_CODE_LOCK_BASE, year=year)
    prefix = f"REV-{year}-"
    rows = db.scalars(
        select(JournalEntry.code).where(JournalEntry.code.like(f"{prefix}%"))
    ).all()
    max_sequence = 0
    for code in rows:
        suffix = code[len(prefix) :]
        if suffix.isdigit():
            max_sequence = max(max_sequence, int(suffix))
    return f"{prefix}{max_sequence + 1:04d}"


# --------------------------------------------------------------------------- #
# Soporte transversal para integraciones y cartera
# --------------------------------------------------------------------------- #


@contextmanager
def _unit_of_work(db: Session, *, commit: bool) -> Iterator[None]:
    """Aísla la frontera de commit para permitir llamadas desde otros módulos.

    Los servicios de ``sales``/``purchasing`` pueden pasar ``commit=False`` para
    incluir la contabilización en su propia transacción. Por defecto la función
    pública confirma y revierte por sí misma.
    """
    if commit:
        with _atomic(db):
            yield
    else:
        yield


def _resolve_account_id(
    db: Session, role: str, explicit_id: int | None, *, required: bool = True
) -> int | None:
    """Resuelve una cuenta por id explícito o por el código PUC por defecto."""
    if explicit_id is not None:
        return explicit_id
    code = DEFAULT_ACCOUNT_CODES[role]
    account = db.scalar(select(Account).where(Account.code == code))
    if account is not None:
        return account.id
    if required:
        raise AccountingError(
            f"Falta la cuenta '{role}' del PUC: configure el código '{code}' o "
            f"pase el parámetro '{role}_account_id'"
        )
    return None


def _next_auto_code(db: Session, *, prefix: str, year: int) -> str:
    """Genera ``ASI-XXX-YYYY-XXXX`` con una secuencia serializada por prefijo."""
    _lock_sequence(
        db, base=_AUTO_CODE_LOCK_BASES[prefix], year=year
    )
    pattern = f"{prefix}-{year}-%"
    rows = db.scalars(
        select(JournalEntry.code).where(JournalEntry.code.like(pattern))
    ).all()
    marker = f"{prefix}-{year}-"
    max_sequence = 0
    for code in rows:
        suffix = code[len(marker) :]
        if suffix.isdigit():
            max_sequence = max(max_sequence, int(suffix))
    return f"{marker}{max_sequence + 1:04d}"


def _find_generated_entry(
    db: Session, *, reference: str, label: str
) -> JournalEntry | None:
    """Localiza el asiento generado antes para un mismo documento."""
    return db.scalars(
        select(JournalEntry)
        .options(selectinload(JournalEntry.items))
        .where(
            JournalEntry.reference_document == reference,
            JournalEntry.description.like(f"{label}%"),
            JournalEntry.status == JournalEntryStatus.POSTED,
        )
        .order_by(JournalEntry.id)
        .limit(1)
    ).first()


def _ensure_entry_postable(db: Session, entry: JournalEntry) -> None:
    """Reúne las validaciones comunes antes de fijar ``POSTED``."""
    _ensure_accounts_available(db, [item.account_id for item in entry.items])
    _ensure_open_period(db, entry.entry_date)
    _ensure_balanced(entry)


def _build_posted_entry(
    db: Session,
    *,
    code: str,
    entry_date: date,
    description: str,
    reference_document: str | None,
    created_by: str | None,
    items: Sequence[JournalItemCreate],
) -> JournalEntry:
    """Construye un asiento ``POSTED`` validado sin hacer commit."""
    _ensure_unique_entry_code(db, code)
    entry = JournalEntry(
        code=code,
        entry_date=entry_date,
        description=description,
        reference_document=reference_document,
        status=JournalEntryStatus.POSTED,
        posted_at=datetime.now(timezone.utc),
        created_by=created_by,
        items=_build_items(db, items),
    )
    _ensure_entry_postable(db, entry)
    # No se añade a la sesión aquí: las validaciones consultan la BD y un
    # autoflush anticipado convertiría el primer INSERT en un UPDATE, que la
    # regla de inmutabilidad rechazaría. Cada llamador lo añade tras enlazar
    # las relaciones con la CxC/CxP o el PaymentRecord.
    return entry


def _get_document(db: Session, model: Any, document_id: int, label: str) -> Any:
    """Obtiene un documento por id o lanza ``ResourceNotFoundError``."""
    document = db.get(model, document_id)
    if document is None:
        raise ResourceNotFoundError(f"{label} {document_id} no encontrado")
    return document


def _get_invoice(db: Session, invoice_id: int) -> Invoice:
    """Obtiene una factura junto con el pedido que originó sus impuestos."""
    invoice = db.scalars(
        select(Invoice)
        .options(selectinload(Invoice.sales_order))
        .where(Invoice.id == invoice_id)
    ).first()
    if invoice is None:
        raise ResourceNotFoundError(f"Factura {invoice_id} no encontrada")
    return invoice


def _get_credit_note(db: Session, credit_note_id: int) -> CreditNote:
    """Obtiene una nota crédito junto con su factura de origen."""
    note = db.scalars(
        select(CreditNote)
        .options(selectinload(CreditNote.invoice))
        .where(CreditNote.id == credit_note_id)
    ).first()
    if note is None:
        raise ResourceNotFoundError(f"Nota crédito {credit_note_id} no encontrada")
    return note


def _get_receipt(db: Session, receipt_id: int) -> GoodsReceipt:
    """Obtiene una recepción con sus líneas, pedido y proveedor."""
    receipt = db.scalars(
        select(GoodsReceipt)
        .options(
            selectinload(GoodsReceipt.items).selectinload(
                GoodsReceiptItem.order_item
            ),
            selectinload(GoodsReceipt.order),
        )
        .where(GoodsReceipt.id == receipt_id)
    ).first()
    if receipt is None:
        raise ResourceNotFoundError(f"Recepción {receipt_id} no encontrada")
    return receipt


def _get_bill(db: Session, bill_id: int) -> SupplierBill:
    """Obtiene una factura de proveedor por id."""
    return _get_document(db, SupplierBill, bill_id, "Factura de proveedor")


def _as_balance_status(value: Any) -> AccountBalanceStatus | Any:
    """Normaliza un estado de cartera leído de la base de datos."""
    if isinstance(value, AccountBalanceStatus):
        return value
    try:
        return AccountBalanceStatus(value)
    except (TypeError, ValueError):
        return value


def _get_receivable_by_invoice(
    db: Session, invoice_id: int
) -> AccountReceivable | None:
    """Busca la CxC asociada a una factura de ventas."""
    return db.scalar(
        select(AccountReceivable).where(AccountReceivable.invoice_id == invoice_id)
    )


def _get_payable_by_reference(
    db: Session, bill_reference: str
) -> AccountPayable | None:
    """Busca la CxP asociada a un documento de compras."""
    return db.scalar(
        select(AccountPayable).where(
            AccountPayable.bill_reference == bill_reference
        )
    )


def _recompute_balance_status(balance: AccountReceivable | AccountPayable) -> AccountBalanceStatus:
    """Deriva el estado de la cartera a partir de ``paid_amount``."""
    total = _money(balance.total_amount)
    paid = _money(balance.paid_amount)
    if paid >= total:
        return AccountBalanceStatus.PAID
    current = _as_balance_status(balance.status)
    if current is AccountBalanceStatus.OVERDUE:
        return AccountBalanceStatus.OVERDUE
    if paid > 0:
        return AccountBalanceStatus.PARTIALLY_PAID
    return AccountBalanceStatus.PENDING


def _apply_payment_to_balance(
    balance: AccountReceivable | AccountPayable, amount: Decimal
) -> None:
    """Abona a una CxC/CxP y recalcula su estado (punto de rollback de pagos)."""
    balance.paid_amount = _money(_money(balance.paid_amount) + amount)
    if balance.paid_amount > _money(balance.total_amount):
        raise InvalidSourceDocumentError(
            "El abono acumulado supera el total de la cuenta de cartera"
        )
    balance.status = _recompute_balance_status(balance)


def _sales_tax_amount(db: Session, invoice: Invoice) -> Decimal:
    """Importe de impuesto de una factura, derivado de su pedido si existe."""
    if invoice.sales_order is None:
        return Decimal("0.00")
    total = _money(invoice.total)
    tax = _money(invoice.sales_order.tax_amount)
    if tax <= 0 or tax > total:
        return Decimal("0.00")
    if _money(invoice.sales_order.total) != total:
        return Decimal("0.00")
    return tax


def _receipt_amounts(receipt: GoodsReceipt) -> tuple[Decimal, Decimal, Decimal]:
    """Devuelve ``(subtotal, impuesto, total)`` de las líneas recibidas."""
    subtotal = Decimal("0.00")
    tax = Decimal("0.00")
    for line in receipt.items:
        order_item = line.order_item
        if order_item is None:
            raise InvalidSourceDocumentError(
                f"La línea {line.id} de la recepción no tiene línea de OC"
            )
        line_subtotal = _money(Decimal(line.quantity) * _money(order_item.unit_price))
        line_tax = _money(line_subtotal * _as_decimal(order_item.tax_rate) / Decimal("100"))
        subtotal += line_subtotal
        tax += line_tax
    return _money(subtotal), _money(tax), _money(subtotal + tax)


def _supplier_due_date(db: Session, supplier_id: int, from_date: date) -> date:
    """Fecha de vencimiento según los términos de pago del proveedor."""
    supplier = db.get(Supplier, supplier_id)
    days = supplier.payment_terms_days if supplier is not None else 30
    return from_date + timedelta(days=days)


# --------------------------------------------------------------------------- #
# Plan de cuentas — /api/v1/accounting/accounts
# --------------------------------------------------------------------------- #


def create_account(db: Session, data: AccountCreate) -> Account:
    """Registra una cuenta validando ``code`` único y cuenta padre existente."""
    _ensure_unique_account_code(db, data.code)
    if data.parent_id is not None:
        _get_account(db, data.parent_id)

    account = Account(**data.model_dump())
    try:
        with _atomic(db):
            db.add(account)
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            raise DuplicateResourceError(
                f"Ya existe una cuenta contable con el código '{data.code}'"
            ) from exc
        raise
    db.refresh(account)
    return account


def get_account(db: Session, account_id: int) -> Account:
    """Obtiene una cuenta por id o lanza ``ResourceNotFoundError``."""
    return _get_account(db, account_id)


def list_accounts(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 100,
    code: str | None = None,
    name: str | None = None,
    account_type: Any | None = None,
    is_active: bool | None = None,
    parent_id: int | None = None,
) -> list[Account]:
    """Lista cuentas con filtros por tipo, código, nombre y estado."""
    stmt = select(Account)
    if code:
        stmt = stmt.where(Account.code.ilike(f"%{code}%"))
    if name:
        stmt = stmt.where(Account.name.ilike(f"%{name}%"))
    if account_type is not None:
        stmt = stmt.where(Account.account_type == account_type)
    if is_active is not None:
        stmt = stmt.where(Account.is_active.is_(is_active))
    if parent_id is not None:
        stmt = stmt.where(Account.parent_id == parent_id)
    stmt = stmt.order_by(Account.code).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


def update_account(db: Session, account_id: int, data: AccountUpdate) -> Account:
    """Actualiza parcialmente una cuenta, impidiendo ciclos en la jerarquía."""
    account = _get_account(db, account_id)
    changes = data.model_dump(exclude_unset=True)

    new_code = changes.get("code")
    if new_code is not None and new_code != account.code:
        _ensure_unique_account_code(db, new_code, exclude_id=account_id)
    if "parent_id" in changes and changes["parent_id"] is not None:
        _ensure_no_parent_cycle(db, account_id, changes["parent_id"])

    try:
        with _atomic(db):
            for field, value in changes.items():
                setattr(account, field, value)
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            raise DuplicateResourceError(
                f"Ya existe una cuenta contable con el código '{new_code}'"
            ) from exc
        raise
    db.refresh(account)
    return account


def deactivate_account(db: Session, account_id: int) -> Account:
    """Desactiva una cuenta (borrado lógico) preservando su historial."""
    account = _get_account(db, account_id)
    if account.is_active:
        with _atomic(db):
            account.is_active = False
        db.refresh(account)
    return account


def delete_account(db: Session, account_id: int) -> None:
    """Elimina una cuenta vacía; las que tienen movimientos o hijos solo se desactivan."""
    account = _get_account(db, account_id)
    _ensure_account_deletable(db, account_id)
    with _atomic(db):
        db.delete(account)


# --------------------------------------------------------------------------- #
# Asientos contables — /api/v1/accounting/entries
# --------------------------------------------------------------------------- #


def get_journal_entry(
    db: Session, entry_id: int, *, for_update: bool = False
) -> JournalEntry:
    """Obtiene un asiento con sus líneas, opcionalmente bloqueando la fila."""
    stmt = select(JournalEntry).options(selectinload(JournalEntry.items))
    if for_update:
        stmt = stmt.with_for_update()
    entry = db.scalars(stmt.where(JournalEntry.id == entry_id)).first()
    if entry is None:
        raise ResourceNotFoundError(f"Asiento contable {entry_id} no encontrado")
    return entry


def list_journal_entries(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 100,
    code: str | None = None,
    status: JournalEntryStatus | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[JournalEntry]:
    """Lista asientos con filtros por código, estado y rango de fechas."""
    stmt = select(JournalEntry).options(selectinload(JournalEntry.items))
    if code:
        stmt = stmt.where(JournalEntry.code.ilike(f"%{code}%"))
    if status is not None:
        stmt = stmt.where(JournalEntry.status == status)
    if date_from is not None:
        stmt = stmt.where(JournalEntry.entry_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(JournalEntry.entry_date <= date_to)
    stmt = stmt.order_by(JournalEntry.id).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


def create_journal_entry(db: Session, data: JournalEntryCreate) -> JournalEntry:
    """Crea un comprobante en ``DRAFT`` con líneas y cuentas válidas.

    No se exige equilibrio aquí: la spec permite borradores desequilibrados y
    la partida doble se comprueba al publicar (regla 1).
    """
    _ensure_unique_entry_code(db, data.code)
    items = _build_items(db, data.items)

    entry = JournalEntry(
        code=data.code,
        entry_date=data.entry_date,
        description=data.description,
        reference_document=data.reference_document,
        status=JournalEntryStatus.DRAFT,
        created_by=data.created_by,
        items=items,
    )
    try:
        with _atomic(db):
            db.add(entry)
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            raise DuplicateResourceError(
                f"Ya existe un asiento contable con el código '{data.code}'"
            ) from exc
        raise
    db.refresh(entry)
    return entry


def update_journal_entry(
    db: Session, entry_id: int, data: JournalEntryCreate
) -> JournalEntry:
    """Sustituye el encabezado y las líneas de un asiento que siga en ``DRAFT``."""
    entry = get_journal_entry(db, entry_id, for_update=True)
    if entry.status is not JournalEntryStatus.DRAFT:
        raise ImmutableJournalEntryError(
            f"El asiento '{entry.code}' está {entry.status.value}: los asientos "
            "publicados o anulados no se editan; use un comprobante de reversión"
        )

    if data.code != entry.code:
        _ensure_unique_entry_code(db, data.code)
    items = _build_items(db, data.items)

    with _atomic(db):
        entry.code = data.code
        entry.entry_date = data.entry_date
        entry.description = data.description
        entry.reference_document = data.reference_document
        entry.created_by = data.created_by
        entry.items.clear()
        entry.items.extend(items)
    db.refresh(entry)
    return entry


def delete_journal_entry(db: Session, entry_id: int) -> None:
    """Descarta un borrador; los asientos ``POSTED`` son inmutables."""
    entry = get_journal_entry(db, entry_id, for_update=True)
    if entry.status is JournalEntryStatus.POSTED:
        raise ImmutableJournalEntryError(
            f"El asiento '{entry.code}' está publicado y no puede eliminarse: "
            "registre un asiento de reversión"
        )
    with _atomic(db):
        db.delete(entry)


def post_journal_entry(db: Session, entry_id: int) -> JournalEntry:
    """Contabiliza un borrador en una transacción atómica (reglas 1, 4, 5 y 7).

    Si falla cualquiera de las comprobaciones, ``_atomic`` revierte la sesión:
    el asiento permanece en ``DRAFT`` con ``posted_at=None`` y no queda ningún
    cambio parcial en las líneas o en el periodo.
    """
    entry = get_journal_entry(db, entry_id, for_update=True)
    if entry.status is JournalEntryStatus.POSTED:
        raise ImmutableJournalEntryError(
            f"El asiento '{entry.code}' ya está publicado"
        )
    if entry.status is JournalEntryStatus.VOID:
        raise InvalidJournalEntryStateError(
            f"El asiento '{entry.code}' está anulado y no puede publicarse"
        )

    with _atomic(db):
        _ensure_accounts_available(db, [item.account_id for item in entry.items])
        _ensure_open_period(db, entry.entry_date)
        _ensure_balanced(entry)
        entry.status = JournalEntryStatus.POSTED
        entry.posted_at = datetime.now(timezone.utc)
    db.refresh(entry)
    return entry


def void_journal_entry(db: Session, entry_id: int) -> JournalEntry:
    """Anula un borrador; un asiento publicado exige una reversión trazable."""
    entry = get_journal_entry(db, entry_id, for_update=True)
    if entry.status is JournalEntryStatus.POSTED:
        raise ImmutableJournalEntryError(
            f"El asiento '{entry.code}' está publicado: use reverse_journal_entry "
            "para generar un comprobante de reversión"
        )
    if entry.status is JournalEntryStatus.VOID:
        raise InvalidJournalEntryStateError(
            f"El asiento '{entry.code}' ya está anulado"
        )
    with _atomic(db):
        entry.status = JournalEntryStatus.VOID
    db.refresh(entry)
    return entry


def reverse_journal_entry(
    db: Session,
    entry_id: int,
    *,
    created_by: str | None = None,
) -> JournalEntry:
    """Genera y publica un asiento de reversión de uno ``POSTED``.

    El comprobante nuevo invierte débitos y créditos, referencia el código del
    original en ``reference_document`` y nace en ``POSTED`` dentro de la misma
    transacción. El asiento original nunca se modifica.
    """
    original = get_journal_entry(db, entry_id, for_update=True)
    if original.status is not JournalEntryStatus.POSTED:
        raise InvalidJournalEntryStateError(
            "Solo se pueden revertir asientos en estado POSTED; los borradores "
            "pueden anularse con void_journal_entry"
        )

    reversal_items: list[JournalItemCreate] = []
    for item in original.items:
        description = f"Reversión de {original.code}"
        if item.description:
            description += f": {item.description}"
        reversal_items.append(
            JournalItemCreate(
                account_id=item.account_id,
                debit=_money(item.credit),
                credit=_money(item.debit),
                description=description,
            )
        )

    reversal_date = date.today()
    code = _next_reversal_code(db, reversal_date.year)
    reversal = JournalEntry(
        code=code,
        entry_date=reversal_date,
        description=(
            f"Reversión del asiento {original.code}: {original.description}"
        ),
        reference_document=original.code,
        status=JournalEntryStatus.POSTED,
        posted_at=datetime.now(timezone.utc),
        created_by=created_by,
        items=_build_items(db, reversal_items),
    )
    with _atomic(db):
        _ensure_open_period(db, reversal.entry_date)
        _ensure_balanced(reversal)
        db.add(reversal)
    db.refresh(reversal)
    return reversal


def reject_journal_entry_mutation(db: Session, entry_id: int) -> None:
    """Bloquea explícitamente PATCH/DELETE sobre un asiento publicado."""
    entry = get_journal_entry(db, entry_id)
    raise ImmutableJournalEntryError(
        f"El asiento '{entry.code}' es inmutable: use void_journal_entry para "
        "borradores o reverse_journal_entry para asientos publicados"
    )


def build_journal_entry_post_response(
    entry: JournalEntry,
) -> JournalEntryPostResponse:
    """Construye la respuesta de publicación con los totales del comprobante."""
    total_debit, total_credit = _entry_totals(entry)
    return JournalEntryPostResponse(
        id=entry.id,
        code=entry.code,
        status=_as_status(entry.status),
        posted_at=entry.posted_at,  # type: ignore[arg-type]
        total_debit=total_debit,
        total_credit=total_credit,
    )


# --------------------------------------------------------------------------- #
# Automatización contable desde sales — regla 3 de la spec
# --------------------------------------------------------------------------- #

#: Etiquetas ASCII de las descripciones para localizar asientos ya generados.
_LABEL_INVOICE = "Factura venta"
_LABEL_CREDIT_NOTE = "Nota credito"
_LABEL_RECEIPT = "Recepcion compra"
_LABEL_BILL = "Factura proveedor"
_LABEL_RECEIVABLE_PAYMENT = "Cobro CxC"
_LABEL_PAYABLE_PAYMENT = "Pago CxP"
_LABEL_PAYROLL = "Nomina"
_LABEL_PRODUCTION = "Orden produccion"


def _status_value(value: Any) -> Any:
    """Devuelve el valor escalar de un enum nativo o de Python."""
    return getattr(value, "value", value)


def _upsert_receivable(
    db: Session,
    *,
    invoice: Invoice,
    entry: JournalEntry,
    total_amount: Decimal,
) -> AccountReceivable:
    """Crea o sincroniza la CxC de una factura con el importe vigente."""
    balance = _get_receivable_by_invoice(db, invoice.id)
    if balance is None:
        balance = AccountReceivable(
            customer_id=invoice.customer_id,
            invoice_id=invoice.id,
            journal_entry=entry,
            total_amount=_money(total_amount),
            paid_amount=Decimal("0.00"),
            due_date=invoice.due_date,
            status=AccountBalanceStatus.PENDING,
        )
        db.add(balance)
    else:
        balance.total_amount = _money(total_amount)
        if balance.journal_entry_id is None:
            balance.journal_entry = entry
        balance.status = _recompute_balance_status(balance)
    return balance


def post_sales_invoice_accounting(
    db: Session,
    invoice: int | Invoice,
    *,
    receivable_account_id: int | None = None,
    revenue_account_id: int | None = None,
    output_tax_account_id: int | None = None,
    tax_account_id: int | None = None,
    created_by: str | None = None,
    commit: bool = True,
) -> AccountingResult:
    """Contabiliza una factura de ventas y registra su CxC en una transacción.

    El asiento debita la cuenta de CxC por el total de la factura y acredita la
    cuenta de ingresos por el neto. Si hay impuesto y se configura
    ``output_tax_account_id`` (o el código PUC por defecto), el impuesto se
    acredita en su propia línea; en caso contrario se integra en la línea de
    ingresos para conservar la partida doble.

    La operación es idempotente: si el documento ya tiene un asiento ``POSTED``
    se devuelve ese asiento y su CxC sin duplicar movimientos.
    """
    document = _get_invoice(db, invoice) if isinstance(invoice, int) else invoice
    if _status_value(document.status) == "VOID":
        raise InvalidSourceDocumentError(
            f"La factura '{document.code}' está anulada y no genera asiento"
        )

    total = _money(document.total)
    if total <= 0:
        raise InvalidSourceDocumentError(
            f"La factura '{document.code}' no tiene un total contabilizable"
        )

    receivable_id = _resolve_account_id(db, "receivable", receivable_account_id)
    revenue_id = _resolve_account_id(db, "revenue", revenue_account_id)
    tax_id = _resolve_account_id(
        db,
        "output_tax",
        output_tax_account_id or tax_account_id,
        required=False,
    )
    tax = _sales_tax_amount(db, document) if tax_id is not None else Decimal("0.00")
    net = _money(total - tax)

    items = [
        JournalItemCreate(
            account_id=receivable_id,  # type: ignore[arg-type]
            debit=total,
            credit=Decimal("0.00"),
            description=f"CxC factura {document.code}",
        ),
        JournalItemCreate(
            account_id=revenue_id,  # type: ignore[arg-type]
            debit=Decimal("0.00"),
            credit=net,
            description=f"Ingreso factura {document.code}",
        ),
    ]
    if tax_id is not None and tax > 0:
        items.append(
            JournalItemCreate(
                account_id=tax_id,
                debit=Decimal("0.00"),
                credit=tax,
                description=f"Impuesto factura {document.code}",
            )
        )

    with _unit_of_work(db, commit=commit):
        existing = _find_generated_entry(
            db, reference=document.code, label=_LABEL_INVOICE
        )
        if existing is not None:
            return AccountingResult(
                existing, _get_receivable_by_invoice(db, document.id)
            )

        code = _next_auto_code(db, prefix="ASI-FAC", year=document.issue_date.year)
        entry = _build_posted_entry(
            db,
            code=code,
            entry_date=document.issue_date,
            description=f"{_LABEL_INVOICE} {document.code}",
            reference_document=document.code,
            created_by=created_by or "accounting-automation",
            items=items,
        )
        balance = _upsert_receivable(
            db, invoice=document, entry=entry, total_amount=total
        )
        # Se añade al final, con las relaciones ya enlazadas, para evitar que un
        # autoflush durante las validaciones provoque un UPDATE del asiento.
        db.add(entry)
    if commit:
        db.refresh(entry)
        db.refresh(balance)
    return AccountingResult(entry, balance)


def post_sales_credit_note_accounting(
    db: Session,
    credit_note: int | CreditNote,
    *,
    receivable_account_id: int | None = None,
    revenue_account_id: int | None = None,
    output_tax_account_id: int | None = None,
    tax_account_id: int | None = None,
    created_by: str | None = None,
    commit: bool = True,
) -> AccountingResult:
    """Contabiliza una nota crédito y reduce la CxC de la factura de origen.

    El asiento debita ingresos (y el impuesto proporcional, si está configurado)
    y acredita la cuenta de CxC. El ``total_amount`` de la CxC se reduce sin
    borrar el historial de pagos; si ya estaba liquidada, el saldo queda en cero.
    """
    note = (
        _get_credit_note(db, credit_note)
        if isinstance(credit_note, int)
        else credit_note
    )
    invoice = note.invoice
    if invoice is None:
        raise InvalidSourceDocumentError(
            f"La nota crédito '{note.code}' no tiene factura de origen"
        )

    amount = _money(note.amount)
    if amount <= 0:
        raise InvalidSourceDocumentError(
            f"La nota crédito '{note.code}' no tiene un importe válido"
        )

    receivable_id = _resolve_account_id(db, "receivable", receivable_account_id)
    revenue_id = _resolve_account_id(db, "revenue", revenue_account_id)
    tax_id = _resolve_account_id(
        db,
        "output_tax",
        output_tax_account_id or tax_account_id,
        required=False,
    )
    tax = Decimal("0.00")
    if tax_id is not None:
        tax = _sales_tax_amount(db, invoice)
        invoice_total = _money(invoice.total)
        if tax > 0 and invoice_total > 0:
            tax = min(amount, _money(amount * tax / invoice_total))
        else:
            tax = Decimal("0.00")
    net = _money(amount - tax)

    items = [
        JournalItemCreate(
            account_id=revenue_id,  # type: ignore[arg-type]
            debit=net,
            credit=Decimal("0.00"),
            description=f"Descuento nota crédito {note.code}",
        ),
        JournalItemCreate(
            account_id=receivable_id,  # type: ignore[arg-type]
            debit=Decimal("0.00"),
            credit=amount,
            description=f"CxC nota crédito {note.code}",
        ),
    ]
    if tax_id is not None and tax > 0:
        items.append(
            JournalItemCreate(
                account_id=tax_id,
                debit=tax,
                credit=Decimal("0.00"),
                description=f"Impuesto nota crédito {note.code}",
            )
        )

    with _unit_of_work(db, commit=commit):
        existing = _find_generated_entry(
            db, reference=note.code, label=_LABEL_CREDIT_NOTE
        )
        if existing is not None:
            return AccountingResult(
                existing, _get_receivable_by_invoice(db, invoice.id)
            )

        code = _next_auto_code(db, prefix="ASI-NC", year=note.issue_date.year)
        entry = _build_posted_entry(
            db,
            code=code,
            entry_date=note.issue_date,
            description=f"{_LABEL_CREDIT_NOTE} {note.code}",
            reference_document=note.code,
            created_by=created_by or "accounting-automation",
            items=items,
        )
        balance = _get_receivable_by_invoice(db, invoice.id)
        if balance is None:
            balance = AccountReceivable(
                customer_id=invoice.customer_id,
                invoice_id=invoice.id,
                journal_entry=entry,
                total_amount=max(
                    Decimal("0.00"), _money(_money(invoice.total) - amount)
                ),
                paid_amount=Decimal("0.00"),
                due_date=invoice.due_date,
                status=AccountBalanceStatus.PENDING,
            )
            db.add(balance)
        else:
            balance.total_amount = max(
                _money(balance.paid_amount),
                _money(_money(balance.total_amount) - amount),
            )
            if balance.journal_entry_id is None:
                balance.journal_entry = entry
            balance.status = _recompute_balance_status(balance)
        db.add(entry)
    if commit:
        db.refresh(entry)
        db.refresh(balance)
    return AccountingResult(entry, balance)


def _resolve_purchase_accounts(
    db: Session,
    *,
    inventory_account_id: int | None,
    expense_account_id: int | None,
    input_tax_account_id: int | None,
    tax_account_id: int | None,
    payable_account_id: int | None,
) -> tuple[int, int | None, int]:
    """Resuelve las cuentas de inventario/gasto, impuesto y por pagar."""
    inventory_id = _resolve_account_id(
        db, "inventory", inventory_account_id, required=False
    )
    expense_id = _resolve_account_id(
        db, "expense", expense_account_id, required=False
    )
    if inventory_id is None and expense_id is None:
        raise AccountingError(
            "Falta la cuenta de inventario o gasto: configure el código del PUC "
            "o pase inventory_account_id / expense_account_id"
        )
    debit_account_id = inventory_id or expense_id
    tax_id = _resolve_account_id(
        db, "input_tax", input_tax_account_id or tax_account_id, required=False
    )
    payable_id = _resolve_account_id(db, "payable", payable_account_id)
    return debit_account_id, tax_id, payable_id  # type: ignore[return-value]


def _upsert_payable(
    db: Session,
    *,
    bill_reference: str,
    supplier_id: int,
    entry: JournalEntry,
    total_amount: Decimal,
    due_date: date,
) -> AccountPayable:
    """Crea o sincroniza la CxP de un documento de compras."""
    balance = _get_payable_by_reference(db, bill_reference)
    if balance is None:
        balance = AccountPayable(
            supplier_id=supplier_id,
            bill_reference=bill_reference,
            journal_entry=entry,
            total_amount=_money(total_amount),
            paid_amount=Decimal("0.00"),
            due_date=due_date,
            status=AccountBalanceStatus.PENDING,
        )
        db.add(balance)
    else:
        balance.total_amount = _money(total_amount)
        if balance.journal_entry_id is None:
            balance.journal_entry = entry
        balance.status = _recompute_balance_status(balance)
    return balance


def post_purchase_receipt_accounting(
    db: Session,
    receipt: int | GoodsReceipt,
    *,
    inventory_account_id: int | None = None,
    expense_account_id: int | None = None,
    input_tax_account_id: int | None = None,
    tax_account_id: int | None = None,
    payable_account_id: int | None = None,
    created_by: str | None = None,
    commit: bool = True,
) -> AccountingResult:
    """Contabiliza una recepción de mercancía y abre su CxP.

    El importe se deriva de las líneas recibidas (cantidad × precio de la OC y
    su tasa de impuesto), debitando inventario —o gasto si no hay cuenta de
    inventario— y acreditando la cuenta de CxP.
    """
    document = _get_receipt(db, receipt) if isinstance(receipt, int) else receipt
    order = document.order
    if order is None:
        raise InvalidSourceDocumentError(
            f"La recepción '{document.code}' no tiene orden de compra"
        )

    subtotal, document_tax, total = _receipt_amounts(document)
    if total <= 0:
        raise InvalidSourceDocumentError(
            f"La recepción '{document.code}' no tiene un total contabilizable"
        )

    debit_id, tax_id, payable_id = _resolve_purchase_accounts(
        db,
        inventory_account_id=inventory_account_id,
        expense_account_id=expense_account_id,
        input_tax_account_id=input_tax_account_id,
        tax_account_id=tax_account_id,
        payable_account_id=payable_account_id,
    )
    tax = document_tax if tax_id is not None else Decimal("0.00")
    debit_amount = subtotal if tax_id is not None and tax > 0 else total

    items = [
        JournalItemCreate(
            account_id=debit_id,
            debit=debit_amount,
            credit=Decimal("0.00"),
            description=f"Inventario recepción {document.code}",
        ),
        JournalItemCreate(
            account_id=payable_id,
            debit=Decimal("0.00"),
            credit=total,
            description=f"CxP recepción {document.code}",
        ),
    ]
    if tax_id is not None and tax > 0:
        items.append(
            JournalItemCreate(
                account_id=tax_id,
                debit=tax,
                credit=Decimal("0.00"),
                description=f"Impuesto recepción {document.code}",
            )
        )

    due_date = _supplier_due_date(db, order.supplier_id, document.receipt_date)
    with _unit_of_work(db, commit=commit):
        existing = _find_generated_entry(
            db, reference=document.code, label=_LABEL_RECEIPT
        )
        if existing is not None:
            return AccountingResult(
                existing, _get_payable_by_reference(db, document.code)
            )

        code = _next_auto_code(db, prefix="ASI-REC", year=document.receipt_date.year)
        entry = _build_posted_entry(
            db,
            code=code,
            entry_date=document.receipt_date,
            description=f"{_LABEL_RECEIPT} {document.code}",
            reference_document=document.code,
            created_by=created_by or "accounting-automation",
            items=items,
        )
        balance = _upsert_payable(
            db,
            bill_reference=document.code,
            supplier_id=order.supplier_id,
            entry=entry,
            total_amount=total,
            due_date=due_date,
        )
        db.add(entry)
    if commit:
        db.refresh(entry)
        db.refresh(balance)
    return AccountingResult(entry, balance)


def post_supplier_bill_accounting(
    db: Session,
    bill: int | SupplierBill,
    *,
    inventory_account_id: int | None = None,
    expense_account_id: int | None = None,
    input_tax_account_id: int | None = None,
    tax_account_id: int | None = None,
    payable_account_id: int | None = None,
    created_by: str | None = None,
    commit: bool = True,
) -> AccountingResult:
    """Contabiliza una factura de proveedor y su CxP en una transacción.

    Usa los importes propios de la factura (``subtotal``, ``tax_amount`` y
    ``total``) y respeta el mismo mapeo de inventario/gasto e impuestos que la
    recepción de mercancía.
    """
    document = _get_bill(db, bill) if isinstance(bill, int) else bill
    if _status_value(document.status) == "VOID":
        raise InvalidSourceDocumentError(
            f"La factura de proveedor '{document.code}' está anulada"
        )

    subtotal = _money(document.subtotal)
    document_tax = _money(document.tax_amount)
    total = _money(document.total)
    if total <= 0:
        raise InvalidSourceDocumentError(
            f"La factura de proveedor '{document.code}' no tiene un total válido"
        )

    debit_id, tax_id, payable_id = _resolve_purchase_accounts(
        db,
        inventory_account_id=inventory_account_id,
        expense_account_id=expense_account_id,
        input_tax_account_id=input_tax_account_id,
        tax_account_id=tax_account_id,
        payable_account_id=payable_account_id,
    )
    tax = document_tax if tax_id is not None else Decimal("0.00")
    debit_amount = subtotal if tax_id is not None and tax > 0 else total

    items = [
        JournalItemCreate(
            account_id=debit_id,
            debit=debit_amount,
            credit=Decimal("0.00"),
            description=f"Compra factura {document.code}",
        ),
        JournalItemCreate(
            account_id=payable_id,
            debit=Decimal("0.00"),
            credit=total,
            description=f"CxP factura {document.code}",
        ),
    ]
    if tax_id is not None and tax > 0:
        items.append(
            JournalItemCreate(
                account_id=tax_id,
                debit=tax,
                credit=Decimal("0.00"),
                description=f"Impuesto factura {document.code}",
            )
        )

    with _unit_of_work(db, commit=commit):
        existing = _find_generated_entry(
            db, reference=document.code, label=_LABEL_BILL
        )
        if existing is not None:
            return AccountingResult(
                existing, _get_payable_by_reference(db, document.code)
            )

        code = _next_auto_code(db, prefix="ASI-FCP", year=document.issue_date.year)
        entry = _build_posted_entry(
            db,
            code=code,
            entry_date=document.issue_date,
            description=f"{_LABEL_BILL} {document.code}",
            reference_document=document.code,
            created_by=created_by or "accounting-automation",
            items=items,
        )
        balance = _upsert_payable(
            db,
            bill_reference=document.code,
            supplier_id=document.supplier_id,
            entry=entry,
            total_amount=total,
            due_date=document.due_date,
        )
        db.add(entry)
    if commit:
        db.refresh(entry)
        db.refresh(balance)
    return AccountingResult(entry, balance)


def post_payroll_run_accounting(
    db: Session,
    *,
    code: str,
    entry_date: date,
    total_earnings: Decimal,
    total_deductions: Decimal,
    total_net: Decimal,
    expense_account_id: int | None = None,
    payable_account_id: int | None = None,
    deductions_account_id: int | None = None,
    created_by: str | None = None,
    commit: bool = True,
) -> AccountingResult:
    """Contabiliza una nómina: debita gasto de personal y acredita pasivos.

    El asiento debita la cuenta de gasto por el total devengado y acredita:

    * la cuenta por pagar de nómina por el neto a pagar;
    * la cuenta de pasivo laboral por las deducciones, cuando las hay. Si no se
      configura ``deductions_account_id``, se usa la misma cuenta ``payable``.

    La partida doble se valida antes de fijar ``POSTED``. Con ``commit=False``
    el llamador (por ejemplo ``hr.approve_payroll_run``) incluye el asiento en
    su propia unidad de trabajo; con el valor por defecto la función confirma
    y revierte por sí misma. Es idempotente por el código del periodo.
    """
    earnings = _money(total_earnings)
    deductions = _money(total_deductions)
    net = _money(total_net)

    if earnings <= 0:
        raise InvalidJournalEntryError(
            f"La nómina '{code}' no tiene un total devengado contabilizable"
        )
    if deductions < 0 or net < 0:
        raise InvalidJournalEntryError(
            f"La nómina '{code}' tiene deducciones o neto negativos"
        )
    if net != earnings - deductions:
        raise InvalidJournalEntryError(
            f"La nómina '{code}' no es consistente: neto {net} != "
            f"devengado {earnings} - deducciones {deductions}"
        )
    for label, amount in (
        ("devengado de la nómina", earnings),
        ("deducciones de la nómina", deductions),
        ("neto de la nómina", net),
    ):
        _ensure_money_range(amount, label=label)

    expense_id = _resolve_account_id(db, "expense", expense_account_id)
    payable_id = _resolve_account_id(db, "payable", payable_account_id)
    deductions_id = _resolve_account_id(db, "payable", deductions_account_id)

    items = [
        JournalItemCreate(
            account_id=expense_id,  # type: ignore[arg-type]
            debit=earnings,
            credit=Decimal("0.00"),
            description=f"Gasto personal nomina {code}",
        ),
        JournalItemCreate(
            account_id=payable_id,  # type: ignore[arg-type]
            debit=Decimal("0.00"),
            credit=net,
            description=f"CxP nomina {code}",
        ),
    ]
    if deductions > 0:
        items.append(
            JournalItemCreate(
                account_id=deductions_id,  # type: ignore[arg-type]
                debit=Decimal("0.00"),
                credit=deductions,
                description=f"Deducciones nomina {code}",
            )
        )

    with _unit_of_work(db, commit=commit):
        existing = _find_generated_entry(
            db, reference=code, label=_LABEL_PAYROLL
        )
        if existing is not None:
            return AccountingResult(existing, None)

        entry_code = _next_auto_code(db, prefix="ASI-NOM", year=entry_date.year)
        entry = _build_posted_entry(
            db,
            code=entry_code,
            entry_date=entry_date,
            description=f"{_LABEL_PAYROLL} {code}",
            reference_document=code,
            created_by=created_by or "hr-payroll-approval",
            items=items,
        )
        # _build_posted_entry valida sin añadir a la sesión para evitar un
        # autoflush anticipado; el llamador lo registra dentro de su transacción.
        db.add(entry)
    if commit:
        db.refresh(entry)
    return AccountingResult(entry, None)


def post_production_order_accounting(
    db: Session,
    *,
    order_code: str,
    entry_date: date,
    total_cost: Decimal,
    materials_cost: Decimal,
    labor_cost: Decimal,
    finished_goods_account_id: int | None = None,
    materials_account_id: int | None = None,
    labor_account_id: int | None = None,
    created_by: str | None = None,
    commit: bool = True,
) -> JournalEntry:
    """Contabiliza el cierre de una OP de manufactura (spec manufacturing §3.3).

    El asiento debita el inventario de producto terminado por el coste total y
    acredita el inventario de materias primas por el consumo y la cuenta de
    pasivo laboral por la mano de obra del centro de trabajo. Las cuentas se
    resuelven por id explícito o por los códigos PUC por defecto; cuando no se
    configuran cuentas distintas, producto terminado y materias primas comparten
    la cuenta ``inventory`` sin romper la partida doble.

    Con ``commit=False`` el llamador (``manufacturing.complete_production_order``)
    incluye el asiento en su propia unidad de trabajo. Es idempotente por el
    código de la orden: si ya existe un asiento ``POSTED`` se devuelve sin
    duplicarlo.
    """
    total = _money(total_cost)
    materials = _money(materials_cost)
    labor = _money(labor_cost)

    if total <= 0:
        raise InvalidJournalEntryError(
            f"La orden '{order_code}' no tiene un coste contabilizable"
        )
    if materials < 0 or labor < 0:
        raise InvalidJournalEntryError(
            f"La orden '{order_code}' tiene costes negativos"
        )
    if total != _money(materials + labor):
        raise InvalidJournalEntryError(
            f"El coste de la orden '{order_code}' no es consistente: total "
            f"{total} != materiales {materials} + mano de obra {labor}"
        )
    for label, amount in (
        ("coste total de producción", total),
        ("coste de materiales", materials),
        ("coste de mano de obra", labor),
    ):
        _ensure_money_range(amount, label=label)

    finished_id = _resolve_account_id(
        db, "inventory", finished_goods_account_id
    )
    materials_id = _resolve_account_id(db, "inventory", materials_account_id)
    labor_id = _resolve_account_id(db, "payable", labor_account_id)

    zero = Decimal("0.00")
    items = [
        JournalItemCreate(
            account_id=finished_id,  # type: ignore[arg-type]
            debit=total,
            credit=zero,
            description=f"Producto terminado OP {order_code}",
        ),
        JournalItemCreate(
            account_id=materials_id,  # type: ignore[arg-type]
            debit=zero,
            credit=materials,
            description=f"Consumo de materias primas OP {order_code}",
        ),
    ]
    if labor > 0:
        items.append(
            JournalItemCreate(
                account_id=labor_id,  # type: ignore[arg-type]
                debit=zero,
                credit=labor,
                description=f"Mano de obra OP {order_code}",
            )
        )

    with _unit_of_work(db, commit=commit):
        existing = _find_generated_entry(
            db, reference=order_code, label=_LABEL_PRODUCTION
        )
        if existing is not None:
            return existing

        entry = _build_posted_entry(
            db,
            code=_next_auto_code(db, prefix="ASI-PRO", year=entry_date.year),
            entry_date=entry_date,
            description=f"{_LABEL_PRODUCTION} {order_code}",
            reference_document=order_code,
            created_by=created_by or "manufacturing-automation",
            items=items,
        )
        db.add(entry)
    if commit:
        db.refresh(entry)
    return entry


# --------------------------------------------------------------------------- #
# Cartera: consultas y registro de cobros/pagos — reglas 5, 8 y 9
# --------------------------------------------------------------------------- #


def get_account_receivable(db: Session, receivable_id: int) -> AccountReceivable:
    """Obtiene una CxC por id."""
    return _get_document(db, AccountReceivable, receivable_id, "Cuenta por cobrar")


def list_account_receivables(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 100,
    third_party_id: int | None = None,
    customer_id: int | None = None,
    status: AccountBalanceStatus | None = None,
    due_before: date | None = None,
    due_after: date | None = None,
) -> list[AccountReceivable]:
    """Lista CxC con filtros por cliente, estado y vencimiento."""
    stmt = select(AccountReceivable)
    party = customer_id or third_party_id
    if party is not None:
        stmt = stmt.where(AccountReceivable.customer_id == party)
    if status is not None:
        stmt = stmt.where(AccountReceivable.status == status)
    if due_before is not None:
        stmt = stmt.where(AccountReceivable.due_date <= due_before)
    if due_after is not None:
        stmt = stmt.where(AccountReceivable.due_date >= due_after)
    stmt = stmt.order_by(AccountReceivable.id).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


def get_account_payable(db: Session, payable_id: int) -> AccountPayable:
    """Obtiene una CxP por id."""
    return _get_document(db, AccountPayable, payable_id, "Cuenta por pagar")


def list_account_payables(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 100,
    third_party_id: int | None = None,
    supplier_id: int | None = None,
    status: AccountBalanceStatus | None = None,
    due_before: date | None = None,
    due_after: date | None = None,
) -> list[AccountPayable]:
    """Lista CxP con filtros por proveedor, estado y vencimiento."""
    stmt = select(AccountPayable)
    party = supplier_id or third_party_id
    if party is not None:
        stmt = stmt.where(AccountPayable.supplier_id == party)
    if status is not None:
        stmt = stmt.where(AccountPayable.status == status)
    if due_before is not None:
        stmt = stmt.where(AccountPayable.due_date <= due_before)
    if due_after is not None:
        stmt = stmt.where(AccountPayable.due_date >= due_after)
    stmt = stmt.order_by(AccountPayable.id).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


def list_payment_records(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 100,
    receivable_id: int | None = None,
    payable_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    reference: str | None = None,
) -> list[PaymentRecord]:
    """Consulta el historial de cobros y pagos."""
    stmt = select(PaymentRecord)
    if receivable_id is not None:
        stmt = stmt.where(PaymentRecord.receivable_id == receivable_id)
    if payable_id is not None:
        stmt = stmt.where(PaymentRecord.payable_id == payable_id)
    if date_from is not None:
        stmt = stmt.where(PaymentRecord.payment_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(PaymentRecord.payment_date <= date_to)
    if reference:
        stmt = stmt.where(PaymentRecord.reference == reference)
    stmt = stmt.order_by(PaymentRecord.id).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


def _resolve_payment_account(
    db: Session,
    *,
    cash_account_id: int | None,
    bank_account_id: int | None,
    payment_account_id: int | None,
) -> int:
    """Cuenta de efectivo/banco que contrapartiza el cobro o pago."""
    explicit = payment_account_id or bank_account_id or cash_account_id
    if explicit is not None:
        return explicit
    cash = _resolve_account_id(db, "cash", None, required=False)
    if cash is not None:
        return cash
    bank = _resolve_account_id(db, "bank", None, required=False)
    if bank is not None:
        return bank
    raise AccountingError(
        "Falta la cuenta de caja o banco para registrar el movimiento de efectivo"
    )


def register_receivable_payment(
    db: Session,
    receivable: int | PaymentCreate,
    amount: Decimal | str | None = None,
    *,
    payment_date: date | None = None,
    reference: str | None = None,
    receivable_account_id: int | None = None,
    cash_account_id: int | None = None,
    bank_account_id: int | None = None,
    payment_account_id: int | None = None,
    created_by: str | None = None,
    code: str | None = None,
    commit: bool = True,
) -> PaymentResult:
    """Registra un cobro en una CxC con asiento ``POSTED`` y saldo actualizado.

    Acepta un ``PaymentCreate`` como primer argumento o un ``receivable_id``
    seguido del importe. Valida ``0 < amount <= total_amount - paid_amount``;
    dentro de una sola transacción crea el asiento (debe Caja/Banco, haber CxC),
    el ``PaymentRecord`` y actualiza ``paid_amount`` y el estado. Cualquier fallo
    revierte los tres efectos.
    """
    if isinstance(receivable, PaymentCreate):
        data = receivable
        if data.payable_id is not None or data.receivable_id is None:
            raise InvalidSourceDocumentError(
                "PaymentCreate debe apuntar exactamente a una CxC"
            )
        target_id = data.receivable_id
        amount = data.amount
        payment_date = payment_date or data.payment_date
        reference = reference or data.reference
    else:
        target_id = receivable
    if amount is None:
        raise InvalidSourceDocumentError("Se requiere el importe del cobro")

    value = _money(amount)
    if value <= 0:
        raise InvalidSourceDocumentError("El importe del cobro debe ser mayor que cero")
    when = payment_date or date.today()

    balance = db.scalars(
        select(AccountReceivable)
        .where(AccountReceivable.id == target_id)
        .with_for_update()
    ).first()
    if balance is None:
        raise ResourceNotFoundError(f"Cuenta por cobrar {target_id} no encontrada")

    remaining = _money(_money(balance.total_amount) - _money(balance.paid_amount))
    if remaining <= 0:
        raise InvalidSourceDocumentError("La cuenta por cobrar ya está liquidada")
    if value > remaining:
        raise InvalidSourceDocumentError(
            f"El cobro ({value}) excede el saldo pendiente de la CxC ({remaining})"
        )

    cash_id = _resolve_payment_account(
        db,
        cash_account_id=cash_account_id,
        bank_account_id=bank_account_id,
        payment_account_id=payment_account_id,
    )
    receivable_id = _resolve_account_id(db, "receivable", receivable_account_id)
    entry_code = code or _next_auto_code(db, prefix="ASI-COB", year=when.year)
    description = f"{_LABEL_RECEIVABLE_PAYMENT} CxC-{target_id}"

    with _unit_of_work(db, commit=commit):
        entry = _build_posted_entry(
            db,
            code=entry_code,
            entry_date=when,
            description=description,
            reference_document=reference or f"CxC-{target_id}",
            created_by=created_by or "accounting-automation",
            items=[
                JournalItemCreate(
                    account_id=cash_id,
                    debit=value,
                    credit=Decimal("0.00"),
                    description=f"Cobro aplicado a CxC-{target_id}",
                ),
                JournalItemCreate(
                    account_id=receivable_id,
                    debit=Decimal("0.00"),
                    credit=value,
                    description=f"Abono a CxC-{target_id}",
                ),
            ],
        )
        payment = PaymentRecord(
            receivable=balance,
            journal_entry=entry,
            amount=value,
            payment_date=when,
            reference=reference,
        )
        db.add(payment)
        db.add(entry)
        _apply_payment_to_balance(balance, value)
    if commit:
        db.refresh(entry)
        db.refresh(payment)
        db.refresh(balance)
    return PaymentResult(entry, payment, balance)


def register_payable_payment(
    db: Session,
    payable: int | PaymentCreate,
    amount: Decimal | str | None = None,
    *,
    payment_date: date | None = None,
    reference: str | None = None,
    payable_account_id: int | None = None,
    cash_account_id: int | None = None,
    bank_account_id: int | None = None,
    payment_account_id: int | None = None,
    created_by: str | None = None,
    code: str | None = None,
    commit: bool = True,
) -> PaymentResult:
    """Registra un pago en una CxP con asiento ``POSTED`` y saldo actualizado.

    Espejo de :func:`register_receivable_payment`: debe a la cuenta de CxP y
    haber a Caja/Banco, con validación de saldo y transacción atómica.
    """
    if isinstance(payable, PaymentCreate):
        data = payable
        if data.receivable_id is not None or data.payable_id is None:
            raise InvalidSourceDocumentError(
                "PaymentCreate debe apuntar exactamente a una CxP"
            )
        target_id = data.payable_id
        amount = data.amount
        payment_date = payment_date or data.payment_date
        reference = reference or data.reference
    else:
        target_id = payable
    if amount is None:
        raise InvalidSourceDocumentError("Se requiere el importe del pago")

    value = _money(amount)
    if value <= 0:
        raise InvalidSourceDocumentError("El importe del pago debe ser mayor que cero")
    when = payment_date or date.today()

    balance = db.scalars(
        select(AccountPayable)
        .where(AccountPayable.id == target_id)
        .with_for_update()
    ).first()
    if balance is None:
        raise ResourceNotFoundError(f"Cuenta por pagar {target_id} no encontrada")

    remaining = _money(_money(balance.total_amount) - _money(balance.paid_amount))
    if remaining <= 0:
        raise InvalidSourceDocumentError("La cuenta por pagar ya está liquidada")
    if value > remaining:
        raise InvalidSourceDocumentError(
            f"El pago ({value}) excede el saldo pendiente de la CxP ({remaining})"
        )

    cash_id = _resolve_payment_account(
        db,
        cash_account_id=cash_account_id,
        bank_account_id=bank_account_id,
        payment_account_id=payment_account_id,
    )
    payable_id = _resolve_account_id(db, "payable", payable_account_id)
    entry_code = code or _next_auto_code(db, prefix="ASI-PAG", year=when.year)
    description = f"{_LABEL_PAYABLE_PAYMENT} CxP-{target_id}"

    with _unit_of_work(db, commit=commit):
        entry = _build_posted_entry(
            db,
            code=entry_code,
            entry_date=when,
            description=description,
            reference_document=reference or f"CxP-{target_id}",
            created_by=created_by or "accounting-automation",
            items=[
                JournalItemCreate(
                    account_id=payable_id,
                    debit=value,
                    credit=Decimal("0.00"),
                    description=f"Cancelación parcial CxP-{target_id}",
                ),
                JournalItemCreate(
                    account_id=cash_id,
                    debit=Decimal("0.00"),
                    credit=value,
                    description=f"Salida de caja por CxP-{target_id}",
                ),
            ],
        )
        payment = PaymentRecord(
            payable=balance,
            journal_entry=entry,
            amount=value,
            payment_date=when,
            reference=reference,
        )
        db.add(payment)
        db.add(entry)
        _apply_payment_to_balance(balance, value)
    if commit:
        db.refresh(entry)
        db.refresh(payment)
        db.refresh(balance)
    return PaymentResult(entry, payment, balance)


# --------------------------------------------------------------------------- #
# Reportes financieros — sección 4.6 de la spec / Hito 5 del apéndice
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _AccountTotals:
    """Sumas de débito y crédito de una cuenta dentro del periodo del reporte."""

    account_id: int
    code: str
    name: str
    account_type: AccountType
    debit: Decimal
    credit: Decimal

    @property
    def debit_balance(self) -> Decimal:
        """Saldo natural de una cuenta de debe (activo o gasto)."""
        return _money(self.debit - self.credit)

    @property
    def credit_balance(self) -> Decimal:
        """Saldo natural de una cuenta de haber (pasivo, patrimonio o ingreso)."""
        return _money(self.credit - self.debit)


def _as_account_type(value: Any) -> AccountType | Any:
    """Normaliza el tipo de cuenta leído de PostgreSQL o SQLite."""
    if isinstance(value, AccountType):
        return value
    try:
        return AccountType(value)
    except (TypeError, ValueError):
        return value


def _resolve_report_window(
    db: Session,
    *,
    date_from: date | None,
    date_to: date | None,
    period_id: int | None,
    period_name: str | None,
) -> tuple[date | None, date | None]:
    """Combina el rango de fechas con el periodo contable indicado.

    Si se dan ambos, se usa la intersección. Los periodos cerrados **sí** se
    consultan: el control de periodos aplica a contabilizar, no a reportar.
    """
    if period_id is not None and period_name is not None:
        raise AccountingError("Indique solo uno de period_id o period_name")

    period: AccountingPeriod | None = None
    if period_id is not None:
        period = db.get(AccountingPeriod, period_id)
        if period is None:
            raise ResourceNotFoundError(
                f"Periodo contable {period_id} no encontrado"
            )
    elif period_name is not None:
        period = db.scalar(
            select(AccountingPeriod).where(AccountingPeriod.name == period_name)
        )
        if period is None:
            raise ResourceNotFoundError(
                f"Periodo contable '{period_name}' no encontrado"
            )

    if period is not None:
        date_from = (
            period.start_date
            if date_from is None
            else max(date_from, period.start_date)
        )
        date_to = period.end_date if date_to is None else min(date_to, period.end_date)

    if date_from is not None and date_to is not None and date_from > date_to:
        raise AccountingError(
            f"El rango del reporte es inválido: {date_from} es posterior a {date_to}"
        )
    return date_from, date_to


def _posted_account_totals(
    db: Session,
    *,
    date_from: date | None,
    date_to: date | None,
    period_id: int | None,
    period_name: str | None,
) -> list[_AccountTotals]:
    """Agrega las líneas de asientos ``POSTED`` por cuenta.

    ``DRAFT`` y ``VOID`` quedan fuera por construcción: el filtro se aplica al
    encabezado del asiento antes de cualquier suma. Las cuentas desactivadas
    siguen apareciendo si tienen movimientos históricos dentro del periodo.
    """
    start, end = _resolve_report_window(
        db,
        date_from=date_from,
        date_to=date_to,
        period_id=period_id,
        period_name=period_name,
    )
    stmt = (
        select(
            Account.id,
            Account.code,
            Account.name,
            Account.account_type,
            func.coalesce(func.sum(JournalItem.debit), 0),
            func.coalesce(func.sum(JournalItem.credit), 0),
        )
        .join(JournalItem, JournalItem.account_id == Account.id)
        .join(JournalEntry, JournalEntry.id == JournalItem.journal_entry_id)
        .where(JournalEntry.status == JournalEntryStatus.POSTED)
        .group_by(Account.id, Account.code, Account.name, Account.account_type)
        .order_by(Account.code, Account.id)
    )
    if start is not None:
        stmt = stmt.where(JournalEntry.entry_date >= start)
    if end is not None:
        stmt = stmt.where(JournalEntry.entry_date <= end)

    return [
        _AccountTotals(
            account_id=row[0],
            code=row[1],
            name=row[2],
            account_type=_as_account_type(row[3]),
            debit=_money(row[4]),
            credit=_money(row[5]),
        )
        for row in db.execute(stmt).all()
    ]


def _report_line(row: _AccountTotals, balance: Decimal) -> ReportAccountLine:
    """Construye una línea de balance o estado de resultados."""
    return ReportAccountLine(
        account_id=row.account_id,
        code=row.code,
        name=row.name,
        balance=_money(max(Decimal("0.00"), balance)),
    )


def _sum_balances(lines: Sequence[ReportAccountLine]) -> Decimal:
    """Suma los saldos de las líneas con precisión monetaria."""
    return _money(sum((line.balance for line in lines), Decimal("0.00")))


def get_trial_balance(
    db: Session,
    date_from: date | None = None,
    date_to: date | None = None,
    *,
    period_id: int | None = None,
    period_name: str | None = None,
) -> TrialBalanceResponse:
    """Balance de comprobación de los asientos ``POSTED`` del periodo.

    Devuelve débitos, créditos y saldo neto (``débito - crédito``) por cuenta.
    El saldo puede ser negativo en cuentas de naturaleza acreedora; los totales
    son las sumas brutas de ambos lados y por eso siempre son no negativos.
    """
    rows = _posted_account_totals(
        db,
        date_from=date_from,
        date_to=date_to,
        period_id=period_id,
        period_name=period_name,
    )
    lines = [
        TrialBalanceLine(
            account_id=row.account_id,
            code=row.code,
            name=row.name,
            account_type=row.account_type,
            debit=row.debit,
            credit=row.credit,
            balance=row.debit_balance,
        )
        for row in rows
    ]
    return TrialBalanceResponse(
        lines=lines,
        total_debit=_money(sum((row.debit for row in rows), Decimal("0.00"))),
        total_credit=_money(sum((row.credit for row in rows), Decimal("0.00"))),
    )


def get_balance_sheet(
    db: Session,
    date_from: date | None = None,
    date_to: date | None = None,
    *,
    period_id: int | None = None,
    period_name: str | None = None,
) -> BalanceSheetResponse:
    """Balance General con activos, pasivos y patrimonio del periodo.

    Cada cuenta se reporta con su saldo natural: débito menos crédito para los
    activos, crédito menos débito para pasivos y patrimonio. ``difference`` es
    ``Activo - (Pasivo + Patrimonio)``: permite verificar la ecuación contable
    sin ocultar el resultado del periodo que aún no se ha cerrado a patrimonio.
    Los saldos invertidos se reportan en cero porque el contrato de respuesta
    exige totales no negativos.
    """
    rows = _posted_account_totals(
        db,
        date_from=date_from,
        date_to=date_to,
        period_id=period_id,
        period_name=period_name,
    )
    assets: list[ReportAccountLine] = []
    liabilities: list[ReportAccountLine] = []
    equity: list[ReportAccountLine] = []
    for row in rows:
        if row.account_type is AccountType.ASSET:
            target = assets
            balance = row.debit_balance
        elif row.account_type is AccountType.LIABILITY:
            target = liabilities
            balance = row.credit_balance
        elif row.account_type is AccountType.EQUITY:
            target = equity
            balance = row.credit_balance
        else:
            continue
        if balance != 0:
            target.append(_report_line(row, balance))

    total_assets = _sum_balances(assets)
    total_liabilities = _sum_balances(liabilities)
    total_equity = _sum_balances(equity)
    total_liabilities_and_equity = _money(total_liabilities + total_equity)
    return BalanceSheetResponse(
        assets=assets,
        liabilities=liabilities,
        equity=equity,
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        total_equity=total_equity,
        total_liabilities_and_equity=total_liabilities_and_equity,
        difference=_money(total_assets - total_liabilities_and_equity),
    )


def get_income_statement(
    db: Session,
    date_from: date | None = None,
    date_to: date | None = None,
    *,
    period_id: int | None = None,
    period_name: str | None = None,
) -> IncomeStatementResponse:
    """Estado de Resultados: ingresos, gastos y utilidad o pérdida del periodo.

    Los ingresos se leen por su saldo natural acreedor y los gastos por su
    saldo natural deudor. ``net_income`` puede ser negativo cuando el periodo
    cierra con pérdida. Solo se consideran asientos ``POSTED``.
    """
    rows = _posted_account_totals(
        db,
        date_from=date_from,
        date_to=date_to,
        period_id=period_id,
        period_name=period_name,
    )
    revenues: list[ReportAccountLine] = []
    expenses: list[ReportAccountLine] = []
    for row in rows:
        if row.account_type is AccountType.REVENUE:
            balance = row.credit_balance
            if balance != 0:
                revenues.append(_report_line(row, balance))
        elif row.account_type is AccountType.EXPENSE:
            balance = row.debit_balance
            if balance != 0:
                expenses.append(_report_line(row, balance))

    total_revenue = _sum_balances(revenues)
    total_expenses = _sum_balances(expenses)
    return IncomeStatementResponse(
        revenues=revenues,
        expenses=expenses,
        total_revenue=total_revenue,
        total_expenses=total_expenses,
        net_income=_money(total_revenue - total_expenses),
    )


# --------------------------------------------------------------------------- #
# Integridad a nivel ORM (defensa en profundidad)
# --------------------------------------------------------------------------- #


def _parent_entry_status(connection: Any, journal_entry_id: int) -> Any:
    """Lee el estado del asiento padre desde la conexión en curso."""
    row = connection.execute(
        select(JournalEntry.status).where(JournalEntry.id == journal_entry_id)
    ).first()
    return _as_status(row[0]) if row is not None else None


def _previous_status(target: JournalEntry) -> Any:
    """Estado persisted del asiento antes del ``flush`` actual."""
    history = inspect(target).attrs.status.history
    if history.deleted:
        return _as_status(history.deleted[0])
    return _as_status(target.status)


@event.listens_for(JournalEntry, "before_update")
def _guard_journal_entry_update(mapper: Any, connection: Any, target: JournalEntry) -> None:  # noqa: ARG001
    """Solo un borrador puede cambiar: a ``POSTED``, a ``VOID`` o en sus datos."""
    previous = _previous_status(target)
    if previous is JournalEntryStatus.POSTED:
        raise ImmutableJournalEntryError(
            "Un asiento publicado no puede modificarse; registre una reversión"
        )
    if previous is JournalEntryStatus.VOID:
        raise ImmutableJournalEntryError(
            "Un asiento anulado no puede modificarse"
        )
    current = _as_status(target.status)
    if current not in _DRAFT_TRANSITIONS | {JournalEntryStatus.DRAFT}:
        raise InvalidJournalEntryStateError(
            f"Transición de estado no permitida: {previous} -> {current}"
        )


@event.listens_for(JournalEntry, "before_delete")
def _guard_journal_entry_delete(mapper: Any, connection: Any, target: JournalEntry) -> None:  # noqa: ARG001
    """Los asientos publicados no se eliminan físicamente."""
    if _as_status(target.status) is JournalEntryStatus.POSTED:
        raise ImmutableJournalEntryError(
            "Un asiento publicado no puede eliminarse; registre una reversión"
        )


@event.listens_for(JournalItem, "before_update")
def _guard_journal_item_update(mapper: Any, connection: Any, target: JournalItem) -> None:  # noqa: ARG001
    """Las líneas de un asiento publicado son inmutables."""
    if _parent_entry_status(connection, target.journal_entry_id) is JournalEntryStatus.POSTED:
        raise ImmutableJournalEntryError(
            "Las líneas de un asiento publicado no pueden modificarse"
        )


@event.listens_for(JournalItem, "before_delete")
def _guard_journal_item_delete(mapper: Any, connection: Any, target: JournalItem) -> None:  # noqa: ARG001
    """Las líneas de un asiento publicado no se eliminan."""
    if _parent_entry_status(connection, target.journal_entry_id) is JournalEntryStatus.POSTED:
        raise ImmutableJournalEntryError(
            "Las líneas de un asiento publicado no pueden eliminarse"
        )


@event.listens_for(Account, "before_delete")
def _guard_account_delete(mapper: Any, connection: Any, target: Account) -> None:  # noqa: ARG001
    """Espejo de la regla 8 para borrados que no pasen por el servicio."""
    children = connection.execute(
        select(Account.id).where(Account.parent_id == target.id).limit(1)
    ).first()
    if children is not None:
        raise AccountInUseError(
            "La cuenta tiene subcuentas; desactívela en lugar de eliminarla"
        )
    items = connection.execute(
        select(JournalItem.id).where(JournalItem.account_id == target.id).limit(1)
    ).first()
    if items is not None:
        raise AccountInUseError(
            "La cuenta tiene movimientos contables; desactívela en lugar de "
            "eliminarla"
        )
