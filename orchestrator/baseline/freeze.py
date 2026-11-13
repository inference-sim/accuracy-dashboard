#!/usr/bin/env python3
"""Re-freeze the pull behind a published snapshot, for the before/after comparison.

The nightly keeps nothing raw (COV-8), so the pull behind data/latest/summary.json has to be
made again from the live InferenceX API. The API has moved since, in two ways this script
records instead of hiding:

  * frameworks that did not exist on the snapshot's day (engines.unknown_labels) would stop the
    pull, so their rows are dropped;
  * a row whose identity now differs from the ledger's pinned source revision
    (ledger.RowDiffers) is dropped.

The units to freeze are the published snapshot's point ids mapped to ledger units through
data/legacy/point-ids.json. Writes <out>/drift.json beside the pull.

    freeze.py --snapshot-state state/last-run-api.json --legacy-map data/legacy/point-ids.json
              --ledger LEDGER --today 2026-11-09 --out PULL --cache CACHE
"""
from __future__ import annotations

import argparse
import json
import sys
import types
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ingest"))
import api  # noqa: E402
import cli  # noqa: E402
import contract  # noqa: E402
import engines  # noqa: E402
import ledger as ldg  # noqa: E402


def units_of(state: dict, legacy: dict) -> tuple[list[str], dict]:
    """The ledger units of a snapshot's point ids, and why any id has none."""
    units, why = set(), {}
    for pid in state["point_ids"]:
        e = legacy["points"][pid]
        if e["units"]:
            units.update(e["units"])
        else:
            why[e["reason"]] = why.get(e["reason"], 0) + 1
    return sorted(units), why


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshot-state")
    ap.add_argument("--legacy-map")
    ap.add_argument("--units-file", help="freeze these ledger units (one per line) instead of a snapshot's")
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--today", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--download-workers", type=int, default=4)
    a = ap.parse_args(argv)
    if a.units_file:
        units = sorted(x.strip() for x in Path(a.units_file).read_text().split() if x.strip())
        state, no_unit = {"snapshot_id": None, "point_ids": []}, {}
    elif a.snapshot_state and a.legacy_map:
        state = json.loads(Path(a.snapshot_state).read_text())
        units, no_unit = units_of(state, json.loads(Path(a.legacy_map).read_text()))
    else:
        ap.error("name --units-file, or --snapshot-state with --legacy-map")
    lg = ldg.load(Path(a.ledger))
    real_pull = api.pull
    drift = {"snapshot_id": state["snapshot_id"], "snapshot_points": len(state["point_ids"]),
             "points_with_no_unit": no_unit, "units": len(units)}

    def pull(fetch, *, today, window_days):
        p = real_pull(fetch, today=today, window_days=window_days)
        later = set(engines.unknown_labels(p.rows))
        dates = contract.run_dates(p.rows)
        differs = []
        for r in p.rows:
            try:
                lg.place(r, dates)
            except ldg.RowDiffers:
                differs.append(str(r["id"]))
        drift.update(rows_returned=len(p.rows), frameworks_dropped=sorted(later),
                     rows_of_those_frameworks=sum(r["framework"] in later for r in p.rows),
                     rows_that_differ_from_the_ledger=sorted(differs))
        p.rows = [r for r in p.rows if r["framework"] not in later and str(r["id"]) not in set(differs)]
        return p

    api.pull = pull
    try:
        rc = cli.cmd_pull(types.SimpleNamespace(
            out=a.out, today=a.today, window_days=180, cache=a.cache, prior=None, only=units,
            download_workers=a.download_workers, ledger=a.ledger))
    finally:
        api.pull = real_pull
    Path(a.out).mkdir(parents=True, exist_ok=True)
    manifest = json.loads((Path(a.out) / "manifest.json").read_text()) if rc == 0 else {}
    held = {p["point_id"] for p in manifest.get("points", [])}
    drift.update(units_frozen=len(held), units_not_frozen=sorted(set(units) - held))
    (Path(a.out) / "drift.json").write_text(json.dumps(drift, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in drift.items() if not isinstance(v, list)}, sort_keys=True))
    return rc


if __name__ == "__main__":
    sys.exit(main())
