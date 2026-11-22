import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { canWriteModule, useAuth } from "../../store/authStore";
import {
  canApprovePayroll,
  employeeFullName,
  PAYROLL_STATUS_HINTS,
  PAYROLL_STATUS_LABELS,
  PAYROLL_STATUS_TONES,
} from "./constants";
import { errorHint, errorMessage } from "./errors";
import { formatDate, formatDateTime, formatMoney } from "./format";
import { useApprovePayrollRun, useEmployees, usePayrollRun } from "./hooks";
import HrDialog from "./HrDialog";
import HrTabs from "./HrTabs";
import StatusBadge from "./StatusBadge";

type Feedback = { tone: "success" | "error"; text: string };

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

export default function PayrollRunDetail() {
  const { payrollRunId: rawId } = useParams();
  const payrollRunId = Number(rawId);
  const validId = Number.isInteger(payrollRunId) && payrollRunId > 0;

  const { user } = useAuth();
  const canWrite = canWriteModule(user, "hr");
  const runQuery = usePayrollRun(payrollRunId, validId);
  const employeesQuery = useEmployees({ limit: 200 });
  const approveMutation = useApprovePayrollRun();

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  const run = runQuery.data;
  const employees = employeesQuery.data ?? [];
  const message = errorMessage(runQuery.error);

  function employeeLabel(employeeId: number): string {
    const employee = employees.find((item) => item.id === employeeId);
    return employee === undefined
      ? `Empleado #${employeeId}`
      : employeeFullName(employee);
  }

  function handleApprove() {
    approveMutation.mutate(payrollRunId, {
      onSuccess: (updated) => {
        setConfirmOpen(false);
        setFeedback({
          tone: "success",
          text: `Periodo ${updated.code} aprobado; asiento contable generado.`,
        });
      },
      onError: (error) => {
        const text =
          errorMessage(error) ?? "No se pudo aprobar el periodo de nómina.";
        setConfirmOpen(false);
        setFeedback({ tone: "error", text });
      },
    });
  }

  if (!validId || message !== null || (!runQuery.isPending && run === undefined)) {
    return (
      <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
        <HrTabs />
        <div className="mt-6 border border-signal-500/40 bg-signal-100 px-5 py-6">
          <h1 className="text-xl font-bold">No se pudo cargar el periodo</h1>
          <p className="mt-1 text-sm text-ink-700">
            {message ?? "El identificador de la nómina no es válido."}
          </p>
          <Link
            className="mt-4 inline-block text-sm font-semibold text-signal-600 hover:underline"
            to="/hr/payrolls"
          >
            Volver a nómina
          </Link>
        </div>
      </div>
    );
  }

  if (runQuery.isPending || run === undefined) {
    return (
      <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
        <HrTabs />
        <p className="mt-6 border border-concrete-200 bg-white px-4 py-8 text-center text-sm text-ink-500">
          Cargando periodo de nómina…
        </p>
      </div>
    );
  }

  const canApprove = canWrite && canApprovePayroll(run.status);
  const approvalError = errorMessage(approveMutation.error);

  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <header className="border-b-2 border-ink-950 pb-6">
        <Link
          className="text-xs font-semibold text-ink-500 hover:text-signal-600 hover:underline"
          to="/hr/payrolls"
        >
          ← Nómina
        </Link>
        <div className="mt-3 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
              Periodo #{run.id}
            </p>
            <h1 className="mt-2 text-3xl font-extrabold tracking-tight sm:text-4xl">
              {run.code}
            </h1>
            <p className="mt-1 text-sm text-ink-700">
              {formatDate(run.period_start)} a {formatDate(run.period_end)}
              {run.is_adjustment ? " · Nómina de ajuste" : ""}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge
              label={PAYROLL_STATUS_LABELS[run.status]}
              tone={PAYROLL_STATUS_TONES[run.status]}
              hint={PAYROLL_STATUS_HINTS[run.status]}
            />
            {canApprove ? (
              <button
                type="button"
                onClick={() => {
                  setFeedback(null);
                  setConfirmOpen(true);
                }}
                className="bg-signal-500 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-signal-600"
              >
                Aprobar nómina
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
              ? "border-pine-500 bg-pine-50 text-pine-700"
              : "border-signal-500/40 bg-signal-100 text-ink-900",
          ].join(" ")}
        >
          {feedback.text}
          {feedback.tone === "error" ? (
            <span className="block text-xs">{errorHint(feedback.text)}</span>
          ) : null}
        </p>
      )}

      {approvalError === null ? null : (
        <p className="mt-4 border border-signal-500/40 bg-signal-100 px-4 py-3 text-sm text-ink-900">
          {approvalError}
        </p>
      )}

      <p className="mt-6 text-xs text-ink-500">
        {PAYROLL_STATUS_HINTS[run.status]}
        {run.approved_at === null
          ? ""
          : ` Aprobada el ${formatDateTime(run.approved_at)}.`}
      </p>

      <section className="mt-4 grid gap-4 sm:grid-cols-3">
        <SummaryCard label="Total devengos" value={formatMoney(run.total_earnings)} />
        <SummaryCard
          label="Total deducciones"
          value={formatMoney(run.total_deductions)}
        />
        <SummaryCard label="Neto a pagar" value={formatMoney(run.total_net)} emphasis />
      </section>

      <section className="mt-8">
        <h2 className="text-xl font-bold tracking-tight">Desprendibles</h2>
        <p className="mt-0.5 text-xs text-ink-500">
          {run.payslips.length} empleado{run.payslips.length === 1 ? "" : "s"} incluidos
          en el calculo del periodo.
        </p>
        <div className="mt-3 overflow-x-auto border border-concrete-200 bg-white">
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                <th scope="col" className="px-4 py-2.5">Empleado</th>
                <th scope="col" className="px-4 py-2.5 text-right">Salario base</th>
                <th scope="col" className="px-4 py-2.5 text-right">Horas extra</th>
                <th scope="col" className="px-4 py-2.5 text-right">Bonificaciones</th>
                <th scope="col" className="px-4 py-2.5 text-right">Deducciones</th>
                <th scope="col" className="px-4 py-2.5 text-right">Devengos</th>
                <th scope="col" className="px-4 py-2.5 text-right">Neto</th>
              </tr>
            </thead>
            <tbody>
              {run.payslips.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-ink-500">
                    No se generaron desprendibles: revise empleados activos y
                    contratos vigentes en el periodo.
                  </td>
                </tr>
              ) : (
                run.payslips.map((payslip) => (
                  <tr
                    key={payslip.id}
                    className="border-b border-concrete-100 last:border-b-0"
                  >
                    <td className="px-4 py-3">
                      <Link
                        className="font-semibold hover:text-signal-600 hover:underline"
                        to={`/hr/employees/${payslip.employee_id}`}
                      >
                        {employeeLabel(payslip.employee_id)}
                      </Link>
                      <p className="text-xs text-ink-500">#{payslip.employee_id}</p>
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatMoney(payslip.base_salary)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatMoney(payslip.overtime_pay)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatMoney(payslip.bonuses)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatMoney(payslip.deductions)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatMoney(payslip.earnings)}
                    </td>
                    <td className="px-4 py-3 text-right font-semibold tabular-nums">
                      {formatMoney(payslip.net_pay)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <HrDialog
        open={confirmOpen}
        title="Aprobar nómina"
        subtitle={`Periodo ${run.code}`}
        onClose={() => setConfirmOpen(false)}
        footer={
          <>
            <button
              type="button"
              onClick={() => setConfirmOpen(false)}
              disabled={approveMutation.isPending}
              className="border border-concrete-200 px-4 py-2 text-sm font-semibold text-ink-700 hover:border-ink-500"
            >
              Cancelar
            </button>
            <button
              type="button"
              onClick={handleApprove}
              disabled={approveMutation.isPending}
              className="bg-signal-500 px-4 py-2 text-sm font-semibold text-white hover:bg-signal-600 disabled:opacity-60"
            >
              {approveMutation.isPending ? "Aprobando…" : "Confirmar aprobación"}
            </button>
          </>
        }
      >
        <p className="text-sm leading-relaxed text-ink-700">
          Se aprobará el periodo <strong>{run.code}</strong> con{" "}
          <strong>{run.payslips.length}</strong> desprendible
          {run.payslips.length === 1 ? "" : "s"} y un neto total de{" "}
          <strong>{formatMoney(run.total_net)}</strong>.
        </p>
        <p className="mt-3 border border-amber-400 bg-amber-50 px-4 py-3 text-xs leading-relaxed text-amber-900">
          La aprobación genera el asiento contable en la misma transacción. Si
          falla la contabilidad, el periodo permanece en borrador. Una nómina
          aprobada no se puede modificar ni aprobar de nuevo.
        </p>
      </HrDialog>
    </div>
  );
}
