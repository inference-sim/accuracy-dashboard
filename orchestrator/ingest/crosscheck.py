#!/usr/bin/env python3
"""Cross-check a contract directory's measured values against InferenceX API data.

The extractor copies each point's measured mean TTFT / TPOT from its InferenceX API row
(`metrics.mean_ttft`, `metrics.mean_tpot`, in seconds) into points.csv (microseconds). This
checks every scored point against API rows you provide -- your own download, or a frozen pull
-- matching them by point id (contract.point_id of the row's identity), and reports any value
that differs, any scored point the rows don't contain, and any row matched twice.

  crosscheck.py --contract DIR --rows ROWS.json     a JSON list of /benchmarks rows
  crosscheck.py --contract DIR --pull PULL          a frozen pull (PULL/manifest.json)
  crosscheck.py --contract DIR --api --window-days N [--today YYYY-MM-DD]   fetch the API now

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
import pull as pl  # noqa: E402

FIELDS = (("meas_ttft_us", "mean_ttft"), ("meas_tpot_us", "mean_tpot"))


def check(points_csv: Path, rows: list[dict], tol_us: float = 0.01) -> tuple[int, list[str]]:
    by_id: dict[str, dict] = {}
    problems = []
    for r in rows:
        pid = c.point_id(pl.identity(r))
        if pid in by_id:
            problems.append(f"{pid[:12]}: two API rows have this point's identity")
        by_id[pid] = r
    n = 0
    for p in csv.DictReader(points_csv.open()):
        row = by_id.get(p["point_id"])
        if row is None:
            problems.append(f"{p['point_id'][:12]}: scored, but not in the API rows given")
            continue
        for col, key in FIELDS:
            n += 1
            api_us = float(row["metrics"][key]) * 1e6
            if abs(float(p[col]) - api_us) > tol_us:
                problems.append(f"{p['point_id'][:12]} {col}: contract {p[col]}, API {api_us:.3f}")
    return n, problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--contract", required=True)
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
    n, problems = check(Path(a.contract) / c.POINTS_CSV, rows)
    for p in problems:
        print(p, file=sys.stderr)
    print(f"{n - sum('API ' in p for p in problems)}/{n} measured values match the API rows; "
          f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
