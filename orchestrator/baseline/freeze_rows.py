#!/usr/bin/env python3
"""Freeze the recorded runs of a pinned list of InferenceX rows that the ledger does not hold yet.

The baseline's pull (freeze.py) is the 1734 points of the ledger's source revision. It is a fixed
set and this script never touches it. Rows measured after that revision have no ledger unit, so
this script makes the unit the way the ledger's ingest tool does (contract.unit_identity, whose
hash is the unit_id) into a supplementary ledger directory, and freezes the rows' artifacts into a
pull of their own. The rows are pinned by their API records, committed as ROWS.json (the API's
records are not stable, and the artifacts expire after 90 days), so the same rows can be frozen
again while the artifacts last.

    freeze_rows.py --rows ROWS.json --revision NAME --ledger-out DIR --out PULL --cache CACHE
                   [--units-out FILE]

A supplementary ledger is not the substrate's ledger: its units have no role key (the placeholder
is all zeros) and its `revision` says so. The development split does not read role keys.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ingest"))
import api  # noqa: E402
import cli  # noqa: E402
import contract  # noqa: E402

NO_ROLE_KEY = "0" * 64


def write_ledger(directory: Path, rows: list[dict], revision: str) -> list[str]:
    """A ledger directory (units/inferencex.jsonl.gz, reports/inferencex.yaml) holding one unit
    per row, in the format ledger.load reads. Returns the unit ids."""
    d = Path(directory)
    (d / "units").mkdir(parents=True, exist_ok=True)
    (d / "reports").mkdir(parents=True, exist_ok=True)
    dates = contract.run_dates(rows)
    units = {}
    for r in rows:
        ident = contract.unit_identity(r, dates)
        uid = contract.point_id(ident)
        if uid in units:
            raise ValueError(f"rows {units[uid]['measurements'][0]['record']} and {r['id']} have one identity")
        measured = hashlib.sha256(contract.canonical_dumps(r["metrics"]).encode()).hexdigest()
        units[uid] = {"unit_id": uid, "role_key": NO_ROLE_KEY, "identity": ident,
                      "measurements": [{"record": str(r["id"]), "measured": measured, "duplicates": [],
                                        "merged": [], "recorded": {}}]}
    lines = [units[k] for k in sorted(units)]
    (d / "units" / "inferencex.jsonl.gz").write_bytes(
        gzip.compress("".join(json.dumps(u, sort_keys=True) + "\n" for u in lines).encode(), mtime=0))
    by_fw: dict = {}
    for r in rows:
        by_fw[r["framework"]] = by_fw.get(r["framework"], 0) + 1
    (d / "reports" / "inferencex.yaml").write_text(json.dumps({
        "kind": "IngestReport", "source": "inferencex", "revision": revision, "input": "0" * 64,
        "records": len(rows), "units": len(lines), "role_keys": 0, "duplicates": 0, "merged": 0,
        "joined_units": 0, "joined_records": 0, "left_out": {}, "units_by_framework": dict(sorted(by_fw.items()))},
        indent=1, sort_keys=True) + "\n")
    return sorted(units)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", required=True, help="the pinned API records (a JSON list)")
    ap.add_argument("--revision", required=True, help="the supplementary ledger's name, written to its report")
    ap.add_argument("--ledger-out", required=True)
    ap.add_argument("--out", required=True, help="the new pull directory (never the baseline's)")
    ap.add_argument("--cache", required=True)
    ap.add_argument("--units-out")
    ap.add_argument("--download-workers", type=int, default=4)
    a = ap.parse_args(argv)
    rows = sorted(json.loads(Path(a.rows).read_text()), key=lambda r: int(r["id"]))
    units = write_ledger(Path(a.ledger_out), rows, a.revision)
    if a.units_out:
        Path(a.units_out).write_text("".join(u + "\n" for u in units))
    dates = sorted({str(r["date"])[:10] for r in rows})

    def pull(fetch, *, today, window_days):
        return api.Pull(rows=rows, window=(dates[0], dates[-1]))
    real = api.pull
    api.pull = pull
    try:
        rc = cli.cmd_pull(types.SimpleNamespace(
            out=a.out, today=dates[-1], window_days=180, cache=a.cache, prior=None, only=units,
            download_workers=a.download_workers, ledger=a.ledger_out))
    finally:
        api.pull = real
    if rc == 0:
        m = json.loads((Path(a.out) / "manifest.json").read_text())
        print(json.dumps({"points": len(m["points"]), "rows": len(rows), "units": len(units)}, sort_keys=True))
    return rc


if __name__ == "__main__":
    sys.exit(main())
