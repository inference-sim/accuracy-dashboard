"""A ledger directory for tests: one unit per row, written in the unit list's format.

Only tests use it, for rows that are not in testdata/ledger. The identity it writes is
contract.unit_identity's, which test_ledger.py checks against units that blis-substrate's own
ingest tool generated, so a unit written here is the unit the real tool would write for a row
that shares no benchmark run, measured values or identity with another.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import contract as c


def write(directory: Path, rows: list[dict], left_out: dict | None = None) -> Path:
    d = Path(directory)
    (d / "units").mkdir(parents=True, exist_ok=True)
    (d / "reports").mkdir(parents=True, exist_ok=True)
    dates = c.run_dates(rows)
    lines = []
    for r in rows:
        ident = c.unit_identity(r, dates)
        lines.append({"unit_id": c.point_id(ident), "role_key": "0" * 64, "identity": ident,
                      "measurements": [{"record": str(r["id"]), "measured": "0" * 64, "duplicates": [],
                                        "merged": [], "recorded": {}}]})
    lines.sort(key=lambda u: u["unit_id"])
    (d / "units" / "inferencex.jsonl.gz").write_bytes(
        gzip.compress("".join(json.dumps(u, sort_keys=True) + "\n" for u in lines).encode(), mtime=0))
    lo = {k: sorted(v) for k, v in (left_out or {}).items()}
    (d / "reports" / "inferencex.yaml").write_text(json.dumps({
        "kind": "IngestReport", "source": "inferencex", "revision": "test", "input": "0" * 64,
        "records": len(rows), "units": len(lines), "role_keys": 1, "duplicates": 0, "merged": 0,
        "joined_units": 0, "joined_records": 0, "left_out": lo, "units_by_framework": {}}))
    return d


def point_id(row: dict) -> str:
    """The point_id a lone row has: its own identity's hash."""
    return c.point_id(c.unit_identity(row, c.run_dates([row])))
