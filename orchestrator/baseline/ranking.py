"""Ranking quality of predicted configurations (docs/m2/evaluation-protocol.md).

A configuration search asks which of several configurations serves a workload best. MAPE says how far
each prediction is from its measurement; it does not say whether the order of the configurations is
right. This module scores the order.

GROUP      the scored points of one (model, hardware, ISL, OSL): the configurations are the points of that
           group, which differ in concurrency, parallelism, engine, precision and speculation. A group
           needs at least MIN_CONFIGS points to have an order.
VALUE      one number per point, computed from TTFT and TPOT the same way for the measured and the
           predicted side:
             latency  L = TTFT + (OSL - 1) * TPOT                   (seconds, one request)
             throughput per GPU  T = concurrency * OSL / L / GPUs     (output tokens per second per GPU;
                                                                    a closed loop of `concurrency` requests)
             SLO goodput  T if TPOT <= SLO_TPOT and TTFT <= SLO_TTFT, else 0
METRICS    per group:
             spearman   Spearman rank correlation of predicted against measured value (ties get the mean rank)
             kendall    Kendall tau-b of the same pairs
             top1       1 if the predicted-best configuration is the measured-best one, else 0
             top3       1 if the measured-best configuration is among the three predicted-best, else 0
             regret     (best measured value - measured value of the predicted-best) / best measured value
           Ties for best break by the configuration key (the first in sorted order), on both sides.
           Over groups: the mean of each, with the number of groups. A figure over fewer than
           MIN_GROUPS groups is "too few groups", as a MAPE over fewer than 10 points is "too few points".
"""
from __future__ import annotations

import math
from collections import defaultdict

MIN_CONFIGS = 3
MIN_GROUPS = 10
TOO_FEW = "too few groups"


def latency_s(ttft_us: float, tpot_us: float, osl: int) -> float:
    return (ttft_us + (osl - 1) * tpot_us) / 1e6


def throughput_per_gpu(ttft_us, tpot_us, conc, osl, gpus) -> float:
    return conc * osl / latency_s(ttft_us, tpot_us, osl) / gpus


def slo_goodput(ttft_us, tpot_us, conc, osl, gpus, slo_ttft_ms=None, slo_tpot_ms=None) -> float:
    if (slo_ttft_ms is not None and ttft_us > slo_ttft_ms * 1e3) or (slo_tpot_ms is not None and tpot_us > slo_tpot_ms * 1e3):
        return 0.0
    return throughput_per_gpu(ttft_us, tpot_us, conc, osl, gpus)


def _ranks(x: list[float]) -> list[float]:
    order = sorted(range(len(x)), key=lambda i: x[i])
    r = [0.0] * len(x)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and x[order[j + 1]] == x[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def _pearson(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def spearman(pred: list[float], meas: list[float]) -> float | None:
    """Pearson correlation of the average ranks; None when a side is constant."""
    return _pearson(_ranks(pred), _ranks(meas))


def kendall(pred: list[float], meas: list[float]) -> float | None:
    """Kendall tau-b over all pairs; None when a side is constant."""
    conc = disc = tp = tm = 0
    n = len(pred)
    for i in range(n):
        for j in range(i + 1, n):
            dp, dm = pred[i] - pred[j], meas[i] - meas[j]
            if dp == 0 and dm == 0:
                continue
            if dp == 0:
                tp += 1
            elif dm == 0:
                tm += 1
            elif (dp > 0) == (dm > 0):
                conc += 1
            else:
                disc += 1
    denom = math.sqrt((conc + disc + tp) * (conc + disc + tm))
    return None if denom == 0 else (conc - disc) / denom


def group_metrics(items: list[dict]) -> dict:
    """items: each {"key", "pred", "meas"} (the configuration key and the two values)."""
    items = sorted(items, key=lambda i: i["key"])
    pred, meas = [i["pred"] for i in items], [i["meas"] for i in items]
    best_m = max(range(len(items)), key=lambda i: (meas[i], -i))
    order_p = sorted(range(len(items)), key=lambda i: (-pred[i], i))
    best_p = order_p[0]
    return {"configs": len(items), "spearman": spearman(pred, meas), "kendall": kendall(pred, meas),
            "top1": int(best_p == best_m), "top3": int(best_m in order_p[:3]),
            "regret": (meas[best_m] - meas[best_p]) / meas[best_m] if meas[best_m] > 0 else None}


def evaluate(points: list[dict], value: str = "throughput_per_gpu", slo_ttft_ms=None, slo_tpot_ms=None) -> dict:
    """points: scored points with model, hardware, isl, osl, concurrency, gpus, the four microsecond
    figures and a "key" (the configuration). Groups of fewer than MIN_CONFIGS points are left out."""
    groups = defaultdict(list)
    for p in points:
        if not p.get("osl"):
            continue            # a point with no ISL and OSL (an agentic trace) has no throughput per GPU
        f = (lambda t, o: throughput_per_gpu(t, o, p["concurrency"], p["osl"], p["gpus"])) if value == "throughput_per_gpu" \
            else (lambda t, o: slo_goodput(t, o, p["concurrency"], p["osl"], p["gpus"], slo_ttft_ms, slo_tpot_ms))
        groups[(p["model"], p["hardware"], p["isl"], p["osl"])].append(
            {"key": p["key"], "pred": f(p["pred_ttft_us"], p["pred_tpot_us"]), "meas": f(p["meas_ttft_us"], p["meas_tpot_us"])})
    per = {g: group_metrics(v) for g, v in sorted(groups.items()) if len(v) >= MIN_CONFIGS}
    out = {"value": value, "groups": len(per), "left_out": len(groups) - len(per)}
    for m in ("spearman", "kendall", "top1", "top3", "regret"):
        xs = [v[m] for v in per.values() if v[m] is not None]
        out[m] = TOO_FEW if len(per) < MIN_GROUPS or not xs else sum(xs) / len(xs)
    return out
