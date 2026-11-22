"""Esquemas Pydantic v2 del módulo de Manufactura y Producción.

Derivados de ``specs/manufacturing_spec.md`` (secciones 2, 3 y 4) y de los
modelos ORM de ``src.modules.manufacturing.models``. Definen contratos de
entrada (``Create``), actualización parcial (``Update``), salida (``Response``)
y los cuerpos de las transiciones de una orden de producción (``Start`` y
``Complete``).

Principios transversales, alineados con ``hr``, ``accounting`` y ``purchasing``:

* **Sin asignación masiva**: todas las clases declaran
  ``ConfigDict(extra="forbid")``. Los campos controlados por el servicio
  (``status``, ``code`` autogenerado, costes calculados y fechas de transición)
  no se aceptan del cliente en los esquemas de entrada.
* **Dinero, cantidades y horas estrictamente decimales**: se usa el alias
  :data:`StrictDecimal`, que rechaza ``float`` y admite ``Decimal``, ``int`` o
  cadena. Importes y cantidades usan ``max_digits=14, decimal_places=2`` para
  coincidir con ``Numeric(14, 2)``; horas ``Numeric(7, 2)`` y mermas
  ``Numeric(5, 2)``.
* **Validaciones espejo de la BD**: ``cost_per_hour >= 0``, ``quantity > 0``,
  ``0 <= scrap_percentage <= 100``, ``quantity_to_produce > 0`` y
  ``quantity_produced > 0`` al completar. La existencia de al menos un
  ``BOMItem`` se garantiza con ``Field(min_length=1)``.
* **Respuestas desde el ORM**: los esquemas ``Response`` activan
  ``ConfigDict(from_attributes=True)`` para validar directamente entidades
  SQLAlchemy, incluido el detalle de los componentes de una BOM.
* Reglas que requieren consultar estado (BOM activa única, stock suficiente,
  transiciones ``PLANNED -> IN_PROGRESS -> COMPLETED`` e inmutabilidad) se
  resuelven en la capa de servicio, no aquí.
"""

from __future__ import annotations

# Se aliasan los tipos para que los campos ``date`` no choquen con el nombre del
# tipo importado al construir los ``FieldInfo`` de Pydantic.
from datetime import date as date_type, datetime as datetime_type
from decimal import Decimal
from typing import Annotated, Any, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

from src.modules.manufacturing.models import ProductionOrderStatus

__all__ = [
    "BOMCreate",
    "BOMItemCreate",
    "BOMItemResponse",
    "BOMResponse",
    "BOMUpdate",
    "ManufacturingResponseSchema",
    "ManufacturingSchema",
    "ProductionOrderComplete",
    "ProductionOrderCreate",
    "ProductionOrderResponse",
    "ProductionOrderStart",
    "ProductionOrderStatus",
    "StrictDecimal",
    "StrictHours",
    "StrictMoney",
    "StrictPercentage",
    "StrictQuantity",
    "WorkCenterCreate",
    "WorkCenterResponse",
    "WorkCenterUpdate",
]

#: Patrón de códigos de negocio: mayúsculas/dígitos con ``.``, ``-`` o ``_``.
_CODE_PATTERN = r"^[A-Z0-9][A-Z0-9._-]*$"

#: Descripción reutilizable de importes y cantidades ``Numeric(14, 2)``.
_MONEY_DESCRIPTION = "Decimal con hasta 14 enteros y 2 decimales."

#: Descripción reutilizable de horas ``Numeric(7, 2)``.
_HOURS_DESCRIPTION = "Horas decimales con hasta 5 enteros y 2 decimales."

#: Descripción reutilizable del porcentaje de merma ``Numeric(5, 2)``.
_PERCENTAGE_DESCRIPTION = (
    "Porcentaje decimal con hasta 3 enteros y 2 decimales (0–100)."
)


def _reject_float(value: Any) -> Any:
    """Impide que un ``float`` se convierta silenciosamente en ``Decimal``."""
    if isinstance(value, float):
        raise ValueError(
            "Cantidades, horas, mermas e importes deben enviarse como Decimal "
            "o cadena, nunca como float."
        )
    return value


#: ``Decimal`` estricto: acepta ``Decimal``, ``int`` y cadenas, pero no ``float``.
StrictDecimal = Annotated[Decimal, BeforeValidator(_reject_float)]

#: Importes alineados con ``Numeric(14, 2)``.
StrictMoney = Annotated[StrictDecimal, Field(max_digits=14, decimal_places=2)]

#: Cantidades alineadas con ``Numeric(14, 2)``.
StrictQuantity = Annotated[StrictDecimal, Field(max_digits=14, decimal_places=2)]

#: Horas alineadas con ``Numeric(7, 2)``.
StrictHours = Annotated[StrictDecimal, Field(max_digits=7, decimal_places=2)]

#: Mermas alineadas con ``Numeric(5, 2)``.
StrictPercentage = Annotated[StrictDecimal, Field(max_digits=5, decimal_places=2)]


class ManufacturingSchema(BaseModel):
    """Base de los esquemas de manufactura con rechazo de campos desconocidos."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ManufacturingResponseSchema(ManufacturingSchema):
    """Base de las respuestas construidas desde entidades SQLAlchemy."""

    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, from_attributes=True
    )


# --------------------------------------------------------------------------- #
# Centros de trabajo — /api/v1/manufacturing/work-centers
# --------------------------------------------------------------------------- #


class WorkCenterCreate(ManufacturingSchema):
    """Datos para registrar una máquina, línea o estación de trabajo."""

    code: str = Field(
        min_length=1,
        max_length=50,
        pattern=_CODE_PATTERN,
        description="Código único del centro de trabajo.",
        examples=["WC-ENSAMBLE-01"],
    )
    name: str = Field(
        min_length=1,
        max_length=150,
        description="Nombre descriptivo del centro de trabajo.",
        examples=["Línea de ensamble A"],
    )
    cost_per_hour: StrictMoney = Field(
        ge=0,
        description="Costo operativo por hora; no puede ser negativo.",
        examples=["150.00"],
    )
    is_active: bool = Field(
        default=True, description="Indica si el centro de trabajo está operativo."
    )


class WorkCenterUpdate(ManufacturingSchema):
    """Actualización parcial de un centro de trabajo (PATCH)."""

    code: str | None = Field(
        default=None, min_length=1, max_length=50, pattern=_CODE_PATTERN
    )
    name: str | None = Field(default=None, min_length=1, max_length=150)
    cost_per_hour: StrictMoney | None = Field(default=None, ge=0)
    is_active: bool | None = None

    @model_validator(mode="after")
    def _validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Debe enviar al menos un campo para actualizar")
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"El campo '{field}' no puede ser nulo")
        return self


class WorkCenterResponse(ManufacturingResponseSchema):
    """Representación de salida de un centro de trabajo."""

    id: int
    code: str
    name: str
    cost_per_hour: StrictMoney
    is_active: bool
    created_at: datetime_type


# --------------------------------------------------------------------------- #
# Listas de materiales — /api/v1/manufacturing/boms
# --------------------------------------------------------------------------- #


class BOMItemCreate(ManufacturingSchema):
    """Componente de una BOM; la cantidad requerida siempre es positiva."""

    component_product_id: int = Field(
        gt=0, description="Insumo del inventario usado por la receta."
    )
    quantity: StrictQuantity = Field(
        gt=0,
        description="Cantidad requerida por cada unidad del producto final.",
        examples=["1.00"],
    )
    scrap_percentage: StrictPercentage = Field(
        default=Decimal("0.00"),
        ge=0,
        le=100,
        description="Merma esperada del componente (0–100).",
        examples=["0.00"],
    )


class BOMItemResponse(ManufacturingResponseSchema):
    """Representación de salida de una línea de la lista de materiales."""

    id: int
    bom_id: int
    component_product_id: int
    quantity: StrictQuantity
    scrap_percentage: StrictPercentage


class BOMCreate(ManufacturingSchema):
    """Receta con al menos un componente.

    ``code`` debe ser único; el formato se valida aquí y la unicidad se resuelve
    en el índice único de la base de datos y en el servicio. La regla de negocio
    5 exige al menos un ``BOMItem`` y cantidades positivas.
    """

    code: str = Field(
        min_length=1,
        max_length=50,
        pattern=_CODE_PATTERN,
        description="Código único de la lista de materiales.",
        examples=["BOM-LAP-IND-01"],
    )
    product_id: int = Field(
        gt=0, description="Producto terminado que produce la receta."
    )
    version: int = Field(
        default=1, ge=1, description="Número de versión de la receta."
    )
    name: str | None = Field(
        default=None, max_length=200, description="Descripción de la receta (opcional)."
    )
    is_active: bool = Field(
        default=True, description="Indica si la versión está vigente."
    )
    notes: str | None = Field(default=None, description="Observaciones opcionales.")
    items: list[BOMItemCreate] = Field(
        min_length=1,
        description="Componentes de la receta; al menos uno.",
    )

    @model_validator(mode="after")
    def _validate_items(self) -> Self:
        components = [item.component_product_id for item in self.items]
        if len(components) != len(set(components)):
            raise ValueError(
                "No se puede repetir el mismo component_product_id en una BOM"
            )
        return self


class BOMUpdate(ManufacturingSchema):
    """Actualización parcial de una BOM (PATCH).

    Si se envían ``items``, reemplazan por completo a los anteriores y debe
    haber al menos uno. ``name`` y ``notes`` sí pueden limpiarse con ``null``.
    """

    code: str | None = Field(
        default=None, min_length=1, max_length=50, pattern=_CODE_PATTERN
    )
    product_id: int | None = Field(default=None, gt=0)
    version: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None
    notes: str | None = None
    items: list[BOMItemCreate] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Debe enviar al menos un campo para actualizar")

        nullable = {"name", "notes"}
        for field in self.model_fields_set - nullable:
            if getattr(self, field) is None:
                raise ValueError(f"El campo '{field}' no puede ser nulo")

        if self.items is not None:
            components = [item.component_product_id for item in self.items]
            if len(components) != len(set(components)):
                raise ValueError(
                    "No se puede repetir el mismo component_product_id en una BOM"
                )
        return self


class BOMResponse(ManufacturingResponseSchema):
    """Detalle de una receta con todos sus componentes."""

    id: int
    code: str
    product_id: int
    version: int
    name: str | None
    is_active: bool
    notes: str | None
    created_at: datetime_type
    items: list[BOMItemResponse] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Órdenes de producción — /api/v1/manufacturing/orders
# --------------------------------------------------------------------------- #


class ProductionOrderCreate(ManufacturingSchema):
    """Orden nueva en estado ``PLANNED``.

    Si ``code`` se omite, el servicio genera uno secuencial ``OP-YYYY-XXXX``.
    El estado, la cantidad producida y los costes los fija el servicio, por lo
    que no se aceptan del cliente (reglas de negocio 3 y 5).
    """

    code: str | None = Field(
        default=None,
        min_length=1,
        max_length=30,
        pattern=_CODE_PATTERN,
        description="Código único de la OP; si se omite, lo genera el servicio.",
        examples=["OP-2026-0001"],
    )
    bom_id: int = Field(gt=0, description="BOM activa que se va a producir.")
    work_center_id: int | None = Field(
        default=None, gt=0, description="Estación opcional."
    )
    warehouse_source_id: int = Field(
        gt=0, description="Bodega de origen de las materias primas."
    )
    warehouse_destination_id: int = Field(
        gt=0, description="Bodega de destino del producto terminado."
    )
    quantity_to_produce: StrictQuantity = Field(
        gt=0,
        description="Cantidad objetivo a fabricar; siempre mayor que cero.",
        examples=["10.00"],
    )
    estimated_hours: StrictHours = Field(
        default=Decimal("0.00"),
        ge=0,
        description=_HOURS_DESCRIPTION,
        examples=["0.00"],
    )

    @model_validator(mode="after")
    def _validate_warehouses(self) -> Self:
        if self.warehouse_source_id == self.warehouse_destination_id:
            raise ValueError(
                "La bodega de origen y la de destino deben ser distintas"
            )
        return self


class ProductionOrderStart(ManufacturingSchema):
    """Cuerpo opcional de ``POST /{id}/start``.

    El servicio valida stock y transición de estado; la fecha la fija él si se
    omite. No se acepta ``status`` ni cantidades para evitar saltarse reglas.
    """

    started_at: date_type | None = Field(
        default=None, description="Fecha de inicio; el servicio usa hoy si se omite."
    )


class ProductionOrderComplete(ManufacturingSchema):
    """Cuerpo de ``POST /{id}/complete``.

    La regla 6 exige ``quantity_produced > 0``. Los costes unitario y total se
    calculan en el servicio con el consumo real y las horas del centro de
    trabajo, por lo que no forman parte de la entrada.
    """

    quantity_produced: StrictQuantity = Field(
        gt=0,
        description="Cantidad real fabricada; siempre mayor que cero.",
        examples=["10.00"],
    )
    actual_hours: StrictHours = Field(
        default=Decimal("0.00"),
        ge=0,
        description=_HOURS_DESCRIPTION,
        examples=["8.00"],
    )
    completed_at: date_type | None = Field(
        default=None,
        description="Fecha de finalización; el servicio usa hoy si se omite.",
    )


class ProductionOrderResponse(ManufacturingResponseSchema):
    """Representación de salida de una orden de producción."""

    id: int
    code: str
    bom_id: int
    work_center_id: int | None
    warehouse_source_id: int
    warehouse_destination_id: int
    quantity_to_produce: StrictQuantity
    quantity_produced: StrictQuantity
    estimated_hours: StrictHours
    actual_hours: StrictHours
    unit_production_cost: StrictMoney | None
    total_production_cost: StrictMoney | None
    status: ProductionOrderStatus
    started_at: date_type | None
    completed_at: date_type | None
    created_at: datetime_type
