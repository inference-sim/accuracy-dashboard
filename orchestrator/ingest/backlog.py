"""The blocker backlog (design §11.6): everything that lowers coverage or grade, ranked by how
many points it blocks or demotes. Engine and substrate work is chosen from the top of it.

An entry is one subject: a G5 reason (a field, a model or chip, a router, an engine), or a
substitution that holds a point below G1. The summary publishes the ten most common (top).
"""
from __future__ import annotations

from collections import Counter


def top(points: list[dict], n: int = 10) -> list[tuple[str, int]]:
    """The n most common reasons a point is not G1, over every engine: each G5 reason and each
    substitution, counted once per point. Ties are broken by the reason's text, so the list does
    not depend on the order of the points."""
    c = Counter()
    for p in points:
        if p["grade"] == "G1":
            continue
        if p["grade"] == "G5":
            for r in {(r["code"], r.get("subject", "")) for r in p.get("g5_reasons") or []}:
                c[f"G5 {r[0]}" + (f": {r[1]}" if r[1] else "")] += 1
        else:
            for s in {(s["kind"], s["subject"]) for s in p.get("substitutions") or []}:
                c[f"{s[0]}: {s[1]}"] += 1
    return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
