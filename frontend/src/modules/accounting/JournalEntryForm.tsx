import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import FormSheet from "../../components/FormSheet";
import { errorHint, errorMessage } from "./errors";
import { formatCents, moneyString, parseAmount, todayIso, toCents } from "./format";
import { useAccounts, useCreateJournalEntry } from "./hooks";
import type { JournalEntry, JournalItemCreate } from "./types";

interface JournalEntryFormProps {
  open: boolean;
  onClose: () => void;
  onCreated: (entry: JournalEntry) => void;
}

interface JournalLine {
  key: number;
  accountId: string;
  debit: string;
  credit: string;
  description: string;
}

const CODE_PATTERN = /^[A-Z0-9][A-Z0-9._-]*$/;

let lineCounter = 0;
function createLine(): JournalLine {
  lineCounter += 1;
  return {
    key: lineCounter,
    accountId: "",
    debit: "",
    credit: "",
    description: "",
  };
}

const labelClass = "mb-1.5 block text-xs font-semibold text-ink-700";
const fieldClass =
  "w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 " +
  "placeholder:text-concrete-400 focus:border-ink-950";

/**
 * Alta de comprobantes en `DRAFT`.
 *
 * El indicador de diferencia se calcula en centavos mientras se escriben las
 * líneas; el backend vuelve a validar el equilibrio al publicar el asiento.
 */
export default function JournalEntryForm({
  open,
  onClose,
  onCreated,
}: JournalEntryFormProps) {
  const [code, setCode] = useState("");
  const [entryDate, setEntryDate] = useState(todayIso());
  const [description, setDescription] = useState("");
  const [reference, setReference] = useState("");
  const [lines, setLines] = useState<JournalLine[]>(() => [
    createLine(),
    createLine(),
  ]);
  const [formError, setFormError] = useState<string | null>(null);

  const accountsQuery = useAccounts({ limit: 200, is_active: true });
  const createMutation = useCreateJournalEntry();

  useEffect(() => {
    if (!open) {
      return;
    }
    setCode("");
    setEntryDate(todayIso());
    setDescription("");
    setReference("");
    setLines([createLine(), createLine()]);
    setFormError(null);
  }, [open]);

  const accounts = accountsQuery.data ?? [];
  const debitCents = lines.reduce(
    (total, line) => total + toCents(parseAmount(line.debit) ?? 0),
    0,
  );
  const creditCents = lines.reduce(
    (total, line) => total + toCents(parseAmount(line.credit) ?? 0),
    0,
  );
  const differenceCents = debitCents - creditCents;

  const mutationError = errorMessage(createMutation.error);

  function updateLine(key: number, patch: Partial<JournalLine>) {
    setLines((current) =>
      current.map((line) => (line.key === key ? { ...line, ...patch } : line)),
    );
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);

    const normalizedCode = code.trim().toUpperCase();
    if (!CODE_PATTERN.test(normalizedCode) || normalizedCode.length > 30) {
      setFormError("El código del comprobante debe ser único y usar mayúsculas, dígitos, punto, guion o guion bajo (máximo 30).");
      return;
    }
    if (description.trim() === "") {
      setFormError("La glosa del asiento es obligatoria.");
      return;
    }
    if (lines.length < 2) {
      setFormError("Un asiento requiere al menos dos líneas.");
      return;
    }

    const items: JournalItemCreate[] = [];
    for (const [index, line] of lines.entries()) {
      if (line.accountId === "") {
        setFormError(`Selecciona la cuenta de la línea ${index + 1}.`);
        return;
      }
      const debit = parseAmount(line.debit) ?? 0;
      const credit = parseAmount(line.credit) ?? 0;
      if ((line.debit.trim() !== "" && debit === 0 && !/^0+([.,]0+)?$/.test(line.debit.trim())) ||
          (line.credit.trim() !== "" && credit === 0 && !/^0+([.,]0+)?$/.test(line.credit.trim()))) {
        setFormError(`Revisa el importe de la línea ${index + 1}: usa hasta dos decimales.`);
        return;
      }
      if (debit > 0 && credit > 0) {
        setFormError(`La línea ${index + 1} no puede tener débito y crédito positivos a la vez.`);
        return;
      }
      if (debit === 0 && credit === 0) {
        setFormError(`La línea ${index + 1} debe tener un débito o un crédito.`);
        return;
      }
      const item: JournalItemCreate = {
        account_id: Number(line.accountId),
        debit: moneyString(Math.round(debit * 100)),
        credit: moneyString(Math.round(credit * 100)),
      };
      if (line.description.trim() !== "") {
        item.description = line.description.trim();
      }
      items.push(item);
    }

    const payload = {
      code: normalizedCode,
      entry_date: entryDate,
      description: description.trim(),
      items,
    };
    // El optional exacto de TS exige añadir el campo solo cuando tiene valor.
    if (reference.trim() !== "") {
      Object.assign(payload, { reference_document: reference.trim() });
    }

    createMutation.mutate(payload, { onSuccess: onCreated });
  }

  return (
    <FormSheet
      open={open}
      title="Nuevo asiento contable"
      subtitle="Se guarda como borrador; la partida doble se valida al contabilizar."
      submitLabel="Guardar borrador"
      pendingLabel="Guardando…"
      isPending={createMutation.isPending}
      size="lg"
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <div>
          <label className={labelClass} htmlFor="entry-code">
            Código del comprobante
          </label>
          <input
            id="entry-code"
            value={code}
            onChange={(event) => setCode(event.currentTarget.value.toUpperCase())}
            placeholder="ASI-2026-0001"
            maxLength={30}
            className={fieldClass}
            autoFocus
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="entry-date">
            Fecha contable
          </label>
          <input
            id="entry-date"
            type="date"
            value={entryDate}
            onChange={(event) => setEntryDate(event.currentTarget.value)}
            className={fieldClass}
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="entry-reference">
            Documento de soporte
          </label>
          <input
            id="entry-reference"
            value={reference}
            onChange={(event) => setReference(event.currentTarget.value)}
            maxLength={100}
            placeholder="FAC-2026-0001"
            className={fieldClass}
          />
        </div>
      </div>

      <div>
        <label className={labelClass} htmlFor="entry-description">
          Glosa del asiento
        </label>
        <textarea
          id="entry-description"
          value={description}
          onChange={(event) => setDescription(event.currentTarget.value)}
          rows={2}
          placeholder="Pago de nómina de noviembre"
          className={fieldClass}
        />
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between gap-3">
          <h3 className="text-sm font-bold tracking-tight">Líneas de partida doble</h3>
          <button
            type="button"
            onClick={() => setLines((current) => [...current, createLine()])}
            className="border border-concrete-200 px-2.5 py-1 text-xs font-semibold text-ink-700 hover:border-ink-950 hover:text-ink-950"
          >
            + Agregar línea
          </button>
        </div>

        {accountsQuery.error !== null ? (
          <div role="alert" className="border border-signal-500/40 bg-signal-100 px-3 py-2.5 text-sm">
            <p className="font-semibold text-signal-600">No se pudo cargar el plan de cuentas.</p>
            <p className="mt-1 text-xs text-ink-700">{accountsQuery.error.message}</p>
            <button
              type="button"
              onClick={() => void accountsQuery.refetch()}
              className="mt-2 border border-signal-500 px-2 py-1 text-xs font-semibold text-signal-600 hover:bg-signal-500 hover:text-white"
            >
              Reintentar
            </button>
          </div>
        ) : accountsQuery.isPending ? (
          <p className="border border-concrete-200 bg-white px-3 py-4 text-sm text-ink-500">
            Cargando cuentas activas…
          </p>
        ) : accounts.length === 0 ? (
          <p className="border border-dashed border-concrete-200 bg-white px-3 py-4 text-sm text-ink-500">
            No hay cuentas activas. Crea cuentas en el plan de cuentas antes de registrar un asiento.
          </p>
        ) : (
          <div className="space-y-2">
            {lines.map((line, index) => (
              <div
                key={line.key}
                className="grid gap-2 border border-concrete-200 bg-white p-3 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.2fr)_auto]"
              >
                <div>
                  <label className={labelClass} htmlFor={`line-account-${line.key}`}>
                    Línea {index + 1} · Cuenta
                  </label>
                  <select
                    id={`line-account-${line.key}`}
                    value={line.accountId}
                    onChange={(event) => updateLine(line.key, { accountId: event.currentTarget.value })}
                    className={fieldClass}
                  >
                    <option value="">Seleccionar cuenta</option>
                    {accounts.map((account) => (
                      <option key={account.id} value={account.id}>
                        {account.code} · {account.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className={labelClass} htmlFor={`line-debit-${line.key}`}>
                    Débito
                  </label>
                  <input
                    id={`line-debit-${line.key}`}
                    value={line.debit}
                    onChange={(event) => updateLine(line.key, { debit: event.currentTarget.value })}
                    inputMode="decimal"
                    placeholder="0,00"
                    className={fieldClass}
                  />
                </div>
                <div>
                  <label className={labelClass} htmlFor={`line-credit-${line.key}`}>
                    Crédito
                  </label>
                  <input
                    id={`line-credit-${line.key}`}
                    value={line.credit}
                    onChange={(event) => updateLine(line.key, { credit: event.currentTarget.value })}
                    inputMode="decimal"
                    placeholder="0,00"
                    className={fieldClass}
                  />
                </div>
                <div>
                  <label className={labelClass} htmlFor={`line-description-${line.key}`}>
                    Glosa (opcional)
                  </label>
                  <input
                    id={`line-description-${line.key}`}
                    value={line.description}
                    onChange={(event) => updateLine(line.key, { description: event.currentTarget.value })}
                    maxLength={200}
                    className={fieldClass}
                  />
                </div>
                <div className="flex items-end justify-end">
                  <button
                    type="button"
                    onClick={() =>
                      setLines((current) => current.filter((item) => item.key !== line.key))
                    }
                    disabled={lines.length <= 2}
                    aria-label={`Quitar línea ${index + 1}`}
                    className="h-[38px] border border-concrete-200 px-3 text-sm font-semibold text-ink-500 hover:border-signal-500 hover:text-signal-600 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    ×
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div
        role="status"
        aria-live="polite"
        className="grid grid-cols-3 gap-px border border-concrete-200 bg-concrete-200"
      >
        <div className="bg-white px-3 py-2">
          <p className="text-xs text-ink-500">Total débito</p>
          <p className="mt-0.5 text-lg font-bold tabular-nums">{formatCents(debitCents)}</p>
        </div>
        <div className="bg-white px-3 py-2">
          <p className="text-xs text-ink-500">Total crédito</p>
          <p className="mt-0.5 text-lg font-bold tabular-nums">{formatCents(creditCents)}</p>
        </div>
        <div className="bg-white px-3 py-2">
          <p className="text-xs text-ink-500">Diferencia (débito − crédito)</p>
          <p
            className={[
              "mt-0.5 text-lg font-bold tabular-nums",
              differenceCents === 0 ? "text-pine-600" : "text-clay-600",
            ].join(" ")}
          >
            {differenceCents > 0 ? "+" : ""}
            {formatCents(differenceCents)}
          </p>
        </div>
      </div>
      <p className="text-xs text-ink-500">
        {differenceCents === 0
          ? "Asiento equilibrado: se puede contabilizar después de guardarlo."
          : "El borrador se puede guardar desbalanceado, pero no se podrá contabilizar hasta equilibrarlo."}
      </p>

      {(formError === null && mutationError === null) ? null : (
        <div role="alert" className="border border-signal-500/40 bg-signal-100 px-3 py-2.5 text-sm">
          <p className="font-semibold text-signal-600">{formError ?? mutationError}</p>
          {formError === null && mutationError !== null ? (
            <p className="mt-1 text-xs text-ink-700">{errorHint(mutationError)}</p>
          ) : null}
        </div>
      )}
    </FormSheet>
  );
}
