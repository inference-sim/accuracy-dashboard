#!/usr/bin/env python3
"""Tell a person what a night's summary holds that deserves a look, without stopping the night.

    night_notes.py SUMMARY.json

A named refusal (G5 blis_refused: the simulator refused a scenario and said why) never stops a publish. This prints, for the
Actions run and its job summary, two things worth reading and never fails:
  * the refusal codes the nightly has not met before (summary.new_refusal_codes), and
  * a warning when the points the simulator refused that no classifier gave a more specific reason exceed
    assess.UNCLASSIFIED_WARN_SHARE of the night's points.
Real faults stop the night elsewhere (build_summary_v2.PublishRefused, night_health). Exit status is always 0.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingest"))
import assess  # noqa: E402


def refusal_share(summary: dict) -> tuple[int, int, float]:
    """(points whose reasons are the simulator's named refusal alone, points, share): a point with another reason beside it was
    classified by that reason and is not counted."""
    points = (summary.get("coverage") or {}).get("points") or 0
    n = sum(1 for p in summary.get("not_scored") or []
            if {r.get("code") for r in p.get("g5_reasons") or [p["g5_reason"]]} == {"blis_refused"})
    return n, points, (n / points if points else 0.0)


def notes(summary: dict, limit: float = assess.UNCLASSIFIED_WARN_SHARE) -> list[tuple[str, str]]:
    """[(level, text)]: level "warning" or "notice"."""
    out = []
    new = summary.get("new_refusal_codes") or []
    if new:
        out.append(("warning", f"the simulator gave {len(new)} refusal code(s) the nightly has not seen before: {', '.join(new)}. "
                               "The points are published as not scored with the simulator's message; read them (summary not_scored, "
                               "code blis_refused) and add the code to assess.KNOWN_REFUSAL_CODES or fix the cause."))
    n, points, share = refusal_share(summary)
    if points and share > limit:
        out.append(("warning", f"{n} of {points} points ({share:.2%}) were refused by the simulator with no more specific reason, more than "
                               f"{limit:.0%}. The night publishes; the refusals are G5 blis_refused in the summary."))
    elif n:
        out.append(("notice", f"{n} of {points} points ({share:.2%}) are named simulator refusals (G5 blis_refused)."))
    return out


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        lines = notes(json.loads(Path(args[0]).read_text()))
    except (OSError, ValueError, IndexError, KeyError) as e:
        lines = [("warning", f"night_notes could not read the summary ({e}); no note was made.")]
    for level, text in lines:
        print(f"::{level}::{text}")
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target and lines:
        with open(target, "a") as f:
            f.write("### Night notes\n\n" + "\n".join(f"- **{lv}**: {tx}" for lv, tx in lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
