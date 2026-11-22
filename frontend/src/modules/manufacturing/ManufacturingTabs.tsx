import { NavLink, useLocation } from "react-router-dom";

const TABS = [
  { to: "/manufacturing/orders", label: "Órdenes de producción" },
  { to: "/manufacturing/boms", label: "Listas de materiales" },
  { to: "/manufacturing/work-centers", label: "Centros de trabajo" },
] as const;

/** Navegación secundaria común a las vistas del módulo de manufactura. */
export default function ManufacturingTabs() {
  const { pathname } = useLocation();

  return (
    <nav
      aria-label="Vistas de manufactura"
      className="mt-6 flex overflow-x-auto border-b border-concrete-200"
    >
      {TABS.map((tab) => {
        const isActive =
          pathname === tab.to || pathname.startsWith(`${tab.to}/`);
        return (
          <NavLink
            key={tab.to}
            to={tab.to}
            aria-current={isActive ? "page" : undefined}
            className={[
              "-mb-px whitespace-nowrap border-b-2 px-4 py-2.5 text-sm font-semibold transition-colors",
              isActive
                ? "border-signal-500 text-ink-950"
                : "border-transparent text-ink-500 hover:border-concrete-400 hover:text-ink-950",
            ].join(" ")}
          >
            {tab.label}
          </NavLink>
        );
      })}
    </nav>
  );
}
