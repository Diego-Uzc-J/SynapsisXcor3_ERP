import { NavLink } from "react-router-dom";

const TABS = [
  { to: "/accounting/accounts", label: "Plan de cuentas" },
  { to: "/accounting/journal", label: "Libro diario" },
  { to: "/accounting/receivables", label: "Cartera CxC / CxP" },
  { to: "/accounting/reports", label: "Reportes" },
] as const;

/** Navegación secundaria común a las cuatro vistas del módulo contable. */
export default function AccountingTabs() {
  return (
    <nav
      aria-label="Vistas de contabilidad"
      className="mt-6 flex overflow-x-auto border-b border-concrete-200"
    >
      {TABS.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          end
          className={({ isActive }) =>
            [
              "-mb-px whitespace-nowrap border-b-2 px-4 py-2.5 text-sm font-semibold transition-colors",
              isActive
                ? "border-signal-500 text-ink-950"
                : "border-transparent text-ink-500 hover:border-concrete-400 hover:text-ink-950",
            ].join(" ")
          }
        >
          {tab.label}
        </NavLink>
      ))}
    </nav>
  );
}
