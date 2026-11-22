import { useState } from "react";
import { Link } from "react-router-dom";

import { canWriteModule, useAuth } from "../../store/authStore";
import {
  PAYROLL_STATUS_HINTS,
  PAYROLL_STATUS_LABELS,
  PAYROLL_STATUS_TONES,
} from "./constants";
import { errorMessage } from "./errors";
import { formatDate, formatDateTime, formatMoney } from "./format";
import { usePayrollRuns } from "./hooks";
import HrTabs from "./HrTabs";
import PayrollRunForm from "./PayrollRunForm";
import StatusBadge from "./StatusBadge";
import { PAYROLL_STATUSES } from "./types";
import type { PayrollRun, PayrollRunStatus } from "./types";

type StatusFilter = PayrollRunStatus | "all";
type AdjustmentFilter = "all" | "regular" | "adjustment";
type Feedback = { tone: "success" | "error"; text: string };

export default function PayrollRunsPage() {
  const { user } = useAuth();
  const canWrite = canWriteModule(user, "hr");

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [adjustmentFilter, setAdjustmentFilter] =
    useState<AdjustmentFilter>("all");
  const [formOpen, setFormOpen] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  const filters = {
    limit: 100,
    ...(statusFilter === "all" ? {} : { status: statusFilter }),
    ...(adjustmentFilter === "all"
      ? {}
      : { is_adjustment: adjustmentFilter === "adjustment" }),
  };
  const payrollsQuery = usePayrollRuns(filters);
  const runs = payrollsQuery.data ?? [];
  const message = errorMessage(payrollsQuery.error);

  function handleCreated(run: PayrollRun) {
    setFormOpen(false);
    setFeedback({
      tone: "success",
      text: `Periodo ${run.code} generado en borrador con sus desprendibles.`,
    });
  }

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <header className="flex flex-col gap-6 border-b-2 border-ink-950 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
            Liquidación de personal
          </p>
          <h1 className="mt-2 text-4xl font-extrabold tracking-tight sm:text-5xl">
            Nómina
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-700">
            Genera periodos en borrador, revisa el desprendible de cada empleado
            y aprueba la liquidación con su asiento contable.
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
            Generar nómina
          </button>
        ) : null}
      </header>

      <HrTabs />

      <div className="mt-6 flex flex-wrap gap-4 border border-concrete-200 bg-white p-4">
        <div className="w-full sm:w-56">
          <label
            className="mb-1 block text-xs font-semibold text-ink-700"
            htmlFor="hr-payroll-status"
          >
            Estado
          </label>
          <select
            id="hr-payroll-status"
            className="w-full border border-concrete-200 bg-white px-3 py-2 text-sm focus:border-signal-500 focus:outline-none"
            value={statusFilter}
            onChange={(event) =>
              setStatusFilter(event.target.value as StatusFilter)
            }
          >
            <option value="all">Todos</option>
            {PAYROLL_STATUSES.map((status) => (
              <option key={status} value={status}>
                {PAYROLL_STATUS_LABELS[status]}
              </option>
            ))}
          </select>
        </div>
        <div className="w-full sm:w-56">
          <label
            className="mb-1 block text-xs font-semibold text-ink-700"
            htmlFor="hr-payroll-adjustment"
          >
            Tipo
          </label>
          <select
            id="hr-payroll-adjustment"
            className="w-full border border-concrete-200 bg-white px-3 py-2 text-sm focus:border-signal-500 focus:outline-none"
            value={adjustmentFilter}
            onChange={(event) =>
              setAdjustmentFilter(event.target.value as AdjustmentFilter)
            }
          >
            <option value="all">Todas</option>
            <option value="regular">Ordinarias</option>
            <option value="adjustment">Ajustes</option>
          </select>
        </div>
      </div>

      {feedback === null ? null : (
        <p className="mt-4 border border-pine-500 bg-pine-50 px-4 py-3 text-sm text-pine-700">
          {feedback.text}
        </p>
      )}

      {message === null ? null : (
        <div className="mt-4 border border-signal-500/40 bg-signal-100 px-4 py-3 text-sm text-ink-900">
          {message}
        </div>
      )}

      <div className="mt-5 border border-concrete-200 bg-white">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                <th scope="col" className="px-4 py-2.5">Periodo</th>
                <th scope="col" className="px-4 py-2.5">Código</th>
                <th scope="col" className="px-4 py-2.5 text-right">Devengos</th>
                <th scope="col" className="px-4 py-2.5 text-right">Deducciones</th>
                <th scope="col" className="px-4 py-2.5 text-right">Neto</th>
                <th scope="col" className="px-4 py-2.5">Estado</th>
                <th scope="col" className="px-4 py-2.5 text-right">Acción</th>
              </tr>
            </thead>
            <tbody>
              {payrollsQuery.isPending ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-ink-500">
                    Cargando periodos…
                  </td>
                </tr>
              ) : runs.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-ink-500">
                    No hay periodos de nómina para los filtros seleccionados.
                  </td>
                </tr>
              ) : (
                runs.map((run) => (
                  <tr
                    key={run.id}
                    className="border-b border-concrete-100 last:border-b-0"
                  >
                    <td className="px-4 py-3 text-xs">
                      {formatDate(run.period_start)} a {formatDate(run.period_end)}
                      <p className="text-ink-500">
                        {formatDateTime(run.created_at)}
                      </p>
                    </td>
                    <td className="px-4 py-3 font-semibold">
                      {run.code}
                      {run.is_adjustment ? (
                        <p className="text-xs font-normal text-ink-500">Ajuste</p>
                      ) : null}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatMoney(run.total_earnings)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatMoney(run.total_deductions)}
                    </td>
                    <td className="px-4 py-3 text-right font-semibold tabular-nums">
                      {formatMoney(run.total_net)}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge
                        label={PAYROLL_STATUS_LABELS[run.status]}
                        tone={PAYROLL_STATUS_TONES[run.status]}
                        hint={PAYROLL_STATUS_HINTS[run.status]}
                      />
                    </td>
                    <td className="px-4 py-3 text-right text-xs">
                      <Link
                        className="font-semibold text-signal-600 hover:underline"
                        to={`/hr/payrolls/${run.id}`}
                      >
                        Ver desprendibles →
                      </Link>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <PayrollRunForm
        open={formOpen}
        onClose={() => setFormOpen(false)}
        onSaved={handleCreated}
      />
    </div>
  );
}
