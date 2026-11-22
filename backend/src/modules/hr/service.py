"""Servicios de dominio del módulo de Recursos Humanos y Nómina.

Implementa, para los Hitos 2 y 3 de ``specs/hr_spec.md``, la capa de servicio
de empleados, contratos, asistencia y nómina (secciones 2.1 a 2.5, 3.1 a 3.3,
3.6, 4.1 a 4.4 y 5):

* **Empleados:** alta con ``identification_number`` único (regla 6), listado
  filtrable por ``is_active``, perfil con historial laboral (contratos y
  asistencia) y actualización parcial de datos personales y de contacto.
* **Contratos:** alta validando que el empleado exista y que no tenga ya un
  contrato activo (regla 1). El segundo contrato activo se rechaza con una
  excepción de dominio que FastAPI traduce a ``400 Bad Request``, tal como
  exige el escenario 2 de aceptación.
* **Historial:** consulta de contratos por ``employee_id`` y del contrato
  activo vigente, que servirá de base para el cálculo de nómina.
* **Asistencia:** registro de ``PRESENT``, ``ABSENT``, ``SICK_LEAVE``,
  ``VACATION`` y ``OVERTIME`` exigiendo empleado existente y horas extra no
  negativas (sección 4.3), con filtros por empleado, fecha exacta o rango de
  periodo. Cada operación tiene una variante síncrona (``Session``) y otra
  asíncrona (``AsyncSession``) que comparten validación y construcción de la
  consulta.
* **Nómina:** generación atómica de un ``PayrollRun`` en ``DRAFT`` a partir de
  empleados activos con contrato activo vigente en el periodo (reglas 2, 3 y 6,
  escenarios 1, 3, 5 y 6). Los importes se calculan solo con ``Decimal`` y se
  cuantizan a 2 decimales con ``ROUND_HALF_UP``; los totales se suman desde los
  desprendibles ya redondeados para que la agregación sea exacta. La aprobación
  (regla 4, escenario 4) usa ``accounting.post_payroll_run_accounting`` con
  ``commit=False`` para crear el asiento y marcar el periodo como ``APPROVED``
  en la **misma** transacción; cualquier fallo revierte ambos.

Las fórmulas adoptadas, necesarias porque la spec no fija tarifas, son:

* ``base_salary`` del desprendible = salario mensual del contrato proporcional
  al periodo: ``salario * min(días_del_periodo, 30) / 30``. Un periodo mensual
  completo (28-31 días) paga el salario íntegro; uno quincenal paga la mitad.
* ``overtime_pay`` = ``horas_extra_totales * salario_mensual / (30 * 8)``. La
  tarifa por hora sale del salario mensual completo, no del proporcional.
* ``bonuses`` y ``deductions`` no tienen fuente en la spec: el servicio acepta
  importes explícitos por empleado y usa ``0.00`` cuando no se proporcionan.
* ``earnings = base_salary + overtime_pay + bonuses`` y
  ``net_pay = earnings - deductions``.

Cualquier intento de recalcular o cambiar el estado de un periodo ``APPROVED``
o ``PAID`` se rechaza con :class:`ImmutablePayrollRunError` (409); la corrección
debe hacerse mediante una nueva nómina con ``is_adjustment=True`` (regla 3).

Todas las escrituras usan :func:`_atomic` o :func:`_atomic_async`, que confirman
al finalizar y revierten cualquier cambio ante un error de negocio o de
integridad. Las excepciones derivan de ``fastapi.HTTPException`` con
``status_code`` 400/404/409, por lo que son mapeables directamente por FastAPI
sin un manejador adicional.

La exclusividad se comprueba en servicio y se serializa bloqueando la fila del
empleado (``SELECT ... FOR UPDATE``) dentro de la transacción; el índice único
de ``employees.identification_number`` es la última barrera contra duplicados
por carrera entre peticiones concurrentes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from datetime import date as date_type, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql import Select

from src.modules.accounting.service import post_payroll_run_accounting
from src.modules.hr.models import (
    Attendance,
    AttendanceStatus,
    Contract,
    Employee,
    PayrollRun,
    PayrollRunStatus,
    Payslip,
)
from src.modules.hr.schemas import (
    AttendanceCreate,
    ContractCreate,
    EmployeeCreate,
    EmployeeResponse,
    EmployeeUpdate,
    PayrollRunCreate,
    PayrollRunDetailResponse,
    PayrollRunResponse,
)

__all__ = [
    "ActiveContractError",
    "DuplicateIdentificationError",
    "DuplicatePayrollCodeError",
    "HRServiceError",
    "ImmutablePayrollRunError",
    "InvalidAttendanceError",
    "InvalidEmployeeDataError",
    "InvalidPayrollDataError",
    "PayrollAccountingError",
    "ResourceNotFoundError",
    "approve_payroll_run",
    "create_attendance",
    "create_attendance_async",
    "create_contract",
    "create_employee",
    "create_payroll_run",
    "get_active_contract",
    "get_contract",
    "get_employee",
    "get_employee_profile",
    "get_payroll_run",
    "get_payroll_run_detail",
    "get_payroll_run_summary",
    "list_attendance",
    "list_attendance_async",
    "list_contracts_by_employee",
    "list_employees",
    "list_payroll_runs",
    "recalculate_payroll_run",
    "set_payroll_run_status",
    "update_employee",
]


# --------------------------------------------------------------------------- #
# Excepciones HTTP de dominio
# --------------------------------------------------------------------------- #


class HRServiceError(HTTPException):
    """Error base del módulo de RRHH con su equivalencia HTTP."""

    status_code: int = 400

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=self.status_code, detail=detail)

    def __str__(self) -> str:
        """Devuelve solo el mensaje, como las excepciones de dominio del ERP."""
        return str(self.detail)


class ResourceNotFoundError(HRServiceError):
    """El empleado o el contrato solicitado no existe."""

    status_code = 404


class DuplicateIdentificationError(HRServiceError):
    """El ``identification_number`` ya pertenece a otro empleado (regla 6)."""

    status_code = 400


class InvalidEmployeeDataError(HRServiceError):
    """Los datos personales del empleado no son coherentes."""

    status_code = 400


class ActiveContractError(HRServiceError):
    """El empleado ya tiene un contrato activo (regla 1, escenario 2)."""

    status_code = 400


class InvalidAttendanceError(HRServiceError):
    """La novedad de asistencia no cumple la spec (estado, horas o rango)."""

    status_code = 400


class DuplicatePayrollCodeError(HRServiceError):
    """El ``code`` del periodo de nómina ya existe (regla 6, escenario 5)."""

    status_code = 400


class InvalidPayrollDataError(HRServiceError):
    """Periodo, importes o parámetros de cálculo de nómina no válidos."""

    status_code = 400


class ImmutablePayrollRunError(HRServiceError):
    """El periodo aprobado/pagado no se puede modificar (regla 3, escenario 3)."""

    status_code = 409


class PayrollAccountingError(HRServiceError):
    """Falló la contabilización al aprobar; la transacción fue revertida."""

    status_code = 400


# --------------------------------------------------------------------------- #
# Constantes de cálculo de nómina
# --------------------------------------------------------------------------- #

#: Unidad mínima de los importes monetarios del ERP.
_CENT = Decimal("0.01")

#: Límite de ``Numeric(14, 2)`` expresado como ``Decimal``.
_MAX_MONEY = Decimal("999999999999.99")

#: Base de prorrateo mensual y jornada diaria usadas por la spec implícita.
_DAYS_IN_MONTH = Decimal("30")
_HOURS_PER_DAY = Decimal("8")

#: Horas extra máximas que caben en ``Numeric(7, 2)``.
_MAX_HOURS = Decimal("99999.99")

#: Importe neutro para bonificaciones/deducciones no informadas.
_ZERO_MONEY = Decimal("0.00")

#: Estados que todavía permiten recalcular o transicionar un periodo.
_MUTABLE_PAYROLL_STATUSES = frozenset({PayrollRunStatus.DRAFT})

#: Estados a los que puede transicionar ``set_payroll_run_status``.
#: ``APPROVED`` solo se alcanza vía :func:`approve_payroll_run`, que exige el
#: asiento contable en la misma transacción (regla 4).
_ALLOWED_PAYROLL_TARGET_STATUSES = frozenset({PayrollRunStatus.PAID})


# --------------------------------------------------------------------------- #
# Utilidades internas y control transaccional
# --------------------------------------------------------------------------- #


@contextmanager
def _atomic(db: Session) -> Iterator[None]:
    """Confirma la unidad de trabajo o revierte cualquier cambio ante un error."""
    try:
        yield
        db.commit()
    except Exception:
        db.rollback()
        raise


@asynccontextmanager
async def _atomic_async(db: AsyncSession) -> AsyncIterator[None]:
    """Equivalente asíncrono de :func:`_atomic` para ``AsyncSession``."""
    try:
        yield
        await db.commit()
    except Exception:
        await db.rollback()
        raise


def _get_employee_row(
    db: Session, employee_id: int, *, for_update: bool = False
) -> Employee:
    """Obtiene un empleado por id o lanza ``ResourceNotFoundError``."""
    stmt = select(Employee).where(Employee.id == employee_id)
    if for_update:
        stmt = stmt.with_for_update()
    employee = db.scalars(stmt).first()
    if employee is None:
        raise ResourceNotFoundError(f"Empleado {employee_id} no encontrado")
    return employee


def _ensure_unique_identification(
    db: Session, identification: str, *, exclude_id: int | None = None
) -> None:
    """Verifica que el documento no pertenezca a otro empleado."""
    stmt = select(Employee.id).where(
        Employee.identification_number == identification
    )
    if exclude_id is not None:
        stmt = stmt.where(Employee.id != exclude_id)
    if db.execute(stmt.limit(1)).first() is not None:
        raise DuplicateIdentificationError(
            f"Ya existe un empleado con el número de identificación "
            f"'{identification}'"
        )


def _ensure_employee_dates(birth_date: date_type, hire_date: date_type) -> None:
    """Exige que la fecha de nacimiento no sea posterior al ingreso."""
    if birth_date > hire_date:
        raise InvalidEmployeeDataError(
            "birth_date no puede ser posterior a hire_date"
        )


def _ensure_contract_dates(start_date: date_type, end_date: date_type | None) -> None:
    """Exige que ``end_date`` sea igual o posterior a ``start_date``."""
    if end_date is not None and end_date < start_date:
        raise InvalidEmployeeDataError(
            "end_date no puede ser anterior a start_date"
        )


def _find_active_contract(db: Session, employee_id: int) -> Contract | None:
    """Devuelve el contrato activo del empleado, o ``None`` si no tiene."""
    stmt = (
        select(Contract)
        .where(Contract.employee_id == employee_id, Contract.is_active.is_(True))
        .order_by(Contract.start_date.desc(), Contract.id.desc())
    )
    return db.scalars(stmt.limit(1)).first()


async def _ensure_employee_async(db: AsyncSession, employee_id: int) -> Employee:
    """Obtiene un empleado con ``AsyncSession`` o lanza ``ResourceNotFoundError``."""
    employee = await db.get(Employee, employee_id)
    if employee is None:
        raise ResourceNotFoundError(f"Empleado {employee_id} no encontrado")
    return employee


def _ensure_attendance_data(data: AttendanceCreate) -> None:
    """Valida estado y horas extra aunque el llamador haya sorteado el esquema."""
    if not isinstance(data.status, AttendanceStatus):
        raise InvalidAttendanceError(
            f"Estado de asistencia no válido: {data.status!r}"
        )
    try:
        overtime_hours = Decimal(str(data.overtime_hours))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidAttendanceError(
            "overtime_hours debe ser un valor decimal"
        ) from exc
    if overtime_hours < 0:
        raise InvalidAttendanceError("overtime_hours no puede ser negativo")


def _ensure_attendance_range(
    start_date: date_type | None, end_date: date_type | None
) -> None:
    """Rechaza rangos de periodo invertidos."""
    if start_date is not None and end_date is not None and start_date > end_date:
        raise InvalidAttendanceError(
            "start_date no puede ser posterior a end_date"
        )


def _attendance_statement(
    *,
    employee_id: int | None = None,
    date: date_type | None = None,
    start_date: date_type | None = None,
    end_date: date_type | None = None,
) -> Select[Attendance]:
    """Construye la consulta de asistencia con todos los filtros aplicados.

    Los filtros se combinan con ``AND``: ``date`` acota a un día exacto, mientras
    que ``start_date``/``end_date`` acotan el periodo, ambos inclusivos.
    """
    _ensure_attendance_range(start_date, end_date)
    stmt = select(Attendance)
    if employee_id is not None:
        stmt = stmt.where(Attendance.employee_id == employee_id)
    if date is not None:
        stmt = stmt.where(Attendance.date == date)
    if start_date is not None:
        stmt = stmt.where(Attendance.date >= start_date)
    if end_date is not None:
        stmt = stmt.where(Attendance.date <= end_date)
    return stmt.order_by(Attendance.date, Attendance.id)


def _raise_duplicate_identification(identification: str, exc: IntegrityError) -> None:
    """Traduce una violación del índice único a error de dominio."""
    raise DuplicateIdentificationError(
        f"Ya existe un empleado con el número de identificación '{identification}'"
    ) from exc


# --------------------------------------------------------------------------- #
# Utilidades de nómina — /api/v1/hr/payrolls
# --------------------------------------------------------------------------- #


def _as_decimal(value: object, *, field: str, maximum: Decimal) -> Decimal:
    """Convierte a ``Decimal`` sin pasar por ``float`` y valida el rango.

    Se rechazan explícitamente ``float`` y ``bool`` para que ningún importe o
    hora entre en el cálculo con pérdida de precisión binaria.
    """
    if isinstance(value, (float, bool)) or value is None:
        raise InvalidPayrollDataError(
            f"{field} debe ser Decimal, entero o cadena, nunca float"
        )
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidPayrollDataError(f"{field} no es un valor decimal válido") from exc
    if not amount.is_finite():
        raise InvalidPayrollDataError(f"{field} debe ser finito")
    if amount < 0 or amount > maximum:
        raise InvalidPayrollDataError(
            f"{field} debe estar entre 0 y {maximum}"
        )
    return amount


def _quantize_money(value: Decimal) -> Decimal:
    """Redondea importes a céntanos con ``ROUND_HALF_UP``."""
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _ensure_payroll_period(data: PayrollRunCreate) -> None:
    """Revalida el periodo y el código aunque se haya sorteado Pydantic."""
    if not isinstance(data.code, str) or not data.code.strip():
        raise InvalidPayrollDataError("code no puede estar vacío")
    if len(data.code) > 30:
        raise InvalidPayrollDataError("code no puede superar 30 caracteres")
    if not isinstance(data.period_start, date_type) or not isinstance(
        data.period_end, date_type
    ):
        raise InvalidPayrollDataError(
            "period_start y period_end deben ser fechas"
        )
    if data.period_start > data.period_end:
        raise InvalidPayrollDataError(
            "period_start no puede ser posterior a period_end"
        )
    if not isinstance(data.is_adjustment, bool):
        raise InvalidPayrollDataError("is_adjustment debe ser booleano")


def _amount_from(
    mapping: Mapping[int, object] | None,
    employee_id: int,
    fallback: Decimal,
    field: str,
) -> Decimal:
    """Resuelve un importe por empleado, usando ``fallback`` si no se informa."""
    if mapping is None or employee_id not in mapping:
        return fallback
    return _quantize_money(
        _as_decimal(
            mapping[employee_id],
            field=f"{field}[{employee_id}]",
            maximum=_MAX_MONEY,
        )
    )


def _ensure_unique_payroll_code(
    db: Session, code: str, *, exclude_id: int | None = None
) -> None:
    """Verifica que el código de periodo no pertenezca a otro ``PayrollRun``."""
    stmt = select(PayrollRun.id).where(PayrollRun.code == code)
    if exclude_id is not None:
        stmt = stmt.where(PayrollRun.id != exclude_id)
    if db.execute(stmt.limit(1)).first() is not None:
        raise DuplicatePayrollCodeError(
            f"Ya existe un periodo de nómina con el código '{code}'"
        )


def _get_payroll_run_row(
    db: Session,
    payroll_run_id: int,
    *,
    for_update: bool = False,
    with_payslips: bool = False,
) -> PayrollRun:
    """Obtiene un periodo de nómina o lanza ``ResourceNotFoundError``."""
    stmt = select(PayrollRun).where(PayrollRun.id == payroll_run_id)
    if with_payslips:
        stmt = stmt.options(selectinload(PayrollRun.payslips))
    if for_update:
        stmt = stmt.with_for_update()
    payroll_run = db.scalars(stmt).first()
    if payroll_run is None:
        raise ResourceNotFoundError(
            f"Periodo de nómina {payroll_run_id} no encontrado"
        )
    return payroll_run


def _ensure_payroll_mutable(payroll_run: PayrollRun) -> None:
    """Bloquea la mutación de periodos aprobados o pagados (regla 3)."""
    try:
        status = PayrollRunStatus(payroll_run.status)
    except (TypeError, ValueError) as exc:
        raise InvalidPayrollDataError(
            f"Estado de nómina no válido: {payroll_run.status!r}"
        ) from exc
    if status not in _MUTABLE_PAYROLL_STATUSES:
        raise ImmutablePayrollRunError(
            f"El periodo de nómina '{payroll_run.code}' está {status.value} y es "
            "inmutable; cree una nómina de ajuste (is_adjustment=True) para "
            "corregirlo"
        )


def _ensure_payroll_postable(payroll_run: PayrollRun) -> tuple[Decimal, Decimal, Decimal]:
    """Valida que el periodo sea contabilizable y devuelve sus tres totales.

    Además de exigir ``DRAFT`` (vía :func:`_ensure_payroll_mutable` en el
    llamador), comprueba que existan desprendibles, que el devengado sea
    positivo y que los totales del encabezado coincidan exactamente con la suma
    de los desprendibles ya redondeados.
    """
    if not payroll_run.payslips:
        raise InvalidPayrollDataError(
            f"El periodo '{payroll_run.code}' no tiene desprendibles contabilizables"
        )

    earnings = _quantize_money(
        _as_decimal(
            payroll_run.total_earnings,
            field="total_earnings",
            maximum=_MAX_MONEY,
        )
    )
    deductions = _quantize_money(
        _as_decimal(
            payroll_run.total_deductions,
            field="total_deductions",
            maximum=_MAX_MONEY,
        )
    )
    net = _quantize_money(
        _as_decimal(
            payroll_run.total_net, field="total_net", maximum=_MAX_MONEY
        )
    )
    if earnings <= 0:
        raise InvalidPayrollDataError(
            f"El periodo '{payroll_run.code}' no tiene un devengado positivo"
        )
    if net != earnings - deductions:
        raise InvalidPayrollDataError(
            f"Los totales del periodo '{payroll_run.code}' son incoherentes: "
            f"{net} != {earnings} - {deductions}"
        )

    payslip_earnings = sum(
        (item.earnings for item in payroll_run.payslips), _ZERO_MONEY
    )
    payslip_deductions = sum(
        (item.deductions for item in payroll_run.payslips), _ZERO_MONEY
    )
    payslip_net = sum((item.net_pay for item in payroll_run.payslips), _ZERO_MONEY)
    if (
        _quantize_money(payslip_earnings) != earnings
        or _quantize_money(payslip_deductions) != deductions
        or _quantize_money(payslip_net) != net
    ):
        raise InvalidPayrollDataError(
            f"Los totales del periodo '{payroll_run.code}' no coinciden con sus "
            "desprendibles"
        )
    return earnings, deductions, net


def _eligible_payroll_employees(
    db: Session, period_start: date_type, period_end: date_type
) -> list[tuple[Employee, Contract]]:
    """Empleados activos con contrato activo vigente en el periodo (escenario 6)."""
    stmt = (
        select(Employee, Contract)
        .join(Contract, Contract.employee_id == Employee.id)
        .where(
            Employee.is_active.is_(True),
            Contract.is_active.is_(True),
            Contract.start_date <= period_end,
            or_(
                Contract.end_date.is_(None),
                Contract.end_date >= period_start,
            ),
        )
        .order_by(Employee.id, Contract.id)
    )
    return list(db.execute(stmt).all())


def _overtime_hours_by_employee(
    db: Session,
    employee_ids: list[int],
    period_start: date_type,
    period_end: date_type,
) -> dict[int, Decimal]:
    """Suma las horas extra de asistencia del periodo sin usar ``float``."""
    totals = {employee_id: Decimal("0") for employee_id in employee_ids}
    if not employee_ids:
        return totals
    stmt = (
        select(Attendance)
        .where(
            Attendance.employee_id.in_(employee_ids),
            Attendance.date >= period_start,
            Attendance.date <= period_end,
        )
        .order_by(Attendance.employee_id, Attendance.date, Attendance.id)
    )
    for record in db.scalars(stmt).all():
        hours = _as_decimal(
            record.overtime_hours,
            field=f"overtime_hours[{record.employee_id}]",
            maximum=_MAX_HOURS,
        )
        totals[record.employee_id] = totals[record.employee_id] + hours
    return totals


def _build_payslips(
    db: Session,
    payroll_run: PayrollRun,
    *,
    period_start: date_type,
    period_end: date_type,
    bonuses: Mapping[int, object] | None,
    deductions: Mapping[int, object] | None,
    previous: Mapping[int, Payslip] | None = None,
) -> list[Payslip]:
    """Calcula y persiste los desprendibles del periodo con ``Decimal`` exacto."""
    eligible = _eligible_payroll_employees(db, period_start, period_end)
    if not eligible:
        return []

    overtime_hours = _overtime_hours_by_employee(
        db,
        [employee.id for employee, _ in eligible],
        period_start,
        period_end,
    )
    days_in_period = (period_end - period_start).days + 1
    proration = Decimal(min(days_in_period, 30)) / _DAYS_IN_MONTH
    hourly_divisor = _DAYS_IN_MONTH * _HOURS_PER_DAY

    payslips: list[Payslip] = []
    for employee, contract in eligible:
        monthly_salary = _as_decimal(
            contract.base_salary,
            field=f"base_salary[{employee.id}]",
            maximum=_MAX_MONEY,
        )
        base_salary = _quantize_money(monthly_salary * proration)
        overtime_pay = _quantize_money(
            overtime_hours[employee.id] * monthly_salary / hourly_divisor
        )
        old = previous.get(employee.id) if previous is not None else None
        bonus = _amount_from(
            bonuses,
            employee.id,
            old.bonuses if old is not None else _ZERO_MONEY,
            "bonuses",
        )
        deduction = _amount_from(
            deductions,
            employee.id,
            old.deductions if old is not None else _ZERO_MONEY,
            "deductions",
        )
        earnings = _quantize_money(base_salary + overtime_pay + bonus)
        net_pay = _quantize_money(earnings - deduction)
        if net_pay < 0:
            raise InvalidPayrollDataError(
                f"Las deducciones superan los devengos del empleado {employee.id}"
            )

        payslip = Payslip(
            payroll_run_id=payroll_run.id,
            employee_id=employee.id,
            base_salary=base_salary,
            overtime_pay=overtime_pay,
            bonuses=bonus,
            deductions=deduction,
            earnings=earnings,
            net_pay=net_pay,
        )
        db.add(payslip)
        payslips.append(payslip)
    return payslips


def _set_payroll_totals(
    payroll_run: PayrollRun, payslips: list[Payslip]
) -> None:
    """Consolida totales exactos sumando los importes ya cuantizados."""
    payroll_run.total_earnings = _quantize_money(
        sum((item.earnings for item in payslips), _ZERO_MONEY)
    )
    payroll_run.total_deductions = _quantize_money(
        sum((item.deductions for item in payslips), _ZERO_MONEY)
    )
    payroll_run.total_net = _quantize_money(
        sum((item.net_pay for item in payslips), _ZERO_MONEY)
    )


# --------------------------------------------------------------------------- #
# Empleados — /api/v1/hr/employees
# --------------------------------------------------------------------------- #


def create_employee(db: Session, data: EmployeeCreate) -> Employee:
    """Registra un empleado validando la unicidad de su documento (regla 6)."""
    try:
        with _atomic(db):
            _ensure_unique_identification(db, data.identification_number)
            employee = Employee(**data.model_dump())
            db.add(employee)
    except IntegrityError as exc:
        _raise_duplicate_identification(data.identification_number, exc)
    db.refresh(employee)
    return employee


def get_employee(db: Session, employee_id: int) -> Employee:
    """Obtiene un empleado con sus contratos y novedades de asistencia."""
    stmt = (
        select(Employee)
        .where(Employee.id == employee_id)
        .options(
            selectinload(Employee.contracts),
            selectinload(Employee.attendance_records),
        )
    )
    employee = db.scalars(stmt).first()
    if employee is None:
        raise ResourceNotFoundError(f"Empleado {employee_id} no encontrado")
    return employee


def get_employee_profile(db: Session, employee_id: int) -> EmployeeResponse:
    """Devuelve el perfil del empleado junto con su historial laboral."""
    return EmployeeResponse.model_validate(get_employee(db, employee_id))


def list_employees(
    db: Session,
    *,
    is_active: bool | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[Employee]:
    """Lista empleados, opcionalmente filtrando por activos o inactivos."""
    stmt = select(Employee)
    if is_active is not None:
        stmt = stmt.where(Employee.is_active.is_(is_active))
    stmt = stmt.order_by(Employee.id).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


def update_employee(db: Session, employee_id: int, data: EmployeeUpdate) -> Employee:
    """Actualiza parcialmente un empleado, conservando la unicidad del documento.

    La coherencia de fechas se valida con los valores efectivos resultantes de
    mezclar el PATCH con los datos ya persistidos, no solo con los campos
    enviados, para que un cambio aislado no deje un registro inválido.
    """
    changes = data.model_dump(exclude_unset=True)
    new_identification = changes.get("identification_number")

    try:
        with _atomic(db):
            employee = _get_employee_row(db, employee_id, for_update=True)

            birth_date = changes.get("birth_date", employee.birth_date)
            hire_date = changes.get("hire_date", employee.hire_date)
            _ensure_employee_dates(birth_date, hire_date)

            if (
                new_identification is not None
                and new_identification != employee.identification_number
            ):
                _ensure_unique_identification(
                    db, new_identification, exclude_id=employee_id
                )

            for field, value in changes.items():
                setattr(employee, field, value)
    except IntegrityError as exc:
        _raise_duplicate_identification(new_identification or "", exc)

    db.refresh(employee)
    return employee


# --------------------------------------------------------------------------- #
# Contratos — /api/v1/hr/contracts
# --------------------------------------------------------------------------- #


def get_contract(db: Session, contract_id: int) -> Contract:
    """Obtiene un contrato por id o lanza ``ResourceNotFoundError``."""
    contract = db.get(Contract, contract_id)
    if contract is None:
        raise ResourceNotFoundError(f"Contrato {contract_id} no encontrado")
    return contract


def get_active_contract(db: Session, employee_id: int) -> Contract | None:
    """Devuelve el contrato activo de un empleado, si existe."""
    return _find_active_contract(db, employee_id)


def create_contract(db: Session, data: ContractCreate) -> Contract:
    """Crea un contrato exigiendo empleado existente y contrato activo único.

    La fila del empleado se bloquea dentro de la transacción para que dos
    peticiones concurrentes no puedan crear cada una un contrato activo. Si ya
    existe uno, se lanza :class:`ActiveContractError` (``400 Bad Request``) y
    ``_atomic`` revierte la transacción antes de propagar el error.
    """
    with _atomic(db):
        _get_employee_row(db, data.employee_id, for_update=True)
        _ensure_contract_dates(data.start_date, data.end_date)

        if data.is_active and _find_active_contract(db, data.employee_id) is not None:
            raise ActiveContractError(
                f"El empleado {data.employee_id} ya cuenta con un contrato vigente; "
                "no se puede registrar otro contrato activo"
            )

        contract = Contract(**data.model_dump())
        db.add(contract)

    db.refresh(contract)
    return contract


def list_contracts_by_employee(
    db: Session,
    employee_id: int,
    *,
    active_only: bool = False,
    skip: int = 0,
    limit: int = 100,
) -> list[Contract]:
    """Lista el historial de contratos de un empleado, del más reciente al más antiguo."""
    _get_employee_row(db, employee_id)
    stmt = select(Contract).where(Contract.employee_id == employee_id)
    if active_only:
        stmt = stmt.where(Contract.is_active.is_(True))
    stmt = stmt.order_by(Contract.start_date.desc(), Contract.id.desc())
    stmt = stmt.offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


# --------------------------------------------------------------------------- #
# Asistencia — /api/v1/hr/attendance
# --------------------------------------------------------------------------- #


def create_attendance(db: Session, data: AttendanceCreate) -> Attendance:
    """Registra una novedad de asistencia para un empleado existente.

    Se aceptan los cinco estados de la spec y se exige ``overtime_hours >= 0``;
    la validación se repite en servicio para no depender de que el llamador haya
    pasado por Pydantic. Devuelve el registro persistido con su ``Decimal``.
    """
    _ensure_attendance_data(data)
    with _atomic(db):
        _get_employee_row(db, data.employee_id)
        record = Attendance(**data.model_dump())
        db.add(record)
    db.refresh(record)
    return record


def list_attendance(
    db: Session,
    *,
    employee_id: int | None = None,
    date: date_type | None = None,
    start_date: date_type | None = None,
    end_date: date_type | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[Attendance]:
    """Consulta asistencia por empleado, fecha exacta o rango de periodo."""
    if employee_id is not None:
        _get_employee_row(db, employee_id)
    stmt = _attendance_statement(
        employee_id=employee_id,
        date=date,
        start_date=start_date,
        end_date=end_date,
    )
    stmt = stmt.offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


async def create_attendance_async(
    db: AsyncSession, data: AttendanceCreate
) -> Attendance:
    """Variante asíncrona de :func:`create_attendance` para ``AsyncSession``."""
    _ensure_attendance_data(data)
    async with _atomic_async(db):
        await _ensure_employee_async(db, data.employee_id)
        record = Attendance(**data.model_dump())
        db.add(record)
    await db.refresh(record)
    return record


async def list_attendance_async(
    db: AsyncSession,
    *,
    employee_id: int | None = None,
    date: date_type | None = None,
    start_date: date_type | None = None,
    end_date: date_type | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[Attendance]:
    """Variante asíncrona de :func:`list_attendance` con los mismos filtros."""
    if employee_id is not None:
        await _ensure_employee_async(db, employee_id)
    stmt = _attendance_statement(
        employee_id=employee_id,
        date=date,
        start_date=start_date,
        end_date=end_date,
    )
    stmt = stmt.offset(skip).limit(limit)
    result = await db.scalars(stmt)
    return list(result.all())


# --------------------------------------------------------------------------- #
# Nómina — /api/v1/hr/payrolls
# --------------------------------------------------------------------------- #


def create_payroll_run(
    db: Session,
    data: PayrollRunCreate,
    *,
    bonuses: Mapping[int, object] | None = None,
    deductions: Mapping[int, object] | None = None,
) -> PayrollRun:
    """Genera un periodo en ``DRAFT`` con sus desprendibles calculados.

    El código único se comprueba antes de insertar y el índice único es la
    última barrera; cualquier ``IntegrityError`` se traduce a
    :class:`DuplicatePayrollCodeError` (400, escenario 5). Empleados inactivos,
    sin contrato activo o con un contrato que no cubre el periodo se excluyen
    (escenario 6). ``bonuses`` y ``deductions`` son importes opcionales por
    ``employee_id``; la spec no define una fuente de datos para ellos.
    """
    _ensure_payroll_period(data)
    try:
        with _atomic(db):
            _ensure_unique_payroll_code(db, data.code)
            payroll_run = PayrollRun(
                code=data.code,
                period_start=data.period_start,
                period_end=data.period_end,
                status=PayrollRunStatus.DRAFT,
                is_adjustment=data.is_adjustment,
                total_earnings=_ZERO_MONEY,
                total_deductions=_ZERO_MONEY,
                total_net=_ZERO_MONEY,
                approved_at=None,
            )
            db.add(payroll_run)
            db.flush()

            payslips = _build_payslips(
                db,
                payroll_run,
                period_start=data.period_start,
                period_end=data.period_end,
                bonuses=bonuses,
                deductions=deductions,
            )
            _set_payroll_totals(payroll_run, payslips)
    except IntegrityError as exc:
        raise DuplicatePayrollCodeError(
            f"Ya existe un periodo de nómina con el código '{data.code}'"
        ) from exc

    db.refresh(payroll_run)
    return payroll_run


def get_payroll_run(db: Session, payroll_run_id: int) -> PayrollRun:
    """Obtiene un periodo de nómina con todos sus desprendibles."""
    return _get_payroll_run_row(db, payroll_run_id, with_payslips=True)


def get_payroll_run_summary(
    db: Session, payroll_run_id: int
) -> PayrollRunResponse:
    """Devuelve el periodo sin la colección de desprendibles."""
    return PayrollRunResponse.model_validate(
        _get_payroll_run_row(db, payroll_run_id)
    )


def get_payroll_run_detail(
    db: Session, payroll_run_id: int
) -> PayrollRunDetailResponse:
    """Devuelve el detalle del periodo y sus ``Payslip`` ya calculados."""
    return PayrollRunDetailResponse.model_validate(get_payroll_run(db, payroll_run_id))


def list_payroll_runs(
    db: Session,
    *,
    status: PayrollRunStatus | None = None,
    is_adjustment: bool | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[PayrollRun]:
    """Lista periodos históricos filtrando por estado y tipo de ajuste."""
    stmt = select(PayrollRun)
    if status is not None:
        stmt = stmt.where(PayrollRun.status == status)
    if is_adjustment is not None:
        stmt = stmt.where(PayrollRun.is_adjustment.is_(is_adjustment))
    stmt = stmt.order_by(PayrollRun.period_start, PayrollRun.id)
    stmt = stmt.offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


def recalculate_payroll_run(
    db: Session,
    payroll_run_id: int,
    *,
    bonuses: Mapping[int, object] | None = None,
    deductions: Mapping[int, object] | None = None,
) -> PayrollRun:
    """Recalcula desprendibles y totales de un periodo en ``DRAFT``.

    Los importes de bonificación/deducción no informados se conservan de los
    desprendibles anteriores. En ``APPROVED``/``PAID`` la operación se rechaza
    con :class:`ImmutablePayrollRunError` (409) y no se escribe nada.
    """
    with _atomic(db):
        payroll_run = _get_payroll_run_row(
            db, payroll_run_id, for_update=True, with_payslips=True
        )
        _ensure_payroll_mutable(payroll_run)
        previous = {item.employee_id: item for item in payroll_run.payslips}
        payroll_run.payslips.clear()
        db.flush()

        payslips = _build_payslips(
            db,
            payroll_run,
            period_start=payroll_run.period_start,
            period_end=payroll_run.period_end,
            bonuses=bonuses,
            deductions=deductions,
            previous=previous,
        )
        _set_payroll_totals(payroll_run, payslips)

    db.refresh(payroll_run)
    return payroll_run


def set_payroll_run_status(
    db: Session, payroll_run_id: int, status: PayrollRunStatus
) -> PayrollRun:
    """Transiciona un periodo ``DRAFT`` a ``PAID``.

    ``APPROVED`` **no** se puede fijar aquí: ese estado exige el asiento
    contable de :func:`approve_payroll_run` (regla 4). Un periodo ya aprobado o
    pagado no puede cambiar de estado; la corrección exige una nueva nómina de
    ajuste (regla 3, escenario 3).
    """
    try:
        target = PayrollRunStatus(status)
    except (TypeError, ValueError) as exc:
        raise InvalidPayrollDataError(
            f"Estado de nómina no válido: {status!r}"
        ) from exc
    if target not in _ALLOWED_PAYROLL_TARGET_STATUSES:
        raise InvalidPayrollDataError(
            "Desde DRAFT solo se puede transicionar a PAID; para APPROVED use "
            "approve_payroll_run, que genera el asiento contable"
        )

    with _atomic(db):
        payroll_run = _get_payroll_run_row(db, payroll_run_id, for_update=True)
        _ensure_payroll_mutable(payroll_run)
        payroll_run.status = target

    db.refresh(payroll_run)
    return payroll_run


def approve_payroll_run(
    db: Session,
    payroll_run_id: int,
    *,
    expense_account_id: int | None = None,
    payable_account_id: int | None = None,
    deductions_account_id: int | None = None,
    created_by: str | None = None,
) -> PayrollRun:
    """Aprueba un periodo ``DRAFT`` y contabiliza su nómina de forma atómica.

    Dentro de una única unidad de trabajo se generan las líneas de gasto de
    personal y pasivo, se publica el asiento en ``accounting`` con
    ``commit=False`` y se marcan ``status=APPROVED``/``approved_at``. Si la
    contabilización falla, :func:`_atomic` revierte el asiento y el cambio de
    estado; el periodo sigue en ``DRAFT`` sin movimientos parciales (regla 4,
    escenario 4).
    """
    initial = _get_payroll_run_row(db, payroll_run_id, with_payslips=True)
    _ensure_payroll_mutable(initial)
    payroll_code = initial.code
    earnings, deductions, net = _ensure_payroll_postable(initial)

    try:
        with _atomic(db):
            payroll_run = _get_payroll_run_row(
                db, payroll_run_id, for_update=True, with_payslips=True
            )
            # Se repiten las comprobaciones dentro de la transacción para no
            # aprobar un periodo modificado entre la lectura y el bloqueo.
            _ensure_payroll_mutable(payroll_run)
            earnings, deductions, net = _ensure_payroll_postable(payroll_run)

            post_payroll_run_accounting(
                db,
                code=payroll_run.code,
                entry_date=payroll_run.period_end,
                total_earnings=earnings,
                total_deductions=deductions,
                total_net=net,
                expense_account_id=expense_account_id,
                payable_account_id=payable_account_id,
                deductions_account_id=deductions_account_id,
                created_by=created_by,
                commit=False,
            )
            payroll_run.status = PayrollRunStatus.APPROVED
            payroll_run.approved_at = datetime.now(timezone.utc)
    except HRServiceError:
        raise
    except Exception as exc:
        raise PayrollAccountingError(
            f"No se pudo contabilizar la nómina '{payroll_code}': {exc}"
        ) from exc

    db.refresh(payroll_run)
    return payroll_run
