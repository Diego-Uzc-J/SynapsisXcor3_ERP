import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import ActiveSwitch from "../../components/ActiveSwitch";
import FormSheet from "../../components/FormSheet";
import { errorHint, errorMessage } from "./errors";
import { currentMonthRange } from "./format";
import { useCreatePayrollRun } from "./hooks";
import type { PayrollRun } from "./types";

interface PayrollRunFormProps {
  open: boolean;
  onClose: () => void;
  onSaved: (run: PayrollRun) => void;
}

interface FormState {
  code: string;
  period_start: string;
  period_end: string;
  is_adjustment: boolean;
}

function initialState(): FormState {
  const month = currentMonthRange();
  return {
    code: "",
    period_start: month.start,
    period_end: month.end,
    is_adjustment: false,
  };
}

const labelClass = "mb-1.5 block text-xs font-semibold text-ink-700";
const fieldClass =
  "w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 " +
  "placeholder:text-concrete-400 focus:border-signal-500 focus:outline-none";

/** Genera un periodo en DRAFT; el backend calcula los payslips de forma atómica. */
export default function PayrollRunForm({
  open,
  onClose,
  onSaved,
}: PayrollRunFormProps) {
  const [form, setForm] = useState<FormState>(initialState);
  const [validationError, setValidationError] = useState<string | null>(null);
  const mutation = useCreatePayrollRun();

  useEffect(() => {
    if (open) {
      setForm(initialState());
      setValidationError(null);
    }
  }, [open]);

  function setField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setValidationError(null);

    const code = form.code.trim().toUpperCase();
    if (!/^[A-Z0-9][A-Z0-9._-]*$/.test(code) || code.length > 30) {
      setValidationError(
        "El código debe empezar por letra o dígito y usar mayúsculas, números, puntos, guiones o guiones bajos.",
      );
      return;
    }
    if (form.period_start === "" || form.period_end === "") {
      setValidationError("Define el rango completo del periodo.");
      return;
    }
    if (form.period_start > form.period_end) {
      setValidationError("El inicio del periodo no puede ser posterior al fin.");
      return;
    }

    mutation.mutate(
      {
        code,
        period_start: form.period_start,
        period_end: form.period_end,
        is_adjustment: form.is_adjustment,
      },
      { onSuccess: onSaved },
    );
  }

  const message = errorMessage(mutation.error);

  return (
    <FormSheet
      open={open}
      title="Generar nómina"
      subtitle="El periodo se crea en borrador con los desprendibles ya calculados."
      submitLabel="Generar periodo"
      pendingLabel="Calculando…"
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
        <label className={labelClass} htmlFor="hr-payroll-code">
          Código del periodo *
        </label>
        <input
          id="hr-payroll-code"
          className={fieldClass}
          value={form.code}
          onChange={(event) => setField("code", event.target.value)}
          placeholder="NOM-2026-03"
          maxLength={30}
          required
        />
        <p className="mt-1 text-xs text-ink-500">Debe ser único en el sistema.</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelClass} htmlFor="hr-payroll-start">
            Desde *
          </label>
          <input
            id="hr-payroll-start"
            type="date"
            className={fieldClass}
            value={form.period_start}
            onChange={(event) => setField("period_start", event.target.value)}
            required
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="hr-payroll-end">
            Hasta *
          </label>
          <input
            id="hr-payroll-end"
            type="date"
            className={fieldClass}
            value={form.period_end}
            onChange={(event) => setField("period_end", event.target.value)}
            required
          />
        </div>
      </div>

      <ActiveSwitch
        checked={form.is_adjustment}
        onChange={(checked) => setField("is_adjustment", checked)}
        label="Nómina de ajuste"
        hint="Marca periodos que corrigen una liquidación aprobada anteriormente."
      />
    </FormSheet>
  );
}
