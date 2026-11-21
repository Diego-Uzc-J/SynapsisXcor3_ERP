/**
 * Cliente HTTP del módulo de Finanzas y Contabilidad.
 *
 * Todas las peticiones usan la instancia compartida del ERP (`apiRequest`),
 * que añade el Bearer token, traduce los errores de FastAPI y renueva la sesión
 * ante un 401. Las rutas se construyen bajo `/api/v1/accounting`: la URL base
 * del backend la aporta `api/config.ts`.
 */
import { apiRequest } from "../../api/client";
import { buildQuery } from "../../api/config";
import type {
  Account,
  AccountCreate,
  AccountFilters,
  AccountPayable,
  AccountReceivable,
  AccountUpdate,
  BalanceSheetResponse,
  IncomeStatementResponse,
  JournalEntry,
  JournalEntryCreate,
  JournalEntryFilters,
  JournalEntryPostResponse,
  PayableFilters,
  PaymentCreate,
  PaymentFilters,
  PaymentRecord,
  PaymentRecordRequest,
  ReceivableFilters,
  ReportFilters,
  TrialBalanceResponse,
} from "./types";

export { ApiError as AccountingApiError } from "../../api/client";

const ACCOUNTING_PATH = "/api/v1/accounting";

// --------------------------------------------------------------------------- //
// Plan de cuentas — /api/v1/accounting/accounts
// --------------------------------------------------------------------------- //

export function listAccounts(
  filters: AccountFilters = {},
): Promise<Account[]> {
  return apiRequest<Account[]>(
    `${ACCOUNTING_PATH}/accounts${buildQuery(filters)}`,
  );
}

export function getAccount(accountId: number): Promise<Account> {
  return apiRequest<Account>(`${ACCOUNTING_PATH}/accounts/${accountId}`);
}

export function createAccount(payload: AccountCreate): Promise<Account> {
  return apiRequest<Account>(`${ACCOUNTING_PATH}/accounts`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateAccount(
  accountId: number,
  payload: AccountUpdate,
): Promise<Account> {
  return apiRequest<Account>(`${ACCOUNTING_PATH}/accounts/${accountId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

/** Borrado lógico (204): preserva el historial y bloquea nuevos movimientos. */
export function deactivateAccount(accountId: number): Promise<void> {
  return apiRequest<void>(`${ACCOUNTING_PATH}/accounts/${accountId}`, {
    method: "DELETE",
  });
}

// --------------------------------------------------------------------------- //
// Libro diario — /api/v1/accounting/journal-entries
// --------------------------------------------------------------------------- //

export function listJournalEntries(
  filters: JournalEntryFilters = {},
): Promise<JournalEntry[]> {
  return apiRequest<JournalEntry[]>(
    `${ACCOUNTING_PATH}/journal-entries${buildQuery(filters)}`,
  );
}

export function getJournalEntry(entryId: number): Promise<JournalEntry> {
  return apiRequest<JournalEntry>(
    `${ACCOUNTING_PATH}/journal-entries/${entryId}`,
  );
}

/** Crea un borrador con sus líneas de partida doble. */
export function createJournalEntry(
  payload: JournalEntryCreate,
): Promise<JournalEntry> {
  return apiRequest<JournalEntry>(`${ACCOUNTING_PATH}/journal-entries`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** Publica el borrador: valida equilibrio, cuentas activas y periodo abierto. */
export function postJournalEntry(
  entryId: number,
): Promise<JournalEntryPostResponse> {
  return apiRequest<JournalEntryPostResponse>(
    `${ACCOUNTING_PATH}/journal-entries/${entryId}/post`,
    { method: "POST" },
  );
}

/** Anula un `DRAFT`; los asientos `POSTED` requieren reversión. */
export function voidJournalEntry(entryId: number): Promise<JournalEntry> {
  return apiRequest<JournalEntry>(
    `${ACCOUNTING_PATH}/journal-entries/${entryId}/void`,
    { method: "POST" },
  );
}

/** Crea y publica un comprobante que invierte un asiento `POSTED`. */
export function reverseJournalEntry(entryId: number): Promise<JournalEntry> {
  return apiRequest<JournalEntry>(
    `${ACCOUNTING_PATH}/journal-entries/${entryId}/reverse`,
    { method: "POST" },
  );
}

// --------------------------------------------------------------------------- //
// Cartera — /api/v1/accounting/receivables y /payables
// --------------------------------------------------------------------------- //

export function listReceivables(
  filters: ReceivableFilters = {},
): Promise<AccountReceivable[]> {
  return apiRequest<AccountReceivable[]>(
    `${ACCOUNTING_PATH}/receivables${buildQuery(filters)}`,
  );
}

export function getReceivable(
  receivableId: number,
): Promise<AccountReceivable> {
  return apiRequest<AccountReceivable>(
    `${ACCOUNTING_PATH}/receivables/${receivableId}`,
  );
}

export function listPayables(
  filters: PayableFilters = {},
): Promise<AccountPayable[]> {
  return apiRequest<AccountPayable[]>(
    `${ACCOUNTING_PATH}/payables${buildQuery(filters)}`,
  );
}

export function getPayable(payableId: number): Promise<AccountPayable> {
  return apiRequest<AccountPayable>(
    `${ACCOUNTING_PATH}/payables/${payableId}`,
  );
}

// --------------------------------------------------------------------------- //
// Pagos y cobros — /api/v1/accounting/payments
// --------------------------------------------------------------------------- //

export function listPayments(
  filters: PaymentFilters = {},
): Promise<PaymentRecord[]> {
  return apiRequest<PaymentRecord[]>(
    `${ACCOUNTING_PATH}/payments${buildQuery(filters)}`,
  );
}

/** Registra un cobro o pago indicando exactamente un destino en el cuerpo. */
export function registerPayment(payload: PaymentCreate): Promise<PaymentRecord> {
  return apiRequest<PaymentRecord>(`${ACCOUNTING_PATH}/payments`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function registerReceivablePayment(
  receivableId: number,
  payload: PaymentRecordRequest,
): Promise<PaymentRecord> {
  return apiRequest<PaymentRecord>(
    `${ACCOUNTING_PATH}/receivables/${receivableId}/payments`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function registerPayablePayment(
  payableId: number,
  payload: PaymentRecordRequest,
): Promise<PaymentRecord> {
  return apiRequest<PaymentRecord>(
    `${ACCOUNTING_PATH}/payables/${payableId}/payments`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

// --------------------------------------------------------------------------- //
// Reportes financieros — /api/v1/accounting/reports
// --------------------------------------------------------------------------- //

/** Balance de comprobación de los asientos `POSTED` del periodo. */
export function getTrialBalance(
  filters: ReportFilters = {},
): Promise<TrialBalanceResponse> {
  return apiRequest<TrialBalanceResponse>(
    `${ACCOUNTING_PATH}/reports/trial-balance${buildQuery(filters)}`,
  );
}

/** Balance General con la ecuación activos = pasivos + patrimonio verificada. */
export function getBalanceSheet(
  filters: ReportFilters = {},
): Promise<BalanceSheetResponse> {
  return apiRequest<BalanceSheetResponse>(
    `${ACCOUNTING_PATH}/reports/balance-sheet${buildQuery(filters)}`,
  );
}

/** Estado de resultados (ingresos, gastos y resultado neto). */
export function getIncomeStatement(
  filters: ReportFilters = {},
): Promise<IncomeStatementResponse> {
  return apiRequest<IncomeStatementResponse>(
    `${ACCOUNTING_PATH}/reports/income-statement${buildQuery(filters)}`,
  );
}

// --------------------------------------------------------------------------- //
// Claves de caché de TanStack Query
// --------------------------------------------------------------------------- //

export const accountingKeys = {
  all: ["accounting"] as const,
  accounts: {
    all: ["accounting", "accounts"] as const,
    list: (filters: AccountFilters) =>
      ["accounting", "accounts", "list", filters] as const,
    detail: (accountId: number) =>
      ["accounting", "accounts", "detail", accountId] as const,
  },
  journalEntries: {
    all: ["accounting", "journal-entries"] as const,
    list: (filters: JournalEntryFilters) =>
      ["accounting", "journal-entries", "list", filters] as const,
    detail: (entryId: number) =>
      ["accounting", "journal-entries", "detail", entryId] as const,
  },
  receivables: {
    all: ["accounting", "receivables"] as const,
    list: (filters: ReceivableFilters) =>
      ["accounting", "receivables", "list", filters] as const,
    detail: (receivableId: number) =>
      ["accounting", "receivables", "detail", receivableId] as const,
  },
  payables: {
    all: ["accounting", "payables"] as const,
    list: (filters: PayableFilters) =>
      ["accounting", "payables", "list", filters] as const,
    detail: (payableId: number) =>
      ["accounting", "payables", "detail", payableId] as const,
  },
  payments: {
    all: ["accounting", "payments"] as const,
    list: (filters: PaymentFilters) =>
      ["accounting", "payments", "list", filters] as const,
  },
  reports: {
    all: ["accounting", "reports"] as const,
    trialBalance: (filters: ReportFilters) =>
      ["accounting", "reports", "trial-balance", filters] as const,
    balanceSheet: (filters: ReportFilters) =>
      ["accounting", "reports", "balance-sheet", filters] as const,
    incomeStatement: (filters: ReportFilters) =>
      ["accounting", "reports", "income-statement", filters] as const,
  },
} as const;
