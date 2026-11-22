/**
 * Contratos TypeScript del módulo de Manufactura y Producción.
 *
 * Derivados de `backend/src/modules/manufacturing/schemas.py`, del router bajo
 * `/api/v1/manufacturing` y de `specs/manufacturing_spec.md`. Pydantic serializa
 * los `Decimal` como cadena, por lo que cantidades, horas, mermas y costes se
 * modelan como `string` y se envían también como cadena: el backend rechaza
 * explícitamente los `float`.
 */

export const PRODUCTION_ORDER_STATUSES = [
  "PLANNED",
  "IN_PROGRESS",
  "COMPLETED",
  "CANCELLED",
] as const;
export type ProductionOrderStatus = (typeof PRODUCTION_ORDER_STATUSES)[number];

export interface WorkCenter {
  id: number;
  code: string;
  name: string;
  cost_per_hour: string;
  is_active: boolean;
  created_at: string;
}

export interface WorkCenterCreate {
  code: string;
  name: string;
  cost_per_hour: string;
  is_active: boolean;
}

/** PATCH parcial: el backend exige al menos un campo no nulo. */
export interface WorkCenterUpdate {
  code?: string;
  name?: string;
  cost_per_hour?: string;
  is_active?: boolean;
}

export interface BomItem {
  id: number;
  bom_id: number;
  component_product_id: number;
  /** Cantidad del insumo por cada unidad del producto final. */
  quantity: string;
  scrap_percentage: string;
}

export interface BomItemCreate {
  component_product_id: number;
  quantity: string;
  scrap_percentage: string;
}

export interface Bom {
  id: number;
  code: string;
  product_id: number;
  version: number;
  name: string | null;
  is_active: boolean;
  notes: string | null;
  created_at: string;
  items: BomItem[];
}

export interface BomCreate {
  code: string;
  product_id: number;
  version: number;
  name: string | null;
  is_active: boolean;
  notes: string | null;
  items: BomItemCreate[];
}

export interface ProductionOrder {
  id: number;
  code: string;
  bom_id: number;
  work_center_id: number | null;
  warehouse_source_id: number;
  warehouse_destination_id: number;
  quantity_to_produce: string;
  quantity_produced: string;
  estimated_hours: string;
  actual_hours: string;
  unit_production_cost: string | null;
  total_production_cost: string | null;
  status: ProductionOrderStatus;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface ProductionOrderCreate {
  /** `null` para que el servicio genere `OP-YYYY-XXXX`. */
  code: string | null;
  bom_id: number;
  work_center_id: number | null;
  warehouse_source_id: number;
  warehouse_destination_id: number;
  quantity_to_produce: string;
  estimated_hours: string;
}

export interface ProductionOrderComplete {
  quantity_produced: string;
  actual_hours: string;
  /** `null` para que el servicio use la fecha actual. */
  completed_at: string | null;
}

export interface WorkCenterFilters {
  is_active?: boolean;
  skip?: number;
  limit?: number;
}

export interface BomFilters {
  product_id?: number;
  is_active?: boolean;
  skip?: number;
  limit?: number;
}

export interface ProductionOrderFilters {
  status?: ProductionOrderStatus;
  bom_id?: number;
  created_date?: string;
  skip?: number;
  limit?: number;
}
