import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import ActiveSwitch from "../../components/ActiveSwitch";
import FormSheet from "../../components/FormSheet";
import { errorHint, errorMessage } from "./errors";
import { useCreateEmployee, useUpdateEmployee } from "./hooks";
import type { Employee } from "./types";

interface EmployeeFormProps {
  open: boolean;
  /** `null` para dar de alta; un empleado para editar. */
  employee: Employee | null;
  onClose: () => void;
  onSaved: (employee: Employee, mode: "created" | "updated") => void;
}

const labelClass = "mb-1.5 block text-xs font-semibold text-ink-700";
const fieldClass =
  "w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 " +
  "placeholder:text-concrete-400 focus:border-signal-500 focus:outline-none";

interface FormState {
  identification_number: string;
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  birth_date: string;
  hire_date: string;
  is_active: boolean;
}

function initialState(employee: Employee | null): FormState {
  if (employee === null) {
    return {
      identification_number: "",
      first_name: "",
      last_name: "",
      email: "",
      phone: "",
      birth_date: "",
      hire_date: "",
      is_active: true,
    };
  }
  return {
    identification_number: employee.identification_number,
    first_name: employee.first_name,
    last_name: employee.last_name,
    email: employee.email,
    phone: employee.phone ?? "",
    birth_date: employee.birth_date,
    hire_date: employee.hire_date,
    is_active: employee.is_active,
  };
}

export default function EmployeeForm({
  open,
  employee,
  onClose,
  onSaved,
}: EmployeeFormProps) {
  const [form, setForm] = useState<FormState>(() => initialState(employee));
  const [validationError, setValidationError] = useState<string | null>(null);
  const createMutation = useCreateEmployee();
  const updateMutation = useUpdateEmployee();

  useEffect(() => {
    if (open) {
      setForm(initialState(employee));
      setValidationError(null);
    }
  }, [open, employee]);

  function setField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setValidationError(null);

    const identification = form.identification_number.trim();
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(identification)) {
      setValidationError("El documento debe ser alfanumérico (guiones y puntos permitidos).");
      return;
    }
    if (form.birth_date === "" || form.hire_date === "") {
      setValidationError("La fecha de nacimiento y de ingreso son obligatorias.");
      return;
    }
    if (form.birth_date > form.hire_date) {
      setValidationError("La fecha de nacimiento no puede ser posterior al ingreso.");
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim())) {
      setValidationError("Ingresa un correo electrónico válido.");
      return;
    }

    const payload = {
      identification_number: identification,
      first_name: form.first_name.trim(),
      last_name: form.last_name.trim(),
      email: form.email.trim(),
      phone: form.phone.trim() === "" ? null : form.phone.trim(),
      birth_date: form.birth_date,
      hire_date: form.hire_date,
      is_active: form.is_active,
    };

    if (employee === null) {
      createMutation.mutate(payload, {
        onSuccess: (created) => onSaved(created, "created"),
      });
      return;
    }
    updateMutation.mutate(
      { employeeId: employee.id, payload },
      { onSuccess: (updated) => onSaved(updated, "updated") },
    );
  }

  const mutation = employee === null ? createMutation : updateMutation;
  const message = errorMessage(mutation.error);

  return (
    <FormSheet
      open={open}
      title={employee === null ? "Nuevo empleado" : "Editar empleado"}
      subtitle={
        employee === null
          ? "El documento de identidad debe ser único."
          : `Expediente #${employee.id}`
      }
      submitLabel={employee === null ? "Registrar empleado" : "Guardar cambios"}
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
        <label className={labelClass} htmlFor="hr-employee-identification">
          Documento de identidad *
        </label>
        <input
          id="hr-employee-identification"
          className={fieldClass}
          value={form.identification_number}
          onChange={(event) =>
            setField("identification_number", event.target.value)
          }
          placeholder="900123456-1"
          maxLength={50}
          required
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelClass} htmlFor="hr-employee-first-name">
            Nombres *
          </label>
          <input
            id="hr-employee-first-name"
            className={fieldClass}
            value={form.first_name}
            onChange={(event) => setField("first_name", event.target.value)}
            required
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="hr-employee-last-name">
            Apellidos *
          </label>
          <input
            id="hr-employee-last-name"
            className={fieldClass}
            value={form.last_name}
            onChange={(event) => setField("last_name", event.target.value)}
            required
          />
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelClass} htmlFor="hr-employee-email">
            Correo electrónico *
          </label>
          <input
            id="hr-employee-email"
            type="email"
            className={fieldClass}
            value={form.email}
            onChange={(event) => setField("email", event.target.value)}
            placeholder="nombre@empresa.com"
            required
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="hr-employee-phone">
            Teléfono
          </label>
          <input
            id="hr-employee-phone"
            className={fieldClass}
            value={form.phone}
            onChange={(event) => setField("phone", event.target.value)}
            placeholder="Opcional"
            maxLength={50}
          />
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelClass} htmlFor="hr-employee-birth-date">
            Fecha de nacimiento *
          </label>
          <input
            id="hr-employee-birth-date"
            type="date"
            className={fieldClass}
            value={form.birth_date}
            onChange={(event) => setField("birth_date", event.target.value)}
            required
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="hr-employee-hire-date">
            Fecha de ingreso *
          </label>
          <input
            id="hr-employee-hire-date"
            type="date"
            className={fieldClass}
            value={form.hire_date}
            onChange={(event) => setField("hire_date", event.target.value)}
            required
          />
        </div>
      </div>

      <ActiveSwitch
        checked={form.is_active}
        onChange={(checked) => setField("is_active", checked)}
        label="Empleado activo"
        hint="Los empleados inactivos no se incluyen en nuevas nóminas."
      />
    </FormSheet>
  );
}
