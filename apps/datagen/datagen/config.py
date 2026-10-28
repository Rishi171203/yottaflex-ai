"""Dataset scale configuration (DATA_DICTIONARY 16.4: "scales as config, not code").

The YAML at ``data/config/dataset_scale.yaml`` defines named presets; every knob
is positive. Mixes are integer weights (deterministic integer allocation).
"""
from __future__ import annotations

import hashlib
import pathlib
from dataclasses import dataclass
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = pathlib.Path(__file__).resolve().parents[1] / "data" / "config" / "dataset_scale.yaml"


class ScaleConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ScaleConfig:
    """One named scale preset, fully resolved."""

    name: str
    seed: int
    window_end: str  # inclusive ISO date; the dataset ends (last ticket) this day
    days: int
    n_customers: int
    n_agents: int
    n_skills: int
    n_queues: int
    tickets_per_day: int
    channel_mix: dict[str, int]
    intent_mix: dict[str, int]
    tier_mix: dict[str, int]
    language_mix: dict[str, int]
    ownership_tier_mix: dict[str, int]
    shift_mix: dict[str, int]
    resolution_mix: dict[str, int]
    csat_mix: dict[str, int]
    status_mix: dict[str, int]
    reopen_rate_pct: int = 0  # >0 only once the anomaly/centreline pass exists
    duplicate_rate_pct: int = 2

    @property
    def n_tickets(self) -> int:
        return self.days * self.tickets_per_day

    @property
    def window_start(self) -> str:
        """ISO date of the first day (inclusive); window spans [start, end]."""
        import datetime as dt

        end = dt.date.fromisoformat(self.window_end)
        first = end - dt.timedelta(days=self.days - 1)
        return first.isoformat()


def _require_positive_int(name: str, value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ScaleConfigError(f"{name} must be a positive int, got {value!r}")
    return value


def _check_mix(name: str, mix: dict[str, Any], allowed: set[str] | None = None) -> dict[str, int]:
    if not isinstance(mix, dict) or not mix:
        raise ScaleConfigError(f"{name} must be a non-empty dict of positive int weights")
    for key, weight in mix.items():
        if allowed is not None and key not in allowed:
            raise ScaleConfigError(f"{name}[{key!r}] not an allowed code")
        if not isinstance(weight, int) or isinstance(weight, bool) or weight <= 0:
            raise ScaleConfigError(f"{name}[{key!r}] must have a positive int weight")
    return {k: int(v) for k, v in mix.items()}


def _validate(raw: dict[str, Any], name: str, seed: int) -> ScaleConfig:
    window_end = raw.get("window_end")
    if not isinstance(window_end, str):
        raise ScaleConfigError(f"preset {name!r}: window_end must be an ISO date string")
    days = _require_positive_int("days", raw["days"])
    counts = {k: _require_positive_int(k, raw[k])
              for k in ("n_customers", "n_agents", "n_skills", "n_queues", "tickets_per_day")}
    mixes = {
        "channel_mix": _check_mix("channel_mix", raw["channel_mix"]),
        "intent_mix": _check_mix("intent_mix", raw["intent_mix"]),
        "tier_mix": _check_mix("tier_mix", raw["tier_mix"], {"free", "standard", "premium", "enterprise"}),
        "language_mix": _check_mix("language_mix", raw["language_mix"]),
        "ownership_tier_mix": _check_mix(
            "ownership_tier_mix", raw["ownership_tier_mix"],
            {"global", "regional", "product_specialist"},
        ),
        "shift_mix": _check_mix(
            "shift_mix", raw["shift_mix"], {"morning", "afternoon", "night", "split", "on_call"}
        ),
        "resolution_mix": _check_mix(
            "resolution_mix", raw["resolution_mix"],
            {"problem_solved", "workaround", "no_response", "customer_cancelled", "other"},
        ),
        "csat_mix": _check_mix("csat_mix", raw["csat_mix"]),
        "status_mix": _check_mix("status_mix", raw["status_mix"]),
    }
    duplicate_rate_pct = int(raw.get("duplicate_rate_pct", 2))
    if not 0 <= duplicate_rate_pct <= 100:
        raise ScaleConfigError("duplicate_rate_pct must be within 0..100")
    return ScaleConfig(name=name, seed=seed, days=days, window_end=window_end,
                       duplicate_rate_pct=duplicate_rate_pct, **counts, **mixes)


def sha256_config(config: ScaleConfig) -> str:
    """Stable config fingerprint (goes into manifest.json)."""
    payload = yaml.safe_dump(config.__dict__, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_scale_config(preset: str, seed: int, config_path: pathlib.Path | None = None) -> ScaleConfig:
    """Load a named preset from the scale YAML (or an override file)."""
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        raise ScaleConfigError(f"scale config not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    presets = document.get("presets", document)
    if preset not in presets:
        known = ", ".join(sorted(presets))
        raise ScaleConfigError(f"unknown scale preset {preset!r}; known: {known}")
    return _validate(presets[preset], preset, seed)


def weighted_pick(rng, mix: dict[str, int]) -> str:
    """Deterministic weighted draw for a named stream (integer cumulative)."""
    total = sum(mix.values())
    point = rng.randint(1, total)
    cumulative = 0
    for key, weight in mix.items():
        cumulative += weight
        if point <= cumulative:
            return key
    return next(iter(mix))  # pragma: no cover - unreachable, float safety
