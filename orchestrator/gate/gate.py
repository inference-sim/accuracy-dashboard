#!/usr/bin/env python3
"""The whole-run held-out gate (design VAL-6, §12.3, §13.5), as the commands its workflows run.

    gate.py check-prereg [FILE...]              every pre-registration (or the files named) is well formed
    gate.py check-ledger                        the budget ledger is well formed
    gate.py check-pr --body-file F --changes-file F    the pull request follows the rule (rule.py)
    gate.py unrecorded --run-ids F              every earlier successful gate run is in the ledger on main
    gate.py read-sim-pin --pins-file F          the SIM_REF a stack-pins.env assigns
    gate.py ledger-digest --ledger D            the SHA-256 a gate run records for the ledger it was scored over
    gate.py check-binding ...                   each side was scored over what its commit's simulator pin names
    gate.py contract-to-predictions ...         a contract's points.csv as a Predictions document (candidate job)
    gate.py handed-units --ledger D --out F      every unit that is not a published fit or anchor (what a candidate run scores)
    gate.py build-measured ...                  the measured table from a contract and the ledger's units
    gate.py evaluate ...                        the gate job: roles, aggregates, report, comment, ledger record

`evaluate` is the only command that reads the seed. It reads it from the environment variable named by
--seed-env (the value is never an argument), prints only text the guard has cleared, and writes only
aggregates. Run it from a checkout of main (the workflow checks main out).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ingest"))
import binding  # noqa: E402
import budget  # noqa: E402
import guard as gd  # noqa: E402
import partition  # noqa: E402
import predictions as pd_  # noqa: E402
import prereg as pr  # noqa: E402
import reduce as rd  # noqa: E402
import rule  # noqa: E402

ROOT = HERE.parent.parent
HEX40 = pd_.HEX40


def marker(partition_version: int, prereg_id: str) -> str:
    return f"<!-- whole-run-gate partition={partition_version} preregistration={prereg_id} -->"


def render_comment(report: dict) -> str:
    L = [marker(report["partition_version"], report["preregistration"]), "",
         f"### Whole-run held-out gate: **{report['verdict']}**", "",
         f"Pre-registration `{report['preregistration']}`, partition version {report['partition_version']}, "
         f"evaluation {report['evaluation']} of {report['budget']}. Base `{report['base'][:12]}`, "
         f"candidate `{report['candidate'][:12]}`.", "",
         f"Aggregates over lanes of at least {report['min_points']} held role keys: the difference is the "
         f"candidate's error minus the base's (negative is better); each p-value is for the null shown, "
         f"after the Holm correction over all {report['resamples']:,}-resample tests of this evaluation.", ""]
    for lane in report["lanes"]:
        kind = "target" if lane["target"] else "guard"
        merged = (f" (merged from {lane['member_lanes']} lanes; * marks a field that differs among them; a regression "
                  "confined to one member can pass inside it)") if lane["merged"] else ""
        L += [f"**{lane['name']}** [{kind}] - {lane['role_keys']} role keys{merged}"
              + ("" if lane["passes"] is None else f" - {'passes' if lane['passes'] else 'does not pass'}"), "",
              "| criterion | metric | null: difference at least | difference | upper 95% | p | rejected |", "|---|---|---|---|---|---|---|"]
        for r in lane["results"]:
            L.append(f"| {r['criterion']} | {r['metric']} | {r['null_difference_at_least']:g} | {r['difference']:.4g} | "
                     f"{r['upper_95']:.4g} | {r['p_value'] if isinstance(r['p_value'], str) else format(r['p_value'], '.4g')} | "
                     f"{'yes' if r['rejected'] else 'no'} |")
        for u in lane["unjudged"]:
            L.append(f"| {u['criterion']} | {u['metric']} | unjudged: {u['reason']} | | | | |")
        L.append("")
    if report["target_unjudged"]:
        L += ["Unjudged on the target lanes (a maintainer decides, VAL-6 Reach):", ""]
        L += [f"- {json.dumps(t, sort_keys=True)}" for t in report["target_unjudged"]]
        L.append("")
    L.append(f"Lanes with fewer than {report['min_points']} role keys after merging are unjudged: {report['unjudged_lanes']}.")
    nb = report["not_blind"]
    L += ["", f"Not blind ({len(nb['lanes'])} lanes, {nb['unjudged_lanes']} unjudged): {nb['note']}"]
    for lane in nb["lanes"]:
        L.append(f"- {lane['name']}: {lane['role_keys']} role keys; "
                 + "; ".join(f"{r['criterion']} {r['metric']} difference {r['difference']:.4g}" for r in lane["results"]))
    L += ["", "This is the one held evaluation of this pre-registration. It is recorded against the partition "
          "version's budget by the ledger file attached to the run (state/gate/ledger.json)."]
    return "\n".join(L) + "\n"


def _read_lines(path) -> list[str]:
    return [l.strip() for l in Path(path).read_text().splitlines() if l.strip() and not l.startswith("#")]


def cmd_check_prereg(a) -> int:
    root = Path(a.root)
    files = [Path(f) for f in a.files] or sorted((root / pr.DIR).glob("*.json"))
    bad = 0
    for f in files:
        try:
            pr.load(f)
        except pr.PreRegistrationError as e:
            print(f"::error::{e}")
            bad += 1
    print(f"{len(files)} pre-registrations; {bad} problems")
    return 1 if bad else 0


def cmd_check_ledger(a) -> int:
    try:
        doc = budget.load(Path(a.root) / budget.PATH)
    except (budget.Refused, OSError, ValueError) as e:
        print(f"::error::{e}")
        return 1
    print("partitions: " + ", ".join(f"{k}: {len(v['evaluations'])} of {v['budget'] if v['budget'] is not None else 'no budget (A5)'}"
                                      for k, v in sorted(doc["partitions"].items())))
    return 0


def cmd_check_pr(a) -> int:
    errs = rule.check_pr(Path(a.body_file).read_text(), rule.parse_changes(Path(a.changes_file).read_text()), a.root, a.base_root)
    for e in errs:
        print(f"::error::{e}")
    print("the pull request follows the gate rule" if not errs else f"{len(errs)} problems")
    return 1 if errs else 0


def harness_digest(provenance: Path) -> str:
    """The settings a run was scored under, without the commit that ran it and without what names its simulator
    build or data (binding.SIDE_BOUND): the base and the candidate differ in those by construction, and
    binding.check_side ties each to its own pin. Everything else (the units, the pull, the ingest) must agree."""
    doc = json.loads(provenance.read_text())
    doc.pop("harness_commit", None)
    for k in binding.SIDE_BOUND:
        doc.pop(k, None)
    if isinstance(doc.get("simulator"), dict):
        doc["simulator"].pop("harness_commit", None)
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def cmd_read_sim_pin(a) -> int:
    try:
        print(binding.read_sim_pin(Path(a.pins_file).read_text()))
    except (binding.BindingError, OSError) as e:
        print(f"::error::{e}")
        return 1
    return 0


def cmd_ledger_digest(a) -> int:
    try:
        print(binding.ledger_digest(Path(a.ledger)))
    except (binding.BindingError, OSError) as e:
        print(f"::error::{e}")
        return 1
    return 0


def cmd_check_binding(a) -> int:
    """Both sides against what their pins resolve to (resolve_data.sh output files), then against each other."""
    try:
        ledgers = [binding.check_side(label, binding.parse_resolved(Path(res).read_text()), Path(art))
                   for label, res, art in (("base", a.base_resolved, a.base_artifact), ("candidate", a.cand_resolved, a.cand_artifact))]
        binding.check_pair(*ledgers)
    except (binding.BindingError, OSError) as e:
        print(f"::error::{e}")
        return 1
    print("both runs are bound to the simulator and the ledger their commits pin")
    return 0


def cmd_unrecorded(a) -> int:
    """Succeeds only when every earlier successful gate run is already in the ledger on main. The gate pushes
    nothing, so a run's spend reaches the ledger when a maintainer commits its ledger.json; until then a
    second evaluation would be counted against a budget that does not yet show the first."""
    recorded = budget.recorded_run_ids(budget.load(Path(a.root) / budget.PATH))
    ids = {int(x) for x in Path(a.run_ids).read_text().split()}
    missing = sorted(ids - recorded)
    for i in missing:
        print(f"::error::gate run {i} succeeded but is not in state/gate/ledger.json; commit its ledger.json artifact first")
    return 1 if missing else 0


def cmd_contract_to_predictions(a) -> int:
    if not HEX40.match(a.candidate):
        raise SystemExit("--candidate is not a 40-hex commit")
    rows = list(csv.DictReader(Path(a.contract, "points.csv").read_text().splitlines()))
    by_id = {r["point_id"]: r for r in rows}
    out = []
    for uid in sorted(set(_read_lines(a.handed))):
        r = by_id.get(uid)
        vals = {}
        if r is not None:
            for col, v in r.items():
                if col.startswith("pred_") and v not in ("", None):
                    try:
                        vals[col[5:]] = float(v)
                    except ValueError:
                        pass
        out.append({"source": pd_.SOURCE, "unit_id": uid,
                    **({"values": vals} if vals else {"reason": "not scored by the harness" if r is None else "no prediction"})})
    harness = harness_digest(Path(a.contract, "provenance.json"))
    Path(a.out).write_text(json.dumps({"kind": pd_.KIND, "candidate": a.candidate, "harness": harness, "predictions": out},
                                      sort_keys=True))
    print(f"{len(out)} predictions written")
    return 0


def cmd_handed_units(a) -> int:
    skip = set()
    for name in ("fit", "anchor"):
        skip |= partition.load_published(a.ledger, name)
    ids = sorted(u.unit_id for u in partition.load_units(Path(a.ledger)) if u.unit_id not in skip)
    Path(a.out).write_text("\n".join(ids) + "\n")
    print(f"{len(ids)} units handed to the candidate run")
    return 0


def cmd_build_measured(a) -> int:
    units = {u.unit_id: u for u in partition.load_units(Path(a.ledger))}
    rows = list(csv.DictReader(Path(a.contract, "points.csv").read_text().splitlines()))
    metrics = sorted(c[5:] for c in rows[0] if c.startswith("meas_"))
    skip = set()
    for name in ("fit", "anchor"):
        skip |= partition.load_published(a.ledger, name)
    with open(a.out, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["point_id", *pr.LANE_FIELDS, *[f"meas_{m}" for m in metrics]])
        for r in sorted(rows, key=lambda r: r["point_id"]):
            u = units.get(r["point_id"])
            if u is None or u.unit_id in skip:
                continue
            i = u.identity
            w.writerow([u.unit_id, i["framework"], a.modelled_commit, i["hardware"], i["model"], i["configuration_hash"],
                        *[r[f"meas_{m}"] for m in metrics]])
    print("measured table written; sha256 " + hashlib.sha256(Path(a.out).read_bytes()).hexdigest())
    return 0


def cmd_evaluate(a) -> int:
    root, ledger = Path(a.root), Path(a.ledger)
    pre = pr.find(root, a.prereg)
    bud = budget.load(root / budget.PATH)
    n = budget.check_may_evaluate(bud, pre)
    cfg = partition.load_config(ledger)
    if pre["partition_version"] != cfg.partition_version:
        raise budget.Refused("the pre-registration names another partition version than the ledger's")
    seed = partition.seed_from_env(a.seed_env, cfg.seed_sha256)
    units = partition.load_units(ledger)
    legacy = partition.load_legacy_sides(ledger)
    assigned = partition.assign(units, cfg, seed, legacy)
    withheld = {u.unit_id for u in units} | {u.role_key for u in units}
    withheld |= {json.dumps(partition.role_key(u.identity), sort_keys=True, separators=(",", ":"), ensure_ascii=False) for u in units}
    withheld |= {os.environ.get(a.seed_env, "")}
    g = gd.Guard(withheld)
    try:
        measured = rd.load_measured(a.measured, pre["measured_sha256"])
        known = {u.unit_id for u in units}
        if set(measured) - known:
            raise rd.ReduceError("the measured table holds units that are not in the ledger")
        published = partition.load_published(ledger, "fit") | partition.load_published(ledger, "anchor")
        if set(measured) & published:
            raise rd.ReduceError("the measured table holds units on the published fit or anchor lists")
        want = set(measured)
        base = pd_.load(a.base_predictions, a.base, want)
        cand = pd_.load(a.candidate_predictions, a.candidate, want)
        if base.harness != cand.harness:
            raise pd_.PredictionsError("the base and the candidate ran under different harnesses; the same scenario seeds and replications are required")
        report = rd.reduce_report(pre, [{"unit_id": u.unit_id, "role_key": u.role_key} for u in units], assigned, measured, base, cand)
        report = {"kind": "WholeRunGateReport", "partition_version": cfg.partition_version, "preregistration": pre["id"],
                  "preregistration_sha256": pr.digest(pre), "base": a.base, "candidate": a.candidate, "harness": cand.harness,
                  "evaluation": n, "budget": bud["partitions"][str(cfg.partition_version)]["budget"], **report,
                  "notes": ["distribution distance is unjudged unless the candidate supplies per-request samples"]}
        g.check_report(report)
        comment = render_comment(report)
        if g.leaks(comment):
            raise gd.LeakError("the comment names a unit, a role key or the seed")
        nxt = budget.record(bud, pre["id"], pr.digest(pre), a.base, a.candidate, a.run_id, cfg.partition_version, report["verdict"])
    except (rd.ReduceError, pd_.PredictionsError, gd.LeakError, budget.Refused) as e:
        raise SystemExit(g.scrub(f"refused: {e}")) from None
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (out / "comment.md").write_text(comment)
    (out / "ledger.json").write_text(budget.dumps(nxt))
    print(g.scrub(f"{report['verdict']}: evaluation {n} of {report['budget']} for {pre['id']}; "
                  f"{sum(len(l['results']) for l in report['lanes'])} tests over {len(report['lanes'])} lanes"))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check-prereg"); p.add_argument("files", nargs="*"); p.add_argument("--root", default=str(ROOT)); p.set_defaults(f=cmd_check_prereg)
    p = sub.add_parser("check-ledger"); p.add_argument("--root", default=str(ROOT)); p.set_defaults(f=cmd_check_ledger)
    p = sub.add_parser("check-pr"); p.add_argument("--body-file", required=True); p.add_argument("--changes-file", required=True)
    p.add_argument("--root", default=str(ROOT)); p.add_argument("--base-root", default=None); p.set_defaults(f=cmd_check_pr)
    p = sub.add_parser("unrecorded"); p.add_argument("--run-ids", required=True); p.add_argument("--root", default=str(ROOT)); p.set_defaults(f=cmd_unrecorded)
    p = sub.add_parser("read-sim-pin"); p.add_argument("--pins-file", required=True); p.set_defaults(f=cmd_read_sim_pin)
    p = sub.add_parser("ledger-digest"); p.add_argument("--ledger", required=True); p.set_defaults(f=cmd_ledger_digest)
    p = sub.add_parser("check-binding"); p.add_argument("--base-resolved", required=True); p.add_argument("--base-artifact", required=True)
    p.add_argument("--cand-resolved", required=True); p.add_argument("--cand-artifact", required=True); p.set_defaults(f=cmd_check_binding)
    p = sub.add_parser("contract-to-predictions"); p.add_argument("--contract", required=True); p.add_argument("--handed", required=True)
    p.add_argument("--candidate", required=True); p.add_argument("--out", required=True); p.set_defaults(f=cmd_contract_to_predictions)
    p = sub.add_parser("handed-units"); p.add_argument("--ledger", required=True); p.add_argument("--out", required=True); p.set_defaults(f=cmd_handed_units)
    p = sub.add_parser("build-measured"); p.add_argument("--contract", required=True); p.add_argument("--ledger", required=True)
    p.add_argument("--modelled-commit", required=True); p.add_argument("--out", required=True); p.set_defaults(f=cmd_build_measured)
    p = sub.add_parser("evaluate"); p.add_argument("--root", default=str(ROOT)); p.add_argument("--ledger", required=True)
    p.add_argument("--prereg", required=True); p.add_argument("--measured", required=True)
    p.add_argument("--base-predictions", required=True); p.add_argument("--candidate-predictions", required=True)
    p.add_argument("--base", required=True); p.add_argument("--candidate", required=True); p.add_argument("--run-id", required=True, type=int)
    p.add_argument("--seed-env", default="LEDGER_SEED"); p.add_argument("--out", required=True); p.set_defaults(f=cmd_evaluate)
    a = ap.parse_args(argv)
    try:
        return a.f(a)
    except (budget.Refused, pr.PreRegistrationError, partition.PartitionError) as e:
        raise SystemExit(f"refused: {e}") from None
    except Exception as e:
        if a.cmd != "evaluate":
            raise
        raise SystemExit(f"internal error ({type(e).__name__}); the details are withheld") from None


if __name__ == "__main__":
    sys.exit(main())
