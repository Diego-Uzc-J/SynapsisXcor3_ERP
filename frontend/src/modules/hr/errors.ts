/** Traducción de errores HTTP del backend de RRHH a mensajes accionables. */

export function errorMessage(error: unknown): string | null {
  if (error instanceof Error && error.message.trim() !== "") {
    return error.message;
  }
  return null;
}

/**
 * Pista derivada del mensaje del backend.
 *
 * El router de RRHH devuelve textos explícitos para contrato vigente, códigos
 * duplicados, nómina inmutable y fallos de contabilidad; aquí se añade qué
 * hacer a continuación sin ocultar el mensaje original.
 */
export function errorHint(message: string): string | null {
  const normalized = message.toLowerCase();

  if (normalized.includes("contrato vigente")) {
    return "Cierra el contrato actual o registra el nuevo como histórico inactivo.";
  }
  if (normalized.includes("identification") || normalized.includes("documento")) {
    return "Revisa el número de identificación: debe ser único en la empresa.";
  }
  if (normalized.includes("code") || normalized.includes("código")) {
    return "Usa un código de periodo diferente; los códigos de nómina son únicos.";
  }
  if (
    normalized.includes("aprobad") ||
    normalized.includes("inmutable") ||
    normalized.includes("pagada")
  ) {
    return "Los periodos aprobados o pagados no se modifican; genera una nómina de ajuste.";
  }
  if (normalized.includes("contab") || normalized.includes("asiento")) {
    return (
      "La aprobación se revertió por completo. Revisa el plan de cuentas y " +
      "vuelve a intentarlo."
    );
  }
  if (normalized.includes("sin contrato") || normalized.includes("contract")) {
    return "El empleado debe tener un contrato activo vigente en el periodo.";
  }
  if (normalized.includes("forbidden") || normalized.includes("403")) {
    return "Tu rol no tiene acceso a este módulo.";
  }
  return null;
}
