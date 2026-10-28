# YottaFlex.ai — Support Ticket Routing & SLA Intelligence Platform
## ARCHITECTURE.md — v0.1 (Planning / Schema-Design Stage)

> Companion to `DATA_DICTIONARY.md` (same status: draft, pre-implementation).
> Scope of this stage: repo layout, data flow, engine contracts, test & reproducibility
> strategy, execution roadmap. **No code written yet.**

---

## 1. Problem framing

The platform has three jobs, all evaluated on the same synthetic corpus generated
under seed `20261022`:

1. **Routing** — given a ticket's intake facts (channel, language, classified intent,
   customer tier, priority from the rules engine), decide queue + agent, respecting
   skills, concurrency caps, calendars, and escalation rules.
2. **SLA intelligence** — compute/predict clock behaviour against channel-aware
   calendars, detect breaches, and drive escalations.
3. **Anomaly detection** — label the 5 anomaly families (§12 of the data dictionary)
   from the *same* deterministic functions the router/SLA engines use, using labels
   stored **outside** the serving schema.

### Determinism doctrine
- One seed (`20261022`), many named RNG streams (no shared streams).
- IDs from counters, not RNG.
- **Derived values are always pure functions of base data** — the generator never
  "rolls dice" for anything a runtime engine would also compute. We will generate
  the dataset by *simulating the engine*, not by pre-deciding its outputs randomly.
- Ground-truth labels live in a separate `gold` schema; the serving schema never
  joins it (enforced by a CI test on connection grants).

---

## 2. Repository layout

```
yottaflex.ai/
├── README.md
├── docker-compose.yaml              # postgres, api, web, (future) worker
├── Makefile                         # make up / seed / test / lint / run
├── .env.example
│
├── docs/
│   ├── DATA_DICTIONARY.md           # ← created in this stage
│   ├── ARCHITECTURE.md              # ← created in this stage
│   ├── decisions/                   # ADR-0001.md … (one per OPEN question resolved)
│   └── open_questions.md            # row-per-question tracker, owner, decision
│
├── apps/
│   ├── api/                         # FastAPI service
│   │   ├── pyproject.toml
│   │   ├── alembic/                 # migrations (single source of schema truth)
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── core/                # config.py (pydantic-settings), logging, deps
│   │   │   ├── db/                  # base.py, session.py, mixins (audit columns)
│   │   │   ├── models/              # SQLAlchemy ORM, one file per entity
│   │   │   ├── schemas/             # Pydantic v2 request/response models
│   │   │   ├── api/v1/              # routers: tickets, messages, agents, queues,
│   │   │   │                        #   rules, sla, anomalies, admin
│   │   │   ├── services/            # domain logic — pure where possible:
│   │   │   │   ├── priority.py      #   PriorityRule evaluation (pure, shared)
│   │   │   │   ├── routing.py       #   assignment engine (txn + advisory locks)
│   │   │   │   ├── sla.py           #   calendar clock math (pure, shared)
│   │   │   │   ├── escalation.py    #   scheduler step
│   │   │   │   ├── anomalies.py     #   the 5 detectors (pure predicates)
│   │   │   │   └── intents.py       #   intent classifier wrapper (ml/)
│   │   │   └── ml/                  # lightweight, isolated:
│   │   │                            #   intent classifier baseline (TF-IDF +
│   │   │                            #   linear head), model registry, version
│   │   └── tests/                   # pytest (unit / integration / property)
│   │       ├── unit/
│   │       ├── integration/         # against disposable postgres (testcontainers)
│   │       ├── conftest.py
│   │       └── determinism/         # re-derivation diffs, seed checks
│   │
│   ├── datagen/                     # standalone Python package: synthetic corpus
│   │   ├── pyproject.toml
│   │   ├── datagen/
│   │   │   ├── cli.py               # `datagen --seed 20261022 --scale s1`
│   │   │   ├── config/              # dataset_scale.yaml (s0/s1/s2 presets)
│   │   │   ├── streams.py           # StreamContext(seed)->named streams (§16)
│   │   │   ├── ids.py               # counter-based ID allocator
│   │   │   ├── generators/          # customers.py, agents.py, skills.py,
│   │   │   │                        #   queues.py, channels.py, rules.py,
│   │   │   │                        #   tickets.py (drives messages/events too)
│   │   │   ├── engine/              # calls the API's *pure* domain functions:
│   │   │   │                        #   priority, routing, sla, escalation
│   │   │   │                        #  (imported from apps/api services pkg,
│   │   │   │                        #   single implementation rule)
│   │   │   ├── anomalies.py         # injection pass + label writing (gold schema)
│   │   │   ├── writers/             # csv/parquet writers + postgres COPY loader
│   │   │   └── manifest.py          # hashes, versions, scale, seed
│   │   └── tests/
│   │
│   ├── eval/                        # evaluation harness (separate conn to gold)
│   │   ├── pyproject.toml
│   │   ├── evalkit/
│   │   │   ├── metrics.py           # routing accuracy, SLA MAE, breach PR-AUC,
│   │   │   │                        # anomaly micro-F1 per family
│   │   │   ├── runner.py            # replays corpus through services, no leakage
│   │   │   └── reports/             # JSON + markdown scorecards
│   │   └── tests/
│   │
│   └── web/                         # React 18 + Vite + TS (later phase)
│       └── (scaffolded later; only consumes /api/v1)
│
├── scripts/                         # dev convenience: bootstrap.sh, load_golds.py
└── .github/workflows/ci.yaml        # lint, typecheck, pytest, determinism job
```

**Why this shape**
- `apps/api/services` holds **pure, importable domain functions**; `apps/datagen`
  imports them instead of reimplementing (one deterministic definition per rule —
  the single most important reproducibility property).
- `datagen` and `eval` are separate processes from the API so generation can run
  without a server and evaluation can hold gold-privileges cleanly.
- The gold schema is a *PostgreSQL privilege boundary*, not just a convention.

---

## 3. Runtime data flow (serving path)

```
Card/Email/API intake
        │  (idempotent, UTC-normalized)
        ▼
ticket created (status=new) ──► Message #001 persisted
        │
        ▼
ml.intents.classify(body) ──► intent_code (+confidence, model_version)
        │
        ▼
services.priority.evaluate(ticket) ──► P1..P4  (pure function, fallback PRL-999)
        │
        ▼
queue intake: pick queue by intent default / channel / tier
        │      └─ emits AssignmentEvent(seq=1, phase=queue_intake)
        ▼
services.routing.assign(queue) ── serialized txn w/ advisory lock
        │      pool = valid QueueMembership ∧ agent.status=active
        │      ∧ AgentLanguage≥3 ∧ AgentSkill⊇required
        │      ∧ load < min(agent_cap, queue_cap) ∧ agent clock open
        │      order = queue.routing_strategy, tie-break agent_id asc
        │      └─ emits AssignmentEvent(seq=n, phase=agent_assigned)
        ▼
services.sla.clock(ticket) ── calendar-aware; pause on pending_customer
        │      breach_flags derived; breach ⇒ escalation scheduler
        ▼
lifecycle transitions (closed ledger §14.4) / Resolution row
```

**Escalation scheduler:** periodic job (in API: background task; in generation:
part of the simulator tick), iterating open tickets and applying EscalationRules;
every action writes an AssignmentEvent (`phase=queue_reassigned`,
`reason=escalation:<rule_id>`) — no silent assignments.

---

## 4. Tech stack & versions (pinned in pyproject)

| Concern | Choice |
|---|---|
| Language (backend) | Python 3.12 |
| Web framework | FastAPI ≥0.115, Pydantic v2, pydantic-settings |
| ORM/migrations | SQLAlchemy 2.x (typed), Alembic |
| DB | PostgreSQL 16 (docker-compose) |
| Testing | pytest, pytest-asyncio, testcontainers-postgres, hypothesis (for SLA clock property tests) |
| Lint/type | ruff, mypy (strict on `services/`, `datagen/engine`) |
| Synthetic data | numpy RNG (PCG64) via named streams; faker only for display strings (seeded) |
| Intent baseline | scikit-learn TF-IDF + SGDClassifier; export joblib + metrics JSON; model version string in every prediction |
| Frontend (later) | React 18, Vite, TypeScript, TanStack Query |
| Auth (challenge scope) | static API key/OIDC-lite header via FastAPI dependency |

---

## 5. Database schema packaging

- Single Postgres instance, two schemas:
  - `ops` — the 13 entities + supporting tables (serving + generator both write/read).
  - `gold` — `GroundTruthLabel` (+ eval snapshots). Granted to `datagen` and `eval`
    roles only. The API role has **no** SELECT on `gold`; a CI smoke test proves it.
- Alembic owns `ops`; `gold` is created by datagen's bootstrap (kept out of serving
  migrations on purpose).
- All CHECK constraints, FK actions, partial-unique indexes from the data
  dictionary are realized in ORM metadata — no "trust the app" constraints.

---

## 6. Testing strategy

| Layer | What proves |
|---|---|
| `tests/unit` | pure functions: priority eval (rule tables, tie-breaks), SLA clock math across calendars/holidays/pauses, 5 anomaly predicates |
| `tests/integration` | routing txn (concurrency cap held under parallel assigns), lifecycle triggers reject illegal transitions, FK/unique enforcement |
| `tests/determinism` | regenerate with same (seed, scale) → identical manifest hashes; derived columns re-derive byte-equal; gold labels re-derive equal |
| property (hypothesis) | SLA elapsed ≥ 0; pause removal idempotent; elapsed monotonic in calendar windows; routing invariant: no agent exceeds cap at any sim timestamp |
| `eval` | metrics reported only through `evalkit.runner`, which replay *serving* data and consult `gold` via the eval role |

---

## 7. Reproducibility & scale (contract with datagen)

- CLI: `datagen --seed 20261022 --scale presets/s1.yaml --out data/out/s1`
- Scale presets: `s0` (smoke: ~50 tickets), `s1` (~2k), `s2` (~20k) — every knob in
  `dataset_scale.yaml`.
- Emission order fixed (customers → agents → … → tickets with children inline) to
  keep counter IDs stable when scale changes; each run emits `manifest.json`
  (seed, scale, input-config sha-256, output sha-256s, versions).
- Orientation: generate by **simulating the real engines** (priority/routing/SLA)
  so the "ground truth" of routing/SLA is *what the engine would actually do*;
  anomalies are then injected post-hoc and labelled without mutating unrelated rows.

---

## 8. API surface (v1, initially minimal)

| Resource | Verbs | Notes |
|---|---|---|
| `/api/v1/tickets` | POST (intake), GET (filters), GET /{id} (with messages/events), PATCH status | PATCH goes through lifecycle validator |
| `/api/v1/tickets/{id}/messages` | POST, GET | language detect + intent classified at write |
| `/api/v1/agents` · `/queues` · `/skills` | CRUD (admin) | effective-dated writes enforced |
| `/api/v1/rules/priority` · `/escalation` | CRUD | versioned; activations return matched-rule trace |
| `/api/v1/sla/{ticket_id}` | GET | clock state + projected deadline + breach flags (derived) |
| `/api/v1/anomalies` | GET (post-hoc scan endpoint) | runs detectors read-only, writes nothing |
| `/api/v1/admin/seed-status` | GET | current dataset manifest (for challenge demo) |

---

## 9. Execution roadmap after this stage

1. **M0 — Decisions:** resolve §12/Q1–Q10 of the data dictionary (write ADRs).
2. **M1 — Skeleton:** repo scaffolding, docker-compose, alembic base, CI green.
3. **M2 — Schema:** ORM models + migrations for all 13 entities + bridges + calendar/
   escalation/gold; CHECK/FK inline; determinism test harness stub.
4. **M3 — Datagen s0:** streams, IDs, generator set, manifest; verify re-hash.
5. **M4 — Engines:** priority + routing + SLA + escalation services (pure cores),
   unit + property tests.
6. **M5 — API on engine + minimal frontend read views.**
7. **M6 — Anomaly pass + eval harness + scorecard.**
8. **M7 — Scale s1/s2 runs, docs, demo script.**

Target effort: M0–M2 ≈ first day; M3–M6 spread over the remaining 48h; M7 buffer.

---

## 10. Risks & open items (mirrors DATA_DICTIONARY §12)

- The **five anomaly families** must be confirmed (Q1) — schema is already agnostic
  (`anomaly_code` text), but detection/eval logic waits.
- SLA policy matrix values (Q2), supported languages (Q3), auto-reply clock rule (Q4)
  block only constants, not structure.
- Voice-channel transcript modelling (Q10) affects datagen only.
- API-role-gold privilege test is a hard CI gate; if the evaluation harness ever
  needs labels inside serving responses, it must go through an explicit, labelled
  projection endpoint — never a join.
