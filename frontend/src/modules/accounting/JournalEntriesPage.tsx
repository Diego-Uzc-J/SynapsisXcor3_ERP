import { useDeferredValue, useState } from "react";

import { useAuth, canWriteModule } from "../../store/authStore";
import AccountingDialog from "./AccountingDialog";
import AccountingTabs from "./AccountingTabs";
import { JournalStatusBadge } from "./AccountingStatusBadge";
import {
  JOURNAL_ENTRY_STATUSES,
  type JournalEntryFilters,
  type JournalEntryStatus,
} from "./types";
import {
  JOURNAL_STATUS_HINTS,
  JOURNAL_STATUS_LABELS,
} from "./constants";
import { errorMessage } from "./errors";
import { formatDate, formatDateTime, formatMoney, toCents } from "./format";
import {
  useJournalEntries,
  usePostJournalEntry,
  useReverseJournalEntry,
  useVoidJournalEntry,
} from "./hooks";
import type { JournalEntry } from "./types";
import JournalEntryForm from "./JournalEntryForm";

const PAGE_SIZE = 15;

type StatusFilter = JournalEntryStatus | "all";
type Feedback = { tone: "success" | "error"; text: string; entryId?: number };
type ConfirmAction = { entry: JournalEntry; action: "void" | "reverse" };

function totalDebit(entry: JournalEntry): number {
  return entry.items.reduce((total, item) => total + toCents(item.debit), 0);
}

export default function JournalEntriesPage() {
  const { user } = useAuth();
  const canWrite = canWriteModule(user, "accounting");

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [search, setSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(0);
  const [formOpen, setFormOpen] = useState(false);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [confirming, setConfirming] = useState<ConfirmAction | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  const deferredSearch = useDeferredValue(search.trim());

  const filters: JournalEntryFilters = {
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  };
  if (deferredSearch !== "") {
    filters.code = deferredSearch;
  }
  if (statusFilter !== "all") {
    filters.status = statusFilter;
  }
  if (dateFrom !== "") {
    filters.date_from = dateFrom;
  }
  if (dateTo !== "") {
    filters.date_to = dateTo;
  }

  const entriesQuery = useJournalEntries(filters);
  const postMutation = usePostJournalEntry();
  const voidMutation = useVoidJournalEntry();
  const reverseMutation = useReverseJournalEntry();

  const entries = entriesQuery.data ?? [];
  const drafts = entries.filter((entry) => entry.status === "DRAFT").length;
  const posted = entries.filter((entry) => entry.status === "POSTED").length;
  const voided = entries.filter((entry) => entry.status === "VOID").length;
  const hasFilters =
    deferredSearch !== "" || statusFilter !== "all" || dateFrom !== "" || dateTo !== "";

  function resetFilters() {
    setSearch("");
    setStatusFilter("all");
    setDateFrom("");
    setDateTo("");
  }

  function toggleLines(entryId: number) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(entryId)) {
        next.delete(entryId);
      } else {
        next.add(entryId);
      }
      return next;
    });
  }

  function handlePost(entryId: number) {
    setFeedback(null);
    postMutation.mutate(entryId, {
      onSuccess: (result) =>
        setFeedback({
          tone: "success",
          text: `Asiento ${result.code} contabilizado: débitos y créditos por ${formatMoney(result.total_debit)}.`,
        }),
      onError: (error) =>
        setFeedback({
          tone: "error",
          text: errorMessage(error) ?? "No se pudo contabilizar el asiento.",
        }),
    });
  }

  function handleConfirmAction() {
    if (confirming === null) {
      return;
    }
    const { entry, action } = confirming;
    const mutation = action === "void" ? voidMutation : reverseMutation;
    mutation.mutate(entry.id, {
      onSuccess: () => {
        setFeedback({
          tone: "success",
          text:
            action === "void"
              ? `Borrador ${entry.code} anulado.`
              : `Reversión de ${entry.code} contabilizada correctamente.`,
        });
        setConfirming(null);
      },
      onError: (error) => {
        setFeedback({
          tone: "error",
          text: errorMessage(error) ?? "No se pudo completar la acción.",
        });
        setConfirming(null);
      },
    });
  }

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <header className="flex flex-col gap-6 border-b-2 border-ink-950 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
            Registro de partida doble
          </p>
          <h1 className="mt-2 text-4xl font-extrabold tracking-tight sm:text-5xl">
            Libro diario
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-700">
            Comprobantes en borrador, contabilizados y anulados. Solo los asientos{" "}
            <strong>POSTED</strong> afectan los saldos y los reportes financieros.
          </p>
        </div>
        {canWrite ? (
          <button
            type="button"
            onClick={() => setFormOpen(true)}
            className="inline-flex shrink-0 items-center justify-center gap-2 bg-signal-500 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-signal-600"
          >
            <span aria-hidden="true" className="text-lg leading-none">+</span>
            Nuevo asiento
          </button>
        ) : null}
      </header>

      <AccountingTabs />

      <dl className="mt-6 grid grid-cols-2 gap-px border border-concrete-200 bg-concrete-200 sm:grid-cols-4">
        <div className="bg-white px-4 py-3">
          <dt className="text-xs font-semibold text-ink-500">Asientos en la página</dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums">{entries.length}</dd>
        </div>
        <div className="bg-white px-4 py-3">
          <dt className="text-xs font-semibold text-ink-500">Borradores</dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums text-clay-600">{drafts}</dd>
        </div>
        <div className="bg-white px-4 py-3">
          <dt className="text-xs font-semibold text-ink-500">Contabilizados</dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums text-pine-600">{posted}</dd>
        </div>
        <div className="bg-white px-4 py-3">
          <dt className="text-xs font-semibold text-ink-500">Anulados</dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums text-concrete-400">{voided}</dd>
        </div>
      </dl>

      {feedback === null ? null : (
        <div
          role={feedback.tone === "error" ? "alert" : "status"}
          className={[
            "mt-5 flex flex-wrap items-start justify-between gap-4 border px-4 py-3 text-sm font-medium",
            feedback.tone === "error"
              ? "border-signal-500/40 bg-signal-100 text-signal-600"
              : "border-pine-600/30 bg-pine-100 text-pine-600",
          ].join(" ")}
        >
          <p>{feedback.text}</p>
          <div className="flex items-center gap-3">
            {feedback.entryId !== undefined && canWrite ? (
              <button
                type="button"
                onClick={() => {
                  const id = feedback.entryId;
                  if (id !== undefined) {
                    handlePost(id);
                  }
                }}
                className="border border-pine-600 px-3 py-1 text-xs font-semibold hover:bg-pine-600 hover:text-white"
              >
                Contabilizar ahora
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => setFeedback(null)}
              aria-label="Cerrar aviso"
              className="text-base leading-none"
            >
              ×
            </button>
          </div>
        </div>
      )}

      <div className="flex flex-col gap-3 py-5">
        <div
          role="group"
          aria-label="Filtrar asientos por estado"
          className="flex flex-wrap gap-1.5"
        >
          <button
            type="button"
            aria-pressed={statusFilter === "all"}
            onClick={() => setStatusFilter("all")}
            className={[
              "border px-3 py-1.5 text-xs font-semibold transition-colors",
              statusFilter === "all"
                ? "border-ink-950 bg-ink-950 text-concrete-50"
                : "border-concrete-200 bg-white text-ink-700 hover:border-ink-950",
            ].join(" ")}
          >
            Todos
          </button>
          {JOURNAL_ENTRY_STATUSES.map((status) => (
            <button
              key={status}
              type="button"
              aria-pressed={statusFilter === status}
              title={JOURNAL_STATUS_HINTS[status]}
              onClick={() => setStatusFilter(status)}
              className={[
                "border px-3 py-1.5 text-xs font-semibold transition-colors",
                statusFilter === status
                  ? "border-ink-950 bg-ink-950 text-concrete-50"
                  : "border-concrete-200 bg-white text-ink-700 hover:border-ink-950",
              ].join(" ")}
            >
              {JOURNAL_STATUS_LABELS[status]}
            </button>
          ))}
        </div>

        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-1 flex-col gap-2 sm:flex-row">
            <div className="flex border border-concrete-200 bg-white focus-within:border-ink-950">
              <label className="sr-only" htmlFor="journal-search">
                Buscar asientos por código
              </label>
              <input
                id="journal-search"
                type="search"
                value={search}
                onChange={(event) => setSearch(event.currentTarget.value)}
                placeholder="Buscar por código (ASI-…)"
                className="min-w-0 flex-1 px-3 py-2 text-sm placeholder:text-concrete-400 focus:outline-none"
              />
            </div>
            <label className="sr-only" htmlFor="journal-date-from">
              Fecha inicial
            </label>
            <input
              id="journal-date-from"
              type="date"
              value={dateFrom}
              onChange={(event) => setDateFrom(event.currentTarget.value)}
              className="border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-700"
            />
            <label className="sr-only" htmlFor="journal-date-to">
              Fecha final
            </label>
            <input
              id="journal-date-to"
              type="date"
              value={dateTo}
              onChange={(event) => setDateTo(event.currentTarget.value)}
              className="border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-700"
            />
          </div>
          <p className="text-xs text-ink-500" aria-live="polite">
            {entries.length} asiento{entries.length === 1 ? "" : "s"} en esta página
            {entriesQuery.isFetching ? " · actualizando" : ""}
          </p>
        </div>
        {hasFilters ? (
          <button
            type="button"
            onClick={resetFilters}
            className="w-fit border border-concrete-200 px-3 py-1.5 text-xs font-semibold text-ink-700 hover:border-ink-950"
          >
            Limpiar filtros
          </button>
        ) : null}
      </div>

      {entriesQuery.error !== null ? (
        <div className="border border-signal-500/40 bg-signal-100 px-5 py-6">
          <p className="text-sm font-semibold text-signal-600">
            No se pudo cargar el libro diario.
          </p>
          <p className="mt-1 text-sm text-ink-700">{entriesQuery.error.message}</p>
          <button
            type="button"
            onClick={() => void entriesQuery.refetch()}
            className="mt-4 border border-signal-500 px-3 py-1.5 text-sm font-semibold text-signal-600 hover:bg-signal-500 hover:text-white"
          >
            Reintentar
          </button>
        </div>
      ) : entriesQuery.isPending ? (
        <div className="border border-concrete-200 bg-white">
          {[0, 1, 2, 3, 4].map((row) => (
            <div
              key={row}
              className="flex items-center gap-6 border-b border-concrete-100 px-4 py-4 last:border-b-0"
            >
              <div className="h-4 w-1/5 animate-pulse bg-concrete-100" />
              <div className="h-4 w-1/3 animate-pulse bg-concrete-100" />
              <div className="h-4 w-1/6 animate-pulse bg-concrete-100" />
            </div>
          ))}
        </div>
      ) : entries.length === 0 ? (
        <div className="border border-dashed border-concrete-200 bg-white px-6 py-16 text-center">
          <p className="text-lg font-semibold">
            {hasFilters
              ? "No hay asientos que coincidan con los filtros."
              : "Todavía no hay asientos contables."}
          </p>
          <p className="mx-auto mt-2 max-w-sm text-sm text-ink-500">
            {hasFilters
              ? "Cambia el estado, el código o el rango de fechas para ver otros asientos."
              : "Los asientos se crean como borrador y se contabilizan cuando partida doble cuadra."}
          </p>
          {hasFilters ? (
            <button
              type="button"
              onClick={resetFilters}
              className="mt-5 border border-ink-950 px-4 py-2 text-sm font-semibold hover:bg-ink-950 hover:text-concrete-50"
            >
              Limpiar filtros
            </button>
          ) : canWrite ? (
            <button
              type="button"
              onClick={() => setFormOpen(true)}
              className="mt-5 border border-ink-950 px-4 py-2 text-sm font-semibold hover:bg-ink-950 hover:text-concrete-50"
            >
              Crear el primer asiento
            </button>
          ) : null}
        </div>
      ) : (
        <div className="border border-concrete-200 bg-white">
          <div className="relative overflow-x-auto">
            <table className="w-full min-w-[1060px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                  <th scope="col" className="px-4 py-3">Comprobante</th>
                  <th scope="col" className="px-4 py-3">Fecha</th>
                  <th scope="col" className="px-4 py-3">Glosa</th>
                  <th scope="col" className="px-4 py-3 text-right">Total débito</th>
                  <th scope="col" className="px-4 py-3">Estado</th>
                  <th scope="col" className="px-4 py-3">Registro</th>
                  <th scope="col" className="px-4 py-3 text-right">
                    <span className="sr-only">Acciones</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <FragmentEntry
                    key={entry.id}
                    entry={entry}
                    canWrite={canWrite}
                    expanded={expanded.has(entry.id)}
                    onToggle={() => toggleLines(entry.id)}
                    onPost={() => handlePost(entry.id)}
                    onVoid={() => setConfirming({ entry, action: "void" })}
                    onReverse={() => setConfirming({ entry, action: "reverse" })}
                    pending={
                      (postMutation.isPending && postMutation.variables === entry.id) ||
                      (voidMutation.isPending && voidMutation.variables === entry.id) ||
                      (reverseMutation.isPending && reverseMutation.variables === entry.id)
                    }
                  />
                ))}
              </tbody>
            </table>
          </div>

          <footer className="flex items-center justify-between gap-4 border-t border-concrete-200 px-4 py-3 text-sm">
            <p className="text-xs text-ink-500">Página {page + 1}</p>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={page === 0}
                onClick={() => setPage((current) => Math.max(0, current - 1))}
                className="border border-concrete-200 px-3 py-1.5 text-xs font-semibold text-ink-700 hover:border-ink-950 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Anterior
              </button>
              <button
                type="button"
                disabled={entries.length < PAGE_SIZE}
                onClick={() => setPage((current) => current + 1)}
                className="border border-concrete-200 px-3 py-1.5 text-xs font-semibold text-ink-700 hover:border-ink-950 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Siguiente
              </button>
            </div>
          </footer>
        </div>
      )}

      <JournalEntryForm
        open={formOpen}
        onClose={() => setFormOpen(false)}
        onCreated={(entry) => {
          setFormOpen(false);
          if (entry.status === "DRAFT") {
            setFeedback({
              tone: "success",
              text: `Borrador ${entry.code} guardado con ${entry.items.length} líneas.`,
              entryId: entry.id,
            });
          } else {
            setFeedback({
              tone: "success",
              text: `Asiento ${entry.code} registrado.`,
            });
          }
        }}
      />

      <AccountingDialog
        open={confirming !== null}
        title={confirming?.action === "reverse" ? "Revertir asiento" : "Anular borrador"}
        subtitle={confirming === null ? undefined : `${confirming.entry.code} · ${confirming.entry.description}`}
        onClose={() => setConfirming(null)}
        footer={
          <>
            <button
              type="button"
              onClick={() => setConfirming(null)}
              className="border border-concrete-200 px-4 py-2 text-sm font-semibold text-ink-700 hover:border-ink-950"
            >
              Cancelar
            </button>
            <button
              type="button"
              onClick={handleConfirmAction}
              disabled={voidMutation.isPending || reverseMutation.isPending}
              className="bg-signal-500 px-4 py-2 text-sm font-semibold text-white hover:bg-signal-600 disabled:opacity-60"
            >
              {voidMutation.isPending || reverseMutation.isPending
                ? "Procesando…"
                : confirming?.action === "reverse"
                  ? "Revertir"
                  : "Anular"}
            </button>
          </>
        }
      >
        <p className="text-sm leading-relaxed text-ink-700">
          {confirming?.action === "reverse"
            ? "Se creará y publicará un comprobante de reversión trazable que invierte los movimientos del asiento contabilizado."
            : "El borrador pasará a estado VOID y podrá consultarse, pero no afectará saldos ni reportes."}
        </p>
      </AccountingDialog>
    </div>
  );
}

interface FragmentEntryProps {
  entry: JournalEntry;
  canWrite: boolean;
  expanded: boolean;
  pending: boolean;
  onToggle: () => void;
  onPost: () => void;
  onVoid: () => void;
  onReverse: () => void;
}

function FragmentEntry({
  entry,
  canWrite,
  expanded,
  pending,
  onToggle,
  onPost,
  onVoid,
  onReverse,
}: FragmentEntryProps) {
  return (
    <>
      <tr className="border-b border-concrete-100 hover:bg-concrete-50">
        <td className="border-l-2 border-transparent px-4 py-3 font-semibold tabular-nums">
          {entry.code}
          {entry.reference_document === null ? null : (
            <span className="mt-0.5 block text-xs font-normal text-ink-500">
              {entry.reference_document}
            </span>
          )}
        </td>
        <td className="px-4 py-3 text-xs text-ink-700">{formatDate(entry.entry_date)}</td>
        <td className="px-4 py-3">
          <span className="block max-w-[320px] truncate font-medium" title={entry.description}>
            {entry.description}
          </span>
          <span className="mt-0.5 block text-xs text-ink-500">
            {entry.items.length} línea{entry.items.length === 1 ? "" : "s"}
          </span>
        </td>
        <td className="px-4 py-3 text-right font-semibold tabular-nums">
          {formatMoney(totalDebit(entry) / 100)}
        </td>
        <td className="px-4 py-3">
          <JournalStatusBadge status={entry.status} />
          {entry.posted_at === null ? null : (
            <span className="mt-1 block text-[0.6875rem] text-ink-500">
              {formatDateTime(entry.posted_at)}
            </span>
          )}
        </td>
        <td className="px-4 py-3 text-xs text-ink-500">{entry.created_by ?? "—"}</td>
        <td className="px-4 py-3">
          <div className="flex flex-wrap justify-end gap-2">
            <button
              type="button"
              onClick={onToggle}
              aria-expanded={expanded}
              className="border border-concrete-200 px-2 py-1 text-xs font-semibold text-ink-700 hover:border-ink-950"
            >
              {expanded ? "Ocultar líneas" : "Ver líneas"}
            </button>
            {canWrite && entry.status === "DRAFT" ? (
              <>
                <button
                  type="button"
                  onClick={onPost}
                  disabled={pending}
                  className="border border-pine-600 px-2 py-1 text-xs font-semibold text-pine-600 hover:bg-pine-600 hover:text-white disabled:opacity-50"
                >
                  Contabilizar
                </button>
                <button
                  type="button"
                  onClick={onVoid}
                  disabled={pending}
                  className="border border-concrete-200 px-2 py-1 text-xs font-semibold text-ink-500 hover:border-signal-500 hover:text-signal-600 disabled:opacity-50"
                >
                  Anular
                </button>
              </>
            ) : null}
            {canWrite && entry.status === "POSTED" ? (
              <button
                type="button"
                onClick={onReverse}
                disabled={pending}
                className="border border-concrete-200 px-2 py-1 text-xs font-semibold text-ink-700 hover:border-ink-950 disabled:opacity-50"
              >
                Reversar
              </button>
            ) : null}
          </div>
        </td>
      </tr>
      {expanded ? (
        <tr className="border-b border-concrete-200 bg-concrete-50">
          <td colSpan={7} className="px-4 py-3">
            <table className="w-full border-collapse text-left text-xs">
              <thead>
                <tr className="text-ink-500">
                  <th scope="col" className="px-2 py-1">#</th>
                  <th scope="col" className="px-2 py-1">Cuenta</th>
                  <th scope="col" className="px-2 py-1">Glosa</th>
                  <th scope="col" className="px-2 py-1 text-right">Débito</th>
                  <th scope="col" className="px-2 py-1 text-right">Crédito</th>
                </tr>
              </thead>
              <tbody>
                {entry.items.map((item, index) => (
                  <tr key={item.id} className="border-t border-concrete-200">
                    <td className="px-2 py-1.5 tabular-nums text-ink-500">{index + 1}</td>
                    <td className="px-2 py-1.5 font-semibold tabular-nums">#{item.account_id}</td>
                    <td className="px-2 py-1.5 text-ink-700">{item.description ?? "—"}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{formatMoney(item.debit)}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{formatMoney(item.credit)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </td>
        </tr>
      ) : null}
    </>
  );
}
