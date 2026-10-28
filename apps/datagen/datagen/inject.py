"""Injection pass: build a separate anomaly dataset with gold labels.

Reads a complete datagen output tree (clean ops CSVs), deterministically
injects the five ANOM-* anomalies and writes an independent dataset under
``--dst``::

    python -m datagen.inject --src data/out/dev --dst data/out/anomalies

``--src`` stays byte-unchanged. ``--dst/ops`` holds a copy of every ops
table (additive rows shared the t* > last-organic-event spacing rule) and
``--dst/gold/ground_truth_label.csv`` holds gold labels for exactly the
injected entities. Selection is index-based over sorted ids (no RNG), so
two runs over the same source produce byte-identical outputs.

Families (candidates are picked from disjoint ticket sets so families
cannot contaminate each other; see docs/decisions/IMPLEMENTATION_DECISIONS.md D-Q1):

  ANOM-CAPACITY-OVERLOAD          add assignment_event rows pushing agent A's
                                  concurrent open assignments above queue cap
  ANOM-SLA-CALENDAR-IGNORED       flip a stored strict breach flag in the copy
  ANOM-REOPEN-HISTORY-LOSS        add a message row that leaves a sequence gap
  ANOM-TRANSFER-LOOP              add assignment_event rows routing A -> B -> A
  ANOM-PRIORITY-SAFETY-VIOLATION  edit priority_current off the P1 floor
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import shutil
import sys
from pathlib import Path

from app.services.domain_config import ANOMALY_CODES

(CODE_CAPACITY, CODE_SLA, CODE_HISTORY, CODE_LOOP, CODE_PRIORITY) = ANOMALY_CODES

P1_FLOOR_SUFFIXES = ("OUTAGE-REPORT", "ACCOUNT-SUSPENSION")

# Fixed label counts per family (deterministic, index-based selection).
N_SLA = 4
N_HISTORY = 4
N_LOOP = 3
N_PRIORITY = 3
# Minimum concurrent-open baseline for the capacity agent (>=2 avoids 1-off ambiguity).
MIN_OPEN_FOR_CAPACITY = 2

SEVERITY_BY_CODE = {
    CODE_CAPACITY: 4,
    CODE_SLA: 2,
    CODE_HISTORY: 3,
    CODE_LOOP: 3,
    CODE_PRIORITY: 5,
}

MUTATED_TABLES = ("assignment_event", "message", "sla_event", "ticket")

LABELLED_AT = "2026-10-31T00:00:00+00:00"

OPS_TABLES = (
    "agent", "agent_language", "agent_skill", "assignment_event", "calendar",
    "calendar_holiday", "channel", "customer", "escalation_rule", "intent",
    "language", "message", "priority_rule", "queue", "queue_membership",
    "resolution", "skill", "sla_event", "ticket", "ticket_duplicate_link",
    "ticket_skill",
)

GOLD_HEADER = (
    "label_id", "anomaly_code", "entity_type", "entity_id", "related_ids",
    "injected_synthetic", "severity", "explanation", "labelled_at",
    "created_at", "updated_at",
)


def _read_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        return header, [dict(zip(header, r)) for r in reader]


def _write_csv(path: Path, header: list[str], rows: list[dict]) -> None:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([row.get(col, "") for col in header])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        fh.write(buf.getvalue())


def _iso(value: str, delta: dt.timedelta = dt.timedelta(0)) -> str:
    return (dt.datetime.fromisoformat(value) + delta).isoformat(timespec="seconds")


def run_injection(src: Path, dst: Path) -> dict:
    """Read the datagen tree at ``src`` and write the anomaly dataset to ``dst``."""
    src_ops, dst_ops = src / "ops", dst / "ops"
    if not (src_ops / "ticket.csv").exists():
        raise SystemExit(f"expected a datagen output tree under {src} (missing ops/ticket.csv)")
    dst_ops.mkdir(parents=True, exist_ok=True)

    loaded: dict[str, tuple[list[str], list[dict]]] = {}
    for table in OPS_TABLES:
        src_path = src_ops / f"{table}.csv"
        if not src_path.exists():
            continue
        if table in MUTATED_TABLES:
            loaded[table] = _read_csv(src_path)
        else:
            shutil.copyfile(src_path, dst_ops / f"{table}.csv")

    _ticket_hdr, tickets = loaded["ticket"]
    ev_hdr, ev_rows = loaded["assignment_event"]
    ev_by_ticket: dict[str, list[dict]] = {}
    for e in sorted(ev_rows, key=lambda e: (e["event_ts"], int(e["event_seq"]))):
        ev_by_ticket.setdefault(e["ticket_id"], []).append(e)
    _sla_hdr, sla_rows = loaded["sla_event"]
    _msg_hdr, msg_rows = loaded["message"]

    by_id = {t["ticket_id"]: t for t in tickets}

    caps = {r["queue_id"]: int(r["max_concurrent_tickets"])
            for r in _read_csv(dst_ops / "queue.csv")[1]}
    resolutions = {r["ticket_id"]: r["resolved_at"]
                   for r in _read_csv(dst_ops / "resolution.csv")[1]}
    open_tickets = {tid for tid in by_id if tid not in resolutions}

    def open_at(ts: str, tid: str) -> bool:
        """Ticket counts as open at ts: never resolved, or resolved after ts."""
        closed = resolutions.get(tid)
        return closed is None or closed == "" or closed > ts

    labels: list[dict] = []
    used_tickets: set[str] = set()

    def add_label(code: str, entity_type: str, entity_id: str,
                  related: list[str], explanation: str) -> None:
        labels.append({
            "label_id": f"LT-{len(labels) + 1:06d}",
            "anomaly_code": code,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "related_ids": json.dumps(related, separators=(",", ":")),
            "injected_synthetic": "true",
            "severity": str(SEVERITY_BY_CODE[code]),
            "explanation": explanation,
            "labelled_at": LABELLED_AT,
            "created_at": LABELLED_AT,
            "updated_at": LABELLED_AT,
        })

    used_tickets |= _inject_capacity(labels, ev_by_ticket, ev_rows, by_id,
                                     open_tickets, caps, open_at, add_label)
    used_tickets |= _inject_sla(labels, sla_rows, by_id, used_tickets, add_label)
    used_tickets |= _inject_history(labels, msg_rows, by_id, ev_by_ticket, used_tickets, add_label)
    used_tickets |= _inject_loop(labels, ev_by_ticket, ev_hdr, ev_rows,
                                 by_id, sorted(caps), used_tickets, add_label)
    used_tickets |= _inject_priority(labels, by_id, used_tickets, add_label)

    for table in MUTATED_TABLES:
        if table in loaded:
            _write_csv(dst_ops / f"{table}.csv", loaded[table][0], loaded[table][1])

    gold_path = dst / "gold" / "ground_truth_label.csv"
    _write_csv(gold_path, list(GOLD_HEADER), labels)

    counts = {code: 0 for code in ANOMALY_CODES}
    for lab in labels:
        counts[lab["anomaly_code"]] = counts.get(lab["anomaly_code"], 0) + 1
    return {
        "gold_path": str(gold_path),
        "dst_ops": str(dst_ops),
        "labels": len(labels),
        "by_code": counts,
        "tickets_touched": sorted(used_tickets),
    }


def _next_assignment_id(tid: str, seq: int) -> str:
    return f"ASN-TKT-{tid.split('-', 1)[1]}-{seq:03d}"


def _next_message_id(tid: str, seq: int) -> str:
    return f"MSG-TKT-{tid.split('-', 1)[1]}-{seq:04d}"


# ------------------------------------------------------------------ capacity
def _inject_capacity(labels, ev_by_ticket, ev_rows, by_id, open_tickets,
                     caps, open_at, add_label) -> set[str]:
    """One agent A gets (cap + 1) concurrent open assignments by appended rows.

    The governing queue is the ticket's current queue (the generator writes
    ``to_queue_id`` blank on agent assignment rows and keeps the queue in
    ``from_queue_id`` / ``ticket.queue_id_current``). At t* = max(A's ts) + 60s
    the detector counts exactly |A's live tickets| + len(pool) = cap + 1 > cap,
    so every appended row is a finding and no organic row triggers.
    """
    agent_events: dict[str, list[dict]] = {}
    for e in ev_rows:
        if e["to_agent_id"]:
            agent_events.setdefault(e["to_agent_id"], []).append(e)

    for aid in sorted(agent_events):
        events = agent_events[aid]
        t_star = _iso(_max_ts(events), dt.timedelta(seconds=60))
        live = sorted({e["ticket_id"] for e in events if open_at(t_star, e["ticket_id"])})
        if len(live) < MIN_OPEN_FOR_CAPACITY:
            continue
        pool = [tid for tid in sorted(open_tickets)
                if tid not in live
                and all(e["to_agent_id"] != aid for e in ev_by_ticket.get(tid, []))]
        # Prefer unclaimed queue tickets over ones currently held by an agent.
        pool.sort(key=lambda tid: (by_id[tid]["agent_id_current"], tid))
        for home_queue in sorted({by_id[tid]["queue_id_current"] for tid in pool}):
            qpool = [tid for tid in pool if by_id[tid]["queue_id_current"] == home_queue]
            cap_q = caps.get(home_queue, 0)
            to_add = cap_q + 1 - len(live)
            if to_add < 1 or len(qpool) < to_add:
                continue
            template = next(e for e in events if e["to_agent_id"] == aid)
            inject_ids = []
            for tid in qpool[:to_add]:
                seq = max(int(e["event_seq"]) for e in ev_by_ticket[tid]) + 1
                trow = by_id[tid]
                new_row = dict(template)
                new_row.update({
                    "assignment_id": _next_assignment_id(tid, seq),
                    "ticket_id": tid,
                    "event_seq": str(seq),
                    "event_ts": t_star,
                    "from_agent_id": trow["agent_id_current"],
                    "from_queue_id": trow["queue_id_current"],
                    "to_agent_id": aid,
                    "to_queue_id": home_queue,
                    "decided_by": "injected_anomaly",
                    "reason": "Injected capacity anomaly: concurrent open assignments exceed the queue cap (synthetic row).",
                    "latency_ms": "0",
                    "routing_features": json.dumps({"injected": True}, separators=(",", ":")),
                    "created_at": t_star,
                    "updated_at": t_star,
                })
                ev_rows.append(new_row)
                inject_ids.append(new_row["assignment_id"])
                add_label(
                    CODE_CAPACITY, "assignment_event", new_row["assignment_id"],
                    [aid, home_queue, tid],
                    f"Injected: agent {aid} has {cap_q + 1} concurrent open assignments "
                    f"({len(live)} organic + {to_add} synthetic) against queue cap "
                    f"{cap_q} at {t_star}.",
                )
            return set(live) | set(qpool[:to_add])
    return set()  # no eligible agent; capacity family skipped this run


# ---------------------------------------------------------------------- SLA
def _inject_sla(labels, sla_rows, by_id, used, add_label) -> set[str]:
    """Flip the strict breach_response_flag on copied rows (mislabelled clock)."""
    touched: set[str] = set()
    for row in sla_rows:
        if len(touched) >= N_SLA:
            break
        tid = row["ticket_id"]
        if tid in used or tid in touched:
            continue
        flag = row["breach_response_flag"]
        if flag not in ("true", "false") or not row["elapsed_response_minutes"]:
            continue
        row["breach_response_flag"] = "true" if flag == "false" else "false"
        touched.add(tid)
        add_label(
            CODE_SLA, "ticket", tid, [row["policy_id"]],
            f"Injected: stored breach_response_flag flipped from {flag} to "
            f"{row['breach_response_flag']} while calendar-aware recomputation yields {flag}.",
        )
    return touched


# ------------------------------------------------------------------ history
def _inject_history(labels, msg_rows, by_id, ev_by_ticket, used, add_label) -> set[str]:
    """Append a reply per chosen ticket leaving a template gap at N+1."""
    touched: set[str] = set()
    by_ticket: dict[str, list[dict]] = {}
    for m in msg_rows:
        by_ticket.setdefault(m["ticket_id"], []).append(m)
    for tid in sorted(by_ticket):
        if len(touched) >= N_HISTORY:
            break
        if tid in used or tid in touched:
            continue
        msgs = sorted(by_ticket[tid], key=lambda m: int(m["sequence_number"]))
        seqs = [int(m["sequence_number"]) for m in msgs]
        if seqs != list(range(1, len(seqs) + 1)):
            continue  # ledger must be intact before the injected gap
        last = msgs[-1]
        gap_seq = int(last["sequence_number"]) + 2  # gap: N+1 never exists
        ts_reply = _iso(last["created_at"], dt.timedelta(seconds=60))
        new_row = dict(last)
        new_row.update({
            "message_id": _next_message_id(tid, gap_seq),
            "sequence_number": str(gap_seq),
            "created_at": ts_reply,
            "updated_at": ts_reply,
            "body_text": "Synthetic reply appended by anomaly injection (ids above leave sequence gap).",
            "metadata": json.dumps({"injected": True}, separators=(",", ":")),
            "override_reason": "anomaly_injection",
        })
        msg_rows.append(new_row)
        add_label(
            CODE_HISTORY, "ticket", tid, [new_row["message_id"]],
            f"Injected: reply appended with sequence_number {gap_seq} after "
            f"{len(msgs)} contiguous messages; sequence {len(msgs) + 1} is missing.",
        )
        touched.add(tid)
    return touched


# --------------------------------------------------------------------- loop
def _inject_loop(labels, ev_by_ticket, ev_hdr, ev_rows, by_id, queue_ids, used, add_label) -> set[str]:
    """Append two assignment events routing the ticket Q -> B -> Q."""
    touched: set[str] = set()
    for tid in sorted(ev_by_ticket):
        if len(touched) >= N_LOOP:
            break
        if tid in used or tid in touched:
            continue
        current = by_id[tid]["queue_id_current"]
        bounce_to = next((q for q in queue_ids if q != current), None)
        if bounce_to is None:
            continue
        events = ev_by_ticket[tid]
        base_seq = max(int(e["event_seq"]) for e in events)
        base_ts = max(e["event_ts"] for e in events)
        template = next((e for e in events if e["to_queue_id"] and not e["to_agent_id"]), events[0])
        added_ids: list[str] = []
        for step, (q_from, q_to, delta) in enumerate(
                ((current, bounce_to, 60), (bounce_to, current, 120)), start=1):
            ts_step = _iso(base_ts, dt.timedelta(seconds=delta))
            new_row = dict(template)
            new_row.update({
                "assignment_id": _next_assignment_id(tid, base_seq + step),
                "ticket_id": tid,
                "event_seq": str(base_seq + step),
                "event_ts": ts_step,
                "from_agent_id": "",
                "from_queue_id": q_from,
                "to_agent_id": "",
                "to_queue_id": q_to,
                "decided_by": "injected_anomaly",
                "reason": f"Injected transfer loop (step {step}/2): rerouted then bounced back (synthetic row).",
                "latency_ms": "0",
                "routing_features": json.dumps({"injected": True}, separators=(",", ":")),
                "created_at": ts_step,
                "updated_at": ts_step,
            })
            ev_rows.append(new_row)
            added_ids.append(new_row["assignment_id"])
        add_label(
            CODE_LOOP, "ticket", tid, [current, bounce_to] + added_ids,
            f"Injected: routing chain ends {current} -> {bounce_to} -> {current} (ping-pong, no agent work between).",
        )
        touched.add(tid)
    return touched


# ----------------------------------------------------------------- priority
def _inject_priority(labels, by_id, used, add_label) -> set[str]:
    touched: set[str] = set()
    for tid in sorted(by_id):
        if len(touched) >= N_PRIORITY:
            break
        t = by_id[tid]
        if tid in used or tid in touched:
            continue
        if not t["primary_intent_code"].endswith(P1_FLOOR_SUFFIXES):
            continue
        if t["priority_current"] != "P1":
            continue
        t["priority_current"] = "P2"
        touched.add(tid)
        add_label(
            CODE_PRIORITY, "ticket", tid, [],
            f"Injected: intent {t['primary_intent_code']} floors P1 but priority_current was lowered to P2.",
        )
    return touched


def _max_ts(event_list: list[dict]) -> str:
    return max(e["event_ts"] for e in event_list)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="datagen.inject", description=__doc__.splitlines()[0])
    parser.add_argument("--src", required=True, type=Path, help="clean datagen output dir (ops/ + manifest.json)")
    parser.add_argument("--dst", required=True, type=Path, help="destination dir for the anomaly dataset")
    args = parser.parse_args(argv)
    summary = run_injection(args.src, args.dst)
    print(f"injection complete: {summary['labels']} gold labels under {summary['gold_path']}")
    for code in ANOMALY_CODES:
        print(f"  {code}: {summary['by_code'][code]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
