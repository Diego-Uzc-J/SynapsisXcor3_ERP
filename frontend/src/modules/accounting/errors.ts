/** Traducción de errores de negocio de contabilidad a mensajes accionables. */

export function errorMessage(error: unknown): string | null {
  if (error instanceof Error && error.message.trim() !== "") {
    return error.message;
  }
  return null;
}

/**
 * Pista derivada del mensaje del backend.
 *
 * El router de contabilidad devuelve textos explícitos para asientos
 * desbalanceados, cuentas inactivas, periodos cerrados y pagos que exceden el
 * saldo; aquí se añade qué hacer a continuación sin ocultar el mensaje original.
 */
export function errorHint(message: string): string | null {
  const normalized = message.toLowerCase();
  if (normalized.includes("equilibr") || normalized.includes("débito")) {
    return (
      "La partida doble exige que la suma de débitos sea igual a la de " +
      "créditos antes de contabilizar."
    );
  }
  if (normalized.includes("inactiva") || normalized.includes("activas")) {
    return "Selecciona solo cuentas activas del plan de cuentas.";
  }
  if (normalized.includes("cerrado") || normalized.includes("periodo")) {
    return "El periodo contable está cerrado; usa una fecha en un periodo abierto.";
  }
  if (normalized.includes("saldo pendiente") || normalized.includes("excede")) {
    return "El monto debe ser mayor que cero y no superar el saldo pendiente.";
  }
  if (normalized.includes("ya existe") || normalized.includes("duplicad")) {
    return "El código debe ser único; ajusta el código del comprobante o de la cuenta.";
  }
  if (normalized.includes("dos líneas") || normalized.includes("líneas")) {
    return "Un asiento necesita al menos dos líneas de partida doble.";
  }
  if (normalized.includes("inmutable") || normalized.includes("contabilizado")) {
    return "Un asiento contabilizado no se modifica: registra una reversión.";
  }
  return null;
}
