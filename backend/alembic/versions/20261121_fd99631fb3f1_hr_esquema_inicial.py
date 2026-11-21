"""hr: esquema inicial

Revision ID: fd99631fb3f1
Revises: ff363bda84aa
Create Date: 2026-11-21 23:41:14.239687+00:00

Crea el esquema del módulo de Recursos Humanos y Nómina conforme a
``specs/hr_spec.md`` (sección 2) y a ``backend/src/modules/hr/models.py``:

- enums nativos ``contract_type``, ``attendance_status`` y
  ``payroll_run_status``
- expedientes ``employees``, contratos ``contracts`` y novedades
  ``attendance``
- periodos ``payroll_runs`` y desprendibles ``payslips``

Los tipos enum se crean y eliminan explícitamente, igual que en las migraciones
de ``accounting``, ``sales`` y ``purchasing``, para que el ciclo
``upgrade`` / ``downgrade`` sea repetible en PostgreSQL.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fd99631fb3f1"
down_revision: str | None = "ff363bda84aa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTRACT_TYPE_VALUES = (
    "INDEFINITE",
    "FIXED_TERM",
    "SERVICES",
    "PART_TIME",
)

ATTENDANCE_STATUS_VALUES = (
    "PRESENT",
    "ABSENT",
    "SICK_LEAVE",
    "VACATION",
    "OVERTIME",
)

PAYROLL_RUN_STATUS_VALUES = (
    "DRAFT",
    "APPROVED",
    "PAID",
)


def _contract_type_enum() -> postgresql.ENUM:
    """Tipo enum reutilizable que no intenta crear el tipo por segunda vez."""
    return postgresql.ENUM(*CONTRACT_TYPE_VALUES, name="contract_type", create_type=False)


def _attendance_status_enum() -> postgresql.ENUM:
    """Tipo enum reutilizable que no intenta crear el tipo por segunda vez."""
    return postgresql.ENUM(
        *ATTENDANCE_STATUS_VALUES, name="attendance_status", create_type=False
    )


def _payroll_run_status_enum() -> postgresql.ENUM:
    """Tipo enum reutilizable que no intenta crear el tipo por segunda vez."""
    return postgresql.ENUM(
        *PAYROLL_RUN_STATUS_VALUES, name="payroll_run_status", create_type=False
    )


def upgrade() -> None:
    bind = op.get_bind()

    # Los enums nativos deben existir antes de las tablas que los usan.
    postgresql.ENUM(*CONTRACT_TYPE_VALUES, name="contract_type").create(
        bind, checkfirst=True
    )
    postgresql.ENUM(*ATTENDANCE_STATUS_VALUES, name="attendance_status").create(
        bind, checkfirst=True
    )
    postgresql.ENUM(*PAYROLL_RUN_STATUS_VALUES, name="payroll_run_status").create(
        bind, checkfirst=True
    )

    op.create_table(
        "employees",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("identification_number", sa.String(length=50), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=False),
        sa.Column("hire_date", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "birth_date <= hire_date", name="ck_employees_birth_before_hire"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_employees_hire_date", "employees", ["hire_date"], unique=False)
    op.create_index(
        op.f("ix_employees_identification_number"),
        "employees",
        ["identification_number"],
        unique=True,
    )
    op.create_index("ix_employees_is_active", "employees", ["is_active"], unique=False)

    op.create_table(
        "payroll_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column(
            "status",
            _payroll_run_status_enum(),
            server_default=sa.text("'DRAFT'"),
            nullable=False,
        ),
        sa.Column("is_adjustment", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "total_earnings",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0.00"),
            nullable=False,
        ),
        sa.Column(
            "total_deductions",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0.00"),
            nullable=False,
        ),
        sa.Column(
            "total_net",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0.00"),
            nullable=False,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "period_start <= period_end", name="ck_payroll_runs_valid_period"
        ),
        sa.CheckConstraint(
            "total_deductions >= 0",
            name="ck_payroll_runs_total_deductions_non_negative",
        ),
        sa.CheckConstraint(
            "total_earnings >= 0", name="ck_payroll_runs_total_earnings_non_negative"
        ),
        sa.CheckConstraint(
            "total_net = total_earnings - total_deductions",
            name="ck_payroll_runs_total_net_matches",
        ),
        sa.CheckConstraint(
            "total_net >= 0", name="ck_payroll_runs_total_net_non_negative"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_payroll_runs_code"), "payroll_runs", ["code"], unique=True)
    op.create_index(
        "ix_payroll_runs_period_end", "payroll_runs", ["period_end"], unique=False
    )
    op.create_index(
        "ix_payroll_runs_period_start", "payroll_runs", ["period_start"], unique=False
    )
    op.create_index("ix_payroll_runs_status", "payroll_runs", ["status"], unique=False)

    op.create_table(
        "attendance",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("status", _attendance_status_enum(), nullable=False),
        sa.Column(
            "overtime_hours",
            sa.Numeric(precision=7, scale=2),
            server_default=sa.text("0.00"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "overtime_hours >= 0", name="ck_attendance_overtime_hours_non_negative"
        ),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attendance_date", "attendance", ["date"], unique=False)
    op.create_index(
        "ix_attendance_employee_id", "attendance", ["employee_id"], unique=False
    )
    op.create_index("ix_attendance_status", "attendance", ["status"], unique=False)

    op.create_table(
        "contracts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("contract_type", _contract_type_enum(), nullable=False),
        sa.Column("base_salary", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.CheckConstraint(
            "base_salary >= 0", name="ck_contracts_base_salary_non_negative"
        ),
        sa.CheckConstraint(
            "end_date IS NULL OR start_date <= end_date",
            name="ck_contracts_valid_date_range",
        ),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_contracts_contract_type", "contracts", ["contract_type"], unique=False
    )
    op.create_index(
        "ix_contracts_employee_id", "contracts", ["employee_id"], unique=False
    )
    op.create_index("ix_contracts_is_active", "contracts", ["is_active"], unique=False)

    op.create_table(
        "payslips",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("payroll_run_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("base_salary", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "overtime_pay",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0.00"),
            nullable=False,
        ),
        sa.Column(
            "bonuses",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0.00"),
            nullable=False,
        ),
        sa.Column("deductions", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("earnings", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("net_pay", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.CheckConstraint(
            "base_salary >= 0", name="ck_payslips_base_salary_non_negative"
        ),
        sa.CheckConstraint(
            "bonuses >= 0", name="ck_payslips_bonuses_non_negative"
        ),
        sa.CheckConstraint(
            "deductions >= 0", name="ck_payslips_deductions_non_negative"
        ),
        sa.CheckConstraint("earnings >= 0", name="ck_payslips_earnings_non_negative"),
        sa.CheckConstraint(
            "net_pay = earnings - deductions", name="ck_payslips_net_pay_matches"
        ),
        sa.CheckConstraint(
            "overtime_pay >= 0", name="ck_payslips_overtime_pay_non_negative"
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["employees.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["payroll_run_id"], ["payroll_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "payroll_run_id", "employee_id", name="uq_payslips_payroll_run_employee"
        ),
    )
    op.create_index(
        "ix_payslips_employee_id", "payslips", ["employee_id"], unique=False
    )
    op.create_index(
        "ix_payslips_payroll_run_id", "payslips", ["payroll_run_id"], unique=False
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Orden inverso: desprendibles, contratos, asistencia, periodos y
    # empleados. Los tipos enum se eliminan al final, cuando nadie los usa.
    op.drop_index("ix_payslips_payroll_run_id", table_name="payslips")
    op.drop_index("ix_payslips_employee_id", table_name="payslips")
    op.drop_table("payslips")

    op.drop_index("ix_contracts_is_active", table_name="contracts")
    op.drop_index("ix_contracts_employee_id", table_name="contracts")
    op.drop_index("ix_contracts_contract_type", table_name="contracts")
    op.drop_table("contracts")

    op.drop_index("ix_attendance_status", table_name="attendance")
    op.drop_index("ix_attendance_employee_id", table_name="attendance")
    op.drop_index("ix_attendance_date", table_name="attendance")
    op.drop_table("attendance")

    op.drop_index("ix_payroll_runs_status", table_name="payroll_runs")
    op.drop_index("ix_payroll_runs_period_start", table_name="payroll_runs")
    op.drop_index("ix_payroll_runs_period_end", table_name="payroll_runs")
    op.drop_index(op.f("ix_payroll_runs_code"), table_name="payroll_runs")
    op.drop_table("payroll_runs")

    op.drop_index("ix_employees_is_active", table_name="employees")
    op.drop_index(op.f("ix_employees_identification_number"), table_name="employees")
    op.drop_index("ix_employees_hire_date", table_name="employees")
    op.drop_table("employees")

    postgresql.ENUM(*PAYROLL_RUN_STATUS_VALUES, name="payroll_run_status").drop(
        bind, checkfirst=True
    )
    postgresql.ENUM(*ATTENDANCE_STATUS_VALUES, name="attendance_status").drop(
        bind, checkfirst=True
    )
    postgresql.ENUM(*CONTRACT_TYPE_VALUES, name="contract_type").drop(
        bind, checkfirst=True
    )
