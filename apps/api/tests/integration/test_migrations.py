"""Integration tests — run only when POSTGRES_TEST_DSN is set and reachable.

    docker compose up -d postgres
    export POSTGRES_TEST_DSN=postgresql+psycopg2://yottaflex:yottaflex_dev@localhost:5432/yottaflex
    alembic -c apps/api/alembic.ini upgrade head
    pytest apps/api/tests/integration -m integration
"""
import os

import pytest

POSTGRES_TEST_DSN = os.environ.get("POSTGRES_TEST_DSN", "")

pytestmark = pytest.mark.integration

if not POSTGRES_TEST_DSN:
    # skip the whole module — no live database available
    pytest.skip("POSTGRES_TEST_DSN not set; integration tests skipped", allow_module_level=True)


def test_closed_ledger_blocks_update(postgres_engine):
    import sqlalchemy as sa

    with postgres_engine.begin() as conn:
        conn.execute(sa.text(
            "INSERT INTO ops.customer (customer_id, display_name, support_tier, signed_up_at)"
            " VALUES ('CST-999001','T','free', CURRENT_DATE) ON CONFLICT DO NOTHING"
        ))
        conn.execute(sa.text(
            "INSERT INTO ops.ticket (ticket_id, customer_id, channel_code, created_at,"
            " status, priority_current)"
            " VALUES ('TKT-9999-000001','CST-999001','CHANNEL-EMAIL', NOW(), 'new', 'P2')"
            " ON CONFLICT DO NOTHING"
        ))
        conn.execute(sa.text(
            "INSERT INTO ops.message (ticket_id, sequence_number, actor_type, body_text)"
            " VALUES ('TKT-9999-000001', 1, 'customer', 'hello')"
        ))
        with pytest.raises(sa.exc.DBAPIError, match="closed ledger"):
            conn.execute(sa.text(
                "UPDATE ops.message SET body_text='edited' WHERE ticket_id='TKT-9999-000001'"
            ))
