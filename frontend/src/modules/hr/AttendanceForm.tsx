import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import FormSheet from "../../components/FormSheet";
import { ATTENDANCE_STATUS_LABELS, employeeFullName } from "./constants";
import { errorHint, errorMessage } from "./errors";
import { hoursString, todayIso } from "./format";
import { useCreateAttendance } from "./hooks";
import { ATTENDANCE_STATUSES } from "./types";
import type { Attendance, AttendanceStatus, Employee } from "./types";

interface AttendanceFormProps {
  open: boolean;
  employees: Employee[];
  /** Empleado preseleccionado; `null` permite elegirlo en el formulario. */
  employeeId: number | null;
  onClose: () => void;
  onSaved: (record: Attendance, employeeName: string) => void;
}

const labelClass = "mb-1.5 block text-xs font-semibold text-ink-700";
const fieldClass =
  "w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 " +
  "placeholder:text-concrete-400 focus:border-signal-500 focus:outline-none " +
  "disabled:cursor-not-allowed disabled:bg-concrete-100";

interface FormState {
  employeeId: string;
  date: string;
  status: AttendanceStatus;
  overtime_hours: string;
  notes: string;
}

function initialState(employeeId: number | null): FormState {
  return {
    employeeId: employeeId === null ? "" : String(employeeId),
    date: todayIso(),
    status: "PRESENT",
    overtime_hours: "0.00",
    notes: "",
  };
}

export default function AttendanceForm({
  open,
  employees,
  employeeId,
  onClose,
  onSaved,
}: AttendanceFormProps) {
  const [form, setForm] = useState<FormState>(() => initialState(employeeId));
  const [validationError, setValidationError] = useState<string | null>(null);
  const mutation = useCreateAttendance();

  useEffect(() => {
    if (open) {
      setForm(initialState(employeeId));
      setValidationError(null);
    }
  }, [open, employeeId]);

  function setField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  const selectedEmployeeId = Number(form.employeeId);
  const selectedEmployee = employees.find(
    (employee) => employee.id === selectedEmployeeId,
  );
  const message = errorMessage(mutation.error);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setValidationError(null);

    if (!Number.isInteger(selectedEmployeeId) || selectedEmployeeId <= 0) {
      setValidationError("Selecciona un empleado.");
      return;
    }
    if (form.date === "") {
      setValidationError("La fecha del registro es obligatoria.");
      return;
    }
    const overtime = hoursString(form.overtime_hours);
    if (overtime === null) {
      setValidationError("Las horas extra deben ser un número no negativo con dos decimales.");
      return;
    }

    mutation.mutate(
      {
        employee_id: selectedEmployeeId,
        date: form.date,
        status: form.status,
        overtime_hours: overtime,
        notes: form.notes.trim() === "" ? null : form.notes.trim(),
      },
      {
        onSuccess: (record) =>
          onSaved(
            record,
            selectedEmployee === undefined
              ? `Empleado #${selectedEmployeeId}`
              : employeeFullName(selectedEmployee),
          ),
      },
    );
  }

  return (
    <FormSheet
      open={open}
      title="Registrar asistencia"
      subtitle="Las horas extra se suman al cálculo de la nómina del periodo."
      submitLabel="Guardar registro"
      pendingLabel="Guardando…"
      isPending={mutation.isPending}
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      {validationError === null && message === null ? null : (
        <div className="border border-signal-500/40 bg-signal-100 px-4 py-3 text-sm text-ink-900">
          <p className="font-semibold">{message ?? validationError}</p>
          {message === null ? null : (
            <p className="mt-1 text-xs text-ink-700">{errorHint(message)}</p>
          )}
        </div>
      )}

      <div>
        <label className={labelClass} htmlFor="hr-attendance-employee">
          Empleado *
        </label>
        <select
          id="hr-attendance-employee"
          className={fieldClass}
          value={form.employeeId}
          onChange={(event) => setField("employeeId", event.target.value)}
          disabled={employeeId !== null}
          required
        >
          <option value="">Selecciona un empleado</option>
          {employees.map((employee) => (
            <option key={employee.id} value={employee.id}>
              {employeeFullName(employee)} · {employee.identification_number}
            </option>
          ))}
        </select>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelClass} htmlFor="hr-attendance-date">
            Fecha *
          </label>
          <input
            id="hr-attendance-date"
            type="date"
            className={fieldClass}
            value={form.date}
            onChange={(event) => setField("date", event.target.value)}
            required
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="hr-attendance-status">
            Novedad *
          </label>
          <select
            id="hr-attendance-status"
            className={fieldClass}
            value={form.status}
            onChange={(event) =>
              setField("status", event.target.value as AttendanceStatus)
            }
            required
          >
            {ATTENDANCE_STATUSES.map((status) => (
              <option key={status} value={status}>
                {ATTENDANCE_STATUS_LABELS[status]}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label className={labelClass} htmlFor="hr-attendance-overtime">
          Horas extra
        </label>
        <input
          id="hr-attendance-overtime"
          inputMode="decimal"
          className={fieldClass}
          value={form.overtime_hours}
          onChange={(event) => setField("overtime_hours", event.target.value)}
          placeholder="0.00"
          required
        />
      </div>

      <div>
        <label className={labelClass} htmlFor="hr-attendance-notes">
          Observaciones
        </label>
        <textarea
          id="hr-attendance-notes"
          className={fieldClass}
          value={form.notes}
          onChange={(event) => setField("notes", event.target.value)}
          rows={3}
          placeholder="Opcional"
        />
      </div>
    </FormSheet>
  );
}
