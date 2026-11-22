import { useDeferredValue, useState } from "react";

import { canWriteModule, useAuth } from "../../store/authStore";
import { errorHint, errorMessage } from "./errors";
import { formatDateTime, formatMoney } from "./format";
import { useUpdateWorkCenter, useWorkCenters } from "./hooks";
import ManufacturingTabs from "./ManufacturingTabs";
import StatusBadge from "./StatusBadge";
import type { WorkCenter } from "./types";
import WorkCenterForm from "./WorkCenterForm";

const PAGE_SIZE = 15;

type ActiveFilter = "all" | "active" | "inactive";
type Feedback = { tone: "success" | "error"; text: string };

export default function WorkCenterList() {
  const { user } = useAuth();
  const canWrite = canWriteModule(user, "manufacturing");

  const [activeFilter, setActiveFilter] = useState<ActiveFilter>("active");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<WorkCenter | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  const deferredSearch = useDeferredValue(search.trim().toLowerCase());
  const query = useWorkCenters({
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
    ...(activeFilter === "all"
      ? {}
      : { is_active: activeFilter === "active" }),
  });
  const updateMutation = useUpdateWorkCenter();
  const centers = query.data ?? [];
  const visible = centers.filter((center) => {
    if (deferredSearch === "") {
      return true;
    }
    return `${center.code} ${center.name}`.toLowerCase().includes(deferredSearch);
  });

  function openCreate() {
    setEditing(null);
    setFeedback(null);
    setFormOpen(true);
  }

  function openEdit(center: WorkCenter) {
    setEditing(center);
    setFeedback(null);
    setFormOpen(true);
  }

  function toggleActive(center: WorkCenter) {
    setFeedback(null);
    updateMutation.mutate(
      {
        workCenterId: center.id,
        payload: { is_active: !center.is_active },
      },
      {
        onSuccess: (updated) => {
          setFeedback({
            tone: "success",
            text: `Centro ${updated.code} ${updated.is_active ? "activado" : "desactivado"}.`,
          });
        },
        onError: (error) => {
          const text = errorMessage(error) ?? "No se pudo actualizar el centro.";
          setFeedback({ tone: "error", text });
        },
      },
    );
  }

  const message = errorMessage(query.error);

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <header className="flex flex-col gap-6 border-b-2 border-ink-950 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
            Operaciones de manufactura
          </p>
          <h1 className="mt-2 text-4xl font-extrabold tracking-tight sm:text-5xl">
            Centros de trabajo
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-700">
            Máquinas y líneas donde se ejecutan las órdenes. Su coste por hora
            determina la mano de obra de cada orden completada.
          </p>
        </div>
        {canWrite ? (
          <button
            type="button"
            onClick={openCreate}
            className="inline-flex shrink-0 items-center justify-center gap-2 bg-signal-500 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-signal-600"
          >
            <span aria-hidden="true" className="text-lg leading-none">
              +
            </span>
            Nuevo centro
          </button>
        ) : null}
      </header>

      <ManufacturingTabs />

      <div className="mt-6 flex flex-wrap gap-3 border border-concrete-200 bg-white p-4">
        <div className="min-w-[220px] flex-1">
          <label
            className="mb-1 block text-xs font-semibold text-ink-700"
            htmlFor="mfg-center-search"
          >
            Buscar en la página
          </label>
          <input
            id="mfg-center-search"
            className="w-full border border-concrete-200 px-3 py-2 text-sm focus:border-signal-500 focus:outline-none"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Código o nombre"
          />
        </div>
        <div className="w-full sm:w-52">
          <label
            className="mb-1 block text-xs font-semibold text-ink-700"
            htmlFor="mfg-center-active"
          >
            Estado
          </label>
          <select
            id="mfg-center-active"
            className="w-full border border-concrete-200 bg-white px-3 py-2 text-sm focus:border-signal-500 focus:outline-none"
            value={activeFilter}
            onChange={(event) => {
              setActiveFilter(event.target.value as ActiveFilter);
              setPage(0);
            }}
          >
            <option value="active">Activos</option>
            <option value="inactive">Inactivos</option>
            <option value="all">Todos</option>
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
                  Centro
                </th>
                <th scope="col" className="px-4 py-2.5 text-right">
                  Coste / hora
                </th>
                <th scope="col" className="px-4 py-2.5">
                  Estado
                </th>
                <th scope="col" className="px-4 py-2.5">
                  Registro
                </th>
                <th scope="col" className="px-4 py-2.5 text-right">
                  Acciones
                </th>
              </tr>
            </thead>
            <tbody>
              {query.isPending ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-ink-500">
                    Cargando centros de trabajo…
                  </td>
                </tr>
              ) : visible.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-ink-500">
                    No hay centros de trabajo para los filtros seleccionados.
                  </td>
                </tr>
              ) : (
                visible.map((center) => (
                  <tr
                    key={center.id}
                    className="border-b border-concrete-100 last:border-b-0"
                  >
                    <td className="px-4 py-3">
                      <span className="font-semibold">{center.code}</span>
                      <p className="text-xs text-ink-500">{center.name}</p>
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatMoney(center.cost_per_hour)}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge
                        label={center.is_active ? "Activo" : "Inactivo"}
                        tone={center.is_active ? "success" : "muted"}
                      />
                    </td>
                    <td className="px-4 py-3 text-xs text-ink-500">
                      {formatDateTime(center.created_at)}
                    </td>
                    <td className="px-4 py-3 text-right text-xs">
                      {canWrite ? (
                        <>
                          <button
                            type="button"
                            onClick={() => openEdit(center)}
                            className="font-semibold text-ink-700 hover:text-signal-600 hover:underline"
                          >
                            Editar
                          </button>
                          <span className="px-2 text-concrete-400">|</span>
                          <button
                            type="button"
                            onClick={() => toggleActive(center)}
                            disabled={updateMutation.isPending}
                            className="font-semibold text-ink-700 hover:text-signal-600 hover:underline disabled:opacity-40"
                          >
                            {center.is_active ? "Desactivar" : "Activar"}
                          </button>
                        </>
                      ) : (
                        <span className="text-ink-500">Solo lectura</span>
                      )}
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
              disabled={centers.length < PAGE_SIZE || query.isPending}
              onClick={() => setPage((current) => current + 1)}
              className="border border-concrete-200 px-3 py-1.5 font-semibold disabled:opacity-40"
            >
              Siguiente
            </button>
          </div>
        </div>
      </div>

      <WorkCenterForm
        open={formOpen}
        center={editing}
        onClose={() => setFormOpen(false)}
        onSaved={(center, mode) => {
          setFormOpen(false);
          setFeedback({
            tone: "success",
            text:
              mode === "created"
                ? `Centro ${center.code} registrado.`
                : `Centro ${center.code} actualizado.`,
          });
        }}
      />
    </div>
  );
}
