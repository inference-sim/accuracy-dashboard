"""Reduce two sets of predictions to aggregates over lanes of held role keys (design VAL-6, COV-13).

Everything per unit stays inside this module: the output of `reduce_report` is a document whose numbers
are lane aggregates over at least MIN_POINTS role keys, and no unit, role key or per-unit value is in it.
"""
from __future__ import annotations

import csv
import hashlib
import math
import re
from pathlib import Path

import numpy as np

import prereg as pr
import stats

MIN_POINTS = 10
LANE_FIELDS = pr.LANE_FIELDS
FLOOR_LABEL = "<1e-4"
UNIT_ERROR_WHEN_ABSENT = 1.0            # an absent prediction scores as a 100% error
DISTANCE_REASON = ("distribution distance needs the per-request samples of each unit; the candidate's "
                   "predictions are scalars, so it is unjudged")


class ReduceError(ValueError):
    pass


def load_measured(path, want_sha256: str) -> dict:
    """unit_id -> {"lane": (engine, modelled_commit, chip, model, layout), "meas": {metric: float}}.
    The file is the measured table: the gate reads it only if its SHA-256 is the pre-registration's."""
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != want_sha256:
        raise ReduceError("the measured table is not the one the pre-registration pins (measured_sha256)")
    rows = list(csv.DictReader(raw.decode("utf-8").splitlines()))
    if not rows:
        raise ReduceError("the measured table is empty")
    need = {"point_id", *LANE_FIELDS}
    cols = set(rows[0])
    metrics = sorted(c[5:] for c in cols if c.startswith("meas_"))
    if not need <= cols or not metrics:
        raise ReduceError("the measured table lacks point_id, the lane columns or meas_<metric> columns")
    out = {}
    for r in rows:
        uid = r["point_id"]
        if uid in out:
            raise ReduceError("the measured table lists a unit twice")
        meas = {}
        for m in metrics:
            try:
                v = float(r[f"meas_{m}"])
            except ValueError:
                continue
            if math.isfinite(v) and v > 0:
                meas[m] = v
        out[uid] = {"lane": tuple(r[f] for f in LANE_FIELDS), "meas": meas}
    return out


def _error(pred: dict, meas: dict, metric: str):
    """The relative error of one unit on one metric, or None when the measurement is not a positive number."""
    if metric not in meas:
        return None
    if metric not in pred:
        return UNIT_ERROR_WHEN_ABSENT
    return abs(pred[metric] - meas[metric]) / meas[metric]


def _keys(units: list) -> int:
    return len({u["role_key"] for u in units})


def build_lanes(by_lane: dict, min_points: int = MIN_POINTS):
    """Lanes of at least min_points role keys. A short lane is merged with the short lanes that agree with it on
    engine, modelled commit and chip, then, if still short, on engine and modelled commit. Returns
    (judged, unjudged_count): judged is a list of (members, units), members the lane tuples merged."""
    judged, short = [], dict(by_lane)
    for width in (3, 2):
        groups: dict = {}
        for lane, us in sorted(short.items()):
            groups.setdefault(lane[:width], []).append((lane, us))
        short = {}
        for _, parts in sorted(groups.items()):
            units = [u for _, us in parts for u in us]
            if _keys(units) >= min_points:
                judged.append(([l for l, _ in parts], units))
            else:
                short.update(parts)
    return judged, len(short)


def _first_pass(by_lane: dict, min_points: int):
    own = {l: us for l, us in by_lane.items() if _keys(us) >= min_points}
    return [([l], us) for l, us in sorted(own.items())], {l: us for l, us in by_lane.items() if l not in own}


def lanes_of(by_lane: dict, min_points: int = MIN_POINTS):
    judged, short = _first_pass(by_lane, min_points)
    more, left = build_lanes(short, min_points)
    return judged + more, left


def _lane_dict(t) -> dict:
    return dict(zip(LANE_FIELDS, t))


def _is_target(members: list, prereg_doc: dict) -> bool:
    return any(pr.lane_matches(p, _lane_dict(m)) for m in members for p in prereg_doc["target_lanes"])


def _diffs(units: list, metric: str, cand: dict, base: dict, measured: dict):
    """One number per role key: the key's mean of (candidate error - base error) over its scored units."""
    per_key: dict = {}
    for u in units:
        uid = u["unit_id"]
        meas = measured[uid]["meas"]
        ce, be = _error(cand[uid], meas, metric), _error(base[uid], meas, metric)
        if ce is None or be is None:
            continue
        per_key.setdefault(u["role_key"], []).append(ce - be)
    return np.array([sum(v) / len(v) for _, v in sorted(per_key.items())])


def _common(members: list) -> dict:
    """The fields every merged lane shares. A merged lane is named by these alone: listing its members would
    say which deployments are held."""
    return {f: members[0][i] for i, f in enumerate(LANE_FIELDS) if all(m[i] == members[0][i] for m in members)}


def _name(members: list) -> str:
    c = _common(members)
    return "/".join(c.get(f, "*") for f in LANE_FIELDS)


def reduce_report(prereg_doc, units: list, assign: dict, measured: dict, base, cand, min_points: int = MIN_POINTS) -> dict:
    """units: [{"unit_id", "role_key"}]; assign: unit_id -> partition.Assignment. base and cand are
    predictions.Predictions. Returns the aggregates-only report body (the caller adds the run's identity)."""
    held = [{"unit_id": u["unit_id"], "role_key": u["role_key"]} for u in units
            if assign[u["unit_id"]].role == "held" and u["unit_id"] in measured]
    out = {"resamples": stats.B, "alpha": stats.ALPHA, "min_points": min_points}
    sections = {}
    for blind in (True, False):
        by_lane: dict = {}
        for u in held:
            if assign[u["unit_id"]].not_blind != (not blind):
                continue
            by_lane.setdefault(measured[u["unit_id"]]["lane"], []).append(u)
        sections[blind] = lanes_of(by_lane, min_points)
    if not sections[True][0] and not sections[False][0]:
        raise ReduceError("no lane holds enough held role keys to be judged")

    def evaluate(section, test: bool):
        lane_docs, items = [], []
        member_sets = []
        for members, us in section[0]:
            target = _is_target(members, prereg_doc)
            doc = {"name": _name(members), "lane": _common(members), "member_lanes": len(members), "merged": len(members) > 1,
                   "target": target, "role_keys": _keys(us), "results": [], "unjudged": []}
            for c in prereg_doc["criteria"]:
                for metric in prereg_doc["metrics"]:
                    if c["criterion"] == "distance":
                        doc["unjudged"].append({"criterion": "distance", "metric": metric, "reason": DISTANCE_REASON})
                        continue
                    d = _diffs(us, metric, cand.values, base.values, measured)
                    if len(d) < min_points:
                        doc["unjudged"].append({"criterion": "error", "metric": metric,
                                                "reason": f"fewer than {min_points} role keys with a scored unit"})
                        continue
                    null = 0.0 if target else float(c["margin"])
                    rng = stats.rng_for(prereg_doc["substream"], doc["name"], c["criterion"], metric)
                    a = stats.analyse(d, null, rng)
                    res = {"criterion": c["criterion"], "metric": metric, "null_difference_at_least": null,
                           "role_keys": int(len(d)), "difference": a["difference"], "upper_95": a["upper_95"]}
                    doc["results"].append(res)
                    items.append((res, a))
            lane_docs.append(doc)
            member_sets.append(members)
        if test:
            rej = stats.holm([a["p"] for _, a in items])
            for (res, a), r in zip(items, rej):
                res["p_value"] = FLOOR_LABEL if a["below_floor"] else a["p"]
                res["rejected"] = r
        else:
            for res, _ in items:
                res["rejected"] = None
        for doc in lane_docs:
            doc["passes"] = (all(r["rejected"] for r in doc["results"]) and bool(doc["results"])) if test else None
        return lane_docs, member_sets

    blind_docs, blind_members = evaluate(sections[True], True)
    out["lanes"] = blind_docs
    out["unjudged_lanes"] = sections[True][1]
    out["not_blind"] = {"note": ("units on a legacy side are not blind: the old labels and side rules are public. "
                                 "Reported apart, without a test, and never part of the verdict."),
                        "lanes": evaluate(sections[False], False)[0], "unjudged_lanes": sections[False][1]}
    unjudged = []
    for i, p in enumerate(prereg_doc["target_lanes"]):
        hit = [d for d, ms in zip(blind_docs, blind_members) if any(pr.lane_matches(p, _lane_dict(m)) for m in ms)]
        if not any(d["results"] for d in hit):
            unjudged.append({"target_lane": i, "reason": "no judged lane holds this target lane"})
    for d in blind_docs:
        if d["target"]:
            unjudged += [{"target_lane_in": d["name"], **u} for u in d["unjudged"]]
    out["target_unjudged"] = unjudged
    failing = [d for d in blind_docs if d["results"] and not d["passes"]]
    out["verdict"] = "fail" if failing else ("unjudged" if unjudged else "pass")
    return out
