/** Formateadores y normalización decimal de las vistas de manufactura. */

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
export function formatMoney(value: string | null): string {
  if (value === null) {
    return "—";
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? moneyFormatter.format(parsed) : value;
}

export function formatQuantity(value: string): string {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? moneyFormatter.format(parsed) : value;
}

export function formatHours(value: string): string {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${moneyFormatter.format(parsed)} h` : value;
}

export function formatPercent(value: string): string {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${moneyFormatter.format(parsed)} %` : value;
}

export function formatDate(value: string | null): string {
  if (value === null) {
    return "—";
  }
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? value : dateFormatter.format(parsed);
}

export function formatDateTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : dateTimeFormatter.format(parsed);
}

/** Acepta coma decimal y separadores de miles, y normaliza al punto de la API. */
function normalizeDecimal(value: string): string {
  const trimmed = value.trim();
  if (!trimmed.includes(",")) {
    return trimmed;
  }
  return trimmed.replace(/\./g, "").replace(",", ".");
}

/**
 * Decimal no negativo con hasta dos decimales convertido a cadena para la API.
 * Devuelve `null` cuando el texto no es válido, evitando enviar `float`.
 */
export function decimalString(value: string): string | null {
  const normalized = normalizeDecimal(value);
  if (!/^\d{1,12}(\.\d{1,2})?$/.test(normalized)) {
    return null;
  }
  return Number(normalized).toFixed(2);
}

/** Porcentaje de merma entre 0 y 100, como cadena decimal. */
export function percentString(value: string): string | null {
  const normalized = decimalString(value);
  if (normalized === null || Number(normalized) > 100) {
    return null;
  }
  return normalized;
}

/** Fecha local de hoy en formato `YYYY-MM-DD` (sin desfase UTC). */
export function todayIso(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
