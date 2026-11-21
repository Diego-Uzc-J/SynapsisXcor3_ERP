import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";

import ActiveSwitch from "../../components/ActiveSwitch";
import FormSheet from "../../components/FormSheet";
import { ACCOUNT_TYPE_LABELS } from "./constants";
import { errorHint, errorMessage } from "./errors";
import { useCreateAccount, useUpdateAccount } from "./hooks";
import { ACCOUNT_TYPES } from "./types";
import type { Account, AccountCreate, AccountType, AccountUpdate } from "./types";

interface AccountFormProps {
  open: boolean;
  /** `null` para crear; una cuenta para editar. */
  account: Account | null;
  /** Catálogo completo, usado para las cuentas madre y evitar ciclos. */
  accounts: Account[];
  onClose: () => void;
  onSaved: (account: Account, mode: "created" | "updated") => void;
}

const CODE_PATTERN = /^[A-Z0-9][A-Z0-9._-]*$/;

const labelClass = "mb-1.5 block text-xs font-semibold text-ink-700";
const fieldClass =
  "w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 " +
  "placeholder:text-concrete-400 focus:border-ink-950";
const hintClass = "mt-1 text-xs text-ink-500";

/** Descendientes de la cuenta en edición: no pueden ser su cuenta madre. */
function descendantIds(accounts: readonly Account[], rootId: number): Set<number> {
  const childrenByParent = new Map<number, number[]>();
  for (const item of accounts) {
    if (item.parent_id === null) {
      continue;
    }
    const children = childrenByParent.get(item.parent_id) ?? [];
    children.push(item.id);
    childrenByParent.set(item.parent_id, children);
  }
  const excluded = new Set<number>();
  const visited = new Set<number>([rootId]);
  const visit = (id: number) => {
    for (const child of childrenByParent.get(id) ?? []) {
      if (visited.has(child)) {
        continue;
      }
      visited.add(child);
      excluded.add(child);
      visit(child);
    }
  };
  visit(rootId);
  return excluded;
}

export default function AccountForm({
  open,
  account,
  accounts,
  onClose,
  onSaved,
}: AccountFormProps) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [accountType, setAccountType] = useState<AccountType>("ASSET");
  const [parentId, setParentId] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [formError, setFormError] = useState<string | null>(null);

  const createMutation = useCreateAccount();
  const updateMutation = useUpdateAccount();

  useEffect(() => {
    if (!open) {
      return;
    }
    setCode(account?.code ?? "");
    setName(account?.name ?? "");
    setAccountType(account?.account_type ?? "ASSET");
    setParentId(account?.parent_id === null || account === null ? "" : String(account.parent_id));
    setIsActive(account?.is_active ?? true);
    setFormError(null);
  }, [open, account]);

  const excludedParents = useMemo(
    () => (account === null ? new Set<number>() : descendantIds(accounts, account.id)),
    [account, accounts],
  );

  const parentOptions = accounts.filter(
    (item) => item.id !== account?.id && !excludedParents.has(item.id),
  );

  const mutationError = errorMessage(createMutation.error ?? updateMutation.error);
  const isPending = createMutation.isPending || updateMutation.isPending;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);

    const normalizedCode = code.trim().toUpperCase();
    if (!CODE_PATTERN.test(normalizedCode) || normalizedCode.length > 30) {
      setFormError("El código debe tener hasta 30 caracteres en mayúsculas, dígitos, punto, guion o guion bajo.");
      return;
    }
    if (name.trim() === "" || name.trim().length > 200) {
      setFormError("El nombre de la cuenta es obligatorio (máximo 200 caracteres).");
      return;
    }

    if (account === null) {
      const payload: AccountCreate = {
        code: normalizedCode,
        name: name.trim(),
        account_type: accountType,
        is_active: isActive,
      };
      if (parentId !== "") {
        payload.parent_id = Number(parentId);
      }
      createMutation.mutate(payload, {
        onSuccess: (created) => onSaved(created, "created"),
      });
      return;
    }

    const payload: AccountUpdate = {
      code: normalizedCode,
      name: name.trim(),
      account_type: accountType,
      parent_id: parentId === "" ? null : Number(parentId),
      is_active: isActive,
    };
    updateMutation.mutate(
      { accountId: account.id, payload },
      { onSuccess: (updated) => onSaved(updated, "updated") },
    );
  }

  return (
    <FormSheet
      open={open}
      title={account === null ? "Nueva cuenta contable" : "Editar cuenta contable"}
      subtitle="Código único del Plan Único de Cuentas y jerarquía opcional."
      submitLabel={account === null ? "Crear cuenta" : "Guardar cambios"}
      pendingLabel="Guardando…"
      isPending={isPending}
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <div>
        <label className={labelClass} htmlFor="account-code">
          Código
        </label>
        <input
          id="account-code"
          value={code}
          onChange={(event) => setCode(event.currentTarget.value.toUpperCase())}
          placeholder="110505"
          maxLength={30}
          className={fieldClass}
          autoFocus
        />
        <p className={hintClass}>Ejemplos: 110505 (Caja General), 4135 (Ventas).</p>
      </div>

      <div>
        <label className={labelClass} htmlFor="account-name">
          Nombre
        </label>
        <input
          id="account-name"
          value={name}
          onChange={(event) => setName(event.currentTarget.value)}
          placeholder="Caja General"
          maxLength={200}
          className={fieldClass}
        />
      </div>

      <div>
        <label className={labelClass} htmlFor="account-type">
          Tipo de cuenta
        </label>
        <select
          id="account-type"
          value={accountType}
          onChange={(event) => setAccountType(event.currentTarget.value as AccountType)}
          className={fieldClass}
        >
          {ACCOUNT_TYPES.map((type) => (
            <option key={type} value={type}>
              {ACCOUNT_TYPE_LABELS[type]}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className={labelClass} htmlFor="account-parent">
          Cuenta madre
        </label>
        <select
          id="account-parent"
          value={parentId}
          onChange={(event) => setParentId(event.currentTarget.value)}
          className={fieldClass}
        >
          <option value="">Ninguna (cuenta raíz)</option>
          {parentOptions.map((item) => (
            <option key={item.id} value={item.id}>
              {item.code} · {item.name}
            </option>
          ))}
        </select>
        <p className={hintClass}>
          Las cuentas con movimientos no se eliminan: se desactivan para impedir nuevos asientos.
        </p>
      </div>

      <ActiveSwitch
        checked={isActive}
        onChange={setIsActive}
        label="Cuenta activa"
        hint="Una cuenta inactiva no admite nuevas líneas de diario."
      />

      {(formError === null && mutationError === null) ? null : (
        <div role="alert" className="border border-signal-500/40 bg-signal-100 px-3 py-2.5 text-sm">
          <p className="font-semibold text-signal-600">{formError ?? mutationError}</p>
          {(formError === null ? errorHint(mutationError ?? "") : null)?.length ? (
            <p className="mt-1 text-xs text-ink-700">
              {errorHint(mutationError ?? "")}
            </p>
          ) : null}
        </div>
      )}
    </FormSheet>
  );
}
