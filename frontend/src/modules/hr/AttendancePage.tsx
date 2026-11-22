import { useState } from "react";

import { canWriteModule, useAuth } from "../../store/authStore";
import AttendanceForm from "./AttendanceForm";
import {
  ATTENDANCE_STATUS_LABELS,
  employeeFullName,
} from "./constants";
import { errorMessage } from "./errors";
import { formatDate, formatHours } from "./format";
import { useAttendance, useEmployees } from "./hooks";
import HrTabs from "./HrTabs";
import StatusBadge from "./StatusBadge";

type Feedback = { tone: "success" | "error"; text: string };
type DateMode = "range" | "exact";

function employeeLabel(
  employees: { id: number; first_name: string; last_name: string }[],
  employeeId: number,
): string {
  const employee = employees.find((item) => item.id === employeeId);
  return employee === undefined ? `Empleado #${employeeId}` : employeeFullName(employee);
}

export default function AttendancePage() {
  const { user } = useAuth();
  const canWrite = canWriteModule(user, "hr");

  const [employeeId, setEmployeeId] = useState<number>(0);
  const [dateMode, setDateMode] = useState<DateMode>("range");
  const [exactDate, setExactDate] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  const employeesQuery = useEmployees({ limit: 200 });
  const employees = employeesQuery.data ?? [];

  const filters = {
    limit: 200,
    ...(employeeId > 0 ? { employee_id: employeeId } : {}),
    ...(dateMode === "exact" && exactDate !== "" ? { date: exactDate } : {}),
    ...(dateMode === "range" && startDate !== "" ? { start_date: startDate } : {}),
    ...(dateMode === "range" && endDate !== "" ? { end_date: endDate } : {}),
  };
  const attendanceQuery = useAttendance(filters);
  const records = attendanceQuery.data ?? [];
  const message =
    errorMessage(employeesQuery.error) ?? errorMessage(attendanceQuery.error);

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <header className="flex flex-col gap-6 border-b-2 border-ink-950 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
            Control diario
          </p>
          <h1 className="mt-2 text-4xl font-extrabold tracking-tight sm:text-5xl">
            Asistencia
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-700">
            Registra asistencias, ausencias, permisos y horas extra. Las horas
            extra del periodo se suman al cálculo de la nómina.
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
            Registrar novedad
          </button>
        ) : null}
      </header>

      <HrTabs />

      <div className="mt-6 flex flex-wrap gap-4 border border-concrete-200 bg-white p-4">
        <div className="min-w-[220px] flex-1">
          <label
            className="mb-1 block text-xs font-semibold text-ink-700"
            htmlFor="hr-attendance-filter-employee"
          >
            Empleado
          </label>
          <select
            id="hr-attendance-filter-employee"
            className="w-full border border-concrete-200 bg-white px-3 py-2 text-sm focus:border-signal-500 focus:outline-none"
            value={employeeId}
            onChange={(event) => setEmployeeId(Number(event.target.value))}
          >
            <option value={0}>Todos los empleados</option>
            {employees.map((employee) => (
              <option key={employee.id} value={employee.id}>
                {employeeFullName(employee)} · {employee.identification_number}
              </option>
            ))}
          </select>
        </div>
        <div className="w-full sm:w-40">
          <label
            className="mb-1 block text-xs font-semibold text-ink-700"
            htmlFor="hr-attendance-mode"
          >
            Filtro de fecha
          </label>
          <select
            id="hr-attendance-mode"
            className="w-full border border-concrete-200 bg-white px-3 py-2 text-sm focus:border-signal-500 focus:outline-none"
            value={dateMode}
            onChange={(event) => setDateMode(event.target.value as DateMode)}
          >
            <option value="range">Periodo</option>
            <option value="exact">Fecha exacta</option>
          </select>
        </div>
        {dateMode === "exact" ? (
          <div className="w-full sm:w-52">
            <label
              className="mb-1 block text-xs font-semibold text-ink-700"
              htmlFor="hr-attendance-exact-date"
            >
              Fecha
            </label>
            <input
              id="hr-attendance-exact-date"
              type="date"
              className="w-full border border-concrete-200 px-3 py-2 text-sm focus:border-signal-500 focus:outline-none"
              value={exactDate}
              onChange={(event) => setExactDate(event.target.value)}
            />
          </div>
        ) : (
          <>
            <div className="w-full sm:w-48">
              <label
                className="mb-1 block text-xs font-semibold text-ink-700"
                htmlFor="hr-attendance-start"
              >
                Desde
              </label>
              <input
                id="hr-attendance-start"
                type="date"
                className="w-full border border-concrete-200 px-3 py-2 text-sm focus:border-signal-500 focus:outline-none"
                value={startDate}
                onChange={(event) => setStartDate(event.target.value)}
              />
            </div>
            <div className="w-full sm:w-48">
              <label
                className="mb-1 block text-xs font-semibold text-ink-700"
                htmlFor="hr-attendance-end"
              >
                Hasta
              </label>
              <input
                id="hr-attendance-end"
                type="date"
                className="w-full border border-concrete-200 px-3 py-2 text-sm focus:border-signal-500 focus:outline-none"
                value={endDate}
                onChange={(event) => setEndDate(event.target.value)}
              />
            </div>
          </>
        )}
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
        <div className="border-b border-concrete-200 px-4 py-3 text-xs font-semibold text-ink-500">
          {records.length} registro{records.length === 1 ? "" : "s"}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                <th scope="col" className="px-4 py-2.5">Fecha</th>
                <th scope="col" className="px-4 py-2.5">Empleado</th>
                <th scope="col" className="px-4 py-2.5">Novedad</th>
                <th scope="col" className="px-4 py-2.5 text-right">Horas extra</th>
                <th scope="col" className="px-4 py-2.5">Observaciones</th>
              </tr>
            </thead>
            <tbody>
              {attendanceQuery.isPending ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-ink-500">
                    Cargando asistencia…
                  </td>
                </tr>
              ) : records.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-ink-500">
                    No hay registros para los filtros seleccionados.
                  </td>
                </tr>
              ) : (
                [...records]
                  .sort((a, b) => b.date.localeCompare(a.date))
                  .map((record) => (
                    <tr
                      key={record.id}
                      className="border-b border-concrete-100 last:border-b-0"
                    >
                      <td className="px-4 py-2.5 text-xs">{formatDate(record.date)}</td>
                      <td className="px-4 py-2.5 text-xs">
                        {employeeLabel(employees, record.employee_id)}
                      </td>
                      <td className="px-4 py-2.5">
                        <StatusBadge
                          label={ATTENDANCE_STATUS_LABELS[record.status]}
                          tone="neutral"
                        />
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums">
                        {formatHours(record.overtime_hours)}
                      </td>
                      <td className="px-4 py-2.5 text-xs text-ink-500">
                        {record.notes ?? "—"}
                      </td>
                    </tr>
                  ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <AttendanceForm
        open={formOpen}
        employees={employees}
        employeeId={employeeId === 0 ? null : employeeId}
        onClose={() => setFormOpen(false)}
        onSaved={(_record, employeeName) => {
          setFormOpen(false);
          setFeedback({
            tone: "success",
            text: `Novedad registrada para ${employeeName}.`,
          });
        }}
      />
    </div>
  );
}
