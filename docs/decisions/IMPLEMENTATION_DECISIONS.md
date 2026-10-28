# IMPLEMENTATION_DECISIONS.md — v1 (accepted working decisions)

**Project:** YottaFlex.ai — Support Ticket Routing & SLA Intelligence Platform (Associate AI FDE Coding Challenge)
**Purpose:** closes the 10 OPEN questions of `DATA_DICTIONARY.md` §17 (each labelled Qn below) and fixes implementation-level choices that the dictionary left ambiguous. Each decision states a **configurable default**; all defaults live as named constants in `apps/api/app/services/domain_config.py` (domain semantics) or `app/core/config.py` (infra), pinned by tests.

Supersedes the *proposal* wording in DATA_DICTIONARY §15/§17 "default assumption" cells. Where this doc and the dictionary disagree, this doc wins and the dictionary cell is marked "resolved — see IMPLEMENTATION_DECISIONS".

---

## D-Q1. Exact five anomaly types (Q1) — adopted verbatim with fixed codes

The challenge defines five anomaly scenarios; we adopt them **exactly**, mapped to
deterministic predicates over our schema and to the existing `GroundTruthLabel`
contract (label rows, no base-row mutation except the structural wipe itself):

| # | `anomaly_code` | Challenge scenario | Deterministic predicate (single source of truth `services/anomalies.py`) |
|---|---|---|---|
| 1 | `ANOM-CAPACITY-OVERLOAD` | Agent assigned beyond capacity | An `AssignmentEvent` row exists at a timestamp t such that the count of *open* concurrent assignments for `to_agent_id` at t exceeds `min(agent.max_concurrent_tickets, queue.max_concurrent_tickets)` of that agent/queue. Open-ness is computed per §14.2 (ledger-derived; no counters). |
| 2 | `ANOM-SLA-CALENDAR-IGNORED` | SLA ignores channel calendar | Recompute `elapsed_*_seconds` through `services/sla.py::elapsed_between` with the channel's `calendar_id_used`; if the recomputed value crosses the target but the stored `breach_flags` disagree (or vice versa) — i.e. `platform breach flags ≠ derived flags` under the correct calendar — the SLAEvent is anomalous. |
| 3 | `ANOM-REOPEN-HISTORY-LOSS` | Reopened ticket loses history | A ticket with `reopened_count ≥ 1` where the message/event ledger has a gap: `sequence_number` is not contiguous 1..N, or an `AssignmentEvent` `event_seq` is not contiguous, or a Message timestamp is not monotonic with the previous message on the ticket (§9/§6.1 invariants). |
| 4 | `ANOM-TRANSFER-LOOP` | Transfer loop | The ordered sequence of queues visited (`AssignmentEvent.phase ∈ {queue_intake, queue_reassigned, returned_to_queue}`) contains a cycle: any queue appears ≥ 3 times on one ticket, or a pattern A→B→A occurs twice consecutively. |
| 5 | `ANOM-PRIORITY-SAFETY-VIOLATION` | Priority contradicts a defined safety rule | At intake (and at every re-evaluation), the effective `PriorityRule` output for the ticket ≠ `ticket.priority` where the mismatch is an override record that lacks provenance, OR the ticket violates a hard safety floor (§ D-Q6: a rule with `priority_outcome ∈ {P1}` flagged `safety_critical = true` in `conditions.priority_safety_floor`) while stored priority is lower. |

Legacy proposal codes from §15 are retired: `A1-DUP-SESSION` (kept internally as a
*duplicate-detection util*, but not a graded anomaly), `A2-CLOCK-INCONSISTENCY` and
`A3-IMPOSSIBLE-RESPONSE` (folded into `ANOM-REOPEN-HISTORY-LOSS`'s ledger-gap
predicate and generator stress cases), `A4-MISROUTED` (superseded by
`ANOM-CAPACITY-OVERLOAD`), `A5-SLA-MISDECLARED` (superseded by
`ANOM-SLA-CALENDAR-IGNORED`). String names: uppercase, underscore-separated.
Injection counts/scales: fixed proactive label counts as module constants in
`apps/datagen/datagen/inject.py` (`N_SLA`, `N_HISTORY`, `N_LOOP`, `N_PRIORITY`,
with `MIN_OPEN_FOR_CAPACITY` governing the capacity family). No YAML config file.

## D-Q2. SLA policy matrix (Q2) — discoverable defaults, not a guessed "policy table"

No policy is published by the challenge, so we do **not** invent a magic `SLA-*` string table hoping it is "the one". Instead:

- `SLAEvent.policy_id` stays a free TEXT id as specced.
- The **target values** that policy ids resolve to live in one default factor
  `defaults.SLA_POLICY_MATRIX: {(clock_type, priority): (first_response_minutes, resolution_minutes)}`.

Default matrix (used by generator, live SLA engine, and evaluator via the same constant):

| clock_type    | P1            | P2             | P3              | P4              |
| ------------- | ------------- | -------------- | --------------- | --------------- |
| `calendar`    | 60 / 1440     | 240 / 2880     | 480 / 5760      | 1440 / 11520    |
| `business`    | 30 / 480      | 60 / 1440      | 240 / 2880      | 480 / 5760      |

`policy_id` is *composed deterministically*: `SLA-<clock_type>-<priority>` (e.g.
`SLA-business-P1`), chosen at intake = the pure function result; nothing random.
If the challenge later publishes its own policy table, we swap the matrix constant
**and change nothing else** (db column already free-form TEXT).

## D-Q3. Languages & locale scope (Q3)

Supported language set = definite **9-language list**, seeded into `Language`:
`en, hi, ta, es, fr, de, ja, pt, ko`. Multi-lingual agents **ARE a routing dimension**:
only an agent whose `AgentLanguage.proficiency ≥ 3` (at event time) can be assigned a
message in that language (per §13.2 `AgentLanguage`). Default channel mix for the
dataset: 85% English, the rest drawn from the set.

## D-Q4. System / AI messages and the first-response clock (Q4)

**Only `actor_type ∈ {agent, ai_assistant}` starts the `first_response` clock.**
`system` messages (status-change audit rows per §14.4) NEVER stop/start/pause the SLA
clock and do NOT count as a response; out-of-office auto-replies with
`actor_type='system'` do not count. Default is implemented in
`services/sla.py::from_message_ledger` (pure function over Message rows). If the
challenge-maker's rubric disagrees, flip **one** constant: `SYSTEM_MESSAGES_COUNT_AS_RESPONSE = False`.

## D-Q5. Gold dataset & evaluation contract (Q5)

There is **no** challenge-supplied gold dataset. We target byte-identical
**self-consistency**: regenerate the dataset twice and diff `manifest.json` sha-256
entries (§16). Evaluation is over our injected labels (+ small self-built hand-labelled
holdout), measures routing accuracy on held-out tickets vs the deterministic rule
engine baseline. The rubric is documented in `apps/eval/README.md`.

## D-Q6. Priority override by humans (Q6) — rules-aware, but safety-floored

Allowed, with **full provenance**: an `AssignmentEvent.decided_by = 'supervisor_manual'`
row is appended *and* the ticket's `priority` is not simply overwritten — the
`PriorityRule` engine re-runs *underneath*, and only a supervisor at team tier ≥ the
rule's `priority_outcome` may change priority downwards. If the rule outcome carries a
**safety floor** (`priority_outcome = P1` with `conditions.priority_safety_floor = true`),
the downgrade is *rejected at write time* by a CHECK trigger; successful overrides are
logged in a `priority_override` JSONB column of the latest AssignmentEvent of the
ticket together with (`from`, `to`, `decided_by`, `reason`). Every reducer is a pure
function in `services/priority.py::apply_priority_transition` — no side effects outside the event ledger.

## D-Q7. Duplicate tickets (Q7)

**Kept, cross-referenced, never deleted.** The generator may append a structurally
separate duplicate ticket; a `ticket_duplicate_of` link becomes a row on the original
ticket as `ticket_duplicate_of = <the earlier ticket's id>` (NULL otherwise,
UNIQUE self-check: no duplicate chains). The dup is auto-`closed` at intake with a
system Message resolution note; cross-reference column is FK-validated but the row is
not deleted. Grader can LEFT-join on it.

## D-Q8. CSAT window & auto-close (Q8)

After `resolved`, ticket auto-closes `10 business days` after resolution if the
customer hasn't replied to reopen the ticket (`CLOSE_AFTER_BUSINESS_DAYS = 10` in the
remaining-relevant calendar). A CSAT survey row may be filled via `Resolution.csat_score`
but it is **independently optional** (not a precondition of auto-close). The `closed`
transition is written by the scheduler as a system Message; no manual interaction needed.

## D-Q9. Intent storage granularity (Q9)

Both levels — per-message optional `Message.intent_code` / `intent_confidence` +
ticket-level `Ticket.primary_intent_code`, synced from the latest `customer`-authored
message before resolved; the sync event is written as a pure function whatever
`Message.intent_code` row was last relevant; the same contract defines both. We do NOT
add a `TicketIntentHistory` entity — over-engineering for a 3-day window.

## D-Q10. Voice channel (Q10)

**In-flow, transcript becomes messages.** One call is stored as two Message rows:
the `customer` side (`description` extracted from the caller's turns) and the
`agent` side (summary / confirmation turn). The `body` holds the transcript text;
`Message.intent_code`/`intent_confidence` are written computed-from-transcript as for
any message. No binary audio or new entity: binary voice data is out of scope for the
3-day window; ticket/media out-of-line, if the challenge asks for it later, adds a
`MessageAttachment` entity in a later migration.

---

## Implementation-level notes (non-question decisions)

- **TicketSkill bridge, not `TEXT[]` on Ticket.** The dictionary carries a contradiction (§5 declares `Ticket.required_skill_codes TEXT[]`, §13 declares the `TicketSkill` bridge). We implement the **bridge** per the "no comma-separated M:N" doctrine and drop the ticket-level `TEXT[]` column; `Queue.required_skill_codes TEXT[]` remains because it is a 1-many catalog reference, FK-validated (per §13 doctrine).
- **All 13 entities + bridges get `created_at`/`updated_at` audit columns** (`TIMESTAMPTZ`, `server_default=now()`, `onupdate=now()`), even though §17 table omits them ("omitted below" note in §3).
- **No surrogates.** Business text IDs are the PKs everywhere, per §2. Only `GroundTruthLabel.label_id` is BIGSERIAL (the dictionary already allows it) and the CalendarHoliday composite PK.
- **Internal DB keys, external business keys** — no confusion; every entity PK is the TEXT business ID itself (no hidden `id` int column, to eliminate dual-key joins entirely). Where useful, secondary denormalised indexes exist for hot paths (FKs on ticket_id, agent_id, queue_id etc.)
- **Enforcement of the closed ledger** (§14.4) is done by an SQLAlchemy `event`-level validator plus DB `CHECK` + `BEFORE UPDATE` triggers in migrations; the trigger is a belt-and-braces duplicate of the app-level gate, not the source of truth.
- **Namespaces / enum storage** as §1.2: TEXT + CHECK everywhere (no Postgres `ENUM` types — no ALTER pain during the 72h window).
