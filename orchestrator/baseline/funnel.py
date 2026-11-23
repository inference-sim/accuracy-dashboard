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
              [--configiq-ledger L --configiq-points configiq-points.jsonl]
              [--ledger-yaml ledger.yaml] [--training-ledger L] [--complete] [--strict-d9] --out funnel.json

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

import public_text as pt  # noqa: E402
import sources as src  # noqa: E402

FORMAT = "funnel-2"
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


def tally(source: str, rows_held: int, units: list[dict], *, left_out_rows: dict | None = None,
          anchor_rule: str | None = None, not_anchor: dict | None = None, lanes: bool = False) -> dict:
    """One source's funnel. Each unit is {"unit_id", "excluded": reason | None, "recoverable": True | False | None,
    "blocked": reason | None, "grade": G1..G5 | None, "provisional": bool, "failed": reason | None, "g5": code | None,
    "withheld": reason | None, "lane": engine | None}; `blocked` is the reason a not recoverable unit is. `anchor_rule`
    says how the source's anchor units were chosen (sources.py) and `not_anchor` counts the units of the ledger that rule
    leaves out, by reason. With `lanes` the same stages are repeated for each lane (InferenceX: vllm, sglang) beside the
    source's whole."""
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
    out = {
        "source": source, "role": "anchor", "anchor_rule": anchor_rule or "every unit listed",
        "not_anchor": dict(sorted((not_anchor or {}).items())),
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
    if lanes:
        by_lane: dict[str, list] = {}
        for u in units:
            by_lane.setdefault(u.get("lane") or "other", []).append(u)
        out["lanes"] = {name: {k: v for k, v in tally(f"{source}/{name}", 0, us).items()
                               if k in ("stages", "excluded", "scored_by_grade", "provisional", "g5", "failed", "no_outcome")}
                        for name, us in sorted(by_lane.items())}
    return out


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


def combine(funnels: list[dict], *, training_funnels: list[dict] | None = None, discrepancies: list[dict] | None = None,
            complete: bool = False) -> dict:
    """The funnel document. `discrepancies` are ledger.yaml's disagreements with D9 (sources.check_cut_points), None when
    ledger.yaml was not read: the document says which, so an unchecked file never reads as an agreeing one. With
    `complete` the run holds an outcome for every anchor unit (a night's contract), so an in-scope unit with neither a
    grade nor a stated reason is a problem (plan row 16: scored, or a stated G5 reason)."""
    names = [f["source"] for f in funnels]
    if not funnels or len(set(names)) != len(names):
        raise FunnelError(f"a funnel document holds each source once, got {names}")
    doc = {"format": FORMAT, "funnels": {f["source"]: f for f in sorted(funnels, key=lambda f: f["source"])},
           "scored": {f["source"]: f["stages"]["scored"] for f in sorted(funnels, key=lambda f: f["source"])},
           "meaning": "No unit is dropped for its date. Recoverable is a floor (recoverable.py), so a unit can be "
                      "scored without being counted recoverable; unresolved counts the recoverable units that are "
                      "neither scored nor G5. A provisional unit (capped at G3) is outside scored."}
    doc["problems"] = [p for f in funnels for p in check(f)]
    if complete:
        doc["problems"] += [f"{f['source']}: {sum(f['no_outcome'].values())} in-scope units have neither a grade nor a stated "
                            f"reason ({', '.join(f['no_outcome'])})" for f in funnels if f["no_outcome"]]
    doc["training"] = {t["source"]: t for t in sorted(training_funnels or [], key=lambda t: t["source"])}
    doc["cut_points"] = {"checked": discrepancies is not None, "discrepancies": discrepancies or []}
    return doc


def validate(doc: dict) -> dict:
    if not isinstance(doc, dict) or doc.get("format") != FORMAT or not doc.get("funnels"):
        raise FunnelError(f"not a {FORMAT} document")
    problems = [p for f in doc["funnels"].values() for p in check(f)]
    if problems:
        raise FunnelError("; ".join(problems))
    for t in doc.get("training", {}).values():
        if t.get("role") != "training-only" or "accuracy" in t or "scored" in t.get("stages", {}):
            raise FunnelError(f"{t.get('source')}: a training-only source carries no accuracy, only a labelled diagnostic")
    return doc


# ------------------------------------------------------------------------------------------------ sources

def lane_of(unit) -> str:
    """The engine lane of an InferenceX unit: vllm or sglang, else the framework's engine or its label (never scored)."""
    import engines
    try:
        return engines.lookup(unit.identity["framework"]).engine or "other"
    except (engines.EngineError, KeyError):
        return "other"


def inferencex_units(anchor: dict, recoverable: list[dict] | None, outcomes: dict) -> list[dict]:
    """The anchor units, placed by recoverable.py's per-unit lines ({"unit_id", "status", "detail"}) and the scorer's
    contract ({unit_id: {"grade", "g5", "failed"}}, from `contract_outcomes`)."""
    rec = {r["unit_id"]: r for r in recoverable or []}
    out = []
    for uid in sorted(anchor):
        r, o = rec.get(uid), outcomes.get(uid, {})
        u = {"unit_id": uid, "excluded": None, "recoverable": None, "blocked": None, "grade": o.get("grade"),
             "provisional": False, "failed": o.get("failed"), "g5": o.get("g5"), "withheld": None,
             "lane": lane_of(anchor[uid])}
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
    return tally("inferencex", len(lg.by_record), units, left_out_rows=_count(lg.left_out.values()),
                 anchor_rule=src.ANCHOR_RULE[src.INFERENCEX], lanes=True,
                 not_anchor={"not_in_the_anchor_list": len(lg.units) - len(anchor_ids)})


def configiq_units(lg, records: list[dict], left_out: frozenset | set = frozenset()) -> list[dict]:
    """Every anchor unit of the configiq ledger -- every unit but those a partition-prep report left out (D9) -- placed by
    its record in configiq-points.jsonl (configiq_score.record)."""
    by = {r["point_id"]: r for r in records}
    out = []
    for uid in sorted(set(lg.units) - set(left_out)):
        r = by.get(uid)
        u = {"unit_id": uid, "excluded": None, "recoverable": None, "blocked": None, "grade": None,
             "provisional": False, "failed": None, "g5": None, "withheld": None, "lane": "vllm"}
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
            u["withheld"] = "withheld_by_local_option"
    return out


def configiq(lg, records: list[dict], left_out: frozenset | set = frozenset()) -> dict:
    extra = sorted({r["point_id"] for r in records} - set(lg.units))
    if extra:
        raise FunnelError(f"configiq-points holds {len(extra)} points the ledger has no unit for, the first {extra[0]}")
    gone = sorted(set(left_out) - set(lg.units))
    if gone:
        raise FunnelError(f"the left-out list names {len(gone)} units the configiq ledger does not hold, the first {gone[0]}")
    return tally("configiq", len(lg.by_record), configiq_units(lg, records, left_out),
                 left_out_rows=_count(lg.left_out.values()), anchor_rule=src.ANCHOR_RULE[src.CONFIGIQ],
                 not_anchor={"left_out_by_partition_prep": len(left_out)})


def training(source: str, report: dict) -> dict:
    """The funnel of a training-only source, from its ingest report alone: rows held, units, duplicates and the rows left
    out by reason. It scores nothing and reports no accuracy: the source is training data (D9), so what the dashboard
    may show of it is how the fitted model reproduces it, labelled a training diagnostic."""
    return {"source": source, "role": "training-only", "label": src.TRAINING_LABEL,
            "stages": {"rows_held": report["records"], "units": report["units"]},
            "duplicates": report["duplicates"], "merged_records": report["merged"],
            "left_out_rows": {k: len(v) if isinstance(v, list) else v for k, v in sorted((report["left_out"] or {}).items())},
            "diagnostic": None}


def read_training(directory: Path) -> list[dict]:
    """The three training-only sources' funnels from <directory>/reports/<source>.yaml (blis-substrate's catalog/ledger)."""
    import yaml
    out = []
    for s in src.TRAINING_ONLY:
        rep = yaml.safe_load((Path(directory) / "reports" / f"{s}.yaml").read_text())
        if rep.get("source") != s:
            raise FunnelError(f"reports/{s}.yaml is the report of {rep.get('source')!r}")
        out.append(training(s, rep))
    return out


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
        L += [f"Anchor rule: {f['anchor_rule']}.", ""]
        if f["not_anchor"]:
            L += ["Units of the ledger outside the anchors: " + ", ".join(f"{k} {v}" for k, v in f["not_anchor"].items()) + ".", ""]
        for lane, lf in f.get("lanes", {}).items():
            ls = lf["stages"]
            L += [f"- Lane {lane}: {ls['scored']} of {ls['in_scope']} in-scope units scored ({ls['units']} units); "
                  f"G5 {sum(lf['g5'].values())}, failed {sum(lf['failed'].values())}, no result {sum(lf['no_outcome'].values())}."]
        if f.get("lanes"):
            L += [""]
        rows = [(label, r, n) for label, d in (("Excluded", f["excluded"]), ("Not recovered", f["not_recovered"]),
                                                ("G5", f["g5"]), ("Failed", f["failed"]), ("Withheld", f["withheld"]),
                                                ("No result", f["no_outcome"]), ("Left-out rows", f["left_out_rows"]))
                for r, n in d.items()]
        if rows:
            L += ["| Part | Reason | Count |", "|---|---|---|"] + [f"| {a} | `{b}` | {n} |" for a, b, n in rows] + [""]
        L += [f"Recoverable units neither scored nor G5: {f['unresolved']['units']}.", ""]
    for name, t in doc.get("training", {}).items():
        L += [f"### {name} (training only)", "", f"{t['label']}. {t['stages']['units']} units, {t['stages']['rows_held']} rows held; "
              f"no accuracy is reported for it.", ""]
    cp = doc.get("cut_points", {"checked": False, "discrepancies": []})
    if cp["discrepancies"]:
        L += ["### ledger.yaml disagrees with design D9", ""] + [f"- **{d['source']}**: {d['text']}" for d in cp["discrepancies"]] + [""]
    elif not cp["checked"]:
        L += ["ledger.yaml was not checked against design D9 in this run.", ""]
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
    ap.add_argument("--ledger-yaml", type=Path, help="ledger.yaml, checked against design D9 (sources.py); its "
                    "rules.configiq.left_out narrows configiq's anchors")
    ap.add_argument("--training-ledger", type=Path, help="a checkout of catalog/ledger: adds the three training-only "
                    "sources' funnels from reports/<source>.yaml, labelled training only")
    ap.add_argument("--published", type=Path, help="a directory of published unit lists (fit.yaml, select.yaml, ...): a "
                    "configiq unit in a training-role list is a problem (D9: it is left out of the anchors, never made one)")
    ap.add_argument("--complete", action="store_true",
                    help="the contract holds an outcome for every anchor unit (a night): a unit with none is a problem")
    ap.add_argument("--strict-d9", action="store_true", help="exit 1 when ledger.yaml disagrees with D9 (after row 26)")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    funnels, found, left_out, trained, hits = [], None, set(), [], []
    try:
        if a.ledger or a.anchor or a.contract:
            if not (a.ledger and a.anchor and a.contract):
                raise FunnelError("the InferenceX funnel needs --ledger, --anchor and --contract")
            import ledger as ldg
            lg = ldg.load(a.ledger)
            rec = [json.loads(x) for x in a.recoverable_units.read_text().splitlines() if x.strip()] \
                if a.recoverable_units else None
            funnels.append(inferencex(lg, ldg.read_unit_set(a.anchor, role="anchor"), rec, contract_outcomes(a.contract)))
        if a.ledger_yaml:
            ydoc = src.read_ledger_yaml(a.ledger_yaml)
            found, left_out = src.check_cut_points(ydoc), src.configiq_left_out(ydoc)
        if a.training_ledger:
            trained = read_training(a.training_ledger)
        if a.configiq_ledger or a.configiq_points:
            if not (a.configiq_ledger and a.configiq_points):
                raise FunnelError("the configiq funnel needs --configiq-ledger and --configiq-points")
            import configiq as cq
            d = a.configiq_ledger
            lg = cq.load(d / "units" / "configiq.jsonl.gz", d / "reports" / "configiq.yaml", d / "sources.yaml")
            recs = [json.loads(x) for x in a.configiq_points.read_text().splitlines() if x.strip()]
            funnels.append(configiq(lg, recs, left_out))
            if a.published:      # the anchors only: a left-out unit is meant to be in a training list
                hits = src.configiq_in_training(a.published, src.configiq_anchor_ids(lg.units, {"rules": {"configiq": {"left_out": sorted(left_out)}}}))
        doc = combine(funnels, training_funnels=trained, discrepancies=found, complete=a.complete)
        doc["problems"] += [f"configiq: {len(h['units'])} units are in the published {h['role']} list {h['file']} (first "
                            f"{h['units'][0]}); configiq is anchor-only, so each is to be left out of the anchors "
                            f"(rules.configiq.left_out), not made one" for h in hits]
    except (FunnelError, src.SourcesError, OSError, ValueError) as e:
        print(f"funnel: {e}", file=sys.stderr)
        return 2
    a.out.write_text(json.dumps(pt.scrub(doc), indent=1, sort_keys=True) + "\n")
    print(f"wrote {a.out}: " + ", ".join(f"{k} {v} scored" + (f" + {doc['funnels'][k]['provisional']['units']} provisional"
                                                          if doc["funnels"][k]["provisional"]["units"] else "")
                                         for k, v in doc["scored"].items()))
    for p in doc["problems"]:
        print(f"INVALID: {p}", file=sys.stderr)
    for d in doc["cut_points"]["discrepancies"]:
        print(f"WARNING: ledger.yaml vs D9, {d['source']}: {d['text']}", file=sys.stderr)
    return 1 if (doc["problems"] or (a.strict_d9 and doc["cut_points"]["discrepancies"])) else 0


if __name__ == "__main__":
    sys.exit(main())
