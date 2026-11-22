"""manufacturing: esquema inicial

Revision ID: 92333b3dc7e8
Revises: fd99631fb3f1
Create Date: 2026-11-22 22:02:49.193707+00:00

Crea el esquema del módulo de Manufactura y Producción conforme a
``specs/manufacturing_spec.md`` (sección 2) y a
``backend/src/modules/manufacturing/models.py``:

- enum nativo ``production_order_status``
- centros de trabajo ``work_centers``
- listas de materiales ``bill_of_materials`` y sus líneas ``bom_items``
- órdenes de producción ``production_orders``

El tipo enum se crea y elimina explícitamente, igual que en las migraciones de
``hr``, ``accounting``, ``sales`` y ``purchasing``, para que el ciclo
``upgrade`` / ``downgrade`` sea repetible en PostgreSQL.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "92333b3dc7e8"
down_revision: str | None = "fd99631fb3f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRODUCTION_ORDER_STATUS_VALUES = (
    "PLANNED",
    "IN_PROGRESS",
    "COMPLETED",
    "CANCELLED",
)


def _production_order_status_enum() -> postgresql.ENUM:
    """Tipo enum reutilizable que no intenta crear el tipo por segunda vez."""
    return postgresql.ENUM(
        *PRODUCTION_ORDER_STATUS_VALUES,
        name="production_order_status",
        create_type=False,
    )


def upgrade() -> None:
    bind = op.get_bind()

    # El enum nativo debe existir antes de la tabla que lo utiliza.
    postgresql.ENUM(
        *PRODUCTION_ORDER_STATUS_VALUES, name="production_order_status"
    ).create(bind, checkfirst=True)

    op.create_table(
        "work_centers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("cost_per_hour", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "cost_per_hour >= 0", name="ck_work_centers_cost_per_hour_non_negative"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_work_centers_code"), "work_centers", ["code"], unique=True
    )
    op.create_index(
        "ix_work_centers_is_active", "work_centers", ["is_active"], unique=False
    )

    op.create_table(
        "bill_of_materials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_bill_of_materials_code"),
        "bill_of_materials",
        ["code"],
        unique=True,
    )
    op.create_index(
        "ix_bill_of_materials_is_active",
        "bill_of_materials",
        ["is_active"],
        unique=False,
    )
    op.create_index(
        "ix_bill_of_materials_product_id",
        "bill_of_materials",
        ["product_id"],
        unique=False,
    )
    op.create_index(
        "ix_bill_of_materials_version",
        "bill_of_materials",
        ["version"],
        unique=False,
    )

    op.create_table(
        "bom_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bom_id", sa.Integer(), nullable=False),
        sa.Column("component_product_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "scrap_percentage",
            sa.Numeric(precision=5, scale=2),
            server_default="0.00",
            nullable=False,
        ),
        sa.CheckConstraint("quantity > 0", name="ck_bom_items_quantity_positive"),
        sa.CheckConstraint(
            "scrap_percentage >= 0 AND scrap_percentage <= 100",
            name="ck_bom_items_scrap_percentage_range",
        ),
        sa.ForeignKeyConstraint(
            ["bom_id"], ["bill_of_materials.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["component_product_id"], ["products.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "bom_id", "component_product_id", name="uq_bom_items_bom_component"
        ),
    )
    op.create_index(
        op.f("ix_bom_items_bom_id"), "bom_items", ["bom_id"], unique=False
    )
    op.create_index(
        "ix_bom_items_component_product_id",
        "bom_items",
        ["component_product_id"],
        unique=False,
    )

    op.create_table(
        "production_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("bom_id", sa.Integer(), nullable=False),
        sa.Column("work_center_id", sa.Integer(), nullable=True),
        sa.Column("warehouse_source_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_destination_id", sa.Integer(), nullable=False),
        sa.Column(
            "quantity_to_produce", sa.Numeric(precision=14, scale=2), nullable=False
        ),
        sa.Column(
            "quantity_produced",
            sa.Numeric(precision=14, scale=2),
            server_default="0.00",
            nullable=False,
        ),
        sa.Column(
            "estimated_hours",
            sa.Numeric(precision=7, scale=2),
            server_default="0.00",
            nullable=False,
        ),
        sa.Column(
            "actual_hours",
            sa.Numeric(precision=7, scale=2),
            server_default="0.00",
            nullable=False,
        ),
        sa.Column(
            "unit_production_cost", sa.Numeric(precision=14, scale=2), nullable=True
        ),
        sa.Column(
            "total_production_cost", sa.Numeric(precision=14, scale=2), nullable=True
        ),
        sa.Column(
            "status",
            _production_order_status_enum(),
            server_default=sa.text("'PLANNED'"),
            nullable=False,
        ),
        sa.Column("started_at", sa.Date(), nullable=True),
        sa.Column("completed_at", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "actual_hours >= 0",
            name="ck_production_orders_actual_hours_non_negative",
        ),
        sa.CheckConstraint(
            "estimated_hours >= 0",
            name="ck_production_orders_estimated_hours_non_negative",
        ),
        sa.CheckConstraint(
            "quantity_produced >= 0",
            name="ck_production_orders_quantity_produced_non_negative",
        ),
        sa.CheckConstraint(
            "quantity_to_produce > 0",
            name="ck_production_orders_quantity_to_produce_positive",
        ),
        sa.CheckConstraint(
            "total_production_cost IS NULL OR total_production_cost >= 0",
            name="ck_production_orders_total_cost_non_negative",
        ),
        sa.CheckConstraint(
            "unit_production_cost IS NULL OR unit_production_cost >= 0",
            name="ck_production_orders_unit_cost_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["bom_id"], ["bill_of_materials.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_destination_id"], ["warehouses.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_source_id"], ["warehouses.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["work_center_id"], ["work_centers.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_production_orders_bom_id", "production_orders", ["bom_id"], unique=False
    )
    op.create_index(
        op.f("ix_production_orders_code"),
        "production_orders",
        ["code"],
        unique=True,
    )
    op.create_index(
        "ix_production_orders_created_at",
        "production_orders",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_production_orders_status", "production_orders", ["status"], unique=False
    )
    op.create_index(
        "ix_production_orders_work_center_id",
        "production_orders",
        ["work_center_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_production_orders_work_center_id", table_name="production_orders"
    )
    op.drop_index("ix_production_orders_status", table_name="production_orders")
    op.drop_index("ix_production_orders_created_at", table_name="production_orders")
    op.drop_index(op.f("ix_production_orders_code"), table_name="production_orders")
    op.drop_index("ix_production_orders_bom_id", table_name="production_orders")
    op.drop_table("production_orders")
    op.drop_index("ix_bom_items_component_product_id", table_name="bom_items")
    op.drop_index(op.f("ix_bom_items_bom_id"), table_name="bom_items")
    op.drop_table("bom_items")
    op.drop_index("ix_bill_of_materials_version", table_name="bill_of_materials")
    op.drop_index("ix_bill_of_materials_product_id", table_name="bill_of_materials")
    op.drop_index("ix_bill_of_materials_is_active", table_name="bill_of_materials")
    op.drop_index(op.f("ix_bill_of_materials_code"), table_name="bill_of_materials")
    op.drop_table("bill_of_materials")
    op.drop_index("ix_work_centers_is_active", table_name="work_centers")
    op.drop_index(op.f("ix_work_centers_code"), table_name="work_centers")
    op.drop_table("work_centers")

    # El tipo enum se elimina después de la última tabla que lo referencia.
    postgresql.ENUM(
        *PRODUCTION_ORDER_STATUS_VALUES, name="production_order_status"
    ).drop(op.get_bind(), checkfirst=True)
