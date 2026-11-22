/**
 * Hooks de TanStack Query v5 del módulo de RRHH.
 *
 * Las mutaciones invalidan el detalle del empleado y los listados afectados:
 * un nuevo contrato o novedad cambia su historial; aprobar una nómina cambia
 * el estado del periodo y genera el asiento contable en el backend.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import {
  approvePayrollRun,
  createAttendance,
  createContract,
  createEmployee,
  createPayrollRun,
  getEmployee,
  getPayrollRun,
  hrKeys,
  listAttendance,
  listContractsByEmployee,
  listEmployees,
  listPayrollRuns,
  updateEmployee,
} from "./api";
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

// --------------------------------------------------------------------------- //
// Invalidación de caché
// --------------------------------------------------------------------------- //

function invalidateEmployees(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: hrKeys.employees.all });
}

function invalidateContracts(queryClient: QueryClient, employeeId: number): void {
  void queryClient.invalidateQueries({ queryKey: hrKeys.contracts.all });
  void queryClient.invalidateQueries({
    queryKey: hrKeys.employees.detail(employeeId),
  });
}

function invalidateAttendance(queryClient: QueryClient, employeeId: number): void {
  void queryClient.invalidateQueries({ queryKey: hrKeys.attendance.all });
  void queryClient.invalidateQueries({
    queryKey: hrKeys.employees.detail(employeeId),
  });
}

function invalidatePayrolls(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: hrKeys.payrolls.all });
}

// --------------------------------------------------------------------------- //
// Consultas
// --------------------------------------------------------------------------- //

export function useEmployees(filters: EmployeeFilters = {}, enabled = true) {
  return useQuery({
    queryKey: hrKeys.employees.list(filters),
    queryFn: () => listEmployees(filters),
    enabled,
  });
}

export function useEmployee(employeeId: number, enabled = true) {
  return useQuery({
    queryKey: hrKeys.employees.detail(employeeId),
    queryFn: () => getEmployee(employeeId),
    enabled: enabled && employeeId > 0,
  });
}

export function useContractsByEmployee(
  employeeId: number,
  filters: ContractFilters = {},
  enabled = true,
) {
  return useQuery({
    queryKey: hrKeys.contracts.byEmployee(employeeId, filters),
    queryFn: () => listContractsByEmployee(employeeId, filters),
    enabled: enabled && employeeId > 0,
  });
}

export function useAttendance(filters: AttendanceFilters = {}, enabled = true) {
  return useQuery({
    queryKey: hrKeys.attendance.list(filters),
    queryFn: () => listAttendance(filters),
    enabled,
  });
}

export function usePayrollRuns(filters: PayrollFilters = {}, enabled = true) {
  return useQuery({
    queryKey: hrKeys.payrolls.list(filters),
    queryFn: () => listPayrollRuns(filters),
    enabled,
  });
}

export function usePayrollRun(payrollRunId: number, enabled = true) {
  return useQuery({
    queryKey: hrKeys.payrolls.detail(payrollRunId),
    queryFn: () => getPayrollRun(payrollRunId),
    enabled: enabled && payrollRunId > 0,
  });
}

// --------------------------------------------------------------------------- //
// Mutaciones — empleados
// --------------------------------------------------------------------------- //

export function useCreateEmployee() {
  const queryClient = useQueryClient();
  return useMutation<Employee, Error, EmployeeCreate>({
    mutationFn: createEmployee,
    onSuccess: (employee) => {
      queryClient.setQueryData(hrKeys.employees.detail(employee.id), employee);
      invalidateEmployees(queryClient);
    },
  });
}

export interface UpdateEmployeeVariables {
  employeeId: number;
  payload: EmployeeUpdate;
}

export function useUpdateEmployee() {
  const queryClient = useQueryClient();
  return useMutation<Employee, Error, UpdateEmployeeVariables>({
    mutationFn: ({ employeeId, payload }) => updateEmployee(employeeId, payload),
    onSuccess: (employee) => {
      queryClient.setQueryData(hrKeys.employees.detail(employee.id), employee);
      invalidateEmployees(queryClient);
      invalidateContracts(queryClient, employee.id);
      invalidateAttendance(queryClient, employee.id);
    },
  });
}

// --------------------------------------------------------------------------- //
// Mutaciones — contratos y asistencia
// --------------------------------------------------------------------------- //

export function useCreateContract() {
  const queryClient = useQueryClient();
  return useMutation<Contract, Error, ContractCreate>({
    mutationFn: createContract,
    onSuccess: (contract) => {
      invalidateContracts(queryClient, contract.employee_id);
    },
  });
}

export function useCreateAttendance() {
  const queryClient = useQueryClient();
  return useMutation<Attendance, Error, AttendanceCreate>({
    mutationFn: createAttendance,
    onSuccess: (record) => {
      invalidateAttendance(queryClient, record.employee_id);
    },
  });
}

// --------------------------------------------------------------------------- //
// Mutaciones — nómina
// --------------------------------------------------------------------------- //

export function useCreatePayrollRun() {
  const queryClient = useQueryClient();
  return useMutation<PayrollRun, Error, PayrollRunCreate>({
    mutationFn: createPayrollRun,
    onSuccess: (run) => {
      queryClient.setQueryData(hrKeys.payrolls.detail(run.id), {
        ...run,
        payslips: [],
      } satisfies PayrollRunDetail);
      invalidatePayrolls(queryClient);
    },
  });
}

export function useApprovePayrollRun() {
  const queryClient = useQueryClient();
  return useMutation<PayrollRun, Error, number>({
    mutationFn: approvePayrollRun,
    onSuccess: (run) => {
      queryClient.setQueryData<PayrollRunDetail | undefined>(
        hrKeys.payrolls.detail(run.id),
        (current) => (current === undefined ? undefined : { ...current, ...run }),
      );
      invalidatePayrolls(queryClient);
    },
  });
}
