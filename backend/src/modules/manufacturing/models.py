"""Modelos de dominio del módulo de Manufactura y Producción.

Implementa las entidades descritas en ``specs/manufacturing_spec.md`` (sección
2): ``WorkCenter``, ``BillOfMaterials``, ``BOMItem`` y ``ProductionOrder``.

Convenciones alineadas con ``inventory``, ``sales``, ``purchasing`` y ``hr``:

- claves primarias ``Integer`` y fechas ``Date`` / ``DateTime(timezone=True)``;
- importes ``Numeric(14, 2)``, cantidades ``Numeric(14, 2)``, horas
  ``Numeric(7, 2)`` y mermas ``Numeric(5, 2)``, todos tipados como ``Decimal``;
- enum nativo de PostgreSQL para el ciclo de la orden de producción;
- ``ON DELETE RESTRICT`` para las referencias a inventario, BOM y centros de
  trabajo (historial); ``CASCADE`` solo de ``BillOfMaterials`` a sus líneas;
- modelos declarativos SQLAlchemy 2.x con ``Mapped`` / ``mapped_column``.

La clase declarativa ``Base`` es transversal y vive en ``src.core.database``.

La lista de campos entregada usa ``bom_id``, ``started_at`` y ``completed_at``;
la spec emplea ``bill_of_materials_id``, ``start_date`` y ``completion_date``.
Las columnas canónicas siguen la lista entregada y se exponen los nombres de la
spec como ``synonym`` para que ambos contratos funcionen en ORM y en consultas
sin generar columnas adicionales en Alembic.
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
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from src.core.database import Base
from src.modules.inventory.models import Product, Warehouse


class ProductionOrderStatus(str, PyEnum):
    """Ciclo de vida de una orden de producción."""

    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


#: Tipo enum nativo reutilizable con los valores de la spec.
PRODUCTION_ORDER_STATUS_TYPE = SAEnum(
    ProductionOrderStatus,
    name="production_order_status",
    native_enum=True,
    validate_strings=True,
)

#: Importes monetarios del módulo (hasta 999 999 999 999.99).
MONEY = Numeric(14, 2)

#: Cantidades de componentes y producto terminado.
QUANTITY = Numeric(14, 2)

#: Horas estimadas y reales de operación.
HOURS = Numeric(7, 2)

#: Porcentaje de merma por componente (0 a 100).
PERCENTAGE = Numeric(5, 2)


class WorkCenter(Base):
    """Máquina, línea de ensamblaje o grupo de trabajo."""

    __tablename__ = "work_centers"
    __table_args__ = (
        CheckConstraint(
            "cost_per_hour >= 0", name="ck_work_centers_cost_per_hour_non_negative"
        ),
        Index("ix_work_centers_is_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    cost_per_hour: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    orders: Mapped[list[ProductionOrder]] = relationship(back_populates="work_center")

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return f"<WorkCenter id={self.id!r} code={self.code!r}>"


class BillOfMaterials(Base):
    """Receta o lista de materiales para un producto terminado."""

    __tablename__ = "bill_of_materials"
    __table_args__ = (
        Index("ix_bill_of_materials_product_id", "product_id"),
        Index("ix_bill_of_materials_version", "version"),
        Index("ix_bill_of_materials_is_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    # ``name`` figura en la spec; la lista de campos entregada lo omite, por lo
    # que se conserva opcional para no forzarlo en el alta.
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    items: Mapped[list[BOMItem]] = relationship(
        back_populates="bom", cascade="all, delete-orphan"
    )
    orders: Mapped[list[ProductionOrder]] = relationship(back_populates="bom")
    product: Mapped[Product] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return f"<BillOfMaterials id={self.id!r} code={self.code!r}>"


class BOMItem(Base):
    """Componente requerido por unidad del producto final de una BOM."""

    __tablename__ = "bom_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_bom_items_quantity_positive"),
        CheckConstraint(
            "scrap_percentage >= 0 AND scrap_percentage <= 100",
            name="ck_bom_items_scrap_percentage_range",
        ),
        UniqueConstraint(
            "bom_id", "component_product_id", name="uq_bom_items_bom_component"
        ),
        Index("ix_bom_items_component_product_id", "component_product_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bom_id: Mapped[int] = mapped_column(
        ForeignKey("bill_of_materials.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Alias del contrato SDD (``bill_of_materials_id``).
    bill_of_materials_id = synonym("bom_id")
    component_product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    scrap_percentage: Mapped[Decimal] = mapped_column(
        PERCENTAGE, nullable=False, default=Decimal("0.00"), server_default="0.00"
    )

    bom: Mapped[BillOfMaterials] = relationship(back_populates="items")
    component_product: Mapped[Product] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return f"<BOMItem id={self.id!r} bom_id={self.bom_id!r}>"


class ProductionOrder(Base):
    """Orden de producción que transforma insumos en producto terminado."""

    __tablename__ = "production_orders"
    __table_args__ = (
        CheckConstraint(
            "quantity_to_produce > 0",
            name="ck_production_orders_quantity_to_produce_positive",
        ),
        CheckConstraint(
            "quantity_produced >= 0",
            name="ck_production_orders_quantity_produced_non_negative",
        ),
        CheckConstraint(
            "estimated_hours >= 0", name="ck_production_orders_estimated_hours_non_negative"
        ),
        CheckConstraint(
            "actual_hours >= 0", name="ck_production_orders_actual_hours_non_negative"
        ),
        CheckConstraint(
            "unit_production_cost IS NULL OR unit_production_cost >= 0",
            name="ck_production_orders_unit_cost_non_negative",
        ),
        CheckConstraint(
            "total_production_cost IS NULL OR total_production_cost >= 0",
            name="ck_production_orders_total_cost_non_negative",
        ),
        Index("ix_production_orders_bom_id", "bom_id"),
        Index("ix_production_orders_work_center_id", "work_center_id"),
        Index("ix_production_orders_status", "status"),
        Index("ix_production_orders_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(
        String(30), unique=True, nullable=False, index=True
    )
    bom_id: Mapped[int] = mapped_column(
        ForeignKey("bill_of_materials.id", ondelete="RESTRICT"), nullable=False
    )
    #: Alias del contrato SDD (``bill_of_materials_id``).
    bill_of_materials_id = synonym("bom_id")
    work_center_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_centers.id", ondelete="RESTRICT"), nullable=True
    )
    warehouse_source_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    warehouse_destination_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_to_produce: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    quantity_produced: Mapped[Decimal] = mapped_column(
        QUANTITY, nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    estimated_hours: Mapped[Decimal] = mapped_column(
        HOURS, nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    actual_hours: Mapped[Decimal] = mapped_column(
        HOURS, nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    unit_production_cost: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    total_production_cost: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    status: Mapped[ProductionOrderStatus] = mapped_column(
        PRODUCTION_ORDER_STATUS_TYPE,
        nullable=False,
        default=ProductionOrderStatus.PLANNED,
        server_default=ProductionOrderStatus.PLANNED.value,
    )
    started_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: Alias del contrato SDD (``start_date``).
    start_date = synonym("started_at")
    completed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: Alias del contrato SDD (``completion_date``).
    completion_date = synonym("completed_at")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    bom: Mapped[BillOfMaterials] = relationship(back_populates="orders")
    work_center: Mapped[WorkCenter | None] = relationship(back_populates="orders")
    warehouse_source: Mapped[Warehouse] = relationship(
        foreign_keys="ProductionOrder.warehouse_source_id"
    )
    warehouse_destination: Mapped[Warehouse] = relationship(
        foreign_keys="ProductionOrder.warehouse_destination_id"
    )

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return (
            f"<ProductionOrder id={self.id!r} code={self.code!r} "
            f"status={self.status!r}>"
        )


__all__ = [
    "HOURS",
    "MONEY",
    "PERCENTAGE",
    "PRODUCTION_ORDER_STATUS_TYPE",
    "QUANTITY",
    "BOMItem",
    "BillOfMaterials",
    "ProductionOrder",
    "ProductionOrderStatus",
    "WorkCenter",
]
