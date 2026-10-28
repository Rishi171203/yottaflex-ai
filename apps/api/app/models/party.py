"""Party entities: Customer and Agent."""
from datetime import date, datetime

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from .base import OPS_SCHEMA, OpsBase

TIMESTAMPTZ = TIMESTAMP(timezone=True)


class Customer(OpsBase):
    __table_args__ = (
        CheckConstraint("customer_id ~ '^CST-[0-9]{6}$'", name="ck_customer_id"),
        CheckConstraint("support_tier IN ('free', 'standard', 'premium', 'enterprise')",
                        name="ck_customer_tier"),
        {"schema": OPS_SCHEMA},
    )

    customer_id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text(120), nullable=False)
    support_tier: Mapped[str] = mapped_column(Text, nullable=False)
    signed_up_at: Mapped[date] = mapped_column(Date, nullable=False)
    preferred_language: Mapped[str | None] = mapped_column(
        Text, ForeignKey("ops.language.language_code"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Agent(OpsBase):
    __table_args__ = (
        CheckConstraint("agent_id ~ '^AGT-[0-9]{4}$'", name="ck_agent_id"),
        CheckConstraint("ownership_tier IN ('global', 'regional', 'product_specialist')",
                        name="ck_agent_tier"),
        CheckConstraint("shift_pattern IN ('morning', 'afternoon', 'night', 'split', 'on_call')",
                        name="ck_agent_shift"),
        {"schema": OPS_SCHEMA},
    )

    agent_id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text(120), nullable=False, unique=True)
    ownership_tier: Mapped[str] = mapped_column(Text, nullable=False)
    owned_product_codes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    shift_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(Text(60), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now()
    )
