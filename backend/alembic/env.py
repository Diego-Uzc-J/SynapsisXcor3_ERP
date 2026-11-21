"""Entorno de migraciones de Alembic.

Toma la URL de conexión de ``src.core.database.DATABASE_URL`` (que normaliza
``postgresql://`` a ``postgresql+psycopg://``) y compara contra
``Base.metadata``. Importar los modelos de cada módulo registra sus tablas en
los metadatos.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.core.database import Base, DATABASE_URL
from src.modules.accounting import models as accounting_models  # noqa: F401
from src.modules.hr import models as hr_models  # noqa: F401
from src.modules.inventory import models as inventory_models  # noqa: F401
from src.modules.purchasing import models as purchasing_models  # noqa: F401
from src.modules.sales import models as sales_models  # noqa: F401
from src.modules.users import models as users_models  # noqa: F401

# Objeto de configuración de Alembic.
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# `set_main_option` usa ConfigParser, donde `%` debe escaparse.
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Genera el SQL sin conectarse a la base de datos (``alembic upgrade --sql``)."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Aplica las migraciones sobre una conexión real."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
