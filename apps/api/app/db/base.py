"""Single declarative base for the application (re-exported for Alembic & app code)."""
from app.models.base import GOLD_SCHEMA, OPS_SCHEMA
from app.models.base import OpsBase as Base

__all__ = ["Base", "OPS_SCHEMA", "GOLD_SCHEMA"]
