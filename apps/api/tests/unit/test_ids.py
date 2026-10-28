"""Unit tests: business-ID formats and ORM metadata invariants (no DB required)."""
import re

import pytest
from app.models import (
    AssignmentEvent,
    Calendar,
    Message,
    SLAEvent,
    Ticket,
)


@pytest.mark.parametrize(
    ("pattern", "sample", "ok"),
    [
        (r"^TKT-\d{4}-\d{6}$", "TKT-2024-000001", True),
        (r"^TKT-\d{4}-\d{6}$", "TKT-2024-00001", False),
        (r"^CST-\d{6}$", "CST-000123", True),
        (r"^CST-\d{6}$", "CUST-1", False),
        (r"^AGT-\d{4}$", "AGT-0071", True),
        (r"^AGT-\d{4}$", "AGT-71", False),
        (r"^ASN-TKT-\d{4}-\d{6}-\d{3}$", "ASN-TKT-2024-000001-001", True),
        (r"^ASN-TKT-\d{4}-\d{6}-\d{3}$", "ASN-TKT-2024-000001-1", False),
        (r"^RES-TKT-\d{4}-\d{6}$", "RES-TKT-2024-000001", True),
        (r"^INTENT-[A-Z0-9-]{3,40}$", "INTENT-VOICETRANSCRIPT-ERROR", True),
        (r"^INTENT-[A-Z0-9-]{3,40}$", "intent-voice", False),
        (r"^SKILL-[A-Z0-9-]{3,40}$", "SKILL-BILLING-REFUNDS-P2", True),
        (r"^QUEUE-[A-Z0-9-]{3,40}$", "QUEUE-BILLING-P1", True),
        (r"^CHANNEL-[A-Z0-9_]{2,30}$", "CHANNEL-VOICE_INBOUND", True),
        (r"^PRL-[0-9]{3}$", "PRL-001", True),
    ],
)
def test_business_id_formats(pattern, sample, ok):
    assert bool(re.match(pattern, sample)) is ok


def test_all_tables_have_schema():
    assert Ticket.__table__.schema == "ops"
    assert AssignmentEvent.__table__.schema == "ops"
    assert SLAEvent.__table__.schema == "ops"
    assert Calendar.__table__.schema == "ops"


def test_ticket_fixture_ids():
    t = Ticket(ticket_id="TKT-2024-000001", customer_id="CST-000123",
               channel_code="CHANNEL-EMAIL", status="new", priority_current="P2")
    assert t.ticket_id == "TKT-2024-000001"
    m = Message(ticket_id="TKT-2024-000001", sequence_number=1, actor_type="customer", body_text="Hi")
    assert m.sequence_number == 1
