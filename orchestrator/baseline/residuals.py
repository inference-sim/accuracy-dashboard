"""Systematic residuals of the scored points, on the TRAIN split only.

The signed error of a figure is predicted / measured - 1, in percent. A group's bias is the median of
its points' signed errors, with n and the spread (the interquartile range). The groups are the
facets of a point that an estimator could depend on: model, hardware, precision, concurrency band,
serving (aggregated or disaggregated), speculation method, and the regime a point is in (derived
from concurrency and the prompt length). Validation, test and prospective points are never read:
this is the analysis a model is tuned from (docs/m2/evaluation-protocol.md).

    residuals.py --dir CONTRACT [--splits FILE] [--min-n 5] [--top 10] [--out FILE]
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import compare as cmp  # noqa: E402

CONC_BANDS = ((1, 2, "1-2"), (3, 8, "3-8"), (9, 32, "9-32"), (33, 128, "33-128"), (129, 10 ** 9, ">128"))


def band(c: int) -> str:
    return next(name for lo, hi, name in CONC_BANDS if lo <= c <= hi)


def regime(p: dict) -> str:
    """A coarse regime: the queue is shallow (concurrency up to 8) or deep, and the prompt long
    (ISL over 4096) or short. Derived from the point's facets only."""
    depth = "shallow" if p["concurrency"] <= 8 else "deep"
    return f"{depth} queue, {'long' if (p.get('isl') or 0) > 4096 else 'short'} prompt"


def signed(pred: float, meas: float) -> float:
    return (pred / meas - 1.0) * 100.0


def _quartiles(xs: list[float]) -> tuple[float, float]:
    s = sorted(xs)
    n = len(s)
    return s[int(0.25 * (n - 1))], s[int(round(0.75 * (n - 1)))]


FACETS = {"model": lambda p: p["model"], "hardware": lambda p: p["hardware"], "precision": lambda p: p["precision"],
          "concurrency band": lambda p: band(p["concurrency"]), "serving": lambda p: p["serving"],
          "speculation": lambda p: p["spec"], "regime": regime}


def analyse(points: list[dict], min_n: int = 5) -> list[dict]:
    """Every (facet, value, metric) group of the train points with at least min_n points."""
    train = [p for p in points if p["status"] == "scored" and p["kind"] == "train"]
    out = []
    for facet, key in FACETS.items():
        groups = defaultdict(list)
        for p in train:
            groups[key(p)].append(p)
        for value, ps in sorted(groups.items()):
            if len(ps) < min_n:
                continue
            for metric in ("ttft", "tpot"):
                errs = [signed(p[f"pred_{metric}_us"], p[f"meas_{metric}_us"]) for p in ps
                        if p[f"meas_{metric}_us"] > 0 and p[f"pred_{metric}_us"] > 0]
                if len(errs) < min_n:
                    continue
                q1, q3 = _quartiles(errs)
                out.append({"facet": facet, "value": value, "metric": metric, "n": len(errs),
                            "median_signed_error_pct": median(errs), "iqr_pct": q3 - q1,
                            "series": len({p["series"] for p in ps})})
    return out


def top_biases(groups: list[dict], top: int = 10) -> list[dict]:
    """The largest systematic biases: by the size of the median signed error, ties by n."""
    return sorted(groups, key=lambda g: (-abs(g["median_signed_error_pct"]), -g["n"], g["facet"], g["value"]))[:top]


def markdown(groups: list[dict], top: list[dict], n_train: int, hypotheses: dict | None = None) -> str:
    L = ["# Residuals on the train split", "",
         f"Scored points on the train split: {n_train}. Signed error is predicted / measured - 1 in percent; a group is a "
         "facet value with at least five points and, for a metric, five measured values. Validation, test and prospective "
         "points are not read. These figures are the input to model development, not an evaluation.", "",
         "## The ten largest systematic biases", "",
         "| # | Facet | Group | Metric | n | Series | Median signed error % | IQR % | Hypothesis |", "|---|---|---|---|---|---|---|---|---|"]
    for i, g in enumerate(top, 1):
        h = (hypotheses or {}).get((g["facet"], g["value"], g["metric"]), "")
        L.append(f"| {i} | {g['facet']} | {g['value']} | {g['metric'].upper()} | {g['n']} | {g['series']} | "
                 f"{g['median_signed_error_pct']:+.1f} | {g['iqr_pct']:.1f} | {h} |")
    L += ["", "## All groups", "", "| Facet | Group | Metric | n | Series | Median signed error % | IQR % |", "|---|---|---|---|---|---|---|"]
    for g in sorted(groups, key=lambda g: (g["facet"], g["value"], g["metric"])):
        L.append(f"| {g['facet']} | {g['value']} | {g['metric'].upper()} | {g['n']} | {g['series']} | "
                 f"{g['median_signed_error_pct']:+.1f} | {g['iqr_pct']:.1f} |")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--splits")
    ap.add_argument("--min-n", type=int, default=5)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--hypotheses", help="JSON: 'facet|group|METRIC' to a one-line hypothesis")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    run = cmp.Run(a.dir, a.splits)
    pts = list(run.points.values())
    groups = analyse(pts, a.min_n)
    hyp = {}
    if a.hypotheses:
        import json
        for k, v in json.loads(Path(a.hypotheses).read_text()).items():
            f, g, m = k.split("|")
            hyp[(f, g, m.lower())] = v
    text = markdown(groups, top_biases(groups, a.top), sum(1 for p in pts if p["status"] == "scored" and p["kind"] == "train"), hyp)
    if a.out:
        Path(a.out).write_text(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
