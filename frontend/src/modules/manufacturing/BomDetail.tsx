import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useProducts } from "../../api/inventory";
import type { Product } from "../../api/inventory";
import { canWriteModule, useAuth } from "../../store/authStore";
import { errorHint, errorMessage } from "./errors";
import { formatDate, formatDateTime, formatPercent, formatQuantity } from "./format";
import { useBom, useDeactivateBom } from "./hooks";
import ManufacturingDialog from "./ManufacturingDialog";
import ManufacturingTabs from "./ManufacturingTabs";
import StatusBadge from "./StatusBadge";

type Feedback = { tone: "success" | "error"; text: string };

function productLabel(product: Product | undefined, productId: number): string {
  return product === undefined
    ? `Producto #${productId}`
    : `${product.sku} · ${product.name}`;
}

export default function BomDetail() {
  const { bomId: rawId } = useParams();
  const bomId = Number(rawId);
  const validId = Number.isInteger(bomId) && bomId > 0;

  const { user } = useAuth();
  const canWrite = canWriteModule(user, "manufacturing");
  const bomQuery = useBom(bomId, validId);
  const productsQuery = useProducts({ limit: 200, is_active: true });
  const deactivateMutation = useDeactivateBom();

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  const bom = bomQuery.data;
  const products = productsQuery.data ?? [];
  const message = errorMessage(bomQuery.error);

  function handleDeactivate() {
    if (bom === undefined) {
      return;
    }
    deactivateMutation.mutate(bom.id, {
      onSuccess: (updated) => {
        setConfirmOpen(false);
        setFeedback({
          tone: "success",
          text: `BOM ${updated.code} desactivada correctamente.`,
        });
      },
      onError: (error) => {
        const text = errorMessage(error) ?? "No se pudo desactivar la BOM.";
        setConfirmOpen(false);
        setFeedback({ tone: "error", text });
      },
    });
  }

  if (!validId || message !== null || (!bomQuery.isPending && bom === undefined)) {
    return (
      <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
        <ManufacturingTabs />
        <div className="mt-6 border border-signal-500/40 bg-signal-100 px-5 py-6">
          <h1 className="text-xl font-bold">No se pudo cargar la BOM</h1>
          <p className="mt-1 text-sm text-ink-700">
            {message ?? "El identificador de la lista de materiales no es válido."}
          </p>
          <Link
            className="mt-4 inline-block text-sm font-semibold text-signal-600 hover:underline"
            to="/manufacturing/boms"
          >
            Volver a listas de materiales
          </Link>
        </div>
      </div>
    );
  }

  if (bomQuery.isPending || bom === undefined) {
    return (
      <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
        <ManufacturingTabs />
        <p className="mt-6 border border-concrete-200 bg-white px-4 py-8 text-center text-sm text-ink-500">
          Cargando detalle de la BOM…
        </p>
      </div>
    );
  }

  const deactivationError = errorMessage(deactivateMutation.error);

  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <header className="border-b-2 border-ink-950 pb-6">
        <Link
          className="text-xs font-semibold text-ink-500 hover:text-signal-600 hover:underline"
          to="/manufacturing/boms"
        >
          ← Listas de materiales
        </Link>
        <div className="mt-3 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
              Receta v{bom.version}
            </p>
            <h1 className="mt-2 text-3xl font-extrabold tracking-tight sm:text-4xl">
              {bom.code}
            </h1>
            <p className="mt-1 text-sm text-ink-700">
              {productLabel(
                products.find((product) => product.id === bom.product_id),
                bom.product_id,
              )}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge
              label={bom.is_active ? "Vigente" : "Histórica"}
              tone={bom.is_active ? "success" : "muted"}
              hint={
                bom.is_active
                  ? "Puede usarse para crear nuevas órdenes de producción."
                  : "No puede usarse en nuevas órdenes."
              }
            />
            {bom.is_active ? (
              <Link
                className="bg-signal-500 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-signal-600"
                to={`/manufacturing/orders?bom_id=${bom.id}`}
              >
                Crear orden con esta BOM
              </Link>
            ) : null}
            {canWrite && bom.is_active ? (
              <button
                type="button"
                onClick={() => setConfirmOpen(true)}
                className="border border-concrete-200 px-4 py-2.5 text-sm font-semibold text-ink-700 hover:border-signal-500 hover:text-signal-600"
              >
                Desactivar
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

      {deactivationError === null ? null : (
        <p className="mt-4 border border-signal-500/40 bg-signal-100 px-4 py-3 text-sm text-ink-900">
          {deactivationError}
        </p>
      )}

      <section className="mt-6 grid gap-4 sm:grid-cols-3">
        <div className="border border-concrete-200 bg-white px-4 py-3">
          <p className="text-xs font-semibold text-ink-500">Componentes</p>
          <p className="mt-1 text-2xl font-extrabold tabular-nums">
            {bom.items.length}
          </p>
        </div>
        <div className="border border-concrete-200 bg-white px-4 py-3">
          <p className="text-xs font-semibold text-ink-500">Versión</p>
          <p className="mt-1 text-2xl font-extrabold tabular-nums">
            {bom.version}
          </p>
        </div>
        <div className="border border-concrete-200 bg-white px-4 py-3">
          <p className="text-xs font-semibold text-ink-500">Creada</p>
          <p className="mt-1 text-sm font-semibold">
            {formatDateTime(bom.created_at)}
          </p>
        </div>
      </section>

      {bom.name === null && bom.notes === null ? null : (
        <section className="mt-6 border border-concrete-200 bg-white px-4 py-4 text-sm">
          {bom.name === null ? null : (
            <p className="font-semibold">{bom.name}</p>
          )}
          {bom.notes === null ? null : (
            <p className="mt-1 whitespace-pre-line text-ink-700">{bom.notes}</p>
          )}
        </section>
      )}

      <section className="mt-8">
        <h2 className="text-xl font-bold tracking-tight">Componentes</h2>
        <p className="mt-0.5 text-xs text-ink-500">
          Cantidad requerida por cada unidad del producto final. La merma se
          aplica al iniciar la orden.
        </p>
        <div className="mt-3 overflow-x-auto border border-concrete-200 bg-white">
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                <th scope="col" className="px-4 py-2.5">
                  Insumo
                </th>
                <th scope="col" className="px-4 py-2.5 text-right">
                  Cantidad / unidad
                </th>
                <th scope="col" className="px-4 py-2.5 text-right">
                  Merma
                </th>
              </tr>
            </thead>
            <tbody>
              {bom.items.length === 0 ? (
                <tr>
                  <td colSpan={3} className="px-4 py-8 text-center text-ink-500">
                    Esta receta no tiene componentes; no puede usarse en una orden.
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
                      <p className="text-xs text-ink-500">
                        ID {item.component_product_id} ·{" "}
                        {formatDate(bom.created_at.slice(0, 10))}
                      </p>
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatQuantity(item.quantity)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatPercent(item.scrap_percentage)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <ManufacturingDialog
        open={confirmOpen}
        title="Desactivar BOM"
        subtitle={`Receta ${bom.code}`}
        onClose={() => setConfirmOpen(false)}
        footer={
          <>
            <button
              type="button"
              onClick={() => setConfirmOpen(false)}
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
              {deactivateMutation.isPending ? "Desactivando…" : "Confirmar"}
            </button>
          </>
        }
      >
        <p className="text-sm leading-relaxed text-ink-700">
          La BOM pasará a ser histórica y no podrá seleccionarse en nuevas
          órdenes. Las órdenes existentes conservan su referencia y sus consumos.
        </p>
      </ManufacturingDialog>
    </div>
  );
}
