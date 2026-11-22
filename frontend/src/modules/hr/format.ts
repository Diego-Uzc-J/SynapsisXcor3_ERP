/** Formateadores y normalización decimal de las vistas de RRHH. */

const moneyFormatter = new Intl.NumberFormat("es-CO", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const hoursFormatter = new Intl.NumberFormat("es-CO", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const dateFormatter = new Intl.DateTimeFormat("es-CO", { dateStyle: "medium" });
const dateTimeFormatter = new Intl.DateTimeFormat("es-CO", {
  dateStyle: "medium",
  timeStyle: "short",
});

/** Pydantic serializa `Decimal` como cadena; se formatea sin perder precisión. */
export function formatMoney(value: string): string {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? moneyFormatter.format(parsed) : value;
}

export function formatHours(value: string): string {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${hoursFormatter.format(parsed)} h` : value;
}

export function formatDate(value: string): string {
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
 * Importe con hasta dos decimales convertido a la cadena que exige el backend.
 * Devuelve `null` cuando el texto no es válido para evitar enviar `float`.
 */
export function moneyString(value: string): string | null {
  const normalized = normalizeDecimal(value);
  if (!/^\d{1,12}(\.\d{1,2})?$/.test(normalized)) {
    return null;
  }
  return Number(normalized).toFixed(2);
}

/** Horas no negativas con hasta dos decimales, como cadena decimal. */
export function hoursString(value: string): string | null {
  const normalized = normalizeDecimal(value);
  if (!/^\d{1,5}(\.\d{1,2})?$/.test(normalized)) {
    return null;
  }
  return Number(normalized).toFixed(2);
}

/** Fecha local de hoy en formato `YYYY-MM-DD` (sin desfase UTC). */
export function todayIso(): string {
  return toIsoDate(new Date());
}

/** Primer y último día del mes actual, en formato `YYYY-MM-DD`. */
export function currentMonthRange(): { start: string; end: string } {
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth();
  return {
    start: toIsoDate(new Date(year, month, 1)),
    end: toIsoDate(new Date(year, month + 1, 0)),
  };
}

function toIsoDate(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
