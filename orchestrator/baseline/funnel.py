#!/usr/bin/env python3
"""The scoring funnels of InferenceX and configiq: how many units each stage keeps, and why the rest drop out
(design §11.6, COV-2, COV-7; requirements §3A.2, §3A.5, §3A.6; plan row 16).

No unit is dropped for its date: the funnel has no date stage. For one source the stages are

  rows_held      the records the ledger holds for the source
  units          the units to score (InferenceX: the anchor units; configiq: every unit of the pinned revision)
  in_scope       units minus those a chip BLIS does not model, a hardware or a framework no engine runs
  recoverable    in-scope units whose inputs can be fetched (InferenceX: recoverable.py's floor; configiq: the dataset
                 records every value the scorer needs); null when no probe was run
  scored         in-scope units with a grade G1 to G4, split by grade; a provisional unit (capped at G3) is counted in
                 its own band and is never in `scored` (COV-7, COV-11)

The in-scope units are also placed in exactly one of: scored, provisional, g5 (by reason code), failed (a runner
limit), withheld (configiq's test split, not simulated) or no_outcome (the run holds no result for the unit). Each
exclusion and each of those has a named reason, and `blockers` lists the largest reasons that stop an in-scope unit from
being scored, each unit under one reason. Recoverable is a floor, so
a unit can be scored without being counted recoverable; `unresolved` counts the recoverable units that are neither
scored nor G5, which row 16 requires to be none.

    funnel.py [--ledger L --anchor A --contract C [--recoverable-units units.jsonl]]
              [--configiq-ledger L --configiq-points configiq-points.jsonl] --out funnel.json

`m3_baseline.py report --funnel funnel.json` publishes it with the baseline. Run it for real after a nightly with the
contract directory it scored and recoverable.py's --units-out.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ingest"))

FORMAT = "funnel-1"
GRADED = ("G1", "G2", "G3", "G4")
NOT_RECORDED = "value_not_recorded"
OUT_OF_SCOPE = ("chip_not_modelled",)
TOP = 10
NO_OUTCOME = "no_result_in_this_run"


class FunnelError(ValueError):
    pass


def _count(items) -> dict:
    out: dict = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return dict(sorted(out.items()))


def tally(source: str, rows_held: int, units: list[dict], *, left_out_rows: dict | None = None) -> dict:
    """One source's funnel. Each unit is {"unit_id", "excluded": reason | None, "recoverable": True | False | None,
    "blocked": reason | None, "grade": G1..G5 | None, "provisional": bool, "failed": reason | None, "g5": code | None,
    "withheld": reason | None}; `blocked` is the reason a not recoverable unit is."""
    ids = [u["unit_id"] for u in units]
    if len(set(ids)) != len(ids):
        raise FunnelError(f"{source}: a unit is listed twice")
    scope = [u for u in units if not u.get("excluded")]
    excluded = _count(u["excluded"] for u in units if u.get("excluded"))
    probed = any(u.get("recoverable") is not None for u in scope)
    recoverable = [u for u in scope if u.get("recoverable")]
    not_recovered = _count(u.get("blocked") or "unstated" for u in scope if u.get("recoverable") is False)
    placed: dict[str, list] = {"scored": [], "provisional": [], "g5": [], "failed": [], "withheld": [], "no_outcome": []}
    for u in scope:
        if u.get("failed"):
            placed["failed"].append(u)
        elif u.get("g5"):
            placed["g5"].append(u)
        elif u.get("provisional"):
            placed["provisional"].append(u)
        elif u.get("grade") in GRADED:
            placed["scored"].append(u)
        elif u.get("withheld"):
            placed["withheld"].append(u)
        else:
            placed["no_outcome"].append(u)
    by_grade = {g: sum(1 for u in placed["scored"] if u["grade"] == g) for g in GRADED}
    prov_by_grade = _count(u.get("grade") or "ungraded" for u in placed["provisional"])
    g5 = _count(u["g5"] for u in placed["g5"])
    failed = _count(u["failed"] for u in placed["failed"])
    withheld = _count(u["withheld"] for u in placed["withheld"])
    no_outcome = _count(u.get("blocked") or NO_OUTCOME for u in placed["no_outcome"])
    resolved = {id(u) for k in ("scored", "g5") for u in placed[k]}
    unresolved = [u["unit_id"] for u in recoverable if id(u) not in resolved]
    blockers = [{"stage": s, "reason": r, "units": n}
                for s, d in (("g5", g5), ("failed", failed), ("withheld", withheld), ("no_outcome", no_outcome))
                for r, n in d.items()]
    blockers.sort(key=lambda b: (-b["units"], b["stage"], b["reason"]))
    return {
        "source": source,
        "stages": {"rows_held": rows_held, "units": len(units), "in_scope": len(scope),
                   "recoverable": len(recoverable) if probed else None, "scored": len(placed["scored"])},
        "left_out_rows": dict(sorted((left_out_rows or {}).items())),
        "excluded": excluded, "not_recovered": not_recovered,
        "scored_by_grade": by_grade,
        "provisional": {"units": len(placed["provisional"]), "by_grade": prov_by_grade},
        "g5": g5, "failed": failed, "withheld": withheld, "no_outcome": no_outcome,
        "unresolved": {"units": len(unresolved), "unit_ids": sorted(unresolved)[:TOP]},
        "blockers": blockers[:TOP],
    }


def check(f: dict) -> list[str]:
    """Problems with one funnel: stages that do not shrink, buckets that do not add up to what they split."""
    s, out = f["stages"], []
    if s["in_scope"] > s["units"]:
        out.append(f"{f['source']}: in_scope {s['in_scope']} exceeds units {s['units']}")
    if sum(f["excluded"].values()) != s["units"] - s["in_scope"]:
        out.append(f"{f['source']}: the exclusions sum to {sum(f['excluded'].values())}, units - in_scope is "
                   f"{s['units'] - s['in_scope']}")
    if s["recoverable"] is not None and s["recoverable"] > s["in_scope"]:
        out.append(f"{f['source']}: recoverable {s['recoverable']} exceeds in_scope {s['in_scope']}")
    if sum(f["scored_by_grade"].values()) != s["scored"]:
        out.append(f"{f['source']}: the grades sum to {sum(f['scored_by_grade'].values())}, scored is {s['scored']}")
    placed = (s["scored"] + f["provisional"]["units"] + sum(f["g5"].values()) + sum(f["failed"].values())
              + sum(f["withheld"].values()) + sum(f["no_outcome"].values()))
    if placed != s["in_scope"]:
        out.append(f"{f['source']}: the outcomes add up to {placed}, in_scope is {s['in_scope']}")
    if s["recoverable"] is not None and f["unresolved"]["units"] > s["recoverable"]:
        out.append(f"{f['source']}: unresolved {f['unresolved']['units']} exceeds recoverable {s['recoverable']}")
    return out


def combine(funnels: list[dict]) -> dict:
    names = [f["source"] for f in funnels]
    if not funnels or len(set(names)) != len(names):
        raise FunnelError(f"a funnel document holds each source once, got {names}")
    doc = {"format": FORMAT, "funnels": {f["source"]: f for f in sorted(funnels, key=lambda f: f["source"])},
           "scored": {f["source"]: f["stages"]["scored"] for f in sorted(funnels, key=lambda f: f["source"])},
           "meaning": "No unit is dropped for its date. Recoverable is a floor (recoverable.py), so a unit can be "
                      "scored without being counted recoverable; unresolved counts the recoverable units that are "
                      "neither scored nor G5. A provisional unit (capped at G3) is outside scored."}
    doc["problems"] = [p for f in funnels for p in check(f)]
    return doc


def validate(doc: dict) -> dict:
    if not isinstance(doc, dict) or doc.get("format") != FORMAT or not doc.get("funnels"):
        raise FunnelError(f"not a {FORMAT} document")
    problems = [p for f in doc["funnels"].values() for p in check(f)]
    if problems:
        raise FunnelError("; ".join(problems))
    return doc


# ------------------------------------------------------------------------------------------------ sources

def inferencex_units(anchor: dict, recoverable: list[dict] | None, outcomes: dict) -> list[dict]:
    """The anchor units, placed by recoverable.py's per-unit lines ({"unit_id", "status", "detail"}) and the scorer's
    contract ({unit_id: {"grade", "g5", "failed"}}, from `contract_outcomes`)."""
    rec = {r["unit_id"]: r for r in recoverable or []}
    out = []
    for uid in sorted(anchor):
        r, o = rec.get(uid), outcomes.get(uid, {})
        u = {"unit_id": uid, "excluded": None, "recoverable": None, "blocked": None, "grade": o.get("grade"),
             "provisional": False, "failed": o.get("failed"), "g5": o.get("g5"), "withheld": None}
        if r is not None and r["status"] == "excluded":
            u["excluded"] = r["detail"]
        elif o.get("g5") in OUT_OF_SCOPE:
            u["excluded"] = o["g5"]
        elif r is not None:
            u["recoverable"] = r["status"] == "recoverable"
            if r["status"] == "not_recovered":
                u["blocked"] = r["detail"]
        out.append(u)
    return out


def contract_outcomes(directory: Path) -> dict:
    """{unit_id: {"grade", "g5", "failed"}} from a scored contract directory (fidelity, not_scored and failed)."""
    import contract
    out: dict = {}

    def lines(name):
        p = Path(directory) / name
        return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.is_file() else []
    for r in lines(contract.FIDELITY_JSONL):
        out[r["point_id"]] = {"grade": r["grade"]}
    for r in lines(contract.NOT_SCORED_JSONL):
        out[r["point_id"]] = {"grade": "G5", "g5": (r.get("g5_reason") or {}).get("code") or "unstated"}
    for r in lines(contract.FAILED_JSONL):
        out[r["point_id"]] = {"grade": None, "failed": ((r.get("faults") or ["unstated"])[0]).split(":")[0]}
    return out


def inferencex(lg, anchor_ids: set, recoverable: list[dict] | None, outcomes: dict) -> dict:
    missing = sorted(anchor_ids - set(lg.units))
    if missing:
        raise FunnelError(f"the anchor list names {len(missing)} units the ledger does not hold, the first {missing[0]}")
    units = inferencex_units({i: lg.units[i] for i in anchor_ids}, recoverable, outcomes)
    return tally("inferencex", len(lg.by_record), units, left_out_rows=_count(lg.left_out.values()))


def configiq_units(lg, records: list[dict]) -> list[dict]:
    """Every unit of the configiq ledger, placed by its record in configiq-points.jsonl (configiq_score.record)."""
    by = {r["point_id"]: r for r in records}
    out = []
    for uid in sorted(lg.units):
        r = by.get(uid)
        u = {"unit_id": uid, "excluded": None, "recoverable": None, "blocked": None, "grade": None,
             "provisional": False, "failed": None, "g5": None, "withheld": None}
        out.append(u)
        if r is None:
            continue
        reasons = r.get("g5_reasons") or []
        codes = [x["code"] for x in reasons]
        for c in OUT_OF_SCOPE:
            if c in codes:
                u["excluded"] = c
        if u["excluded"]:
            continue
        noted = [x for x in reasons if x["code"] == NOT_RECORDED]
        u["recoverable"] = not noted
        if noted:
            u["blocked"] = f"{NOT_RECORDED}: {noted[0].get('subject', '')}"[:80]
        if r.get("failed"):
            u["failed"] = ((r.get("faults") or ["unstated"])[0]).split(":")[0]
        elif r.get("grade") == "G5":
            u["g5"] = (r.get("g5_reason") or {}).get("code") or "unstated"
        elif r.get("provisional"):
            u["provisional"], u["grade"] = True, r.get("grade")
        elif r.get("grade") in GRADED:
            u["grade"] = r["grade"]
        elif r.get("status") == "withheld":
            u["withheld"] = "test_split_not_simulated"
    return out


def configiq(lg, records: list[dict]) -> dict:
    extra = sorted({r["point_id"] for r in records} - set(lg.units))
    if extra:
        raise FunnelError(f"configiq-points holds {len(extra)} points the ledger has no unit for, the first {extra[0]}")
    return tally("configiq", len(lg.by_record), configiq_units(lg, records),
                 left_out_rows=_count(lg.left_out.values()))


# ------------------------------------------------------------------------------------------------ markdown

def markdown(doc: dict) -> list[str]:
    L = ["## Scoring funnels (design §11.6, COV-2)", "", doc["meaning"], ""]
    for name, f in doc["funnels"].items():
        s = f["stages"]
        L += [f"### {name}", "", f"**{s['scored']} of {s['in_scope']} in-scope units are scored** "
              f"({s['units']} units, {s['rows_held']} rows held, {f['provisional']['units']} provisional, outside the count).",
              "", "| Stage | Units |", "|---|---|"]
        L += [f"| {k} | {'not probed' if v is None else v} |" for k, v in s.items()]
        L += [f"| scored {g} | {n} |" for g, n in f["scored_by_grade"].items()]
        L += [""]
        rows = [(label, r, n) for label, d in (("Excluded", f["excluded"]), ("Not recovered", f["not_recovered"]),
                                                ("G5", f["g5"]), ("Failed", f["failed"]), ("Withheld", f["withheld"]),
                                                ("No result", f["no_outcome"]), ("Left-out rows", f["left_out_rows"]))
                for r, n in d.items()]
        if rows:
            L += ["| Part | Reason | Count |", "|---|---|---|"] + [f"| {a} | `{b}` | {n} |" for a, b, n in rows] + [""]
        L += [f"Recoverable units neither scored nor G5: {f['unresolved']['units']}.", ""]
    return L


# ------------------------------------------------------------------------------------------------ cli

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--ledger", type=Path, help="a checkout of blis-substrate's catalog/ledger (InferenceX)")
    ap.add_argument("--anchor", type=Path, help="the published anchor list")
    ap.add_argument("--contract", type=Path, help="the scored contract directory of the InferenceX run")
    ap.add_argument("--recoverable-units", type=Path, help="recoverable.py --units-out")
    ap.add_argument("--configiq-ledger", type=Path, help="the same checkout, for the configiq ledger")
    ap.add_argument("--configiq-points", type=Path, help="configiq-points.jsonl of a score-configiq run")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    funnels = []
    try:
        if a.ledger or a.anchor or a.contract:
            if not (a.ledger and a.anchor and a.contract):
                raise FunnelError("the InferenceX funnel needs --ledger, --anchor and --contract")
            import ledger as ldg
            lg = ldg.load(a.ledger)
            rec = [json.loads(x) for x in a.recoverable_units.read_text().splitlines() if x.strip()] \
                if a.recoverable_units else None
            funnels.append(inferencex(lg, ldg.read_unit_set(a.anchor, role="anchor"), rec, contract_outcomes(a.contract)))
        if a.configiq_ledger or a.configiq_points:
            if not (a.configiq_ledger and a.configiq_points):
                raise FunnelError("the configiq funnel needs --configiq-ledger and --configiq-points")
            import configiq as cq
            d = a.configiq_ledger
            lg = cq.load(d / "units" / "configiq.jsonl.gz", d / "reports" / "configiq.yaml", d / "sources.yaml")
            recs = [json.loads(x) for x in a.configiq_points.read_text().splitlines() if x.strip()]
            funnels.append(configiq(lg, recs))
        doc = combine(funnels)
    except (FunnelError, OSError, ValueError) as e:
        print(f"funnel: {e}", file=sys.stderr)
        return 2
    a.out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    print(f"wrote {a.out}: " + ", ".join(f"{k} {v} scored" for k, v in doc["scored"].items()))
    for p in doc["problems"]:
        print(f"INVALID: {p}", file=sys.stderr)
    return 1 if doc["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
