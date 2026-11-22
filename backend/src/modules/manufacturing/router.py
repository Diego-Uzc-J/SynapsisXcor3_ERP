"""Routers FastAPI del módulo de Manufactura y Producción.

Expone los contratos de ``specs/manufacturing_spec.md`` (sección 4) bajo el
prefijo ``/api/v1/manufacturing`` aplicado en ``src.main``: centros de trabajo,
listas de materiales y órdenes de producción con sus transiciones.

Todas las operaciones exigen un token válido y uno de los roles autorizados por
la regla 7 de la spec y la matriz de ``PROJECT_MANIFEST.md``: ``MANUFACTURING``
o ``ADMINISTRATOR`` (este último pasa por el *superuser bypass* interno de
:func:`src.core.security.require_roles`). Cualquier otro rol recibe ``403``.

``manufacturing_exception_handler`` traduce las excepciones de dominio a
respuestas HTTP usando el ``status_code`` declarado por cada clase (400/404/409).
La validación de payloads y parámetros (campos extra, ``float`` en cantidades,
rangos) la resuelve FastAPI/Pydantic con ``422``.
"""

from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Body, Depends, Path, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.security import require_roles
from src.modules.manufacturing import services as services
from src.modules.manufacturing.models import ProductionOrderStatus
from src.modules.manufacturing.schemas import (
    BOMCreate,
    BOMResponse,
    ProductionOrderComplete,
    ProductionOrderCreate,
    ProductionOrderResponse,
    ProductionOrderStart,
    WorkCenterCreate,
    WorkCenterResponse,
    WorkCenterUpdate,
)
from src.modules.manufacturing.services import ManufacturingServiceError
from src.modules.users.models import RoleEnum, User

__all__ = ["manufacturing_exception_handler", "router"]


# --------------------------------------------------------------------------- #
# Guardia RBAC (spec de manufacturing, regla 7)
# --------------------------------------------------------------------------- #

#: ``ADMINISTRATOR`` también se enumera explícitamente, aunque ``require_roles``
#: ya lo admite por su bypass, para dejar claro el contrato de la spec.
require_manufacturing = require_roles(
    [RoleEnum.MANUFACTURING, RoleEnum.ADMINISTRATOR]
)


async def manufacturing_exception_handler(
    _request: Request, exc: ManufacturingServiceError
) -> JSONResponse:
    """Convierte un error de dominio de manufactura en una respuesta HTTP."""
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


# --------------------------------------------------------------------------- #
# Centros de trabajo — /api/v1/manufacturing/work-centers
# --------------------------------------------------------------------------- #

work_centers_router = APIRouter(
    prefix="/work-centers", tags=["manufacturing: work centers"]
)


@work_centers_router.post(
    "",
    response_model=WorkCenterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un centro de trabajo",
)
def create_work_center(
    payload: WorkCenterCreate,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_manufacturing),
) -> WorkCenterResponse:
    """Da de alta una máquina o estación con ``code`` único (spec §4.2)."""
    return WorkCenterResponse.model_validate(
        services.create_work_center(db, payload)
    )


@work_centers_router.get(
    "",
    response_model=list[WorkCenterResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar centros de trabajo",
)
def list_work_centers(
    is_active: bool | None = Query(
        True,
        description="Filtra por centros activos (true), inactivos (false) o todos (null).",
    ),
    skip: int = Query(0, ge=0, description="Registros a omitir."),
    limit: int = Query(100, ge=1, le=200, description="Máximo de registros."),
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_manufacturing),
) -> list[WorkCenterResponse]:
    """Devuelve los centros de trabajo; por defecto solo los activos."""
    centers = services.list_work_centers(
        db, is_active=is_active, skip=skip, limit=limit
    )
    return [WorkCenterResponse.model_validate(center) for center in centers]


@work_centers_router.patch(
    "/{work_center_id}",
    response_model=WorkCenterResponse,
    status_code=status.HTTP_200_OK,
    summary="Actualizar un centro de trabajo",
)
def update_work_center(
    payload: WorkCenterUpdate,
    work_center_id: int = Path(..., gt=0, description="Id del centro de trabajo."),
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_manufacturing),
) -> WorkCenterResponse:
    """Aplica una actualización parcial conservando la unicidad del ``code``."""
    return WorkCenterResponse.model_validate(
        services.update_work_center(db, work_center_id, payload)
    )


# --------------------------------------------------------------------------- #
# Listas de materiales — /api/v1/manufacturing/boms
# --------------------------------------------------------------------------- #

boms_router = APIRouter(prefix="/boms", tags=["manufacturing: boms"])


@boms_router.post(
    "",
    response_model=BOMResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una lista de materiales con sus componentes",
)
def create_bom(
    payload: BOMCreate,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_manufacturing),
) -> BOMResponse:
    """Registra una BOM activa única por ``product_id``/``version`` (regla 5)."""
    return BOMResponse.model_validate(services.create_bom(db, payload))


@boms_router.get(
    "",
    response_model=list[BOMResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar listas de materiales",
)
def list_boms(
    product_id: int | None = Query(
        None, gt=0, description="Filtra por producto terminado."
    ),
    is_active: bool | None = Query(
        None, description="Filtra por BOM vigente (true) o histórica (false)."
    ),
    skip: int = Query(0, ge=0, description="Registros a omitir."),
    limit: int = Query(100, ge=1, le=200, description="Máximo de registros."),
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_manufacturing),
) -> list[BOMResponse]:
    """Devuelve las recetas con sus componentes y filtros opcionales."""
    boms = services.list_boms(
        db, product_id=product_id, is_active=is_active, skip=skip, limit=limit
    )
    return [BOMResponse.model_validate(bom) for bom in boms]


@boms_router.get(
    "/{bom_id}",
    response_model=BOMResponse,
    status_code=status.HTTP_200_OK,
    summary="Consultar el detalle de una BOM",
)
def get_bom(
    bom_id: int = Path(..., gt=0, description="Id de la BOM."),
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_manufacturing),
) -> BOMResponse:
    """Devuelve la receta completa con todas sus líneas de componentes."""
    return BOMResponse.model_validate(services.get_bom(db, bom_id))


@boms_router.patch(
    "/{bom_id}/deactivate",
    response_model=BOMResponse,
    status_code=status.HTTP_200_OK,
    summary="Desactivar una BOM",
)
def deactivate_bom(
    bom_id: int = Path(..., gt=0, description="Id de la BOM."),
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_manufacturing),
) -> BOMResponse:
    """Marca la BOM como histórica para permitir otra versión vigente."""
    return BOMResponse.model_validate(services.deactivate_bom(db, bom_id))


# --------------------------------------------------------------------------- #
# Órdenes de producción — /api/v1/manufacturing/orders
# --------------------------------------------------------------------------- #

orders_router = APIRouter(prefix="/orders", tags=["manufacturing: orders"])


@orders_router.post(
    "",
    response_model=ProductionOrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una orden de producción planificada",
)
def create_production_order(
    payload: ProductionOrderCreate,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_manufacturing),
) -> ProductionOrderResponse:
    """Crea una OP en ``PLANNED`` validando BOM, bodegas y cantidad (regla 5)."""
    return ProductionOrderResponse.model_validate(
        services.create_production_order(db, payload)
    )


@orders_router.get(
    "",
    response_model=list[ProductionOrderResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar órdenes de producción",
)
def list_production_orders(
    status_filter: ProductionOrderStatus | None = Query(
        None, alias="status", description="Filtra por estado de la OP."
    ),
    bom_id: int | None = Query(None, gt=0, description="Filtra por BOM."),
    created_date: date_type | None = Query(
        None, description="Filtra por fecha de creación (YYYY-MM-DD)."
    ),
    skip: int = Query(0, ge=0, description="Registros a omitir."),
    limit: int = Query(100, ge=1, le=200, description="Máximo de registros."),
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_manufacturing),
) -> list[ProductionOrderResponse]:
    """Devuelve las OPs filtrables por estado, BOM y fecha de creación."""
    orders = services.list_production_orders(
        db,
        status=status_filter,
        bom_id=bom_id,
        created_date=created_date,
        skip=skip,
        limit=limit,
    )
    return [ProductionOrderResponse.model_validate(order) for order in orders]


@orders_router.get(
    "/{order_id}",
    response_model=ProductionOrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Consultar el detalle de una orden de producción",
)
def get_production_order(
    order_id: int = Path(..., gt=0, description="Id de la orden."),
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_manufacturing),
) -> ProductionOrderResponse:
    """Devuelve la OP con su BOM, componentes, centro y bodegas."""
    return ProductionOrderResponse.model_validate(
        services.get_production_order(db, order_id)
    )


@orders_router.post(
    "/{order_id}/start",
    response_model=ProductionOrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Iniciar una orden de producción",
)
def start_production_order(
    order_id: int = Path(..., gt=0, description="Id de la orden."),
    payload: ProductionOrderStart | None = Body(
        default=None, description="Fecha opcional de inicio."
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_manufacturing),
) -> ProductionOrderResponse:
    """Consume la BOM de forma atómica y pasa la OP a ``IN_PROGRESS``."""
    return ProductionOrderResponse.model_validate(
        services.start_production_order(
            db, order_id, payload, created_by=current_user.username
        )
    )


@orders_router.post(
    "/{order_id}/complete",
    response_model=ProductionOrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Completar una orden de producción",
)
def complete_production_order(
    payload: ProductionOrderComplete,
    order_id: int = Path(..., gt=0, description="Id de la orden."),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_manufacturing),
) -> ProductionOrderResponse:
    """Registra salida, costes y asiento contable, y cierra la OP con ACID."""
    return ProductionOrderResponse.model_validate(
        services.complete_production_order(
            db, order_id, payload, created_by=current_user.username
        )
    )


@orders_router.post(
    "/{order_id}/cancel",
    response_model=ProductionOrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancelar una orden de producción",
)
def cancel_production_order(
    order_id: int = Path(..., gt=0, description="Id de la orden."),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_manufacturing),
) -> ProductionOrderResponse:
    """Cancela la OP revirtiendo sus consumos si ya había empezado."""
    return ProductionOrderResponse.model_validate(
        services.cancel_production_order(db, order_id, created_by=current_user.username)
    )


# --------------------------------------------------------------------------- #
# Agregación
# --------------------------------------------------------------------------- #

router = APIRouter()
router.include_router(work_centers_router)
router.include_router(boms_router)
router.include_router(orders_router)
