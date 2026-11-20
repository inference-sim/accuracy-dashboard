"""The aggregates-only guarantee (design §10.2, COV-13).

A secret-holding job prints, uploads and comments aggregates over at least MIN_POINTS role keys and nothing
about a single unit. This guard is the last step before any text leaves the process:

  * `check_report` refuses a report that holds a field outside the aggregate schema, an aggregate over fewer
    than MIN_POINTS role keys, or any text that names a unit, a role key or the seed;
  * `scrub` removes the same text from a message (an error, a log line) so a failure cannot leak what a
    report could not.

The withheld material is every unit identifier (and its first 16 characters), every role key (its hash and its
canonical JSON), and the seed.
"""
from __future__ import annotations

import json

MIN_POINTS = 10
WITHHELD = "[withheld]"
LANE_KEYS = {"name", "lane", "member_lanes", "merged", "target", "role_keys", "results", "unjudged", "passes"}
LANE_ATTRS = {"engine", "modelled_commit", "chip", "model", "layout"}
RESULT_KEYS = {"criterion", "metric", "null_difference_at_least", "role_keys", "difference", "upper_95",
               "p_value", "rejected"}
UNJUDGED_KEYS = {"criterion", "metric", "reason"}
TOP_KEYS = {"kind", "partition_version", "preregistration", "preregistration_sha256", "base", "candidate",
            "harness", "evaluation", "budget", "resamples", "alpha", "min_points", "verdict", "lanes",
            "unjudged_lanes", "not_blind", "target_unjudged", "notes"}
NOT_BLIND_KEYS = {"note", "lanes", "unjudged_lanes"}


class LeakError(Exception):
    pass


class Guard:
    def __init__(self, withheld: set[str]):
        w = {s for s in withheld if s}
        w |= {s[:16] for s in withheld if len(s) >= 32}
        self._words = sorted(w, key=len, reverse=True)

    def scrub(self, text: str) -> str:
        for w in self._words:
            text = text.replace(w, WITHHELD)
        return text

    def leaks(self, text: str) -> bool:
        return any(w in text for w in self._words)

    def check_report(self, report: dict) -> None:
        """Raise LeakError unless `report` is aggregates only. The error says what rule failed, never the text."""
        text = json.dumps(report, sort_keys=True)
        if self.leaks(text):
            raise LeakError("the report names a unit, a role key or the seed")
        if set(report) - TOP_KEYS:
            raise LeakError("the report has a field outside the aggregate schema")
        mp = report.get("min_points", MIN_POINTS)
        if mp < MIN_POINTS:
            raise LeakError(f"the report's min_points is below {MIN_POINTS}")
        nb = report.get("not_blind", {})
        if set(nb) - NOT_BLIND_KEYS:
            raise LeakError("the not_blind section has a field outside the aggregate schema")
        for t in report.get("target_unjudged", []):
            if set(t) - {"target_lane", "target_lane_in", "criterion", "metric", "reason"}:
                raise LeakError("a target_unjudged entry has a field outside the schema")
        for lane in list(report.get("lanes", [])) + list(nb.get("lanes", [])):
            if set(lane) - LANE_KEYS or not set(lane.get("lane", {})) <= LANE_ATTRS:
                raise LeakError("a lane has a field outside the aggregate schema")
            if lane["role_keys"] < MIN_POINTS:
                raise LeakError(f"a lane aggregates fewer than {MIN_POINTS} role keys")
            for r in lane["results"]:
                if set(r) - RESULT_KEYS:
                    raise LeakError("a result has a field outside the aggregate schema")
                if r["role_keys"] < MIN_POINTS:
                    raise LeakError(f"a result aggregates fewer than {MIN_POINTS} role keys")
            for u in lane["unjudged"]:
                if set(u) != UNJUDGED_KEYS:
                    raise LeakError("an unjudged entry has a field outside the schema")
