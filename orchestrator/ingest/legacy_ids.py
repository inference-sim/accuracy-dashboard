#!/usr/bin/env python3
"""The map from each point_id in a snapshot published before point ids became unit ids, to its
ledger unit (COV-8: published snapshots never change, so they are matched to units through this
map, never rewritten).

Before, a point_id was the SHA-256 of eight InferenceX fields: model, hardware, precision,
framework, benchmark_type, recipe (the recipe fingerprint, or "row:<API row id>"), conc and
measured_date (the row's own date). Such an id names one API row, or several rows that shared
a recipe fingerprint, concurrency and date. The map pairs it with the units those rows are in.

  legacy_ids.py build --rows ROWS.json --ledger LEDGER --data DATA --out MAP
      ROWS: every InferenceX vLLM row of the API (a JSON list), LEDGER: blis-substrate's
      catalog/ledger, DATA: the published data/ tree. Writes MAP.
  legacy_ids.py check --map MAP --data DATA
      Every point_id of every published v2 snapshot is in MAP, and MAP holds no other.

MAP is canonical JSON: {"kind": "LegacyPointIds", "ledger_revision", "points": {old_id: entry}},
entry {"units": [unit_id, ...], "rows": [row id, ...]} or {"units": [], "reason": ...} for an id
the map cannot place: no_api_row (the API no longer returns the rows it was computed from) or
not_in_source_revision (its rows are newer than the ledger's source revision).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import contract as c  # noqa: E402
import ledger as ldg  # noqa: E402

LEGACY_FIELDS = ("model", "hardware", "precision", "framework", "benchmark_type", "recipe", "conc",
                 "measured_date")


def legacy_identity(row: dict) -> dict:
    """The eight-field identity a point had before (CONTRACT.md before this change)."""
    return {"model": row["model"], "hardware": row["hardware"], "precision": row["precision"],
            "framework": row["framework"], "benchmark_type": row["benchmark_type"],
            "recipe": row.get("recipe_fingerprint") or f"row:{row['id']}", "conc": int(row["conc"]),
            "measured_date": str(row["date"])[:10]}


def legacy_point_id(identity: dict) -> str:
    if sorted(identity) != sorted(LEGACY_FIELDS):
        raise ValueError(f"not a legacy identity: {sorted(identity)}")
    return hashlib.sha256(c.canonical_dumps(identity).encode("utf-8")).hexdigest()


def published_ids(data: Path) -> set[str]:
    """Every point_id a published v2 snapshot (or the live view) holds: scored points, their
    folded repeats, and not-scored points."""
    out: set[str] = set()

    def walk(x):
        if isinstance(x, dict):
            if "point_id" in x and "identity" in x and "recipe" in x["identity"]:
                out.add(x["point_id"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    for f in sorted(Path(data).glob("snapshots/*/summary.json")) + [Path(data) / "latest" / "summary.json"]:
        doc = json.loads(f.read_text())
        if doc.get("schema_version") == 2:
            walk(doc.get("matrix", []))
            walk(doc.get("not_scored", []))
    return out


def build(rows: list[dict], lg: "ldg.Ledger", ids: set[str]) -> dict:
    by_old: dict[str, list[dict]] = {}
    for r in rows:
        by_old.setdefault(legacy_point_id(legacy_identity(r)), []).append(r)
    points = {}
    for pid in sorted(ids):
        rs = sorted(by_old.get(pid, []), key=lambda r: int(r["id"]))
        if not rs:
            points[pid] = {"units": [], "reason": "no_api_row"}
            continue
        units = sorted({lg.by_record[str(r["id"])].unit.unit_id for r in rs if str(r["id"]) in lg.by_record})
        if not units:
            points[pid] = {"units": [], "reason": "not_in_source_revision", "rows": [str(r["id"]) for r in rs]}
            continue
        points[pid] = {"units": units, "rows": [str(r["id"]) for r in rs]}
    return {"kind": "LegacyPointIds", "ledger_revision": lg.revision, "points": points}


def check(doc: dict, ids: set[str]) -> list[str]:
    have = set(doc.get("points", {}))
    out = [f"{p[:12]}: published, not in the map" for p in sorted(ids - have)]
    out += [f"{p[:12]}: in the map, not published" for p in sorted(have - ids)]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--rows", required=True)
    b.add_argument("--ledger", required=True)
    b.add_argument("--data", required=True)
    b.add_argument("--out", required=True)
    k = sub.add_parser("check")
    k.add_argument("--map", required=True)
    k.add_argument("--data", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "build":
        doc = build(json.loads(Path(a.rows).read_text()), ldg.load(Path(a.ledger)), published_ids(Path(a.data)))
        Path(a.out).write_text(c.canonical_dumps(doc) + "\n")
        reasons: dict = {}
        for e in doc["points"].values():
            reasons[e.get("reason", "mapped")] = reasons.get(e.get("reason", "mapped"), 0) + 1
        print(f"{len(doc['points'])} published point ids: {reasons}", file=sys.stderr)
        return 0
    problems = check(json.loads(Path(a.map).read_text()), published_ids(Path(a.data)))
    for p in problems:
        print(p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
