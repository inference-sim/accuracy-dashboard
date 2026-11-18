#!/usr/bin/env python3
"""Stop a publish when too many of a night's points are faults and not results.

    night_health.py SUMMARY.json [--limit 0.05]

A point is a result when it is graded (G1 to G4) or a named G5 (a reason on design 11.4's list is a fact about the point).
It is a fault when the harness failed it: the simulator refused a scenario the harness wrote and no classifier turned the
refusal into a named G5 (an unclassified blis_refused), or the run hit a runner limit. The summary lists those in `failed`.
When more than LIMIT of the night's points are faults the publish stops (exit 1), because a release scored mostly by a
harness that cannot place its points is not a measure of BLIS. A named G5 never counts against the night.
"""
from __future__ import annotations

import json
import sys

LIMIT = 0.05


def fault_share(summary: dict) -> tuple[int, int, float]:
    """(points failed, points, their share) of a v3 summary."""
    cov = summary.get("coverage") or {}
    points = cov.get("points")
    failed = len(summary.get("failed") or [])
    if not isinstance(points, int) or points <= 0:
        raise ValueError("the summary states no point count (coverage.points)")
    return failed, points, failed / points


def check(summary: dict, limit: float = LIMIT) -> str | None:
    """None when the night is publishable, else the reason it is not."""
    failed, points, share = fault_share(summary)
    if share > limit:
        faults = sorted({x for f in summary.get("failed") or [] for x in f.get("faults", [])})
        return (f"{failed} of {points} points ({share:.1%}) failed, more than {limit:.0%}; the publish stops. "
                f"Faults: {', '.join(faults[:5])}{' ...' if len(faults) > 5 else ''}")
    return None


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    limit = LIMIT
    if "--limit" in args:
        i = args.index("--limit")
        limit = float(args[i + 1])
        del args[i:i + 2]
    why = check(json.load(open(args[0])), limit)
    if why:
        print(f"night_health: {why}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
