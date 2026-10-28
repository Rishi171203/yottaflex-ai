"""Business-invariant tests over the emitted s0 CSVs (DATA_DICTIONARY + decision log)."""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest
from datagen.cli import generate_dataset

SEED = 20261022

RE_TICKET = re.compile(r"^TKT-\d{4}-\d{6}$")
RE_CUSTOMER = re.compile(r"^CST-\d{6}$")
RE_AGENT = re.compile(r"^AGT-\d{4}$")
RE_ASSIGNMENT = re.compile(r"^ASN-TKT-\d{4}-\d{6}-\d{3}$")
RE_RESOLUTION = re.compile(r"^RES-TKT-\d{4}-\d{6}$")
ID_RULES = {
    "ticket": RE_TICKET,
    "customer": RE_CUSTOMER,
    "agent": RE_AGENT,
    "assignment_event": RE_ASSIGNMENT,
    "resolution": RE_RESOLUTION,
}


def _load(out_dir: Path, table: str, schema: str = "ops") -> list[dict[str, str]]:
    path = out_dir / schema / f"{table}.csv"
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def s0_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("s0_invariants")
    generate_dataset(SEED, "s0", out, None, force=True)
    return out


def test_id_formats(s0_dir: Path) -> None:
    for table, rule in ID_RULES.items():
        rows = _load(s0_dir, table)
        id_col = next(k for k in rows[0] if k.endswith("_id")) if rows else table[:-1] + "_id"
        assert all(rule.match(r[id_col]) for r in rows), table


def test_ticket_ids_unique_monotonic(s0_dir: Path) -> None:
    tickets = _load(s0_dir, "ticket")
    ids = [t["ticket_id"] for t in tickets]
    assert len(ids) == len(set(ids))
    nums = [int(i.split("-")[2]) for i in ids]
    assert nums == sorted(nums) and nums[0] == 1


def test_foreign_keys_resolve(s0_dir: Path) -> None:
    tickets = _load(s0_dir, "ticket")
    customers = {c["customer_id"] for c in _load(s0_dir, "customer")}
    ticket_ids = {t["ticket_id"] for t in tickets}
    msg_ids = {m["ticket_id"] for m in _load(s0_dir, "message")}
    assert {t["customer_id"] for t in tickets} <= customers
    assert msg_ids <= ticket_ids
    for table in ("assignment_event", "sla_event"):
        assert {r["ticket_id"] for r in _load(s0_dir, table)} <= ticket_ids
    dup_ids = {(d["source_ticket_id"], d["target_ticket_id"]) for d in _load(s0_dir, "ticket_duplicate_link")}
    assert all(a in ticket_ids and b in ticket_ids for a, b in dup_ids)


def test_assignment_seq_per_ticket_contiguous(s0_dir: Path) -> None:
    seqs: dict[str, list[int]] = {}
    for row in _load(s0_dir, "assignment_event"):
        seqs.setdefault(row["ticket_id"], []).append(int(row["event_seq"]))
    for per_ticket in seqs.values():
        assert per_ticket == list(range(1, len(per_ticket) + 1))


def test_first_assignment_event_is_intake(s0_dir: Path) -> None:
    by_ticket: dict[str, list[dict]] = {}
    for row in _load(s0_dir, "assignment_event"):
        by_ticket.setdefault(row["ticket_id"], []).append(row)
    for ticket in _load(s0_dir, "ticket"):
        first = min(by_ticket[ticket["ticket_id"]], key=lambda r: int(r["event_seq"]))
        assert first["event_ts"] == ticket["created_at"]
        assert first["to_queue_id"] == ticket["queue_id_current"]


def test_priority_floor_enforced(s0_dir: Path) -> None:
    for ticket in _load(s0_dir, "ticket"):
        if ticket["primary_intent_code"] in ("INTENT-OUTAGE-REPORT", "INTENT-ACCOUNT-SUSPENSION"):
            assert ticket["priority_current"] == "P1"


def test_resolution_completeness(s0_dir: Path) -> None:
    resolutions = {r["ticket_id"]: r for r in _load(s0_dir, "resolution")}
    dups = {d["source_ticket_id"]: d for d in _load(s0_dir, "ticket_duplicate_link")}
    no_resolution_ok = {"in_progress", "pending_customer", "closed"}
    for ticket in _load(s0_dir, "ticket"):
        if ticket["status"] == "resolved":
            assert ticket["ticket_id"] in resolutions
            assert ticket["agent_id_current"] == resolutions[ticket["ticket_id"]]["resolved_by_agent_id"]
        elif ticket["status"] in no_resolution_ok and ticket["ticket_id"] not in dups:
            assert ticket["ticket_id"] not in resolutions


def test_sla_event_per_ticket(s0_dir: Path) -> None:
    sla_ids = {s["ticket_id"] for s in _load(s0_dir, "sla_event")}
    assert sla_ids == {t["ticket_id"] for t in _load(s0_dir, "ticket")}


def test_duplicate_chain_free_and_auto_closed(s0_dir: Path) -> None:
    tickets = {t["ticket_id"]: t for t in _load(s0_dir, "ticket")}
    resolutions = {r["ticket_id"]: r for r in _load(s0_dir, "resolution")}
    dups = _load(s0_dir, "ticket_duplicate_link")
    dup_sources = {d["source_ticket_id"] for d in dups}
    dup_targets = {d["target_ticket_id"] for d in dups}
    assert not (dup_sources & dup_targets), "D-Q7 forbids duplicate chains"
    for dup in dups:
        ticket = tickets[dup["source_ticket_id"]]
        assert ticket["ticket_duplicate_of"] == dup["target_ticket_id"]
        assert ticket["status"] == "closed"
        assert ticket["agent_id_current"] == ""
        res = resolutions[dup["source_ticket_id"]]
        assert res["resolution_type"] == "duplicate"
        assert res["csat"] == ""
        assert res["resolved_at"] == dup["detected_at"]
    for ticket in tickets.values():
        if ticket["ticket_duplicate_of"]:
            assert ticket["ticket_id"] in dup_sources


def test_message_sequence_pads(s0_dir: Path) -> None:
    counted: dict[str, int] = {}
    for row in _load(s0_dir, "message"):
        counted[row["ticket_id"]] = counted.get(row["ticket_id"], 0) + 1
    assert all(1 <= n <= 999 for n in counted.values())
    assert all(row["sequence_number"].isdigit() for row in _load(s0_dir, "message"))


def test_ground_truth_header_only(s0_dir: Path) -> None:
    path = s0_dir / "gold" / "ground_truth_label.csv"
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert len(rows) <= 1
