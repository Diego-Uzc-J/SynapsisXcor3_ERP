import { useState } from "react";
import { Link } from "react-router-dom";

import { canWriteModule, useAuth } from "../../store/authStore";
import { CONTRACT_TYPE_LABELS, employeeFullName } from "./constants";
import ContractForm from "./ContractForm";
import { errorMessage } from "./errors";
import { formatDate, formatMoney } from "./format";
import {
  useContractsByEmployee,
  useEmployees,
} from "./hooks";
import HrTabs from "./HrTabs";
import StatusBadge from "./StatusBadge";

type Feedback = { tone: "success" | "error"; text: string };

export default function ContractsPage() {
  const { user } = useAuth();
  const canWrite = canWriteModule(user, "hr");

  const [selectedId, setSelectedId] = useState<number>(0);
  const [formOpen, setFormOpen] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  const employeesQuery = useEmployees({ limit: 200 });
  const employees = employeesQuery.data ?? [];
  const selectedEmployee = employees.find(
    (employee) => employee.id === selectedId,
  );
  const historyQuery = useContractsByEmployee(selectedId, {}, selectedId > 0);
  const activeQuery = useContractsByEmployee(
    selectedId,
    { active_only: true },
    selectedId > 0,
  );
  const contracts = historyQuery.data ?? [];
  const hasActiveContract = (activeQuery.data ?? []).length > 0;

  const message =
    errorMessage(employeesQuery.error) ?? errorMessage(historyQuery.error);

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <header className="flex flex-col gap-6 border-b-2 border-ink-950 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
            Condiciones laborales
          </p>
          <h1 className="mt-2 text-4xl font-extrabold tracking-tight sm:text-5xl">
            Contratos
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-700">
            Cada empleado puede tener un solo contrato vigente. Los contratos
            anteriores se conservan como historial y alimentan el expediente.
          </p>
        </div>
        {canWrite ? (
          <button
            type="button"
            onClick={() => {
              setFeedback(null);
              setFormOpen(true);
            }}
            className="inline-flex shrink-0 items-center justify-center gap-2 bg-signal-500 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-signal-600"
          >
            <span aria-hidden="true" className="text-lg leading-none">
              +
            </span>
            Nuevo contrato
          </button>
        ) : null}
      </header>

      <HrTabs />

      <div className="mt-6 flex flex-wrap items-end gap-4 border border-concrete-200 bg-white p-4">
        <div className="min-w-[260px] flex-1">
          <label
            className="mb-1 block text-xs font-semibold text-ink-700"
            htmlFor="hr-contracts-employee"
          >
            Empleado
          </label>
          <select
            id="hr-contracts-employee"
            className="w-full border border-concrete-200 bg-white px-3 py-2 text-sm focus:border-signal-500 focus:outline-none"
            value={selectedId}
            onChange={(event) => {
              setSelectedId(Number(event.target.value));
              setFeedback(null);
            }}
          >
            <option value={0}>Selecciona un empleado</option>
            {employees.map((employee) => (
              <option key={employee.id} value={employee.id}>
                {employeeFullName(employee)} · {employee.identification_number}
              </option>
            ))}
          </select>
        </div>
        {selectedEmployee === undefined ? null : (
          <Link
            className="pb-2 text-xs font-semibold text-signal-600 hover:underline"
            to={`/hr/employees/${selectedEmployee.id}`}
          >
            Ver expediente →
          </Link>
        )}
      </div>

      {feedback === null ? null : (
        <p className="mt-4 border border-pine-500 bg-pine-50 px-4 py-3 text-sm text-pine-700">
          {feedback.text}
        </p>
      )}

      {message === null ? null : (
        <div className="mt-4 border border-signal-500/40 bg-signal-100 px-4 py-3 text-sm text-ink-900">
          {message}
        </div>
      )}

      {selectedId === 0 ? (
        <p className="mt-5 border border-dashed border-concrete-200 bg-white px-4 py-10 text-center text-sm text-ink-500">
          Selecciona un empleado para consultar su historial de contratos.
        </p>
      ) : (
        <section className="mt-5 border border-concrete-200 bg-white">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-concrete-200 px-4 py-3">
            <h2 className="text-sm font-bold">
              Historial de {selectedEmployee === undefined ? `#${selectedId}` : employeeFullName(selectedEmployee)}
            </h2>
            <StatusBadge
              label={hasActiveContract ? "Contrato vigente" : "Sin contrato vigente"}
              tone={hasActiveContract ? "success" : "warning"}
            />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                  <th scope="col" className="px-4 py-2.5">Tipo</th>
                  <th scope="col" className="px-4 py-2.5">Inicio</th>
                  <th scope="col" className="px-4 py-2.5">Fin</th>
                  <th scope="col" className="px-4 py-2.5 text-right">Salario base</th>
                  <th scope="col" className="px-4 py-2.5">Estado</th>
                </tr>
              </thead>
              <tbody>
                {historyQuery.isPending ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-ink-500">
                      Cargando contratos…
                    </td>
                  </tr>
                ) : contracts.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-ink-500">
                      Este empleado todavía no tiene contratos registrados.
                    </td>
                  </tr>
                ) : (
                  contracts.map((contract) => (
                    <tr
                      key={contract.id}
                      className="border-b border-concrete-100 last:border-b-0"
                    >
                      <td className="px-4 py-2.5">
                        {CONTRACT_TYPE_LABELS[contract.contract_type]}
                      </td>
                      <td className="px-4 py-2.5 text-xs">
                        {formatDate(contract.start_date)}
                      </td>
                      <td className="px-4 py-2.5 text-xs">
                        {contract.end_date === null
                          ? "Indefinido"
                          : formatDate(contract.end_date)}
                      </td>
                      <td className="px-4 py-2.5 text-right font-semibold tabular-nums">
                        {formatMoney(contract.base_salary)}
                      </td>
                      <td className="px-4 py-2.5">
                        <StatusBadge
                          label={contract.is_active ? "Vigente" : "Histórico"}
                          tone={contract.is_active ? "success" : "muted"}
                        />
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <ContractForm
        open={formOpen}
        employees={employees}
        employeeId={selectedId === 0 ? null : selectedId}
        hasActiveContract={hasActiveContract}
        onClose={() => setFormOpen(false)}
        onSaved={(_contract, employeeName) => {
          setFormOpen(false);
          setFeedback({
            tone: "success",
            text: `Contrato registrado para ${employeeName}.`,
          });
        }}
      />
    </div>
  );
}
