import sys
from pathlib import Path

APPS = Path(__file__).resolve().parents[2]
for p in (
    APPS / "datagen",
    APPS / "api",
):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
