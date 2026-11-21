/** Etiquetas, tonos y ayudas de los estados del módulo contable. */

import type {
  AccountBalanceStatus,
  AccountType,
  JournalEntryStatus,
} from "./types";

export const ACCOUNT_TYPE_LABELS: Record<AccountType, string> = {
  ASSET: "Activo",
  LIABILITY: "Pasivo",
  EQUITY: "Patrimonio",
  REVENUE: "Ingreso",
  EXPENSE: "Gasto",
};

export type BadgeTone = "neutral" | "warning" | "success" | "strong" | "muted";

export const JOURNAL_STATUS_LABELS: Record<JournalEntryStatus, string> = {
  DRAFT: "Borrador",
  POSTED: "Contabilizado",
  VOID: "Anulado",
};

export const JOURNAL_STATUS_HINTS: Record<JournalEntryStatus, string> = {
  DRAFT: "Editable; aún no afecta saldos ni reportes.",
  POSTED: "Inmutable; solo se corrige con un asiento de reversión.",
  VOID: "Descartado antes de contabilizar.",
};

export const JOURNAL_STATUS_TONES: Record<JournalEntryStatus, BadgeTone> = {
  DRAFT: "warning",
  POSTED: "success",
  VOID: "muted",
};

export const BALANCE_STATUS_LABELS: Record<AccountBalanceStatus, string> = {
  PENDING: "Pendiente",
  PARTIALLY_PAID: "Pago parcial",
  PAID: "Pagado",
  OVERDUE: "Vencido",
};

export const BALANCE_STATUS_HINTS: Record<AccountBalanceStatus, string> = {
  PENDING: "Sin abonos registrados.",
  PARTIALLY_PAID: "Con abonos parciales; queda saldo por cubrir.",
  PAID: "Saldo liquidado; no admite más abonos.",
  OVERDUE: "Vencida con saldo pendiente; sigue admitiendo abonos.",
};

export const BALANCE_STATUS_TONES: Record<AccountBalanceStatus, BadgeTone> = {
  PENDING: "neutral",
  PARTIALLY_PAID: "warning",
  PAID: "success",
  OVERDUE: "strong",
};

/** Clave local de la pestaña de reportes seleccionada. */
export type ReportKey = "trial" | "balance" | "income";

export const REPORT_LABELS: Record<ReportKey, string> = {
  trial: "Balance de comprobación",
  balance: "Balance general",
  income: "Estado de resultados",
};
