#!/usr/bin/env python3
"""Freeze the recorded runs of InferenceX rows that the pinned dump does not hold, as the substrate's ledger holds them.

The baseline's pull (freeze.py) is the 1734 points of the ledger's source revision; this script never touches it. Rows InferenceX
published after that dump are pinned by blis-substrate (catalog/ledger/sources.yaml, the `inferencex` source's supplements: record id
and content SHA-256), and the substrate's ingest makes their units (catalog/ledger/units/inferencex.jsonl.gz). The dashboard makes no
unit, no role key and no ledger report (design 2.2: the substrate owns turning each source's records into ledger units), and commits
no third-party record (X12). It takes:

  --ledger DIR    the substrate's catalog/ledger at the pinned commit (pins.env, BLIS_SUBSTRATE_COMMIT)
  --records FILE  the records of a run, written by `go run ./ledger/cmd/ledger supplement-records -out FILE catalog/ledger`, which
                  refuses any record whose content differs from its pin. Never committed.

and freezes the rows' artifacts into a pull of its own:

    freeze_rows.py --ledger DIR --records FILE --out PULL --cache CACHE [--units-out FILE] [--pins pins.env] [--allow-unpinned]

Each row must be placed by a unit of the substrate's list; a row the list does not hold is refused, never given a unit here. Scoring
reads the published anchor lists only (COV-2): a unit with no role until the seed and lists are published is not an anchor.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ingest"))
import api  # noqa: E402
import cli  # noqa: E402
import contract  # noqa: E402
import ledger as ldg  # noqa: E402

PIN_KEY = "BLIS_SUBSTRATE_COMMIT"


class FreezeError(ValueError):
    pass


def read_pin(path: Path) -> str:
    """The blis-substrate commit the pins file names, or '' while it is a placeholder."""
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line.startswith(PIN_KEY + "="):
            return line.split("=", 1)[1].strip()
    raise FreezeError(f"{path}: no {PIN_KEY}=")


def check_pin(ledger_dir: Path, pins: Path, allow_unpinned: bool) -> str:
    """Refuse a ledger checkout that is not the pinned commit; an empty pin is refused unless allowed (a scratch build)."""
    pin = read_pin(pins)
    if not pin:
        if allow_unpinned:
            return ""
        raise FreezeError(f"{pins} holds no {PIN_KEY} yet: the substrate commit is not pinned (--allow-unpinned only for a scratch build)")
    top = Path(ledger_dir).resolve()
    got = subprocess.run(["git", "-C", str(top), "rev-parse", "HEAD"], capture_output=True, text=True)
    if got.returncode != 0 or got.stdout.strip() != pin:
        raise FreezeError(f"the ledger checkout is at {got.stdout.strip() or 'no commit'}, not the pinned {pin}")
    return pin


def place_all(lg: ldg.Ledger, rows: list[dict]) -> list[str]:
    """The unit id of each row, from the substrate's unit list. A row it does not hold, or whose identity the list gives another
    hash, is refused; two rows in one unit are one point."""
    dates = contract.run_dates(rows)
    ids: dict[str, str] = {}
    for r in rows:
        p = lg.place(r, dates)
        if p is None:
            raise FreezeError(f"row {r['id']}: the substrate's unit list holds no unit for it; pin it in catalog/ledger/sources.yaml")
        uid = p.unit.unit_id
        if uid in ids and ids[uid] != str(r["id"]):
            raise FreezeError(f"rows {ids[uid]} and {r['id']} are one unit")
        ids[uid] = str(r["id"])
    return sorted(ids)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", required=True, help="the substrate's catalog/ledger directory")
    ap.add_argument("--records", required=True, help="the verified records of the run (supplement-records output; not committed)")
    ap.add_argument("--out", required=True, help="the new pull directory (never the baseline's)")
    ap.add_argument("--cache", required=True)
    ap.add_argument("--units-out")
    ap.add_argument("--pins", default=str(HERE.parent.parent / "docs" / "m2" / "h200-v033" / "pins.env"))
    ap.add_argument("--allow-unpinned", action="store_true")
    ap.add_argument("--download-workers", type=int, default=4)
    a = ap.parse_args(argv)
    ledger_dir = Path(a.ledger)
    check_pin(ledger_dir, Path(a.pins), a.allow_unpinned)
    rows = sorted(json.loads(Path(a.records).read_text()), key=lambda r: int(r["id"]))
    lg = ldg.load(ledger_dir)
    units = place_all(lg, rows)
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
            download_workers=a.download_workers, ledger=str(ledger_dir)))
    finally:
        api.pull = real
    if rc == 0:
        m = json.loads((Path(a.out) / "manifest.json").read_text())
        print(json.dumps({"points": len(m["points"]), "rows": len(rows), "units": len(units)}, sort_keys=True))
    return rc


if __name__ == "__main__":
    sys.exit(main())
