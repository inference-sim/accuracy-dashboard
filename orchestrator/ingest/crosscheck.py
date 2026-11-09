#!/usr/bin/env python3
"""Cross-check a contract directory's measured values against InferenceX API data.

The extractor copies each point's measured mean TTFT / TPOT from its InferenceX API row
(`metrics.mean_ttft`, `metrics.mean_tpot`, in seconds) into points.csv (microseconds). This
checks every scored point against API rows you provide -- your own download, or a frozen pull
-- matching them to points through the ledger's unit list (a point is one unit, and its
measured value is the mean over the unit's measurements), and reports any value that
differs and any scored point the rows don't contain.

  crosscheck.py --contract DIR --ledger LEDGER --rows ROWS.json     a JSON list of /benchmarks rows
  crosscheck.py --contract DIR --ledger LEDGER --pull PULL          a frozen pull (PULL/manifest.json)
  crosscheck.py --contract DIR --ledger LEDGER --api --window-days N [--today YYYY-MM-DD]

Exits 1 on any mismatch.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import api  # noqa: E402
import contract as c  # noqa: E402
import ledger as ldg  # noqa: E402
import pull as pl  # noqa: E402
import score as sc  # noqa: E402

FIELDS = (("meas_ttft_us", "mean_ttft"), ("meas_tpot_us", "mean_tpot"))


def check(points_csv: Path, rows: list[dict], lg, tol_us: float = 0.01) -> tuple[int, list[str]]:
    by_id = {p.point_id: p for p in pl.place(rows, lg).points}
    problems = []
    n = 0
    for p in csv.DictReader(points_csv.open()):
        pt = by_id.get(p["point_id"])
        if pt is None:
            problems.append(f"{p['point_id'][:12]}: scored, but not in the API rows given")
            continue
        for col, key in FIELDS:
            n += 1
            api_us = sc.measured({"row": pt.row, "measurements": pt.measurements})[key] * 1e6
            if abs(float(p[col]) - api_us) > tol_us:
                problems.append(f"{p['point_id'][:12]} {col}: contract {p[col]}, API {api_us:.3f}")
    return n, problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--contract", required=True)
    ap.add_argument("--ledger", required=True, help="blis-substrate's catalog/ledger")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--rows", help="a JSON list of InferenceX /benchmarks rows")
    src.add_argument("--pull", help="a frozen pull directory")
    src.add_argument("--api", action="store_true", help="fetch the API now")
    ap.add_argument("--window-days", type=int, default=180)
    ap.add_argument("--today")
    a = ap.parse_args(argv)
    if a.rows:
        rows = json.loads(Path(a.rows).read_text())
    elif a.pull:
        rows = [p["row"] for p in json.loads((Path(a.pull) / "manifest.json").read_text())["points"]]
    else:
        today = date.fromisoformat(a.today) if a.today else date.today()
        rows = api.pull(api.http_fetch, today=today, window_days=a.window_days).rows
    n, problems = check(Path(a.contract) / c.POINTS_CSV, rows, ldg.load(Path(a.ledger)))
    for p in problems:
        print(p, file=sys.stderr)
    print(f"{n - sum('API ' in p for p in problems)}/{n} measured values match the API rows; "
          f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
