"""Reference/bridge entity generation (DATA_DICTIONARY 16.5 emission order, parent-first).

Stream discipline: every generator consumes exactly ONE named stream with a
per-entity FIXED number of draws (no loops with variable draw counts), so output
is stable when scale knobs change.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from ..config import ScaleConfig, weighted_pick
from ..ids import IdAllocator
from ..streams import StreamContext


@dataclass
class ReferenceCatalog:
    """In-memory catalogue shared by generators (no re-draws)."""

    language_codes: list[str] = field(default_factory=list)
    calendar_ids: list[str] = field(default_factory=list)
    calendars: dict[str, dict] = field(default_factory=dict)
    customer_ids: list[str] = field(default_factory=list)
    customer_tiers: dict[str, str] = field(default_factory=dict)
    agent_ids: list[str] = field(default_factory=list)
    agent_primary_queue: dict[str, str] = field(default_factory=dict)
    agent_queues: dict[str, set[str]] = field(default_factory=dict)
    agent_shall_capable: dict[str, list[str]] = field(default_factory=dict)
    agent_lang_capable: dict[str, list[str]] = field(default_factory=dict)
    agent_shifts: dict[str, str] = field(default_factory=dict)
    skill_codes: list[str] = field(default_factory=list)
    language_skill_codes: list[str] = field(default_factory=list)
    channel_ids: list[str] = field(default_factory=list)
    channel_calendar: dict[str, str] = field(default_factory=dict)
    channel_is_24x7: dict[str, bool] = field(default_factory=dict)
    queue_ids: list[str] = field(default_factory=list)
    queue_required_skills: dict[str, list[str]] = field(default_factory=dict)
    queue_max_concurrent: dict[str, int] = field(default_factory=dict)
    queue_strategy: dict[str, str] = field(default_factory=dict)
    intent_codes: list[str] = field(default_factory=list)
    intent_default_queue: dict[str, str] = field(default_factory=dict)
    intent_priority_floor: dict[str, str] = field(default_factory=dict)

    def calendar_is_24x7(self, calendar_id: str) -> bool:
        """Every covered day has exactly one 00:00-24:00 window."""
        windows = self.calendars.get(calendar_id)
        if not windows:
            return False
        for windows_that_day in windows.values():
            if not windows_that_day:
                return False
            if not all(w != [] for w in windows_that_day):
                return False
            for w in windows_that_day:
                if w != ["00:00", "24:00"]:
                    return False
        return len(windows) == 7

    def channel_clock_type(self, channel_id: str) -> str:
        """Pure function: 24/7 calendar coverage ⇒ 'calendar' clock; else 'business'."""
        return "calendar" if self.channel_is_24x7[channel_id] else "business"


_SYNC = dt.date(2026, 10, 23)  # deterministic "now" for audit columns (never wall clock)

# pools kept small and ASCII; all original in-house synthetic strings
_FIRST_NAME_POOL = ["Adele", "Bruno", "Carla", "Divya", "Elena", "Farid", "Grace", "Hiroishi",
                    "Imani", "Jonas", "Kavya", "Liam", "Mei", "Noor", "Otto", "Priya",
                    "Quinn", "Ravi", "Sofia", "Tomas", "Uma", "Vikram", "Wen", "Yara",
                    "Zain", "Iris", "Kenji", "Lena", "Marco", "Nadia"]
_LAST_NAME_POOL = ["Abbott", "Bauer", "Cheng", "Dubois", "Eguchi", "Ferrari", "Gustafsson",
                   "Haddad", "Iqbal", "Jensen", "Kapoor", "Laurent", "Moreau", "Novak",
                   "Okafor", "Park", "Quintero", "Rossi", "Silva", "Tanaka", "Ueda",
                   "Vasquez", "Weber", "Xu", "Yilmaz", "Zhang"]
_TEAM_NAME_POOL = ["Meridian", "Northwind", "Aurora", "Summit", "Beacon", "Cascade",
                   "Halcyon", "Vertex", "Cardinal", "Fairview"]
_ROLE_SUFFIX = ["Support", "Service", "Solutions", "Platform", "Systems"]

_PRODUCT_POOL = ["PROD-BILLING", "PROD-COMPUTE", "PROD-STORAGE", "PROD-NETWORK"]

_SKILL_CATALOG: tuple[tuple[str, str], ...] = (
    ("SKILL-BILLING-T1", "billing"),
    ("SKILL-BILLING-T2", "billing"),
    ("SKILL-ACCOUNT-ACCESS", "account"),
    ("SKILL-SECURITY-RESPONSE", "security"),
    ("SKILL-DESKTOP-SUPPORT", "technical"),
    ("SKILL-NETWORK-TROUBLESHOOTING", "technical"),
    ("SKILL-API-INTEGRATION", "technical"),
    ("SKILL-MOBILE-APP-DEBUGGING", "technical"),
    ("SKILL-PRODUCT-ADVISORY", "advisory"),
    ("SKILL-QUOTA-LICENSES", "account"),
    ("SKILL-DATA-EXPORT", "account"),
    ("SKILL-COMPLIANCE", "security"),
)
_LANGUAGE_SKILL_MAP = {
    "hi": "SKILL-LANG-HINDI", "ta": "SKILL-LANG-TAMIL", "es": "SKILL-LANG-SPANISH",
    "fr": "SKILL-LANG-FRENCH", "de": "SKILL-LANG-GERMAN", "ja": "SKILL-LANG-JAPANESE",
    "pt": "SKILL-LANG-PORTUGUESE", "ko": "SKILL-LANG-KOREAN",
}
_LANGUAGE_DISPLAY = {
    "en": "English", "hi": "Hindi", "ta": "Tamil", "es": "Spanish", "fr": "French",
    "de": "German", "ja": "Japanese", "pt": "Portuguese", "ko": "Korean",
}

_INTENT_CATALOG: tuple[tuple[str, str], ...] = (
    ("LOGIN-FAILURE", "INTENT-LOGIN-FAILURE"),
    ("OUTAGE-REPORT", "INTENT-OUTAGE-REPORT"),
    ("BILLING-DISPUTE", "INTENT-BILLING-DISPUTE"),
    ("PERFORMANCE-ISSUE", "INTENT-PERFORMANCE-ISSUE"),
    ("PASSWORD-RESET", "INTENT-PASSWORD-RESET"),
    ("QUOTA-INCREASE", "INTENT-QUOTA-INCREASE"),
    ("API-ERROR", "INTENT-API-ERROR"),
    ("ACCOUNT-ACCESS", "INTENT-ACCOUNT-ACCESS"),
)


def _week_hours(cover: dict[int, list[list[str]]]) -> dict[str, list[list[str]]]:
    days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    return {name: cover.get(i, []) for i, name in enumerate(days)}


def _anchor(day: dt.date, hour: int = 0, minute: int = 0) -> str:
    return f"{day.isoformat()}T{hour:02d}:{minute:02d}:00+00:00"


# ---------------------------------------------------------------------------
# individual generators
# ---------------------------------------------------------------------------

def generate_languages(config: ScaleConfig, streams: StreamContext, ids: IdAllocator,
                       catalog: ReferenceCatalog) -> list[dict]:
    catalog.language_codes = list(_LANGUAGE_DISPLAY)
    anchor_day = dt.date.fromisoformat(config.window_start)
    return [
        {"language_code": code, "display_name": display, "detection_enabled": True,
         "is_rtl": False,
         "created_at": _anchor(anchor_day, 9, 0), "updated_at": _anchor(anchor_day, 9, 0)}
        for code, display in _LANGUAGE_DISPLAY.items()
    ]


def generate_calendars(config: ScaleConfig, streams: StreamContext, ids: IdAllocator,
                       catalog: ReferenceCatalog) -> tuple[list[dict], list[dict]]:
    """Calendar + CalendarHoliday: one 24/7, two 9-17 business calendars."""
    anchor_day = dt.date.fromisoformat(config.window_start)
    spec = {
        "CAL-24X7": {"tz": "UTC", "display_name": "24x7 (UTC)",
                     "hours": {i: [["00:00", "24:00"]] for i in range(7)}},
        "CAL-BUSINESS-UTC": {"tz": "UTC", "display_name": "Business Hours (UTC)",
                             "hours": {i: [["09:00", "17:00"]] for i in range(5)}},
        "CAL-BUSINESS-SG": {"tz": "Asia/Singapore", "display_name": "Business Hours (Asia/Singapore)",
                            "hours": {i: [["09:00", "17:00"]] for i in range(5)}},
    }
    rows = []
    for cal_id, spec_entry in spec.items():
        rows.append({
            "calendar_id": cal_id, "display_name": spec_entry["display_name"],
            "time_zone": spec_entry["tz"],
            "weekly_hours": _week_hours(spec_entry["hours"]),
            "created_at": _anchor(anchor_day, 9, 0), "updated_at": _anchor(anchor_day, 9, 0),
        })
        catalog.calendar_ids.append(cal_id)
        catalog.calendars[cal_id] = _week_hours(spec_entry["hours"])
    holidays = [
        {"calendar_id": "CAL-BUSINESS-UTC", "holiday_date": "2026-10-01",
         "description": "Regional service holiday (synthetic)"},
        {"calendar_id": "CAL-BUSINESS-SG", "holiday_date": "2026-10-15",
         "description": "Regional service holiday (synthetic)"},
    ]
    return rows, holidays


def generate_customers(config: ScaleConfig, streams: StreamContext, ids: IdAllocator,
                       catalog: ReferenceCatalog) -> list[dict]:
    rng = streams.stream("customers")
    window_start = dt.date.fromisoformat(config.window_start)
    rows: list[dict] = []
    for _ in range(config.n_customers):
        cid = ids.next_customer_id()
        catalog.customer_ids.append(cid)
        catalog.customer_tiers[cid] = weighted_pick(rng, config.tier_mix)
        first = rng.choice(_FIRST_NAME_POOL)
        last = rng.choice(_LAST_NAME_POOL)
        signed_up_date = window_start - dt.timedelta(days=rng.randint(60, 500))
        rows.append({
            "customer_id": cid,
            "display_name": f"{first} {last}",
            "support_tier": catalog.customer_tiers[cid],
            "preferred_language": "en",
            "signed_up_at": _anchor(signed_up_date, 12, 0),
            "created_at": _anchor(signed_up_date, 12, 0),
            "updated_at": _anchor(_SYNC, 9, 0),
        })
    return rows


def generate_agents(config: ScaleConfig, streams: StreamContext, ids: IdAllocator,
                    catalog: ReferenceCatalog) -> list[dict]:
    """Fixed per-agent consumption: name(3) + ownership + shift + tz, then derived derived fields."""
    rng = streams.stream("agents")
    window_start = dt.date.fromisoformat(config.window_start)
    valid_from = window_start - dt.timedelta(days=30)
    rows: list[dict] = []
    for _ in range(config.n_agents):
        aid = ids.next_agent_id()
        first = rng.choice(_FIRST_NAME_POOL)
        last = rng.choice(_LAST_NAME_POOL)
        display = f"{first} {last} ({aid[-2:]})"
        catalog.agent_ids.append(aid)
        ownership_tier = weighted_pick(rng, config.ownership_tier_mix)
        catalog.agent_shifts[aid] = weighted_pick(rng, config.shift_mix)
        tz = rng.choice(["UTC", "UTC", "UTC", "Asia/Singapore"])
        product = rng.choice(_PRODUCT_POOL) if ownership_tier == "product_specialist" else None
        if product is not None:
            owned = [product]
        else:
            owned = []
        rows.append({
            "agent_id": aid,
            "display_name": display,
            "ownership_tier": ownership_tier,
            "owned_product_codes": owned,
            "shift_pattern": catalog.agent_shifts[aid],
            "timezone": tz,
            "is_active": True,
            "valid_from": valid_from,
            "valid_to": None,
            "created_at": _anchor(valid_from, 9, 0),
            "updated_at": _anchor(_SYNC, 9, 0),
        })
    return rows


def generate_skills(config: ScaleConfig, streams: StreamContext, ids: IdAllocator,
                    catalog: ReferenceCatalog) -> list[dict]:
    """Skill catalogue: domain skills (config knob) + one language skill per foreign tongue."""
    anchor_day = dt.date.fromisoformat(config.window_start)
    n_domain = min(config.n_skills, len(_SKILL_CATALOG))
    chosen = [code for code, _cat in _SKILL_CATALOG[:n_domain]]
    chosen += [code for code in _LANGUAGE_SKILL_MAP.values()]
    catalog.skill_codes = chosen
    catalog.language_skill_codes = [_LANGUAGE_SKILL_MAP[lang] for lang in _LANGUAGE_SKILL_MAP]
    skill_language_by_code = {code: lang for lang, code in _LANGUAGE_SKILL_MAP.items()}
    return [
        {"skill_code": code, "display_name": code.replace("SKILL-", "").replace("-", " ").title(),
         "category": _SKILL_CATEGORY_BY_CODE.get(code, "language"),
         "is_language_skill": code in skill_language_by_code,
         "linked_language_code": skill_language_by_code.get(code),
         "valid_from": anchor_day, "valid_to": None,
         "created_at": _anchor(anchor_day, 9, 0), "updated_at": _anchor(anchor_day, 9, 0)}
        for code in chosen
    ]


_SKILL_CATEGORY_BY_CODE = {code: cat for code, cat in _SKILL_CATALOG}


def generate_channels(config: ScaleConfig, streams: StreamContext, ids: IdAllocator,
                      catalog: ReferenceCatalog) -> list[dict]:
    spec = [
        ("WEB_PORTAL", "Web Portal", "CAL-24X7"),
        ("EMAIL", "Email", "CAL-BUSINESS-UTC"),
        ("API", "API", "CAL-24X7"),
        ("VOICE_INBOUND", "Voice Inbound", "CAL-BUSINESS-UTC"),
        ("MOBILE_APP", "Mobile App", "CAL-24X7"),
    ]
    anchor_day = dt.date.fromisoformat(config.window_start)
    rows = []
    for counter, (code, display, calendar_id) in enumerate(spec):
        channel_id = f"CHANNEL-{code}"
        catalog.channel_ids.append(channel_id)
        catalog.channel_calendar[channel_id] = calendar_id
        catalog.channel_is_24x7[channel_id] = catalog.calendar_is_24x7(calendar_id)
        modifier = round(0.8 + (counter % 3) * 0.15, 2)
        rows.append({
            "channel_code": channel_id, "display_name": display,
            "priority_weight_modifier": modifier,
            "default_calendar_id": calendar_id,
            "supports_attachments": True,
            "is_active": True,
            "valid_from": anchor_day, "valid_to": None,
            "created_at": _anchor(anchor_day, 9, 0), "updated_at": _anchor(anchor_day, 9, 0),
        })
    return rows


_QUEUE_CATALOG: tuple[tuple[str, str], ...] = (
    ("CUSTOMER-SUCCESS-DESK", "Customer Success Desk"),
    ("TECH-DESKTOP-SUPPORT", "Desktop Support"),
    ("TECH-NETWORK-OPS", "Network Operations"),
    ("SECURITY-RESPONSE-TEAM", "Security Response"),
    ("APAC-REGIONAL-DESK", "APAC Regional Desk"),
    ("ENTERPRISE-QUEUE", "Enterprise Queue"),
)


def generate_queues(config: ScaleConfig, streams: StreamContext, ids: IdAllocator,
                    catalog: ReferenceCatalog) -> list[dict]:
    """Queue rows in ``valid_from DESC`` order, escalation FKs only to earlier queues."""
    rng = streams.stream("queues")
    window_start_date = dt.date.fromisoformat(config.window_start)
    valid_from = window_start_date - dt.timedelta(days=30)
    chosen = list(_QUEUE_CATALOG[: config.n_queues])
    catalog.queue_ids = [f"QUEUE-{code}" for code, _disp in chosen]
    escalation: dict[str, str] = {}
    rows: list[dict] = []
    for queue_idx, (code, display) in enumerate(chosen):
        qid = f"QUEUE-{code}"
        catalog.queue_strategy[qid] = weighted_pick(
            rng, {"round_robin": 8, "least_concurrent": 10, "best_skill_match": 7}
        )
        catalog.queue_max_concurrent[qid] = rng.choice([2, 3, 4, 4, 5, 6, 8])
        budget = 1 + rng.randint(1, min(2, len(catalog.skill_codes) - 1))
        domain_only = [c for c in catalog.skill_codes if not c.startswith("SKILL-LANG-")]
        catalog.queue_required_skills[qid] = rng.sample(domain_only, budget)
        if queue_idx >= 2:
            escalation[qid] = catalog.queue_ids[0]
        rows.append({
            "queue_id": qid, "display_name": display,
            "routing_strategy": catalog.queue_strategy[qid],
            "max_concurrent_tickets": catalog.queue_max_concurrent[qid],
            "required_skill_codes": catalog.queue_required_skills[qid],
            "default_calendar_id": "CAL-24X7",
            "escalation_queue_id": escalation.get(qid),
            "is_active": True,
            "valid_from": valid_from,
            "valid_to": None,
            "created_at": _anchor(valid_from, 9, 0),
            "updated_at": _anchor(_SYNC, 9, 0),
        })
    return rows


def generate_intents(config: ScaleConfig, streams: StreamContext, ids: IdAllocator,
                     catalog: ReferenceCatalog) -> list[dict]:
    """One default queue per intent; OUTAGE/SECURITY get a ledger priority floor."""
    rng = streams.stream("intents")
    anchor_day = dt.date.fromisoformat(config.window_start)
    rows = []
    for slug, code in _INTENT_CATALOG:
        catalog.intent_codes.append(code)
        catalog.intent_default_queue[code] = rng.choice(catalog.queue_ids)
        catalog.intent_priority_floor[code] = "P1" if code.endswith(
            ("OUTAGE-REPORT", "ACCOUNT-SUSPENSION")
        ) else "P3"
        display = slug.replace("-", " ").title()
        rows.append({
            "intent_code": code, "display_name": display,
            "description": f"Synthetic routing intent for {display.lower()} requests.",
            "default_queue_id": catalog.intent_default_queue[code],
            "example_phrasings": [f"I need help with my {display.lower()}.",
                                  f"Please assist with a {display.lower()} issue."],
            "is_active": True,
            "valid_from": anchor_day, "valid_to": None,
            "created_at": _anchor(anchor_day, 9, 0), "updated_at": _anchor(anchor_day, 9, 0),
        })
    return rows


_ALWAYS_PRIORITY_RULES: tuple[tuple[str, dict, dict], ...] = (
    ("1", {"if": [{"tier": "enterprise"}]}, {"baseline_priority": "P2"}),
    ("2", {"if": [{"tier": "premium"}]}, {"baseline_priority": "P3"}),
    ("3", {"if": [{"tier": "standard"}]}, {"baseline_priority": "P4"}),
    ("4", {"if": [{"tier": "free"}]}, {"baseline_priority": "P4"}),
    ("5", {"if": [{"intent_priority_floor": "P1"}]}, {"priority_min": "P1"}),
    ("6", {"if": [{"intent_priority_floor": "P2"}]}, {"priority_min": "P2"}),
    ("7", {"if": [{"vip_contracted": True}]}, {"baseline_priority": "P1"}),
)


def generate_priority_rules(config: ScaleConfig, streams: StreamContext, ids: IdAllocator,
                            catalog: ReferenceCatalog) -> list[dict]:
    """10 static (D-Q3/S-Q2-clean) rules, including a VIP + intent-floor safety logic.

    Engine-side fields (rule_order, baseline etc.) become Stage-4 priority engine's
    input; here we only emit the catalogue deterministically.
    """
    anchor_day = dt.date.fromisoformat(config.window_start)
    anchor = _anchor(anchor_day, 9, 0)
    rows = []
    for n, (order, conditions, outcomes) in enumerate(_ALWAYS_PRIORITY_RULES, start=1):
        rule_id = f"PRL-{int(order):03d}"
        if "baseline_priority" in outcomes:
            priority_outcome = outcomes["baseline_priority"]
            first_cond = conditions["if"][0]
            rule_name = f"{first_cond.get('tier', first_cond)} baseline -> {priority_outcome}"
        elif "priority_min" in outcomes:
            priority_outcome = outcomes["priority_min"]
            rule_name = f"Intent floor -> min priority {priority_outcome}"
        else:
            priority_outcome = outcomes.get("baseline_priority", "P4")
            rule_name = f"VIP contracted -> {priority_outcome}"
        rows.append({
            "rule_id": rule_id, "rule_order": int(order), "rule_name": rule_name,
            "conditions": conditions, "priority_outcome": priority_outcome,
            "is_terminal": True,
            "valid_from": anchor, "valid_to": None,
            "created_by": "system:reference_gen",
            "is_active": True,
            "created_at": anchor, "updated_at": anchor,
        })
    return rows


def generate_escalation_rules(config: ScaleConfig, streams: StreamContext, ids: IdAllocator,
                              catalog: ReferenceCatalog) -> list[dict]:
    """escalation rules select from the queues emitted earlier (no FK cycles)."""
    anchor_day = dt.date.fromisoformat(config.window_start)
    anchor = _anchor(anchor_day, 9, 0)
    if len(catalog.queue_ids) < 3:
        raise ValueError("escalation rules assume at least 3 queues")
    routes = catalog.queue_ids[:3]
    rules = [
        {
            "escalation_rule_id": f"ESC-RULE-{n:03d}",
            "rule_order": n,
            "trigger": {"kind": kind},
            "action": {"reassign_to_queue": routes[n % len(routes)],
                       "notify": ["supervisor"]},
            "valid_from": anchor, "valid_to": None,
            "is_active": True,
            "created_at": anchor,
            "updated_at": anchor,
        }
        for n, kind in enumerate(
            ["response_sla_at_risk", "resolution_sla_at_risk", "no_agent_pickup"],
            start=1,
        )
    ]
    return rules


def generate_bridges(config: ScaleConfig, streams: StreamContext, ids: IdAllocator,
                     catalog: ReferenceCatalog) -> tuple[list[dict], list[dict], list[dict]]:
    """AgentSkill, AgentLanguage, QueueMembership."""
    rng = streams.stream("bridges")
    anchor = _anchor(dt.date.fromisoformat(config.window_start), 9, 0)
    agent_skills: list[dict] = []
    agent_languages: list[dict] = []
    memberships: list[dict] = []
    domain_only = [c for c in catalog.skill_codes if not c.startswith("SKILL-LANG-")]
    foreign_langs = [c for c in catalog.language_codes if c != "en"]
    for aid in catalog.agent_ids:
        secondary_skill = rng.choice(domain_only)
        if rng.random() < 0.35:
            third_skill = rng.choice(domain_only)
            catalog.agent_shall_capable[aid] = sorted({secondary_skill, third_skill})
            agent_skills.append({"agent_id": aid, "skill_code": third_skill,
                                 "proficiency": rng.randint(3, 5),
                                 "certified_at": None, "cert_expires_at": None})
        else:
            catalog.agent_shall_capable[aid] = [secondary_skill]
        agent_skills.append({"agent_id": aid, "skill_code": secondary_skill,
                             "proficiency": rng.randint(3, 5),
                             "certified_at": None, "cert_expires_at": None})
        agent_languages.append({"agent_id": aid, "language_code": "en",
                                "proficiency": min(5, rng.randint(4, 5))})
        if rng.random() < 0.5:
            foreign = rng.choice(foreign_langs)
            proficiency = rng.randint(3, 5)
            agent_languages.append({"agent_id": aid, "language_code": foreign,
                                    "proficiency": proficiency})
            if proficiency >= 3:
                catalog.agent_lang_capable.setdefault(aid, []).append(foreign)
        primary_queue = rng.choice(catalog.queue_ids)
        catalog.agent_primary_queue[aid] = primary_queue
        catalog.agent_queues.setdefault(aid, set()).add(primary_queue)
        memberships.append({"agent_id": aid, "queue_id": primary_queue, "is_primary": True,
                            "created_at": anchor, "updated_at": anchor})
        secondary_queue = rng.choice(catalog.queue_ids)
        if secondary_queue != primary_queue:
            memberships.append({"agent_id": aid, "queue_id": secondary_queue, "is_primary": False,
                                "created_at": anchor, "updated_at": anchor})
            catalog.agent_queues.setdefault(aid, set()).add(secondary_queue)
    valid_from = dt.date.fromisoformat(config.window_start) - dt.timedelta(days=30)
    for row in agent_skills:
        row["valid_from"] = valid_from
        row["valid_to"] = None
        row["created_at"] = anchor
        row["updated_at"] = anchor
    for row in agent_languages:
        row["valid_from"] = valid_from
        row["valid_to"] = None
        row["created_at"] = anchor
        row["updated_at"] = anchor
    for row in memberships:
        row["valid_from"] = valid_from
        row["valid_to"] = None
    return agent_skills, agent_languages, memberships


def generate_reference_catalog(config: ScaleConfig, streams: StreamContext, ids: IdAllocator) -> tuple[
    dict[str, list[dict]], ReferenceCatalog
]:
    """Every reference/bridge row, in canonical parent-first emission order."""
    catalog = ReferenceCatalog()
    generated: dict[str, list[dict]] = {}
    generated["language"] = generate_languages(config, streams, ids, catalog)
    calendars, holidays = generate_calendars(config, streams, ids, catalog)
    generated["calendar"] = calendars
    generated["calendar_holiday"] = holidays
    generated["customer"] = generate_customers(config, streams, ids, catalog)
    generated["agent"] = generate_agents(config, streams, ids, catalog)
    generated["skill"] = generate_skills(config, streams, ids, catalog)
    generated["channel"] = generate_channels(config, streams, ids, catalog)
    generated["queue"] = generate_queues(config, streams, ids, catalog)
    generated["intent"] = generate_intents(config, streams, ids, catalog)
    generated["priority_rule"] = generate_priority_rules(config, streams, ids, catalog)
    generated["escalation_rule"] = generate_escalation_rules(config, streams, ids, catalog)
    agent_skills, agent_languages, memberships = generate_bridges(config, streams, ids, catalog)
    generated["agent_skill"] = agent_skills
    generated["agent_language"] = agent_languages
    generated["queue_membership"] = memberships
    return generated, catalog
