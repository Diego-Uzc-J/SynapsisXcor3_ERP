import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { canWriteModule, useAuth } from "../../store/authStore";
import AttendanceForm from "./AttendanceForm";
import { ATTENDANCE_STATUS_LABELS, CONTRACT_TYPE_LABELS } from "./constants";
import ContractForm from "./ContractForm";
import { errorMessage } from "./errors";
import { formatDate, formatDateTime, formatHours, formatMoney } from "./format";
import { useEmployee } from "./hooks";
import HrTabs from "./HrTabs";
import StatusBadge from "./StatusBadge";

type Feedback = { tone: "success" | "error"; text: string };

export default function EmployeeProfile() {
  const { employeeId: rawId } = useParams();
  const employeeId = Number(rawId);
  const validId = Number.isInteger(employeeId) && employeeId > 0;

  const { user } = useAuth();
  const canWrite = canWriteModule(user, "hr");
  const employeeQuery = useEmployee(employeeId, validId);
  const employee = employeeQuery.data;

  const [contractOpen, setContractOpen] = useState(false);
  const [attendanceOpen, setAttendanceOpen] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  const message = errorMessage(employeeQuery.error);

  if (!validId || message !== null) {
    return (
      <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
        <HrTabs />
        <div className="mt-6 border border-signal-500/40 bg-signal-100 px-5 py-6">
          <h1 className="text-xl font-bold">No se pudo cargar el expediente</h1>
          <p className="mt-1 text-sm text-ink-700">
            {message ?? "El identificador del empleado no es válido."}
          </p>
          <Link
            className="mt-4 inline-block text-sm font-semibold text-signal-600 hover:underline"
            to="/hr/employees"
          >
            Volver a empleados
          </Link>
        </div>
      </div>
    );
  }

  if (employeeQuery.isPending || employee === undefined) {
    return (
      <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
        <HrTabs />
        <p className="mt-6 border border-concrete-200 bg-white px-4 py-8 text-center text-sm text-ink-500">
          Cargando expediente…
        </p>
      </div>
    );
  }

  const hasActiveContract = employee.contracts.some((item) => item.is_active);

  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <header className="border-b-2 border-ink-950 pb-6">
        <Link
          className="text-xs font-semibold text-ink-500 hover:text-signal-600 hover:underline"
          to="/hr/employees"
        >
          ← Empleados
        </Link>
        <div className="mt-3 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
              Expediente #{employee.id}
            </p>
            <h1 className="mt-2 text-3xl font-extrabold tracking-tight sm:text-4xl">
              {employee.first_name} {employee.last_name}
            </h1>
            <p className="mt-1 text-sm text-ink-700">
              {employee.identification_number} · Ingreso {formatDate(employee.hire_date)}
            </p>
          </div>
          <StatusBadge
            label={employee.is_active ? "Empleado activo" : "Empleado inactivo"}
            tone={employee.is_active ? "success" : "muted"}
          />
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
        </p>
      )}

      <section className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="border border-concrete-200 bg-white px-4 py-3">
          <p className="text-xs font-semibold text-ink-500">Correo</p>
          <p className="mt-1 break-all text-sm">{employee.email}</p>
        </div>
        <div className="border border-concrete-200 bg-white px-4 py-3">
          <p className="text-xs font-semibold text-ink-500">Teléfono</p>
          <p className="mt-1 text-sm">{employee.phone ?? "—"}</p>
        </div>
        <div className="border border-concrete-200 bg-white px-4 py-3">
          <p className="text-xs font-semibold text-ink-500">Nacimiento</p>
          <p className="mt-1 text-sm">{formatDate(employee.birth_date)}</p>
        </div>
        <div className="border border-concrete-200 bg-white px-4 py-3">
          <p className="text-xs font-semibold text-ink-500">Registrado</p>
          <p className="mt-1 text-sm">{formatDateTime(employee.created_at)}</p>
        </div>
      </section>

      <section className="mt-8">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-xl font-bold tracking-tight">Historial laboral</h2>
            <p className="mt-0.5 text-xs text-ink-500">
              {hasActiveContract
                ? "Ya existe un contrato vigente; los nuevos se registran como históricos."
                : "Este empleado aún no tiene contrato vigente."}
            </p>
          </div>
          {canWrite ? (
            <button
              type="button"
              onClick={() => setContractOpen(true)}
              className="border border-ink-950 px-3 py-2 text-xs font-semibold hover:bg-ink-950 hover:text-concrete-50"
            >
              + Nuevo contrato
            </button>
          ) : null}
        </div>
        <div className="mt-3 overflow-x-auto border border-concrete-200 bg-white">
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                <th scope="col" className="px-4 py-2.5">Tipo</th>
                <th scope="col" className="px-4 py-2.5">Vigencia</th>
                <th scope="col" className="px-4 py-2.5 text-right">Salario base</th>
                <th scope="col" className="px-4 py-2.5">Estado</th>
              </tr>
            </thead>
            <tbody>
              {employee.contracts.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center text-ink-500">
                    Sin contratos registrados.
                  </td>
                </tr>
              ) : (
                [...employee.contracts]
                  .sort((a, b) => b.start_date.localeCompare(a.start_date))
                  .map((contract) => (
                    <tr
                      key={contract.id}
                      className="border-b border-concrete-100 last:border-b-0"
                    >
                      <td className="px-4 py-2.5">
                        {CONTRACT_TYPE_LABELS[contract.contract_type]}
                      </td>
                      <td className="px-4 py-2.5 text-xs text-ink-700">
                        {formatDate(contract.start_date)} a{" "}
                        {contract.end_date === null
                          ? "indefinido"
                          : formatDate(contract.end_date)}
                      </td>
                      <td className="px-4 py-2.5 text-right font-semibold tabular-nums">
                        {formatMoney(contract.base_salary)}
                      </td>
                      <td className="px-4 py-2.5">
                        <StatusBadge
                          label={contract.is_active ? "Vigente" : "Histórico"}
                          tone={contract.is_active ? "success" : "muted"}
                        />
                      </td>
                    </tr>
                  ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-8">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-xl font-bold tracking-tight">
              Novedades de asistencia
            </h2>
            <p className="mt-0.5 text-xs text-ink-500">
              Últimos {employee.attendance_records.length} registros del expediente.
            </p>
          </div>
          {canWrite ? (
            <button
              type="button"
              onClick={() => setAttendanceOpen(true)}
              className="border border-ink-950 px-3 py-2 text-xs font-semibold hover:bg-ink-950 hover:text-concrete-50"
            >
              + Registrar asistencia
            </button>
          ) : null}
        </div>
        <div className="mt-3 overflow-x-auto border border-concrete-200 bg-white">
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                <th scope="col" className="px-4 py-2.5">Fecha</th>
                <th scope="col" className="px-4 py-2.5">Novedad</th>
                <th scope="col" className="px-4 py-2.5 text-right">Horas extra</th>
                <th scope="col" className="px-4 py-2.5">Observaciones</th>
              </tr>
            </thead>
            <tbody>
              {employee.attendance_records.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center text-ink-500">
                    Sin novedades registradas.
                  </td>
                </tr>
              ) : (
                [...employee.attendance_records]
                  .sort((a, b) => b.date.localeCompare(a.date))
                  .map((record) => (
                    <tr
                      key={record.id}
                      className="border-b border-concrete-100 last:border-b-0"
                    >
                      <td className="px-4 py-2.5 text-xs">{formatDate(record.date)}</td>
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
      </section>

      <ContractForm
        open={contractOpen}
        employees={[employee]}
        employeeId={employee.id}
        hasActiveContract={hasActiveContract}
        onClose={() => setContractOpen(false)}
        onSaved={(_contract, employeeName) => {
          setContractOpen(false);
          setFeedback({
            tone: "success",
            text: `Contrato de ${employeeName} registrado correctamente.`,
          });
        }}
      />

      <AttendanceForm
        open={attendanceOpen}
        employees={[employee]}
        employeeId={employee.id}
        onClose={() => setAttendanceOpen(false)}
        onSaved={(_record, employeeName) => {
          setAttendanceOpen(false);
          setFeedback({
            tone: "success",
            text: `Asistencia de ${employeeName} registrada correctamente.`,
          });
        }}
      />
    </div>
  );
}
