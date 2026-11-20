#!/usr/bin/env python3
"""The M3 InferenceX baseline, per lane, with every point's grade ceiling (design §11.3, §11.6; COV-4, COV-9, COV-11).

Two lanes: vLLM, whose points the scoring harness scores, and SGLang, whose points it grades and cannot yet score
(no SGLang engine exists in BLIS). For each lane the report gives the in-scope points, the scored points, the points
not scored by reason with the issue each reason cites, ordered by points blocked (§11.6), the grade distribution G1 to
G5 with each grade's share, count and own accuracy (COV-11), and each point's grade ceiling with the reason
(ceiling.py), so "not yet" is told from "not possible with this data".

    m3_baseline.py sglang-lane --rows ROWS.json --today YYYY-MM-DD --ledger LEDGER --fields FIELDS --stack STACK
                               --catalog DIR --registry DIR --out LANE.json
    m3_baseline.py issues --fields FIELDS --source TEXT --issues ISSUES.json
    m3_baseline.py report --contract DIR --sglang-lane LANE.json --ported PORTED.json --issues ISSUES.json
                          --engines ENGINES.json --out PREFIX [--recoverable RECOVERABLE.json]
                          [--funnel FUNNEL.json]
    m3_baseline.py engines --sglang-provenance BLIS_SGLANG/provenance.go --sglang-source TEXT
                           --routers SUBSTRATE/catalog/routers --routers-source TEXT --out ENGINES.json

`report --funnel` adds the scoring funnels of funnel.py and the scored count.
`report --recoverable` adds, from recoverable.py's output, the count of anchor units whose inputs are recoverable
(plan row 12); without it the report is unchanged.

`engines` records the SGLang release blis-sglang's provenance names (its `Upstream` Version) and the router table's
entries (router, mode, policy), with the commits they were read at, so the report reads neither from a flag.

`sglang-lane` grades the SGLang units of the window with the scorer's own code and no simulator (coverage.py's
offline path), and writes one line per unit: its id, chip, release and G5 reasons, nothing measured. `issues`
copies, from the engine's field list, the issue each not-modelled field cites (the reasons that are not a field
are written in the same file by hand). `report` is a pure function of committed files: the vLLM lane's contract
directory, the SGLang lane file, the ported-function comparison (ported_changes.py) and the issue file; the test
regenerates the committed report from them.

Accuracy figures follow the evaluation protocol: test and prospective points of the development split are withheld
from every figure, and counts include every point (docs/m2/evaluation-protocol.md, section 6).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "ingest"))
import ceiling as cl  # noqa: E402
import compare as cmp  # noqa: E402
import funnel as fnl  # noqa: E402
import grade as gr  # noqa: E402
import recoverable as rcv  # noqa: E402

FORMAT = "m3-baseline-1"
LANES = ("vllm", "sglang")
# An official SGLang image names its release in the tag, with an optional post release and the build's CUDA or ROCm
# variant: lmsysorg/sglang:v0.5.22-cu130, lmsysorg/sglang-rocm:v0.5.12.post1-rocm720-mi35x-20260523. Any other image
# (a nightly, a dev or model branch, another repository) is a nightly or custom build.
_SGLANG_IMAGE = re.compile(r"^lmsysorg/sglang(?:-rocm)?:v(\d+\.\d+\.\d+(?:\.post\d+)?)(?:-(?:cu\d+|rocm\S*))?$")


class BaselineError(ValueError):
    pass


def sglang_release(image: str | None) -> str | None:
    m = _SGLANG_IMAGE.match((image or "").split("@", 1)[0])
    return m.group(1) if m else None


# ------------------------------------------------------------------------------------------- the SGLang lane

def sglang_lane(*, rows: list[dict], today: str, ledger: Path, fields: Path, stack: Path, catalog: Path,
                registry: Path, window_days: int = 180) -> dict:
    """Every SGLang unit of the window, graded by the scorer with no simulator (score_points(simulate=False), as
    coverage.py grades a window). SGLang units fetch no artifacts, so no pull is read."""
    import tempfile
    from datetime import date
    import api
    import coverage as cv
    import engines
    import ledger as ldg
    import score as sc
    start, end = api.window_bounds(date.fromisoformat(today), window_days)
    window = [start.isoformat(), end.isoformat()]
    lane_rows = [r for r in cv.window_rows(rows, window) if engines.lookup(r["framework"]).engine == engines.SGLANG]
    lg = ldg.load(ledger)
    placed, differing = cv.place_all(lane_rows, lg)
    env = cv.make_env(fields_path=fields, stack_path=stack, catalog=catalog, registry=registry, base_models={})
    with tempfile.TemporaryDirectory() as tmp:
        entries, missing = cv.entries_for(placed, {}, Path(tmp), Path(tmp))
        if missing:
            raise BaselineError(f"{len(missing)} SGLang units want artifacts; the lane fetches none")
        outcomes = sc.score_points(entries, Path(tmp), Path(tmp) / "work", env, simulate=False)
    images = {p.point_id: p.row.get("image") for p in placed.points}
    units = []
    for o in sorted(outcomes, key=lambda o: o.point_id):
        if o.fidelity is not None or o.faults:
            raise BaselineError(f"SGLang unit {o.point_id} was not held at G5; the lane has no engine to score it")
        units.append({"point_id": o.point_id, "framework": o.row["framework"], "hardware": o.row["hardware"],
                      "benchmark_type": o.row["benchmark_type"], "measured_date": str(o.row["date"])[:10],
                      "image": (images[o.point_id] or "").split("@", 1)[0] or None,
                      "run_release": sglang_release(images[o.point_id]),
                      "g5_reasons": sorted([r["code"], r.get("subject", "")] for r in o.g5_reasons)})
    return {"format": "m3-sglang-lane-1", "window": window, "today": today,
            "rows": {"in_window": len(lane_rows), "in_a_unit": len(lane_rows) - len(placed.unlisted),
                     "no_unit": dict(sorted(Counter(x["reason"] for x in placed.unlisted).items())),
                     "differs_from_source_revision": len(differing)},
            "units": units}


# ------------------------------------------------------------------------------------------- engines

_UPSTREAM_VERSION = re.compile(r"var Upstream = [\w.]+\{[^}]*?Version:\s*\"(\d+\.\d+\.\d+)\"", re.S)


def engines_doc(provenance_go: str, sglang_source: str, routers_dir: Path, routers_source: str) -> dict:
    m = _UPSTREAM_VERSION.search(provenance_go)
    if not m:
        raise BaselineError("the SGLang provenance file states no Upstream Version")
    import yaml
    entries = []
    for f in sorted(routers_dir.glob("*.yaml")):
        d = yaml.safe_load(f.read_text())
        entries.append({"router": d["router"], "mode": d["mode"], "policy": d.get("policy"), "file": f.name})
    if not entries:
        raise BaselineError(f"{routers_dir} holds no router table entry")
    return {"sglang": {"version": m.group(1), "source": sglang_source},
            "routers": {"entries": entries, "source": routers_source}}


# ------------------------------------------------------------------------------------------- issues

def field_issues(fields_doc: dict, only: set[str] | None = None) -> dict:
    """The issue each not-modelled field of the engine's list cites (evidence.issue), for the fields in `only` (the
    fields some point's reason names) when given."""
    out = {}
    for f in fields_doc["fields"]:
        issue = (f.get("evidence") or {}).get("issue")
        if issue and f.get("status") != "modelled" and (only is None or f["name"] in only):
            out[f["name"]] = issue
    return dict(sorted(out.items()))


def reason_fields(contract: Path, lane: dict) -> set[str]:
    """Every field a G5 reason of the contract or the lane names."""
    out = set()
    for r in cmp._lines(contract / "not_scored.jsonl"):
        out |= {g.get("subject", "") for g in r["g5_reasons"] if g["code"].startswith("field_")}
    for u in lane["units"]:
        out |= {s for c, s in u["g5_reasons"] if c.startswith("field_")}
    return out


def refusal_issue(text: str | None, issues: dict) -> tuple[str, str | None]:
    """A point the simulator refused: its refusal class (the first rule of the issue file whose text the refusal
    contains) and the issue that rule cites."""
    for rule in issues.get("refusals") or []:
        if text and rule["contains"] in text:
            return rule["class"], rule["issue"]
    return (text or "no refusal text")[:80], None


def issue_for(entry: str, issues: dict) -> str | None:
    """The issue an entry of the refusal list cites: a field's from the engine's list, else the hand-written one
    (by the whole entry, then by its code)."""
    code, _, subject = entry.partition(":")
    if code in ("field_not_modelled", "field_unclassified"):
        hit = issues["fields"]["issues"].get(subject)
        if hit:
            return hit
    reasons = issues.get("reasons") or {}
    e = reasons.get(entry) or reasons.get(code)
    if e is None:
        return None
    return e.get("issue") or f"{e['limit']}: {e.get('why', '')}".rstrip(": ")


def classes_of(issues: dict) -> dict:
    """Each reason's class for the ceiling (ceiling.CLASSES), from the same entries that name its issue."""
    return {k: v["limit"] for k, v in (issues.get("reasons") or {}).items()}


def check_issue_classes(issues: dict) -> list[str]:
    """The issue file's two statements about a reason agree: a reason a BLIS issue removes (blis, estimate, router)
    cites that issue; a limit of the data, or a record the source holds, cites none and says why."""
    out = []
    for k, v in sorted((issues.get("reasons") or {}).items()):
        if v.get("limit") not in cl.CLASSES:
            out.append(f"{k}: limit {v.get('limit')!r} is not one of {cl.CLASSES}")
        elif v["limit"] in ("blis", "estimate", "router") and not v.get("issue"):
            out.append(f"{k}: a {v['limit']} reason cites no issue")
        elif v["limit"] in ("data", "source") and (v.get("issue") or not v.get("why")):
            out.append(f"{k}: a {v['limit']} reason cites a BLIS issue or says no why")
    return out


# ------------------------------------------------------------------------------------------- the report

def _points_of_lane(lane: dict) -> list[dict]:
    pts = []
    for u in lane["units"]:
        pts.append({"id": u["point_id"], "status": "not_scored", "grade": gr.G5, "hardware": u["hardware"],
                    "framework": u["framework"], "run_release": u["run_release"],
                    "g5_reasons": [tuple(r) for r in u["g5_reasons"]], "substitutions": []})
    return pts


def _vllm_points(run: cmp.Run) -> list[dict]:
    d = run.dir
    fid = {r["point_id"]: r for r in cmp._lines(d / "fidelity.jsonl")}
    release = {r["point_id"]: r.get("run_release") for f in ("not_scored.jsonl", "failed.jsonl")
               for r in cmp._lines(d / f)}
    for pid, p in run.points.items():
        if pid in fid:
            p["run_release"], p["args"] = fid[pid].get("run_release"), fid[pid].get("args") or []
        else:
            p["run_release"] = release.get(pid)
    return list(run.points.values())


def refused(points: list[dict], issues: dict) -> list[dict]:
    """Every reason an in-scope point is not scored (its G5 reasons, or the faults of a point the simulator refused),
    with blocks (points carrying it), alone (points whose only reason it is) and the issue it cites, ordered by points
    blocked (design §11.6)."""
    ins = [p for p in points if p["status"] != "scored" and cmp.scope(p["hardware"]) == cmp.SCOPE_IN]
    cited = {}

    def classed(p):
        if p["status"] != "failed":
            return p
        cls, issue = refusal_issue(p.get("error"), issues)
        out = {**p, "g5_reasons": [(c, f"{s}: {cls}") for c, s in p["g5_reasons"]]}
        cited.update({f"{c}:{s}": issue for c, s in out["g5_reasons"]})
        return out
    ins = [classed(p) for p in ins]
    rows = sorted(cmp.reasons(ins).items(), key=lambda kv: (-kv[1]["blocks"], -kv[1]["alone"], kv[0]))
    return [{"reason": k, **v, "issue": cited.get(k) or issue_for(k, issues)} for k, v in rows]


def ceilings(points: list[dict], engine_version: str, ported: dict | None, issues: dict, routers: list[dict],
             engine: str) -> dict[str, dict]:
    classes = classes_of(issues)
    try:
        return {p["id"]: cl.ceiling(p, engine_version=engine_version, ported=ported, classes=classes, routers=routers,
                                    engine=engine) for p in points}
    except cl.CeilingError as e:
        raise BaselineError(str(e)) from None


def ceiling_summary(points: list[dict], ceil: dict[str, dict]) -> dict:
    ins = [p for p in points if cmp.scope(p["hardware"]) == cmp.SCOPE_IN]
    matrix = defaultdict(Counter)
    state, limits = Counter(), Counter()
    for p in ins:
        c = ceil[p["id"]]
        matrix[c["grade"]][c["ceiling"] + ("?" if c["ceiling_is_upper_bound"] else "")] += 1
        state[c["state"]] += 1
        for lim in c["limits"]:
            # a limit is counted by its code, without the free-text subject a value_conflict carries
            limits[(lim["cap"], lim["code"] if not lim["code"].startswith("value_conflict:model") else "value_conflict:model")] += 1
    rows = ("G1", "G2", "G3", "G4", "G5", "failed")
    cols = [k for g in cl.ORDER for k in (g, g + "?") if k in cl.ORDER or any(matrix[r][k] for r in matrix)]
    return {"points": len(ins), "columns": cols,
            "matrix": {g: {k: matrix[g][k] for k in cols} for g in rows if matrix[g]},
            "by_ceiling": {k: sum(matrix[g][k] for g in matrix) for k in cols},
            "state": {"at_ceiling": state["at_ceiling"], "not_yet": state["not_yet"]},
            "upper_bound_only": sum(1 for p in ins if ceil[p["id"]]["ceiling_is_upper_bound"]),
            "limits": [{"cap": cap, "limit": code, "points": n}
                       for (cap, code), n in sorted(limits.items(), key=lambda kv: (-kv[1], kv[0]))]}


def substitution_kinds(points: list[dict]) -> list[dict]:
    """Per substitution kind, the in-scope scored points that carry it and how many distinct subjects it names, so the
    fidelity gaps of the scored points are visible (each is also a limit or a piece of not-yet work of the ceiling)."""
    ins = [p for p in points if p["status"] == "scored" and cmp.scope(p["hardware"]) == cmp.SCOPE_IN]
    pts, subjects = Counter(), defaultdict(set)
    for p in ins:
        kinds = set()
        for s in p.get("substitutions") or []:
            kinds.add(s["kind"])
            subjects[s["kind"]].add(s.get("subject", ""))
        pts.update(kinds)
    return [{"kind": k, "points": n, "subjects": len(subjects[k])}
            for k, n in sorted(pts.items(), key=lambda kv: (-kv[1], kv[0]))]


def lane_report(points: list[dict], *, issues: dict, engine_version: str, ported: dict | None, source: dict,
                accuracy: bool, routers: list[dict] = (), engine: str = "vLLM") -> tuple[dict, dict]:
    ins = [p for p in points if cmp.scope(p["hardware"]) == cmp.SCOPE_IN]
    ceil = ceilings(points, engine_version, ported, issues, list(routers), engine)
    grades = Counter(p["grade"] for p in ins)
    out = {"source": source, "engine_release": engine_version, "points": len(points), "in_scope": len(ins),
           "out_of_scope": len(points) - len(ins),
           "scored": sum(p["status"] == "scored" for p in ins),
           "not_scored": sum(p["status"] == "not_scored" for p in ins),
           "refused_by_simulator": sum(p["status"] == "failed" for p in ins),
           "grades": {g: grades.get(g, 0) for g in (*gr.GRADES, "failed")},
           "refused": refused(points, issues), "ceilings": ceiling_summary(points, ceil),
           "substitution_kinds": substitution_kinds(points)}
    if accuracy:
        out["by_grade"] = cmp.by_grade(ins)
        out["headline"] = cmp.accuracy([p for p in ins if p["grade"] in gr.GRADED])
    return out, ceil


def report(*, contract: Path, splits: Path | None, sglang: dict, ported: dict, issues: dict, engines: dict,
           recoverable: dict | None = None, funnel: dict | None = None) -> tuple[dict, dict]:
    bad = check_issue_classes(issues)
    if bad:
        raise BaselineError("the issue file's reasons disagree with their classes: " + "; ".join(bad))
    run = cmp.Run(contract, splits)
    run.withhold(False)
    engine = (run.prov.get("engine") or {}).get("version")
    releases = {p.get("run_release") for p in _vllm_points(run)} - {None, engine}
    missing = sorted(releases - set(ported.get("releases") or {}))
    if missing:
        raise BaselineError(f"the ported-function comparison holds no comparison for vLLM {', '.join(missing)}, which "
                            f"the contract's runs used: generate it with --release for each")
    if ported.get("engine_release") != engine:
        raise BaselineError(f"the ported-function comparison is against vLLM {ported.get('engine_release')}, "
                            f"the run's simulator runs {engine}")
    if issues["fields"].get("sha256") != run.prov.get("fields_sha256"):
        raise BaselineError(f"the issue file's field list (sha256 {issues['fields'].get('sha256')}) is not the one the "
                            f"run was scored with ({run.prov.get('fields_sha256')})")
    vsrc = {"contract": str(contract), "harness_commit": run.prov.get("harness_commit"), "simulator": (run.prov.get("simulator") or {}).get("build"),
            "catalog": (run.prov.get("blis") or {}).get("catalog"), "fields_sha256": run.prov.get("fields_sha256"),
            "pull_manifest_sha256": run.prov.get("pull_manifest_sha256"), "experimental": run.prov.get("experimental"),
            "point_set_sha256": cmp.id_set_sha256(run.points)}
    routers = engines["routers"]["entries"]
    vllm, vceil = lane_report(_vllm_points(run), issues=issues, engine_version=engine, ported=ported, source=vsrc,
                              accuracy=True, routers=routers, engine="vLLM")
    ssrc = {"window": sglang["window"], "today": sglang["today"], "rows": sglang["rows"],
            "graded_by": "the scorer's offline path (coverage.py: score_points with no simulator)"}
    sg, sceil = lane_report(_points_of_lane(sglang), issues=issues, engine_version=engines["sglang"]["version"],
                            ported=None, source=ssrc, accuracy=False, routers=routers, engine="SGLang")
    doc = {"format": FORMAT, "lanes": {"vllm": vllm, "sglang": sg},
           "ported_functions": {"engine_release": ported["engine_release"], "port": ported["port"],
                                "releases": {r: len(e["changed"]) for r, e in ported["releases"].items()},
                                "cited": len(ported["cited"])},
           "issues_fields_source": issues["fields"].get("source"),
           "engines_source": {"sglang": engines["sglang"]["source"], "routers": engines["routers"]["source"]}}
    if recoverable is not None:
        try:
            doc["recoverable"] = rcv.check(recoverable)
        except rcv.RecoverableError as e:
            raise BaselineError(str(e))
    if funnel is not None:
        try:
            doc["funnel"] = fnl.validate(funnel)
        except fnl.FunnelError as e:
            raise BaselineError(str(e))
    per_point = {"vllm": vceil, "sglang": sceil}
    return doc, per_point


# ------------------------------------------------------------------------------------------- markdown

def _n(x):
    return "-" if x is None else str(x)


def _share(n, total):
    import headline as hl
    return hl.TOO_FEW if n < hl.MIN_POINTS else f"{100 * n / total:.1f}%"


def _recoverable_markdown(r: dict) -> list[str]:
    t = rcv.totals(r)
    L = ["## Anchor units whose inputs are recoverable (requirements §3A.8)", "",
         f"Checked on {r['checked_on']} against the ledger at `{r['source']['ledger_revision']}` and the anchor list "
         f"(sha256 `{r['source']['anchor_list_sha256']}`), without simulating. {r['source']['meaning']}", "",
         f"**{t['recoverable']} of {t['counted']} counted anchor units have recoverable inputs** "
         f"({r['anchor_units']} anchor units, {t['excluded']} excluded).", "",
         "| Part | Units | Source or reason |", "|---|---|---|"]
    for key, label in ((rcv.RECOVERABLE, "Recoverable"), (rcv.NOT_RECOVERED, "Not recovered"), (rcv.EXCLUDED, "Excluded")):
        for detail, n in r[key].items():
            L.append(f"| {label} | {n} | `{detail}` |")
    return L + [""]


def markdown(doc: dict) -> str:
    v, s = doc["lanes"]["vllm"], doc["lanes"]["sglang"]
    L = ["# M3 InferenceX baseline", "",
         "Generated by `orchestrator/baseline/m3_baseline.py report` from committed files; do not edit by hand. "
         "How to read it: [README.md](README.md).", "",
         "## The two lanes", "",
         "| | vLLM | SGLang |", "|---|---|---|",
         f"| Engine release BLIS runs (G1 needs a run on it) | {v['engine_release']} | {s['engine_release']} (the release blis-sglang's provenance names; no engine yet) |",
         f"| Points | {v['points']} | {s['points']} |",
         f"| In scope (not AMD or TPU) | {v['in_scope']} | {s['in_scope']} |",
         f"| Scored, G1 to G4 | {v['scored']} | {s['scored']} |",
         f"| Refused by the simulator (failed) | {v['refused_by_simulator']} | {s['refused_by_simulator']} |",
         f"| Not scored, G5 | {v['not_scored']} | {s['not_scored']} |", ""]
    L += ["## Grades of the in-scope points (COV-11)", "",
          "Each grade's count, its share of the in-scope points, and its own accuracy. Accuracy is over the train and "
          "validation points of the development split; test points are withheld (their count is stated).", "",
          "| Lane | Grade | Points | Share | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % | Withheld (test) |",
          "|---|---|---|---|---|---|---|---|---|"]
    for name, lane in (("vLLM", v), ("SGLang", s)):
        for g in (*gr.GRADES, "failed"):
            n = lane["grades"][g]
            acc = (lane.get("by_grade") or {}).get(g, {}).get("accuracy")
            cells = cmp._acc_cells(acc) if acc else "- | - | - | -"
            wh = acc["withheld"] if acc else "-"
            L.append(f"| {name} | {g} | {n} | {_share(n, lane['in_scope']) if lane['in_scope'] else '-'} | {cells} | {wh} |")
    h = v["headline"]
    L += ["", f"Headline, vLLM lane, every graded in-scope point (G1 to G4): {h['points']} points with figures "
          f"({h['withheld']} test points withheld); TTFT MAPE {cmp._f(h['ttft']['mape'])} (n={h['ttft']['mape']['n']}), "
          f"TPOT MAPE {cmp._f(h['tpot']['mape'])} (n={h['tpot']['mape']['n']}). The SGLang lane has no graded point.", ""]
    L += ["## Grade ceilings", "",
          "The ceiling is the best grade a point's recorded data allows if every piece of BLIS work it needs were done "
          "(`orchestrator/baseline/ceiling.py`). *At ceiling*: only new data raises the point. *Not yet*: BLIS work "
          "holds it below its ceiling. Rows are the grade today, columns the ceiling; in-scope points. A ceiling marked "
          "`?` is an upper bound: the data cannot decide between it and a worse one (no ported-function comparison "
          "exists, or a router's mode is not recorded).", ""]
    for name, lane in (("vLLM", v), ("SGLang", s)):
        c = lane["ceilings"]
        ub = (f" For {c['upper_bound_only']} points the ceiling is only an upper bound: no comparison of the ported "
              f"functions exists, so G3 or only G4 is unknown until the port exists." if c["upper_bound_only"] else "")
        L += [f"**{name}**: {c['state']['at_ceiling']} points at their ceiling, {c['state']['not_yet']} not yet.{ub}", "",
              "| Grade today | " + " | ".join(f"ceiling {k}" for k in c["columns"]) + " |", "|---|" + "---|" * len(c["columns"])]
        for g, row in c["matrix"].items():
            L.append(f"| {g} | " + " | ".join(str(row[k]) for k in c["columns"]) + " |")
        L.append("| all | " + " | ".join(str(c["by_ceiling"][k]) for k in c["columns"]) + " |")
        L += ["", "| Limit (from the data) | Caps at | Points |", "|---|---|---|"]
        L += [f"| `{x['limit']}` | {x['cap']} | {x['points']} |" for x in c["limits"]]
        L.append("")
    L += ["## Substitutions on the scored points", "",
          "Per kind, the in-scope scored points that carry it, and how many subjects it names: what each scored point's "
          "scenario does not take from the run's own records (design §11.2, §11.3). The SGLang lane has no scored point.", "",
          "| Kind | Points (of " + str(v["scored"]) + ") | Subjects |", "|---|---|---|"]
    L += [f"| `{x['kind']}` | {x['points']} | {x['subjects']} |" for x in v["substitution_kinds"]]
    L.append("")
    pf = doc["ported_functions"]
    L += [f"The ported-function comparison reads {pf['cited']} upstream functions that blis-vllm "
          f"`{pf['port']['commit']}` cites in its provenance headers; between each run release and vLLM "
          f"{pf['engine_release']} this many changed: " + ", ".join(f"{r} {n}" for r, n in pf["releases"].items()) + ".", ""]
    for name, lane in (("vLLM", v), ("SGLang", s)):
        L += [f"## Why {name} points are not scored, by points blocked (design §11.6)", "",
              "In-scope points. Blocks: points carrying the reason. Alone: points whose only reason it is.", "",
              "| Reason | Blocks | Alone | Issue |", "|---|---|---|---|"]
        L += [f"| `{r['reason']}` | {r['blocks']} | {r['alone']} | {r['issue'] or 'none cited'} |" for r in lane["refused"]]
        L.append("")
    if "recoverable" in doc:
        L += _recoverable_markdown(doc["recoverable"])
    if "funnel" in doc:
        L += fnl.markdown(doc["funnel"])
    return "\n".join(L) + "\n"


def ceilings_jsonl(per_point: dict) -> str:
    lines = []
    for lane in LANES:
        for pid in sorted(per_point[lane]):
            c = per_point[lane][pid]
            lines.append(json.dumps({"lane": lane, "point_id": pid, "grade": c["grade"], "ceiling": c["ceiling"],
                                     "state": c["state"], "limits": [f"{x['cap']} {x['code']}" for x in c["limits"]],
                                     "ceiling_is_upper_bound": c["ceiling_is_upper_bound"],
                                     "not_yet": c["not_yet"]}, sort_keys=True))
    return "\n".join(lines) + "\n"


def write(prefix: Path, doc: dict, per_point: dict) -> None:
    prefix.parent.mkdir(parents=True, exist_ok=True)
    Path(f"{prefix}.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    Path(f"{prefix}.md").write_text(markdown(doc))
    (prefix.parent / "ceilings.jsonl").write_text(ceilings_jsonl(per_point))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sglang-lane")
    for k in ("rows", "ledger", "fields", "stack", "catalog", "registry", "out"):
        s.add_argument(f"--{k}", required=True, type=Path)
    s.add_argument("--today", required=True)
    i = sub.add_parser("issues")
    i.add_argument("--fields", required=True, type=Path)
    i.add_argument("--source", required=True, help="the field list's repository and commit, as text")
    i.add_argument("--issues", required=True, type=Path)
    i.add_argument("--contract", required=True, type=Path, help="keep the fields the contract's reasons name")
    i.add_argument("--sglang-lane", required=True, type=Path, help="and those the SGLang lane's reasons name")
    r = sub.add_parser("report")
    for k in ("contract", "sglang-lane", "ported", "issues", "out"):
        r.add_argument(f"--{k}", required=True, type=Path)
    r.add_argument("--splits", type=Path)
    r.add_argument("--recoverable", type=Path, help="recoverable.py's output: adds the count of anchor units whose "
                                                    "inputs are recoverable")
    r.add_argument("--funnel", type=Path, help="funnel.py's output: adds the InferenceX and configiq scoring funnels "
                                               "and the scored count")
    r.add_argument("--engines", required=True, type=Path)
    e = sub.add_parser("engines")
    e.add_argument("--sglang-provenance", required=True, type=Path)
    e.add_argument("--sglang-source", required=True)
    e.add_argument("--routers", required=True, type=Path)
    e.add_argument("--routers-source", required=True)
    e.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "sglang-lane":
            doc = sglang_lane(rows=json.loads(a.rows.read_text()), today=a.today, ledger=a.ledger, fields=a.fields,
                              stack=a.stack, catalog=a.catalog, registry=a.registry)
            a.out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
            print(f"wrote {a.out}: {len(doc['units'])} SGLang units")
        elif a.cmd == "engines":
            doc = engines_doc(a.sglang_provenance.read_text(), a.sglang_source, a.routers, a.routers_source)
            a.out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
            print(f"wrote {a.out}: SGLang {doc['sglang']['version']}, {len(doc['routers']['entries'])} router entries")
        elif a.cmd == "issues":
            raw = a.fields.read_bytes()
            doc = json.loads(a.issues.read_text()) if a.issues.is_file() else {"reasons": {}}
            doc["fields"] = {"source": a.source, "sha256": hashlib.sha256(raw).hexdigest(),
                             "issues": field_issues(json.loads(raw), reason_fields(
                                 a.contract, json.loads(a.sglang_lane.read_text())))}
            a.issues.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
            print(f"wrote {a.issues}: {len(doc['fields']['issues'])} field issues")
        else:
            doc, per_point = report(contract=a.contract, splits=a.splits, sglang=json.loads(a.sglang_lane.read_text()),
                                    ported=json.loads(a.ported.read_text()), issues=json.loads(a.issues.read_text()),
                                    engines=json.loads(a.engines.read_text()),
                                    recoverable=json.loads(a.recoverable.read_text()) if a.recoverable else None,
                                    funnel=json.loads(a.funnel.read_text()) if a.funnel else None)
            write(a.out, doc, per_point)
            print(f"wrote {a.out}.json, {a.out}.md and ceilings.jsonl")
    except (BaselineError, cmp.CompareError) as e:
        print(f"m3_baseline: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
