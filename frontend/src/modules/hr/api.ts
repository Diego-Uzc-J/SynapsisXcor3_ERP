/**
 * Cliente HTTP del módulo de Recursos Humanos y Nómina.
 *
 * Usa `apiRequest`, la instancia compartida del ERP que añade el Bearer token,
 * traduce los errores de FastAPI (400/401/403/404/409/422) y renueva la sesión
 * ante un 401. Todas las rutas cuelgan de `/api/v1/hr`.
 */
import { apiRequest } from "../../api/client";
import { buildQuery } from "../../api/config";
import type {
  Attendance,
  AttendanceCreate,
  AttendanceFilters,
  Contract,
  ContractCreate,
  ContractFilters,
  Employee,
  EmployeeCreate,
  EmployeeFilters,
  EmployeeUpdate,
  PayrollFilters,
  PayrollRun,
  PayrollRunCreate,
  PayrollRunDetail,
} from "./types";

export { ApiError as HrApiError } from "../../api/client";

const HR_PATH = "/api/v1/hr";

// --------------------------------------------------------------------------- //
// Empleados — /api/v1/hr/employees
// --------------------------------------------------------------------------- //

export function listEmployees(filters: EmployeeFilters = {}): Promise<Employee[]> {
  return apiRequest<Employee[]>(
    `${HR_PATH}/employees${buildQuery(filters)}`,
  );
}

export function getEmployee(employeeId: number): Promise<Employee> {
  return apiRequest<Employee>(`${HR_PATH}/employees/${employeeId}`);
}

export function createEmployee(payload: EmployeeCreate): Promise<Employee> {
  return apiRequest<Employee>(`${HR_PATH}/employees`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateEmployee(
  employeeId: number,
  payload: EmployeeUpdate,
): Promise<Employee> {
  return apiRequest<Employee>(`${HR_PATH}/employees/${employeeId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

// --------------------------------------------------------------------------- //
// Contratos — /api/v1/hr/contracts
// --------------------------------------------------------------------------- //

export function createContract(payload: ContractCreate): Promise<Contract> {
  return apiRequest<Contract>(`${HR_PATH}/contracts`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listContractsByEmployee(
  employeeId: number,
  filters: ContractFilters = {},
): Promise<Contract[]> {
  return apiRequest<Contract[]>(
    `${HR_PATH}/contracts/employee/${employeeId}${buildQuery(filters)}`,
  );
}

// --------------------------------------------------------------------------- //
// Asistencia — /api/v1/hr/attendance
// --------------------------------------------------------------------------- //

export function createAttendance(payload: AttendanceCreate): Promise<Attendance> {
  return apiRequest<Attendance>(`${HR_PATH}/attendance`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listAttendance(
  filters: AttendanceFilters = {},
): Promise<Attendance[]> {
  return apiRequest<Attendance[]>(
    `${HR_PATH}/attendance${buildQuery(filters)}`,
  );
}

// --------------------------------------------------------------------------- //
// Nómina — /api/v1/hr/payrolls
// --------------------------------------------------------------------------- //

export function listPayrollRuns(filters: PayrollFilters = {}): Promise<PayrollRun[]> {
  return apiRequest<PayrollRun[]>(
    `${HR_PATH}/payrolls${buildQuery(filters)}`,
  );
}

export function getPayrollRun(payrollRunId: number): Promise<PayrollRunDetail> {
  return apiRequest<PayrollRunDetail>(`${HR_PATH}/payrolls/${payrollRunId}`);
}

export function createPayrollRun(
  payload: PayrollRunCreate,
): Promise<PayrollRun> {
  return apiRequest<PayrollRun>(`${HR_PATH}/payrolls`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** DRAFT → APPROVED: contabiliza la nómina en la misma transacción. */
export function approvePayrollRun(payrollRunId: number): Promise<PayrollRun> {
  return apiRequest<PayrollRun>(`${HR_PATH}/payrolls/${payrollRunId}/approve`, {
    method: "POST",
  });
}

// --------------------------------------------------------------------------- //
// Claves de caché de TanStack Query
// --------------------------------------------------------------------------- //

export const hrKeys = {
  all: ["hr"] as const,
  employees: {
    all: ["hr", "employees"] as const,
    list: (filters: EmployeeFilters) =>
      ["hr", "employees", "list", filters] as const,
    detail: (employeeId: number) =>
      ["hr", "employees", "detail", employeeId] as const,
  },
  contracts: {
    all: ["hr", "contracts"] as const,
    byEmployee: (employeeId: number, filters: ContractFilters = {}) =>
      ["hr", "contracts", "employee", employeeId, filters] as const,
  },
  attendance: {
    all: ["hr", "attendance"] as const,
    list: (filters: AttendanceFilters) =>
      ["hr", "attendance", "list", filters] as const,
  },
  payrolls: {
    all: ["hr", "payrolls"] as const,
    list: (filters: PayrollFilters) =>
      ["hr", "payrolls", "list", filters] as const,
    detail: (payrollRunId: number) =>
      ["hr", "payrolls", "detail", payrollRunId] as const,
  },
} as const;
