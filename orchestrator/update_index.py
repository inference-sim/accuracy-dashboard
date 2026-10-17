#!/usr/bin/env python3
"""Maintain data/index.json — the manifest of published nightly snapshots the UI's run-picker
reads (static HTTP can't list a directory, so we publish an explicit index). Also prunes
snapshots older than the retention window so history stays bounded.

Each entry is the minimum the picker needs to label a run; the full data is in each snapshot's
own summary.json. Sorted newest-first. Run in CI after a snapshot is committed, before push.

Usage: update_index.py --data-dir data [--retention-days 30 --today 2026-10-17]
The snapshot_id is dated (YYYY-MM-DD_blis-..._ix-...), so retention is read from that prefix —
no clock needed in the normal case, but --today can pin it for reproducibility/tests.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys


def _snap_date(snapshot_id: str) -> dt.date | None:
    """The YYYY-MM-DD prefix of a snapshot_id, or None if it doesn't parse."""
    head = snapshot_id.split("_", 1)[0]
    try:
        return dt.date.fromisoformat(head)
    except ValueError:
        return None


def build_index(data_dir: str, retention_days: int, today: dt.date) -> list[dict]:
    snaps_dir = os.path.join(data_dir, "snapshots")
    if not os.path.isdir(snaps_dir):
        return []
    cutoff = today - dt.timedelta(days=retention_days)
    entries: list[dict] = []
    for snap_id in sorted(os.listdir(snaps_dir)):
        path = os.path.join(snaps_dir, snap_id, "summary.json")
        if not os.path.isfile(path):
            continue
        d = _snap_date(snap_id)
        if d is not None and d < cutoff:
            # Older than the retention window — prune the snapshot directory entirely.
            shutil.rmtree(os.path.join(snaps_dir, snap_id), ignore_errors=True)
            continue
        try:
            with open(path) as fh:
                doc = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        prov = doc.get("provenance", {})
        gt = prov.get("ground_truth", {})
        entries.append({
            "snapshot_id": doc.get("snapshot_id", snap_id),
            "generated_at": doc.get("generated_at"),
            "blis_release": prov.get("blis", {}).get("release"),
            "ix_release": gt.get("release_tag"),
            "path": f"snapshots/{snap_id}/summary.json",
        })
    # Newest first — by snapshot date then id (ids are date-prefixed, so lexical works).
    entries.sort(key=lambda e: e["snapshot_id"], reverse=True)
    return entries


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--retention-days", type=int, default=30)
    ap.add_argument("--today", default=None, help="YYYY-MM-DD; defaults to UTC today")
    args = ap.parse_args(argv)

    today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(dt.timezone.utc).date()
    entries = build_index(args.data_dir, args.retention_days, today)

    index = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "retention_days": args.retention_days,
        "latest": entries[0]["snapshot_id"] if entries else None,
        "runs": entries,
    }
    out = os.path.join(args.data_dir, "index.json")
    with open(out, "w") as fh:
        json.dump(index, fh, indent=2)
        fh.write("\n")
    print(f"index.json: {len(entries)} run(s), latest={index['latest']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
