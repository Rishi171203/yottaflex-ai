"""The five ANOM-* detectors (decisions doc D-Q1). Ops data only, never gold."""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from app.services.domain_config import ANOMALY_CODES, SLA_POLICY_MATRIX
from datagen.generators.ticket_gen import calendar_elapsed_minutes

from .dataset import Dataset

(CODE_CAPACITY, CODE_SLA, CODE_HISTORY, CODE_LOOP, CODE_PRIORITY) = ANOMALY_CODES

P1_FLOOR_SUFFIXES = ("OUTAGE-REPORT", "ACCOUNT-SUSPENSION")
FLOOR_PRIORITY = "P1"


def _ts(value: str) -> dt.datetime | None:
    return dt.datetime.fromisoformat(value) if value else None


def _open_at(ds: Dataset, tid: str, at: dt.datetime) -> bool:
    """Ticket is open at `at` if never resolved, or resolved after `at`."""
    resolved_at = _ts(ds.resolutions.get(tid, {}).get("resolved_at", ""))
    return resolved_at is None or resolved_at > at


def _finding(code: str, entity_type: str, entity_id: str, evidence: dict) -> dict:
    return {"anomaly_code": code, "entity_type": entity_type,
            "entity_id": entity_id, "evidence": evidence}


# ------------------------------------------------------ capacity overload
def _queue_cap(ds: Dataset, event: dict, tid: str) -> int:
    """Cap of the queue that governs this assignment.

    Generator shape: agent-assignment rows carry ``to_queue_id`` blank and
    keep the queue in ``from_queue_id`` and ``ticket.queue_id_current``;
    injected rows write ``to_queue_id`` explicitly.
    """
    ticket = ds.tickets.get(tid, {})
    for qid in (event["to_queue_id"], event["from_queue_id"],
                ticket.get("queue_id_current")):
        if qid and qid in ds.caps:
            return ds.caps[qid]
    return 0


def detect_capacity_overload(ds: Dataset) -> list[dict]:
    """Per-assignment-event: concurrent OPEN tickets assigned to that agent.

    Open set at event time t = tickets with an earlier assignment to the agent
    that are not yet resolved at t. Capped by the assignment's governing queue.
    """
    per_agent = defaultdict(list)
    for e in ds.events:
        if e["to_agent_id"]:
            per_agent[e["to_agent_id"]].append(e)
    findings = []
    for aid in sorted(per_agent):
        events = per_agent[aid]
        for e in events:
            at = _ts(e["event_ts"])
            cap = _queue_cap(ds, e, e["ticket_id"])
            concurrent = {
                e2["ticket_id"]
                for e2 in events
                if _ts(e2["event_ts"]) <= at and _open_at(ds, e2["ticket_id"], at)
            }
            if len(concurrent) > cap:
                findings.append(_finding(
                    CODE_CAPACITY, "assignment_event", e["assignment_id"],
                    {"agent_id": aid, "queue_id": e["to_queue_id"] or e["from_queue_id"],
                     "open_at_event_ts": len(concurrent), "queue_cap": cap},
                ))
    findings.sort(key=lambda f: f["entity_id"])
    return findings


# ---------------------------------------------------- SLA calendar-ignored
def _policy_key(ds: Dataset, sla_row: dict, ticket: dict) -> tuple | None:
    """(clock, priority) from the stored policy id (SLA-business-P1 shape).

    Deliberately independent of ``ticket.priority_current`` so a recompute
    does not cascade other families' priority edits into SLA evidence.
    """
    parts = sla_row["policy_id"].split("-")
    prio = parts[-1].upper() if parts and parts[-1].upper() in ("P1", "P2", "P3", "P4") else None
    if prio and len(parts) == 3 and parts[-2] == sla_row["clock_type"]:
        key = (sla_row["clock_type"], prio)
        if key in SLA_POLICY_MATRIX:
            return key
    return (sla_row["clock_type"], ticket["priority_current"])


def _slaclock_mismatch(ds: Dataset, sla_row: dict, ticket: dict,
                       stamp: str, target_index: int,
                       flag_column: str, elapsed_column: str) -> dict | None:
    """Recompute one SLA clock; returns evidence when the flag is wrong."""
    start = _ts(sla_row["sla_started_at"])
    end = _ts(ticket[stamp])
    elapsed_stored = sla_row[elapsed_column]
    flag_stored = sla_row[flag_column]
    if start is None or end is None:
        return None
    key = _policy_key(ds, sla_row, ticket)
    if key is None:
        return None
    windows = ds.calendars.get(sla_row["calendar_id_used"], {})
    elapsed = calendar_elapsed_minutes(start, end, windows, ds.holidays)
    target = SLA_POLICY_MATRIX[key][target_index]
    flag_recomputed = "true" if elapsed > target else "false"
    flags_agree = flag_stored == flag_recomputed
    elapsed_agree = elapsed_stored == "" or int(elapsed_stored) == elapsed
    if not flags_agree or not elapsed_agree:
        return {
            "ticket_id": sla_row["ticket_id"],
            "clock": sla_row["clock_type"],
            "recomputed_elapsed_minutes": elapsed,
            "stored_elapsed_minutes": int(elapsed_stored) if elapsed_stored != "" else None,
            "target_minutes": target,
            flag_column: flag_stored,
            f"recomputed_{flag_column}": flag_recomputed,
        }
    return None


def detect_sla_calendar_ignored(ds: Dataset) -> list[dict]:
    """Stored breach flags disagree with correct-calendar recomputation."""
    findings = []
    for tid in ds.ticket_ids_sorted:
        row = ds.sla_by_ticket.get(tid)
        if row is None:
            continue
        mism = (_slaclock_mismatch(ds, row, ds.tickets[tid], "sla_responded_at", 0,
                                   "breach_response_flag", "elapsed_response_minutes")
                or _slaclock_mismatch(ds, row, ds.tickets[tid], "sla_resolved_at", 1,
                                      "breach_resolution_flag", "elapsed_resolution_minutes"))
        if mism is not None:
            findings.append(_finding(CODE_SLA, "ticket", tid, mism))
    return findings


# ------------------------------------------------------ reopen hist loss
def detect_reopen_history_loss(ds: Dataset) -> list[dict]:
    """Audit-ledger gaps: message sequence numbers not 1..N contiguous."""
    findings = []
    for tid in ds.ticket_ids_sorted:
        msgs = ds.messages.get(tid, [])
        if not msgs:
            continue
        seqs = [int(m["sequence_number"]) for m in msgs]
        if seqs != list(range(1, len(seqs) + 1)):
            findings.append(_finding(
                CODE_HISTORY, "ticket", tid,
                {"n_messages": len(msgs), "sequence_numbers": seqs},
            ))
    findings.sort(key=lambda f: f["entity_id"])
    return findings


# ----------------------------------------------------------- transfer loop
def detect_transfer_loop(ds: Dataset) -> list[dict]:
    """Queue-visit chain ping-pong: any queue visited >=3x, or A->B->A."""
    findings = []
    for tid in ds.ticket_ids_sorted:
        events = ds.ev_by_ticket.get(tid, [])
        queues = [e["to_queue_id"] for e in events if e["to_queue_id"]]
        triple = [i for i in range(len(queues) - 2) if queues[i] == queues[i + 2]]
        overvisit = [q for q in sorted(set(queues)) if queues.count(q) >= 3]
        if overvisit or triple:
            findings.append(_finding(
                CODE_LOOP, "ticket", tid,
                {"queue_visits": queues, "queues_revisited_3x": overvisit,
                 "consecutive_aba_at": [i + 1 for i in triple]},
            ))
    return findings


# --------------------------------------------- priority safety violation
def detect_priority_safety_violation(ds: Dataset) -> list[dict]:
    """P1-floored intents must remain priority_current == 'P1'."""
    findings = []
    for tid in ds.ticket_ids_sorted:
        t = ds.tickets[tid]
        if t["primary_intent_code"].endswith(P1_FLOOR_SUFFIXES) and t["priority_current"] != FLOOR_PRIORITY:
            findings.append(_finding(
                CODE_PRIORITY, "ticket", tid,
                {"primary_intent_code": t["primary_intent_code"],
                 "priority_current": t["priority_current"],
                 "expected_priority": FLOOR_PRIORITY},
            ))
    return findings


DETECTORS = {
    CODE_CAPACITY: detect_capacity_overload,
    CODE_SLA: detect_sla_calendar_ignored,
    CODE_HISTORY: detect_reopen_history_loss,
    CODE_LOOP: detect_transfer_loop,
    CODE_PRIORITY: detect_priority_safety_violation,
}


def run_all(ds: Dataset) -> list[dict]:
    """Run all five detectors against ops data and return merged findings.

    Findings are deterministic: sorted by (anomaly_code, entity_id).
    """
    findings = [f for run in DETECTORS.values() for f in run(ds)]
    findings.sort(key=lambda f: (f["anomaly_code"], f["entity_id"]))
    return findings
