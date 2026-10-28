# YottaFlex.ai — Support Ticket Routing & SLA Intelligence Platform
## DATA_DICTIONARY.md — v0.1 (Planning / Schema-Design Stage)

> Status: **Draft for review.** No code, no seed dataset generated yet.
> Everything in this document is a *proposal*; items flagged ⚠️ **OPEN** require an explicit
> business-rule decision before implementation (see §12).
>
> Author: Forward Deployed Engineer candidate
> Challenge: AI-powered Support Ticket Routing and SLA Intelligence

---

## 1. Scope & Conventions

### 1.1 Scope
This dictionary defines the 13 required core entities

| # | Entity |
|---|--------|
| 1 | Customer |
| 2 | Channel |
| 3 | Ticket |
| 4 | Message |
| 5 | Intent |
| 6 | Language |
| 7 | PriorityRule |
| 8 | Agent |
| 9 | Skill |
| 10 | Queue |
| 11 | AssignmentEvent |
| 12 | SLAEvent |
| 13 | Resolution |

plus the **supporting entities and bridge tables** they need to function correctly
(Calendar, EscalationRule, AgentSkill, AgentLanguage, QueueMembership, SystemRuleNoOp,
MessageIntent, GroundTruthLabel) and the governance rules (ID conventions, lifecycle
states, routing constraints, anomaly labelling, reproducibility).

### 1.2 Conventions
- **Database:** PostgreSQL 15+, PostgreSQL-native type names shown.
- **Naming:** physical column names `snake_case`; check-constraint enums are `TEXT`
  columns constrained (NOT PostgreSQL ENUM) so that adding values is online and
  Alembic-migration-friendly.
- **Timestamps:** always `TIMESTAMPTZ`, always UTC.
- **Money:** `NUMERIC(12,2)` in **USD**.
- **Percentages / probabilities:** `NUMERIC(5,4)` in the range [0, 1] (unit: fraction).
- **Durations:** integer **milliseconds** unless a column named `*_seconds` /
  `*_minutes` says otherwise.
- **Booleans** expressed with `NOT NULL` unless trivially defaultable.
- **Client-supplied timestamps** are normalized to UTC at ingest; naive inputs are
  rejected at the API layer.
- **Surrogate vs business keys:** every entity has a **deterministic business primary
  key** (`TEXT`) that follows the ID convention (§2). We use it directly as the PK —
  no separate BIGSERIAL surrogate — because the challenge key requirement is
  reproduce-by-ID (deterministic regeneration, stable eval joins). If Postgres
  clustering becomes a concern at scale, we will promote the business key to a unique
  column and add `BIGINT` identity PKs; this is isolated to the Base class.

### 1.3 Reading a field table
Every entity section lists: purpose, primary key, fields (name / type / required /
allowed values & validation / uniqueness / notes-units), relationships with
cardinality, and lifecycle or effectiveness notes.

`Req` column: `Y` = required (`NOT NULL`), `N` = optional/nullable, `C` = conditionally
required (condition stated in the validation column).

---

## 2. Deterministic ID Conventions (challenge-required)

All IDs are uppercase, hyphen-separated, and **monotonic with respect to generation
order** — counters, never hashes, never RNG output — so regeneration from the same
seed replay yields byte-identical IDs.

| Entity | Pattern | Example | Notes |
|---|---|---|---|
| Ticket | `TKT-<YYYY>-<NNNNNN>` | `TKT-2026-000001` | Year of creation; per-year zero-padded 6-digit counter starting at 000001 per generated dataset. |
| Message | `MSG-<TICKET_ID>-<NNN>` | `MSG-TKT-2026-000001-001` | `<TICKET_ID>` is the **full** ticket ID string (includes the `TKT-` prefix). 3-digit zero-padded per-ticket message sequence starting at 001. Regexp: `^MSG-TKT-\d{4}-\d{6}-\d{3}$`. |
| Agent | `AGT-<NNNNNN>` | `AGT-000001` | Global 6-digit agent counter across the whole dataset (not per year/team). |
| AssignmentEvent | `ASN-<TICKET_ID>-<NNN>` | `ASN-TKT-2026-000001-001` | Per-ticket assignment sequence starting at 001; the first row for a ticket is always seq 001 (queue intake). |
| SLAEvent | `SLA-<TICKET_ID>` | `SLA-TKT-2026-000001` | **Exactly one** per ticket (1:1) covering both clocks (see §14). |

**Counter semantics (reproducibility rule):** counters are allocated by the dataset
generator in a single, defined emission order (ticket creation order = generation
order ⇒ `TKT-2026-000001`, then its messages in reply order, then the next ticket).
No two rows in the whole dataset may share a business PK. Counters are **seeded
independently of the RNG streams** (see §11) — they are a *deterministic function of
record order*, never of chance.

**Entities not named by the challenge** get the same style so the dataset stays
uniform:

| Entity | Pattern | Example |
|---|---|---|
| Customer | `CST-<NNNNNN>` | `CST-000001` |
| Resolution | `RES-<TICKET_ID>` | `RES-TKT-2026-000001` (1:1 with ticket) |
| PriorityRule | `PRL-<NNN>` | `PRL-001` |
| Calendar | `CAL-<NNN>` | `CAL-001` |
| EscalationRule | `ESC-<NNN>` | `ESC-001` |
| Intent | text code | `INTENT-TECHNICAL-OUTAGE` (§6.4) |
| Skill | text code | `SKILL-K8S-OPERATIONS` |
| Queue | text code | `QUEUE-TIER1-EMAIL` |
| Channel | text code | `CHANNEL-EMAIL` |
| Language | ISO 639-1 | `en` |

---

## 3. Entity 1 — Customer

**Purpose:** the human or organization raising tickets. Drives tier-based priority
and SLA policy selection.

**PK:** `customer_id TEXT` — `^CST-\d{6}$` (§2).

| Field | Type | Req | Allowed values / validation | Unique | Notes |
|---|---|---|---|---|---|
| `customer_id` | TEXT | Y | regexp `^CST-\d{6}$` | **PK** | §2 |
| `display_name` | TEXT(120) | Y | non-empty after strip | N | |
| `email` | TEXT(254) | Y | valid RFC-5322 address (Pydantic `EmailStr`), lower-cased at ingest | **Y** | uniqueness is the dedupe key for anomaly A-DUP-ALIAS |
| `company_name` | TEXT(160) | N | | N | |
| `tier` | TEXT | Y | `free` \| `standard` \| `premium` \| `enterprise` (CHECK) | N | drives base SLA policy selection; default `standard` |
| `preferred_language_code` | TEXT | Y | FK → `Language.language_code` | N | default `en` |
| `time_zone` | TEXT | Y | IANA zone (e.g. `Asia/Kolkata`); validated against `zoneinfo` at write | N | NOT a UTC offset string |
| `account_created_at` | TIMESTAMPTZ | Y | ≤ ticket timestamps for that customer (asserted by generator) | N | |
| `status` | TEXT | Y | `active` \| `churned` \| `blocked` (CHECK) | N | blocked customers cannot open tickets |
| `created_at`, `updated_at` | TIMESTAMPTZ | Y | | N | audit columns, all entities have them (omitted below) |

**Relationships**
- `1 Customer — N Ticket` (a customer raises many tickets).
- `N Customer — 1 Language` via `preferred_language_code`.

---

## 4. Entity 2 — Channel

**Purpose:** intake medium of the ticket (email, chat, …). Determines default
business-hours **calendar** for SLA clocks and a priority weight.

**PK:** `channel_code TEXT` — text code, e.g. `CHANNEL-EMAIL`.

| Field | Type | Req | Allowed values / validation | Unique | Notes |
|---|---|---|---|---|---|
| `channel_code` | TEXT | Y | `^CHANNEL-[A-Z0-9_]{2,30}$` | **PK** | codes: `CHANNEL-EMAIL`, `CHANNEL-CHAT`, `CHANNEL-VOICE`, `CHANNEL-PORTAL`, `CHANNEL-API` ⚠️ set is OPEN (which five channels does the challenge define?) |
| `display_name` | TEXT(60) | Y | | N | |
| `default_calendar_id` | TEXT | Y | FK → `Calendar.calendar_id` | N | chat = 24/7 calendar; email/voice = business-hours calendar |
| `priority_weight_modifier` | NUMERIC(3,2) | Y | ∈ `[0.5, 1.5]` (CHECK) | N | unit: multiplier; final priority = rule outcome composed with modifiers (§9) |
| `supports_attachments` | BOOLEAN | Y | | N | |
| `is_active` | BOOLEAN | Y | default `true` | N | |
| `valid_from` | DATE | Y | | N | effective-date window (§10) |
| `valid_to` | DATE | N | ≥ `valid_from` (CHECK); NULL = open-ended | N | overlapping active rows per code rejected |

**Relationships**
- `1 Channel — N Ticket` (the ticket's origin).
- `1 Channel — 1 Calendar` (default).

---

## 5. Entity 3 — Ticket

**Purpose:** the central workflow object; carries state, priority, queue/agent
placement, and the two SLA clock anchors.

**PK:** `ticket_id TEXT` — `^TKT-\d{4}-\d{6}$` (§2).

| Field | Type | Req | Allowed values / validation | Unique | Notes |
|---|---|---|---|---|---|
| `ticket_id` | TEXT | Y | regexp (§2) | **PK** | |
| `customer_id` | TEXT | Y | FK → `Customer` | N (composite indexed) | |
| `channel_code` | TEXT | Y | FK → `Channel` | N | |
| `subject` | TEXT(500) | Y | 1..500 chars after strip | N | |
| `description` | TEXT(8000) | Y | 1..8000 chars | N | the customer-authored body (Message row seq 001 mirrors this) |
| `status` | TEXT | Y | see lifecycle §8.1: `new` \| `queued` \| `assigned` \| `in_progress` \| `pending_customer` \| `escalated` \| `resolved` \| `closed` \| `reopened` (CHECK) | N | checked transitions only (§8.2) |
| `priority` | TEXT | Y | `P1` \| `P2` \| `P3` \| `P4` (CHECK); P1 = most urgent | N | set by PriorityRule pipeline at intake; human override allowed & logged (⚠️ OPEN how override interacts with rules — §12-Q6) |
| `queue_id` | TEXT | N | FK → `Queue` | N | NULL while `new` |
| `assigned_agent_id` | TEXT | N | FK → `Agent` | N (partial index where NOT NULL) | NULL unless `assigned`/`in_progress`/… |
| `primary_intent_code` | TEXT | N | FK → `Intent` | N | derived from first customer message's primary classified intent (⚠️ OPEN confirmed-at-intake vs re-classifiable per message, §12-Q9) |
| `language_code` | TEXT | Y | FK → `Language` | N | taken from Message seq 001 detection |
| `created_at` | TIMESTAMPTZ | Y | | **Y (unique within customer+channel+minute in generator, see A-DUP)** | |
| `first_response_at` | TIMESTAMPTZ | N | ≥ `created_at` (CHECK) | N | earliest agent/automated-out-of-office?? ⚠️ OPEN whether auto-replies start the clock (§12-Q4) |
| `resolved_at` | TIMESTAMPTZ | N | ≥ `first_response_at` if present (CHECK) | N | set when status → `resolved` |
| `closed_at` | TIMESTAMPTZ | N | ≥ `resolved_at` (CHECK) | N | |
| `reopened_count` | SMALLINT | Y | ≥ 0, default 0 | N | |
| `title_normalization_hash` | — | NO | | | *not stored*; duplicate detection happens in the generator/evaluator from `subject`+`description`, matching how it will be detected live |

**Relationships**
- `1 Ticket — N Message` (ordered by `sequence_number`).
- `1 Ticket — N AssignmentEvent`, `1 Ticket — 1 SLAEvent`, `1 Ticket — 1 Resolution` (Resolution row created at first `resolved`).
- `N Ticket — N Skill` *indirectly required*: a ticket declares `required_skill_codes TEXT[]` (NOT NULL default, validated against existing skill codes via the DB trigger). We consciously avoid a comma-separated skill column — see §13.1.

---

## 6. Entities 4–6 — Message, Intent, Language

### 6.1 Message
**Purpose:** every inbound/outbound utterance on a ticket, in order. The intent
classifier and the SLA first-response clock both read from here.

**PK:** `message_id TEXT` — `^MSG-TKT-\d{4}-\d{6}-\d{3}$` (§2).

| Field | Type | Req | Allowed values / validation | Unique | Notes |
|---|---|---|---|---|---|
| `message_id` | TEXT | Y | regexp §2 | **PK** | |
| `ticket_id` | TEXT | Y | FK → `Ticket` | part of `UNIQUE (ticket_id, sequence_number)` | |
| `sequence_number` | SMALLINT | Y | 1..999, contiguous per ticket (CHECK `> 0`) | same composite | message ordering is by this column, **not** wall clock |
| `actor_type` | TEXT | Y | `customer` \| `agent` \| `ai_assistant` \| `system` (CHECK) | N | `system` = status-change notifications; ⚠️ OPEN do system messages count as responses (§12-Q4) |
| `agent_id` | TEXT | N | FK → `Agent`; required iff `actor_type='agent'` and `ticket_id`'s assigned agent is NULL | N | consistency trigger |
| `body` | TEXT(10000) | Y | 1..10000 chars | N | |
| `language_code` | TEXT | Y | FK → `Language` | N | detected language |
| `language_confidence` | NUMERIC(5,4) | Y | ∈ `[0,1]` | N | unit: probability |
| `intent_code` | TEXT | N | FK → `Intent` | N | per-message classification (⚠️ OPEN ticket-level stored too? §12-Q9) |
| `intent_confidence` | NUMERIC(5,4) | N | ∈ `[0,1]` | N | required iff `intent_code` NOT NULL |
| `sentiment` | NUMERIC(4,3) | N | ∈ `[-1, 1]` | N | unit: normalized score; used by escalation rules |
| `created_at` | TIMESTAMPTZ | Y | monotonically ≥ previous message on same ticket (CHECK via trigger) | N | |

### 6.2 Intent
**Purpose:** classification catalog (deterministic, closed set).

**PK:** `intent_code TEXT`.

| Field | Type | Req | Allowed values / validation | Unique | Notes |
|---|---|---|---|---|---|
| `intent_code` | TEXT | Y | `^INTENT-[A-Z0-9-]{3,40}$` | **PK** | |
| `display_name` | TEXT(80) | Y | | **Y** | |
| `description` | TEXT(500) | Y | | N | |
| `default_queue_id` | TEXT | N | FK → `Queue` | N | where first-match routing would default |
| `example_phrasings` | TEXT[] | Y | ≥ 3 seed examples | N | used by the generator + classifier few-shot prompts |
| `is_active` | BOOLEAN | Y | default `true` | N | |
| `valid_from`, `valid_to` | DATE | Y/N | §10 | N | |

**Seed catalog (⚠️ OPEN — confirm this is the challenge's intent set, §12-Q9):**
`INTENT-BILLING-DISPUTE`, `INTENT-BILLING-REFUND`, `INTENT-TECHNICAL-OUTAGE`,
`INTENT-TECHNICAL-HOWTO`, `INTENT-ACCOUNT-ACCESS`, `INTENT-ACCOUNT-SECURITY`,
`INTENT-FEATURE-REQUEST`, `INTENT-DATA-PRIVACY`, `INTENT-SLA-COMPLAINT`,
`INTENT-ONBOARDING`, `INTENT-UPGRADE-DOWNGRADE`, `INTENT-CANCELLATION`, `INTENT-OTHER`.

**Relationships**
- `N Message — 1 Intent` (per-message, optional).
- `1 Intent — N Ticket` via `Ticket.primary_intent_code`.

### 6.3 Language
**Purpose:** closed set of supported locales for detection and routing.

**PK:** `language_code TEXT` — ISO 639-1 lowercase, e.g. `en`, `hi`, `es`, `de`, `fr`, `ja`. ⚠️ OPEN — final supported list is a business decision (§12-Q3).

| Field | Type | Req | Allowed values / validation | Unique | Notes |
|---|---|---|---|---|---|
| `language_code` | TEXT | Y | ISO 639-1 2-letter lowercase (CHECK) | **PK** | |
| `display_name` | TEXT(60) | Y | | **Y** | |
| `is_rtl` | BOOLEAN | Y | | N | |
| `detection_enabled` | BOOLEAN | Y | default `true` | N | |

**Relationships:** `N Language — N Agent` via bridge `AgentLanguage` (§13.2);
`1 Language — N Message`.

---

## 7. Entity 7 — PriorityRule (effective-dated rule engine)

**Purpose:** deterministic, versioned, *first-match-wins* mapping from ticket
attributes to a priority `P1..P4`. This is the *rules* half of the routing engine;
the ML intent model supplies `primary_intent_code` upstream of these rules.

**PK:** `rule_id TEXT` — `^PRL-\d{3}$` (§2-styled).

| Field | Type | Req | Allowed values / validation | Unique | Notes |
|---|---|---|---|---|---|
| `rule_id` | TEXT | Y | regexp | **PK** | |
| `rule_order` | SMALLINT | Y | 1..500 (CHECK); ordering of evaluation, **ascending = first** | **Y** | two active rules may not share a number (partial UNIQUE where is_active) |
| `rule_name` | TEXT(120) | Y | | **Y** | |
| `conditions` | JSONB | Y | validated JSON: any subset of `customer_tier[]`, `channel[]`, `intent[]`, `language[]`, `sentiment_lte/ gte`, `keywords_any[]`, `min_reopen_count`; at least one key must be present | N | evaluated with AND between keys, OR inside arrays |
| `priority_outcome` | TEXT | Y | `P1..P4` (CHECK) | N | also `+escalate_one` operator ⚠️ OPEN (§12-Q6) |
| `is_terminal` | BOOLEAN | Y | default `true` | N | first match wins; set false only for rules used in dry-run "what-if" |
| `valid_from` | TSTZ | Y | | N | **effective dates** — the rule applies iff valid window ∋ evaluation time |
| `valid_to` | TSTZ | N | > valid_from; NULL = open-ended | N | overlapping rules with same `rule_order` while both active → rejected by uniqueness |
| `created_by` | TEXT | Y | `generator` \| `admin:<name>` | N | provenance |
| `is_active` | BOOLEAN | Y | default `true` | N | |

**Deterministic evaluation contract:** `P(final)` is *derived*, `P(rule) ∘ f(channel.
priority_weight_modifier, tier)`, computed in one pure function `services/priority.py`
with a fixed tie-break order: `rule_order asc`, then `rule_id asc`. A fallback rule
`PRL-999` (matches everything → `P3`) always exists last. The **same pure function**
is used by dataset generation, routing, and evaluation — never three implementations.

---

## 8. Entities 8–10 — Agent, Skill, Queue

### 8.1 Agent
**PK:** `agent_id TEXT` — `^AGT-\d{6}$` (§2).

| Field | Type | Req | Allowed values / validation | Unique | Notes |
|---|---|---|---|---|---|
| `agent_id` | TEXT | Y | regexp | **PK** | |
| `full_name` | TEXT(120) | Y | | N | |
| `email` | TEXT(254) | Y | lowercase RFC-5322 | **Y** | |
| `team` | TEXT(80) | Y | `tier1-support` \| `tier2-technical` \| `billing` \| `fraud` \| `onboarding` (CHECK) ⚠️ OPEN | N | |
| `time_zone` | TEXT | Y | IANA | N | used to know when *this agent* may be non-productive (a scheduling concept, NOT the SLA clock) |
| `status` | TEXT | Y | `active` \| `inactive` \| `on_leave` (CHECK) | N | `inactive`/`on_leave` agents get no new assignments |
| `max_concurrent_tickets` | SMALLINT | Y | ∈ [1, 10] (CHECK), default 3 | N | **agent concurrency cap** (§14.2) |
| `hired_at` | DATE | Y | | N | |
| `valid_from`, `valid_to` | DATE | Y/N | §10 | N | roster snapshot semantics for reproducibility |

### 8.2 Skill (and bridge AgentSkill)
**PK (Skill):** `skill_code TEXT`, e.g. `SKILL-K8S-OPERATIONS`, `SKILL-BILLING-REFUNDS`, `SKILL-FRAUD-TRIAGE`, `SKILL-VIP-HANDLING`. Validation: `^SKILL-[A-Z0-9-]{3,40}$`.

| Field | Type | Req | Allowed values / validation | Unique | Notes |
|---|---|---|---|---|---|
| `skill_code` | TEXT | Y | regexp | **PK** | |
| `display_name` | TEXT(80) | Y | | **Y** | |
| `category` | TEXT | Y | `technical` \| `billing` \| `process` \| `product` (CHECK) | N | |
| `is_language_skill` | BOOLEAN | Y | default `false` | N | if `true`, `linked_language_code` must be set and this skill is *in addition to* `AgentLanguage` (belt-and-braces; the routing read path uses AgentLanguage) |
| `linked_language_code` | TEXT | N | FK → `Language` | N | |
| `valid_from`, `valid_to` | DATE | Y/N | | N | |

### 8.3 Queue
**PK:** `queue_id TEXT` — `^QUEUE-[A-Z0-9-]{3,40}$`, e.g. `QUEUE-TIER1-EMAIL`.

| Field | Type | Req | Allowed values / validation | Unique | Notes |
|---|---|---|---|---|---|
| `queue_id` | TEXT | Y | regexp | **PK** | |
| `display_name` | TEXT(80) | Y | | **Y** | |
| `routing_strategy` | TEXT | Y | `round_robin` \| `least_concurrent` \| `best_skill_match` (CHECK); ties broken by `agent_id` **lexicographic asc** (determinism) | N | |
| `max_concurrent_tickets` | SMALLINT | Y | ∈ [1, 10], default 3 | N | **queue-level concurrency cap** (§14.2) |
| `required_skill_codes` | TEXT[] | Y | each in FK-subselect of `Skill` | N | a ticket may only be *assigned out of* this queue if its agent holds all required skills |
| `default_calendar_id` | TEXT | Y | FK → `Calendar` | N | channel-aware routing is per-channel, but the queue can override |
| `escalation_queue_id` | TEXT | N | FK → `Queue` (no self, no cycle: recursive CHECK row) | N | |
| `is_active` | BOOLEAN | Y | | N | |
| `valid_from`, `valid_to` | DATE | Y/N | | N | |

---

## 9. Entity 11 — AssignmentEvent

**Purpose:** immutable, append-only ledger of *every* queue-assignment and
agent-assignment action on a ticket. Rebuilding "who was holding ticket X when" is a
query, not a mutable column.

**PK:** `assignment_id TEXT` — `^ASN-TKT-\d{4}-\d{6}-\d{3}$` (§2).

| Field | Type | Req | Allowed values / validation | Unique | Notes |
|---|---|---|---|---|---|
| `assignment_id` | TEXT | Y | regexp §2 | **PK** | sequence contiguous per ticket |
| `ticket_id` | TEXT | Y | FK → `Ticket` | composite `UNIQUE (ticket_id, event_seq)` | |
| `event_seq` | SMALLINT | Y | ≥ 1 contiguous |  same  | |
| `occurred_at` | TIMESTAMPTZ | Y | ≥ ticket.created_at; monotonic with prev event on ticket | N | |
| `phase` | TEXT | Y | `queue_intake` \| `agent_assigned` \| `agent_reassigned` \| `queue_reassigned` \| `returned_to_queue` (CHECK) | N | |
| `from_queue_id` | TEXT | N | FK → `Queue` | N | NULL for the very first intake |
| `from_agent_id` | TEXT | N | FK → `Agent` | N | NULL except reassignment/return |
| `to_queue_id` | TEXT | N | FK → `Queue` | N | required for intake/reassign/return |
| `to_agent_id` | TEXT | N | FK → `Agent` | N | required for agent_assigned/reassigned; must be a member of `to_queue_id` then |
| `decided_by` | TEXT | Y | `system_rule` \| `system_routing_model` \| `supervisor_manual` \| `agent_self_take` (CHECK) | N | provenance — used as a feature/eval axis, never a *label* |
| `reason` | TEXT | Y | free text slug ≤ 60 chars (`priority_match`, `best_skill_match`, `escalation…`) | N | |
| `routing_features` | JSONB | Y | only **input** features (priority, intent, language, queue load, skill match booleans, calendar open) | N | 🚫 NO ground-truth labels ever enter this column (§11.3) |
| `latency_ms` | INTEGER | Y | ≥ 0 (CHECK) | N | unit: ms, engine decision time |

**Cardinality:** `1 Ticket → N AssignmentEvent` (≥ 1: event_seq = 1 is the intake).

---

## 10. Entity 12 — SLAEvent (per-ticket, 1:1)

**Purpose:** owns the two SLA clocks (`first_response`, `resolution`) with all
pause/resume segments against the **channel-aware calendar**. Breach flags are
*derived here from clock arithmetic*, not set randomly.

**PK/UNIQUE:** `sla_event_id TEXT` — `^SLA-TKT-\d{4}-\d{6}$`, one per ticket.

| Field | Type | Req | Allowed values / validation | Unique | Notes |
|---|---|---|---|---|---|
| `sla_event_id` | TEXT | Y | regexp | **PK** | |
| `ticket_id` | TEXT | Y | FK → `Ticket` | **Y** | 1:1 by construction |
| `policy_id` | TEXT | Y | text (set of valid policies is ⚠️ OPEN §12-Q2); e.g. `SLA-P1-CRITICAL-24x7` | N | resolved once at intake, from tier × priority × channel |
| `clock_type` | TEXT | Y | `business` \| `calendar` (CHECK) | N | calendar-aware when the channel calendar has hours other than 24/7 |
| `sla_started_at` | TIMESTAMPTZ | Y | = ticket.created_at (CHECK) | N | |
| `elapsed_secs_first_response` | BIGINT | Y | ≥ 0 (CHECK) | N | **unit: seconds**, calendar time (§14.1) |
| `elapsed_secs_resolution` | BIGINT | N | ≥ 0 | N | NULL until resolved |
| `pause_events` | JSONB | Y | validated array of `{reason: enum, from: tstz, to: tstz}`; reasons: `pending_customer`, `wait_internal`, `manual_hold`; `to > from`, no overlaps | N | clock paused while ticket is `pending_customer` etc. (§14.1) |
| `breach_flags` | JSONB | N | `{first_response_breached: bool, resolution_breached: bool, breach_at: tstz}` | N | **derived**, consistent with `elapsed_*` by definition; recomputed, never random |
| `calendar_id_used` | TEXT | Y | FK → `Calendar` | N | the channel's calendar actually applied (snapshot) |
| `computed_at` | TIMESTAMPTZ | Y | | N | |

**Rule:** SLA target itself is *not a random value* — it is selected from the SLA
policy table by (priority, tier, channel, clock_type) lookup.

---

## 11. Entity 13 — Resolution

**Purpose:** terminal record per ticket: how it was resolved and by whom.

**PK/UNIQUE:** `resolution_id TEXT` — `^RES-TKT-\d{4}-\d{6}$`, one row per ticket
(excluding closed-merged duplicates ⚠️ OPEN, §12-Q7).

| Field | Type | Req | Allowed values / validation | Unique | Notes |
|---|---|---|---|---|---|
| `resolution_id` | TEXT | Y | regexp | **PK** | |
| `ticket_id` | TEXT | Y | FK → `Ticket` | **Y** | 1:1 |
| `resolved_by_agent_id` | TEXT | Y | FK → `Agent` | N | |
| `resolution_type` | TEXT | Y | `technical_fix` \| `billing_adjustment` \| `kb_answer` \| `customer_withdrawn` \| `duplicate_closed` \| `escalated_closed` (CHECK) | N | ⚠️ OPEN enum values |
| `root_cause_note` | TEXT(2000) | N | | N | |
| `first_contact_resolution` | BOOLEAN | Y | | N | derived: resolved without ≥2 agent messages |
| `csat_score` | SMALLINT | N | ∈ [1, 5] | N | unit: 1..5; sparsely present (~30% of tickets in generator — ⚠️ OPEN rate) |
| `resolved_at` | TIMESTAMPTZ | Y | = ticket.resolved_at (CHECK, trigger-aligned) | N | |
| `reopened_after_resolution` | BOOLEAN | Y | consistent with `ticket.reopened_count > 0` | N | |

---

## 12. Calendar & Escalation (supporting entities, required for correctness)

### 12.1 Calendar
`calendar_id TEXT` PK, `display_name`, `time_zone IANA`, `weekly_hours JSONB`
(validated: 7 keys `mon..sun`, each `null` or `[hh:mm, hh:mm]`), plus holidays via
child table `CalendarHoliday (calendar_id, holiday_date, description)` PK (calendar_id,
holiday_date). Seed content: `CAL-24x7`, `CAL-BUSINESS-BL-9x6` (Asia/Kolkata 9:00–18:00
IST, Sat-Sun off), `CAL-BUSINESS-US-24x5`. Channels reference these; the SLA clock
integrator (§14.1) uses them.

### 12.2 EscalationRule
`escalation_rule_id TEXT` PK, `rule_order SMALLINT`, `trigger JSONB` (validated keys:
`first_response_breach`, `resolution_breach`, `sentiment_lte`, `priority_in[]`),
`action JSONB` (`to_queue_id`, `priority_override ∈ {+1, keep}`, `notify_team`),
`valid_from`, `valid_to`, `is_active`. Executed by a single scheduler step; every
execution emits an `AssignmentEvent` with `phase` = `queue_reassigned` and
`reason` = `escalation:<rule_id>`.

---

## 13. Bridge Tables (explicit — no comma-separated storage anywhere)

| Bridge | Columns | Unique | Cardinality & purpose |
|---|---|---|---|
| **AgentSkill** | `agent_id FK`, `skill_code FK`, `proficiency SMALLINT 1..5 (unit: level)`, `certified_at DATE`, `cert_expires_at DATE NULL`, `valid_from`, `valid_to` | `(agent_id, skill_code, valid_from)` | N:N Agent↔Skill with competency metadata. Checked by assignment: agent must hold all of queue's `required_skill_codes`. |
| **AgentLanguage** | `agent_id FK`, `language_code FK`, `proficiency SMALLINT 1..5`, `valid_from`, `valid_to` | `(agent_id, language_code, valid_from)` | N:N Agent↔Language. Agents only take tickets whose message language they speak (≥3). |
| **QueueMembership** | `agent_id FK`, `queue_id FK`, `is_primary BOOLEAN`, `valid_from`, `valid_to`, UNIQUE `(agent_id, queue_id, valid_from)` | N:N Agent↔Queue. Assignment pool for a queue = currently-valid members. |
| **MessageIntent** | *(inlined in Message as intent_code/intent_confidence* — no separate bridge needed because it is N:1 per message with provenance kept in `decided_by`-style field `intent_source ∈ {ml, rules, human}` — we do NOT need a 4th bridge) | — | — |
| **TicketSkill** | `ticket_id FK`, `skill_code FK`, UNIQUE `(ticket_id, skill_code)` | N:N Ticket↔Skill: which skills the ticket requires. Populated from queue defaults at intake; never a `TEXT[]` blob of unknown codes. |

> **Doctrine:** *no* many-to-many relationship is stored as a delimited string.
> Wherever one appears, there is a bridge table with FKs both ways, a UNIQUE
> constraint, and effective dates. The one place `TEXT[]` remains in this design
> (`Queue.required_skill_codes`) is a 1-many *catalog reference*, not an N:M relation,
> and every element is FK-validated by trigger.

---

## 14. Operational Rules

### 14.1 Channel-aware SLA calendars
- Each channel has a default `Calendar`; the calendar's weekly window decides
  *which clock seconds count* (`business` mode) or whether the clock runs straight
  (`calendar` mode for `CAL-24x7`).
- Clock starts at intake (`sla_started_at`); pauses for `pending_customer` and
  manual holds; resumes on next activity. Pauses stack as a list, never as
  precomputed totals, so re-audit is possible.
- **Calendar mode formula (deterministic):**
  `elapsed = Σ window-overlap([from, to), week_windows) − Σ pause_similar`.
  Implemented once in `services/sla.py::elapsed_between(start, end, cal, pauses)`;
  dataset generation, live routing, evaluation share it.
- Holidays counted as closed all day.

### 14.2 Agent concurrency
- Cap = `min(Agent.max_concurrent_tickets, Queue.max_concurrent_tickets)`.
- "Currently working" is computed from open `AssignmentEvent` rows
  (`phase ∈ {agent_assigned, agent_reassigned}` with no later `returned_to_queue`
  for the same ticket), NOT from a mutable counter — avoids state drift.
- Assignment is a serialized transaction per queue (advisory lock on queue): select
  candidate pool → filter clock-open + skills + language → order by strategy →
  check cap → insert event → update ticket. Retry-safe.

### 14.3 Escalation rules
- Scheduler runs every 60s of sim-time over open tickets; the same rules are
  replayed inside the dataset generator over event logs. Escalation *always*
  appends an AssignmentEvent (auditable) instead of silently flipping priority.

### 14.4 Ticket lifecycle states & transitions (closed ledger)
| From → To | Allowed when |
|---|---|
| `new → queued` at intake, after PriorityRule applied | auto |
| `queued → assigned` assignment to agent with skill/lang + concurrency free | system or manual |
| `assigned → in_progress` Agent first views ticket | agent action |
| `in_progress → pending_customer` waiting on customer; SLA clock pauses | agent |
| `pending_customer → in_progress` customer replies | auto |
| `assigned/in_progress → escalated` per EscalationRule | system |
| `escalated → assigned` to target queue/agent | system/manual |
| `in_progress/escalated → resolved` closure set | agent |
| `resolved → closed` after CSAT window ⚠️ OPEN (§12-Q8) | auto |
| `resolved → reopened` customer replies after resolution; `reopened_count++` | auto |
| `closed → reopened` only within 30-day window ⚠️ OPEN | policy |
- Forbidden transitions rejected by INSERT/UPDATE trigger. Every transition writes
  a system `Message` row (audit trail) with `actor_type = 'system'`.

---

## 15. Anomaly Framework (5 types) — ⚠️ the exact challenge list is OPEN (§12-Q1)

We **propose** the following five as the most plausible set for the challenge; until
confirmed, the contract below is parameterised by `anomaly_code` so swapping labelling
logic does not disturb the schema.

| Code (proposal) | Family | Definition (deterministic predicate) |
|---|---|---|
| `A1-DUP-SESSION` | Duplicate | Two tickets by the same customer in a ≤ 15-minute window whose descriptions share a 5-gram; treated as one session |
| `A2-CLOCK-INCONSISTENCY` | Timestamp disorder | `first_response_at < created_at`, `resolved_at < first_response_at`, or message `sequence_number` ordering conflict |
| `A3-IMPOSSIBLE-RESPONSE` | Speed anomaly | Agent reply < 5 s of customer message (humanly impossible) |
| `A4-MISROUTED` | Routing anomaly | Ticket assigned to an agent lacking required skill/language, or queue/agent cap exceeded |
| `A5-SLA-MISDECLARED` | SLA label mismatch | Declared `breach_flags` ⊕ recomputed calendar-clock value disagree |

### 15.1 Labelling strategy — *post-hoc annotation, not mutation*
1. Base dataset is generated clean under the seed.
2. A separate **injection pass** walks records *by stable business ID* and writes
   rows to `GroundTruthLabel` (see below) describing the anomaly's exact location.
   No base-row column is altered except a *second* synthetic record appended to the
   data set when the anomaly is intrinsically structural (e.g. duplicating a ticket:
   we write a new, adjacent ticket row, never overwrite one).
3. Randomness for *where/what* anomalies to inject comes from `rng.stream("anomalies")`
   (§16). The *label* itself (e.g. "A4-MISROUTED because agent lacked
   SKILL-K8S-OPERATIONS") is **derived** from stored data stepped through the same
   deterministic functions as evaluation — we never invent an independent outcome
   for a derived value.
4. The evaluation harness reads `GroundTruthLabel` only through its own connection
   (`schema: gold`). The serving/ops connection is granted no SELECT on the
   `gold` schema; this is enforced by an automated test in CI.

| `GroundTruthLabel` field | Type | Notes |
|---|---|---|
| `label_id` BIGSERIAL PK | | surrogate fine here (not a business object) |
| `anomaly_code` TEXT NOT NULL | one of the 5 (⚠️ OPEN) | |
| `entity_type` TEXT ∈ {`ticket`, `message`, `assignment_event`, `sla_event`, `resolution`} | | target object *(primary anchor)* |
| `entity_id` TEXT NOT NULL | | the exact business-ID row(s) **additionally listed in `related_ids JSONB`** when a multi-row anomaly (e.g. duplicate pair) |
| `injected_synthetic` BOOLEAN | true when part of the generator's scenario; false when labelled by reviewer/rules post-hoc | |
| `severity` SMALLINT ∈ [1,5] | | |
| `explanation` TEXT | | human-readable, includes numeric evidence |
| `labelled_at` TIMESTAMPTZ | | |

**No silent corruption of unrelated records** is guaranteed because (a) injections
touch only rows listed in a label + optional new rows, (b) each label row names its
own payload, (c) there is exactly one label-regeneration path, (d) a nightly job
re-runs label derivation and diffs — catching any two-source drift.

---

## 16. Reproducibility Strategy (seed `20261022`)

**Principles**
1. **One seed, many streams.** seed = `20261022`; a named-`StreamContext` derives
   per-purpose streams via SHA-256(`${seed}:${stream_name}`):
   `customers`, `tickets`, `messages`, `skills`, `calendars`, `anomalies`,
   `slas`, … Two consumers never share a stream ⇒ adding a generator never shifts
   another one's output.
2. **Counters, not RNG, for IDs** (§2). No hash-ID, no surrogate-from-random.
3. **Derived values have no dice.** Anything *computed from* base data (priority
   from rules; SLA target from policy; breach flags from clock math; label text from
   the anomaly predicate) is a pure function of those inputs — never drawn from an
   RNG. This is enforced by a test that re-derives every derived column and diffs.
4. **Scales as config, not code.** `data/config/dataset_scale.yaml`:
   `{n_customers, n_agents, n_skills, n_queues, tickets_per_day, days, channel_mix,
   intent_mix, tier_mix, anomaly_rate:%, language_mix}` — all positive.
   Reproduce `seed=20261022, scale={...}` to byte-identical CSV/Parquet/SQL.
5. **Emission order is part of the contract.** Customers → Agents → Skills →
   Queues → Channels → Calendars → Rules → Tickets (chronological, each followed
   immediately by its Messages/AssignmentEvent/SLAEvent/Resolution), so ID
   sequencing is stable when the scale changes.
6. **Manifest.** Every produced dataset writes `manifest.json` (seed, scale, sha-256
   of each output, library versions). CI checks regeneration produces the same hashes.
7. ⚠️ OPEN — is there an expected output the challenge supplies to diff against?
   (§12-Q5)

---

## 17. OPEN QUESTIONS (explicit — do NOT proceed without answers)

| # | Question | Default assumption until answered |
|---|---|---|
| Q1 | **What are the exact five anomaly types the challenge defines?** Are they tolerance windows, types, or exact labels? | We shipped a *proposal* (§15) but treat it as placeholder. |
| Q2 | **SLA policy matrix** — acceptable values per priority × tier × channel? Does the challenge publish one? | None published; we defined `SLA-` family strings + calendar-aware assignment and await values. |
| Q3 | **Which languages / locales** are in scope? Are multilingual agents a routing dimension? | 6 languages proposed, `AgentLanguage` table created regardless. |
| Q4 | Do auto-replies / system messages **start the first-response SLA clock**, or only human responses? | Human only. |
| Q5 | Is there an **expected gold dataset** or evaluation metric contract we must match exactly? | Assume none; we design for self-consistency. |
| Q6 | Priority override by humans — allowed? Does it bypass rules or sit atop them? | Allowed with provenance, and rules re-run beneath it for review. |
| Q7 | Are duplicate tickets closed-merged, or kept and cross-referenced? | Kept, cross-referenced via `A1-DUP-SESSION` label. |
| Q8 | CSAT window / auto-close SLA after resolution? | 3 business days for reply, or auto close. |
| Q9 | Ticket-level `primary_intent_code` vs per-message reclassification — does the challenge require per-message columns? | We model per-message optional fields **and** a ticket-level column synced from the latest customer message before resolution. |
| Q10 | Voice channel — do we synthesise transcripts into Messages 1:1, or is voice out of ticket-flow? | In-flow, transcript becomes messages. |
