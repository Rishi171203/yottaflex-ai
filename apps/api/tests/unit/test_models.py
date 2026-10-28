"""Metadata-level ORM invariants (no database needed)."""

from app.models import (
    AssignmentEvent,
    Message,
    OpsBase,
    Resolution,
    SLAEvent,
    TicketDuplicateLink,
)


def test_unique_ticket_seq_on_message():
    uniq = [c for c in Message.__table__.constraints if c.__class__.__name__ == "UniqueConstraint"]
    spans = [tuple(col.name for col in c.columns) for c in uniq]
    assert ("ticket_id", "sequence_number") in spans


def test_slaevent_one_row_per_ticket():
    uniq = [c for c in SLAEvent.__table__.constraints if c.__class__.__name__ == "UniqueConstraint"]
    spans = [tuple(col.name for col in c.columns) for c in uniq]
    assert ("ticket_id",) in spans


def test_assignmentevent_unique_ticket_seq():
    uniq = [c for c in AssignmentEvent.__table__.constraints if c.__class__.__name__ == "UniqueConstraint"]
    spans = [tuple(col.name for col in c.columns) for c in uniq]
    assert ("ticket_id", "event_seq") in spans


def test_resolution_unique_ticket():
    uniq = [c for c in Resolution.__table__.constraints if c.__class__.__name__ == "UniqueConstraint"]
    spans = [tuple(col.name for col in c.columns) for c in uniq]
    assert ("ticket_id",) in spans


def test_ticketduplicatelink_source_is_pk():
    pk = tuple(col.name for col in TicketDuplicateLink.__table__.primary_key.columns)
    assert pk == ("source_ticket_id",)


def test_table_count_matches_dictionary():
    table_names = {t.name for t in OpsBase.metadata.sorted_tables}
    assert len(table_names) >= 19  # 13 core + 6 bridges/supporting (gold separate schema name shared ok)
