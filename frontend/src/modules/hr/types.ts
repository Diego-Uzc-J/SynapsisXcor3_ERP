/**
 * Contratos TypeScript del módulo de Recursos Humanos y Nómina.
 *
 * Derivados de `backend/src/modules/hr/schemas.py`, del router bajo
 * `/api/v1/hr` y de `specs/hr_spec.md`. Pydantic serializa los `Decimal` como
 * cadena, por lo que importes y horas se modelan como `string` y se envían
 * también como cadena: el backend rechaza explícitamente los `float`.
 */

export const CONTRACT_TYPES = [
  "INDEFINITE",
  "FIXED_TERM",
  "SERVICES",
  "PART_TIME",
] as const;
export type ContractType = (typeof CONTRACT_TYPES)[number];

export const ATTENDANCE_STATUSES = [
  "PRESENT",
  "ABSENT",
  "SICK_LEAVE",
  "VACATION",
  "OVERTIME",
] as const;
export type AttendanceStatus = (typeof ATTENDANCE_STATUSES)[number];

export const PAYROLL_STATUSES = ["DRAFT", "APPROVED", "PAID"] as const;
export type PayrollRunStatus = (typeof PAYROLL_STATUSES)[number];

export interface Contract {
  id: number;
  employee_id: number;
  contract_type: ContractType;
  base_salary: string;
  start_date: string;
  end_date: string | null;
  is_active: boolean;
}

export interface Attendance {
  id: number;
  employee_id: number;
  date: string;
  status: AttendanceStatus;
  overtime_hours: string;
  notes: string | null;
}

export interface Employee {
  id: number;
  identification_number: string;
  first_name: string;
  last_name: string;
  email: string;
  phone: string | null;
  birth_date: string;
  hire_date: string;
  is_active: boolean;
  created_at: string;
  contracts: Contract[];
  attendance_records: Attendance[];
}

export interface Payslip {
  id: number;
  payroll_run_id: number;
  employee_id: number;
  base_salary: string;
  overtime_pay: string;
  bonuses: string;
  deductions: string;
  earnings: string;
  net_pay: string;
}

export interface PayrollRun {
  id: number;
  code: string;
  period_start: string;
  period_end: string;
  status: PayrollRunStatus;
  is_adjustment: boolean;
  total_earnings: string;
  total_deductions: string;
  total_net: string;
  approved_at: string | null;
  created_at: string;
}

export interface PayrollRunDetail extends PayrollRun {
  payslips: Payslip[];
}

export interface EmployeeCreate {
  identification_number: string;
  first_name: string;
  last_name: string;
  email: string;
  phone: string | null;
  birth_date: string;
  hire_date: string;
  is_active: boolean;
}

export interface EmployeeUpdate {
  identification_number?: string;
  first_name?: string;
  last_name?: string;
  email?: string;
  phone?: string | null;
  birth_date?: string;
  hire_date?: string;
  is_active?: boolean;
}

export interface ContractCreate {
  employee_id: number;
  contract_type: ContractType;
  base_salary: string;
  start_date: string;
  end_date: string | null;
  is_active: boolean;
}

export interface AttendanceCreate {
  employee_id: number;
  date: string;
  status: AttendanceStatus;
  overtime_hours: string;
  notes: string | null;
}

export interface PayrollRunCreate {
  code: string;
  period_start: string;
  period_end: string;
  is_adjustment: boolean;
}

export interface EmployeeFilters {
  is_active?: boolean;
  skip?: number;
  limit?: number;
}

export interface ContractFilters {
  active_only?: boolean;
  skip?: number;
  limit?: number;
}

export interface AttendanceFilters {
  employee_id?: number;
  date?: string;
  start_date?: string;
  end_date?: string;
  skip?: number;
  limit?: number;
}

export interface PayrollFilters {
  status?: PayrollRunStatus;
  is_adjustment?: boolean;
  skip?: number;
  limit?: number;
}
