import { useDeferredValue, useEffect, useState } from "react";

import { canWriteModule, useAuth } from "../../store/authStore";
import AccountingTabs from "./AccountingTabs";
import { BalanceStatusBadge } from "./AccountingStatusBadge";
import { BALANCE_STATUS_HINTS, BALANCE_STATUS_LABELS } from "./constants";
import { formatCents, formatDate, formatDateTime, formatMoney, toCents } from "./format";
import PaymentForm from "./PaymentForm";
import type { PaymentTarget } from "./PaymentForm";
import { usePayables, usePayments, useReceivables } from "./hooks";
import { ACCOUNT_BALANCE_STATUSES } from "./types";
import type {
  AccountBalanceStatus,
  AccountPayable,
  AccountReceivable,
  PayableFilters,
  PaymentRecord,
  ReceivableFilters,
} from "./types";

const PAGE_SIZE = 15;

type LedgerKind = "receivable" | "payable";
type StatusFilter = AccountBalanceStatus | "all";
type Feedback = { tone: "success" | "error"; text: string };
type LedgerRow = AccountReceivable | AccountPayable;

function isReceivable(row: LedgerRow): row is AccountReceivable {
  return "customer_id" in row;
}

function balanceCents(row: LedgerRow): number {
  return Math.max(0, toCents(row.total_amount) - toCents(row.paid_amount));
}

function titleFor(row: LedgerRow): string {
  if (isReceivable(row)) {
    return row.invoice_id === null ? `CxC #${row.id}` : `Factura #${row.invoice_id}`;
  }
  return row.bill_reference.trim() === "" ? `CxP #${row.id}` : row.bill_reference;
}

function subtitleFor(row: LedgerRow): string {
  return isReceivable(row)
    ? `Cliente #${row.customer_id}`
    : `Proveedor #${row.supplier_id}`;
}

function targetFor(row: LedgerRow, kind: LedgerKind): PaymentTarget {
  return {
    kind,
    id: row.id,
    title: titleFor(row),
    subtitle: subtitleFor(row),
    total: row.total_amount,
    paid: row.paid_amount,
    balanceCents: balanceCents(row),
  };
}

function paymentSubject(record: PaymentRecord, kind: LedgerKind): string {
  const id = kind === "receivable" ? record.receivable_id : record.payable_id;
  return `${kind === "receivable" ? "CxC" : "CxP"} #${id ?? "—"}`;
}

export default function ReceivablesPayablesPage() {
  const { user } = useAuth();
  const canWrite = canWriteModule(user, "accounting");

  const [kind, setKind] = useState<LedgerKind>("receivable");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [thirdParty, setThirdParty] = useState("");
  const [dueFrom, setDueFrom] = useState("");
  const [dueTo, setDueTo] = useState("");
  const [page, setPage] = useState(0);
  const [paymentTarget, setPaymentTarget] = useState<PaymentTarget | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  const deferredThirdParty = useDeferredValue(thirdParty.trim());

  const thirdPartyValid =
    deferredThirdParty === "" || /^\d+$/.test(deferredThirdParty);
  const dateRangeValid =
    dueFrom === "" || dueTo === "" || dueFrom <= dueTo;
  const validationMessage = !thirdPartyValid
    ? "El ID del tercero debe ser un número entero (por ejemplo, 12)."
    : !dateRangeValid
      ? "La fecha de vencimiento inicial no puede ser posterior a la final."
      : null;

  const pagination = { skip: page * PAGE_SIZE, limit: PAGE_SIZE };
  const receivableFilters: ReceivableFilters = { ...pagination };
  const payableFilters: PayableFilters = { ...pagination };

  if (validationMessage === null) {
    if (statusFilter !== "all") {
      receivableFilters.status = statusFilter;
      payableFilters.status = statusFilter;
    }
    if (deferredThirdParty !== "") {
      receivableFilters.third_party_id = Number(deferredThirdParty);
      payableFilters.third_party_id = Number(deferredThirdParty);
    }
    if (dueFrom !== "") {
      receivableFilters.due_after = dueFrom;
      payableFilters.due_after = dueFrom;
    }
    if (dueTo !== "") {
      receivableFilters.due_before = dueTo;
      payableFilters.due_before = dueTo;
    }
  }

  const ledgerEnabled = validationMessage === null;
  const receivablesQuery = useReceivables(
    receivableFilters,
    kind === "receivable" && ledgerEnabled,
  );
  const payablesQuery = usePayables(
    payableFilters,
    kind === "payable" && ledgerEnabled,
  );
  const paymentsQuery = usePayments({ limit: 200 });

  useEffect(() => {
    setPage(0);
  }, [kind, deferredThirdParty, statusFilter, dueFrom, dueTo]);

  const activeQuery = kind === "receivable" ? receivablesQuery : payablesQuery;
  const rows: LedgerRow[] = activeQuery.data ?? [];
  const balanceTotalCents = rows.reduce(
    (total, row) => total + balanceCents(row),
    0,
  );
  const overdueCount = rows.filter((row) => row.status === "OVERDUE").length;
  const partialCount = rows.filter(
    (row) => row.status === "PARTIALLY_PAID",
  ).length;
  const pendingCount = rows.filter((row) => row.status === "PENDING").length;
  const hasFilters =
    statusFilter !== "all" ||
    thirdParty.trim() !== "" ||
    dueFrom !== "" ||
    dueTo !== "";

  const history = (paymentsQuery.data ?? []).filter((record) =>
    kind === "receivable"
      ? record.receivable_id !== null
      : record.payable_id !== null,
  );
  const recentHistory = history.slice(0, 6);

  function resetFilters() {
    setStatusFilter("all");
    setThirdParty("");
    setDueFrom("");
    setDueTo("");
  }

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <header className="flex flex-col gap-6 border-b-2 border-ink-950 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
            Gestión de cartera
          </p>
          <h1 className="mt-2 text-4xl font-extrabold tracking-tight sm:text-5xl">
            Cuentas por cobrar y pagar
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-700">
            Saldos, vencimientos y abonos de CxC/CxP. Cada pago genera su
            movimiento contable y actualiza los reportes financieros.
          </p>
        </div>
        <div
          aria-live="polite"
          className="border border-concrete-200 bg-white px-4 py-2 text-xs text-ink-500"
        >
          {kind === "receivable" ? "Cartera por cobrar" : "Cartera por pagar"}
          {activeQuery.isFetching ? " · actualizando" : ""}
        </div>
      </header>

      <AccountingTabs />

      <div
        role="tablist"
        aria-label="Tipo de cartera"
        className="mt-6 flex flex-wrap gap-2 border-b border-concrete-200 pb-2"
      >
        <button
          type="button"
          role="tab"
          aria-selected={kind === "receivable"}
          onClick={() => setKind("receivable")}
          className={[
            "px-4 py-2 text-sm font-semibold transition-colors",
            kind === "receivable"
              ? "bg-ink-950 text-concrete-50"
              : "border border-concrete-200 bg-white text-ink-700 hover:border-ink-950",
          ].join(" ")}
        >
          Cuentas por cobrar (CxC)
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={kind === "payable"}
          onClick={() => setKind("payable")}
          className={[
            "px-4 py-2 text-sm font-semibold transition-colors",
            kind === "payable"
              ? "bg-ink-950 text-concrete-50"
              : "border border-concrete-200 bg-white text-ink-700 hover:border-ink-950",
          ].join(" ")}
        >
          Cuentas por pagar (CxP)
        </button>
      </div>

      <dl className="mt-6 grid grid-cols-2 gap-px border border-concrete-200 bg-concrete-200 sm:grid-cols-4">
        <div className="bg-white px-4 py-3">
          <dt className="text-xs font-semibold text-ink-500">Saldo en la página</dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums text-signal-600">
            {formatCents(balanceTotalCents)}
          </dd>
        </div>
        <div className="bg-white px-4 py-3">
          <dt className="text-xs font-semibold text-ink-500">Vencidas</dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums">{overdueCount}</dd>
        </div>
        <div className="bg-white px-4 py-3">
          <dt className="text-xs font-semibold text-ink-500">Pago parcial</dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums text-clay-600">
            {partialCount}
          </dd>
        </div>
        <div className="bg-white px-4 py-3">
          <dt className="text-xs font-semibold text-ink-500">Pendientes</dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums">{pendingCount}</dd>
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
        <div
          role="group"
          aria-label="Filtrar cartera por estado"
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
          {ACCOUNT_BALANCE_STATUSES.map((status) => (
            <button
              key={status}
              type="button"
              aria-pressed={statusFilter === status}
              title={BALANCE_STATUS_HINTS[status]}
              onClick={() => setStatusFilter(status)}
              className={[
                "border px-3 py-1.5 text-xs font-semibold transition-colors",
                statusFilter === status
                  ? "border-ink-950 bg-ink-950 text-concrete-50"
                  : "border-concrete-200 bg-white text-ink-700 hover:border-ink-950",
              ].join(" ")}
            >
              {BALANCE_STATUS_LABELS[status]}
            </button>
          ))}
        </div>

        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-1 flex-col gap-2 sm:flex-row">
            <div className="flex border border-concrete-200 bg-white focus-within:border-ink-950">
              <label className="sr-only" htmlFor="ledger-third-party">
                ID del tercero
              </label>
              <input
                id="ledger-third-party"
                inputMode="numeric"
                value={thirdParty}
                onChange={(event) => setThirdParty(event.currentTarget.value)}
                placeholder={
                  kind === "receivable" ? "ID de cliente" : "ID de proveedor"
                }
                className="min-w-0 flex-1 px-3 py-2 text-sm placeholder:text-concrete-400 focus:outline-none"
              />
            </div>
            <label className="sr-only" htmlFor="ledger-due-from">
              Vencimiento desde
            </label>
            <input
              id="ledger-due-from"
              type="date"
              value={dueFrom}
              onChange={(event) => setDueFrom(event.currentTarget.value)}
              className="border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-700"
            />
            <label className="sr-only" htmlFor="ledger-due-to">
              Vencimiento hasta
            </label>
            <input
              id="ledger-due-to"
              type="date"
              value={dueTo}
              onChange={(event) => setDueTo(event.currentTarget.value)}
              className="border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-700"
            />
          </div>
          <p className="text-xs text-ink-500" aria-live="polite">
            {rows.length} registro{rows.length === 1 ? "" : "s"} en esta página
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
        {validationMessage === null ? null : (
          <p role="alert" className="border border-signal-500/40 bg-signal-100 px-3 py-2 text-sm text-signal-600">
            {validationMessage} Corrígelo para consultar la cartera.
          </p>
        )}
      </div>

      {validationMessage !== null ? null : activeQuery.error !== null ? (
        <div className="border border-signal-500/40 bg-signal-100 px-5 py-6">
          <p className="text-sm font-semibold text-signal-600">
            No se pudo cargar la cartera.
          </p>
          <p className="mt-1 text-sm text-ink-700">{activeQuery.error.message}</p>
          <button
            type="button"
            onClick={() => void activeQuery.refetch()}
            className="mt-4 border border-signal-500 px-3 py-1.5 text-sm font-semibold text-signal-600 hover:bg-signal-500 hover:text-white"
          >
            Reintentar
          </button>
        </div>
      ) : activeQuery.isPending ? (
        <div className="border border-concrete-200 bg-white">
          {[0, 1, 2, 3, 4].map((row) => (
            <div
              key={row}
              className="flex items-center gap-6 border-b border-concrete-100 px-4 py-4 last:border-b-0"
            >
              <div className="h-4 w-1/5 animate-pulse bg-concrete-100" />
              <div className="h-4 w-1/4 animate-pulse bg-concrete-100" />
              <div className="h-4 w-1/6 animate-pulse bg-concrete-100" />
            </div>
          ))}
        </div>
      ) : rows.length === 0 ? (
        <div className="border border-dashed border-concrete-200 bg-white px-6 py-16 text-center">
          <p className="text-lg font-semibold">
            {hasFilters
              ? "No hay registros que coincidan con los filtros."
              : "Todavía no hay movimientos en esta cartera."}
          </p>
          <p className="mx-auto mt-2 max-w-sm text-sm text-ink-500">
            {hasFilters
              ? "Cambia el estado, el tercero o el vencimiento para ver otros registros."
              : "Las facturas de venta y compra alimentan estas carteras al contabilizarse."}
          </p>
          {hasFilters ? (
            <button
              type="button"
              onClick={resetFilters}
              className="mt-5 border border-ink-950 px-4 py-2 text-sm font-semibold hover:bg-ink-950 hover:text-concrete-50"
            >
              Limpiar filtros
            </button>
          ) : null}
        </div>
      ) : (
        <div className="border border-concrete-200 bg-white">
          <div className="relative overflow-x-auto">
            <table className="w-full min-w-[1040px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                  <th scope="col" className="px-4 py-3">
                    Documento
                  </th>
                  <th scope="col" className="px-4 py-3">Tercero</th>
                  <th scope="col" className="px-4 py-3">Vencimiento</th>
                  <th scope="col" className="px-4 py-3 text-right">Total</th>
                  <th scope="col" className="px-4 py-3 text-right">Pagado</th>
                  <th scope="col" className="px-4 py-3 text-right">Saldo</th>
                  <th scope="col" className="px-4 py-3">Estado</th>
                  <th scope="col" className="px-4 py-3 text-right">
                    <span className="sr-only">Acciones</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.id}
                    className="border-b border-concrete-100 last:border-b-0 hover:bg-concrete-50"
                  >
                    <td className="border-l-2 border-transparent px-4 py-3 font-semibold">
                      {titleFor(row)}
                      <span className="mt-0.5 block text-xs font-normal text-ink-500">
                        #{row.id}
                        {row.journal_entry_id === null
                          ? ""
                          : ` · asiento #${row.journal_entry_id}`}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-ink-700">
                      {subtitleFor(row)}
                    </td>
                    <td className="px-4 py-3 text-xs text-ink-700">
                      {formatDate(row.due_date)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatMoney(row.total_amount)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-ink-500">
                      {formatMoney(row.paid_amount)}
                    </td>
                    <td className="px-4 py-3 text-right font-bold tabular-nums text-signal-600">
                      {formatCents(balanceCents(row))}
                    </td>
                    <td className="px-4 py-3">
                      <BalanceStatusBadge status={row.status} />
                    </td>
                    <td className="px-4 py-3 text-right">
                      {canWrite ? (
                        <button
                          type="button"
                          onClick={() => setPaymentTarget(targetFor(row, kind))}
                          disabled={balanceCents(row) <= 0}
                          className="border border-ink-950 px-2.5 py-1 text-xs font-semibold text-ink-950 hover:bg-ink-950 hover:text-concrete-50 disabled:cursor-not-allowed disabled:border-concrete-200 disabled:text-concrete-400"
                        >
                          {kind === "receivable" ? "Registrar cobro" : "Registrar pago"}
                        </button>
                      ) : (
                        <span className="text-xs text-concrete-400">Solo lectura</span>
                      )}
                    </td>
                  </tr>
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
                disabled={rows.length < PAGE_SIZE}
                onClick={() => setPage((current) => current + 1)}
                className="border border-concrete-200 px-3 py-1.5 text-xs font-semibold text-ink-700 hover:border-ink-950 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Siguiente
              </button>
            </div>
          </footer>
        </div>
      )}

      <section className="mt-10">
        <div className="mb-3 flex items-end justify-between gap-4 border-b border-concrete-200 pb-2">
          <div>
            <h2 className="text-lg font-bold tracking-tight">
              Últimos {kind === "receivable" ? "cobros" : "pagos"}
            </h2>
            <p className="text-xs text-ink-500">
              Traza del asiento contable que respalda cada abono.
            </p>
          </div>
          <p className="text-xs text-ink-500" aria-live="polite">
            {history.length} registro{history.length === 1 ? "" : "s"}
          </p>
        </div>

        {paymentsQuery.error !== null ? (
          <div className="border border-signal-500/40 bg-signal-100 px-4 py-3 text-sm">
            <p className="font-semibold text-signal-600">
              No se pudo cargar el historial de abonos.
            </p>
            <p className="mt-1 text-ink-700">{paymentsQuery.error.message}</p>
            <button
              type="button"
              onClick={() => void paymentsQuery.refetch()}
              className="mt-3 border border-signal-500 px-3 py-1 text-xs font-semibold text-signal-600 hover:bg-signal-500 hover:text-white"
            >
              Reintentar
            </button>
          </div>
        ) : paymentsQuery.isPending ? (
          <div className="border border-concrete-200 bg-white px-4 py-6 text-sm text-ink-500">
            Cargando historial de abonos…
          </div>
        ) : recentHistory.length === 0 ? (
          <div className="border border-dashed border-concrete-200 bg-white px-4 py-8 text-center text-sm text-ink-500">
            Aún no hay abonos registrados en esta cartera.
          </div>
        ) : (
          <div className="border border-concrete-200 bg-white">
            <table className="w-full min-w-[720px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                  <th scope="col" className="px-4 py-2.5">Abono</th>
                  <th scope="col" className="px-4 py-2.5">Cartera</th>
                  <th scope="col" className="px-4 py-2.5">Fecha</th>
                  <th scope="col" className="px-4 py-2.5 text-right">Monto</th>
                  <th scope="col" className="px-4 py-2.5">Referencia</th>
                  <th scope="col" className="px-4 py-2.5">Asiento</th>
                </tr>
              </thead>
              <tbody>
                {recentHistory.map((record) => (
                  <tr
                    key={record.id}
                    className="border-b border-concrete-100 last:border-b-0"
                  >
                    <td className="px-4 py-2.5 font-semibold tabular-nums">#{record.id}</td>
                    <td className="px-4 py-2.5 text-xs text-ink-700">
                      {paymentSubject(record, kind)}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-ink-700">
                      {formatDate(record.payment_date)}
                    </td>
                    <td className="px-4 py-2.5 text-right font-bold tabular-nums">
                      {formatMoney(record.amount)}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-ink-500">
                      {record.reference ?? "—"}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-ink-500">
                      {record.journal_entry_id === null
                        ? "Sin asiento"
                        : `#${record.journal_entry_id}`}
                      <span className="mt-0.5 block text-[0.6875rem]">
                        {formatDateTime(record.created_at)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <PaymentForm
        open={paymentTarget !== null}
        target={paymentTarget}
        onClose={() => setPaymentTarget(null)}
        onDone={(message) => {
          setPaymentTarget(null);
          setFeedback({ tone: "success", text: message });
        }}
      />
    </div>
  );
}
