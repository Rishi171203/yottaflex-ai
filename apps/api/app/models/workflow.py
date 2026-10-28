"""Workflow entities: Ticket, Message, TicketSkill, TicketDuplicateLink, Resolution."""
from datetime import datetime

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import OPS_SCHEMA, OpsBase

TIMESTAMPTZ = TIMESTAMP(timezone=True)

TICKET_STATUS = (
    "new", "triage", "assigned", "in_progress", "pending_customer",
    "resolved", "closed", "reopened", "cancelled",
)
PRIORITY_CODES = ("P1", "P2", "P3", "P4")


class Ticket(OpsBase):
    __table_args__ = (
        CheckConstraint("ticket_id ~ '^TKT-[0-9]{4}-[0-9]{6}$'", name="ck_ticket_id"),
        CheckConstraint(
            "status IN ('new','triage','assigned','in_progress','pending_customer',"
            "'resolved','closed','reopened','cancelled')",
            name="ck_ticket_status",
        ),
        CheckConstraint("priority_current ~ '^P[1-4]$'", name="ck_ticket_priority"),
        CheckConstraint("sentiment_trend IN ('declining','stable','improving')",
                        name="ck_ticket_sentiment"),
        CheckConstraint("sentiment_score >= 0 AND sentiment_score <= 1", name="ck_ticket_sentscore"),
        CheckConstraint(
            "ticket_duplicate_of IS NULL OR ticket_duplicate_of <> ticket_id",
            name="ck_ticket_not_self_dup",
        ),
        {"schema": OPS_SCHEMA},
    )

    ticket_id: Mapped[str] = mapped_column(Text, primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        Text, ForeignKey("ops.customer.customer_id"), nullable=False
    )
    channel_code: Mapped[str] = mapped_column(
        Text, ForeignKey("ops.channel.channel_code"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, index=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="new")
    priority_current: Mapped[str] = mapped_column(Text, nullable=False)
    queue_id_current: Mapped[str | None] = mapped_column(
        Text, ForeignKey("ops.queue.queue_id"), nullable=True
    )
    agent_id_current: Mapped[str | None] = mapped_column(
        Text, ForeignKey("ops.agent.agent_id"), nullable=True
    )
    primary_intent_code: Mapped[str | None] = mapped_column(
        Text, ForeignKey("ops.intent.intent_code"), nullable=True
    )
    language_detected: Mapped[str | None] = mapped_column(
        Text, ForeignKey("ops.language.language_code"), nullable=True
    )
    ticket_duplicate_of: Mapped[str | None] = mapped_column(
        Text, ForeignKey("ops.ticket.ticket_id"), nullable=True
    )
    sentiment_trend: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment_score: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    first_response_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
    sla_responded_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
    sla_resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Message(OpsBase):
    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('customer','agent','ai_assistant','system')",
            name="ck_message_actor",
        ),
        CheckConstraint("sequence_number >= 1", name="ck_message_seq"),
        CheckConstraint(
            "intent_confidence IS NULL OR (intent_confidence >= 0 AND intent_confidence <= 1)",
            name="ck_message_intent_conf",
        ),
        UniqueConstraint("ticket_id", "sequence_number", name="uq_message_ticket_seq"),
        {"schema": OPS_SCHEMA},
    )

    """Open/closed ledger: rows are immutable; corrections append, never update §14.2."""
    ticket_id: Mapped[str] = mapped_column(
        Text, ForeignKey("ops.ticket.ticket_id"), primary_key=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_agent_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("ops.agent.agent_id"), nullable=True
    )
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    intent_code: Mapped[str | None] = mapped_column(
        Text, ForeignKey("ops.intent.intent_code"), nullable=True
    )
    intent_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    language_code_inferred: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text(200), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TicketSkill(OpsBase):
    """Bridge: resolved skill requirements per ticket (replaces a TEXT[] column)."""

    __table_args__ = (
        UniqueConstraint("ticket_id", "skill_code", "valid_from", name="uq_ticketskill_from"),
        {"schema": OPS_SCHEMA},
    )

    ticket_id: Mapped[str] = mapped_column(
        Text, ForeignKey("ops.ticket.ticket_id"), primary_key=True
    )
    skill_code: Mapped[str] = mapped_column(
        Text, ForeignKey("ops.skill.skill_code"), primary_key=True
    )
    source: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # classifier | rule_override | supervisor_manual
    source_rule_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    valid_from: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TicketDuplicateLink(OpsBase):
    """Dedup §14.4: original (target) ← later duplicate (source). Source rows are never deleted."""

    __table_args__ = (
        UniqueConstraint("source_ticket_id", name="uq_ticketdup_source"),
        CheckConstraint("source_ticket_id <> target_ticket_id", name="ck_ticketdup_not_self"),
        CheckConstraint("match_score >= 0 AND match_score <= 1", name="ck_ticketdup_score"),
        {"schema": OPS_SCHEMA},
    )

    source_ticket_id: Mapped[str] = mapped_column(
        Text, ForeignKey("ops.ticket.ticket_id"), primary_key=True
    )
    target_ticket_id: Mapped[str] = mapped_column(
        Text, ForeignKey("ops.ticket.ticket_id"), nullable=False
    )
    match_score: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    match_method: Mapped[str] = mapped_column(Text, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
    superseded_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Resolution(OpsBase):
    __table_args__ = (
        CheckConstraint("resolution_id ~ '^RES-TKT-[0-9]{4}-[0-9]{6}$'", name="ck_resolution_id"),
        CheckConstraint(
            "resolution_type IN ('problem_solved','workaround','duplicate','no_response',"
            "'customer_cancelled','other')",
            name="ck_resolution_type",
        ),
        CheckConstraint("csat >= 1 AND csat <= 5", name="ck_resolution_csat"),
        {"schema": OPS_SCHEMA},
    )

    resolution_id: Mapped[str] = mapped_column(Text, primary_key=True)
    ticket_id: Mapped[str] = mapped_column(
        Text, ForeignKey("ops.ticket.ticket_id"), nullable=False, unique=True
    )
    resolved_by_agent_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("ops.agent.agent_id"), nullable=True
    )
    resolution_type: Mapped[str] = mapped_column(Text, nullable=False)
    root_cause_note: Mapped[str] = mapped_column(Text(500), nullable=False)
    first_contact_resolution: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    csat: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    resolved_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
    reopened_after_resolution: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now()
    )
