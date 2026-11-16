"""Coverage and grades by source, then by engine release, chip and model (COV-7, blis-design#14).

A second source is a dimension of the one dashboard, not a second dashboard: InferenceX and configiq points are
graded by the same bands, ceilings and reasons, and each source's points are broken down the same way. A
provisional point (configiq's launcher-consistent rows, scored with named substitutions and capped at G3) is counted
in its own band: it is never in `graded`, the headline coverage, or the headline accuracy (COV-11).

Input: one record per point, each {"source", "engine_release", "chip", "model", "grade", "provisional",
"failed", "g5_reason"}. A failed point (a runner limit, CONTRACT.md) counts in points and failed only. grade is G1-G5 (a provisional point's capped grade, or None until it is simulated); g5_reason is
{"code", ...} on a G5 point. Output: the summary's `coverage.by_source` (schemas/summary.v4.json#/definitions/
sourceCoverage), whose rows sum to the totals.
"""
from __future__ import annotations

GRADES = ("G1", "G2", "G3", "G4", "G5")
GRADED = GRADES[:4]
FACETS = (("by_engine_release", "engine_release"), ("by_chip", "chip"), ("by_model", "model"))


class BySourceError(ValueError):
    """A point record the breakdown cannot place, or a breakdown that does not sum to its totals."""


def _row() -> dict:
    return {"points": 0, "graded": 0, "provisional": 0, "not_scored": 0, "failed": 0, "grades": {g: 0 for g in GRADES},
            "provisional_grades": {g: 0 for g in GRADED}}


def _add(row: dict, p: dict) -> None:
    row["points"] += 1
    g = p.get("grade")
    if p.get("failed"):
        row["failed"] += 1
        return
    if p.get("provisional"):
        row["provisional"] += 1
        if g is not None:
            if g not in GRADED or GRADES.index(g) < GRADES.index("G3"):
                raise BySourceError(f"provisional point {p.get('point_id')}: grade {g}, but the band is capped at G3")
            row["provisional_grades"][g] += 1
        return
    if g == "G5":
        row["not_scored"] += 1
        row["grades"]["G5"] += 1
    elif g in GRADED:
        row["graded"] += 1
        row["grades"][g] += 1
    else:
        raise BySourceError(f"point {p.get('point_id')}: grade {g!r} is not G1-G5 and the point is not provisional")


def by_source(points: list[dict]) -> dict:
    """The breakdown: {source: row + {"g5_reasons", "by_engine_release", "by_chip", "by_model"}}, each facet a
    {value: row}. Keys are sorted, so the output does not depend on input order."""
    out: dict = {}
    for p in points:
        for k in ("source", "engine_release", "chip", "model"):
            if not isinstance(p.get(k), str) or not p[k]:
                raise BySourceError(f"point {p.get('point_id')}: no {k}")
        src = out.setdefault(p["source"], {**_row(), "g5_reasons": {},
                                           **{f: {} for f, _ in FACETS}})
        _add(src, p)
        if p.get("grade") == "G5" and not p.get("provisional"):
            code = (p.get("g5_reason") or {}).get("code")
            if not code:
                raise BySourceError(f"G5 point {p.get('point_id')}: no reason")
            src["g5_reasons"][code] = src["g5_reasons"].get(code, 0) + 1
        for facet, key in FACETS:
            _add(src[facet].setdefault(p[key], _row()), p)
    for src in out.values():
        src["g5_reasons"] = dict(sorted(src["g5_reasons"].items()))
        for facet, _ in FACETS:
            src[facet] = dict(sorted(src[facet].items()))
    return dict(sorted(out.items()))


def check(breakdown: dict, totals: dict) -> list[str]:
    """Problems with a breakdown against the summary's headline coverage totals ({"points", "graded",
    "not_scored", "failed"}): the sources must sum to the totals, every facet to its source, and no provisional point may be
    counted as graded (COV-7, COV-11)."""
    problems = []
    for k in ("points", "graded", "not_scored", "failed"):
        got = sum(s[k] for s in breakdown.values())
        want = totals[k] if k != "points" else totals[k] + sum(s["provisional"] for s in breakdown.values())
        if got != want:
            problems.append(f"by_source {k} sums to {got}, the totals give {want}")
    for name, s in breakdown.items():
        if s["points"] != s["graded"] + s["not_scored"] + s["failed"] + s["provisional"]:
            problems.append(f"{name}: points {s['points']} != graded + not_scored + failed + provisional")
        if s["graded"] != sum(s["grades"][g] for g in GRADED):
            problems.append(f"{name}: graded {s['graded']} != its G1-G4 counts")
        for facet, _ in FACETS:
            for k in ("points", "graded", "provisional", "not_scored", "failed"):
                got = sum(r[k] for r in s[facet].values())
                if got != s[k]:
                    problems.append(f"{name}.{facet}: {k} sums to {got}, the source has {s[k]}")
    return problems
