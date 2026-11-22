import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import ActiveSwitch from "../../components/ActiveSwitch";
import FormSheet from "../../components/FormSheet";
import { CONTRACT_TYPE_LABELS, employeeFullName } from "./constants";
import { errorHint, errorMessage } from "./errors";
import { moneyString, todayIso } from "./format";
import { useCreateContract } from "./hooks";
import { CONTRACT_TYPES } from "./types";
import type { Contract, ContractType, Employee } from "./types";

interface ContractFormProps {
  open: boolean;
  employees: Employee[];
  /** Empleado preseleccionado; `null` permite elegirlo en el formulario. */
  employeeId: number | null;
  /** El backend permite un único contrato activo por empleado. */
  hasActiveContract: boolean;
  onClose: () => void;
  onSaved: (contract: Contract, employeeName: string) => void;
}

const labelClass = "mb-1.5 block text-xs font-semibold text-ink-700";
const fieldClass =
  "w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 " +
  "placeholder:text-concrete-400 focus:border-signal-500 focus:outline-none " +
  "disabled:cursor-not-allowed disabled:bg-concrete-100";

interface FormState {
  employeeId: string;
  contract_type: ContractType;
  base_salary: string;
  start_date: string;
  end_date: string;
  is_active: boolean;
}

function initialState(
  employeeId: number | null,
  hasActiveContract: boolean,
): FormState {
  return {
    employeeId: employeeId === null ? "" : String(employeeId),
    contract_type: "INDEFINITE",
    base_salary: "",
    start_date: todayIso(),
    end_date: "",
    is_active: !hasActiveContract,
  };
}

export default function ContractForm({
  open,
  employees,
  employeeId,
  hasActiveContract,
  onClose,
  onSaved,
}: ContractFormProps) {
  const [form, setForm] = useState<FormState>(() =>
    initialState(employeeId, hasActiveContract),
  );
  const [validationError, setValidationError] = useState<string | null>(null);
  const mutation = useCreateContract();

  useEffect(() => {
    if (open) {
      setForm(initialState(employeeId, hasActiveContract));
      setValidationError(null);
    }
  }, [open, employeeId, hasActiveContract]);

  function setField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  const selectedEmployeeId = Number(form.employeeId);
  const selectedEmployee = employees.find(
    (employee) => employee.id === selectedEmployeeId,
  );
  const activeConflict = form.is_active && hasActiveContract;
  const message = errorMessage(mutation.error);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setValidationError(null);

    if (!Number.isInteger(selectedEmployeeId) || selectedEmployeeId <= 0) {
      setValidationError("Selecciona el empleado titular del contrato.");
      return;
    }
    const baseSalary = moneyString(form.base_salary);
    if (baseSalary === null || Number(baseSalary) <= 0) {
      setValidationError("El salario base debe ser un importe positivo con dos decimales.");
      return;
    }
    if (form.start_date === "") {
      setValidationError("La fecha de inicio es obligatoria.");
      return;
    }
    if (form.end_date !== "" && form.end_date < form.start_date) {
      setValidationError("La fecha de fin no puede ser anterior al inicio.");
      return;
    }
    if (activeConflict) {
      setValidationError(
        "Este empleado ya tiene un contrato vigente. Registra este como histórico inactivo.",
      );
      return;
    }

    mutation.mutate(
      {
        employee_id: selectedEmployeeId,
        contract_type: form.contract_type,
        base_salary: baseSalary,
        start_date: form.start_date,
        end_date: form.end_date === "" ? null : form.end_date,
        is_active: form.is_active,
      },
      {
        onSuccess: (contract) =>
          onSaved(
            contract,
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
      title="Nuevo contrato"
      subtitle="Solo un contrato puede estar vigente por empleado."
      submitLabel="Registrar contrato"
      pendingLabel="Guardando…"
      isPending={mutation.isPending}
      submitDisabled={activeConflict}
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

      {activeConflict ? (
        <div className="border border-amber-400 bg-amber-50 px-4 py-3 text-xs leading-relaxed text-amber-900">
          El empleado ya cuenta con contrato vigente. Desactiva este contrato
          para registrarlo como historial o cierra primero el actual.
        </div>
      ) : null}

      <div>
        <label className={labelClass} htmlFor="hr-contract-employee">
          Empleado *
        </label>
        <select
          id="hr-contract-employee"
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

      <div>
        <label className={labelClass} htmlFor="hr-contract-type">
          Tipo de contrato *
        </label>
        <select
          id="hr-contract-type"
          className={fieldClass}
          value={form.contract_type}
          onChange={(event) =>
            setField("contract_type", event.target.value as ContractType)
          }
          required
        >
          {CONTRACT_TYPES.map((type) => (
            <option key={type} value={type}>
              {CONTRACT_TYPE_LABELS[type]}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className={labelClass} htmlFor="hr-contract-salary">
          Salario base *
        </label>
        <input
          id="hr-contract-salary"
          inputMode="decimal"
          className={fieldClass}
          value={form.base_salary}
          onChange={(event) => setField("base_salary", event.target.value)}
          placeholder="3000000.00"
          required
        />
        <p className="mt-1 text-xs text-ink-500">
          Se envía como decimal exacto; el backend rechaza importes con coma
          flotante.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelClass} htmlFor="hr-contract-start">
            Fecha de inicio *
          </label>
          <input
            id="hr-contract-start"
            type="date"
            className={fieldClass}
            value={form.start_date}
            onChange={(event) => setField("start_date", event.target.value)}
            required
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="hr-contract-end">
            Fecha de fin
          </label>
          <input
            id="hr-contract-end"
            type="date"
            className={fieldClass}
            value={form.end_date}
            onChange={(event) => setField("end_date", event.target.value)}
          />
        </div>
      </div>

      <ActiveSwitch
        checked={form.is_active}
        onChange={(checked) => setField("is_active", checked)}
        label="Contrato vigente"
        hint="Si ya existe uno activo, desactívalo para guardarlo como historial."
      />
    </FormSheet>
  );
}
