import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useProducts, useWarehouses } from "../../api/inventory";
import type { Product, Warehouse } from "../../api/inventory";
import { canWriteModule, useAuth } from "../../store/authStore";
import {
  canCancelOrder,
  canCompleteOrder,
  canStartOrder,
  isClosedOrder,
  ORDER_STATUS_HINTS,
  ORDER_STATUS_LABELS,
  ORDER_STATUS_TONES,
} from "./constants";
import { errorHint, errorMessage } from "./errors";
import {
  decimalString,
  formatDate,
  formatDateTime,
  formatMoney,
  formatPercent,
  formatQuantity,
} from "./format";
import {
  useBom,
  useCancelProductionOrder,
  useCompleteProductionOrder,
  useProductionOrder,
  useStartProductionOrder,
  useWorkCenters,
} from "./hooks";
import ManufacturingDialog from "./ManufacturingDialog";
import ManufacturingTabs from "./ManufacturingTabs";
import StatusBadge from "./StatusBadge";
import type { BomItem } from "./types";

type DialogKind = "start" | "complete" | "cancel" | null;
type Feedback = { tone: "success" | "error"; text: string };

/** Cantidad entera que el backend descuenta por componente (ROUND_CEILING). */
function requiredUnits(item: BomItem, quantityToProduce: string): number {
  const perUnit = Number(item.quantity);
  const scrap = Number(item.scrap_percentage);
  const target = Number(quantityToProduce);
  if (
    !Number.isFinite(perUnit) ||
    !Number.isFinite(scrap) ||
    !Number.isFinite(target)
  ) {
    return 0;
  }
  return Math.max(1, Math.ceil(perUnit * (1 + scrap / 100) * target));
}

function productLabel(product: Product | undefined, productId: number): string {
  return product === undefined
    ? `Producto #${productId}`
    : `${product.sku} · ${product.name}`;
}

function warehouseLabel(warehouse: Warehouse | undefined, warehouseId: number): string {
  return warehouse === undefined
    ? `Bodega #${warehouseId}`
    : `${warehouse.code} · ${warehouse.name}`;
}

function SummaryCard({
  label,
  value,
  emphasis = false,
}: {
  label: string;
  value: string;
  emphasis?: boolean;
}) {
  return (
    <div className="border border-concrete-200 bg-white px-4 py-3">
      <p className="text-xs font-semibold text-ink-500">{label}</p>
      <p
        className={[
          "mt-1 text-xl font-extrabold tabular-nums sm:text-2xl",
          emphasis ? "text-signal-600" : "text-ink-950",
        ].join(" ")}
      >
        {value}
      </p>
    </div>
  );
}

export default function ProductionOrderDetail() {
  const { orderId: rawId } = useParams();
  const orderId = Number(rawId);
  const validId = Number.isInteger(orderId) && orderId > 0;

  const { user } = useAuth();
  const canWrite = canWriteModule(user, "manufacturing");

  const orderQuery = useProductionOrder(orderId, validId);
  const order = orderQuery.data;
  const bomId = order?.bom_id ?? 0;
  const bomQuery = useBom(bomId, order !== undefined);
  const productsQuery = useProducts({ limit: 200, is_active: true });
  const warehousesQuery = useWarehouses({ limit: 200 });
  const centersQuery = useWorkCenters({ limit: 200, is_active: true });

  const startMutation = useStartProductionOrder();
  const completeMutation = useCompleteProductionOrder();
  const cancelMutation = useCancelProductionOrder();

  const [dialog, setDialog] = useState<DialogKind>(null);
  const [completeQuantity, setCompleteQuantity] = useState("");
  const [completeHours, setCompleteHours] = useState("0.00");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  useEffect(() => {
    if (dialog === "complete") {
      setCompleteQuantity(order?.quantity_to_produce ?? "");
      setCompleteHours(order?.estimated_hours ?? "0.00");
      setValidationError(null);
    }
  }, [dialog, order?.quantity_to_produce, order?.estimated_hours]);

  const products = productsQuery.data ?? [];
  const warehouses = warehousesQuery.data ?? [];
  const centers = centersQuery.data ?? [];
  const bom = bomQuery.data;
  const message = errorMessage(orderQuery.error);

  function openDialog(kind: Exclude<DialogKind, null>) {
    setFeedback(null);
    setValidationError(null);
    setDialog(kind);
  }

  function handleStart() {
    if (order === undefined) {
      return;
    }
    startMutation.mutate(order.id, {
      onSuccess: (updated) => {
        setDialog(null);
        setFeedback({
          tone: "success",
          text: `Orden ${updated.code} iniciada; componentes descontados de la bodega de origen.`,
        });
      },
      onError: (error) => {
        setDialog(null);
        setFeedback({
          tone: "error",
          text: errorMessage(error) ?? "No se pudo iniciar la orden.",
        });
      },
    });
  }

  function handleComplete() {
    if (order === undefined) {
      return;
    }
    setValidationError(null);
    const quantity = decimalString(completeQuantity);
    const hours = decimalString(completeHours);
    if (quantity === null || Number(quantity) <= 0) {
      setValidationError("La cantidad producida debe ser mayor que cero.");
      return;
    }
    if (hours === null) {
      setValidationError("Las horas reales deben ser un número no negativo.");
      return;
    }

    completeMutation.mutate(
      {
        orderId: order.id,
        payload: {
          quantity_produced: quantity,
          actual_hours: hours,
          completed_at: null,
        },
      },
      {
        onSuccess: (updated) => {
          setDialog(null);
          setFeedback({
            tone: "success",
            text: `Orden ${updated.code} completada: coste ${formatMoney(updated.total_production_cost)} registrado con su asiento.`,
          });
        },
        onError: (error) => {
          setDialog(null);
          setFeedback({
            tone: "error",
            text: errorMessage(error) ?? "No se pudo completar la orden.",
          });
        },
      },
    );
  }

  function handleCancel() {
    if (order === undefined) {
      return;
    }
    cancelMutation.mutate(order.id, {
      onSuccess: (updated) => {
        setDialog(null);
        setFeedback({
          tone: "success",
          text: `Orden ${updated.code} cancelada; los consumos fueron revertidos si la orden estaba en curso.`,
        });
      },
      onError: (error) => {
        setDialog(null);
        setFeedback({
          tone: "error",
          text: errorMessage(error) ?? "No se pudo cancelar la orden.",
        });
      },
    });
  }

  if (!validId || message !== null || (!orderQuery.isPending && order === undefined)) {
    return (
      <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
        <ManufacturingTabs />
        <div className="mt-6 border border-signal-500/40 bg-signal-100 px-5 py-6">
          <h1 className="text-xl font-bold">No se pudo cargar la orden</h1>
          <p className="mt-1 text-sm text-ink-700">
            {message ?? "El identificador de la orden no es válido."}
          </p>
          <Link
            className="mt-4 inline-block text-sm font-semibold text-signal-600 hover:underline"
            to="/manufacturing/orders"
          >
            Volver a órdenes de producción
          </Link>
        </div>
      </div>
    );
  }

  if (orderQuery.isPending || order === undefined) {
    return (
      <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
        <ManufacturingTabs />
        <p className="mt-6 border border-concrete-200 bg-white px-4 py-8 text-center text-sm text-ink-500">
          Cargando detalle de la orden…
        </p>
      </div>
    );
  }

  const center = centers.find((item) => item.id === order.work_center_id);
  const actionError = errorMessage(
    startMutation.error ?? completeMutation.error ?? cancelMutation.error,
  );
  const actionPending =
    startMutation.isPending ||
    completeMutation.isPending ||
    cancelMutation.isPending;

  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <header className="border-b-2 border-ink-950 pb-6">
        <Link
          className="text-xs font-semibold text-ink-500 hover:text-signal-600 hover:underline"
          to="/manufacturing/orders"
        >
          ← Órdenes de producción
        </Link>
        <div className="mt-3 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
              Orden #{order.id}
            </p>
            <h1 className="mt-2 text-3xl font-extrabold tracking-tight sm:text-4xl">
              {order.code}
            </h1>
            <p className="mt-1 text-sm text-ink-700">
              {bom === undefined
                ? `BOM #${order.bom_id}`
                : productLabel(
                    products.find((product) => product.id === bom.product_id),
                    bom.product_id,
                  )}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge
              label={ORDER_STATUS_LABELS[order.status]}
              tone={ORDER_STATUS_TONES[order.status]}
              hint={ORDER_STATUS_HINTS[order.status]}
            />
            {canWrite && canStartOrder(order.status) ? (
              <button
                type="button"
                onClick={() => openDialog("start")}
                className="bg-signal-500 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-signal-600"
              >
                Iniciar orden
              </button>
            ) : null}
            {canWrite && canCompleteOrder(order.status) ? (
              <button
                type="button"
                onClick={() => openDialog("complete")}
                className="bg-signal-500 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-signal-600"
              >
                Completar
              </button>
            ) : null}
            {canWrite && canCancelOrder(order.status) ? (
              <button
                type="button"
                onClick={() => openDialog("cancel")}
                className="border border-concrete-200 px-4 py-2.5 text-sm font-semibold text-ink-700 hover:border-signal-500 hover:text-signal-600"
              >
                Cancelar
              </button>
            ) : null}
          </div>
        </div>
      </header>

      {feedback === null ? null : (
        <p
          className={[
            "mt-4 border px-4 py-3 text-sm",
            feedback.tone === "success"
              ? "border-pine-600 bg-pine-100 text-pine-600"
              : "border-signal-500/40 bg-signal-100 text-ink-900",
          ].join(" ")}
        >
          {feedback.text}
          {feedback.tone === "error" ? (
            <span className="block text-xs">{errorHint(feedback.text)}</span>
          ) : null}
        </p>
      )}

      <p className="mt-6 text-xs text-ink-500">
        {ORDER_STATUS_HINTS[order.status]}
        {isClosedOrder(order.status) ? " No admite nuevas transiciones." : ""}
      </p>

      <section className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryCard
          label="Cantidad planificada"
          value={formatQuantity(order.quantity_to_produce)}
        />
        <SummaryCard
          label="Cantidad producida"
          value={formatQuantity(order.quantity_produced)}
        />
        <SummaryCard
          label="Horas estimadas / reales"
          value={`${formatQuantity(order.estimated_hours)} / ${formatQuantity(order.actual_hours)}`}
        />
        <SummaryCard
          label="Coste total"
          value={formatMoney(order.total_production_cost)}
          emphasis
        />
      </section>

      <section className="mt-4 grid gap-4 sm:grid-cols-3">
        <SummaryCard
          label="Coste unitario"
          value={formatMoney(order.unit_production_cost)}
        />
        <div className="border border-concrete-200 bg-white px-4 py-3">
          <p className="text-xs font-semibold text-ink-500">Centro de trabajo</p>
          <p className="mt-1 text-sm font-semibold">
            {center === undefined
              ? "Sin centro asignado"
              : `${center.code} · ${center.name}`}
          </p>
          <p className="mt-0.5 text-xs text-ink-500">
            {center === undefined ? "—" : `Coste/h ${formatMoney(center.cost_per_hour)}`}
          </p>
        </div>
        <div className="border border-concrete-200 bg-white px-4 py-3">
          <p className="text-xs font-semibold text-ink-500">Bodegas</p>
          <p className="mt-1 text-xs font-semibold">
            Origen: {warehouseLabel(
              warehouses.find((item) => item.id === order.warehouse_source_id),
              order.warehouse_source_id,
            )}
          </p>
          <p className="mt-0.5 text-xs text-ink-700">
            Destino: {warehouseLabel(
              warehouses.find(
                (item) => item.id === order.warehouse_destination_id,
              ),
              order.warehouse_destination_id,
            )}
          </p>
        </div>
      </section>

      <section className="mt-6 border border-concrete-200 bg-white px-4 py-4 text-sm">
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <p className="text-xs font-semibold text-ink-500">Creación</p>
            <p className="mt-0.5 font-semibold">
              {formatDateTime(order.created_at)}
            </p>
          </div>
          <div>
            <p className="text-xs font-semibold text-ink-500">Inicio</p>
            <p className="mt-0.5 font-semibold">{formatDate(order.started_at)}</p>
          </div>
          <div>
            <p className="text-xs font-semibold text-ink-500">Finalización</p>
            <p className="mt-0.5 font-semibold">
              {formatDate(order.completed_at)}
            </p>
          </div>
        </div>
        {bom === undefined ? null : (
          <p className="mt-4 border-t border-concrete-100 pt-3 text-xs text-ink-500">
            BOM: {bom.code} · versión {bom.version} ·{" "}
            <Link
              className="font-semibold text-ink-700 hover:text-signal-600 hover:underline"
              to={`/manufacturing/boms/${bom.id}`}
            >
              ver receta
            </Link>
          </p>
        )}
      </section>

      <section className="mt-8">
        <h2 className="text-xl font-bold tracking-tight">Consumos de la BOM</h2>
        <p className="mt-0.5 text-xs text-ink-500">
          Estimación por cantidad planificada, incluida la merma. El backend
          redondea cada componente hacia arriba al iniciar la orden.
        </p>
        <div className="mt-3 overflow-x-auto border border-concrete-200 bg-white">
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                <th scope="col" className="px-4 py-2.5">
                  Componente
                </th>
                <th scope="col" className="px-4 py-2.5 text-right">
                  Cantidad / unidad
                </th>
                <th scope="col" className="px-4 py-2.5 text-right">
                  Merma
                </th>
                <th scope="col" className="px-4 py-2.5 text-right">
                  Requerido
                </th>
              </tr>
            </thead>
            <tbody>
              {bom === undefined || bom.items.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-ink-500">
                    {bomQuery.isPending
                      ? "Cargando componentes…"
                      : "La BOM no tiene componentes registrados."}
                  </td>
                </tr>
              ) : (
                bom.items.map((item) => (
                  <tr
                    key={item.id}
                    className="border-b border-concrete-100 last:border-b-0"
                  >
                    <td className="px-4 py-3">
                      {productLabel(
                        products.find(
                          (product) => product.id === item.component_product_id,
                        ),
                        item.component_product_id,
                      )}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatQuantity(item.quantity)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatPercent(item.scrap_percentage)}
                    </td>
                    <td className="px-4 py-3 text-right font-semibold tabular-nums">
                      {requiredUnits(item, order.quantity_to_produce)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {actionError === null || dialog !== null ? null : (
        <p className="mt-4 border border-signal-500/40 bg-signal-100 px-4 py-3 text-sm text-ink-900">
          {actionError}
        </p>
      )}

      <ManufacturingDialog
        open={dialog === "start"}
        title="Iniciar orden de producción"
        subtitle={`Orden ${order.code}`}
        onClose={() => setDialog(null)}
        footer={
          <>
            <button
              type="button"
              onClick={() => setDialog(null)}
              disabled={actionPending}
              className="border border-concrete-200 px-4 py-2 text-sm font-semibold text-ink-700 hover:border-ink-500"
            >
              Cancelar
            </button>
            <button
              type="button"
              onClick={handleStart}
              disabled={actionPending}
              className="bg-signal-500 px-4 py-2 text-sm font-semibold text-white hover:bg-signal-600 disabled:opacity-60"
            >
              {startMutation.isPending ? "Iniciando…" : "Confirmar inicio"}
            </button>
          </>
        }
      >
        <p className="text-sm leading-relaxed text-ink-700">
          Se validará el stock de cada componente en la bodega de origen. Si hay
          suficiente, la orden pasa a <strong>En proceso</strong> y se descuentan
          los insumos de la BOM.
        </p>
        <p className="mt-3 border border-clay-600 bg-clay-100 px-4 py-3 text-xs leading-relaxed text-clay-600">
          Si algún componente tiene déficit, la operación se rechaza sin
          descuentos parciales.
        </p>
      </ManufacturingDialog>

      <ManufacturingDialog
        open={dialog === "complete"}
        title="Completar orden de producción"
        subtitle={`Orden ${order.code}`}
        onClose={() => setDialog(null)}
        footer={
          <>
            <button
              type="button"
              onClick={() => setDialog(null)}
              disabled={actionPending}
              className="border border-concrete-200 px-4 py-2 text-sm font-semibold text-ink-700 hover:border-ink-500"
            >
              Cancelar
            </button>
            <button
              type="button"
              onClick={handleComplete}
              disabled={actionPending}
              className="bg-signal-500 px-4 py-2 text-sm font-semibold text-white hover:bg-signal-600 disabled:opacity-60"
            >
              {completeMutation.isPending ? "Completando…" : "Confirmar cierre"}
            </button>
          </>
        }
      >
        {validationError === null ? null : (
          <p className="mb-4 border border-signal-500/40 bg-signal-100 px-3 py-2 text-sm text-ink-900">
            {validationError}
          </p>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label
              className="mb-1.5 block text-xs font-semibold text-ink-700"
              htmlFor="mfg-complete-quantity"
            >
              Cantidad producida *
            </label>
            <input
              id="mfg-complete-quantity"
              inputMode="decimal"
              className="w-full border border-concrete-200 bg-white px-3 py-2 text-sm focus:border-signal-500 focus:outline-none"
              value={completeQuantity}
              onChange={(event) => setCompleteQuantity(event.target.value)}
            />
          </div>
          <div>
            <label
              className="mb-1.5 block text-xs font-semibold text-ink-700"
              htmlFor="mfg-complete-hours"
            >
              Horas reales
            </label>
            <input
              id="mfg-complete-hours"
              inputMode="decimal"
              className="w-full border border-concrete-200 bg-white px-3 py-2 text-sm focus:border-signal-500 focus:outline-none"
              value={completeHours}
              onChange={(event) => setCompleteHours(event.target.value)}
            />
          </div>
        </div>
        <p className="mt-4 border border-concrete-200 bg-concrete-50 px-4 py-3 text-xs leading-relaxed text-ink-700">
          El backend registra el ingreso de producto terminado, calcula costes
          con el consumo real y las horas del centro, publica el asiento
          contable y cierra la orden. Si algo falla, se revierte todo.
        </p>
      </ManufacturingDialog>

      <ManufacturingDialog
        open={dialog === "cancel"}
        title="Cancelar orden de producción"
        subtitle={`Orden ${order.code}`}
        onClose={() => setDialog(null)}
        footer={
          <>
            <button
              type="button"
              onClick={() => setDialog(null)}
              disabled={actionPending}
              className="border border-concrete-200 px-4 py-2 text-sm font-semibold text-ink-700 hover:border-ink-500"
            >
              Volver
            </button>
            <button
              type="button"
              onClick={handleCancel}
              disabled={actionPending}
              className="bg-signal-500 px-4 py-2 text-sm font-semibold text-white hover:bg-signal-600 disabled:opacity-60"
            >
              {cancelMutation.isPending ? "Cancelando…" : "Confirmar cancelación"}
            </button>
          </>
        }
      >
        <p className="text-sm leading-relaxed text-ink-700">
          La orden pasará a <strong>Cancelada</strong> y no podrá reabrirse.
        </p>
        {order.status === "IN_PROGRESS" ? (
          <p className="mt-3 border border-clay-600 bg-clay-100 px-4 py-3 text-xs leading-relaxed text-clay-600">
            Como ya estaba en curso, se revertirán atómicamente los consumos de
            insumos registrados al iniciar.
          </p>
        ) : null}
      </ManufacturingDialog>
    </div>
  );
}
