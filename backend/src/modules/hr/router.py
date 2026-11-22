"""Routers FastAPI del módulo de Recursos Humanos y Nómina.

Expone los contratos de ``specs/hr_spec.md`` (sección 4) bajo el prefijo
``/api/v1/hr`` aplicado en ``src.main``: empleados, contratos, control de
asistencia y periodos de nómina.

Todas las operaciones exigen un token válido y uno de los roles autorizados por
la regla 5 de la spec y por la matriz de ``PROJECT_MANIFEST.md``: ``HR`` o
``ADMINISTRATOR`` (este último pasa por el *superuser bypass* de
:func:`src.core.security.require_roles`).

``hr_exception_handler`` traduce las excepciones de dominio a respuestas HTTP
usando el ``status_code`` declarado por cada clase (400/404/409). La validación
de payloads y parámetros (campos extra, ``float`` en importes/horas, rangos)
la resuelve FastAPI/Pydantic con ``422``.
"""

from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Depends, Path, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.security import require_roles
from src.modules.hr import service as services
from src.modules.hr.models import AttendanceStatus, PayrollRunStatus
from src.modules.hr.schemas import (
    AttendanceCreate,
    AttendanceResponse,
    ContractCreate,
    ContractResponse,
    EmployeeCreate,
    EmployeeResponse,
    EmployeeUpdate,
    PayrollRunCreate,
    PayrollRunDetailResponse,
    PayrollRunResponse,
)
from src.modules.hr.service import HRServiceError
from src.modules.users.models import RoleEnum, User

__all__ = ["hr_exception_handler", "router"]


# --------------------------------------------------------------------------- #
# Guardia RBAC (spec de users, sección 4.3 / spec de hr, regla 5)
# --------------------------------------------------------------------------- #

#: ``ADMINISTRATOR`` pasa siempre gracias al bypass interno de ``require_roles``.
require_hr = require_roles([RoleEnum.HR])


async def hr_exception_handler(
    _request: Request, exc: HRServiceError
) -> JSONResponse:
    """Convierte un error de dominio de RRHH en una respuesta HTTP."""
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


# --------------------------------------------------------------------------- #
# Empleados — /api/v1/hr/employees
# --------------------------------------------------------------------------- #

employees_router = APIRouter(prefix="/employees", tags=["hr: employees"])


@employees_router.post(
    "",
    response_model=EmployeeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un nuevo empleado",
    dependencies=[Depends(require_hr)],
)
def create_employee(
    payload: EmployeeCreate,
    db: Session = Depends(get_db),
) -> EmployeeResponse:
    """Registra un empleado validando la unicidad de su documento (regla 6)."""
    return EmployeeResponse.model_validate(services.create_employee(db, payload))


@employees_router.get(
    "",
    response_model=list[EmployeeResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar empleados activos o inactivos",
    dependencies=[Depends(require_hr)],
)
def list_employees(
    is_active: bool | None = Query(
        None, description="Filtra por empleados activos (true) o inactivos (false)."
    ),
    skip: int = Query(0, ge=0, description="Registros a omitir."),
    limit: int = Query(100, ge=1, le=200, description="Máximo de registros."),
    db: Session = Depends(get_db),
) -> list[EmployeeResponse]:
    """Devuelve el listado de empleados, opcionalmente filtrado por estado."""
    employees = services.list_employees(db, is_active=is_active, skip=skip, limit=limit)
    return [EmployeeResponse.model_validate(employee) for employee in employees]


@employees_router.get(
    "/{employee_id}",
    response_model=EmployeeResponse,
    status_code=status.HTTP_200_OK,
    summary="Consultar el perfil y el historial laboral de un empleado",
    dependencies=[Depends(require_hr)],
)
def get_employee(
    employee_id: int = Path(..., gt=0, description="Id del empleado."),
    db: Session = Depends(get_db),
) -> EmployeeResponse:
    """Devuelve el perfil con sus contratos y novedades de asistencia."""
    return services.get_employee_profile(db, employee_id)


@employees_router.patch(
    "/{employee_id}",
    response_model=EmployeeResponse,
    status_code=status.HTTP_200_OK,
    summary="Actualizar datos personales o de contacto de un empleado",
    dependencies=[Depends(require_hr)],
)
def update_employee(
    payload: EmployeeUpdate,
    employee_id: int = Path(..., gt=0, description="Id del empleado."),
    db: Session = Depends(get_db),
) -> EmployeeResponse:
    """Aplica una actualización parcial conservando la unicidad del documento."""
    return EmployeeResponse.model_validate(
        services.update_employee(db, employee_id, payload)
    )


# --------------------------------------------------------------------------- #
# Contratos — /api/v1/hr/contracts
# --------------------------------------------------------------------------- #

contracts_router = APIRouter(prefix="/contracts", tags=["hr: contracts"])


@contracts_router.post(
    "",
    response_model=ContractResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un contrato laboral para un empleado",
    dependencies=[Depends(require_hr)],
)
def create_contract(
    payload: ContractCreate,
    db: Session = Depends(get_db),
) -> ContractResponse:
    """Crea un contrato exigiendo un único contrato activo por empleado."""
    return ContractResponse.model_validate(services.create_contract(db, payload))


@contracts_router.get(
    "/employee/{employee_id}",
    response_model=list[ContractResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar el historial de contratos de un empleado",
    dependencies=[Depends(require_hr)],
)
def list_contracts_by_employee(
    employee_id: int = Path(..., gt=0, description="Id del empleado."),
    active_only: bool = Query(
        False, description="Si es true, devuelve solo el contrato vigente."
    ),
    skip: int = Query(0, ge=0, description="Registros a omitir."),
    limit: int = Query(100, ge=1, le=200, description="Máximo de registros."),
    db: Session = Depends(get_db),
) -> list[ContractResponse]:
    """Devuelve los contratos del empleado, del más reciente al más antiguo."""
    contracts = services.list_contracts_by_employee(
        db, employee_id, active_only=active_only, skip=skip, limit=limit
    )
    return [ContractResponse.model_validate(contract) for contract in contracts]


# --------------------------------------------------------------------------- #
# Control de asistencia — /api/v1/hr/attendance
# --------------------------------------------------------------------------- #

attendance_router = APIRouter(prefix="/attendance", tags=["hr: attendance"])


@attendance_router.post(
    "",
    response_model=AttendanceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar asistencia, ausencia, permiso u horas extra",
    dependencies=[Depends(require_hr)],
)
def create_attendance(
    payload: AttendanceCreate,
    db: Session = Depends(get_db),
) -> AttendanceResponse:
    """Registra una novedad diaria para un empleado existente."""
    return AttendanceResponse.model_validate(services.create_attendance(db, payload))


@attendance_router.get(
    "",
    response_model=list[AttendanceResponse],
    status_code=status.HTTP_200_OK,
    summary="Consultar registros de asistencia",
    dependencies=[Depends(require_hr)],
)
def list_attendance(
    employee_id: int | None = Query(
        None, gt=0, description="Filtra por empleado."
    ),
    date: date_type | None = Query(
        None, description="Filtra por una fecha exacta."
    ),
    start_date: date_type | None = Query(
        None, description="Inicio del rango (inclusive)."
    ),
    end_date: date_type | None = Query(
        None, description="Fin del rango (inclusive)."
    ),
    skip: int = Query(0, ge=0, description="Registros a omitir."),
    limit: int = Query(100, ge=1, le=200, description="Máximo de registros."),
    db: Session = Depends(get_db),
) -> list[AttendanceResponse]:
    """Consulta asistencia por empleado, fecha exacta o rango de periodo."""
    records = services.list_attendance(
        db,
        employee_id=employee_id,
        date=date,
        start_date=start_date,
        end_date=end_date,
        skip=skip,
        limit=limit,
    )
    return [AttendanceResponse.model_validate(record) for record in records]


# --------------------------------------------------------------------------- #
# Nómina — /api/v1/hr/payrolls
# --------------------------------------------------------------------------- #

payrolls_router = APIRouter(prefix="/payrolls", tags=["hr: payrolls"])


@payrolls_router.post(
    "",
    response_model=PayrollRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generar un periodo de nómina en borrador",
    dependencies=[Depends(require_hr)],
)
def create_payroll_run(
    payload: PayrollRunCreate,
    db: Session = Depends(get_db),
) -> PayrollRunResponse:
    """Genera el periodo y sus desprendibles calculados (reglas 2 y 6)."""
    return PayrollRunResponse.model_validate(
        services.create_payroll_run(db, payload)
    )


@payrolls_router.get(
    "",
    response_model=list[PayrollRunResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar periodos de nómina históricos y su estado",
    dependencies=[Depends(require_hr)],
)
def list_payroll_runs(
    status_filter: PayrollRunStatus | None = Query(
        None,
        alias="status",
        description="Filtra por estado del periodo.",
    ),
    is_adjustment: bool | None = Query(
        None, description="Filtra por nóminas de ajuste."
    ),
    skip: int = Query(0, ge=0, description="Registros a omitir."),
    limit: int = Query(100, ge=1, le=200, description="Máximo de registros."),
    db: Session = Depends(get_db),
) -> list[PayrollRunResponse]:
    """Devuelve los periodos de nómina, opcionalmente filtrados por estado."""
    runs = services.list_payroll_runs(
        db,
        status=status_filter,
        is_adjustment=is_adjustment,
        skip=skip,
        limit=limit,
    )
    return [PayrollRunResponse.model_validate(run) for run in runs]


@payrolls_router.get(
    "/{payroll_run_id}",
    response_model=PayrollRunDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Consultar el detalle de un periodo y sus desprendibles",
    dependencies=[Depends(require_hr)],
)
def get_payroll_run(
    payroll_run_id: int = Path(..., gt=0, description="Id del periodo de nómina."),
    db: Session = Depends(get_db),
) -> PayrollRunDetailResponse:
    """Devuelve el periodo con todos sus ``Payslip`` ya calculados."""
    return services.get_payroll_run_detail(db, payroll_run_id)


@payrolls_router.post(
    "/{payroll_run_id}/approve",
    response_model=PayrollRunResponse,
    status_code=status.HTTP_200_OK,
    summary="Aprobar un periodo generando su asiento contable",
    dependencies=[Depends(require_hr)],
)
def approve_payroll_run(
    payroll_run_id: int = Path(..., gt=0, description="Id del periodo de nómina."),
    db: Session = Depends(get_db),
) -> PayrollRunResponse:
    """Aprueba el periodo y contabiliza la nómina en una sola transacción."""
    return PayrollRunResponse.model_validate(
        services.approve_payroll_run(db, payroll_run_id)
    )


# --------------------------------------------------------------------------- #
# Agregación
# --------------------------------------------------------------------------- #

router = APIRouter()
router.include_router(employees_router)
router.include_router(contracts_router)
router.include_router(attendance_router)
router.include_router(payrolls_router)
