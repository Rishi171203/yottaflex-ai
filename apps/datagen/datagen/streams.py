"""Named RNG streams (DATA_DICTIONARY 16.1).

One seed (default 20261022), many named streams. Each stream is derived via
SHA-256 of ``f"{seed}:{stream_name}"``; two consumers never share a stream, so
adding a generator never shifts another generator's output.
"""
from __future__ import annotations

import hashlib
import random

# Canonical stream names (superset used by all generators). New generators must
# register their stream name here; existing streams stay byte-stable.
STREAM_NAMES: tuple[str, ...] = (
    "languages",
    "calendars",
    "customers",
    "agents",
    "skills",
    "channels",
    "queues",
    "intents",
    "rules",
    "bridges",
    "tickets",
    "messages",
    "assignment_events",
    "sla_events",
    "resolutions",
    "anomalies",
)

DEFAULT_SEED = 20261022


def derive_stream_seed(seed: int, stream_name: str) -> int:
    """Deterministic per-stream seed from SHA-256(f"{seed}:{stream_name}")."""
    digest = hashlib.sha256(f"{seed}:{stream_name}".encode()).digest()
    return int.from_bytes(digest, "big") % (2**63 - 1)


class StreamContext:
    """Factory of named, isolated random streams."""

    __slots__ = ("_streams", "seed")

    def __init__(self, seed: int = DEFAULT_SEED) -> None:
        self.seed = seed
        self._streams: dict[str, random.Random] = {}

    def stream(self, name: str) -> random.Random:
        """Return ( memoizing ) the Random for a named stream."""
        rng = self._streams.get(name)
        if rng is None:
            if name not in STREAM_NAMES:
                raise ValueError(f"unknown stream name: {name!r} (not in STREAM_NAMES)")
            rng = random.Random(derive_stream_seed(self.seed, name))
            self._streams[name] = rng
        return rng
