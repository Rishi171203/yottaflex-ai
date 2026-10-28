"""Counter-based business ID allocation (DATA_DICTIONARY 2 + 16.2).

IDs come from counters, never from RNG. Formats (regex-checked in tests):
- Ticket          ``TKT-<YYYY>-<6d>``
- Customer        ``CST-<6d>``
- Agent           ``AGT-<4d>``
- AssignmentEvent ``ASN-TKT-<YYYY>-<6d>-<3d>`` (per-ticket event counter)
- Resolution      ``RES-TKT-<YYYY>-<6d>``
"""
from __future__ import annotations

DATASET_YEAR = 2026


def _pad(value: int, width: int) -> str:
    return str(value).zfill(width)


class IdAllocator:
    """Emission-order counters; stable when scale changes."""

    __slots__ = ("_counters", "_per_ticket_counters", "year")

    def __init__(self, year: int = DATASET_YEAR) -> None:
        self.year = year
        self._counters = {"customer": 0, "agent": 0, "ticket": 0}
        self._per_ticket_counters: dict[str, int] = {}

    # -- simple entity counters ------------------------------------------------
    def next_ticket_id(self) -> str:
        self._counters["ticket"] += 1
        return f"TKT-{self.year}-{_pad(self._counters['ticket'], 6)}"

    def next_customer_id(self) -> str:
        self._counters["customer"] += 1
        return f"CST-{_pad(self._counters['customer'], 6)}"

    def next_agent_id(self) -> str:
        self._counters["agent"] += 1
        return f"AGT-{_pad(self._counters['agent'], 4)}"

    # -- per-ticket ledger counters --------------------------------------------
    def next_assignment_event_seq(self, ticket_id: str) -> int:
        self._per_ticket_counters[ticket_id] = self._per_ticket_counters.get(ticket_id, 0) + 1
        return self._per_ticket_counters[ticket_id]

    def assignment_event_id(self, ticket_id: str, event_seq: int) -> str:
        """ASN-TKT-<YYYY>-<6d>-<3d>, trailing seq derived from the ticket counter."""
        # ticket_id is TKT-<YYYY>-<6d>; reuse the same numeric stamp.
        return f"ASN-{ticket_id}-{_pad(event_seq, 3)}"

    def resolution_id(self, ticket_id: str) -> str:
        return f"RES-{ticket_id}"
