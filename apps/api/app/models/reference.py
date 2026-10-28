"""Reference entities: Language, Channel, Calendar + CalendarHoliday, Intent, Skill.

All live in schema `ops`. Business text IDs are the primary keys (§2 of the data
dictionary). Every table carries created_at / updated_at TIMESTAMPTZ audit columns.
"""
from datetime import date, datetime

from sqlalchemy import TIMESTAMP, Boolean, CheckConstraint, Date, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import OPS_SCHEMA, OpsBase

TIMESTAMPTZ = TIMESTAMP(timezone=True)


class Language(OpsBase):
    __table_args__ = (
        CheckConstraint("language_code ~ '^[a-z]{2}$'", name="ck_language_iso639_1"),
        {"schema": OPS_SCHEMA},
    )

    language_code: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text(60), nullable=False, unique=True)
    is_rtl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    detection_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Channel(OpsBase):
    __table_args__ = (
        CheckConstraint("channel_code ~ '^CHANNEL-[A-Z0-9_]{2,30}$'", name="ck_channel_code"),
        CheckConstraint("priority_weight_modifier BETWEEN 0.5 AND 1.5", name="ck_channel_weight"),
        {"schema": OPS_SCHEMA},
    )

    channel_code: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text(60), nullable=False)
    default_calendar_id: Mapped[str] = mapped_column(
        Text, ForeignKey("ops.calendar.calendar_id"), nullable=False
    )
    priority_weight_modifier: Mapped[float] = mapped_column(nullable=False)
    supports_attachments: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Calendar(OpsBase):
    """Business-hours calendars; clock integrator §14.1 consumes weekly_hours."""

    __table_args__ = ({"schema": OPS_SCHEMA},)
    calendar_id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text(60), nullable=False, unique=True)
    time_zone: Mapped[str] = mapped_column(Text(60), nullable=False)
    weekly_hours: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CalendarHoliday(OpsBase):
    __table_args__ = ({"schema": OPS_SCHEMA},)

    calendar_id: Mapped[str] = mapped_column(
        Text, ForeignKey("ops.calendar.calendar_id"), primary_key=True
    )
    holiday_date: Mapped[date] = mapped_column(Date, primary_key=True)
    description: Mapped[str | None] = mapped_column(Text(200), nullable=True)


class Intent(OpsBase):
    """Deterministic classification catalog (closed set §6.2)."""

    __table_args__ = (
        CheckConstraint("intent_code ~ '^INTENT-[A-Z0-9-]{3,40}$'", name="ck_intent_code"),
        {"schema": OPS_SCHEMA},
    )

    intent_code: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text(80), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text(500), nullable=False)
    default_queue_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("ops.queue.queue_id"), nullable=True
    )
    example_phrasings: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Skill(OpsBase):
    __table_args__ = (
        CheckConstraint("skill_code ~ '^SKILL-[A-Z0-9-]{3,40}$'", name="ck_skill_code"),
        CheckConstraint(
            "category IN ('technical', 'billing', 'process', 'product')", name="ck_skill_category"
        ),
        {"schema": OPS_SCHEMA},
    )

    skill_code: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text(80), nullable=False, unique=True)
    category: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # CHECK technical|billing|process|product
    is_language_skill: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    linked_language_code: Mapped[str | None] = mapped_column(
        Text, ForeignKey("ops.language.language_code"), nullable=True
    )
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now()
    )
