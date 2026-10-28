"""Ledger event entities: AssignmentEvent and SLAEvent (§9, §10)."""
from datetime import datetime

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import OPS_SCHEMA, OpsBase

TIMESTAMPTZ = TIMESTAMP(timezone=True)


class AssignmentEvent(OpsBase):
    """Closed append-only ledger; every change emits exactly one event (§14.3)."""

    __table_args__ = (
        CheckConstraint("assignment_id ~ '^ASN-TKT-[0-9]{4}-[0-9]{6}-[0-9]{3}$'",
                        name="ck_assignevent_id"),
        UniqueConstraint("ticket_id", "event_seq", name="uq_assignevent_ticket_seq"),
        CheckConstraint(
            "phase IN ('queue_intake','agent_assigned','agent_reassigned',"
            "'queue_reassigned','returned_to_queue')",
            name="ck_assignevent_phase",
        ),
        CheckConstraint(
            "decided_by IN ('system_rule','system_routing_model','supervisor_manual','agent_self_take')",
            name="ck_assignevent_decided_by",
        ),
        CheckConstraint("latency_ms >= 0", name="ck_assignevent_latency"),
        {"schema": OPS_SCHEMA},
    )

    assignment_id: Mapped[str] = mapped_column(Text, primary_key=True)
    ticket_id: Mapped[str] = mapped_column(
        Text, ForeignKey("ops.ticket.ticket_id"), nullable=False
    )
    event_seq: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    event_ts: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
    from_agent_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("ops.agent.agent_id"), nullable=True
    )
    from_queue_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("ops.queue.queue_id"), nullable=True
    )
    to_agent_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("ops.agent.agent_id"), nullable=True
    )
    to_queue_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("ops.queue.queue_id"), nullable=True
    )
    decided_by: Mapped[str] = mapped_column(Text, nullable=False)
    rule_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text(300), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    routing_features: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    priority_override_json: Mapped[dict | None] = mapped_column(
        "priority_override", JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SLAEvent(OpsBase):
    """One row per ticket; state machine recompute (materialized §10 / D-Q runtime)."""

    __table_args__ = (
        UniqueConstraint("ticket_id", name="uq_slaevent_ticket"),
        CheckConstraint("clock_type IN ('calendar','business')", name="ck_slaevent_clock"),
        CheckConstraint("elapsed_paused_minutes >= 0", name="ck_slaevent_pause"),
        CheckConstraint("elapsed_response_minutes >= 0", name="ck_slaevent_elapsed_resp"),
        CheckConstraint("elapsed_resolution_minutes >= 0", name="ck_slaevent_elapsed_res"),
        CheckConstraint(
            "remaining_response_minutes >= -100000", name="ck_slaevent_remaining_resp"
        ),
        {"schema": OPS_SCHEMA},
    )

    ticket_id: Mapped[str] = mapped_column(
        Text, ForeignKey("ops.ticket.ticket_id"), primary_key=True
    )
    policy_id: Mapped[str] = mapped_column(Text, nullable=False)
    clock_type: Mapped[str] = mapped_column(Text, nullable=False)
    sla_started_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
    pause_events: Mapped[dict] = mapped_column(JSONB, nullable=False)
    elapsed_paused_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    elapsed_response_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remaining_response_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    breach_response_flag: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    elapsed_resolution_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remaining_resolution_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    breach_resolution_flag: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    calendar_id_used: Mapped[str] = mapped_column(
        Text, ForeignKey("ops.calendar.calendar_id"), nullable=False
    )
    computed_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now()
    )
