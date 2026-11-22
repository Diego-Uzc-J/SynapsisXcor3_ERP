import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { ROLE_LABELS } from "../modules/users/constants";
import { canWriteModule, hasModuleAccess, useAuth } from "../store/authStore";
import type { AuthUser } from "../store/authStore";
import { canOpenModule, MODULES } from "./modules";
import type { ModuleDefinition, ModuleKey } from "./modules";

const svgProps = {
  "aria-hidden": true,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  className: "size-6",
} as const;

/** Iconos inline: el proyecto no incorpora una librería de iconos. */
const MODULE_ICONS: Record<ModuleKey, ReactNode> = {
  inventory: (
    <svg {...svgProps}>
      <path d="M3 7.5 12 3l9 4.5v9L12 21l-9-4.5z" />
      <path d="m3 7.5 9 4.5 9-4.5M12 12v9" />
    </svg>
  ),
  sales: (
    <svg {...svgProps}>
      <path d="M3 4h2l2.3 11.2a2 2 0 0 0 2 1.6h7.6a2 2 0 0 0 2-1.6L20.5 8H6" />
      <circle cx="10" cy="20" r="1" />
      <circle cx="17.5" cy="20" r="1" />
    </svg>
  ),
  purchasing: (
    <svg {...svgProps}>
      <path d="M3 6h11v10H3zM14 10h3.5L21 13.5V16h-7z" />
      <circle cx="7" cy="18" r="1.5" />
      <circle cx="17.5" cy="18" r="1.5" />
    </svg>
  ),
  accounting: (
    <svg {...svgProps}>
      <path d="M4 4h13a3 3 0 0 1 3 3v13H7a3 3 0 0 1-3-3z" />
      <path d="M4 17a3 3 0 0 1 3-3h13M8 8h8M8 11h5" />
    </svg>
  ),
  hr: (
    <svg {...svgProps}>
      <circle cx="9" cy="8" r="3" />
      <path d="M3 20a6 6 0 0 1 12 0" />
      <path d="M16 5.2a3 3 0 0 1 0 5.6M18 14.2A6 6 0 0 1 21 20" />
    </svg>
  ),
  manufacturing: (
    <svg {...svgProps}>
      <path d="M3 21V10l6 4V10l6 4V6h6v15z" />
      <path d="M7 17.5h2M13 17.5h2M18 17.5h1" />
    </svg>
  ),
  users: (
    <svg {...svgProps}>
      <path d="M12 3l8 3v5c0 5-3.4 8.4-8 10-4.6-1.6-8-5-8-10V6z" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  ),
};

function ModuleCard({
  module,
  user,
}: {
  module: ModuleDefinition;
  user: AuthUser;
}) {
  const readOnly = !canWriteModule(user, module.key);
  // Los permisos `modulo:read` de contabilidad no abren las rutas de ventas ni
  // compras (RequireRole). Se muestran como tarjetas informativas, sin enlace
  // que lleve a un 403.
  const navigable = canOpenModule(user, module.key);

  const content = (
    <>
      <div className="flex items-start justify-between gap-3">
        <span
          className={[
            "grid size-11 shrink-0 place-items-center border border-concrete-200 bg-concrete-50 text-ink-700",
            navigable
              ? "transition-colors group-hover:border-signal-500 group-hover:text-signal-600"
              : "",
          ].join(" ")}
        >
          {MODULE_ICONS[module.key]}
        </span>
        {readOnly ? (
          <span className="border border-concrete-200 bg-concrete-50 px-2 py-1 text-[0.625rem] font-semibold uppercase tracking-[0.12em] text-ink-500">
            Solo lectura
          </span>
        ) : null}
      </div>

      <h2 className="mt-5 text-lg font-bold tracking-tight">{module.label}</h2>
      <p className="mt-1.5 text-sm leading-relaxed text-ink-700">
        {module.description}
      </p>
      {!navigable ? (
        <p className="mt-3 text-xs leading-relaxed text-concrete-400">
          Tu rol consulta este módulo en la API; la consola no tiene una vista
          dedicada para él.
        </p>
      ) : null}

      <span className="mt-auto flex items-center justify-between gap-2 border-t border-concrete-200 pt-3">
        <span className="font-mono text-[0.6875rem] text-concrete-400">
          {module.path}
        </span>
        <span
          aria-hidden="true"
          className={
            navigable
              ? "text-sm font-bold text-ink-500 transition-transform group-hover:translate-x-0.5"
              : "text-sm font-bold text-concrete-400"
          }
        >
          {navigable ? "→" : "·"}
        </span>
      </span>
    </>
  );

  if (!navigable) {
    return (
      <li
        aria-disabled="true"
        className="flex flex-col border border-concrete-200 bg-concrete-50 p-5"
      >
        {content}
      </li>
    );
  }

  return (
    <li>
      <Link
        to={module.path}
        className="group flex h-full flex-col border border-concrete-200 bg-white p-5 transition-colors hover:border-signal-500 hover:bg-concrete-50"
      >
        {content}
      </Link>
    </li>
  );
}

/** Hub principal: muestra solo los módulos autorizados para el perfil activo. */
export default function ModuleHub() {
  const { user } = useAuth();

  // `RequireAuth` garantiza el perfil; el guardia evita renderizar vacío.
  if (user === null) {
    return null;
  }

  const modules = MODULES.filter((module) =>
    hasModuleAccess(user, module.key),
  );
  const navigableCount = modules.filter((module) =>
    canOpenModule(user, module.key),
  ).length;
  const readOnlyCount = modules.filter(
    (module) => !canWriteModule(user, module.key),
  ).length;
  const firstName = user.full_name.trim().split(/\s+/)[0] ?? user.full_name;

  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-10 sm:px-6 lg:px-10">
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
        Centro de operaciones
      </p>
      <h1 className="mt-3 text-3xl font-extrabold tracking-tight sm:text-4xl">
        Hola, {firstName}
      </h1>
      <p className="mt-3 max-w-2xl text-sm leading-relaxed text-ink-700">
        Estos son los módulos habilitados para tu rol{" "}
        <strong>{ROLE_LABELS[user.role.name]}</strong>. Cada tarjeta abre su
        vista principal; los accesos de consulta se indican como solo lectura.
      </p>

      <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-2 border-y border-concrete-200 py-3 text-xs text-ink-500">
        <span>
          <strong className="text-ink-950">{modules.length}</strong> módulos
          disponibles
        </span>
        <span>
          <strong className="text-ink-950">{navigableCount}</strong> enlaces
          activos
        </span>
        <span>
          <strong className="text-ink-950">{readOnlyCount}</strong> en solo
          lectura
        </span>
      </div>

      {modules.length === 0 ? (
        <div className="mt-6 border border-concrete-200 bg-white px-6 py-10 text-center">
          <p className="text-sm font-semibold">
            Tu cuenta no tiene módulos asignados.
          </p>
          <p className="mt-2 text-sm text-ink-700">
            Solicita a un administrador la asignación de un rol operativo.
          </p>
          <Link
            to="/sin-acceso"
            className="mt-5 inline-flex bg-ink-950 px-4 py-2.5 text-sm font-semibold text-concrete-50 hover:bg-ink-900"
          >
            Ver detalles del acceso
          </Link>
        </div>
      ) : (
        <ul className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {modules.map((module) => (
            <ModuleCard key={module.key} module={module} user={user} />
          ))}
        </ul>
      )}
    </div>
  );
}
