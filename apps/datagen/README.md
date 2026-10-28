# Datagen — deterministic synthetic ticket corpus

Generator for the YottaFlex.ai **Support Ticket Routing & SLA Intelligence** challenge
(Stage 3 dataset scaffold). It emits the full synthetic corpus described in
`DATA_DICTIONARY.md`: a dimension catalog (customers, agents, skills, queues, …) plus an
`ops/` operational ledger (tickets, messages, assignment events, SLA events, resolution)
and header-only `gold/` files reserved for the later anomaly stage.

**Scope boundary:** this app generates data only. It does not inject anomalies, score
ground truth, or run the routing engine — those are later stages. `gold/ground_truth_label.csv`
ships header-only until then.

## Determinism contract

- Single canonical seed: **20261022** (override only for experiments).
- The same seed + scale produces **byte-identical** CSVs and `manifest.json` on the same
  machine, verified on every run by the test suite.
- Every RNG consumer draws from its own named stream via `StreamContext.stream(name)`
  (belch/fair inspired); stream order is fixed by generation order.
- IDs are counter-based (`IdAllocator`), never RNG-derived: `TKT-<YYYY>-<6d>`,
  `CST-<6d>`, `AGT-<4d>`, `ASN-TKT-…-<3d>`, `RES-TKT-…`.
- Tables are emitted **parent-before-child** (`schema.TABLE_EMISSION_ORDER`), so the corpus
  is loadable into Postgres in CSV order with FK enforcement on.
- The manifest carries per-file SHA-256; the machine-varying `generator` block (platform,
  Python version) is the only field expected to differ across machines.

## Usage

```bash
cd apps/datagen
python -m datagen --seed 20261022 --scale dev --out data/out/dev --force
```

Scales are presets in `data/config/dataset_scale.yaml`: `s0` (smoke), `s1`, `s2`, `dev`,
`full` (5,000 customers / 90 agents / 30,000 tickets). Validation rejects seeds outside
`1..10_000_000`, unknown presets, non-positive mix weights, and unknown intent/channel
codes (see `datagen/config.py`).

Without `--force`, `generate_dataset` refuses to overwrite an existing output directory.

## Output layout

```
<out>/
  ops/            operational ledger CSVs (ticket-first FK order)
  gold/           ground_truth_label.csv (header-only until the anomaly stage)
  manifest.json   seed, scale{name, window, n_tickets, config sha256}, per-file sha256
```

## Business rules encoded here

- **D-Q7** — duplicates are auto-`closed` at intake: no agent, no dedup chain
  (`ticket_duplicate_of` never points at another duplicate), an immediate
  `resolution` row with `resolution_type="duplicate"`, blank CSAT, and
  `resolved_at == detected_at`.
- **D-Q8** — resolved tickets auto-close 10 business days after resolution via the
  calendar scheduler; CSAT is independently optional, so scheduler-closed tickets may
  legitimately have no resolution row.
- Priority floor: `INTENT-OUTAGE-REPORT` and `INTENT-ACCOUNT-SUSPENSION` are always P1.
- Every ticket has ≥1 assignment event at `seq 1` (intake, to its current queue) and
  exactly one SLA event.

## Tests

```bash
python -m pytest tests -q     # 16 tests
python -m ruff check datagen tests
```

The invariants run at scale `s0` per test session; the determinism test runs the preset
twice and diffs SHA-256 across all emitted files.

## Known boundary

Postgres-side behavior (migrations, `COPY` load order) is not exercised in CI here —
validation compares the CSVs against the SQLite-checked API models (`apps/api/app/models`).
Docker/psql is intentionally out of scope; FK ordering is guaranteed by construction.
