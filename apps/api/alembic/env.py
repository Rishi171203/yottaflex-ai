import os

from alembic import context
from app.db.base import Base
from app.models import *  # noqa: F401,F403  — imports all model modules so metadata is populated
from sqlalchemy import create_engine, pool

config = context.config
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option(
        "sqlalchemy.url",
        os.environ.get("DATABASE_URL", "postgresql+psycopg2://yottaflex:yottaflex_dev@localhost:5432/yottaflex"),
    )

target_metadata = Base.metadata

OPS_SCHEMA = "ops"
GOLD_SCHEMA = "gold"


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table" and obj.schema == GOLD_SCHEMA:
        return False  # gold schema is populated by its own migration, never diffed here
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
        version_table_schema=OPS_SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(config.get_main_option("sqlalchemy.url"), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            version_table_schema=OPS_SCHEMA,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
