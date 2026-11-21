/** Formateadores y aritmética monetaria de las vistas contables. */

const moneyFormatter = new Intl.NumberFormat("es-CO", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const dateFormatter = new Intl.DateTimeFormat("es-CO", { dateStyle: "medium" });

const dateTimeFormatter = new Intl.DateTimeFormat("es-CO", {
  dateStyle: "medium",
  timeStyle: "short",
});

/** Pydantic serializa `Decimal` como cadena; se formatea sin perder precisión. */
export function formatMoney(value: string | number): string {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? moneyFormatter.format(parsed) : String(value);
}

export function formatCents(cents: number): string {
  return moneyFormatter.format(cents / 100);
}

export function formatDate(value: string): string {
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? value : dateFormatter.format(parsed);
}

export function formatDateTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : dateTimeFormatter.format(parsed);
}

/** Convierte centavos a la cadena de dos decimales que exige el backend. */
export function moneyString(cents: number): string {
  return (cents / 100).toFixed(2);
}

/** Acepta coma decimal y separadores de miles, y normaliza al punto de la API. */
export function normalizeDecimal(value: string): string {
  const trimmed = value.trim();
  if (!trimmed.includes(",")) {
    return trimmed;
  }
  return trimmed.replace(/\./g, "").replace(",", ".");
}

/** Importe no negativo con hasta dos decimales, o `null` si es inválido. */
export function parseAmount(value: string): number | null {
  const normalized = normalizeDecimal(value);
  if (!/^\d{1,12}(\.\d{1,2})?$/.test(normalized)) {
    return null;
  }
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

/** Importe a centavos; las sumas se hacen enteras para evitar coma flotante. */
export function toCents(value: string | number): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? Math.round(parsed * 100) : 0;
}

function toIsoDate(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/** Fecha local de hoy en formato `YYYY-MM-DD` (sin desfase UTC). */
export function todayIso(): string {
  return toIsoDate(new Date());
}

/** Fecha local de hoy más `days` días en formato `YYYY-MM-DD`. */
export function todayPlusDays(days: number): string {
  const value = new Date();
  value.setDate(value.getDate() + days);
  return toIsoDate(value);
}
