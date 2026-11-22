/**
 * Hooks de TanStack Query v5 del módulo de Manufactura.
 *
 * Las mutaciones invalidan el detalle y los listados afectados. Las transiciones
 * de una OP también refrescan existencias, movimientos de inventario y el libro
 * diario, porque el backend las escribe en la misma transacción ACID.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { inventoryKeys } from "../../api/inventory";
import { accountingKeys } from "../accounting/api";
import {
  cancelProductionOrder,
  completeProductionOrder,
  createBom,
  createProductionOrder,
  createWorkCenter,
  deactivateBom,
  getBom,
  getProductionOrder,
  listBoms,
  listProductionOrders,
  listWorkCenters,
  manufacturingKeys,
  startProductionOrder,
  updateWorkCenter,
} from "./api";
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

// --------------------------------------------------------------------------- //
// Invalidación de caché
// --------------------------------------------------------------------------- //

function invalidateBoms(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: manufacturingKeys.boms.all });
}

function refreshOrderViews(
  queryClient: QueryClient,
  order: ProductionOrder,
): void {
  queryClient.setQueryData(manufacturingKeys.orders.detail(order.id), order);
  void queryClient.invalidateQueries({ queryKey: manufacturingKeys.orders.all });
  void queryClient.invalidateQueries({ queryKey: inventoryKeys.movements.all });
  void queryClient.invalidateQueries({ queryKey: inventoryKeys.stock.all });
  void queryClient.invalidateQueries({
    queryKey: accountingKeys.journalEntries.all,
  });
}

// --------------------------------------------------------------------------- //
// Consultas
// --------------------------------------------------------------------------- //

export function useWorkCenters(filters: WorkCenterFilters = {}) {
  return useQuery({
    queryKey: manufacturingKeys.workCenters.list(filters),
    queryFn: () => listWorkCenters(filters),
  });
}

export function useBoms(filters: BomFilters = {}) {
  return useQuery({
    queryKey: manufacturingKeys.boms.list(filters),
    queryFn: () => listBoms(filters),
  });
}

export function useBom(bomId: number, enabled = true) {
  return useQuery({
    queryKey: manufacturingKeys.boms.detail(bomId),
    queryFn: () => getBom(bomId),
    enabled: enabled && bomId > 0,
  });
}

export function useProductionOrders(filters: ProductionOrderFilters = {}) {
  return useQuery({
    queryKey: manufacturingKeys.orders.list(filters),
    queryFn: () => listProductionOrders(filters),
  });
}

export function useProductionOrder(orderId: number, enabled = true) {
  return useQuery({
    queryKey: manufacturingKeys.orders.detail(orderId),
    queryFn: () => getProductionOrder(orderId),
    enabled: enabled && orderId > 0,
  });
}

// --------------------------------------------------------------------------- //
// Mutaciones — centros de trabajo
// --------------------------------------------------------------------------- //

export function useCreateWorkCenter() {
  const queryClient = useQueryClient();
  return useMutation<WorkCenter, Error, WorkCenterCreate>({
    mutationFn: createWorkCenter,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: manufacturingKeys.workCenters.all,
      });
    },
  });
}

export interface UpdateWorkCenterVariables {
  workCenterId: number;
  payload: WorkCenterUpdate;
}

export function useUpdateWorkCenter() {
  const queryClient = useQueryClient();
  return useMutation<WorkCenter, Error, UpdateWorkCenterVariables>({
    mutationFn: ({ workCenterId, payload }) =>
      updateWorkCenter(workCenterId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: manufacturingKeys.workCenters.all,
      });
    },
  });
}

// --------------------------------------------------------------------------- //
// Mutaciones — listas de materiales
// --------------------------------------------------------------------------- //

export function useCreateBom() {
  const queryClient = useQueryClient();
  return useMutation<Bom, Error, BomCreate>({
    mutationFn: createBom,
    onSuccess: (bom) => {
      queryClient.setQueryData(manufacturingKeys.boms.detail(bom.id), bom);
      invalidateBoms(queryClient);
    },
  });
}

/** Desactivar una BOM no borra su historial: solo la marca como no vigente. */
export function useDeactivateBom() {
  const queryClient = useQueryClient();
  return useMutation<Bom, Error, number>({
    mutationFn: deactivateBom,
    onSuccess: (bom) => {
      queryClient.setQueryData(manufacturingKeys.boms.detail(bom.id), bom);
      invalidateBoms(queryClient);
    },
  });
}

// --------------------------------------------------------------------------- //
// Mutaciones — órdenes de producción
// --------------------------------------------------------------------------- //

export function useCreateProductionOrder() {
  const queryClient = useQueryClient();
  return useMutation<ProductionOrder, Error, ProductionOrderCreate>({
    mutationFn: createProductionOrder,
    onSuccess: (order) => refreshOrderViews(queryClient, order),
  });
}

export function useStartProductionOrder() {
  const queryClient = useQueryClient();
  return useMutation<ProductionOrder, Error, number>({
    mutationFn: startProductionOrder,
    onSuccess: (order) => refreshOrderViews(queryClient, order),
  });
}

export interface CompleteOrderVariables {
  orderId: number;
  payload: ProductionOrderComplete;
}

export function useCompleteProductionOrder() {
  const queryClient = useQueryClient();
  return useMutation<ProductionOrder, Error, CompleteOrderVariables>({
    mutationFn: ({ orderId, payload }) =>
      completeProductionOrder(orderId, payload),
    onSuccess: (order) => refreshOrderViews(queryClient, order),
  });
}

export function useCancelProductionOrder() {
  const queryClient = useQueryClient();
  return useMutation<ProductionOrder, Error, number>({
    mutationFn: cancelProductionOrder,
    onSuccess: (order) => refreshOrderViews(queryClient, order),
  });
}
