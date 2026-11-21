"""Esquemas Pydantic v2 del módulo de Finanzas y Contabilidad.

Derivados de ``specs/accounting_spec.md`` (secciones 2 a 4) y de los modelos
ORM de ``src.modules.accounting.models``. Definen contratos de entrada
(``Create``), actualización parcial (``Update``), salida (``Response``), el
resultado de contabilizar un asiento y los tipos de los reportes financieros.

Principios transversales:

* **Sin asignación masiva**: todas las clases declaran
  ``ConfigDict(extra="forbid")``. Los campos controlados por el servicio
  (``status``, ``posted_at``, ``created_at``, ``created_by`` en los comprobantes
  generados automáticamente) no forman parte de los esquemas de entrada.
* **Dinero estrictamente decimal**: todos los importes, saldos y totales usan
  el alias :data:`StrictDecimal`, que rechaza ``float`` y admite ``Decimal`` o
  cadenas, con ``max_digits=14`` y ``decimal_places=2`` para coincidir con
  ``Numeric(14, 2)``.
* **Códigos validados**: ``Account.code`` y ``JournalEntry.code`` usan el mismo
  patrón (alfanumérico en mayúsculas con ``.``, ``-`` o ``_`` como separadores)
  y longitud máxima de 30 caracteres, como la columna ``String(30)``.
* **Respuestas desde el ORM**: los esquemas ``Response`` activan
  ``ConfigDict(from_attributes=True)`` para validar directamente entidades
  SQLAlchemy.
* **Validaciones espejo de la BD**: una línea no puede tener débito y crédito
  positivos a la vez; un pago tiene exactamente un destino (CxC o CxP) y
  ``paid_amount <= total_amount`` en cartera. La partida doble exacta, las
  cuentas activas y el periodo abierto se validan en la capa de servicio.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from src.modules.accounting.models import (
    AccountBalanceStatus,
    AccountType,
    JournalEntryStatus,
)

__all__ = [
    "AccountBalanceStatus",
    "AccountCreate",
    "AccountPayableCreate",
    "AccountPayableResponse",
    "AccountReceivableCreate",
    "AccountReceivableResponse",
    "AccountResponse",
    "AccountType",
    "AccountUpdate",
    "BalanceSheetResponse",
    "IncomeStatementResponse",
    "JournalEntryCreate",
    "JournalEntryPostResponse",
    "JournalEntryResponse",
    "JournalEntryStatus",
    "JournalItemCreate",
    "JournalItemResponse",
    "PaymentCreate",
    "PaymentRecordRequest",
    "PaymentRecordResponse",
    "ReportAccountLine",
    "StrictDecimal",
    "TrialBalanceLine",
    "TrialBalanceResponse",
]

#: Patrón de códigos contables: ``110505``, ``4135`` o ``ASI-2026-0001``.
_CODE_PATTERN = r"^[A-Z0-9][A-Z0-9._-]*$"

#: Descripción reutilizable de los importes ``Numeric(14, 2)``.
_MONEY_DESCRIPTION = "Importe decimal con hasta 14 enteros y 2 decimales."


def _reject_float(value: Any) -> Any:
    """Impide que un ``float`` se convierta silenciosamente en ``Decimal``."""
    if isinstance(value, float):
        raise ValueError(
            "Los importes deben enviarse como Decimal o cadena, nunca como float."
        )
    return value


#: ``Decimal`` estricto: acepta ``Decimal``, ``int`` y cadenas, pero no ``float``.
StrictDecimal = Annotated[Decimal, BeforeValidator(_reject_float)]


class AccountingSchema(BaseModel):
    """Base de los esquemas de contabilidad con rechazo de campos desconocidos."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AccountingResponseSchema(AccountingSchema):
    """Base de las respuestas construidas desde entidades SQLAlchemy."""

    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, from_attributes=True
    )


# --------------------------------------------------------------------------- #
# Plan de cuentas — /api/v1/accounting/accounts
# --------------------------------------------------------------------------- #


class AccountCreate(AccountingSchema):
    """Datos para registrar una cuenta en el Plan Único de Cuentas."""

    code: str = Field(
        min_length=1,
        max_length=30,
        pattern=_CODE_PATTERN,
        description="Código único de la cuenta (PUC).",
        examples=["110505", "4135"],
    )
    name: str = Field(
        min_length=1,
        max_length=200,
        description="Nombre de la cuenta.",
        examples=["Caja General"],
    )
    account_type: AccountType = Field(
        description="Clasificación de la cuenta dentro del PUC.",
        examples=[AccountType.ASSET],
    )
    parent_id: int | None = Field(
        default=None,
        gt=0,
        description="Cuenta madre, si la cuenta es jerárquica.",
    )
    is_active: bool = Field(
        default=True,
        description="Indica si la cuenta admite nuevos movimientos.",
    )


class AccountUpdate(AccountingSchema):
    """Actualización parcial de una cuenta (PATCH).

    ``parent_id`` es el único campo que puede limpiarse con ``null`` para
    convertir una subcuenta en cuenta raíz.
    """

    code: str | None = Field(
        default=None, min_length=1, max_length=30, pattern=_CODE_PATTERN
    )
    name: str | None = Field(default=None, min_length=1, max_length=200)
    account_type: AccountType | None = None
    parent_id: int | None = Field(default=None, gt=0)
    is_active: bool | None = None

    @model_validator(mode="after")
    def _validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Debe enviar al menos un campo para actualizar")

        nullable = {"parent_id"}
        for field in self.model_fields_set - nullable:
            if getattr(self, field) is None:
                raise ValueError(f"El campo '{field}' no puede ser nulo")
        return self


class AccountResponse(AccountingResponseSchema):
    """Representación de salida de una cuenta contable."""

    id: int
    code: str
    name: str
    account_type: AccountType
    parent_id: int | None
    is_active: bool
    created_at: datetime


# --------------------------------------------------------------------------- #
# Asientos contables — /api/v1/accounting/entries
# --------------------------------------------------------------------------- #


class JournalItemCreate(AccountingSchema):
    """Línea de partida doble; débito y crédito no pueden ser positivos a la vez.

    Se permite que ambos sean cero para no endurecer el contrato de la spec:
    la validación de equilibrio y de líneas útiles se reserva al servicio que
    publica el comprobante.
    """

    account_id: int = Field(gt=0, description="Cuenta afectada por el movimiento.")
    debit: StrictDecimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=14,
        decimal_places=2,
        description=_MONEY_DESCRIPTION,
        examples=["500.00"],
    )
    credit: StrictDecimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=14,
        decimal_places=2,
        description=_MONEY_DESCRIPTION,
        examples=["0.00"],
    )
    description: str | None = Field(
        default=None, description="Glosa opcional de la línea."
    )

    @model_validator(mode="after")
    def _validate_single_side(self) -> Self:
        if self.debit > 0 and self.credit > 0:
            raise ValueError(
                "Una línea no puede tener débito y crédito positivos simultáneamente"
            )
        return self


class JournalItemResponse(AccountingResponseSchema):
    """Representación de salida de una línea de asiento."""

    id: int
    journal_entry_id: int
    account_id: int
    debit: StrictDecimal
    credit: StrictDecimal
    description: str | None


class JournalEntryCreate(AccountingSchema):
    """Comprobante en borrador con al menos dos líneas de partida doble.

    El servicio asigna ``status = DRAFT`` y, en su caso, genera el ``code``
    secuencial; por eso ninguno de esos campos acepta valores del cliente.
    """

    code: str = Field(
        min_length=1,
        max_length=30,
        pattern=_CODE_PATTERN,
        description="Código único del comprobante.",
        examples=["ASI-2026-0001"],
    )
    entry_date: date = Field(
        default_factory=date.today,
        description="Fecha contable del asiento.",
    )
    description: str = Field(
        min_length=1,
        description="Concepto o glosa general de la transacción.",
        examples=["Pago de nómina de noviembre"],
    )
    reference_document: str | None = Field(
        default=None,
        max_length=100,
        description="Documento de soporte, por ejemplo FAC-2026-0001.",
    )
    created_by: str | None = Field(
        default=None,
        max_length=150,
        description="Identificador de quien registra el borrador.",
    )
    items: list[JournalItemCreate] = Field(
        min_length=2,
        description="Líneas del asiento; mínimo dos según la regla de negocio 6.",
    )


class JournalEntryPostResponse(AccountingResponseSchema):
    """Resultado de contabilizar un asiento (``POSTED``)."""

    id: int
    code: str
    status: JournalEntryStatus
    posted_at: datetime
    total_debit: StrictDecimal
    total_credit: StrictDecimal


class JournalEntryResponse(AccountingResponseSchema):
    """Detalle de un asiento con sus líneas."""

    id: int
    code: str
    entry_date: date
    description: str
    reference_document: str | None
    status: JournalEntryStatus
    created_by: str | None
    posted_at: datetime | None
    created_at: datetime
    items: list[JournalItemResponse]


# --------------------------------------------------------------------------- #
# Cartera — /api/v1/accounting/receivables y /payables
# --------------------------------------------------------------------------- #


class AccountReceivableCreate(AccountingSchema):
    """Cuenta por cobrar derivada de una factura de ventas.

    El servicio fija ``status = PENDING`` y calcula los cambios de estado;
    ``paid_amount`` arranca en cero salvo carga controlada desde integración.
    """

    customer_id: int = Field(gt=0, description="Cliente deudor.")
    invoice_id: int | None = Field(
        default=None, gt=0, description="Factura de ventas de origen."
    )
    journal_entry_id: int | None = Field(
        default=None, gt=0, description="Asiento que originó la cartera."
    )
    total_amount: StrictDecimal = Field(
        ge=0,
        max_digits=14,
        decimal_places=2,
        description=_MONEY_DESCRIPTION,
        examples=["1000.00"],
    )
    paid_amount: StrictDecimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=14,
        decimal_places=2,
        description=_MONEY_DESCRIPTION,
        examples=["0.00"],
    )
    due_date: date = Field(description="Fecha límite de pago.")

    @model_validator(mode="after")
    def _validate_amounts(self) -> Self:
        if self.paid_amount > self.total_amount:
            raise ValueError("paid_amount no puede superar total_amount")
        return self


class AccountPayableCreate(AccountingSchema):
    """Cuenta por pagar derivada de una factura o recepción de compras."""

    supplier_id: int = Field(gt=0, description="Proveedor acreedor.")
    bill_reference: str = Field(
        min_length=1,
        max_length=100,
        description="Referencia de la factura o documento de compra.",
        examples=["FAC-2026-0001"],
    )
    journal_entry_id: int | None = Field(
        default=None, gt=0, description="Asiento que originó la obligación."
    )
    total_amount: StrictDecimal = Field(
        ge=0,
        max_digits=14,
        decimal_places=2,
        description=_MONEY_DESCRIPTION,
        examples=["800.00"],
    )
    paid_amount: StrictDecimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=14,
        decimal_places=2,
        description=_MONEY_DESCRIPTION,
        examples=["0.00"],
    )
    due_date: date = Field(description="Fecha límite de pago.")

    @model_validator(mode="after")
    def _validate_amounts(self) -> Self:
        if self.paid_amount > self.total_amount:
            raise ValueError("paid_amount no puede superar total_amount")
        return self


class AccountReceivableResponse(AccountingResponseSchema):
    """Representación de salida de una cuenta por cobrar."""

    id: int
    customer_id: int
    invoice_id: int | None
    journal_entry_id: int | None
    total_amount: StrictDecimal
    paid_amount: StrictDecimal
    due_date: date
    status: AccountBalanceStatus
    created_at: datetime


class AccountPayableResponse(AccountingResponseSchema):
    """Representación de salida de una cuenta por pagar."""

    id: int
    supplier_id: int
    bill_reference: str
    journal_entry_id: int | None
    total_amount: StrictDecimal
    paid_amount: StrictDecimal
    due_date: date
    status: AccountBalanceStatus
    created_at: datetime


# --------------------------------------------------------------------------- #
# Pagos y cobros — /api/v1/accounting/payments
# --------------------------------------------------------------------------- #


class PaymentCreate(AccountingSchema):
    """Abono o pago aplicado a exactamente una CxC o una CxP.

    El servicio valida que ``amount`` no exceda el saldo pendiente y actualiza
    ``paid_amount`` y ``status`` dentro de la misma transacción.
    """

    receivable_id: int | None = Field(
        default=None, gt=0, description="Cuenta por cobrar a abonar."
    )
    payable_id: int | None = Field(
        default=None, gt=0, description="Cuenta por pagar a liquidar."
    )
    journal_entry_id: int | None = Field(
        default=None, gt=0, description="Asiento contable de soporte del pago."
    )
    amount: StrictDecimal = Field(
        gt=0,
        max_digits=14,
        decimal_places=2,
        description="Monto del abono o pago, estrictamente positivo.",
        examples=["400.00"],
    )
    payment_date: date = Field(
        default_factory=date.today, description="Fecha en que se registró el pago."
    )
    reference: str | None = Field(
        default=None,
        max_length=100,
        description="Comprobante o referencia bancaria.",
    )

    @model_validator(mode="after")
    def _validate_target(self) -> Self:
        if (self.receivable_id is None) == (self.payable_id is None):
            raise ValueError(
                "Debe indicar exactamente uno de receivable_id o payable_id"
            )
        return self


class PaymentRecordRequest(AccountingSchema):
    """Cuerpo para abonar una CxC o CxP cuyo id viaja en la URL."""

    amount: StrictDecimal = Field(
        gt=0,
        max_digits=14,
        decimal_places=2,
        description="Monto del abono o pago, estrictamente positivo.",
        examples=["400.00"],
    )
    payment_date: date = Field(
        default_factory=date.today, description="Fecha en que se registró el pago."
    )
    reference: str | None = Field(
        default=None,
        max_length=100,
        description="Comprobante o referencia bancaria.",
    )


class PaymentRecordResponse(AccountingResponseSchema):
    """Abono o pago ya registrado, con trazabilidad del asiento generado."""

    id: int
    receivable_id: int | None
    payable_id: int | None
    journal_entry_id: int | None
    amount: StrictDecimal
    payment_date: date
    reference: str | None
    created_at: datetime


# --------------------------------------------------------------------------- #
# Reportes financieros — /api/v1/accounting/reports
# --------------------------------------------------------------------------- #


class ReportAccountLine(AccountingResponseSchema):
    """Saldo de una cuenta en cualquier reporte financiero."""

    account_id: int
    code: str
    name: str
    balance: StrictDecimal = Field(
        default=Decimal("0.00"),
        max_digits=14,
        decimal_places=2,
        description=_MONEY_DESCRIPTION,
    )


class TrialBalanceLine(ReportAccountLine):
    """Fila del balance de comprobación (sumas y saldos por cuenta)."""

    account_type: AccountType
    debit: StrictDecimal = Field(
        default=Decimal("0.00"), ge=0, max_digits=14, decimal_places=2
    )
    credit: StrictDecimal = Field(
        default=Decimal("0.00"), ge=0, max_digits=14, decimal_places=2
    )


class TrialBalanceResponse(AccountingResponseSchema):
    """Balance de comprobación con totales de débito y crédito."""

    lines: list[TrialBalanceLine] = Field(default_factory=list)
    total_debit: StrictDecimal = Field(
        default=Decimal("0.00"), ge=0, max_digits=14, decimal_places=2
    )
    total_credit: StrictDecimal = Field(
        default=Decimal("0.00"), ge=0, max_digits=14, decimal_places=2
    )


class BalanceSheetResponse(AccountingResponseSchema):
    """Balance General: activos frente a pasivos y patrimonio."""

    assets: list[ReportAccountLine] = Field(default_factory=list)
    liabilities: list[ReportAccountLine] = Field(default_factory=list)
    equity: list[ReportAccountLine] = Field(default_factory=list)
    total_assets: StrictDecimal = Field(
        default=Decimal("0.00"), ge=0, max_digits=14, decimal_places=2
    )
    total_liabilities: StrictDecimal = Field(
        default=Decimal("0.00"), ge=0, max_digits=14, decimal_places=2
    )
    total_equity: StrictDecimal = Field(
        default=Decimal("0.00"), ge=0, max_digits=14, decimal_places=2
    )
    total_liabilities_and_equity: StrictDecimal = Field(
        default=Decimal("0.00"), ge=0, max_digits=14, decimal_places=2
    )
    difference: StrictDecimal = Field(
        default=Decimal("0.00"), max_digits=14, decimal_places=2
    )


class IncomeStatementResponse(AccountingResponseSchema):
    """Estado de Resultados: ingresos, gastos y resultado neto."""

    revenues: list[ReportAccountLine] = Field(default_factory=list)
    expenses: list[ReportAccountLine] = Field(default_factory=list)
    total_revenue: StrictDecimal = Field(
        default=Decimal("0.00"), ge=0, max_digits=14, decimal_places=2
    )
    total_expenses: StrictDecimal = Field(
        default=Decimal("0.00"), ge=0, max_digits=14, decimal_places=2
    )
    net_income: StrictDecimal = Field(
        default=Decimal("0.00"), max_digits=14, decimal_places=2
    )
