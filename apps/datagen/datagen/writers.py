"""CSV writers + sha-256 hashing (manifest contract 16.6).

CSV conventions (documented in apps/datagen/README.md):
- one UTF-8 file per table: ``<out>/<schema>/<table>.csv``
- header row of SQL column names, table column order preserved
- ``None`` → empty field; booleans → ``true``/``false``; timestamps → ISO-8601
  with explicit ``+00:00``; TEXT[] → Postgres array literal ``{a,b}``;
  JSONB → compact ``json.dumps``
- lines end with ``\n`` (LF), QUOTE_MINIMAL
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import pathlib
from typing import Any

Bool = bool
DateVal = str
TsVal = str


def _serialize_array(values: list[str] | None) -> str:
    if values is None:
        return ""
    escaped = [v.replace("\\", "\\\\").replace('"', '\\"') for v in values]
    return "{" + ",".join(escaped) + "}"


def _serialize_jsonb(value: dict[str, Any] | None) -> str:
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _serialize_value(category: str, value: Any) -> str:
    if value is None:
        return ""
    if category == "bool":
        return "true" if value else "false"
    if category == "array":
        return _serialize_array(value)
    if category == "jsonb":
        return _serialize_jsonb(value)
    if category in ("int", "numeric", "float"):
        return str(value)
    if category in ("date", "datetime", "text"):
        return str(value)
    raise ValueError(f"unknown serializer category: {category!r}")  # pragma: no cover


def render_csv(
    column_spec: list[tuple[str, str, str]],
    rows: list[dict[str, Any]],
) -> bytes:
    """Render one table's CSV to UTF-8 bytes (header + rows)."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    column_keys = [key for key, _sql, _cat in column_spec]
    column_names = [sql for _key, sql, _cat in column_spec]
    categories = {key: cat for key, _sql, cat in column_spec}
    writer.writerow(column_names)
    for row in rows:
        missing = [key for key in column_keys if key not in row]
        if missing:
            raise KeyError(f"row for table is missing columns: {missing}")
        writer.writerow([_serialize_value(categories[key], row[key]) for key in column_keys])
    return buffer.getvalue().encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_table_csv(
    out_dir: pathlib.Path,
    schema: str,
    table: str,
    column_spec: list[tuple[str, str, str]],
    rows: list[dict[str, Any]],
) -> tuple[str, int]:
    """Write one CSV, return (sha256_hex, n_rows)."""
    target = out_dir / schema / f"{table}.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = render_csv(column_spec, rows)
    target.write_bytes(payload)
    return sha256_bytes(payload), len(rows)
