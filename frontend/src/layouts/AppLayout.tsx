import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";

import { initials, ROLE_LABELS } from "../modules/users/constants";
import {
  accessibleModules,
  ACCOUNTING_LINKS,
  canOpenModule,
  HR_LINKS,
  INVENTORY_LINKS,
  MANUFACTURING_LINKS,
  PURCHASING_LINKS,
  SALES_LINKS,
} from "../routes/modules";
import { canWriteModule, logout, useAuth } from "../store/authStore";

const navItemClass = (isActive: boolean): string =>
  [
    "block border-l-2 px-3 py-2.5 transition-colors",
    isActive
      ? "border-signal-500 bg-white/5 text-concrete-50"
      : "border-transparent text-concrete-400 hover:border-concrete-400 hover:text-concrete-50",
  ].join(" ");

const mobileItemClass = (isActive: boolean): string =>
  [
    "whitespace-nowrap border-b-2 pb-0.5 text-sm font-semibold transition-colors",
    isActive
      ? "border-signal-500 text-ink-950"
      : "border-transparent text-ink-500 hover:text-ink-950",
  ].join(" ");

function SectionLabel({ children }: { children: string }) {
  return (
    <p className="mb-2 mt-5 hidden px-3 text-xs font-semibold uppercase tracking-[0.18em] text-concrete-400 first:mt-0 lg:block">
      {children}
    </p>
  );
}

export default function AppLayout() {
  const { user } = useAuth();
  const navigate = useNavigate();

  const modules = user === null ? [] : accessibleModules(user);
  const inventory = modules.find((module) => module.key === "inventory");
  const sales = modules.find((module) => module.key === "sales");
  const purchasing = modules.find((module) => module.key === "purchasing");
  const accounting = modules.find((module) => module.key === "accounting");
  const hr = modules.find((module) => module.key === "hr");
  const manufacturing = modules.find((module) => module.key === "manufacturing");
  const users = modules.find((module) => module.key === "users");
  const otherModules = modules.filter(
    (module) =>
      module.key !== "inventory" &&
      module.key !== "sales" &&
      module.key !== "purchasing" &&
      module.key !== "accounting" &&
      module.key !== "hr" &&
      module.key !== "manufacturing" &&
      module.key !== "users",
  );
  const isInventoryReadOnly =
    user !== null && !canWriteModule(user, "inventory");
  // Las rutas de estos módulos exigen además el rol exacto (o administrador),
  // igual que `RequireRole` y el router FastAPI. Ocultar los enlaces evita
  // mostrar destinos que el frontend rechazaría con 403.
  const canOpenSales = user !== null && canOpenModule(user, "sales");
  const canOpenPurchasing = user !== null && canOpenModule(user, "purchasing");
  const canOpenAccounting = user !== null && canOpenModule(user, "accounting");
  const canOpenHr = user !== null && canOpenModule(user, "hr");
  const canOpenManufacturing =
    user !== null && canOpenModule(user, "manufacturing");

  const mobileLinks = [
    ...(inventory === undefined
      ? []
      : INVENTORY_LINKS.map((link) => ({ to: link.to, label: link.label }))),
    ...(canOpenSales
      ? SALES_LINKS.map((link) => ({ to: link.to, label: link.label }))
      : []),
    ...(canOpenPurchasing
      ? PURCHASING_LINKS.map((link) => ({ to: link.to, label: link.label }))
      : []),
    ...(canOpenAccounting
      ? ACCOUNTING_LINKS.map((link) => ({ to: link.to, label: link.label }))
      : []),
    ...(canOpenHr
      ? HR_LINKS.map((link) => ({ to: link.to, label: link.label }))
      : []),
    ...(canOpenManufacturing
      ? MANUFACTURING_LINKS.map((link) => ({ to: link.to, label: link.label }))
      : []),
    ...otherModules.map((module) => ({
      to: module.path,
      label: module.label,
    })),
    ...(users === undefined
      ? []
      : [{ to: users.path, label: users.label }]),
  ];

  function handleLogout() {
    // Navegar antes de limpiar evita que `RequireAuth` conserve la ruta
    // protegida como destino del siguiente inicio de sesión.
    navigate("/login", { replace: true, state: null });
    logout();
  }

  return (
    <div className="min-h-screen bg-concrete-50 text-ink-950 md:flex">
      <aside className="sticky top-0 hidden h-screen w-20 shrink-0 flex-col justify-between bg-ink-950 px-3 py-6 md:flex lg:w-60 lg:px-5">
        <div className="min-h-0 overflow-y-auto">
          <div className="mb-10">
            <Link to="/" className="flex items-center gap-3" aria-label="Ir al hub del ERP">
              <span className="grid size-10 shrink-0 place-items-center bg-signal-500 text-base font-extrabold tracking-tight text-white">
                SX
              </span>
              <span className="hidden lg:block">
                <span className="block text-sm font-semibold text-concrete-50">
                  SynapsisXcor3
                </span>
                <span className="block text-xs text-concrete-400">
                  ERP modular
                </span>
              </span>
            </Link>
          </div>

          <nav aria-label="Navegación principal" className="space-y-1">
            {inventory === undefined ? null : (
              <>
                <SectionLabel>{inventory.label}</SectionLabel>
                {INVENTORY_LINKS.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end
                    className={({ isActive }) => navItemClass(isActive)}
                  >
                    <span className="block text-sm font-semibold lg:text-[0.8125rem]">
                      {item.label}
                    </span>
                    <span className="hidden text-xs text-concrete-400 lg:block">
                      {item.description}
                    </span>
                  </NavLink>
                ))}
                {isInventoryReadOnly ? (
                  <p className="hidden px-3 pt-2 text-[0.6875rem] leading-relaxed text-concrete-400 lg:block">
                    Tu rol tiene lectura de inventario; las acciones de
                    escritura están reservadas a inventario.
                  </p>
                ) : null}
              </>
            )}

            {canOpenSales && sales !== undefined ? (
              <>
                <SectionLabel>{sales.label}</SectionLabel>
                {SALES_LINKS.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end
                    className={({ isActive }) => navItemClass(isActive)}
                  >
                    <span className="block text-sm font-semibold lg:text-[0.8125rem]">
                      {item.label}
                    </span>
                    <span className="hidden text-xs text-concrete-400 lg:block">
                      {item.description}
                    </span>
                  </NavLink>
                ))}
              </>
            ) : null}

            {canOpenPurchasing && purchasing !== undefined ? (
              <>
                <SectionLabel>{purchasing.label}</SectionLabel>
                {PURCHASING_LINKS.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end
                    className={({ isActive }) => navItemClass(isActive)}
                  >
                    <span className="block text-sm font-semibold lg:text-[0.8125rem]">
                      {item.label}
                    </span>
                    <span className="hidden text-xs text-concrete-400 lg:block">
                      {item.description}
                    </span>
                  </NavLink>
                ))}
              </>
            ) : null}

            {canOpenAccounting && accounting !== undefined ? (
              <>
                <SectionLabel>{accounting.label}</SectionLabel>
                {ACCOUNTING_LINKS.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end
                    className={({ isActive }) => navItemClass(isActive)}
                  >
                    <span className="block text-sm font-semibold lg:text-[0.8125rem]">
                      {item.label}
                    </span>
                    <span className="hidden text-xs text-concrete-400 lg:block">
                      {item.description}
                    </span>
                  </NavLink>
                ))}
              </>
            ) : null}

            {canOpenHr && hr !== undefined ? (
              <>
                <SectionLabel>{hr.label}</SectionLabel>
                {HR_LINKS.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end
                    className={({ isActive }) => navItemClass(isActive)}
                  >
                    <span className="block text-sm font-semibold lg:text-[0.8125rem]">
                      {item.label}
                    </span>
                    <span className="hidden text-xs text-concrete-400 lg:block">
                      {item.description}
                    </span>
                  </NavLink>
                ))}
              </>
            ) : null}

            {canOpenManufacturing && manufacturing !== undefined ? (
              <>
                <SectionLabel>{manufacturing.label}</SectionLabel>
                {MANUFACTURING_LINKS.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end
                    className={({ isActive }) => navItemClass(isActive)}
                  >
                    <span className="block text-sm font-semibold lg:text-[0.8125rem]">
                      {item.label}
                    </span>
                    <span className="hidden text-xs text-concrete-400 lg:block">
                      {item.description}
                    </span>
                  </NavLink>
                ))}
              </>
            ) : null}

            {otherModules.length === 0 ? null : (
              <>
                <SectionLabel>Módulos</SectionLabel>
                {otherModules.map((module) => (
                  <NavLink
                    key={module.key}
                    to={module.path}
                    end
                    className={({ isActive }) => navItemClass(isActive)}
                  >
                    <span className="block text-sm font-semibold lg:text-[0.8125rem]">
                      {module.label}
                    </span>
                    <span className="hidden text-xs text-concrete-400 lg:block">
                      {module.description}
                    </span>
                  </NavLink>
                ))}
              </>
            )}

            {users === undefined ? null : (
              <>
                <SectionLabel>Administración</SectionLabel>
                <NavLink
                  to={users.path}
                  end
                  className={({ isActive }) => navItemClass(isActive)}
                >
                  <span className="block text-sm font-semibold lg:text-[0.8125rem]">
                    {users.label}
                  </span>
                  <span className="hidden text-xs text-concrete-400 lg:block">
                    {users.description}
                  </span>
                </NavLink>
              </>
            )}
          </nav>
        </div>

        <div className="mt-6 border-t border-white/10 pt-4">
          <div className="flex items-center gap-3">
            <span
              aria-hidden="true"
              className="grid size-9 shrink-0 place-items-center bg-concrete-50 text-xs font-bold text-ink-950"
            >
              {user === null ? "?" : initials(user.full_name)}
            </span>
            <div className="hidden min-w-0 lg:block">
              <p className="truncate text-sm font-semibold text-concrete-50">
                {user?.full_name ?? "Sesión finalizada"}
              </p>
              <p className="truncate text-xs text-concrete-400">
                {user === null ? "Sin perfil" : ROLE_LABELS[user.role.name]}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleLogout}
            className="mt-3 w-full border border-white/15 px-3 py-1.5 text-xs font-semibold text-concrete-400 hover:border-signal-500 hover:text-concrete-50"
          >
            <span className="lg:hidden" aria-label="Cerrar sesión">
              Salir
            </span>
            <span className="hidden lg:inline">Cerrar sesión</span>
          </button>
          <p className="hidden pt-4 text-xs leading-relaxed text-concrete-400 lg:block">
            Operaciones
            <br />
            v0.1 · Monolito modular
          </p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-4 border-b border-concrete-200 px-4 py-3 md:hidden">
          <Link to="/" className="flex shrink-0 items-center gap-2.5" aria-label="Ir al hub del ERP">
            <span className="grid size-8 place-items-center bg-signal-500 text-xs font-extrabold tracking-tight text-white">
              SX
            </span>
            <span className="text-sm font-semibold">SynapsisXcor3 ERP</span>
          </Link>
          <div className="flex min-w-0 items-center gap-3">
            <nav
              aria-label="Navegación principal"
              className="flex min-w-0 items-center gap-4 overflow-x-auto"
            >
              {mobileLinks.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end
                  className={({ isActive }) => mobileItemClass(isActive)}
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
            <button
              type="button"
              onClick={handleLogout}
              className="shrink-0 border border-concrete-200 px-2 py-1 text-xs font-semibold text-ink-500 hover:border-ink-950 hover:text-ink-950"
            >
              Salir
            </button>
          </div>
        </header>

        <main className="min-w-0 flex-1">
          <Outlet />
        </main>

        <footer className="border-t border-concrete-200 px-4 py-3 text-[0.6875rem] text-concrete-400 sm:px-6">
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
            <span>SynapsisXcor3 ERP · Monolito modular</span>
            <nav aria-label="Enlaces del proyecto" className="flex items-center gap-4">
              <a
                href="https://www.linkedin.com/in/diego-uzc-j/"
                target="_blank"
                rel="noreferrer"
                className="hover:text-ink-950"
              >
                LinkedIn
              </a>
              <a
                href="https://github.com/Diego-Uzc-J/SynapsisXcor3_ERP"
                target="_blank"
                rel="noreferrer"
                className="hover:text-ink-950"
              >
                GitHub
              </a>
            </nav>
          </div>
        </footer>
      </div>
    </div>
  );
}
