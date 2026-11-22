import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { useProducts } from "../../api/inventory";
import type { Product } from "../../api/inventory";
import FormSheet from "../../components/FormSheet";
import { errorHint, errorMessage } from "./errors";
import { decimalString, formatMoney, percentString } from "./format";
import { useCreateBom } from "./hooks";
import type { Bom } from "./types";

interface BomFormProps {
  open: boolean;
  onClose: () => void;
  onSaved: (bom: Bom) => void;
}

interface BomLine {
  key: number;
  componentProductId: string;
  quantity: string;
  scrapPercentage: string;
}

const CODE_PATTERN = /^[A-Z0-9][A-Z0-9._-]*$/;
const labelClass = "mb-1.5 block text-xs font-semibold text-ink-700";
const fieldClass =
  "w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 " +
  "placeholder:text-concrete-400 focus:border-signal-500 focus:outline-none";

let lineCounter = 0;
function createLine(): BomLine {
  lineCounter += 1;
  return {
    key: lineCounter,
    componentProductId: "",
    quantity: "1.00",
    scrapPercentage: "0.00",
  };
}

function productLabel(product: Product): string {
  return `${product.sku} · ${product.name}`;
}

/** Alta de una receta con al menos un componente y merma opcional. */
export default function BomForm({ open, onClose, onSaved }: BomFormProps) {
  const [code, setCode] = useState("");
  const [productId, setProductId] = useState("");
  const [version, setVersion] = useState("1");
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<BomLine[]>(() => [createLine()]);
  const [validationError, setValidationError] = useState<string | null>(null);

  const productsQuery = useProducts({ limit: 200, is_active: true });
  const createMutation = useCreateBom();
  const products = productsQuery.data ?? [];

  useEffect(() => {
    if (open) {
      setCode("");
      setProductId("");
      setVersion("1");
      setName("");
      setNotes("");
      setLines([createLine()]);
      setValidationError(null);
    }
  }, [open]);

  function updateLine(key: number, patch: Partial<BomLine>) {
    setLines((current) =>
      current.map((line) => (line.key === key ? { ...line, ...patch } : line)),
    );
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setValidationError(null);

    const normalizedCode = code.trim().toUpperCase();
    if (!CODE_PATTERN.test(normalizedCode) || normalizedCode.length > 50) {
      setValidationError(
        "El código debe empezar por letra o dígito y usar mayúsculas, números, puntos, guiones o guiones bajos.",
      );
      return;
    }
    if (productId === "") {
      setValidationError("Selecciona el producto terminado que produce la receta.");
      return;
    }
    const parsedVersion = Number(version);
    if (!Number.isInteger(parsedVersion) || parsedVersion < 1) {
      setValidationError("La versión debe ser un entero mayor o igual que 1.");
      return;
    }

    const items = [];
    const usedComponents = new Set<number>();
    for (const line of lines) {
      const componentProductId = Number(line.componentProductId);
      if (!Number.isInteger(componentProductId) || componentProductId <= 0) {
        setValidationError("Todas las líneas deben indicar un componente.");
        return;
      }
      if (usedComponents.has(componentProductId)) {
        setValidationError("No se puede repetir el mismo componente en una BOM.");
        return;
      }
      usedComponents.add(componentProductId);

      const quantity = decimalString(line.quantity);
      const scrapPercentage = percentString(line.scrapPercentage);
      if (quantity === null || Number(quantity) <= 0 || scrapPercentage === null) {
        setValidationError(
          "Cada componente exige una cantidad mayor que cero y una merma entre 0 y 100.",
        );
        return;
      }
      items.push({ componentProductId, quantity, scrapPercentage });
    }

    createMutation.mutate(
      {
        code: normalizedCode,
        product_id: Number(productId),
        version: parsedVersion,
        name: name.trim() === "" ? null : name.trim(),
        is_active: true,
        notes: notes.trim() === "" ? null : notes.trim(),
        items: items.map((item) => ({
          component_product_id: item.componentProductId,
          quantity: item.quantity,
          scrap_percentage: item.scrapPercentage,
        })),
      },
      { onSuccess: onSaved },
    );
  }

  const message = errorMessage(createMutation.error);

  return (
    <FormSheet
      open={open}
      title="Nueva lista de materiales"
      subtitle="Define el producto terminado y los insumos necesarios por unidad."
      submitLabel="Crear BOM"
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
          <label className={labelClass} htmlFor="mfg-bom-code">
            Código *
          </label>
          <input
            id="mfg-bom-code"
            className={fieldClass}
            value={code}
            onChange={(event) => setCode(event.target.value)}
            placeholder="BOM-LAP-IND-01"
            maxLength={50}
            required
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="mfg-bom-version">
            Versión *
          </label>
          <input
            id="mfg-bom-version"
            type="number"
            min={1}
            step={1}
            className={fieldClass}
            value={version}
            onChange={(event) => setVersion(event.target.value)}
            required
          />
        </div>
      </div>

      <div>
        <label className={labelClass} htmlFor="mfg-bom-product">
          Producto terminado *
        </label>
        <select
          id="mfg-bom-product"
          className={fieldClass}
          value={productId}
          onChange={(event) => setProductId(event.target.value)}
          required
        >
          <option value="">Selecciona un producto del catálogo</option>
          {products.map((product) => (
            <option key={product.id} value={product.id}>
              {productLabel(product)}
            </option>
          ))}
        </select>
        {productsQuery.isPending ? (
          <p className="mt-1 text-xs text-ink-500">Cargando catálogo…</p>
        ) : null}
      </div>

      <div>
        <label className={labelClass} htmlFor="mfg-bom-name">
          Descripción
        </label>
        <input
          id="mfg-bom-name"
          className={fieldClass}
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Receta de ensamble"
          maxLength={200}
        />
      </div>

      <section>
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-sm font-bold tracking-tight">Componentes *</h3>
          <button
            type="button"
            onClick={() => setLines((current) => [...current, createLine()])}
            className="border border-concrete-200 px-3 py-1.5 text-xs font-semibold text-ink-700 hover:border-ink-500"
          >
            + Añadir componente
          </button>
        </div>
        <p className="mt-1 text-xs text-ink-500">
          Cantidad por unidad terminada; la merma se aplica al iniciar la orden.
        </p>

        <div className="mt-3 space-y-3">
          {lines.map((line, index) => {
            const selected = products.find(
              (product) => product.id === Number(line.componentProductId),
            );
            return (
              <div
                key={line.key}
                className="border border-concrete-200 bg-white p-3"
              >
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs font-semibold text-ink-700">
                    Componente {index + 1}
                  </p>
                  <button
                    type="button"
                    onClick={() =>
                      setLines((current) =>
                        current.filter((item) => item.key !== line.key),
                      )
                    }
                    disabled={lines.length === 1}
                    className="text-xs font-semibold text-signal-600 hover:underline disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    Quitar
                  </button>
                </div>
                <div className="mt-2 grid gap-2 sm:grid-cols-[2fr_1fr_1fr]">
                  <select
                    aria-label={`Componente ${index + 1}`}
                    className={fieldClass}
                    value={line.componentProductId}
                    onChange={(event) =>
                      updateLine(line.key, {
                        componentProductId: event.target.value,
                      })
                    }
                    required
                  >
                    <option value="">Selecciona insumo</option>
                    {products.map((product) => (
                      <option key={product.id} value={product.id}>
                        {productLabel(product)}
                      </option>
                    ))}
                  </select>
                  <input
                    aria-label={`Cantidad del componente ${index + 1}`}
                    inputMode="decimal"
                    className={fieldClass}
                    value={line.quantity}
                    onChange={(event) =>
                      updateLine(line.key, { quantity: event.target.value })
                    }
                    placeholder="1.00"
                    required
                  />
                  <input
                    aria-label={`Merma del componente ${index + 1}`}
                    inputMode="decimal"
                    className={fieldClass}
                    value={line.scrapPercentage}
                    onChange={(event) =>
                      updateLine(line.key, {
                        scrapPercentage: event.target.value,
                      })
                    }
                    placeholder="0.00"
                    required
                  />
                </div>
                <p className="mt-1 text-xs text-ink-500">
                  {selected === undefined
                    ? "Cantidad · merma (%)"
                    : `Precio referencia ${formatMoney(selected.unit_price)}`}
                </p>
              </div>
            );
          })}
        </div>
      </section>

      <div>
        <label className={labelClass} htmlFor="mfg-bom-notes">
          Observaciones
        </label>
        <textarea
          id="mfg-bom-notes"
          className={fieldClass}
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          rows={3}
          placeholder="Instrucciones especiales de ensamble"
        />
      </div>
    </FormSheet>
  );
}
