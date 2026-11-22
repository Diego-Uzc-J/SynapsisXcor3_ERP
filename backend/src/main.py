"""Punto de entrada de la API del ERP modular (FastAPI).

Registra los routers de cada módulo de negocio: inventario bajo
``/api/v1/inventory``, ventas bajo ``/api/v1/sales``, compras bajo
``/api/v1/purchasing``, contabilidad bajo ``/api/v1/accounting``, recursos
humanos bajo ``/api/v1/hr`` y usuarios/autenticación bajo ``/api/v1/users``,
conforme a sus respectivas especificaciones en ``specs/``.

``slowapi`` se configura a nivel de aplicación (``app.state.limiter``) para
aplicar los límites de ``/auth/captcha`` y ``/auth/login``.

Al arrancar se ejecuta el seeding idempotente del módulo ``users`` (roles y
superusuario inicial). Si las migraciones aún no se aplicaron, el hook lo
omite y deja constancia en el log.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from src.modules.accounting.router import (
    accounting_exception_handler,
    router as accounting_router,
)
from src.modules.accounting.service import AccountingServiceError
from src.modules.inventory.router import (
    inventory_exception_handler,
    router as inventory_router,
)
from src.modules.hr.router import hr_exception_handler, router as hr_router
from src.modules.hr.service import HRServiceError
from src.modules.inventory.services import InventoryError
from src.modules.purchasing.router import (
    purchasing_exception_handler,
    router as purchasing_router,
)
from src.modules.purchasing.services import PurchasingServiceError
from src.modules.sales.router import (
    router as sales_router,
    sales_exception_handler,
)
from src.modules.sales.services import SalesServiceError
from src.modules.users.router import (
    limiter as users_limiter,
    router as users_router,
    users_exception_handler,
)
from src.modules.users.seeding import seed_users_on_startup
from src.modules.users.services import UserServiceError


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Ejecuta tareas de inicialización antes de aceptar peticiones."""
    seed_users_on_startup()
    yield


app = FastAPI(
    title="SynapsisXcor3 ERP API",
    version="0.1.0",
    description="API del ERP modular construido con FastAPI y SQLAlchemy.",
    lifespan=lifespan,
)

# slowapi necesita el limitador en ``app.state`` para aplicar los cupos de
# ``/api/v1/users/auth/captcha`` y ``/login``.
app.state.limiter = users_limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# El frontend se sirve en otro origen (Vite :5173), por lo que el navegador
# exige CORS: sin esto las peticiones desde React fallan con "Failed to fetch".
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Traduce las excepciones de dominio de inventario a respuestas HTTP.
app.add_exception_handler(InventoryError, inventory_exception_handler)

# Traduce los fallos de autenticación a 400/401/403/423 uniformes.
app.add_exception_handler(UserServiceError, users_exception_handler)

# Traduce las excepciones de dominio de ventas a respuestas HTTP.
app.add_exception_handler(SalesServiceError, sales_exception_handler)

# Traduce las excepciones de dominio de compras a respuestas HTTP.
app.add_exception_handler(PurchasingServiceError, purchasing_exception_handler)

# Traduce las excepciones de dominio de contabilidad a respuestas HTTP.
app.add_exception_handler(AccountingServiceError, accounting_exception_handler)

# Traduce las excepciones de dominio de recursos humanos a respuestas HTTP.
app.add_exception_handler(HRServiceError, hr_exception_handler)

app.include_router(inventory_router, prefix="/api/v1/inventory")
app.include_router(sales_router, prefix="/api/v1/sales")
app.include_router(purchasing_router, prefix="/api/v1/purchasing")
app.include_router(accounting_router, prefix="/api/v1/accounting")
app.include_router(hr_router, prefix="/api/v1/hr")
app.include_router(users_router, prefix="/api/v1/users")
