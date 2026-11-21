"""Servicios de dominio del módulo de Recursos Humanos y Nómina.

Implementa, para el Hito 2 de ``specs/hr_spec.md``, la capa de servicio de
empleados y contratos (secciones 2.1, 2.2, 3.1, 3.6, 4.1 y 4.2):

* **Empleados:** alta con ``identification_number`` único (regla 6), listado
  filtrable por ``is_active``, perfil con historial laboral (contratos y
  asistencia) y actualización parcial de datos personales y de contacto.
* **Contratos:** alta validando que el empleado exista y que no tenga ya un
  contrato activo (regla 1). El segundo contrato activo se rechaza con una
  excepción de dominio que FastAPI traduce a ``400 Bad Request``, tal como
  exige el escenario 2 de aceptación.
* **Historial:** consulta de contratos por ``employee_id`` y del contrato
  activo vigente, que servirá de base para el cálculo de nómina.

Todas las escrituras usan :func:`_atomic`, que confirma al finalizar y revierte
cualquier cambio ante un error de negocio o de integridad. Las excepciones
derivan de ``fastapi.HTTPException`` con ``status_code`` 400/404, por lo que son
mapeables directamente por FastAPI sin un manejador adicional.

La exclusividad se comprueba en servicio y se serializa bloqueando la fila del
empleado (``SELECT ... FOR UPDATE``) dentro de la transacción; el índice único
de ``employees.identification_number`` es la última barrera contra duplicados
por carrera entre peticiones concurrentes.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.modules.hr.models import Contract, Employee
from src.modules.hr.schemas import (
    ContractCreate,
    EmployeeCreate,
    EmployeeResponse,
    EmployeeUpdate,
)

__all__ = [
    "ActiveContractError",
    "DuplicateIdentificationError",
    "HRServiceError",
    "InvalidEmployeeDataError",
    "ResourceNotFoundError",
    "create_contract",
    "create_employee",
    "get_active_contract",
    "get_contract",
    "get_employee",
    "get_employee_profile",
    "list_contracts_by_employee",
    "list_employees",
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


def _ensure_employee_dates(birth_date: date, hire_date: date) -> None:
    """Exige que la fecha de nacimiento no sea posterior al ingreso."""
    if birth_date > hire_date:
        raise InvalidEmployeeDataError(
            "birth_date no puede ser posterior a hire_date"
        )


def _ensure_contract_dates(start_date: date, end_date: date | None) -> None:
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


def _raise_duplicate_identification(identification: str, exc: IntegrityError) -> None:
    """Traduce una violación del índice único a error de dominio."""
    raise DuplicateIdentificationError(
        f"Ya existe un empleado con el número de identificación '{identification}'"
    ) from exc


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
