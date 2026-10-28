"""Ticket ledger generation (Stage 3 centerline: NO anomaly injection, NO routing engine).

Chronological per-ticket emission (DATA_DICTIONARY 16.5 §4): for each ticket in
created_at order we emit Ticket, its Messages, TicketSkill, TicketDuplicateLink,
AssignmentEvent(s), SLAEvent and (when resolved) Resolution, so any CSV consumer
never sees a child before its parent.

Pure derived parts (no RNG): priority (tier baseline max intent floor, mirroring
the emitted PRL rules), intake queue (intent default), clock_type, SLA policy id,
and calendar-aware elapsed minutes. All draws come from the named streams only.
"""
from __future__ import annotations

import datetime as dt

from app.services.domain_config import SLA_POLICY_MATRIX

from ..config import ScaleConfig, weighted_pick
from ..ids import IdAllocator
from ..streams import StreamContext
from .reference_gen import ReferenceCatalog

_MESSAGES_ANCHOR = dt.datetime(2026, 10, 23, 0, 0, tzinfo=dt.UTC)

# Original synthetic thread snippets (in-house wording, ASCII only).
_CUSTOMER_OPENERS: dict[str, list[str]] = {
    "INTENT-LOGIN-FAILURE": [
        "web sso login fails with error code 0xA4 and we cannot reach the dashboards",
        "single sign-on redirects into a loop right after the password change",
        "login keeps failing even after resetting our credentials",
    ],
    "INTENT-OUTAGE-REPORT": [
        "region wide outage: api endpoints return 503 for about ten minutes",
        "our production workspace cannot call the platform apis at all",
        "chat and voice integrations are unreachable since this morning",
    ],
    "INTENT-BILLING-DISPUTE": [
        "we were charged twice for the same monthly invoice amount",
        "the refund we requested three days ago still has not arrived",
        "invoice total does not match the seats actually provisioned",
    ],
    "INTENT-PERFORMANCE-ISSUE": [
        "queries hang for more than a minute on the primary dataset",
        "dashboards stop refreshing after the latest release",
        "job queue rate suddenly dropped to a quarter of normal",
    ],
    "INTENT-PASSWORD-RESET": [
        "password reset emails are not being delivered to our domain",
        "we need a reset for an administrator account we no longer control",
        "reset links expire before anyone can click them",
    ],
    "INTENT-QUOTA-INCREASE": [
        "we need a higher api rate limit before the new campaign launch",
        "requesting additional storage quota for the archive buckets",
        "seat count must go up twenty seats starting monday",
    ],
    "INTENT-API-ERROR": [
        "webhook deliveries return error 412 repeatedly",
        "the python client fails on the events endpoint with unexpected errors",
        "api responses started returning 500 for intermittent calls",
    ],
    "INTENT-ACCOUNT-ACCESS": [
        "we cannot add teammates because the seat limit is suddenly reached",
        "a transferred teammate lost access after the workspace reorg",
        "role change removed visibility into our shared project board",
    ],
}
_CUSTOMER_FOLLOWUPS = (
    "same issue happens again today",
    "still waiting, another failure observed this morning",
    "one more attempt failed with the identical error message",
    "additional context attached, waiting on confirmation",
)
_AGENT_REPLIES = (
    "acknowledged, checking the account configuration now",
    "thanks for the details, reproducing on a test workspace",
    "applied the first mitigation, monitoring for recurrences",
    "root cause narrowed down, applying the stable fix",
    "escalation raised to the platform team for deeper checks",
)
_SYSTEM_DUPLICATE_NOTE = (
    "[auto-close] duplicate of the master report; handled automatically "
    "after the standard deduplication review."
)
_CUSTOMER_WAITING_NOTE = "additional context attached while waiting for a human agent"

# ---------------------------------------------------------------- pure derived

_TIER_BASELINE_PRIORITY = {"enterprise": "P2", "premium": "P3", "standard": "P4", "free": "P4"}
_PRIORITY_ORDER = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}


def derive_priority(tier: str, intent_floor: str | None) -> str:
    """Pure: max(tier baseline, intent floor), mirroring the PRL rule outcomes."""
    baseline = _TIER_BASELINE_PRIORITY[tier]
    if intent_floor is None:
        return baseline
    return min(baseline, intent_floor, key=lambda p: _PRIORITY_ORDER[p])


def derive_policy_id(clock_type: str, priority: str) -> str:
    key = (clock_type, priority)
    if key not in SLA_POLICY_MATRIX:
        raise ValueError(f"SLA_POLICY_MATRIX missing key {key!r}")
    return f"SLA-{clock_type}-{priority}"


def _hhmm_to_minutes(text: str) -> int:
    hours, mins = text.split(":")
    return int(hours) * 60 + int(mins)


def calendar_elapsed_minutes(
    start: dt.datetime,
    end: dt.datetime,
    weekly_hours: dict[str, list[list[str]]],
    holiday_dates: set[dt.date],
) -> int:
    """Elapsed minutes between two UTC timestamps against a weekly-hours calendar."""
    if end <= start:
        return 0
    day_windows: dict[int, list[tuple[int, int]]] = {}
    covered = 0
    for idx, name in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun")):
        windows: list[tuple[int, int]] = []
        for pair in weekly_hours.get(name, []):
            begin, finish = _hhmm_to_minutes(pair[0]), _hhmm_to_minutes(pair[1])
            covered += finish - begin
            windows.append((begin, finish))
        day_windows[idx] = windows
    if covered == 7 * 1440:  # full 24/7 calendar: plain wall-clock delta
        return int((end - start).total_seconds() // 60)
    elapsed = 0
    day = start.date()
    while day <= end.date():
        if day not in holiday_dates:
            for begin, finish in day_windows[day.weekday()]:
                lo = max(begin, start.hour * 60 + start.minute) if day == start.date() else begin
                hi = min(finish, end.hour * 60 + end.minute) if day == end.date() else finish
                if hi > lo:
                    elapsed += hi - lo
        day += dt.timedelta(days=1)
    return max(0, elapsed)


def business_days_between(date_from: dt.date, date_to: dt.date) -> int:
    """Weekday count between two dates (exclusive of date_to), for auto-close checks."""
    days = 0
    current = date_from
    while current < date_to:
        if current.weekday() < 5:
            days += 1
        current += dt.timedelta(days=1)
    return days


# ------------------------------------------------------------------- generator

_STATUS_NO_AGENT_NEEDED = ("resolved", "closed")


def generate_ticket_ledger(
    config: ScaleConfig,
    streams: StreamContext,
    ids: IdAllocator,
    catalog: ReferenceCatalog,
) -> dict[str, list[dict]]:
    rng_tickets = streams.stream("tickets")
    rng_messages = streams.stream("messages")
    rng_assignments = streams.stream("assignment_events")
    rng_resolutions = streams.stream("resolutions")
    rng_sla = streams.stream("sla_events")

    # CalendarHoliday rows are synthetic and calendar-scoped; applied calendar-wide
    # in elapsed math (24/7 calendars shortcut past holidays by design).
    holiday_dates = {dt.date(2026, 10, 1), dt.date(2026, 10, 15)}
    day0 = dt.date.fromisoformat(config.window_start)
    window_end_date = dt.date.fromisoformat(config.window_end)
    sync_iso = _iso(_MESSAGES_ANCHOR)

    rows: dict[str, list[dict]] = {
        "ticket": [], "message": [], "ticket_skill": [], "ticket_duplicate_link": [],
        "assignment_event": [], "sla_event": [], "resolution": [],
    }
    agent_loads: dict[str, int] = {aid: 0 for aid in catalog.agent_ids}
    created_index: list[tuple[str, str]] = []  # (ticket_id, intent_code) in emission order
    dup_source_ids: set[str] = set()
    intent_openers = {code: _CUSTOMER_OPENERS[code] for code in catalog.intent_codes}

    for day_offset in range(config.days):
        day = day0 + dt.timedelta(days=day_offset)
        for slot in range(config.tickets_per_day):
            ticket_id = ids.next_ticket_id()
            intent_code = f"INTENT-{weighted_pick(rng_tickets, config.intent_mix)}"
            channel_code = f"CHANNEL-{weighted_pick(rng_tickets, config.channel_mix)}"
            language = weighted_pick(rng_tickets, config.language_mix)
            customer_id = catalog.customer_ids[rng_tickets.randrange(len(catalog.customer_ids))]
            tier = catalog.customer_tiers.get(customer_id, "standard")
            queue_id = catalog.intent_default_queue[intent_code]
            duplicate_draw = rng_tickets.random() * 100.0 < config.duplicate_rate_pct
            status = weighted_pick(rng_tickets, config.status_mix)
            # D-Q8: a ticket may be closed only if its resolution can sit >=10
            # business days inside the window; later tickets keep the drawn status
            # bumped out of 'closed'.
            close_eligible = business_days_between(day, window_end_date) >= 12
            if status == "closed" and not close_eligible:
                status = "resolved"
            sentiment_trend = weighted_pick(
                rng_tickets, {"stable": 6, "declining": 2, "improving": 2}
            )
            sentiment_score = round(rng_tickets.uniform(0.2, 0.6), 2)

            dup_target = _choose_duplicate_target(
                created_index, intent_code, rng_tickets, dup_source_ids
            ) if duplicate_draw else None
            duplicate = dup_target is not None
            if duplicate:
                status = "closed"  # D-Q7: duplicates auto-close at intake

            priority = derive_priority(tier, catalog.intent_priority_floor.get(intent_code))
            clock_type = catalog.channel_clock_type(channel_code)
            calendar_id = catalog.channel_calendar[channel_code]
            calendar_hours = catalog.calendars[calendar_id]
            created_at = _iso(dt.datetime(
                day.year, day.month, day.day, 9 + (slot % 9),
                rng_tickets.randrange(60), rng_tickets.randrange(60),
                tzinfo=dt.UTC,
            ))

            rows["ticket"].append({
                "ticket_id": ticket_id,
                "customer_id": customer_id,
                "channel_code": channel_code,
                "created_at": created_at,
                "status": status,
                "priority_current": priority,
                "queue_id_current": queue_id,
                "agent_id_current": None,  # patched after assignment events
                "primary_intent_code": intent_code,
                "language_detected": language,
                "ticket_duplicate_of": dup_target,
                "sentiment_trend": sentiment_trend,
                "sentiment_score": sentiment_score,
                "first_response_at": None,  # patched after messages
                "sla_responded_at": None,
                "sla_resolved_at": None,  # patched if resolved
                "updated_at": sync_iso,
            })

            for skill_code in catalog.queue_required_skills.get(queue_id, []):
                rows["ticket_skill"].append({
                    "ticket_id": ticket_id,
                    "skill_code": skill_code,
                    "source": "rule_override",
                    "source_rule_id": None,
                    "valid_from": created_at,
                    "valid_to": None,
                    "created_at": created_at,
                    "updated_at": sync_iso,
                })

            assignment_rows, assigned_agent = _emit_assignment_events(
                _facts := {
                    "ticket_id": ticket_id, "created_at": created_at,
                    "intent_code": intent_code, "channel_code": channel_code,
                    "language": language, "queue_id": queue_id, "priority": priority,
                },
                rng_assignments, rng_tickets, catalog, agent_loads, ids,
                allow_agent=not duplicate,
            )
            rows["assignment_event"].extend(assignment_rows)
            rows["ticket"][-1]["agent_id_current"] = assigned_agent

            thread_rows, first_response, last_msg_iso, dup_detected_iso = _emit_messages(
                ticket_id, created_at, intent_code, channel_code, language, priority,
                catalog, rng_messages, assigned_agent, duplicate, status,
                intent_openers[intent_code],
            )
            rows["message"].extend(thread_rows)

            if duplicate:
                detected_iso = _bump_minutes(last_msg_iso, 1)
                rows["ticket_duplicate_link"].append({
                    "source_ticket_id": ticket_id,
                    "target_ticket_id": dup_target,
                    "match_score": round(rng_tickets.uniform(0.75, 0.95), 3),
                    "match_method": "text_overlap",
                    "detected_at": detected_iso,
                    "superseded_by": None,
                    "created_at": detected_iso,
                    "updated_at": sync_iso,
                })
                dup_source_ids.add(ticket_id)

            if status in _STATUS_NO_AGENT_NEEDED:
                if duplicate:
                    resolved_at = detected_iso
                else:
                    resolution_type = weighted_pick(rng_resolutions, config.resolution_mix)
                    lag_days = rng_resolutions.randrange(0, 4)
                    resolution_date = min(day + dt.timedelta(days=lag_days), window_end_date)
                    resolved_at = _shift_forward(resolution_date, rng_resolutions, last_msg_iso)
                    csat = int(weighted_pick(rng_resolutions, config.csat_mix))
                rows["resolution"].append({
                    "resolution_id": ids.resolution_id(ticket_id),
                    "ticket_id": ticket_id,
                    "resolved_by_agent_id": None if duplicate else assigned_agent,
                    "resolution_type": "duplicate" if duplicate else resolution_type,
                    "root_cause_note": (
                        "deduplicated against the earlier master report at intake auto-close" if duplicate
                        else f"{resolution_type.replace('_', ' ')} confirmed by support engineer"
                    ),
                    "first_contact_resolution": not duplicate and len(thread_rows) <= 2,
                    "csat": None if duplicate else csat,
                    "resolved_at": resolved_at,
                    "reopened_after_resolution": False,
                    "created_at": resolved_at,
                    "updated_at": sync_iso,
                })
                rows["ticket"][-1]["sla_resolved_at"] = resolved_at
                last_msg_iso = max(last_msg_iso, resolved_at)

            if first_response is not None:
                rows["ticket"][-1]["first_response_at"] = first_response
                rows["ticket"][-1]["sla_responded_at"] = first_response
                rows["ticket"][-1]["sentiment_score"] = _bump_sentiment(
                    float(rows["ticket"][-1]["sentiment_score"]), sentiment_trend
                )

            _emit_sla_event(
                rows, ticket_id, created_at, priority, clock_type, calendar_id, calendar_hours,
                first_response, rows["ticket"][-1]["sla_resolved_at"],
                dup_detected_iso, holiday_dates, rng_sla, sync_iso,
            )
            created_index.append((ticket_id, intent_code))
    return rows


# --------------------------------------------------------------------- helpers


def _iso(ts: dt.datetime) -> str:
    return ts.isoformat(timespec="seconds")


def _bump_minutes(iso_ts: str, minutes: int) -> str:
    return _iso(dt.datetime.fromisoformat(iso_ts) + dt.timedelta(minutes=minutes))


def _bump_sentiment(score: float, trend: str) -> float:
    delta = {"improving": 0.2, "stable": 0.05, "declining": -0.2}[trend]
    return round(min(1.0, max(0.0, score + delta)), 2)


def _shift_forward(day: dt.date, rng, base_ts: str) -> str:
    """Resolution timestamp: base + jitter 15 min..12 h, clamped inside `day`."""
    candidate = dt.datetime.fromisoformat(base_ts) + dt.timedelta(
        minutes=rng.randrange(15, 720)
    )
    midnight = dt.datetime(day.year, day.month, day.day, 23, 0, tzinfo=dt.UTC)
    return _iso(min(candidate, midnight))


def _choose_duplicate_target(
    created_index: list[tuple[str, str]], intent_code: str, rng_tickets,
    excluded: set[str],
) -> str | None:
    """Earlier non-duplicate ticket with the same intent (D-Q7: no chains)."""
    same_intent = [
        tid for tid, intent in created_index
        if intent == intent_code and tid not in excluded
    ]
    pool = same_intent or [
        tid for tid, _intent in created_index if tid not in excluded
    ]
    if not pool:
        return None
    recent = pool[-min(80, len(pool)):]
    return recent[rng_tickets.randrange(len(recent))]


def _emit_assignment_events(
    facts, rng_assignments, rng_tickets, catalog, agent_loads, ids, allow_agent: bool
) -> tuple[list[dict], str | None]:
    """Queue intake, then (when allowed) one agent_assigned event; bounded picks."""
    ticket_id, created_at = facts["ticket_id"], facts["created_at"]

    def _new_row(**overrides) -> dict:
        return {
            "assignment_id": ids.assignment_event_id(ticket_id, overrides["event_seq"]),
            "ticket_id": ticket_id,
            "event_seq": overrides["event_seq"],
            "event_ts": overrides["event_ts"],
            "from_agent_id": None,
            "from_queue_id": overrides.get("from_queue_id"),
            "to_agent_id": overrides.get("to_agent_id"),
            "to_queue_id": overrides.get("to_queue_id"),
            "decided_by": "system_rule",
            "rule_id": None,
            "reason": overrides.get("reason"),
            "latency_ms": rng_assignments.randrange(2, 90),
            "routing_features": overrides.get("routing_features", {}),
            "priority_override": None,
            "created_at": created_at,
            "updated_at": _iso(
                dt.datetime.fromisoformat(created_at)
            ),
        }

    rows: list[dict] = [_new_row(
        event_seq=1,
        event_ts=created_at,
        to_queue_id=facts["queue_id"],
        reason="intake: intent default queue",
        routing_features={"intent": facts["intent_code"], "channel": facts["channel_code"]},
    )]
    assigned_agent = None
    if facts["queue_id"] and allow_agent:
        required = catalog.queue_required_skills.get(facts["queue_id"], [])
        assigned_agent = pick_agent_for_ticket(
            facts, catalog, agent_loads, rng_tickets, required
        )
        if assigned_agent is not None:
            agent_loads[assigned_agent] += 1
            rows.append(_new_row(
                event_seq=2,
                event_ts=_bump_minutes(created_at, rng_assignments.randrange(1, 6)),
                from_queue_id=facts["queue_id"],
                to_agent_id=assigned_agent,
                reason="least loaded qualified agent",
                routing_features={
                    "strategy": catalog.queue_strategy.get(facts["queue_id"], "round_robin"),
                    "queue_required_skills": required,
                },
            ))
    return rows, assigned_agent


def pick_agent_for_ticket(
    facts, catalog: ReferenceCatalog, agent_loads: dict[str, int], rng_tickets,
    required_skills: list[str],
) -> str | None:
    """Deterministic agent pick: membership + skills + language + capacity, with
    relaxation tiers; ties broken by ascending agent_id."""
    queue_id, language = facts["queue_id"], facts["language"]

    def _members() -> list[str]:
        return [aid for aid in catalog.agent_ids if queue_id in catalog.agent_queues.get(aid, set())]

    def _capable(pool: list[str], skills: bool, langs: bool) -> list[str]:
        out = []
        for aid in pool:
            if skills and not all(s in catalog.agent_shall_capable.get(aid, []) for s in required_skills):
                continue
            if langs and language != "en" and language not in catalog.agent_lang_capable.get(aid, []):
                continue
            out.append(aid)
        return out

    max_cap = catalog.queue_max_concurrent.get(queue_id, 10)
    under_cap = [aid for aid in _members() if agent_loads.get(aid, 0) < max_cap]
    for pool, skills, langs in (
        (under_cap, True, True),
        (under_cap, False, True),
        (under_cap, False, False),
        (catalog.agent_ids, True, True),
        (catalog.agent_ids, False, True),
        (catalog.agent_ids, False, False),
    ):
        candidates = _capable(pool, skills, langs)
        if not candidates:
            continue
        best_load = min(agent_loads.get(aid, 0) for aid in candidates)
        finalists = sorted(cid for cid in candidates if agent_loads.get(cid, 0) == best_load)
        chosen = finalists[:8]
        return chosen[0] if len(chosen) == 1 else chosen[rng_tickets.randrange(len(chosen))]
    return None


def _emit_messages(
    ticket_id, created_at, intent_code, channel_code, language, priority,
    catalog: ReferenceCatalog, rng_messages, assigned_agent, duplicate, status, openers,
) -> tuple[list[dict], str | None, str, str | None]:
    """Thread: customer opener, agent replies, bounded follow-ups, system notes.

    Returns (rows, first_response_iso, last_iso, duplicate_detected_iso).
    """
    rows: list[dict] = []
    created = dt.datetime.fromisoformat(created_at)
    sync_iso = _iso(_MESSAGES_ANCHOR)

    def _add(sequence, ts, actor, body_text, actor_agent_id, extra):
        rows.append({
            "ticket_id": ticket_id,
            "sequence_number": sequence,
            "actor_type": actor,
            "actor_agent_id": actor_agent_id,
            "body_text": body_text,
            "intent_code": intent_code if actor in ("customer", "ai_assistant") else None,
            "intent_confidence": round(rng_messages.uniform(0.55, 0.95), 3),
            "language_code_inferred": language,
            "override_reason": None,
            "metadata": extra,
            "created_at": _iso(ts),
            "updated_at": sync_iso,
        })

    _add(1, created, "customer", openers[rng_messages.randrange(len(openers))], None,
         {"priority": priority, "channel": channel_code})
    first_response_iso = None
    dup_detected_iso = None
    latest = created

    if duplicate:
        # D-Q7: intake auto-close, one system note, never counted as a response.
        system_ts = created + dt.timedelta(minutes=2)
        _add(2, system_ts, "system", _SYSTEM_DUPLICATE_NOTE, None, {"auto_close": True})
        latest = system_ts
        dup_detected_iso = _bump_minutes(_iso(system_ts), 1)
    elif assigned_agent is not None:
        first_response = created + dt.timedelta(minutes=rng_messages.randrange(3, 40))
        _add(2, first_response, "agent",
             _AGENT_REPLIES[rng_messages.randrange(len(_AGENT_REPLIES))],
             assigned_agent, {"first_response": True})
        first_response_iso = _iso(first_response)
        latest = first_response
        if status in ("resolved", "closed", "in_progress", "pending_customer"):
            for i in range(rng_messages.randrange(0, 3)):
                latest = latest + dt.timedelta(minutes=rng_messages.randrange(5, 180))
                if i % 2 == 0:
                    _add(rows[-1]["sequence_number"] + 1, latest, "customer",
                         _CUSTOMER_FOLLOWUPS[rng_messages.randrange(len(_CUSTOMER_FOLLOWUPS))],
                         None, None)
                else:
                    _add(rows[-1]["sequence_number"] + 1, latest, "agent",
                         _AGENT_REPLIES[rng_messages.randrange(len(_AGENT_REPLIES))],
                         assigned_agent, None)
    else:
        # Unassigned thread: customer waiting note only (SLA response risk).
        waiting = created + dt.timedelta(minutes=rng_messages.randrange(10, 120))
        _add(2, waiting, "customer", _CUSTOMER_WAITING_NOTE, None, {"awaiting_agent": True})
        latest = waiting
    return rows, first_response_iso, _iso(latest), dup_detected_iso


def _emit_sla_event(
    rows, ticket_id, created_at, priority, clock_type, calendar_id, calendar_hours,
    first_response_iso, resolved_iso, duplicate_detected_iso,
    holiday_dates, rng_sla, sync_iso,
) -> None:
    """One SLAEvent row per ticket (§10): elapsed vs targets from the policy matrix."""
    started = dt.datetime.fromisoformat(created_at)
    target_response, target_resolution = SLA_POLICY_MATRIX[(clock_type, priority)]
    del rng_sla  # SLA rows are fully derived (pure) this stage; stream reserved for anomalies

    def _elapsed(iso_ts: str | None):
        if iso_ts is None:
            return None
        return calendar_elapsed_minutes(
            started, dt.datetime.fromisoformat(iso_ts), calendar_hours, holiday_dates
        )

    elapsed_response = _elapsed(first_response_iso)
    elapsed_resolution = _elapsed(resolved_iso or duplicate_detected_iso)
    rows["sla_event"].append({
        "ticket_id": ticket_id,
        "policy_id": derive_policy_id(clock_type, priority),
        "clock_type": clock_type,
        "sla_started_at": created_at,
        "pause_events": {"windows": []},
        "elapsed_paused_minutes": 0,
        "elapsed_response_minutes": elapsed_response,
        "remaining_response_minutes": (
            target_response - elapsed_response if elapsed_response is not None
            else target_response
        ),
        "breach_response_flag": (
            None if elapsed_response is None else elapsed_response > target_response
        ),
        "elapsed_resolution_minutes": elapsed_resolution,
        "remaining_resolution_minutes": (
            target_resolution - elapsed_resolution if elapsed_resolution is not None
            else target_resolution
        ),
        "breach_resolution_flag": (
            None if elapsed_resolution is None else elapsed_resolution > target_resolution
        ),
        "calendar_id_used": calendar_id,
        "computed_at": sync_iso,
        "created_at": sync_iso,
        "updated_at": sync_iso,
    })
