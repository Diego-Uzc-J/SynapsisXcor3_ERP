import { useDeferredValue, useState } from "react";
import { Link } from "react-router-dom";

import { canWriteModule, useAuth } from "../../store/authStore";
import EmployeeForm from "./EmployeeForm";
import { errorHint, errorMessage } from "./errors";
import { formatDate, formatMoney } from "./format";
import { useEmployees } from "./hooks";
import HrTabs from "./HrTabs";
import StatusBadge from "./StatusBadge";
import type { Employee } from "./types";

const PAGE_SIZE = 15;

type ActiveFilter = "all" | "active" | "inactive";
type Feedback = { tone: "success" | "error"; text: string };

function activeContractSalary(employee: Employee): string | null {
  const contract = employee.contracts.find((item) => item.is_active);
  return contract === undefined ? null : contract.base_salary;
}

export default function EmployeeList() {
  const { user } = useAuth();
  const canWrite = canWriteModule(user, "hr");

  const [activeFilter, setActiveFilter] = useState<ActiveFilter>("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Employee | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  const deferredSearch = useDeferredValue(search.trim().toLowerCase());
  const filters = {
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
    ...(activeFilter === "all"
      ? {}
      : { is_active: activeFilter === "active" }),
  };
  const employeesQuery = useEmployees(filters);
  const employees = employeesQuery.data ?? [];
  const visible = employees.filter((employee) => {
    if (deferredSearch === "") {
      return true;
    }
    return `${employee.first_name} ${employee.last_name} ${employee.identification_number} ${employee.email}`
      .toLowerCase()
      .includes(deferredSearch);
  });

  const queryMessage = errorMessage(employeesQuery.error);

  function openCreate() {
    setEditing(null);
    setFeedback(null);
    setFormOpen(true);
  }

  function openEdit(employee: Employee) {
    setEditing(employee);
    setFeedback(null);
    setFormOpen(true);
  }

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <header className="flex flex-col gap-6 border-b-2 border-ink-950 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
            Gestión de personal
          </p>
          <h1 className="mt-2 text-4xl font-extrabold tracking-tight sm:text-5xl">
            Empleados
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-700">
            Expedientes, contratos e historial de asistencia. Solo los empleados
            activos con contrato vigente se incluyen en nuevas nóminas.
          </p>
        </div>
        {canWrite ? (
          <button
            type="button"
            onClick={openCreate}
            className="inline-flex shrink-0 items-center justify-center gap-2 bg-signal-500 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-signal-600"
          >
            <span aria-hidden="true" className="text-lg leading-none">
              +
            </span>
            Nuevo empleado
          </button>
        ) : null}
      </header>

      <HrTabs />

      <div className="mt-6 flex flex-wrap gap-3 border border-concrete-200 bg-white p-4">
        <div className="min-w-[220px] flex-1">
          <label
            className="mb-1 block text-xs font-semibold text-ink-700"
            htmlFor="hr-employee-search"
          >
            Buscar en la página
          </label>
          <input
            id="hr-employee-search"
            className="w-full border border-concrete-200 px-3 py-2 text-sm focus:border-signal-500 focus:outline-none"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Nombre, documento o correo"
          />
        </div>
        <div className="w-full sm:w-52">
          <label
            className="mb-1 block text-xs font-semibold text-ink-700"
            htmlFor="hr-employee-active"
          >
            Estado
          </label>
          <select
            id="hr-employee-active"
            className="w-full border border-concrete-200 bg-white px-3 py-2 text-sm focus:border-signal-500 focus:outline-none"
            value={activeFilter}
            onChange={(event) => {
              setActiveFilter(event.target.value as ActiveFilter);
              setPage(0);
            }}
          >
            <option value="all">Todos</option>
            <option value="active">Activos</option>
            <option value="inactive">Inactivos</option>
          </select>
        </div>
      </div>

      {feedback === null ? null : (
        <p
          className={[
            "mt-4 border px-4 py-3 text-sm",
            feedback.tone === "success"
              ? "border-pine-500 bg-pine-50 text-pine-700"
              : "border-signal-500/40 bg-signal-100 text-ink-900",
          ].join(" ")}
        >
          {feedback.text}
        </p>
      )}

      {queryMessage === null ? null : (
        <div className="mt-4 border border-signal-500/40 bg-signal-100 px-4 py-3 text-sm text-ink-900">
          <p className="font-semibold">{queryMessage}</p>
          <p className="mt-1 text-xs text-ink-700">{errorHint(queryMessage)}</p>
        </div>
      )}

      <div className="mt-5 border border-concrete-200 bg-white">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                <th scope="col" className="px-4 py-2.5">
                  Empleado
                </th>
                <th scope="col" className="px-4 py-2.5">
                  Contacto
                </th>
                <th scope="col" className="px-4 py-2.5">
                  Ingreso
                </th>
                <th scope="col" className="px-4 py-2.5">
                  Contrato vigente
                </th>
                <th scope="col" className="px-4 py-2.5">
                  Estado
                </th>
                <th scope="col" className="px-4 py-2.5 text-right">
                  Acciones
                </th>
              </tr>
            </thead>
            <tbody>
              {employeesQuery.isPending ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-ink-500">
                    Cargando empleados…
                  </td>
                </tr>
              ) : visible.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-ink-500">
                    No hay empleados para los filtros seleccionados.
                  </td>
                </tr>
              ) : (
                visible.map((employee) => {
                  const salary = activeContractSalary(employee);
                  return (
                    <tr
                      key={employee.id}
                      className="border-b border-concrete-100 last:border-b-0"
                    >
                      <td className="px-4 py-3">
                        <Link
                          className="font-semibold text-ink-950 hover:text-signal-600 hover:underline"
                          to={`/hr/employees/${employee.id}`}
                        >
                          {employee.first_name} {employee.last_name}
                        </Link>
                        <p className="text-xs text-ink-500">
                          {employee.identification_number}
                        </p>
                      </td>
                      <td className="px-4 py-3 text-xs text-ink-700">
                        {employee.email}
                        <p className="text-ink-500">{employee.phone ?? "—"}</p>
                      </td>
                      <td className="px-4 py-3 text-xs text-ink-700">
                        {formatDate(employee.hire_date)}
                      </td>
                      <td className="px-4 py-3 text-xs tabular-nums text-ink-700">
                        {salary === null ? "Sin contrato vigente" : formatMoney(salary)}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge
                          label={employee.is_active ? "Activo" : "Inactivo"}
                          tone={employee.is_active ? "success" : "muted"}
                        />
                      </td>
                      <td className="px-4 py-3 text-right text-xs">
                        <Link
                          className="font-semibold text-ink-700 hover:text-signal-600 hover:underline"
                          to={`/hr/employees/${employee.id}`}
                        >
                          Historial
                        </Link>
                        {canWrite ? (
                          <>
                            <span className="px-2 text-concrete-300">|</span>
                            <button
                              type="button"
                              onClick={() => openEdit(employee)}
                              className="font-semibold text-ink-700 hover:text-signal-600 hover:underline"
                            >
                              Editar
                            </button>
                          </>
                        ) : null}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
        <div className="flex items-center justify-between border-t border-concrete-200 px-4 py-3 text-xs text-ink-500">
          <span>Página {page + 1}</span>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={page === 0 || employeesQuery.isPending}
              onClick={() => setPage((current) => current - 1)}
              className="border border-concrete-200 px-3 py-1.5 font-semibold disabled:opacity-40"
            >
              Anterior
            </button>
            <button
              type="button"
              disabled={employees.length < PAGE_SIZE || employeesQuery.isPending}
              onClick={() => setPage((current) => current + 1)}
              className="border border-concrete-200 px-3 py-1.5 font-semibold disabled:opacity-40"
            >
              Siguiente
            </button>
          </div>
        </div>
      </div>

      <EmployeeForm
        open={formOpen}
        employee={editing}
        onClose={() => setFormOpen(false)}
        onSaved={(employee, mode) => {
          setFormOpen(false);
          setFeedback({
            tone: "success",
            text:
              mode === "created"
                ? `Empleado ${employee.first_name} ${employee.last_name} registrado.`
                : `Datos de ${employee.first_name} ${employee.last_name} actualizados.`,
          });
        }}
      />
    </div>
  );
}
