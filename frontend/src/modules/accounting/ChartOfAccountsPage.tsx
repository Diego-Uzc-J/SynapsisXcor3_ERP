import { useDeferredValue, useEffect, useMemo, useState } from "react";

import { useAuth, canWriteModule } from "../../store/authStore";
import AccountForm from "./AccountForm";
import AccountingDialog from "./AccountingDialog";
import AccountingTabs from "./AccountingTabs";
import { ACCOUNT_TYPE_LABELS } from "./constants";
import { formatDate } from "./format";
import { errorMessage } from "./errors";
import {
  useAccounts,
  useDeactivateAccount,
  useUpdateAccount,
} from "./hooks";
import type { Account, AccountFilters, AccountType } from "./types";
import { ACCOUNT_TYPES } from "./types";

const PAGE_SIZE = 15;

type SearchField = "code" | "name";
type StatusFilter = "all" | "active" | "inactive";
type Feedback = { tone: "success" | "error"; text: string };

function buildDepths(accounts: readonly Account[]): Map<number, number> {
  const byId = new Map(accounts.map((account) => [account.id, account]));
  const depths = new Map<number, number>();
  for (const account of accounts) {
    let depth = 0;
    let parentId = account.parent_id;
    const visited = new Set<number>([account.id]);
    while (parentId !== null && !visited.has(parentId)) {
      visited.add(parentId);
      depth += 1;
      parentId = byId.get(parentId)?.parent_id ?? null;
    }
    depths.set(account.id, depth);
  }
  return depths;
}

export default function ChartOfAccountsPage() {
  const { user } = useAuth();
  const canWrite = canWriteModule(user, "accounting");

  const [searchField, setSearchField] = useState<SearchField>("code");
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<AccountType | "all">("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [page, setPage] = useState(0);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Account | null>(null);
  const [deactivating, setDeactivating] = useState<Account | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  const deferredSearch = useDeferredValue(search.trim());

  const filters: AccountFilters = {
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  };
  if (deferredSearch !== "") {
    if (searchField === "code") {
      filters.code = deferredSearch;
    } else {
      filters.name = deferredSearch;
    }
  }
  if (typeFilter !== "all") {
    filters.account_type = typeFilter;
  }
  if (statusFilter !== "all") {
    filters.is_active = statusFilter === "active";
  }

  const accountsQuery = useAccounts(filters);
  const catalogQuery = useAccounts({ limit: 200 });
  const deactivateMutation = useDeactivateAccount();
  const updateMutation = useUpdateAccount();

  useEffect(() => {
    setPage(0);
  }, [deferredSearch, searchField, typeFilter, statusFilter]);

  const accounts = accountsQuery.data ?? [];
  const allAccounts = catalogQuery.data ?? [];
  const depths = useMemo(() => buildDepths(allAccounts), [allAccounts]);
  const parentById = useMemo(
    () => new Map(allAccounts.map((account) => [account.id, account])),
    [allAccounts],
  );

  const activeCount = accounts.filter((account) => account.is_active).length;
  const typeCount = new Set(accounts.map((account) => account.account_type)).size;
  const hasFilters =
    deferredSearch !== "" || typeFilter !== "all" || statusFilter !== "all";
  const queryError = accountsQuery.error ?? catalogQuery.error;

  function resetFilters() {
    setSearch("");
    setSearchField("code");
    setTypeFilter("all");
    setStatusFilter("all");
  }

  function openCreate() {
    setEditing(null);
    setFormOpen(true);
  }

  function openEdit(account: Account) {
    setEditing(account);
    setFormOpen(true);
  }

  function handleSaved(account: Account, mode: "created" | "updated") {
    setFormOpen(false);
    setFeedback({
      tone: "success",
      text:
        mode === "created"
          ? `Cuenta ${account.code} creada correctamente.`
          : `Cuenta ${account.code} actualizada.`,
    });
  }

  function confirmDeactivation() {
    if (deactivating === null) {
      return;
    }
    const target = deactivating;
    deactivateMutation.mutate(target.id, {
      onSuccess: () => {
        setDeactivating(null);
        setFeedback({
          tone: "success",
          text: `Cuenta ${target.code} desactivada; su historial se conserva.`,
        });
      },
      onError: (error) =>
        setFeedback({
          tone: "error",
          text: errorMessage(error) ?? "No se pudo desactivar la cuenta.",
        }),
    });
  }

  function reactivate(account: Account) {
    updateMutation.mutate(
      { accountId: account.id, payload: { is_active: true } },
      {
        onSuccess: (updated) =>
          setFeedback({
            tone: "success",
            text: `Cuenta ${updated.code} reactivada para nuevos movimientos.`,
          }),
        onError: (error) =>
          setFeedback({
            tone: "error",
            text: errorMessage(error) ?? "No se pudo reactivar la cuenta.",
          }),
      },
    );
  }

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <header className="flex flex-col gap-6 border-b-2 border-ink-950 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
            Finanzas y contabilidad
          </p>
          <h1 className="mt-2 text-4xl font-extrabold tracking-tight sm:text-5xl">
            Plan de cuentas
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-700">
            Catálogo jerárquico del PUC. Las cuentas con movimientos se desactivan
            en lugar de borrarse para preservar el historial contable.
          </p>
        </div>
        {canWrite ? (
          <button
            type="button"
            onClick={openCreate}
            className="inline-flex shrink-0 items-center justify-center gap-2 bg-signal-500 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-signal-600"
          >
            <span aria-hidden="true" className="text-lg leading-none">+</span>
            Nueva cuenta
          </button>
        ) : null}
      </header>

      <AccountingTabs />

      <dl className="mt-6 grid grid-cols-2 gap-px border border-concrete-200 bg-concrete-200 sm:grid-cols-4">
        <div className="bg-white px-4 py-3">
          <dt className="text-xs font-semibold text-ink-500">Cuentas en la página</dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums">{accounts.length}</dd>
        </div>
        <div className="bg-white px-4 py-3">
          <dt className="text-xs font-semibold text-ink-500">Activas</dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums text-pine-600">{activeCount}</dd>
        </div>
        <div className="bg-white px-4 py-3">
          <dt className="text-xs font-semibold text-ink-500">Inactivas</dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums">{accounts.length - activeCount}</dd>
        </div>
        <div className="bg-white px-4 py-3">
          <dt className="text-xs font-semibold text-ink-500">Tipos representados</dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums">{typeCount}</dd>
        </div>
      </dl>

      {feedback === null ? null : (
        <div
          role={feedback.tone === "error" ? "alert" : "status"}
          className={[
            "mt-5 flex items-start justify-between gap-4 border px-4 py-3 text-sm font-medium",
            feedback.tone === "error"
              ? "border-signal-500/40 bg-signal-100 text-signal-600"
              : "border-pine-600/30 bg-pine-100 text-pine-600",
          ].join(" ")}
        >
          <p>{feedback.text}</p>
          <button
            type="button"
            onClick={() => setFeedback(null)}
            aria-label="Cerrar aviso"
            className="text-base leading-none"
          >
            ×
          </button>
        </div>
      )}

      <div className="flex flex-col gap-3 py-5">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-1 flex-col gap-2 sm:flex-row">
            <div className="flex border border-concrete-200 bg-white focus-within:border-ink-950">
              <label className="sr-only" htmlFor="account-search">
                Buscar cuentas
              </label>
              <select
                aria-label="Buscar por campo"
                value={searchField}
                onChange={(event) => setSearchField(event.currentTarget.value as SearchField)}
                className="border-r border-concrete-200 bg-transparent px-2 py-2 text-xs font-semibold text-ink-700"
              >
                <option value="code">Código</option>
                <option value="name">Nombre</option>
              </select>
              <input
                id="account-search"
                type="search"
                value={search}
                onChange={(event) => setSearch(event.currentTarget.value)}
                placeholder={searchField === "code" ? "Buscar por código" : "Buscar por nombre"}
                className="min-w-0 flex-1 px-3 py-2 text-sm placeholder:text-concrete-400 focus:outline-none"
              />
            </div>
            <label className="sr-only" htmlFor="account-type-filter">
              Filtrar por tipo
            </label>
            <select
              id="account-type-filter"
              value={typeFilter}
              onChange={(event) => setTypeFilter(event.currentTarget.value as AccountType | "all")}
              className="border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-700"
            >
              <option value="all">Todos los tipos</option>
              {ACCOUNT_TYPES.map((type) => (
                <option key={type} value={type}>
                  {ACCOUNT_TYPE_LABELS[type]}
                </option>
              ))}
            </select>
            <label className="sr-only" htmlFor="account-status-filter">
              Filtrar por estado
            </label>
            <select
              id="account-status-filter"
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.currentTarget.value as StatusFilter)}
              className="border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-700"
            >
              <option value="all">Todos los estados</option>
              <option value="active">Solo activas</option>
              <option value="inactive">Solo inactivas</option>
            </select>
          </div>
          <p className="text-xs text-ink-500" aria-live="polite">
            Página {page + 1}
            {accountsQuery.isFetching ? " · actualizando" : ""}
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

      {queryError !== null ? (
        <div className="border border-signal-500/40 bg-signal-100 px-5 py-6">
          <p className="text-sm font-semibold text-signal-600">
            No se pudo cargar el plan de cuentas.
          </p>
          <p className="mt-1 text-sm text-ink-700">{queryError.message}</p>
          <button
            type="button"
            onClick={() => {
              void accountsQuery.refetch();
              void catalogQuery.refetch();
            }}
            className="mt-4 border border-signal-500 px-3 py-1.5 text-sm font-semibold text-signal-600 hover:bg-signal-500 hover:text-white"
          >
            Reintentar
          </button>
        </div>
      ) : accountsQuery.isPending ? (
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
      ) : accounts.length === 0 ? (
        <div className="border border-dashed border-concrete-200 bg-white px-6 py-16 text-center">
          <p className="text-lg font-semibold">
            {hasFilters
              ? "No hay cuentas que coincidan con los filtros."
              : "Todavía no hay cuentas en el plan contable."}
          </p>
          <p className="mx-auto mt-2 max-w-sm text-sm text-ink-500">
            {hasFilters
              ? "Cambia el código, el tipo o el estado para ver otras cuentas."
              : "Registra las cuentas del PUC antes de crear asientos contables."}
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
              onClick={openCreate}
              className="mt-5 border border-ink-950 px-4 py-2 text-sm font-semibold hover:bg-ink-950 hover:text-concrete-50"
            >
              Crear la primera cuenta
            </button>
          ) : null}
        </div>
      ) : (
        <div className="border border-concrete-200 bg-white">
          <div className="relative overflow-x-auto">
            <table className="w-full min-w-[940px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                  <th scope="col" className="px-4 py-3">Código</th>
                  <th scope="col" className="px-4 py-3">Cuenta</th>
                  <th scope="col" className="px-4 py-3">Tipo</th>
                  <th scope="col" className="px-4 py-3">Cuenta madre</th>
                  <th scope="col" className="px-4 py-3">Alta</th>
                  <th scope="col" className="px-4 py-3">Estado</th>
                  <th scope="col" className="px-4 py-3 text-right">
                    <span className="sr-only">Acciones</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((account) => {
                  const depth = depths.get(account.id) ?? 0;
                  const parent = account.parent_id === null
                    ? undefined
                    : parentById.get(account.parent_id);
                  return (
                    <tr
                      key={account.id}
                      className="border-b border-concrete-100 last:border-b-0 hover:bg-concrete-50"
                    >
                      <td className="border-l-2 border-transparent px-4 py-3 font-semibold tabular-nums">
                        {account.code}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className="block font-medium text-ink-950"
                          style={{ paddingLeft: `${depth * 1.25}rem` }}
                        >
                          {depth > 0 ? <span aria-hidden="true" className="mr-1 text-concrete-400">↳</span> : null}
                          {account.name}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-ink-700">
                        {ACCOUNT_TYPE_LABELS[account.account_type]}
                      </td>
                      <td className="px-4 py-3 text-xs tabular-nums text-ink-500">
                        {parent === undefined ? "—" : `${parent.code} · ${parent.name}`}
                      </td>
                      <td className="px-4 py-3 text-xs text-ink-500">
                        {formatDate(account.created_at.slice(0, 10))}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={[
                            "inline-flex px-2 py-1 text-xs font-semibold",
                            account.is_active
                              ? "bg-pine-100 text-pine-600"
                              : "bg-concrete-100 text-concrete-400",
                          ].join(" ")}
                        >
                          {account.is_active ? "Activa" : "Inactiva"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        {canWrite ? (
                          <div className="flex justify-end gap-2">
                            <button
                              type="button"
                              onClick={() => openEdit(account)}
                              className="border border-concrete-200 px-2 py-1 text-xs font-semibold text-ink-700 hover:border-ink-950"
                            >
                              Editar
                            </button>
                            {account.is_active ? (
                              <button
                                type="button"
                                onClick={() => setDeactivating(account)}
                                className="border border-concrete-200 px-2 py-1 text-xs font-semibold text-signal-600 hover:border-signal-500"
                              >
                                Desactivar
                              </button>
                            ) : (
                              <button
                                type="button"
                                onClick={() => reactivate(account)}
                                disabled={updateMutation.isPending}
                                className="border border-concrete-200 px-2 py-1 text-xs font-semibold text-pine-600 hover:border-pine-600 disabled:opacity-50"
                              >
                                Activar
                              </button>
                            )}
                          </div>
                        ) : (
                          <span className="text-xs text-concrete-400">Solo lectura</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <footer className="flex items-center justify-between gap-4 border-t border-concrete-200 px-4 py-3 text-sm">
            <p className="text-xs text-ink-500">
              {accounts.length} cuenta{accounts.length === 1 ? "" : "s"} en esta página ·{" "}
              {activeCount} activas
            </p>
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
                disabled={accounts.length < PAGE_SIZE}
                onClick={() => setPage((current) => current + 1)}
                className="border border-concrete-200 px-3 py-1.5 text-xs font-semibold text-ink-700 hover:border-ink-950 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Siguiente
              </button>
            </div>
          </footer>
        </div>
      )}

      <AccountForm
        open={formOpen}
        account={editing}
        accounts={allAccounts}
        onClose={() => setFormOpen(false)}
        onSaved={handleSaved}
      />

      <AccountingDialog
        open={deactivating !== null}
        title="Desactivar cuenta contable"
        subtitle={deactivating === null ? undefined : `${deactivating.code} · ${deactivating.name}`}
        onClose={() => setDeactivating(null)}
        footer={
          <>
            <button
              type="button"
              onClick={() => setDeactivating(null)}
              className="border border-concrete-200 px-4 py-2 text-sm font-semibold text-ink-700 hover:border-ink-950"
            >
              Cancelar
            </button>
            <button
              type="button"
              onClick={confirmDeactivation}
              disabled={deactivateMutation.isPending}
              className="bg-signal-500 px-4 py-2 text-sm font-semibold text-white hover:bg-signal-600 disabled:opacity-60"
            >
              {deactivateMutation.isPending ? "Desactivando…" : "Desactivar"}
            </button>
          </>
        }
      >
        <p className="text-sm leading-relaxed text-ink-700">
          La cuenta conservará su historial de movimientos, pero no podrá usarse
          en nuevos asientos. Esta es la única baja permitida por la regla de
          inmutabilidad contable.
        </p>
        {deactivateMutation.error !== null ? (
          <p role="alert" className="mt-3 border border-signal-500/40 bg-signal-100 px-3 py-2 text-sm text-signal-600">
            {errorMessage(deactivateMutation.error)}
          </p>
        ) : null}
      </AccountingDialog>
    </div>
  );
}
