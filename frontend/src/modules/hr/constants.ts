/** Etiquetas, tonos y reglas de negocio visibles en el módulo de RRHH. */

import type {
  AttendanceStatus,
  ContractType,
  PayrollRunStatus,
} from "./types";

export type BadgeTone = "neutral" | "warning" | "success" | "strong" | "muted";

export const CONTRACT_TYPE_LABELS: Record<ContractType, string> = {
  INDEFINITE: "Indefinido",
  FIXED_TERM: "Término fijo",
  SERVICES: "Prestación de servicios",
  PART_TIME: "Medio tiempo",
};

export const ATTENDANCE_STATUS_LABELS: Record<AttendanceStatus, string> = {
  PRESENT: "Presente",
  ABSENT: "Ausente",
  SICK_LEAVE: "Incapacidad",
  VACATION: "Vacaciones",
  OVERTIME: "Horas extra",
};

export const ATTENDANCE_STATUS_TONES: Record<AttendanceStatus, BadgeTone> = {
  PRESENT: "success",
  ABSENT: "muted",
  SICK_LEAVE: "warning",
  VACATION: "neutral",
  OVERTIME: "strong",
};

export const PAYROLL_STATUS_LABELS: Record<PayrollRunStatus, string> = {
  DRAFT: "Borrador",
  APPROVED: "Aprobada",
  PAID: "Pagada",
};

export const PAYROLL_STATUS_HINTS: Record<PayrollRunStatus, string> = {
  DRAFT: "Los desprendibles se pueden recalcular; aún no genera asiento.",
  APPROVED: "Inmutable: ya generó su asiento contable.",
  PAID: "Inmutable: periodo liquidado y pagado.",
};

export const PAYROLL_STATUS_TONES: Record<PayrollRunStatus, BadgeTone> = {
  DRAFT: "warning",
  APPROVED: "success",
  PAID: "strong",
};

/** Solo un borrador puede aprobarse; el backend rechaza el resto con 409. */
export function canApprovePayroll(status: PayrollRunStatus): boolean {
  return status === "DRAFT";
}

/** Un documento de identidad legible en los listados y desprendibles. */
export function employeeFullName(
  employee: { first_name: string; last_name: string } | undefined,
): string {
  return employee === undefined
    ? "Empleado no disponible"
    : `${employee.first_name} ${employee.last_name}`.trim();
}
