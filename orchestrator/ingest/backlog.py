"""The blocker backlog (design §11.6, COV-7): per engine, everything that lowers coverage or
grade, ranked by how many points it blocks or demotes. Engine and substrate work is chosen from
the top of this list.

An entry is one subject: a G5 reason (a field, a model or chip, a router, an engine), or a
substitution that holds a point below G1. "blocks" counts the G5 points that carry it;
"alone" counts those whose only G5 reason it is, so fixing it alone would grade them;
"demotes" counts the graded points it holds below G1.

Until M2 the backlog covers fields and coefficients only (release plan §3.3); surface items
join as each surface list is built.
"""
from __future__ import annotations

from collections import Counter, defaultdict

# One unmeasured quantity can reach a point under two names. The send gap the replay assumes between a completion and the next send
# IS the registry's host_completion coefficient (777 us, method assumed): the point names it as a client difference (design COV-12)
# and, because the coefficient is not measured, as a coefficient_method. Measuring it clears both, so the backlog counts the
# quantity once, under its canonical cause. Each entry maps a (kind, subject) that is an alias to the (kind, subject-name) of its
# canonical cause: the canonical subject is "<set>/<name>", matched on its name.
SAME_CAUSE = {("client_difference", "send_gap"): ("coefficient_method", "host_completion")}


def causes(subs: list[dict]) -> list[tuple[str, str]]:
    """The (kind, subject) of each substitution of one point, an alias dropped when its canonical cause is also named on the point,
    so the same unmeasured quantity is counted once."""
    pairs = [(s["kind"], s["subject"]) for s in subs]
    named = {(k, subj.rsplit("/", 1)[-1]) for k, subj in pairs}
    return [(k, subj) for k, subj in pairs if SAME_CAUSE.get((k, subj)) not in named]


def build(points: list[dict]) -> dict:
    """points: each with "framework", "grade", "g5_reasons" (every G5 reason found, not only the
    first), and "substitutions"."""
    out = defaultdict(lambda: defaultdict(lambda: {"blocks": 0, "alone": 0, "demotes": 0}))
    for p in points:
        eng = p["framework"]
        if p["grade"] == "G5":
            reasons = {(r["code"], r.get("subject", "")) for r in p.get("g5_reasons") or []}
            for code, subject in reasons:
                e = out[eng][f"{code}:{subject}" if subject else code]
                e["blocks"] += 1
                if len(reasons) == 1:
                    e["alone"] += 1
        else:
            for kind, subject in causes(p.get("substitutions") or []):
                out[eng][f"{kind}:{subject}"]["demotes"] += 1
    ranked = {}
    for eng, entries in sorted(out.items()):
        ranked[eng] = [{"entry": k, **v} for k, v in sorted(
            entries.items(), key=lambda kv: (-kv[1]["alone"], -kv[1]["blocks"], -kv[1]["demotes"], kv[0]))]
    return ranked


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
            for s in set(causes(p.get("substitutions") or [])):
                c[f"{s[0]}: {s[1]}"] += 1
    return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
