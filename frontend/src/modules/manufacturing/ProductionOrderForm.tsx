import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { useWarehouses } from "../../api/inventory";
import FormSheet from "../../components/FormSheet";
import { errorHint, errorMessage } from "./errors";
import { decimalString } from "./format";
import { useBoms, useCreateProductionOrder, useWorkCenters } from "./hooks";
import type { ProductionOrder } from "./types";

interface ProductionOrderFormProps {
  open: boolean;
  /** BOM preseleccionada al llegar desde el detalle de una receta. */
  defaultBomId: number | null;
  onClose: () => void;
  onSaved: (order: ProductionOrder) => void;
}

interface FormState {
  code: string;
  bomId: string;
  workCenterId: string;
  warehouseSourceId: string;
  warehouseDestinationId: string;
  quantity: string;
  estimatedHours: string;
}

const CODE_PATTERN = /^[A-Z0-9][A-Z0-9._-]*$/;
const labelClass = "mb-1.5 block text-xs font-semibold text-ink-700";
const fieldClass =
  "w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 " +
  "placeholder:text-concrete-400 focus:border-signal-500 focus:outline-none";

/** Alta de una OP en `PLANNED`; el backend fija el código si se omite. */
export default function ProductionOrderForm({
  open,
  defaultBomId,
  onClose,
  onSaved,
}: ProductionOrderFormProps) {
  const [form, setForm] = useState<FormState>(() => initialState(defaultBomId));
  const [validationError, setValidationError] = useState<string | null>(null);

  const bomsQuery = useBoms({ is_active: true, limit: 200 });
  const centersQuery = useWorkCenters({ is_active: true, limit: 200 });
  const warehousesQuery = useWarehouses({ active_only: true, limit: 200 });
  const createMutation = useCreateProductionOrder();

  useEffect(() => {
    if (open) {
      setForm(initialState(defaultBomId));
      setValidationError(null);
    }
  }, [open, defaultBomId]);

  function setField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setValidationError(null);

    const code = form.code.trim().toUpperCase();
    if (code !== "" && (!CODE_PATTERN.test(code) || code.length > 30)) {
      setValidationError(
        "El código debe usar mayúsculas, números, puntos, guiones o guiones bajos (máximo 30).",
      );
      return;
    }
    if (form.bomId === "") {
      setValidationError("Selecciona una BOM vigente para la orden.");
      return;
    }
    if (
      form.warehouseSourceId === "" ||
      form.warehouseDestinationId === "" ||
      form.warehouseSourceId === form.warehouseDestinationId
    ) {
      setValidationError(
        "Selecciona bodegas de origen y destino distintas para los movimientos.",
      );
      return;
    }
    const quantity = decimalString(form.quantity);
    if (quantity === null || Number(quantity) <= 0) {
      setValidationError("La cantidad a producir debe ser mayor que cero.");
      return;
    }
    const estimatedHours = decimalString(form.estimatedHours);
    if (estimatedHours === null) {
      setValidationError("Las horas estimadas deben ser un número no negativo.");
      return;
    }

    createMutation.mutate(
      {
        code: code === "" ? null : code,
        bom_id: Number(form.bomId),
        work_center_id:
          form.workCenterId === "" ? null : Number(form.workCenterId),
        warehouse_source_id: Number(form.warehouseSourceId),
        warehouse_destination_id: Number(form.warehouseDestinationId),
        quantity_to_produce: quantity,
        estimated_hours: estimatedHours,
      },
      { onSuccess: onSaved },
    );
  }

  const message = errorMessage(createMutation.error);
  const boms = bomsQuery.data ?? [];
  const centers = centersQuery.data ?? [];
  const warehouses = warehousesQuery.data ?? [];

  return (
    <FormSheet
      open={open}
      title="Nueva orden de producción"
      subtitle="Se crea en estado Planificada; el inventario se consume al iniciarla."
      submitLabel="Crear orden"
      pendingLabel="Creando…"
      isPending={createMutation.isPending}
      size="lg"
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

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelClass} htmlFor="mfg-order-code">
            Código (opcional)
          </label>
          <input
            id="mfg-order-code"
            className={fieldClass}
            value={form.code}
            onChange={(event) => setField("code", event.target.value)}
            placeholder="Se genera automáticamente"
            maxLength={30}
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="mfg-order-bom">
            BOM vigente *
          </label>
          <select
            id="mfg-order-bom"
            className={fieldClass}
            value={form.bomId}
            onChange={(event) => setField("bomId", event.target.value)}
            required
          >
            <option value="">Selecciona una receta</option>
            {boms.map((bom) => (
              <option key={bom.id} value={bom.id}>
                {bom.code} · v{bom.version}
              </option>
            ))}
          </select>
          {bomsQuery.isPending ? (
            <p className="mt-1 text-xs text-ink-500">Cargando BOM…</p>
          ) : null}
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelClass} htmlFor="mfg-order-quantity">
            Cantidad a producir *
          </label>
          <input
            id="mfg-order-quantity"
            inputMode="decimal"
            className={fieldClass}
            value={form.quantity}
            onChange={(event) => setField("quantity", event.target.value)}
            placeholder="10.00"
            required
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="mfg-order-hours">
            Horas estimadas
          </label>
          <input
            id="mfg-order-hours"
            inputMode="decimal"
            className={fieldClass}
            value={form.estimatedHours}
            onChange={(event) => setField("estimatedHours", event.target.value)}
            placeholder="0.00"
          />
        </div>
      </div>

      <div>
        <label className={labelClass} htmlFor="mfg-order-center">
          Centro de trabajo (opcional)
        </label>
        <select
          id="mfg-order-center"
          className={fieldClass}
          value={form.workCenterId}
          onChange={(event) => setField("workCenterId", event.target.value)}
        >
          <option value="">Sin centro asignado</option>
          {centers.map((center) => (
            <option key={center.id} value={center.id}>
              {center.code} · {center.name}
            </option>
          ))}
        </select>
        <p className="mt-1 text-xs text-ink-500">
          Su coste por hora se usa para calcular la mano de obra al completar.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelClass} htmlFor="mfg-order-source">
            Bodega de origen *
          </label>
          <select
            id="mfg-order-source"
            className={fieldClass}
            value={form.warehouseSourceId}
            onChange={(event) =>
              setField("warehouseSourceId", event.target.value)
            }
            required
          >
            <option value="">Selecciona bodega</option>
            {warehouses.map((warehouse) => (
              <option key={warehouse.id} value={warehouse.id}>
                {warehouse.code} · {warehouse.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelClass} htmlFor="mfg-order-destination">
            Bodega de destino *
          </label>
          <select
            id="mfg-order-destination"
            className={fieldClass}
            value={form.warehouseDestinationId}
            onChange={(event) =>
              setField("warehouseDestinationId", event.target.value)
            }
            required
          >
            <option value="">Selecciona bodega</option>
            {warehouses.map((warehouse) => (
              <option key={warehouse.id} value={warehouse.id}>
                {warehouse.code} · {warehouse.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="border border-concrete-200 bg-white px-4 py-3 text-xs leading-relaxed text-ink-700">
        Al iniciar se validará el stock de todos los componentes de la BOM
        (incluida la merma). Al completar se generará el ingreso de producto
        terminado, los costes y el asiento contable en una sola transacción.
      </div>
    </FormSheet>
  );
}

function initialState(defaultBomId: number | null): FormState {
  return {
    code: "",
    bomId: defaultBomId !== null && defaultBomId > 0 ? String(defaultBomId) : "",
    workCenterId: "",
    warehouseSourceId: "",
    warehouseDestinationId: "",
    quantity: "1.00",
    estimatedHours: "0.00",
  };
}
