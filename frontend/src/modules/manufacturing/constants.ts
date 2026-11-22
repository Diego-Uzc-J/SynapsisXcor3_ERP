/** Etiquetas, tonos y transiciones permitidas del módulo de manufactura. */

import type { ProductionOrderStatus } from "./types";

export type BadgeTone = "neutral" | "warning" | "success" | "strong" | "muted";

export const ORDER_STATUS_LABELS: Record<ProductionOrderStatus, string> = {
  PLANNED: "Planificada",
  IN_PROGRESS: "En proceso",
  COMPLETED: "Completada",
  CANCELLED: "Cancelada",
};

export const ORDER_STATUS_TONES: Record<ProductionOrderStatus, BadgeTone> = {
  PLANNED: "warning",
  IN_PROGRESS: "neutral",
  COMPLETED: "success",
  CANCELLED: "muted",
};

export const ORDER_STATUS_HINTS: Record<ProductionOrderStatus, string> = {
  PLANNED: "Puede iniciarse o cancelarse; aún no consumió materias primas.",
  IN_PROGRESS:
    "Ya consumió los componentes de la BOM; puede completarse o cancelarse con reversión.",
  COMPLETED:
    "Inmutable: registró el ingreso de producto terminado, los costes y el asiento contable.",
  CANCELLED:
    "Inmutable: si había empezado, se revirtieron sus consumos de inventario.",
};

/** Regla 6 de la spec: solo una OP planificada puede iniciarse. */
export function canStartOrder(status: ProductionOrderStatus): boolean {
  return status === "PLANNED";
}

/** Regla 6 de la spec: solo una OP en proceso puede completarse. */
export function canCompleteOrder(status: ProductionOrderStatus): boolean {
  return status === "IN_PROGRESS";
}

/** Una OP planificada o en proceso puede cancelarse. */
export function canCancelOrder(status: ProductionOrderStatus): boolean {
  return status === "PLANNED" || status === "IN_PROGRESS";
}

/** Regla 4 de la spec: las órdenes cerradas no se reabren ni se editan. */
export function isClosedOrder(status: ProductionOrderStatus): boolean {
  return status === "COMPLETED" || status === "CANCELLED";
}
