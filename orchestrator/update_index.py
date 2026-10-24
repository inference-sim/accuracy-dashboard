#!/usr/bin/env python3
"""Maintain data/index.json — the manifest of published snapshots the UI's run-picker reads
(static HTTP can't list a directory, so we publish an explicit index). Sorted newest-first.

Two independent retentions (Discussion #15, "Retention: two independent limits"), kept apart
here because collapsing them into one knob (what the old 30-day --retention-days did) is exactly
the bug #15 calls out:

  * API-release snapshots (v2, provenance.ingest == "api"): keep the newest `--keep-api` by
    snapshot date, prune the rest. Count-based, not a time window: BLIS releases are bursty
    (v0.10→v0.12 in 8 days, then a ~4-month gap), so "the last 5 releases" always gives 5
    comparison points where a day window could hold none.
  * Legacy dump snapshots (v1, no provenance.ingest): NEVER pruned. History (the 2026-09-28
    dump as it was) can't be recreated, so dropping them is irreversible (#15, "Existing
    committed (dump-based) snapshots": keep, but fence off).

The 180-day InferenceX *data* window is the other limit; it lives in the pull/store (api.py's
in_window), not here. This file only bounds how many *snapshots* the picker holds.

Each entry carries its `ingest` ("api" or "db-dump") so the picker can label a run · API / · dump
and refuse to diff across ingests. Run in CI after a snapshot is committed, before push.

Usage: update_index.py --data-dir data [--keep-api 5 --today 2026-10-17]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys

# A snapshot whose summary.json says this came from the live API ingest; anything else (a v1
# snapshot with no such field) is a legacy database-dump snapshot.
API_INGEST = "api"
DUMP_INGEST = "db-dump"


def _classify(doc: dict) -> str:
    """Which ingest a snapshot came from, read from its own summary.json."""
    return API_INGEST if doc.get("provenance", {}).get("ingest") == API_INGEST else DUMP_INGEST


def _entry(doc: dict, snap_id: str) -> dict:
    prov = doc.get("provenance", {})
    gt = prov.get("ground_truth", {})
    return {
        "snapshot_id": doc.get("snapshot_id", snap_id),
        "generated_at": doc.get("generated_at"),
        "blis_release": prov.get("blis", {}).get("release"),
        "ix_release": gt.get("release_tag"),
        "ingest": _classify(doc),
        "path": f"snapshots/{snap_id}/summary.json",
    }


def build_index(data_dir: str, keep_api: int) -> list[dict]:
    """Read every snapshot, prune API snapshots past the last `keep_api`, keep every dump one,
    and return the retained entries newest-first. Pruning deletes the snapshot directory.
    Count-based, so no clock is needed: ranking is by snapshot_id, which leads with the date."""
    snaps_dir = os.path.join(data_dir, "snapshots")
    if not os.path.isdir(snaps_dir):
        return []
    api_entries: list[tuple[str, dict]] = []    # (snap_id, entry) for ranking before prune
    kept: list[dict] = []
    for snap_id in sorted(os.listdir(snaps_dir)):
        path = os.path.join(snaps_dir, snap_id, "summary.json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path) as fh:
                doc = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        entry = _entry(doc, snap_id)
        if entry["ingest"] == API_INGEST:
            api_entries.append((snap_id, entry))
        else:
            kept.append(entry)   # dump snapshots are never pruned
    # Count-based prune of API snapshots: keep the newest `keep_api` (snapshot_ids lead with the
    # date, so lexical order is chronological), delete the older ones' directories.
    api_entries.sort(key=lambda se: se[0], reverse=True)
    for snap_id, entry in api_entries[keep_api:]:
        shutil.rmtree(os.path.join(snaps_dir, snap_id), ignore_errors=True)
    kept.extend(entry for _, entry in api_entries[:keep_api])
    kept.sort(key=lambda e: e["snapshot_id"], reverse=True)   # newest first
    return kept


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--keep-api", type=int, default=5,
                    help="how many API-release snapshots to keep (count-based, #15's last-5 rule)")
    # Accepted for backward compatibility with callers that pass them (the old dump pipeline's
    # --retention-days, and run_night's --today); the new index is count-based, so neither a day
    # window nor the clock drives pruning. Ignored.
    ap.add_argument("--retention-days", type=int, default=None, help=argparse.SUPPRESS)
    ap.add_argument("--today", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    entries = build_index(args.data_dir, args.keep_api)

    index = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "keep_api": args.keep_api,
        "latest": entries[0]["snapshot_id"] if entries else None,
        "runs": entries,
    }
    out = os.path.join(args.data_dir, "index.json")
    with open(out, "w") as fh:
        json.dump(index, fh, indent=2)
        fh.write("\n")
    n_api = sum(1 for e in entries if e["ingest"] == API_INGEST)
    print(f"index.json: {len(entries)} run(s) ({n_api} API, {len(entries) - n_api} dump), "
          f"latest={index['latest']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
