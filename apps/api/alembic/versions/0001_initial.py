"""initial schema: ops tables + gold.ground_truth_label

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-28
"""
from alembic import op
from app.db.base import Base
from app.models import *  # noqa: F401,F403 — registers every table in Base.metadata

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

OPS_SCHEMA = "ops"
GOLD_SCHEMA = "gold"
LEDGER_TABLES = ("message", "assignment_event")


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {OPS_SCHEMA}")
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {GOLD_SCHEMA}")
    Base.metadata.create_all(bind=op.get_bind())
    # closed-ledger enforcement (§14.2/§14.3): forbid UPDATE on Message and AssignmentEvent
    from sqlalchemy import text
    op.execute(text(f"""
        CREATE OR REPLACE FUNCTION {OPS_SCHEMA}.prevent_update() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'closed ledger: UPDATE/DELETE forbidden on %', TG_TABLE_NAME;
        END; $$ LANGUAGE plpgsql;
    """))
    for tbl in LEDGER_TABLES:
        op.execute(text(f"""
            DROP TRIGGER IF EXISTS trg_{tbl}_no_update ON {OPS_SCHEMA}.{tbl};
            CREATE TRIGGER trg_{tbl}_no_update
              BEFORE UPDATE ON {OPS_SCHEMA}.{tbl}
              FOR EACH ROW EXECUTE FUNCTION {OPS_SCHEMA}.prevent_update();
        """))


def downgrade() -> None:
    from sqlalchemy import text
    for tbl in LEDGER_TABLES:
        op.execute(text(f"DROP TRIGGER IF EXISTS trg_{tbl}_no_update ON {OPS_SCHEMA}.{tbl}"))
        op.execute(text(f"DROP FUNCTION IF EXISTS {OPS_SCHEMA}.prevent_update()"))
    Base.metadata.drop_all(bind=op.get_bind())
