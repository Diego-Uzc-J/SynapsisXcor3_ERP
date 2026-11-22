import { useDeferredValue, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { useProducts } from "../../api/inventory";
import type { Product } from "../../api/inventory";
import { canWriteModule, useAuth } from "../../store/authStore";
import {
  ORDER_STATUS_HINTS,
  ORDER_STATUS_LABELS,
  ORDER_STATUS_TONES,
} from "./constants";
import {
  PRODUCTION_ORDER_STATUSES,
  type ProductionOrderStatus,
} from "./types";
import { errorHint, errorMessage } from "./errors";
import { formatDate, formatMoney, formatQuantity } from "./format";
import { useBoms, useProductionOrders } from "./hooks";
import ManufacturingTabs from "./ManufacturingTabs";
import ProductionOrderForm from "./ProductionOrderForm";
import StatusBadge from "./StatusBadge";

const PAGE_SIZE = 15;

type StatusFilter = "all" | ProductionOrderStatus;
type Feedback = { tone: "success" | "error"; text: string };

function bomLabel(code: string, version: number): string {
  return `${code} · v${version}`;
}

function productLabel(product: Product | undefined, productId: number): string {
  return product === undefined
    ? `Producto #${productId}`
    : `${product.sku} · ${product.name}`;
}

export default function ProductionOrderList() {
  const { user } = useAuth();
  const canWrite = canWriteModule(user, "manufacturing");
  const [searchParams] = useSearchParams();

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [bomFilter, setBomFilter] = useState(() => searchParams.get("bom_id") ?? "");
  const [createdDate, setCreatedDate] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [formOpen, setFormOpen] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  const deferredSearch = useDeferredValue(search.trim().toLowerCase());
  const bomsQuery = useBoms({ limit: 200 });
  const productsQuery = useProducts({ limit: 200, is_active: true });

  useEffect(() => {
    const value = searchParams.get("bom_id");
    if (value !== null) {
      setBomFilter(value);
      setPage(0);
    }
  }, [searchParams]);

  const query = useProductionOrders({
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
    ...(statusFilter === "all" ? {} : { status: statusFilter }),
    ...(bomFilter === "" ? {} : { bom_id: Number(bomFilter) }),
    ...(createdDate === "" ? {} : { created_date: createdDate }),
  });

  const orders = query.data ?? [];
  const boms = bomsQuery.data ?? [];
  const products = productsQuery.data ?? [];
  const visible = orders.filter((order) => {
    if (deferredSearch === "") {
      return true;
    }
    return order.code.toLowerCase().includes(deferredSearch);
  });

  const message = errorMessage(query.error);

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <header className="flex flex-col gap-6 border-b-2 border-ink-950 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
            Plan de producción
          </p>
          <h1 className="mt-2 text-4xl font-extrabold tracking-tight sm:text-5xl">
            Órdenes de producción
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-700">
            Planifica, inicia y cierra la transformación de insumos. Los costes y
            los movimientos de inventario se calculan en el servidor.
          </p>
        </div>
        {canWrite ? (
          <button
            type="button"
            onClick={() => {
              setFeedback(null);
              setFormOpen(true);
            }}
            className="inline-flex shrink-0 items-center justify-center gap-2 bg-signal-500 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-signal-600"
          >
            <span aria-hidden="true" className="text-lg leading-none">
              +
            </span>
            Nueva orden
          </button>
        ) : null}
      </header>

      <ManufacturingTabs />

      <div className="mt-6 flex flex-wrap gap-3 border border-concrete-200 bg-white p-4">
        <div className="min-w-[200px] flex-1">
          <label
            className="mb-1 block text-xs font-semibold text-ink-700"
            htmlFor="mfg-order-search"
          >
            Buscar por código
          </label>
          <input
            id="mfg-order-search"
            className="w-full border border-concrete-200 px-3 py-2 text-sm focus:border-signal-500 focus:outline-none"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="OP-2026-0001"
          />
        </div>
        <div className="w-full sm:w-48">
          <label
            className="mb-1 block text-xs font-semibold text-ink-700"
            htmlFor="mfg-order-status"
          >
            Estado
          </label>
          <select
            id="mfg-order-status"
            className="w-full border border-concrete-200 bg-white px-3 py-2 text-sm focus:border-signal-500 focus:outline-none"
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value as StatusFilter);
              setPage(0);
            }}
          >
            <option value="all">Todos</option>
            {PRODUCTION_ORDER_STATUSES.map((status) => (
              <option key={status} value={status}>
                {ORDER_STATUS_LABELS[status]}
              </option>
            ))}
          </select>
        </div>
        <div className="w-full sm:w-56">
          <label
            className="mb-1 block text-xs font-semibold text-ink-700"
            htmlFor="mfg-order-bom-filter"
          >
            BOM
          </label>
          <select
            id="mfg-order-bom-filter"
            className="w-full border border-concrete-200 bg-white px-3 py-2 text-sm focus:border-signal-500 focus:outline-none"
            value={bomFilter}
            onChange={(event) => {
              setBomFilter(event.target.value);
              setPage(0);
            }}
          >
            <option value="">Todas las BOM</option>
            {boms.map((bom) => (
              <option key={bom.id} value={bom.id}>
                {bomLabel(bom.code, bom.version)}
              </option>
            ))}
          </select>
        </div>
        <div className="w-full sm:w-48">
          <label
            className="mb-1 block text-xs font-semibold text-ink-700"
            htmlFor="mfg-order-date"
          >
            Fecha de creación
          </label>
          <input
            id="mfg-order-date"
            type="date"
            className="w-full border border-concrete-200 bg-white px-3 py-2 text-sm focus:border-signal-500 focus:outline-none"
            value={createdDate}
            onChange={(event) => {
              setCreatedDate(event.target.value);
              setPage(0);
            }}
          />
        </div>
      </div>

      {feedback === null ? null : (
        <p className="mt-4 border border-pine-600 bg-pine-100 px-4 py-3 text-sm text-pine-600">
          {feedback.text}
        </p>
      )}

      {message === null ? null : (
        <div className="mt-4 border border-signal-500/40 bg-signal-100 px-4 py-3 text-sm text-ink-900">
          <p className="font-semibold">{message}</p>
          <p className="mt-1 text-xs text-ink-700">{errorHint(message)}</p>
        </div>
      )}

      <div className="mt-5 border border-concrete-200 bg-white">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                <th scope="col" className="px-4 py-2.5">
                  Orden
                </th>
                <th scope="col" className="px-4 py-2.5">
                  Producto / BOM
                </th>
                <th scope="col" className="px-4 py-2.5">
                  Estado
                </th>
                <th scope="col" className="px-4 py-2.5 text-right">
                  Planificada
                </th>
                <th scope="col" className="px-4 py-2.5 text-right">
                  Producida
                </th>
                <th scope="col" className="px-4 py-2.5 text-right">
                  Coste total
                </th>
                <th scope="col" className="px-4 py-2.5 text-right">
                  Coste unit.
                </th>
                <th scope="col" className="px-4 py-2.5">
                  Creada
                </th>
              </tr>
            </thead>
            <tbody>
              {query.isPending ? (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-ink-500">
                    Cargando órdenes de producción…
                  </td>
                </tr>
              ) : visible.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-ink-500">
                    No hay órdenes para los filtros seleccionados.
                  </td>
                </tr>
              ) : (
                visible.map((order) => {
                  const bom = boms.find((item) => item.id === order.bom_id);
                  return (
                    <tr
                      key={order.id}
                      className="border-b border-concrete-100 last:border-b-0"
                    >
                      <td className="px-4 py-3">
                        <Link
                          className="font-semibold text-ink-950 hover:text-signal-600 hover:underline"
                          to={`/manufacturing/orders/${order.id}`}
                        >
                          {order.code}
                        </Link>
                        <p className="text-xs text-ink-500">#{order.id}</p>
                      </td>
                      <td className="px-4 py-3 text-xs text-ink-700">
                        {productLabel(
                          products.find(
                            (product) => product.id === bom?.product_id,
                          ),
                          bom?.product_id ?? 0,
                        )}
                        <p className="text-ink-500">
                          {bom === undefined
                            ? `BOM #${order.bom_id}`
                            : bomLabel(bom.code, bom.version)}
                        </p>
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge
                          label={ORDER_STATUS_LABELS[order.status]}
                          tone={ORDER_STATUS_TONES[order.status]}
                          hint={ORDER_STATUS_HINTS[order.status]}
                        />
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        {formatQuantity(order.quantity_to_produce)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        {formatQuantity(order.quantity_produced)}
                      </td>
                      <td className="px-4 py-3 text-right font-semibold tabular-nums">
                        {formatMoney(order.total_production_cost)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        {formatMoney(order.unit_production_cost)}
                      </td>
                      <td className="px-4 py-3 text-xs text-ink-500">
                        {formatDate(order.created_at.slice(0, 10))}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
        <div className="flex items-center justify-between border-t border-concrete-200 px-4 py-3 text-xs text-ink-500">
          <span>Página {page + 1}</span>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={page === 0 || query.isPending}
              onClick={() => setPage((current) => current - 1)}
              className="border border-concrete-200 px-3 py-1.5 font-semibold disabled:opacity-40"
            >
              Anterior
            </button>
            <button
              type="button"
              disabled={orders.length < PAGE_SIZE || query.isPending}
              onClick={() => setPage((current) => current + 1)}
              className="border border-concrete-200 px-3 py-1.5 font-semibold disabled:opacity-40"
            >
              Siguiente
            </button>
          </div>
        </div>
      </div>

      <ProductionOrderForm
        open={formOpen}
        defaultBomId={bomFilter === "" ? null : Number(bomFilter)}
        onClose={() => setFormOpen(false)}
        onSaved={(order) => {
          setFormOpen(false);
          setFeedback({ tone: "success", text: `Orden ${order.code} creada en estado Planificada.` });
        }}
      />
    </div>
  );
}
