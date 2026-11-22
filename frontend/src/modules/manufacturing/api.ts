/**
 * Cliente HTTP del módulo de Manufactura y Producción.
 *
 * Usa `apiRequest`, la instancia compartida del ERP que añade el Bearer token,
 * traduce los errores de FastAPI (400/401/403/404/409/422) y renueva la sesión
 * ante un 401. Todas las rutas cuelgan de `/api/v1/manufacturing`.
 */
import { apiRequest } from "../../api/client";
import { buildQuery } from "../../api/config";
import type {
  Bom,
  BomCreate,
  BomFilters,
  ProductionOrder,
  ProductionOrderComplete,
  ProductionOrderCreate,
  ProductionOrderFilters,
  WorkCenter,
  WorkCenterCreate,
  WorkCenterFilters,
  WorkCenterUpdate,
} from "./types";

export { ApiError as ManufacturingApiError } from "../../api/client";

const MANUFACTURING_PATH = "/api/v1/manufacturing";

// --------------------------------------------------------------------------- //
// Centros de trabajo — /api/v1/manufacturing/work-centers
// --------------------------------------------------------------------------- //

export function listWorkCenters(
  filters: WorkCenterFilters = {},
): Promise<WorkCenter[]> {
  return apiRequest<WorkCenter[]>(
    `${MANUFACTURING_PATH}/work-centers${buildQuery(filters)}`,
  );
}

export function createWorkCenter(payload: WorkCenterCreate): Promise<WorkCenter> {
  return apiRequest<WorkCenter>(`${MANUFACTURING_PATH}/work-centers`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateWorkCenter(
  workCenterId: number,
  payload: WorkCenterUpdate,
): Promise<WorkCenter> {
  return apiRequest<WorkCenter>(
    `${MANUFACTURING_PATH}/work-centers/${workCenterId}`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );
}

// --------------------------------------------------------------------------- //
// Listas de materiales — /api/v1/manufacturing/boms
// --------------------------------------------------------------------------- //

export function listBoms(filters: BomFilters = {}): Promise<Bom[]> {
  return apiRequest<Bom[]>(
    `${MANUFACTURING_PATH}/boms${buildQuery(filters)}`,
  );
}

export function getBom(bomId: number): Promise<Bom> {
  return apiRequest<Bom>(`${MANUFACTURING_PATH}/boms/${bomId}`);
}

export function createBom(payload: BomCreate): Promise<Bom> {
  return apiRequest<Bom>(`${MANUFACTURING_PATH}/boms`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deactivateBom(bomId: number): Promise<Bom> {
  return apiRequest<Bom>(`${MANUFACTURING_PATH}/boms/${bomId}/deactivate`, {
    method: "PATCH",
  });
}

// --------------------------------------------------------------------------- //
// Órdenes de producción — /api/v1/manufacturing/orders
// --------------------------------------------------------------------------- //

export function listProductionOrders(
  filters: ProductionOrderFilters = {},
): Promise<ProductionOrder[]> {
  return apiRequest<ProductionOrder[]>(
    `${MANUFACTURING_PATH}/orders${buildQuery(filters)}`,
  );
}

export function getProductionOrder(orderId: number): Promise<ProductionOrder> {
  return apiRequest<ProductionOrder>(`${MANUFACTURING_PATH}/orders/${orderId}`);
}

export function createProductionOrder(
  payload: ProductionOrderCreate,
): Promise<ProductionOrder> {
  return apiRequest<ProductionOrder>(`${MANUFACTURING_PATH}/orders`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** `PLANNED → IN_PROGRESS`: consume la BOM y valida stock en inventario. */
export function startProductionOrder(orderId: number): Promise<ProductionOrder> {
  return apiRequest<ProductionOrder>(
    `${MANUFACTURING_PATH}/orders/${orderId}/start`,
    { method: "POST" },
  );
}

/** `IN_PROGRESS → COMPLETED`: costes, ingreso de producto y asiento contable. */
export function completeProductionOrder(
  orderId: number,
  payload: ProductionOrderComplete,
): Promise<ProductionOrder> {
  return apiRequest<ProductionOrder>(
    `${MANUFACTURING_PATH}/orders/${orderId}/complete`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

/** Cancela la OP y revierte los consumos si ya estaba en curso. */
export function cancelProductionOrder(orderId: number): Promise<ProductionOrder> {
  return apiRequest<ProductionOrder>(
    `${MANUFACTURING_PATH}/orders/${orderId}/cancel`,
    { method: "POST" },
  );
}

// --------------------------------------------------------------------------- //
// Claves de caché de TanStack Query
// --------------------------------------------------------------------------- //

export const manufacturingKeys = {
  all: ["manufacturing"] as const,
  workCenters: {
    all: ["manufacturing", "work-centers"] as const,
    list: (filters: WorkCenterFilters) =>
      ["manufacturing", "work-centers", "list", filters] as const,
  },
  boms: {
    all: ["manufacturing", "boms"] as const,
    list: (filters: BomFilters) =>
      ["manufacturing", "boms", "list", filters] as const,
    detail: (bomId: number) =>
      ["manufacturing", "boms", "detail", bomId] as const,
  },
  orders: {
    all: ["manufacturing", "orders"] as const,
    list: (filters: ProductionOrderFilters) =>
      ["manufacturing", "orders", "list", filters] as const,
    detail: (orderId: number) =>
      ["manufacturing", "orders", "detail", orderId] as const,
  },
} as const;
