"""Routing-organization entities and Agent bridges: Queue, PriorityRule,
EscalationRule, AgentSkill, AgentLanguage, QueueMembership."""
from datetime import date, datetime

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import OPS_SCHEMA, OpsBase

TIMESTAMPTZ = TIMESTAMP(timezone=True)


class Queue(OpsBase):
    __table_args__ = (
        CheckConstraint("queue_id ~ '^QUEUE-[A-Z0-9-]{3,40}$'", name="ck_queue_code"),
        CheckConstraint("routing_strategy IN ('round_robin','least_concurrent','best_skill_match')",
                        name="ck_queue_strategy"),
        CheckConstraint("max_concurrent_tickets BETWEEN 1 AND 10", name="ck_queue_concurrency"),
        {"schema": OPS_SCHEMA},
    )

    queue_id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text(80), nullable=False, unique=True)
    routing_strategy: Mapped[str] = mapped_column(Text, nullable=False)
    max_concurrent_tickets: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    required_skill_codes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    default_calendar_id: Mapped[str] = mapped_column(
        Text, ForeignKey("ops.calendar.calendar_id"), nullable=False
    )
    escalation_queue_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("ops.queue.queue_id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PriorityRule(OpsBase):
    """Effective-dated, first-match-wins priority rules (§7; evaluation in services/priority.py)."""

    __table_args__ = (
        CheckConstraint("rule_id ~ '^PRL-[0-9]{3}$'", name="ck_priorityrule_code"),
        CheckConstraint("rule_order BETWEEN 1 AND 500", name="ck_priorityrule_order"),
        CheckConstraint("priority_outcome ~ '^P[1-4]$'", name="ck_priorityrule_outcome"),
        UniqueConstraint("rule_order", name="uq_priorityrule_rule_order"),
        {"schema": OPS_SCHEMA},
    )

    rule_id: Mapped[str] = mapped_column(Text, primary_key=True)
    rule_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    rule_name: Mapped[str] = mapped_column(Text(120), nullable=False, unique=True)
    conditions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    priority_outcome: Mapped[str] = mapped_column(Text, nullable=False)
    is_terminal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    valid_from: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
    created_by: Mapped[str] = mapped_column(Text(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class EscalationRule(OpsBase):
    """Scheduler rules §12.2; every execution emits an AssignmentEvent (§14.3)."""

    __table_args__ = (
        CheckConstraint("rule_order BETWEEN 1 AND 500", name="ck_escalationrule_order"),
        {"schema": OPS_SCHEMA},
    )

    escalation_rule_id: Mapped[str] = mapped_column(Text, primary_key=True)
    rule_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    trigger: Mapped[dict] = mapped_column(JSONB, nullable=False)
    action: Mapped[dict] = mapped_column(JSONB, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AgentSkill(OpsBase):
    """N:M Agent ↔ Skill with competency metadata (§13)."""

    __table_args__ = (
        UniqueConstraint("agent_id", "skill_code", "valid_from", name="uq_agentskill_from"),
        CheckConstraint("proficiency BETWEEN 1 AND 5", name="ck_agentskill_proficiency"),
        {"schema": OPS_SCHEMA},
    )

    agent_id: Mapped[str] = mapped_column(
        Text, ForeignKey("ops.agent.agent_id"), primary_key=True
    )
    skill_code: Mapped[str] = mapped_column(
        Text, ForeignKey("ops.skill.skill_code"), primary_key=True
    )
    proficiency: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    certified_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    cert_expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_from: Mapped[date] = mapped_column(Date, primary_key=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AgentLanguage(OpsBase):
    """N:M Agent ↔ Language; assignment eligibility requires proficiency ≥ 3 (§13)."""

    __table_args__ = (
        UniqueConstraint("agent_id", "language_code", "valid_from", name="uq_agentlang_from"),
        CheckConstraint("proficiency BETWEEN 1 AND 5", name="ck_agentlang_proficiency"),
        {"schema": OPS_SCHEMA},
    )

    agent_id: Mapped[str] = mapped_column(
        Text, ForeignKey("ops.agent.agent_id"), primary_key=True
    )
    language_code: Mapped[str] = mapped_column(
        Text, ForeignKey("ops.language.language_code"), primary_key=True
    )
    proficiency: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, primary_key=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class QueueMembership(OpsBase):
    """N:M Agent ↔ Queue; assignment pool = currently-valid members (§13)."""

    __table_args__ = (
        UniqueConstraint("agent_id", "queue_id", "valid_from", name="uq_queuemembership_from"),
        {"schema": OPS_SCHEMA},
    )

    agent_id: Mapped[str] = mapped_column(
        Text, ForeignKey("ops.agent.agent_id"), primary_key=True
    )
    queue_id: Mapped[str] = mapped_column(
        Text, ForeignKey("ops.queue.queue_id"), primary_key=True
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now()
    )
