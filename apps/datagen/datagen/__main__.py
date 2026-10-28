"""Entry point: python -m datagen --seed 20261022 --scale s0 --out tmp/clean --force."""
from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
