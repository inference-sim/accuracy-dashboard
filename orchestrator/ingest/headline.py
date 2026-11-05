"""The headline accuracy and coverage (design §11.3, COV-7, COV-11).

The headline covers every graded point, G1 to G4. Beside it: each grade's share of the graded
points and each grade's own accuracy, and every figure with the number of points it covers. A
figure over fewer points than MIN_POINTS is published as "too few points", never as a number.

Coverage is graded points over all points (anchor units), split by engine, engine release,
chip and grade, with the share in each grade, and the number of source records the ledger left
out (COV-7).
"""
from __future__ import annotations

from collections import Counter

import grade as gr

# The smallest number of points a published figure may cover (the summary schema's minimum).
MIN_POINTS = 10
TOO_FEW = "too few points"


def _mape(points: list[dict], metric: str):
    errs = [abs(p[f"pred_{metric}_us"] - p[f"meas_{metric}_us"]) / p[f"meas_{metric}_us"] * 100
            for p in points if p.get(f"meas_{metric}_us") and p.get(f"pred_{metric}_us") is not None]
    return errs


def figure(points: list[dict], metric: str) -> dict:
    """One figure, with the count it covers. Under MIN_POINTS it is "too few points"."""
    errs = _mape(points, metric)
    n = len(errs)
    if n < MIN_POINTS:
        return {"mape": TOO_FEW, "n": n}
    return {"mape": sum(errs) / n, "n": n}


def share(count: int, graded: int):
    """A grade's share of the graded points: "too few points" when the grade holds fewer than
    MIN_POINTS points (its count stays beside it)."""
    if count < MIN_POINTS:
        return TOO_FEW
    return count / graded


def headline(points: list[dict]) -> dict:
    """points: every point, scored or not, each with its "grade" and, when graded, its measured
    and predicted microseconds (meas_ttft_us, pred_ttft_us, meas_tpot_us, pred_tpot_us)."""
    by = Counter(p["grade"] for p in points)
    unknown = set(by) - set(gr.GRADES)
    if unknown:
        raise ValueError(f"grades {sorted(unknown)} are not {gr.GRADES}")
    graded = [p for p in points if p["grade"] in gr.GRADED]
    n = len(graded)
    out = {"points": len(points), "graded": n, "not_scored": by.get(gr.G5, 0),
           "headline": {m: figure(graded, m) for m in ("ttft", "tpot")}, "grades": {}}
    for g in gr.GRADED:
        pts = [p for p in graded if p["grade"] == g]
        out["grades"][g] = {"points": len(pts), "share": share(len(pts), n),
                            **{m: figure(pts, m) for m in ("ttft", "tpot")}}
    if sum(v["points"] for v in out["grades"].values()) + out["not_scored"] != len(points):
        raise ValueError("the grade counts do not sum to the total (COV-1)")
    return out


def coverage(points: list[dict], left_out_records: int) -> dict:
    """COV-7: graded points over all points, by engine, engine release, chip and grade."""
    def split(key):
        rows: dict = {}
        for p in points:
            k = key(p)
            r = rows.setdefault(k, Counter())
            r[p["grade"]] += 1
        return {k: {"points": sum(c.values()), "graded": sum(c[g] for g in gr.GRADED),
                    "grades": {g: c.get(g, 0) for g in gr.GRADES}} for k, c in sorted(rows.items())}
    total = len(points)
    graded = sum(1 for p in points if p["grade"] in gr.GRADED)
    return {"points": total, "graded": graded, "share_graded": graded / total if total else None,
            "left_out_records": left_out_records,
            "by_engine": split(lambda p: p["framework"]),
            "by_engine_release": split(lambda p: f"{p['framework']} {p.get('release') or 'nightly or custom'}"),
            "by_chip": split(lambda p: p["hardware"]),
            "by_grade": {g: sum(1 for p in points if p["grade"] == g) for g in gr.GRADES}}


def check(summary_headline: dict) -> list[str]:
    """The publish check of COV-11 for the headline block: every figure carries its count, and one
    under MIN_POINTS is "too few points". check_document walks the whole summary."""
    out = []

    def fig(where, f):
        if "n" not in f:
            out.append(f"{where}: a figure without its point count")
        elif f["n"] < MIN_POINTS and f["mape"] != TOO_FEW:
            out.append(f"{where}: a figure over {f['n']} points, under the minimum {MIN_POINTS}")
    for m, f in summary_headline["headline"].items():
        fig(f"headline.{m}", f)
    for g, row in summary_headline["grades"].items():
        for m in ("ttft", "tpot"):
            fig(f"grades.{g}.{m}", row[m])
    return out


def check_document(doc) -> list[str]:
    """COV-11 over a whole summary, at every depth: a dict that states a count `n` (a headline
    figure, or the mape and shape of a metric block at any level of the matrix and its totals)
    holds a number only when n >= MIN_POINTS, and a grade row (`points` and `share`) shows a
    share only when it holds MIN_POINTS points."""
    out = []

    def walk(x, path):
        if isinstance(x, dict):
            n = x.get("n")
            if isinstance(n, int) and not isinstance(n, bool) and n < MIN_POINTS:
                for k in ("mape", "ttft", "tpot"):
                    v = x.get(k)
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        out.append(f"{path}.{k}: a figure over {n} points, under the minimum {MIN_POINTS}")
            c = x.get("points")
            if isinstance(c, int) and "share" in x and c < MIN_POINTS and x["share"] != TOO_FEW:
                out.append(f"{path}.share: the share of a grade of {c} points, under the minimum {MIN_POINTS}")
            for k, v in x.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, f"{path}[{i}]")
    walk(doc, "")
    return out
