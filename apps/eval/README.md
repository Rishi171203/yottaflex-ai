# Eval — detector evaluation vs ground truth

Evaluation harness for the YottaFlex.ai Support Ticket Routing & SLA Intelligence
challenge: it reads the ops CSV tree and gold labels, runs the five `ANOM-*`
detectors (`eval/detectors.py`), and emits a micro + per-code
precision/recall/F1 scorecard with false-positive and missed-label diagnostics
(`eval/score.py`).

Verified locally end-to-end on the `s0` profile (seed 20261022): the injected
tree scores findings=16 gold=16 precision=1.000 recall=1.000 f1=1.000, and the
clean tree produces zero findings. Full-scale profiles (`s1`, `s2`, `full`) and
PostgreSQL-backed runs are **not** verified. The running commands are documented
in the root `README.md` ("Anomaly pipeline (datagen → eval)").

## Tests

```bash
python -m pytest tests -q     # 4 tests, no Postgres required
```
