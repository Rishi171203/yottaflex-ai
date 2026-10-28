"""Gold-schema entity: GroundTruthLabel (§11) — labelled anomaly ground truth."""
from datetime import datetime

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    Boolean,
    CheckConstraint,
    Identity,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import GOLD_SCHEMA, OpsBase

TIMESTAMPTZ = TIMESTAMP(timezone=True)


class GroundTruthLabel(OpsBase):
    __table_args__ = (
        CheckConstraint("entity_type IN ('ticket','agent','queue','assignment','sla')",
                        name="ck_gt_entity_type"),
        CheckConstraint("severity BETWEEN 1 AND 5", name="ck_gt_severity"),
        {"schema": GOLD_SCHEMA},
    )

    label_id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    anomaly_code: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    related_ids: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    injected_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    severity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    labelled_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now()
    )
