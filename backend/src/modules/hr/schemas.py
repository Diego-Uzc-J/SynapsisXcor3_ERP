"""Esquemas Pydantic v2 del módulo de Recursos Humanos y Nómina.

Derivados de ``specs/hr_spec.md`` (sección 2) y de los modelos ORM de
``src.modules.hr.models``. Definen contratos de entrada (``Create``),
actualización parcial (``Update``), salida (``Response``) y el detalle de un
periodo de nómina con sus desprendibles calculados.

Principios transversales:

* **Sin asignación masiva**: todas las clases declaran
  ``ConfigDict(extra="forbid")``. Los campos controlados por el servicio
  (``status``, ``approved_at``, ``created_at`` y los totales calculados) no
  forman parte de los esquemas de entrada.
* **Dinero y horas estrictamente decimales**: todos los importes y
  ``overtime_hours`` usan el alias :data:`StrictDecimal`, que rechaza
  ``float`` y admite ``Decimal``, ``int`` o cadenas. Los importes usan
  ``max_digits=14, decimal_places=2`` para coincidir con ``Numeric(14, 2)`` y
  las horas ``max_digits=7, decimal_places=2`` para ``Numeric(7, 2)``.
* **Códigos validados**: ``Employee.identification_number`` y
  ``PayrollRun.code`` validan formato y longitud; la unicidad real se garantiza
  en los índices únicos de la base de datos y se verifica en el servicio.
* **Validaciones espejo de la BD**: fechas coherentes, ``base_salary > 0``,
  ``overtime_hours >= 0`` y rango ``period_start <= period_end``. La
  exclusividad de contrato activo y la inmutabilidad de nómina aprobada se
  resuelven en la capa de servicio, porque requieren consultar estado.
* **Respuestas desde el ORM**: los esquemas ``Response`` activan
  ``ConfigDict(from_attributes=True)`` para validar directamente entidades
  SQLAlchemy, incluido el historial laboral del empleado.
"""

from __future__ import annotations

# Se aliasan los tipos para que el campo ``date`` de Attendance no choque con
# el nombre del tipo importado al construir los ``FieldInfo`` de Pydantic.
from datetime import date as date_type, datetime as datetime_type
from decimal import Decimal
from typing import Annotated, Any, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    model_validator,
)

from src.modules.hr.models import AttendanceStatus, ContractType, PayrollRunStatus

__all__ = [
    "AttendanceCreate",
    "AttendanceResponse",
    "AttendanceStatus",
    "ContractCreate",
    "ContractResponse",
    "ContractType",
    "EmployeeCreate",
    "EmployeeResponse",
    "EmployeeUpdate",
    "HRResponseSchema",
    "HRSchema",
    "PayrollRunCreate",
    "PayrollRunDetailResponse",
    "PayrollRunResponse",
    "PayrollRunStatus",
    "PayslipResponse",
    "StrictDecimal",
    "StrictHours",
    "StrictMoney",
]

#: Patrón de códigos de negocio: mayúsculas/dígitos con ``.``, ``-`` o ``_``.
_CODE_PATTERN = r"^[A-Z0-9][A-Z0-9._-]*$"

#: Patrón de documentos de identidad: alfanumérico con separadores comunes.
_IDENTIFICATION_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"

#: Descripción reutilizable de los importes ``Numeric(14, 2)``.
_MONEY_DESCRIPTION = "Importe decimal con hasta 14 enteros y 2 decimales."

#: Descripción reutilizable de las horas ``Numeric(7, 2)``.
_HOURS_DESCRIPTION = "Horas decimales con hasta 5 enteros y 2 decimales."


def _reject_float(value: Any) -> Any:
    """Impide que un ``float`` se convierta silenciosamente en ``Decimal``."""
    if isinstance(value, float):
        raise ValueError(
            "Los importes y las horas deben enviarse como Decimal o cadena, "
            "nunca como float."
        )
    return value


#: ``Decimal`` estricto: acepta ``Decimal``, ``int`` y cadenas, pero no ``float``.
StrictDecimal = Annotated[Decimal, BeforeValidator(_reject_float)]

#: Importes alineados con ``Numeric(14, 2)``.
StrictMoney = Annotated[StrictDecimal, Field(max_digits=14, decimal_places=2)]

#: Horas alineadas con ``Numeric(7, 2)``.
StrictHours = Annotated[StrictDecimal, Field(max_digits=7, decimal_places=2)]


class HRSchema(BaseModel):
    """Base de los esquemas de RRHH con rechazo de campos desconocidos."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class HRResponseSchema(HRSchema):
    """Base de las respuestas construidas desde entidades SQLAlchemy."""

    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, from_attributes=True
    )


# --------------------------------------------------------------------------- #
# Empleados — /api/v1/hr/employees
# --------------------------------------------------------------------------- #


class EmployeeCreate(HRSchema):
    """Datos para registrar un empleado.

    ``identification_number`` debe ser único en el sistema; el formato se
    valida aquí y la unicidad en la base de datos y en el servicio.
    """

    identification_number: str = Field(
        min_length=1,
        max_length=50,
        pattern=_IDENTIFICATION_PATTERN,
        description="Documento de identidad único del empleado.",
        examples=["900123456-1"],
    )
    first_name: str = Field(
        min_length=1, max_length=100, description="Nombres del empleado."
    )
    last_name: str = Field(
        min_length=1, max_length=100, description="Apellidos del empleado."
    )
    email: EmailStr = Field(
        max_length=255,
        description="Correo corporativo o personal.",
        examples=["ana.perez@example.com"],
    )
    phone: str | None = Field(
        default=None, max_length=50, description="Teléfono opcional."
    )
    birth_date: date_type = Field(description="Fecha de nacimiento.")
    hire_date: date_type = Field(description="Fecha de ingreso a la empresa.")
    is_active: bool = Field(
        default=True, description="Indica si el empleado está activo."
    )

    @model_validator(mode="after")
    def _validate_dates(self) -> Self:
        if self.birth_date > self.hire_date:
            raise ValueError("birth_date no puede ser posterior a hire_date")
        return self


class EmployeeUpdate(HRSchema):
    """Actualización parcial de un empleado (PATCH).

    Se permite limpiar ``phone`` enviando ``null``. El resto de campos, si se
    incluyen, deben tener un valor no nulo.
    """

    identification_number: str | None = Field(
        default=None, min_length=1, max_length=50, pattern=_IDENTIFICATION_PATTERN
    )
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    birth_date: date_type | None = Field(default=None)
    hire_date: date_type | None = Field(default=None)
    is_active: bool | None = None

    @model_validator(mode="after")
    def _validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Debe enviar al menos un campo para actualizar")

        nullable = {"phone"}
        for field in self.model_fields_set - nullable:
            if getattr(self, field) is None:
                raise ValueError(f"El campo '{field}' no puede ser nulo")

        if (
            self.birth_date is not None
            and self.hire_date is not None
            and self.birth_date > self.hire_date
        ):
            raise ValueError("birth_date no puede ser posterior a hire_date")
        return self


# --------------------------------------------------------------------------- #
# Contratos — /api/v1/hr/contracts
# --------------------------------------------------------------------------- #


class ContractCreate(HRSchema):
    """Contrato laboral con salario base estrictamente positivo."""

    employee_id: int = Field(gt=0, description="Empleado vinculado al contrato.")
    contract_type: ContractType = Field(
        description="Modalidad del contrato.",
        examples=[ContractType.INDEFINITE],
    )
    base_salary: StrictMoney = Field(
        gt=0,
        description=_MONEY_DESCRIPTION,
        examples=["3500000.00"],
    )
    start_date: date_type = Field(description="Fecha de inicio del contrato.")
    end_date: date_type | None = Field(
        default=None, description="Fecha de fin; opcional en contratos indefinidos."
    )
    is_active: bool = Field(
        default=True, description="Indica si es el contrato vigente del empleado."
    )

    @model_validator(mode="after")
    def _validate_dates(self) -> Self:
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date no puede ser anterior a start_date")
        return self


class ContractResponse(HRResponseSchema):
    """Representación de salida de un contrato laboral."""

    id: int
    employee_id: int
    contract_type: ContractType
    base_salary: StrictMoney
    start_date: date_type
    end_date: date_type | None
    is_active: bool


# --------------------------------------------------------------------------- #
# Asistencia — /api/v1/hr/attendance
# --------------------------------------------------------------------------- #


class AttendanceCreate(HRSchema):
    """Novedad diaria de asistencia; las horas extra nunca son negativas."""

    employee_id: int = Field(gt=0, description="Empleado al que pertenece el registro.")
    date: date_type = Field(description="Fecha del registro.")
    status: AttendanceStatus = Field(
        description="Estado de asistencia o novedad.",
        examples=[AttendanceStatus.PRESENT],
    )
    overtime_hours: StrictHours = Field(
        default=Decimal("0.00"),
        ge=0,
        description=_HOURS_DESCRIPTION,
        examples=["0.00"],
    )
    notes: str | None = Field(default=None, description="Observaciones opcionales.")


class AttendanceResponse(HRResponseSchema):
    """Representación de salida de un registro de asistencia."""

    id: int
    employee_id: int
    date: date_type
    status: AttendanceStatus
    overtime_hours: StrictHours
    notes: str | None


# --------------------------------------------------------------------------- #
# Empleado con historial laboral
# --------------------------------------------------------------------------- #


class EmployeeResponse(HRResponseSchema):
    """Perfil del empleado con su historial de contratos y asistencia."""

    id: int
    identification_number: str
    first_name: str
    last_name: str
    email: EmailStr
    phone: str | None
    birth_date: date_type
    hire_date: date_type
    is_active: bool
    created_at: datetime_type
    contracts: list[ContractResponse] = Field(default_factory=list)
    attendance_records: list[AttendanceResponse] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Nómina — /api/v1/hr/payrolls
# --------------------------------------------------------------------------- #


class PayrollRunCreate(HRSchema):
    """Periodo de nómina en borrador.

    ``code`` debe ser único; se valida el formato y la unicidad se resuelve en
    el índice único de la base de datos. ``status``, ``approved_at`` y los
    totales los fija el servicio, por lo que no se aceptan del cliente.
    """

    code: str = Field(
        min_length=1,
        max_length=30,
        pattern=_CODE_PATTERN,
        description="Código único del periodo de nómina.",
        examples=["NOM-2026-03"],
    )
    period_start: date_type = Field(description="Primer día del periodo liquidado.")
    period_end: date_type = Field(description="Último día del periodo liquidado.")
    is_adjustment: bool = Field(
        default=False,
        description="Indica si la nómina corrige un periodo ya aprobado.",
    )

    @model_validator(mode="after")
    def _validate_period(self) -> Self:
        if self.period_start > self.period_end:
            raise ValueError("period_start no puede ser posterior a period_end")
        return self


class PayslipResponse(HRResponseSchema):
    """Desprendible individual calculado dentro de un ``PayrollRun``."""

    id: int
    payroll_run_id: int
    employee_id: int
    base_salary: StrictMoney
    overtime_pay: StrictMoney
    bonuses: StrictMoney
    deductions: StrictMoney
    earnings: StrictMoney
    net_pay: StrictMoney


class PayrollRunResponse(HRResponseSchema):
    """Representación de salida de un periodo de nómina."""

    id: int
    code: str
    period_start: date_type
    period_end: date_type
    status: PayrollRunStatus
    is_adjustment: bool
    total_earnings: StrictMoney
    total_deductions: StrictMoney
    total_net: StrictMoney
    approved_at: datetime_type | None
    created_at: datetime_type


class PayrollRunDetailResponse(PayrollRunResponse):
    """Detalle de un periodo de nómina con todos sus desprendibles."""

    payslips: list[PayslipResponse] = Field(default_factory=list)
