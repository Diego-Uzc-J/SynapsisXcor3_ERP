import { useEffect, useId, useState } from "react";
import type { FormEvent } from "react";

import AccountingDialog from "./AccountingDialog";
import { errorHint, errorMessage } from "./errors";
import { formatCents, formatMoney, moneyString, parseAmount, todayIso } from "./format";
import {
  useRegisterPayablePayment,
  useRegisterReceivablePayment,
} from "./hooks";
import type { PaymentRecordRequest } from "./types";

export interface PaymentTarget {
  kind: "receivable" | "payable";
  id: number;
  title: string;
  subtitle: string;
  total: string;
  paid: string;
  balanceCents: number;
}

interface PaymentFormProps {
  open: boolean;
  target: PaymentTarget | null;
  onClose: () => void;
  onDone: (message: string) => void;
}

const labelClass = "mb-1.5 block text-xs font-semibold text-ink-700";
const fieldClass =
  "w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 " +
  "placeholder:text-concrete-400 focus:border-ink-950";

export default function PaymentForm({
  open,
  target,
  onClose,
  onDone,
}: PaymentFormProps) {
  const formId = useId();
  const [amount, setAmount] = useState("");
  const [paymentDate, setPaymentDate] = useState(todayIso());
  const [reference, setReference] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const receivableMutation = useRegisterReceivablePayment();
  const payableMutation = useRegisterPayablePayment();

  useEffect(() => {
    if (!open || target === null) {
      return;
    }
    setAmount(moneyString(target.balanceCents));
    setPaymentDate(todayIso());
    setReference("");
    setFormError(null);
  }, [open, target]);

  const isPending =
    receivableMutation.isPending || payableMutation.isPending;
  const mutationError = errorMessage(
    receivableMutation.error ?? payableMutation.error,
  );

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    if (target === null) {
      return;
    }

    const parsed = parseAmount(amount);
    const amountCents = parsed === null ? 0 : Math.round(parsed * 100);
    if (parsed === null || amountCents <= 0) {
      setFormError("Ingresa un monto positivo con hasta dos decimales.");
      return;
    }
    if (amountCents > target.balanceCents) {
      setFormError(
        `El monto supera el saldo pendiente de ${formatCents(target.balanceCents)}.`,
      );
      return;
    }

    const payload: PaymentRecordRequest = {
      amount: moneyString(amountCents),
      payment_date: paymentDate,
    };
    if (reference.trim() !== "") {
      payload.reference = reference.trim();
    }

    if (target.kind === "receivable") {
      receivableMutation.mutate(
        { receivableId: target.id, payload },
        {
          onSuccess: (record) =>
            onDone(
              `Cobro de ${formatMoney(record.amount)} registrado${
                record.journal_entry_id === null
                  ? ""
                  : ` (asiento #${record.journal_entry_id})`
              }.`,
            ),
        },
      );
      return;
    }

    payableMutation.mutate(
      { payableId: target.id, payload },
      {
        onSuccess: (record) =>
          onDone(
            `Pago de ${formatMoney(record.amount)} registrado${
              record.journal_entry_id === null
                ? ""
                : ` (asiento #${record.journal_entry_id})`
            }.`,
          ),
      },
    );
  }

  return (
    <AccountingDialog
      open={open}
      title={target?.kind === "payable" ? "Registrar pago" : "Registrar cobro"}
      subtitle={target === null ? undefined : `${target.title} · ${target.subtitle}`}
      onClose={onClose}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="border border-concrete-200 px-4 py-2 text-sm font-semibold text-ink-700 hover:border-ink-500 hover:text-ink-950"
          >
            Cancelar
          </button>
          <button
            type="submit"
            form={formId}
            disabled={isPending || target === null || target.balanceCents <= 0}
            className="bg-signal-500 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-signal-600 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isPending ? "Registrando…" : "Registrar abono"}
          </button>
        </>
      }
    >
      {target === null ? null : (
        <form id={formId} onSubmit={handleSubmit} noValidate className="space-y-4">
          <dl className="grid grid-cols-3 gap-px border border-concrete-200 bg-concrete-200 text-sm">
            <div className="bg-white px-3 py-2">
              <dt className="text-xs text-ink-500">Total</dt>
              <dd className="mt-0.5 font-semibold tabular-nums">{formatMoney(target.total)}</dd>
            </div>
            <div className="bg-white px-3 py-2">
              <dt className="text-xs text-ink-500">Pagado</dt>
              <dd className="mt-0.5 font-semibold tabular-nums">{formatMoney(target.paid)}</dd>
            </div>
            <div className="bg-white px-3 py-2">
              <dt className="text-xs text-ink-500">Saldo</dt>
              <dd className="mt-0.5 font-semibold tabular-nums text-signal-600">
                {formatCents(target.balanceCents)}
              </dd>
            </div>
          </dl>

          <div>
            <label className={labelClass} htmlFor="payment-amount">
              Monto del abono
            </label>
            <input
              id="payment-amount"
              value={amount}
              onChange={(event) => setAmount(event.currentTarget.value)}
              inputMode="decimal"
              placeholder="0,00"
              className={fieldClass}
              autoFocus
            />
            <p className="mt-1 text-xs text-ink-500">Máximo: {formatCents(target.balanceCents)}.</p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className={labelClass} htmlFor="payment-date">
                Fecha de pago
              </label>
              <input
                id="payment-date"
                type="date"
                value={paymentDate}
                onChange={(event) => setPaymentDate(event.currentTarget.value)}
                className={fieldClass}
              />
            </div>
            <div>
              <label className={labelClass} htmlFor="payment-reference">
                Referencia (opcional)
              </label>
              <input
                id="payment-reference"
                value={reference}
                onChange={(event) => setReference(event.currentTarget.value)}
                maxLength={100}
                placeholder="Comprobante o transferencia"
                className={fieldClass}
              />
            </div>
          </div>

          {(formError === null && mutationError === null) ? null : (
            <div role="alert" className="border border-signal-500/40 bg-signal-100 px-3 py-2.5 text-sm">
              <p className="font-semibold text-signal-600">{formError ?? mutationError}</p>
              {formError === null && mutationError !== null ? (
                <p className="mt-1 text-xs text-ink-700">{errorHint(mutationError)}</p>
              ) : null}
            </div>
          )}
        </form>
      )}
    </AccountingDialog>
  );
}
