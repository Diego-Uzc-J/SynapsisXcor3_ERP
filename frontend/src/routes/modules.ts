import type { AuthUser } from "../store/authStore";
import { hasModuleAccess } from "../store/authStore";

export type ModuleKey =
  | "inventory"
  | "sales"
  | "purchasing"
  | "accounting"
  | "hr"
  | "manufacturing"
  | "users";

export interface ModuleDefinition {
  key: ModuleKey;
  label: string;
  description: string;
  path: string;
  /** `false` mientras solo exista la vista de preparación. */
  implemented: boolean;
}

/**
 * Orden canónico del menú. Inventario va primero para conservar el destino
 * inicial del ERP; Usuarios queda al final porque es administración.
 */
export const MODULES: readonly ModuleDefinition[] = [
  {
    key: "inventory",
    label: "Inventario",
    description: "Existencias, productos y bodegas",
    path: "/inventory",
    implemented: true,
  },
  {
    key: "sales",
    label: "Ventas",
    description: "Pedidos y facturación de venta",
    path: "/sales",
    implemented: true,
  },
  {
    key: "purchasing",
    label: "Compras",
    description: "Proveedores, recepciones y cuentas por pagar",
    path: "/purchasing",
    implemented: true,
  },
  {
    key: "accounting",
    label: "Contabilidad",
    description: "PUC, diario, cartera y reportes",
    path: "/accounting",
    implemented: true,
  },
  {
    key: "hr",
    label: "Recursos humanos",
    description: "Personal y nómina",
    path: "/hr",
    implemented: true,
  },
  {
    key: "manufacturing",
    label: "Manufactura",
    description: "Órdenes y materias primas",
    path: "/manufacturing",
    implemented: false,
  },
  {
    key: "users",
    label: "Usuarios",
    description: "Cuentas, roles y accesos",
    path: "/users",
    implemented: true,
  },
] as const;

export const INVENTORY_LINKS = [
  {
    to: "/inventory",
    label: "Existencias",
    description: "Saldos por bodega",
  },
  {
    to: "/inventory/products",
    label: "Productos",
    description: "Catálogo de SKUs",
  },
  {
    to: "/inventory/warehouses",
    label: "Bodegas",
    description: "Almacenes físicos",
  },
] as const;

export const SALES_LINKS = [
  {
    to: "/sales/customers",
    label: "Clientes",
    description: "Cartera y límites de crédito",
  },
  {
    to: "/sales/orders",
    label: "Pedidos",
    description: "Cotizaciones y facturación",
  },
  {
    to: "/sales/invoices",
    label: "Facturas",
    description: "Cobros, abonos y notas",
  },
] as const;

export const PURCHASING_LINKS = [
  {
    to: "/purchasing/suppliers",
    label: "Proveedores",
    description: "NIT, contactos y plazos",
  },
  {
    to: "/purchasing/orders",
    label: "Órdenes de compra",
    description: "Aprobación, recepciones y cierres",
  },
  {
    to: "/purchasing/receipts",
    label: "Recepciones",
    description: "Entradas de mercancía al stock",
  },
  {
    to: "/purchasing/bills",
    label: "Facturas",
    description: "Cuentas por pagar y abonos",
  },
] as const;

export const ACCOUNTING_LINKS = [
  {
    to: "/accounting/accounts",
    label: "Plan de cuentas",
    description: "PUC jerárquico",
  },
  {
    to: "/accounting/journal",
    label: "Libro diario",
    description: "Asientos de partida doble",
  },
  {
    to: "/accounting/receivables",
    label: "CxC / CxP",
    description: "Cobros, pagos y saldos",
  },
  {
    to: "/accounting/reports",
    label: "Reportes",
    description: "Estados financieros",
  },
] as const;

export const HR_LINKS = [
  {
    to: "/hr/employees",
    label: "Empleados",
    description: "Expedientes e historial laboral",
  },
  {
    to: "/hr/contracts",
    label: "Contratos",
    description: "Vigencia e historial por empleado",
  },
  {
    to: "/hr/attendance",
    label: "Asistencia",
    description: "Novedades y horas extra",
  },
  {
    to: "/hr/payrolls",
    label: "Nómina",
    description: "Periodos, desprendibles y aprobación",
  },
] as const;

export function moduleByKey(key: ModuleKey): ModuleDefinition {
  const definition = MODULES.find((module) => module.key === key);
  if (definition === undefined) {
    throw new Error(`Módulo desconocido: ${key}`);
  }
  return definition;
}

/** Primer destino navegable según `allowed_modules`; nunca deja un callejón. */
export function firstAccessiblePath(user: AuthUser): string {
  const definition = MODULES.find((module) =>
    hasModuleAccess(user, module.key),
  );
  return definition?.path ?? "/sin-acceso";
}

/**
 * Destino seguro tras el login.
 *
 * Si la ruta guardada por la guardia pertenece a un módulo que el perfil no
 * puede ver (por ejemplo, un cierre de sesión desde `/users` seguido de un
 * login con rol de ventas), se ignora y se usa el primer módulo permitido.
 */
export function safeReturnPath(
  user: AuthUser,
  requestedPath: string | null,
): string {
  if (requestedPath === null) {
    return firstAccessiblePath(user);
  }
  const definition = MODULES.find(
    (module) =>
      requestedPath === module.path ||
      requestedPath.startsWith(`${module.path}/`),
  );
  if (definition !== undefined && hasModuleAccess(user, definition.key)) {
    return requestedPath;
  }
  return firstAccessiblePath(user);
}

/** Destinos que se muestran en el menú lateral para este perfil. */
export function accessibleModules(user: AuthUser): ModuleDefinition[] {
  return MODULES.filter((module) => hasModuleAccess(user, module.key));
}
