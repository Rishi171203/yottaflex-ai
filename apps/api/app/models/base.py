import re

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase, declared_attr

OPS_SCHEMA = "ops"
GOLD_SCHEMA = "gold"

# Stable constraint naming (helps future Alembic autogenerate diffs).
conventions = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


def camel_to_snake(name: str) -> str:
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s1).lower()


class OpsBase(DeclarativeBase):
    """Declarative base with camel→snake table naming (SQLAlchemy 2.1 dropped auto-generation)."""

    metadata = conventions

    @declared_attr.directive
    def __tablename__(cls) -> str:  # noqa: N805
        return camel_to_snake(cls.__name__)



class AuditMixin:
    """§1.2: every entity carries created_at / updated_at (TIMESTAMPTZ, DB-defaulted)."""
