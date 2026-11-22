import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import ActiveSwitch from "../../components/ActiveSwitch";
import FormSheet from "../../components/FormSheet";
import { errorHint, errorMessage } from "./errors";
import { decimalString, formatMoney } from "./format";
import { useCreateWorkCenter, useUpdateWorkCenter } from "./hooks";
import type { WorkCenter } from "./types";

interface WorkCenterFormProps {
  open: boolean;
  center: WorkCenter | null;
  onClose: () => void;
  onSaved: (center: WorkCenter, mode: "created" | "updated") => void;
}

interface FormState {
  code: string;
  name: string;
  costPerHour: string;
  isActive: boolean;
}

const CODE_PATTERN = /^[A-Z0-9][A-Z0-9._-]*$/;
const labelClass = "mb-1.5 block text-xs font-semibold text-ink-700";
const fieldClass =
  "w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 " +
  "placeholder:text-concrete-400 focus:border-signal-500 focus:outline-none";

function initialState(center: WorkCenter | null): FormState {
  return {
    code: center?.code ?? "",
    name: center?.name ?? "",
    costPerHour: center?.cost_per_hour ?? "0.00",
    isActive: center?.is_active ?? true,
  };
}

/** Alta y edición de estaciones; el coste por hora alimenta las OP al completar. */
export default function WorkCenterForm({
  open,
  center,
  onClose,
  onSaved,
}: WorkCenterFormProps) {
  const [form, setForm] = useState<FormState>(() => initialState(center));
  const [validationError, setValidationError] = useState<string | null>(null);
  const createMutation = useCreateWorkCenter();
  const updateMutation = useUpdateWorkCenter();

  useEffect(() => {
    if (open) {
      setForm(initialState(center));
      setValidationError(null);
    }
  }, [open, center]);

  function setField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setValidationError(null);

    const code = form.code.trim().toUpperCase();
    if (!CODE_PATTERN.test(code) || code.length > 50) {
      setValidationError(
        "El código debe empezar por letra o dígito y usar mayúsculas, números, puntos, guiones o guiones bajos.",
      );
      return;
    }
    if (form.name.trim() === "") {
      setValidationError("El nombre del centro de trabajo es obligatorio.");
      return;
    }
    const costPerHour = decimalString(form.costPerHour);
    if (costPerHour === null) {
      setValidationError(
        "El coste por hora debe ser un importe no negativo con hasta dos decimales.",
      );
      return;
    }

    const payload = {
      code,
      name: form.name.trim(),
      cost_per_hour: costPerHour,
      is_active: form.isActive,
    };

    if (center === null) {
      createMutation.mutate(payload, {
        onSuccess: (created) => onSaved(created, "created"),
      });
    } else {
      updateMutation.mutate(
        { workCenterId: center.id, payload },
        { onSuccess: (updated) => onSaved(updated, "updated") },
      );
    }
  }

  const message = errorMessage(updateMutation.error ?? createMutation.error);
  const isPending = createMutation.isPending || updateMutation.isPending;

  return (
    <FormSheet
      open={open}
      title={center === null ? "Nuevo centro de trabajo" : "Editar centro"}
      subtitle="El coste por hora se usa para calcular la mano de obra al completar una orden."
      submitLabel={center === null ? "Registrar centro" : "Guardar cambios"}
      pendingLabel="Guardando…"
      isPending={isPending}
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
        <label className={labelClass} htmlFor="mfg-work-center-code">
          Código *
        </label>
        <input
          id="mfg-work-center-code"
          className={fieldClass}
          value={form.code}
          onChange={(event) => setField("code", event.target.value)}
          placeholder="WC-ENSAMBLE-01"
          maxLength={50}
          required
        />
      </div>

      <div>
        <label className={labelClass} htmlFor="mfg-work-center-name">
          Nombre *
        </label>
        <input
          id="mfg-work-center-name"
          className={fieldClass}
          value={form.name}
          onChange={(event) => setField("name", event.target.value)}
          placeholder="Línea de ensamble A"
          maxLength={150}
          required
        />
      </div>

      <div>
        <label className={labelClass} htmlFor="mfg-work-center-cost">
          Coste por hora *
        </label>
        <input
          id="mfg-work-center-cost"
          inputMode="decimal"
          className={fieldClass}
          value={form.costPerHour}
          onChange={(event) => setField("costPerHour", event.target.value)}
          placeholder="150.00"
          required
        />
        <p className="mt-1 text-xs text-ink-500">
          Referencia actual: {formatMoney(center?.cost_per_hour ?? null)} / h
        </p>
      </div>

      <ActiveSwitch
        checked={form.isActive}
        onChange={(checked) => setField("isActive", checked)}
        label="Centro operativo"
        hint="Los centros inactivos no se ofrecen al crear órdenes."
      />
    </FormSheet>
  );
}
