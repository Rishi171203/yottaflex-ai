# yottaflex.ai

## YottaFlex Routing & SLA Intelligence — Dataset, Anomaly & Evaluation Pipeline

> A deterministic synthetic-dataset generator, anomaly injector, five-detector
> evaluation harness, and a FastAPI backend scaffold (schema, models,
> migrations, health endpoint) for the Support-Ticket Routing & SLA
> Intelligence challenge (72h window).

For the design rationale see:
- `DATA_DICTIONARY.md` — the schema contract (13 entities + bridges + events)
- `ARCHITECTURE.md` — repo layout, ops/gold split, testing strategy
- `docs/decisions/IMPLEMENTATION_DECISIONS.md` — the 10 open questions, resolved with configurable defaults

## Quickstart (works with Docker or without)

### 1. Get Postgres

```bash
docker compose up -d postgres   # starts Postgres 16 on :5432
#   user/pass/db: yottaflex / yottaflex_dev / yottaflex
```

(or point `DATABASE_URL` at your own Postgres 16+ instance in a copied `.env`)

### 2. Install libs

```bash
python -m venv .venv
source .venv/bin/activate          # Windows:  .venv/Scripts/activate
pip install -e "apps/api[dev]"
```

### 3. Migrate schema

```bash
alembic -c apps/api/alembic.ini upgrade head
```

### 4. Run the API

```bash
cd apps/api && uvicorn app.main:app --reload
# → http://localhost:8000/health  (also /openapi.json)
```

### 5. Tests

```bash
pytest apps/api -q           # unit tests: no Postgres required
# Postgres-dependent integration tests skip automatically, unless:
#   POSTGRES_TEST_DSN=postgresql://... (then they execute against that DB)
```

## Anomaly pipeline (datagen → eval)

Deterministic GUI-free CLI: generate the clean ops tree, inject labeled anomalies
into a separate output tree, and score detectors against gold labels.

```bash
mkdir -p tmp && cd apps/datagen      # workdir matters: -m datagen resolves the package there

# 1. Clean dataset (deterministic; seed 20261022, s0 profile)
python -m datagen --seed 20261022 --scale s0 --out tmp/clean --force
#    → tmp/clean/ops/*.csv + tmp/clean/gold/ground_truth_label.csv (header-only until step 2)

# 2. Inject the five ANOM-* anomaly families (decision D-Q1) into a separate tree
python -m datagen.inject --src tmp/clean --dst tmp/anomalies
#    → dst/ops/*.csv verbatim copies + appended injected rows,
#      gold/ground_truth_label.csv (ANOM-* labels)

# 3. Score the five detectors (P/R/F1 → JSON scorecard)
cd ../eval                            # apps/eval
python -m eval --ops ../datagen/tmp/anomalies/ops \
               --gold ../datagen/tmp/anomalies/gold/ground_truth_label.csv \
               --out ../datagen/tmp/report.json
#    → {"micro": {...}, "by_code": {...}, "false_positives": [...], "missed_labels": [...]}

# 4. Sanity: the clean tree must yield zero findings (no gold labels → F1 0.0, 0 FP)
python -m eval --ops ../datagen/tmp/clean/ops \
               --gold ../datagen/tmp/clean/gold/ground_truth_label.csv \
               --out ../datagen/tmp/report_clean.json
```

Both trees are byte-identical except for appended/modified rows written by the
injector; the verbatim-copy invariant is asserted by tests.

## Verification status

Verified in CI-less local runs: all four pipeline commands above, the whole-repo
test suite (`46 passed, 1 skipped`), and Ruff (`All checks passed!`).

Not yet verified:
- **PostgreSQL integration** — the API's Postgres-dependent integration tests
  skip unless `POSTGRES_TEST_DSN` is set; no live-DB run has been executed.
- **Full-scale dataset generation** — only the `s0` profile has been generated;
  the `s1`/`s2`/`full` profiles in `dataset_scale.yaml` are untested.

## Tests & lint (whole repo, no Postgres required)

```bash
python -m pytest apps/datagen/tests apps/eval/tests apps/api/tests -q
python -m ruff check apps/datagen apps/eval apps/api
```

## Run full stack on Docker

```bash
docker compose up --build       # pg + api (health endpoint at :8000/health)
```

## Layout

```
pyproject.toml            monorepo meta (ruff / mypy)
docker-compose.yaml       Postgres 16 + FastAPI api
apps/api/                 FastAPI backend scaffold: SQLAlchemy models, Alembic
                          migrations, health endpoint; no routing engine yet
apps/datagen/             deterministic synthetic dataset generator, seed=20261022
apps/eval/                evaluation harness: five ANOM-* detectors, P/R/F1 scorecard
DATA_DICTIONARY.md        schema contract (entities, bridges, anomaly framework)
ARCHITECTURE.md           repo layout, ops/gold split, testing strategy
docs/decisions/           IMPLEMENTATION_DECISIONS.md (D-Q1…D-Q10)
```
