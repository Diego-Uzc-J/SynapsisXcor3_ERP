/**
 * Contratos TypeScript del módulo de Finanzas y Contabilidad.
 *
 * Derivados de `backend/src/modules/accounting/schemas.py`, de
 * `backend/src/modules/accounting/router.py` y de `specs/accounting_spec.md`.
 * Las rutas HTTP se construyen en `./api.ts` bajo `/api/v1/accounting`.
 *
 * Pydantic serializa `Decimal` como cadena en JSON, por lo que todos los
 * importes, saldos y totales se reciben como `string` para no perder precisión
 * monetaria. Al enviar datos se acepta `number | string`, aunque el backend
 * rechaza `float`; las vistas deben construir cadenas con dos decimales.
 * Las fechas (`date`) y marcas de tiempo (`datetime`) llegan como strings ISO.
 */

// --------------------------------------------------------------------------- //
// Enumeraciones del dominio
// --------------------------------------------------------------------------- //

/** Clasificación de una cuenta dentro del Plan Único de Cuentas (PUC). */
export const ACCOUNT_TYPES = [
  "ASSET",
  "LIABILITY",
  "EQUITY",
  "REVENUE",
  "EXPENSE",
] as const;

export type AccountType = (typeof ACCOUNT_TYPES)[number];

/** Ciclo de vida de un comprobante de diario. */
export const JOURNAL_ENTRY_STATUSES = ["DRAFT", "POSTED", "VOID"] as const;

export type JournalEntryStatus = (typeof JOURNAL_ENTRY_STATUSES)[number];

/** Estados compartidos por la cartera por cobrar y por pagar. */
export const ACCOUNT_BALANCE_STATUSES = [
  "PENDING",
  "PARTIALLY_PAID",
  "PAID",
  "OVERDUE",
] as const;

export type AccountBalanceStatus = (typeof ACCOUNT_BALANCE_STATUSES)[number];

// --------------------------------------------------------------------------- //
// Plan de cuentas
// --------------------------------------------------------------------------- //

export interface Account {
  id: number;
  code: string;
  name: string;
  account_type: AccountType;
  /** Cuenta madre; `null` cuando es una cuenta raíz. */
  parent_id: number | null;
  is_active: boolean;
  created_at: string;
}

export interface AccountCreate {
  /** Hasta 30 caracteres: mayúsculas, dígitos, `.`, `-` o `_`. */
  code: string;
  name: string;
  account_type: AccountType;
  parent_id?: number | null;
  is_active?: boolean;
}

/**
 * Actualización parcial (PATCH).
 *
 * Solo `parent_id` admite `null` para convertir una subcuenta en raíz; el
 * backend rechaza explícitamente `null` en el resto de los campos y exige al
 * menos uno.
 */
export interface AccountUpdate {
  code?: string;
  name?: string;
  account_type?: AccountType;
  parent_id?: number | null;
  is_active?: boolean;
}

// --------------------------------------------------------------------------- //
// Libro diario
// --------------------------------------------------------------------------- //

export interface JournalItem {
  id: number;
  journal_entry_id: number;
  account_id: number;
  /** Decimal serializado como string por Pydantic. */
  debit: string;
  /** Decimal serializado como string por Pydantic. */
  credit: string;
  description: string | null;
}

/**
 * Línea de partida doble. Débito y crédito no pueden ser positivos a la vez;
 * omisos valen `"0.00"`. La partida doble se valida al publicar el asiento.
 */
export interface JournalItemCreate {
  account_id: number;
  debit?: number | string;
  credit?: number | string;
  description?: string | null;
}

export interface JournalEntry {
  id: number;
  code: string;
  entry_date: string;
  description: string;
  reference_document: string | null;
  status: JournalEntryStatus;
  created_by: string | null;
  posted_at: string | null;
  created_at: string;
  items: JournalItem[];
}

/** Crea siempre un borrador (`DRAFT`); el `code` es obligatorio y único. */
export interface JournalEntryCreate {
  code: string;
  entry_date?: string;
  description: string;
  reference_document?: string | null;
  created_by?: string | null;
  /** Mínimo dos líneas. */
  items: JournalItemCreate[];
}

/** Resultado de `POST /journal-entries/{id}/post`. */
export interface JournalEntryPostResponse {
  id: number;
  code: string;
  status: JournalEntryStatus;
  posted_at: string;
  total_debit: string;
  total_credit: string;
}

// --------------------------------------------------------------------------- //
// Cartera: cuentas por cobrar y por pagar
// --------------------------------------------------------------------------- //

export interface AccountReceivable {
  id: number;
  customer_id: number;
  invoice_id: number | null;
  journal_entry_id: number | null;
  total_amount: string;
  paid_amount: string;
  due_date: string;
  status: AccountBalanceStatus;
  created_at: string;
}

export interface AccountReceivableCreate {
  customer_id: number;
  invoice_id?: number | null;
  journal_entry_id?: number | null;
  total_amount: number | string;
  paid_amount?: number | string;
  due_date: string;
}

export interface AccountPayable {
  id: number;
  supplier_id: number;
  bill_reference: string;
  journal_entry_id: number | null;
  total_amount: string;
  paid_amount: string;
  due_date: string;
  status: AccountBalanceStatus;
  created_at: string;
}

export interface AccountPayableCreate {
  supplier_id: number;
  bill_reference: string;
  journal_entry_id?: number | null;
  total_amount: number | string;
  paid_amount?: number | string;
  due_date: string;
}

// --------------------------------------------------------------------------- //
// Pagos y cobros
// --------------------------------------------------------------------------- //

/** Abono ya registrado, con trazabilidad del asiento que lo soporta. */
export interface PaymentRecord {
  id: number;
  receivable_id: number | null;
  payable_id: number | null;
  journal_entry_id: number | null;
  /** Decimal serializado como string por Pydantic. */
  amount: string;
  payment_date: string;
  reference: string | null;
  created_at: string;
}

/**
 * Pago genérico de `POST /payments`: exactamente uno de `receivable_id` o
 * `payable_id` debe indicarse.
 */
export interface PaymentCreate {
  receivable_id?: number | null;
  payable_id?: number | null;
  journal_entry_id?: number | null;
  amount: number | string;
  payment_date?: string;
  reference?: string | null;
}

/** Cuerpo para abonar una CxC o CxP cuyo id viaja en la URL. */
export interface PaymentRecordRequest {
  amount: number | string;
  payment_date?: string;
  reference?: string | null;
}

// --------------------------------------------------------------------------- //
// Reportes financieros
// --------------------------------------------------------------------------- //

export interface ReportAccountLine {
  account_id: number;
  code: string;
  name: string;
  balance: string;
}

/** Fila del balance de comprobación (sumas y saldos por cuenta). */
export interface TrialBalanceLine extends ReportAccountLine {
  account_type: AccountType;
  debit: string;
  credit: string;
}

export interface TrialBalanceResponse {
  lines: TrialBalanceLine[];
  total_debit: string;
  total_credit: string;
}

/** Balance General: activos frente a pasivos y patrimonio. */
export interface BalanceSheetResponse {
  assets: ReportAccountLine[];
  liabilities: ReportAccountLine[];
  equity: ReportAccountLine[];
  total_assets: string;
  total_liabilities: string;
  total_equity: string;
  total_liabilities_and_equity: string;
  /** Diferencia de la ecuación contable; cero si el balance cuadra. */
  difference: string;
}

/** Estado de Resultados: ingresos, gastos y resultado neto. */
export interface IncomeStatementResponse {
  revenues: ReportAccountLine[];
  expenses: ReportAccountLine[];
  total_revenue: string;
  total_expenses: string;
  net_income: string;
}

// --------------------------------------------------------------------------- //
// Filtros de consulta
// --------------------------------------------------------------------------- //

export interface PaginationFilters {
  skip?: number;
  limit?: number;
}

export interface AccountFilters extends PaginationFilters {
  code?: string;
  name?: string;
  account_type?: AccountType;
  is_active?: boolean;
  parent_id?: number;
}

export interface JournalEntryFilters extends PaginationFilters {
  code?: string;
  /** Se envía como parámetro `status` (alias del backend). */
  status?: JournalEntryStatus;
  date_from?: string;
  date_to?: string;
}

export interface ReceivableFilters extends PaginationFilters {
  customer_id?: number;
  /** Alias de `customer_id` en el backend. */
  third_party_id?: number;
  /** Se envía como parámetro `status` (alias del backend). */
  status?: AccountBalanceStatus;
  due_before?: string;
  due_after?: string;
}

export interface PayableFilters extends PaginationFilters {
  supplier_id?: number;
  /** Alias de `supplier_id` en el backend. */
  third_party_id?: number;
  /** Se envía como parámetro `status` (alias del backend). */
  status?: AccountBalanceStatus;
  due_before?: string;
  due_after?: string;
}

export interface PaymentFilters extends PaginationFilters {
  receivable_id?: number;
  payable_id?: number;
  date_from?: string;
  date_to?: string;
  reference?: string;
}

/** Ventana compartida por los tres reportes financieros. */
export interface ReportFilters {
  date_from?: string;
  date_to?: string;
  period_id?: number;
  period_name?: string;
}
