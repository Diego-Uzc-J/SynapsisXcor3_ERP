import { useState } from "react";

import AccountingTabs from "./AccountingTabs";
import { ACCOUNT_TYPE_LABELS, REPORT_LABELS } from "./constants";
import type { ReportKey } from "./constants";
import { formatMoney, toCents } from "./format";
import { useBalanceSheet, useIncomeStatement, useTrialBalance } from "./hooks";
import type {
  BalanceSheetResponse,
  IncomeStatementResponse,
  ReportAccountLine,
  ReportFilters,
  TrialBalanceResponse,
} from "./types";

const REPORT_KEYS: readonly ReportKey[] = ["trial", "balance", "income"];

type StatTone = "default" | "positive" | "negative";

function Stat({
  label,
  value,
  note,
  tone = "default",
}: {
  label: string;
  value: string;
  note?: string;
  tone?: StatTone;
}) {
  const valueClass =
    tone === "positive"
      ? "text-pine-600"
      : tone === "negative"
        ? "text-signal-600"
        : "text-ink-950";
  return (
    <div className="bg-white px-4 py-3">
      <dt className="text-xs font-semibold text-ink-500">{label}</dt>
      <dd className={`mt-1 text-2xl font-extrabold tabular-nums ${valueClass}`}>
        {value}
      </dd>
      {note === undefined ? null : (
        <p className="mt-1 text-[0.6875rem] leading-relaxed text-ink-500">{note}</p>
      )}
    </div>
  );
}

function EmptyLines({ label }: { label: string }) {
  return (
    <p className="border border-dashed border-concrete-200 bg-white px-4 py-6 text-center text-sm text-ink-500">
      {label}
    </p>
  );
}

function LinesTable({
  lines,
  emptyLabel,
}: {
  lines: readonly ReportAccountLine[];
  emptyLabel: string;
}) {
  if (lines.length === 0) {
    return <EmptyLines label={emptyLabel} />;
  }
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full min-w-[480px] border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
            <th scope="col" className="px-4 py-2">Código</th>
            <th scope="col" className="px-4 py-2">Cuenta</th>
            <th scope="col" className="px-4 py-2 text-right">Saldo</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => (
            <tr
              key={line.account_id}
              className="border-b border-concrete-100 last:border-b-0"
            >
              <td className="px-4 py-2 font-semibold tabular-nums">{line.code}</td>
              <td className="px-4 py-2 text-ink-700">{line.name}</td>
              <td className="px-4 py-2 text-right font-semibold tabular-nums">
                {formatMoney(line.balance)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReportSection({
  title,
  lines,
  total,
}: {
  title: string;
  lines: readonly ReportAccountLine[];
  total: string;
}) {
  return (
    <section className="border border-concrete-200 bg-white">
      <header className="flex items-center justify-between gap-3 border-b border-concrete-200 bg-concrete-50 px-4 py-2.5">
        <h3 className="text-sm font-bold tracking-tight">{title}</h3>
        <p className="text-xs text-ink-500">
          {lines.length} cuenta{lines.length === 1 ? "" : "s"}
        </p>
      </header>
      <LinesTable
        lines={lines}
        emptyLabel={`No hay cuentas de ${title.toLowerCase()} con saldo en el periodo.`}
      />
      <footer className="flex items-center justify-between gap-3 border-t border-concrete-200 px-4 py-2.5 text-sm">
        <span className="text-xs font-semibold text-ink-500">Total {title.toLowerCase()}</span>
        <span className="font-bold tabular-nums">{formatMoney(total)}</span>
      </footer>
    </section>
  );
}

function TrialBalanceReport({ data }: { data: TrialBalanceResponse }) {
  const differenceCents = toCents(data.total_debit) - toCents(data.total_credit);
  const balanced = differenceCents === 0;
  return (
    <div className="space-y-5">
      <dl className="grid grid-cols-1 gap-px border border-concrete-200 bg-concrete-200 sm:grid-cols-3">
        <Stat label="Total débito" value={formatMoney(data.total_debit)} />
        <Stat label="Total crédito" value={formatMoney(data.total_credit)} />
        <Stat
          label="Diferencia (débito − crédito)"
          value={formatMoney(differenceCents / 100)}
          note={balanced ? "La partida doble cuadra." : "Revisa los asientos PUBLICADOS del periodo."}
          tone={balanced ? "positive" : "negative"}
        />
      </dl>

      {data.lines.length === 0 ? (
        <EmptyLines label="No hay cuentas con movimientos contabilizados en el periodo seleccionado." />
      ) : (
        <div className="border border-concrete-200 bg-white">
          <div className="relative overflow-x-auto">
            <table className="w-full min-w-[720px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                  <th scope="col" className="px-4 py-2.5">Código</th>
                  <th scope="col" className="px-4 py-2.5">Cuenta</th>
                  <th scope="col" className="px-4 py-2.5">Tipo</th>
                  <th scope="col" className="px-4 py-2.5 text-right">Débito</th>
                  <th scope="col" className="px-4 py-2.5 text-right">Crédito</th>
                  <th scope="col" className="px-4 py-2.5 text-right">Saldo</th>
                </tr>
              </thead>
              <tbody>
                {data.lines.map((line) => (
                  <tr
                    key={line.account_id}
                    className="border-b border-concrete-100 last:border-b-0"
                  >
                    <td className="px-4 py-2.5 font-semibold tabular-nums">{line.code}</td>
                    <td className="px-4 py-2.5 text-ink-700">{line.name}</td>
                    <td className="px-4 py-2.5 text-xs text-ink-500">
                      {ACCOUNT_TYPE_LABELS[line.account_type]}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums">
                      {formatMoney(line.debit)}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums">
                      {formatMoney(line.credit)}
                    </td>
                    <td className="px-4 py-2.5 text-right font-bold tabular-nums">
                      {formatMoney(line.balance)}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-ink-950 bg-concrete-50 font-bold">
                  <td scope="row" colSpan={3} className="px-4 py-2.5 text-xs uppercase tracking-wide">
                    Totales
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums">
                    {formatMoney(data.total_debit)}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums">
                    {formatMoney(data.total_credit)}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums">
                    {formatMoney(differenceCents / 100)}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function BalanceSheetReport({ data }: { data: BalanceSheetResponse }) {
  const differenceCents = toCents(data.difference);
  const balanced = differenceCents === 0;
  return (
    <div className="space-y-5">
      <dl className="grid grid-cols-1 gap-px border border-concrete-200 bg-concrete-200 sm:grid-cols-3">
        <Stat label="Total activos" value={formatMoney(data.total_assets)} />
        <Stat
          label="Pasivo + patrimonio"
          value={formatMoney(data.total_liabilities_and_equity)}
        />
        <Stat
          label="Diferencia de la ecuación"
          value={formatMoney(data.difference)}
          note={balanced ? "Activo = pasivo + patrimonio." : "La ecuación contable no cuadra."}
          tone={balanced ? "positive" : "negative"}
        />
      </dl>

      <div className="grid gap-5 xl:grid-cols-2">
        <ReportSection title="Activos" lines={data.assets} total={data.total_assets} />
        <div className="space-y-5">
          <ReportSection
            title="Pasivos"
            lines={data.liabilities}
            total={data.total_liabilities}
          />
          <ReportSection title="Patrimonio" lines={data.equity} total={data.total_equity} />
        </div>
      </div>
    </div>
  );
}

function IncomeStatementReport({ data }: { data: IncomeStatementResponse }) {
  const netCents = toCents(data.net_income);
  return (
    <div className="space-y-5">
      <dl className="grid grid-cols-1 gap-px border border-concrete-200 bg-concrete-200 sm:grid-cols-3">
        <Stat label="Total ingresos" value={formatMoney(data.total_revenue)} />
        <Stat label="Total gastos" value={formatMoney(data.total_expenses)} />
        <Stat
          label={netCents < 0 ? "Pérdida neta" : "Utilidad neta"}
          value={formatMoney(data.net_income)}
          note="Ingresos menos gastos contabilizados en el periodo."
          tone={netCents < 0 ? "negative" : "positive"}
        />
      </dl>

      <div className="grid gap-5 xl:grid-cols-2">
        <ReportSection title="Ingresos" lines={data.revenues} total={data.total_revenue} />
        <ReportSection title="Gastos" lines={data.expenses} total={data.total_expenses} />
      </div>
    </div>
  );
}

export default function FinancialReportsPage() {
  const [report, setReport] = useState<ReportKey>("trial");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [periodName, setPeriodName] = useState("");

  const rangeValid = dateFrom === "" || dateTo === "" || dateFrom <= dateTo;
  const filters: ReportFilters = {};
  if (dateFrom !== "") {
    filters.date_from = dateFrom;
  }
  if (dateTo !== "") {
    filters.date_to = dateTo;
  }
  if (periodName.trim() !== "") {
    filters.period_name = periodName.trim();
  }

  const trialQuery = useTrialBalance(filters, rangeValid && report === "trial");
  const balanceQuery = useBalanceSheet(filters, rangeValid && report === "balance");
  const incomeQuery = useIncomeStatement(filters, rangeValid && report === "income");
  const activeQuery =
    report === "trial"
      ? trialQuery
      : report === "balance"
        ? balanceQuery
        : incomeQuery;

  function resetFilters() {
    setDateFrom("");
    setDateTo("");
    setPeriodName("");
  }

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <header className="border-b-2 border-ink-950 pb-6">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
          Información financiera
        </p>
        <h1 className="mt-2 text-4xl font-extrabold tracking-tight sm:text-5xl">
          Reportes financieros
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-700">
          Los tres reportes se calculan únicamente con asientos{" "}
          <strong>POSTED</strong>. Borradores y anulados no alteran los saldos.
        </p>
      </header>

      <AccountingTabs />

      <div
        role="tablist"
        aria-label="Tipo de reporte financiero"
        className="mt-6 flex flex-wrap gap-2 border-b border-concrete-200 pb-2"
      >
        {REPORT_KEYS.map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={report === key}
            onClick={() => setReport(key)}
            className={[
              "px-4 py-2 text-sm font-semibold transition-colors",
              report === key
                ? "bg-ink-950 text-concrete-50"
                : "border border-concrete-200 bg-white text-ink-700 hover:border-ink-950",
            ].join(" ")}
          >
            {REPORT_LABELS[key]}
          </button>
        ))}
      </div>

      <div className="mt-6 border border-concrete-200 bg-white p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div className="grid flex-1 gap-3 sm:grid-cols-3">
            <div>
              <label
                className="mb-1.5 block text-xs font-semibold text-ink-700"
                htmlFor="report-date-from"
              >
                Desde
              </label>
              <input
                id="report-date-from"
                type="date"
                value={dateFrom}
                onChange={(event) => setDateFrom(event.currentTarget.value)}
                className="w-full border border-concrete-200 px-3 py-2 text-sm text-ink-950"
              />
            </div>
            <div>
              <label
                className="mb-1.5 block text-xs font-semibold text-ink-700"
                htmlFor="report-date-to"
              >
                Hasta
              </label>
              <input
                id="report-date-to"
                type="date"
                value={dateTo}
                onChange={(event) => setDateTo(event.currentTarget.value)}
                className="w-full border border-concrete-200 px-3 py-2 text-sm text-ink-950"
              />
            </div>
            <div>
              <label
                className="mb-1.5 block text-xs font-semibold text-ink-700"
                htmlFor="report-period"
              >
                Periodo contable (opcional)
              </label>
              <input
                id="report-period"
                value={periodName}
                onChange={(event) => setPeriodName(event.currentTarget.value)}
                placeholder="2026-11"
                maxLength={50}
                className="w-full border border-concrete-200 px-3 py-2 text-sm text-ink-950 placeholder:text-concrete-400"
              />
            </div>
          </div>
          <div className="flex items-center gap-3">
            <p className="text-xs text-ink-500" aria-live="polite">
              {activeQuery.isFetching ? "Actualizando…" : "Datos al día"}
            </p>
            <button
              type="button"
              onClick={resetFilters}
              className="border border-concrete-200 px-3 py-2 text-xs font-semibold text-ink-700 hover:border-ink-950"
            >
              Limpiar filtros
            </button>
          </div>
        </div>
        <p className="mt-3 text-xs leading-relaxed text-ink-500">
          Si indicas un periodo, sus fechas se intersectan con el rango. Vacío
          muestra todos los asientos contabilizados.
        </p>
      </div>

      <section className="mt-6" aria-live="polite">
        {rangeValid ? null : (
          <div role="alert" className="border border-signal-500/40 bg-signal-100 px-4 py-3 text-sm text-signal-600">
            La fecha inicial no puede ser posterior a la fecha final. Corrígele
            para generar el reporte.
          </div>
        )}

        {!rangeValid ? null : activeQuery.error !== null ? (
          <div className="border border-signal-500/40 bg-signal-100 px-5 py-6">
            <p className="text-sm font-semibold text-signal-600">
              No se pudo generar {REPORT_LABELS[report].toLowerCase()}.
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
            <div className="flex items-center gap-4 border-b border-concrete-100 px-4 py-3">
              <div className="h-4 w-1/4 animate-pulse bg-concrete-100" />
              <div className="h-4 w-1/4 animate-pulse bg-concrete-100" />
              <div className="h-4 w-1/4 animate-pulse bg-concrete-100" />
            </div>
            {[0, 1, 2, 3, 4, 5].map((row) => (
              <div
                key={row}
                className="flex items-center gap-6 border-b border-concrete-100 px-4 py-3 last:border-b-0"
              >
                <div className="h-4 w-1/5 animate-pulse bg-concrete-100" />
                <div className="h-4 w-1/3 animate-pulse bg-concrete-100" />
                <div className="h-4 w-1/6 animate-pulse bg-concrete-100" />
              </div>
            ))}
          </div>
        ) : report === "trial" ? (
          trialQuery.data === undefined ? null : (
            <TrialBalanceReport data={trialQuery.data} />
          )
        ) : report === "balance" ? (
          balanceQuery.data === undefined ? null : (
            <BalanceSheetReport data={balanceQuery.data} />
          )
        ) : incomeQuery.data === undefined ? null : (
          <IncomeStatementReport data={incomeQuery.data} />
        )}
      </section>
    </div>
  );
}
