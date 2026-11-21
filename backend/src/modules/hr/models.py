"""Modelos de dominio del módulo de Recursos Humanos y Nómina.

Implementa las entidades descritas en ``specs/hr_spec.md`` (sección 2):
``Employee``, ``Contract``, ``Attendance``, ``PayrollRun`` y ``Payslip``.

Convenciones alineadas con ``inventory``, ``sales``, ``purchasing`` y
``accounting``:

- claves primarias ``Integer`` y fechas ``Date`` / ``DateTime(timezone=True)``;
- importes ``Numeric(14, 2)`` y horas ``Numeric(7, 2)`` con ``CHECK`` de no
  negatividad, todos tipados como ``Decimal``;
- enums nativos de PostgreSQL con los valores exactos del contrato;
- ``ON DELETE RESTRICT`` para empleados, contratos, asistencia y desprendibles
  con historial; ``CASCADE`` solo desde ``PayrollRun`` a sus ``Payslip``;
- modelos declarativos SQLAlchemy 2.x con ``Mapped`` / ``mapped_column``,
  compatibles con el despacho asíncrono de FastAPI.

La clase declarativa ``Base`` es transversal y vive en ``src.core.database``.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class ContractType(str, PyEnum):
    """Tipos de contrato laboral soportados por la spec."""

    INDEFINITE = "INDEFINITE"
    FIXED_TERM = "FIXED_TERM"
    SERVICES = "SERVICES"
    PART_TIME = "PART_TIME"


class AttendanceStatus(str, PyEnum):
    """Estados del registro diario de asistencia y novedades."""

    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    SICK_LEAVE = "SICK_LEAVE"
    VACATION = "VACATION"
    OVERTIME = "OVERTIME"


class PayrollRunStatus(str, PyEnum):
    """Ciclo de vida de un periodo de nómina."""

    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PAID = "PAID"


#: Tipo enum nativo reutilizable con los valores del contrato.
CONTRACT_TYPE_TYPE = SAEnum(
    ContractType,
    name="contract_type",
    native_enum=True,
    validate_strings=True,
)

#: Tipo enum nativo reutilizable con los valores del contrato.
ATTENDANCE_STATUS_TYPE = SAEnum(
    AttendanceStatus,
    name="attendance_status",
    native_enum=True,
    validate_strings=True,
)

#: Tipo enum nativo reutilizable con los valores del contrato.
PAYROLL_RUN_STATUS_TYPE = SAEnum(
    PayrollRunStatus,
    name="payroll_run_status",
    native_enum=True,
    validate_strings=True,
)

#: Importes monetarios del módulo (hasta 999 999 999 999.99).
MONEY = Numeric(14, 2)

#: Horas extra acumuladas en un día (hasta 999 999.99).
HOURS = Numeric(7, 2)


class Employee(Base):
    """Persona natural vinculada laboralmente a la empresa."""

    __tablename__ = "employees"
    __table_args__ = (
        CheckConstraint(
            "birth_date <= hire_date", name="ck_employees_birth_before_hire"
        ),
        Index("ix_employees_hire_date", "hire_date"),
        Index("ix_employees_is_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identification_number: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)
    hire_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Las FK de las tablas dependientes son RESTRICT: no se desvinculan hijos
    # automáticamente; la baja física se controla en el servicio.
    contracts: Mapped[list[Contract]] = relationship(
        back_populates="employee", passive_deletes=True
    )
    attendance_records: Mapped[list[Attendance]] = relationship(
        back_populates="employee", passive_deletes=True
    )
    payslips: Mapped[list[Payslip]] = relationship(
        back_populates="employee", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return (
            f"<Employee id={self.id!r} "
            f"identification_number={self.identification_number!r}>"
        )


class Contract(Base):
    """Condiciones económicas y legales de la relación con un empleado."""

    __tablename__ = "contracts"
    __table_args__ = (
        CheckConstraint("base_salary >= 0", name="ck_contracts_base_salary_non_negative"),
        CheckConstraint(
            "end_date IS NULL OR start_date <= end_date",
            name="ck_contracts_valid_date_range",
        ),
        Index("ix_contracts_employee_id", "employee_id"),
        Index("ix_contracts_contract_type", "contract_type"),
        Index("ix_contracts_is_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False
    )
    contract_type: Mapped[ContractType] = mapped_column(
        CONTRACT_TYPE_TYPE, nullable=False
    )
    base_salary: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    employee: Mapped[Employee] = relationship(back_populates="contracts")

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return (
            f"<Contract id={self.id!r} employee_id={self.employee_id!r} "
            f"type={self.contract_type!r} is_active={self.is_active!r}>"
        )


class Attendance(Base):
    """Registro diario de asistencia, ausencias, permisos u horas extra."""

    __tablename__ = "attendance"
    __table_args__ = (
        CheckConstraint(
            "overtime_hours >= 0", name="ck_attendance_overtime_hours_non_negative"
        ),
        Index("ix_attendance_employee_id", "employee_id"),
        Index("ix_attendance_date", "date"),
        Index("ix_attendance_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[AttendanceStatus] = mapped_column(
        ATTENDANCE_STATUS_TYPE, nullable=False
    )
    overtime_hours: Mapped[Decimal] = mapped_column(
        HOURS, nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    employee: Mapped[Employee] = relationship(back_populates="attendance_records")

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return (
            f"<Attendance id={self.id!r} employee_id={self.employee_id!r} "
            f"date={self.date!r} status={self.status!r}>"
        )


class PayrollRun(Base):
    """Periodo de liquidación de nómina de toda la compañía."""

    __tablename__ = "payroll_runs"
    __table_args__ = (
        CheckConstraint(
            "period_start <= period_end", name="ck_payroll_runs_valid_period"
        ),
        CheckConstraint(
            "total_earnings >= 0", name="ck_payroll_runs_total_earnings_non_negative"
        ),
        CheckConstraint(
            "total_deductions >= 0",
            name="ck_payroll_runs_total_deductions_non_negative",
        ),
        CheckConstraint(
            "total_net >= 0", name="ck_payroll_runs_total_net_non_negative"
        ),
        CheckConstraint(
            "total_net = total_earnings - total_deductions",
            name="ck_payroll_runs_total_net_matches",
        ),
        Index("ix_payroll_runs_status", "status"),
        Index("ix_payroll_runs_period_start", "period_start"),
        Index("ix_payroll_runs_period_end", "period_end"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(
        String(30), unique=True, nullable=False, index=True
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[PayrollRunStatus] = mapped_column(
        PAYROLL_RUN_STATUS_TYPE,
        nullable=False,
        default=PayrollRunStatus.DRAFT,
        server_default=PayrollRunStatus.DRAFT.value,
    )
    is_adjustment: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    total_earnings: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    total_deductions: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    total_net: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Las líneas dependen del periodo: se eliminan con él, igual que
    # ``JournalItem`` respecto de ``JournalEntry`` en ``accounting``.
    payslips: Mapped[list[Payslip]] = relationship(
        back_populates="payroll_run", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return (
            f"<PayrollRun id={self.id!r} code={self.code!r} "
            f"status={self.status!r}>"
        )


class Payslip(Base):
    """Desprendible individual de un empleado dentro de un ``PayrollRun``."""

    __tablename__ = "payslips"
    __table_args__ = (
        UniqueConstraint(
            "payroll_run_id",
            "employee_id",
            name="uq_payslips_payroll_run_employee",
        ),
        CheckConstraint("base_salary >= 0", name="ck_payslips_base_salary_non_negative"),
        CheckConstraint("overtime_pay >= 0", name="ck_payslips_overtime_pay_non_negative"),
        CheckConstraint("bonuses >= 0", name="ck_payslips_bonuses_non_negative"),
        CheckConstraint("deductions >= 0", name="ck_payslips_deductions_non_negative"),
        CheckConstraint("earnings >= 0", name="ck_payslips_earnings_non_negative"),
        CheckConstraint(
            "net_pay = earnings - deductions", name="ck_payslips_net_pay_matches"
        ),
        Index("ix_payslips_payroll_run_id", "payroll_run_id"),
        Index("ix_payslips_employee_id", "employee_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payroll_run_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False
    )
    base_salary: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    overtime_pay: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    bonuses: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    deductions: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    earnings: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    net_pay: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    payroll_run: Mapped[PayrollRun] = relationship(back_populates="payslips")
    employee: Mapped[Employee] = relationship(back_populates="payslips")

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return (
            f"<Payslip id={self.id!r} payroll_run_id={self.payroll_run_id!r} "
            f"employee_id={self.employee_id!r} net_pay={self.net_pay!r}>"
        )


__all__ = [
    "ATTENDANCE_STATUS_TYPE",
    "CONTRACT_TYPE_TYPE",
    "HOURS",
    "MONEY",
    "PAYROLL_RUN_STATUS_TYPE",
    "Attendance",
    "AttendanceStatus",
    "Contract",
    "ContractType",
    "Employee",
    "PayrollRun",
    "PayrollRunStatus",
    "Payslip",
]
