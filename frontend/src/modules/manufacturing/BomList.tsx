import { useDeferredValue, useState } from "react";
import { Link } from "react-router-dom";

import { useProducts } from "../../api/inventory";
import type { Product } from "../../api/inventory";
import { canWriteModule, useAuth } from "../../store/authStore";
import BomForm from "./BomForm";
import { errorHint, errorMessage } from "./errors";
import { formatDate } from "./format";
import { useBoms, useDeactivateBom } from "./hooks";
import ManufacturingDialog from "./ManufacturingDialog";
import ManufacturingTabs from "./ManufacturingTabs";
import StatusBadge from "./StatusBadge";
import type { Bom } from "./types";

const PAGE_SIZE = 15;

type ActiveFilter = "all" | "active" | "inactive";
type Feedback = { tone: "success" | "error"; text: string };

function productLabel(product: Product | undefined, productId: number): string {
  return product === undefined
    ? `Producto #${productId}`
    : `${product.sku} · ${product.name}`;
}

export default function BomList() {
  const { user } = useAuth();
  const canWrite = canWriteModule(user, "manufacturing");

  const [activeFilter, setActiveFilter] = useState<ActiveFilter>("active");
  const [productFilter, setProductFilter] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [formOpen, setFormOpen] = useState(false);
  const [toDeactivate, setToDeactivate] = useState<Bom | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  const deferredSearch = useDeferredValue(search.trim().toLowerCase());
  const productsQuery = useProducts({ limit: 200, is_active: true });
  const query = useBoms({
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
    ...(activeFilter === "all" ? {} : { is_active: activeFilter === "active" }),
    ...(productFilter === "" ? {} : { product_id: Number(productFilter) }),
  });
  const deactivateMutation = useDeactivateBom();

  const products = productsQuery.data ?? [];
  const boms = query.data ?? [];
  const visible = boms.filter((bom) => {
    if (deferredSearch === "") {
      return true;
    }
    return `${bom.code} ${bom.name ?? ""}`
      .toLowerCase()
      .includes(deferredSearch);
  });

  function handleDeactivate() {
    if (toDeactivate === null) {
      return;
    }
    deactivateMutation.mutate(toDeactivate.id, {
      onSuccess: (updated) => {
        setToDeactivate(null);
        setFeedback({
          tone: "success",
          text: `BOM ${updated.code} desactivada; ya no puede usarse en nuevas órdenes.`,
        });
      },
      onError: (error) => {
        const text = errorMessage(error) ?? "No se pudo desactivar la BOM.";
        setToDeactivate(null);
        setFeedback({ tone: "error", text });
      },
    });
  }

  const message = errorMessage(query.error);

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <header className="flex flex-col gap-6 border-b-2 border-ink-950 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
            Ingeniería de producción
          </p>
          <h1 className="mt-2 text-4xl font-extrabold tracking-tight sm:text-5xl">
            Listas de materiales
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-700">
            Recetas vigentes por producto y versión. Solo puede existir una BOM
            activa por combinación de producto y versión.
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
            Nueva BOM
          </button>
        ) : null}
      </header>

      <ManufacturingTabs />

      <div className="mt-6 flex flex-wrap gap-3 border border-concrete-200 bg-white p-4">
        <div className="min-w-[220px] flex-1">
          <label
            className="mb-1 block text-xs font-semibold text-ink-700"
            htmlFor="mfg-bom-search"
          >
            Buscar en la página
          </label>
          <input
            id="mfg-bom-search"
            className="w-full border border-concrete-200 px-3 py-2 text-sm focus:border-signal-500 focus:outline-none"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Código o descripción"
          />
        </div>
        <div className="w-full sm:w-64">
          <label
            className="mb-1 block text-xs font-semibold text-ink-700"
            htmlFor="mfg-bom-product-filter"
          >
            Producto terminado
          </label>
          <select
            id="mfg-bom-product-filter"
            className="w-full border border-concrete-200 bg-white px-3 py-2 text-sm focus:border-signal-500 focus:outline-none"
            value={productFilter}
            onChange={(event) => {
              setProductFilter(event.target.value);
              setPage(0);
            }}
          >
            <option value="">Todos los productos</option>
            {products.map((product) => (
              <option key={product.id} value={product.id}>
                {product.sku} · {product.name}
              </option>
            ))}
          </select>
        </div>
        <div className="w-full sm:w-40">
          <label
            className="mb-1 block text-xs font-semibold text-ink-700"
            htmlFor="mfg-bom-active"
          >
            Vigencia
          </label>
          <select
            id="mfg-bom-active"
            className="w-full border border-concrete-200 bg-white px-3 py-2 text-sm focus:border-signal-500 focus:outline-none"
            value={activeFilter}
            onChange={(event) => {
              setActiveFilter(event.target.value as ActiveFilter);
              setPage(0);
            }}
          >
            <option value="active">Vigentes</option>
            <option value="inactive">Históricas</option>
            <option value="all">Todas</option>
          </select>
        </div>
      </div>

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
                  Receta
                </th>
                <th scope="col" className="px-4 py-2.5">
                  Producto terminado
                </th>
                <th scope="col" className="px-4 py-2.5">
                  Versión
                </th>
                <th scope="col" className="px-4 py-2.5 text-right">
                  Componentes
                </th>
                <th scope="col" className="px-4 py-2.5">
                  Estado
                </th>
                <th scope="col" className="px-4 py-2.5">
                  Creada
                </th>
                <th scope="col" className="px-4 py-2.5 text-right">
                  Acciones
                </th>
              </tr>
            </thead>
            <tbody>
              {query.isPending ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-ink-500">
                    Cargando listas de materiales…
                  </td>
                </tr>
              ) : visible.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-ink-500">
                    No hay BOM para los filtros seleccionados.
                  </td>
                </tr>
              ) : (
                visible.map((bom) => (
                  <tr
                    key={bom.id}
                    className="border-b border-concrete-100 last:border-b-0"
                  >
                    <td className="px-4 py-3">
                      <Link
                        className="font-semibold text-ink-950 hover:text-signal-600 hover:underline"
                        to={`/manufacturing/boms/${bom.id}`}
                      >
                        {bom.code}
                      </Link>
                      <p className="text-xs text-ink-500">{bom.name ?? "—"}</p>
                    </td>
                    <td className="px-4 py-3 text-xs text-ink-700">
                      {productLabel(
                        products.find((product) => product.id === bom.product_id),
                        bom.product_id,
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs tabular-nums">
                      v{bom.version}
                    </td>
                    <td className="px-4 py-3 text-right text-xs tabular-nums">
                      {bom.items.length}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge
                        label={bom.is_active ? "Vigente" : "Histórica"}
                        tone={bom.is_active ? "success" : "muted"}
                      />
                    </td>
                    <td className="px-4 py-3 text-xs text-ink-500">
                      {formatDate(bom.created_at.slice(0, 10))}
                    </td>
                    <td className="px-4 py-3 text-right text-xs">
                      <Link
                        className="font-semibold text-ink-700 hover:text-signal-600 hover:underline"
                        to={`/manufacturing/boms/${bom.id}`}
                      >
                        Ver detalle
                      </Link>
                      {canWrite && bom.is_active ? (
                        <>
                          <span className="px-2 text-concrete-400">|</span>
                          <button
                            type="button"
                            onClick={() => setToDeactivate(bom)}
                            className="font-semibold text-ink-700 hover:text-signal-600 hover:underline"
                          >
                            Desactivar
                          </button>
                        </>
                      ) : null}
                    </td>
                  </tr>
                ))
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
              disabled={boms.length < PAGE_SIZE || query.isPending}
              onClick={() => setPage((current) => current + 1)}
              className="border border-concrete-200 px-3 py-1.5 font-semibold disabled:opacity-40"
            >
              Siguiente
            </button>
          </div>
        </div>
      </div>

      <BomForm
        open={formOpen}
        onClose={() => setFormOpen(false)}
        onSaved={(bom) => {
          setFormOpen(false);
          setFeedback({
            tone: "success",
            text: `BOM ${bom.code} creada con ${bom.items.length} componentes.`,
          });
        }}
      />

      <ManufacturingDialog
        open={toDeactivate !== null}
        title="Desactivar BOM"
        subtitle={toDeactivate?.code ?? ""}
        onClose={() => setToDeactivate(null)}
        footer={
          <>
            <button
              type="button"
              onClick={() => setToDeactivate(null)}
              disabled={deactivateMutation.isPending}
              className="border border-concrete-200 px-4 py-2 text-sm font-semibold text-ink-700 hover:border-ink-500"
            >
              Cancelar
            </button>
            <button
              type="button"
              onClick={handleDeactivate}
              disabled={deactivateMutation.isPending}
              className="bg-signal-500 px-4 py-2 text-sm font-semibold text-white hover:bg-signal-600 disabled:opacity-60"
            >
              {deactivateMutation.isPending ? "Desactivando…" : "Desactivar"}
            </button>
          </>
        }
      >
        <p className="text-sm leading-relaxed text-ink-700">
          La receta quedará como histórica y no podrá usarse en nuevas órdenes.
          Las órdenes ya creadas conservan su referencia.
        </p>
      </ManufacturingDialog>
    </div>
  );
}
