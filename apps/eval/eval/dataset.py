"""CSV loaders for the ops tables used by the anomaly detectors."""
from __future__ import annotations

import csv
import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

OPS_TABLES = (
    "agent", "agent_language", "agent_skill", "assignment_event", "calendar",
    "calendar_holiday", "channel", "customer", "escalation_rule", "intent",
    "language", "message", "priority_rule", "queue", "queue_membership",
    "resolution", "skill", "sla_event", "ticket", "ticket_duplicate_link",
    "ticket_skill",
)


@dataclass
class Dataset:
    root: Path
    tickets: dict[str, dict]
    events: list[dict]
    ev_by_ticket: dict[str, list[dict]]
    messages: dict[str, list[dict]]
    sla_by_ticket: dict[str, dict]
    resolutions: dict[str, dict]
    caps: dict[str, int]
    calendars: dict[str, dict]
    holidays: frozenset
    ticket_ids_sorted: list[str]


def read_table(ops_dir: Path, table: str) -> list[dict]:
    path = ops_dir / f"{table}.csv"
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader)


def load_dataset(ops_dir: Path) -> Dataset:
    ops_dir = Path(ops_dir)
    tickets = {r["ticket_id"]: r for r in read_table(ops_dir, "ticket")}
    events = sorted(
        read_table(ops_dir, "assignment_event"),
        key=lambda e: (e["event_ts"], e["assignment_id"]),
    )
    ev_by_ticket: dict[str, list[dict]] = {}
    for e in events:
        ev_by_ticket.setdefault(e["ticket_id"], []).append(e)

    messages_by_ticket: dict[str, list[dict]] = {}
    for m in read_table(ops_dir, "message"):
        messages_by_ticket.setdefault(m["ticket_id"], []).append(m)
    for lst in messages_by_ticket.values():
        lst.sort(key=lambda m: (int(m["sequence_number"]), m["created_at"]))

    sla_by_ticket = {r["ticket_id"]: r for r in read_table(ops_dir, "sla_event")}
    resolutions = {r["ticket_id"]: r for r in read_table(ops_dir, "resolution")}
    caps = {r["queue_id"]: int(r["max_concurrent_tickets"])
            for r in read_table(ops_dir, "queue")}
    calendars = {}
    for r in read_table(ops_dir, "calendar"):
        calendars[r["calendar_id"]] = json.loads(r["weekly_hours"])
    # Holidays are applied dataset-wide, mirroring the generator semantics.
    holidays = frozenset(
        dt.date.fromisoformat(r["holiday_date"])
        for r in read_table(ops_dir, "calendar_holiday")
        if r.get("holiday_date")
    )
    return Dataset(
        root=ops_dir,
        tickets=tickets,
        events=events,
        ev_by_ticket=ev_by_ticket,
        messages=messages_by_ticket,
        sla_by_ticket=sla_by_ticket,
        resolutions=resolutions,
        caps=caps,
        calendars=calendars,
        holidays=holidays,
        ticket_ids_sorted=sorted(tickets),
    )
