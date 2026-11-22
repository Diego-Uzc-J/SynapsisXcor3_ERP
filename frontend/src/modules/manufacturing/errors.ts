/** Traducción de errores HTTP del backend de manufactura a mensajes accionables. */

export function errorMessage(error: unknown): string | null {
  if (error instanceof Error && error.message.trim() !== "") {
    return error.message;
  }
  return null;
}

/**
 * Pista derivada del mensaje del backend, sin ocultar el `detail` original.
 *
 * El handler de manufactura devuelve textos explícitos para déficit de stock,
 * BOM inactiva/duplicada, transiciones inválidas e inmutabilidad; aquí se añade
 * la acción recomendada para el operador.
 */
export function errorHint(message: string): string | null {
  const normalized = message.toLowerCase();

  if (normalized.includes("stock insuficiente") || normalized.includes("déficit")) {
    return "Reabastece el componente indicado en la bodega de origen o reduce la cantidad a producir.";
  }
  if (normalized.includes("inactiva")) {
    return "Selecciona una BOM vigente; las recetas desactivadas solo sirven como historial.";
  }
  if (normalized.includes("bom activa") || normalized.includes("ya existe una bom")) {
    return "Desactiva la versión anterior o usa otro código y otra versión de la receta.";
  }
  if (normalized.includes("no se puede iniciar") || normalized.includes("in_progress")) {
    return "Solo se puede completar una orden que esté en estado En proceso.";
  }
  if (normalized.includes("completad") || normalized.includes("cancelad") || normalized.includes("inmutable")) {
    return "Las órdenes cerradas no se modifican ni se reabren; crea una nueva orden si necesitas corregirla.";
  }
  if (normalized.includes("bodega") || normalized.includes("almacén")) {
    return "La bodega de origen y la de destino deben existir y ser distintas.";
  }
  if (normalized.includes("contab") || normalized.includes("asiento")) {
    return "La operación se revirtió por completo. Revisa el plan de cuentas y vuelve a intentarlo.";
  }
  if (normalized.includes("forbidden") || normalized.includes("403")) {
    return "Tu rol no tiene acceso a este módulo.";
  }
  return null;
}
