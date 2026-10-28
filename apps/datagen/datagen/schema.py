"""Schema bridge: reuse the API's SQLAlchemy models as the single source of truth.

datagen must never re-declare column lists (ARCHITECTURE "single implementation
rule"). We import ``apps/api``'s ORM and enumerate ``__table__.columns`` to get,
per table: the emission column order, the CSV column names, and a serializer
category for each attribute key.
"""
from __future__ import annotations

import pathlib
import sys
from typing import Any

_REPO = pathlib.Path(__file__).resolve().parents[2]
_APP_API = _REPO / "apps" / "api"
if _APP_API.exists() and str(_APP_API) not in sys.path:
    sys.path.insert(0, str(_APP_API))

from app.models import base as models_base
from app.models import events, ground_truth, party, reference, routing, workflow
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Double,
    Float,
    Integer,
    Numeric,
    SmallInteger,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

# Attribute-name → SQL column-name renames declared on mapped columns.
_COLUMN_KEY_RENAMES: dict[str, str] = {}

# Emission order = parent-first per DATA_DICTIONARY 16.5 + FK dependencies.
# (schema, SQLAlchemy class) in WRITE order; ticket tables are written per-ticket
# chunks in generators to honour chronological emission.
TABLE_EMISSION_ORDER: list[tuple[str, type[DeclarativeBase]]] = [
    ("ops", reference.Language),
    ("ops", reference.Calendar),
    ("ops", reference.CalendarHoliday),
    ("ops", party.Customer),
    ("ops", party.Agent),
    ("ops", reference.Skill),
    ("ops", reference.Channel),
    ("ops", routing.Queue),
    ("ops", reference.Intent),
    ("ops", routing.PriorityRule),
    ("ops", routing.EscalationRule),
    ("ops", routing.AgentSkill),
    ("ops", routing.AgentLanguage),
    ("ops", routing.QueueMembership),
    ("ops", workflow.Ticket),
    ("ops", workflow.Message),
    ("ops", workflow.TicketSkill),
    ("ops", workflow.TicketDuplicateLink),
    ("ops", workflow.Resolution),
    ("ops", events.AssignmentEvent),
    ("ops", events.SLAEvent),
    ("gold", ground_truth.GroundTruthLabel),
]


def _category(sqla_type: Any) -> str:
    if isinstance(sqla_type, ARRAY):
        return "array"
    if isinstance(sqla_type, JSONB):
        return "jsonb"
    if isinstance(sqla_type, Boolean):
        return "bool"
    if isinstance(sqla_type, Date):
        return "date"
    if isinstance(sqla_type, DateTime):
        return "datetime"
    if isinstance(sqla_type, Numeric):
        return "numeric"
    if isinstance(sqla_type, (Float, Double)):
        return "float"
    if isinstance(sqla_type, (SmallInteger, Integer, BigInteger)):
        return "int"
    if isinstance(sqla_type, Text):
        return "text"
    raise ValueError(f"unmapped SQLAlchemy type: {sqla_type!r}")  # pragma: no cover


def table_column_spec(model_cls: type[DeclarativeBase]) -> list[tuple[str, str, str]]:
    """[(attribute key, SQL column name, serializer category), ...] in table order."""
    spec: list[tuple[str, str, str]] = []
    for column in model_cls.__table__.columns:  # type: ignore[attr-defined]
        category = _category(column.type)
        # find the mapped attribute name (column.key is the attribute name)
        spec.append((column.key, column.name, category))
    return spec


def table_name(model_cls: type[DeclarativeBase]) -> str:
    return model_cls.__tablename__  # type: ignore[attr-defined]


def dataset_tables() -> dict[str, list[tuple[str, str, str]]]:
    """Ordered mapping table_name -> column spec (ops first, gold last)."""
    tables: dict[str, list[tuple[str, str, str]]] = {}
    for _schema, model_cls in TABLE_EMISSION_ORDER:
        tables[table_name(model_cls)] = table_column_spec(model_cls)
    return tables


__all__ = [
    "TABLE_EMISSION_ORDER",
    "dataset_tables",
    "models_base",
    "table_column_spec",
    "table_name",
]
