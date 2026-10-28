"""CLI: python -m datagen --seed 20261022 --scale dev --out data/out/dev [--config PATH] [--force]."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import DEFAULT_CONFIG_PATH, load_scale_config
from .generators import generate_reference_catalog, generate_ticket_ledger
from .ids import IdAllocator
from .manifest import build_manifest, write_manifest
from .schema import TABLE_EMISSION_ORDER, table_column_spec, table_name
from .streams import DEFAULT_SEED, StreamContext
from .writers import write_table_csv


def generate_dataset(seed: int, scale_name: str, out_dir: Path, config_path: Path | None,
                     force: bool = False) -> dict:
    out_dir = out_dir.resolve()
    if out_dir.exists() and not force and any(out_dir.glob("**/*.csv")):
        raise SystemExit(f"refusing to overwrite existing CSVs under {out_dir} (use --force)")
    out_dir.mkdir(parents=True, exist_ok=True)

    config = load_scale_config(scale_name, seed, config_path or DEFAULT_CONFIG_PATH)
    streams = StreamContext(seed)
    ids = IdAllocator()

    reference, catalog = generate_reference_catalog(config, streams, ids)
    ledger = generate_ticket_ledger(config, streams, ids, catalog)
    table_rows = dict(reference)
    table_rows.update(ledger)
    table_rows["ground_truth_label"] = []  # header-only file until anomaly stage

    files: dict[str, dict] = {}
    for schema, model in TABLE_EMISSION_ORDER:
        table = table_name(model)
        if table not in table_rows:
            raise RuntimeError(f"no rows produced for tabulated table {table!r}")
        spec = table_column_spec(model)
        sha256, n_rows = write_table_csv(out_dir, schema, table, spec, table_rows[table])
        files[table] = {"schema": schema, "sha256": sha256, "rows": n_rows}

    manifest = build_manifest(
        seed=seed, scale_name=config.name, config_sha256=_config_sha(config),
        files=files, n_tickets=len(table_rows["ticket"]),
        window_start=config.window_start, window_end=config.window_end,
    )
    manifest_path = out_dir / "manifest.json"
    write_manifest(manifest_path, manifest)
    return {
        "manifest_path": str(manifest_path),
        "n_tickets": len(table_rows["ticket"]),
        "counts": {name: entry["rows"] for name, entry in files.items()},
        "out_dir": str(out_dir),
        "seed": seed,
        "scale": config.name,
    }


def _config_sha(config) -> str:
    from .config import sha256_config

    return sha256_config(config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="datagen", description=__doc__)
    parser.add_argument("--seed", type=int, default=None,
                        help=f"default {DEFAULT_SEED}")
    parser.add_argument("--scale", required=True,
                        choices=("s0", "s1", "s2", "dev", "full"))
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=None,
                        help=f"scales file (default {DEFAULT_CONFIG_PATH})")
    parser.add_argument("--force", action="store_true",
                        help="overwrite existing CSVs in --out")
    args = parser.parse_args(argv)

    seed = args.seed if args.seed is not None else DEFAULT_SEED
    result = generate_dataset(seed, args.scale, args.out, args.config, force=args.force)
    print(f"scale={result['scale']} seed={result['seed']} tickets={result['n_tickets']}")
    print(f"output: {result['out_dir']}")
    print(f"manifest: {result['manifest_path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
