"""Before/after comparison of two scored runs (M2 release plan; design §11.3, §11.6).

A run is a contract directory (orchestrator/ingest/CONTRACT.md) that harness/run.sh wrote. This
tool reads two of them and writes one table, as JSON and as Markdown. It refuses to compare
runs that differ in anything except the simulator, catalog, registry and field list, because a
difference in the harness, the units, the pull or the sample would make the movement a
statement about those and not about the change under test:

  - the harness commit must be the same, and each run's points must all name it;
  - the units file (its sha256) must be the same;
  - the frozen pull (pull_manifest_sha256) must be the same;
  - the point set (sha256 of the sorted ids of every point, scored or not) must be the same;
  - both runs carry one sample label, in_sample or held_out, and it must be the same.

`check_table` applies the same rules to a table already written, so a committed table that
mixes them fails the tests (test_compare.py, test_committed_tables).

Accuracy is reported by grade (the headline is G1 to G4), for the points scored in both runs
apart from the points scored in one only. A figure over fewer than headline.MIN_POINTS points
is "too few points". The noise floor is the documented fallback (build_summary.
FALLBACK_NOISE_FLOOR_PCT): summary v3 measures none per point.

AMD (mi300x, mi325x, mi355x) and TPU rows are out of scope for M2 to M4 (plan v64). The tables
count them apart from the in-scope points; the scorer's reason codes are not changed.

    compare.py run  --dir DIR --sample in_sample [--out PREFIX]
    compare.py pair --before DIR --after DIR --sample in_sample [--out PREFIX]
    compare.py check TABLE.json [TABLE.json ...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORCH = HERE.parent
sys.path.insert(0, str(ORCH))
sys.path.insert(0, str(ORCH / "ingest"))
import build_summary as bs  # noqa: E402
import backlog as bl  # noqa: E402
import grade as gr  # noqa: E402
import headline as hl  # noqa: E402

SAMPLES = ("in_sample", "held_out")
SAMPLE_TEXT = {
    "in_sample": "IN-SAMPLE: the points are the ones the model was calibrated on or tuned against; "
                 "there is no anchor list yet, so no point is held out. These figures say how well "
                 "the simulator reproduces data it has seen, not how well it predicts new data.",
    "held_out": "HELD-OUT: every point is on the published anchor list's held-out side.",
}
OUT_OF_SCOPE_CHIPS = ("mi300x", "mi325x", "mi355x")
OUT_OF_SCOPE_PREFIXES = ("tpu",)
SCOPE_IN, SCOPE_OUT = "in_scope", "out_of_scope"
FORMAT = "baseline-compare-1"


class CompareError(ValueError):
    """The runs (or a table) break a rule of the comparison."""


def scope(hardware: str) -> str:
    h = (hardware or "").lower()
    return SCOPE_OUT if h in OUT_OF_SCOPE_CHIPS or h.startswith(OUT_OF_SCOPE_PREFIXES) else SCOPE_IN


def _lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def id_set_sha256(ids) -> str:
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


class Run:
    """One contract directory, read into per-point records."""

    def __init__(self, directory):
        import csv
        d = self.dir = Path(directory)
        self.prov = json.loads((d / "provenance.json").read_text())
        facets = json.loads((d / "facets.json").read_text())
        fidelity = {r["point_id"]: r for r in _lines(d / "fidelity.jsonl")}
        self.points: dict[str, dict] = {}
        with open(d / "points.csv", newline="") as fh:
            for r in csv.DictReader(fh):
                pid = r["point_id"]
                f, fid = facets[pid], fidelity[pid]
                self.points[pid] = {
                    "id": pid, "status": "scored", "grade": r["grade"], "hardware": f["gpu"],
                    "model": f["model"], "framework": f["framework"], "precision": f["precision"],
                    "spec": f.get("spec_method") or "none", "sweep": (r["scenario"], r["label"]),
                    "concurrency": int(r["concurrency"]), "date": r["measured_date"],
                    **{k: float(r[k]) for k in ("meas_ttft_us", "pred_ttft_us", "meas_tpot_us", "pred_tpot_us")},
                    "substitutions": fid["substitutions"], "g5_reasons": [],
                    "harness_commit": (fid.get("simulator") or {}).get("harness_commit")}
        for n in _lines(d / "not_scored.jsonl"):
            self.points[n["point_id"]] = {
                "id": n["point_id"], "status": "not_scored", "grade": gr.G5, "hardware": n["hardware"],
                "model": n["model"], "framework": n["framework"], "precision": n["precision"],
                "g5_reasons": [(r["code"], r.get("subject", "")) for r in n["g5_reasons"]],
                "substitutions": [], "harness_commit": (n.get("simulator") or {}).get("harness_commit")}
        for n in _lines(d / "failed.jsonl"):
            ident = n.get("identity") or {}
            self.points[n["point_id"]] = {
                "id": n["point_id"], "status": "failed", "grade": "failed", "hardware": ident.get("hardware", ""),
                "model": ident.get("model", ""), "framework": ident.get("framework", ""),
                "precision": ident.get("precision", ""),
                "g5_reasons": [tuple(f.split(":", 1)) if ":" in f else (f, "") for f in n.get("faults") or []],
                "substitutions": [], "harness_commit": None}
        if len(self.points) != self.prov["points"]:
            raise CompareError(f"{d}: {len(self.points)} points in the files, {self.prov['points']} in provenance.json")

    def identity(self, sample: str) -> dict:
        p = self.prov
        units = p.get("units") or {}
        return {"harness_commit": p.get("harness_commit"), "units_sha256": units.get("sha256"),
                "units_count": units.get("count"), "pull_manifest_sha256": p.get("pull_manifest_sha256"),
                "point_set_sha256": id_set_sha256(self.points), "points": len(self.points), "sample": sample}

    def inputs(self) -> dict:
        """What may differ between the two runs of a pair: the change under test."""
        p = self.prov
        return {"simulator": p.get("simulator"), "blis": p.get("blis"), "engine": p.get("engine"),
                "fields_sha256": p.get("fields_sha256"), "experimental": p.get("experimental")}


# ---------------------------------------------------------------------------------- the guards

def check_run(run: Run, sample: str) -> list[str]:
    out = []
    if sample not in SAMPLES:
        out.append(f"sample {sample!r} is not one of {SAMPLES}")
    ident = run.identity(sample)
    hc = ident["harness_commit"]
    if not hc:
        out.append(f"{run.dir}: provenance.json names no harness_commit")
    if not ident["units_sha256"]:
        out.append(f"{run.dir}: provenance.json names no units file (run.sh --units records its sha256)")
    if not ident["pull_manifest_sha256"]:
        out.append(f"{run.dir}: provenance.json names no pull_manifest_sha256")
    commits = {p["harness_commit"] for p in run.points.values() if p["status"] == "scored"}
    if hc and commits - {hc}:
        out.append(f"{run.dir}: points were scored by harness commit(s) {sorted(c or 'none' for c in commits)}, "
                   f"not only {hc}")
    return out


def check_identities(before: dict, after: dict) -> list[str]:
    """The five equalities between the two sides of a table (each side's identity block)."""
    out = []
    for key, what in (("harness_commit", "harness commits"), ("units_sha256", "unit sets"),
                      ("pull_manifest_sha256", "pull sets"), ("point_set_sha256", "point sets")):
        if before.get(key) != after.get(key):
            out.append(f"the two runs have two {what} ({str(before.get(key))[:12]} and {str(after.get(key))[:12]}); "
                       f"a before/after table must hold one")
    if before.get("sample") != after.get("sample"):
        out.append(f"the runs are labelled {before.get('sample')!r} and {after.get('sample')!r}; "
                   f"a held-out figure is never compared with an in-sample one")
    return out


def check_pair(before: Run, after: Run, sample_before: str, sample_after: str) -> None:
    problems = check_run(before, sample_before) + check_run(after, sample_after)
    problems += check_identities(before.identity(sample_before), after.identity(sample_after))
    if problems:
        raise CompareError("; ".join(problems))


def check_table(table: dict) -> list[str]:
    """Problems with a table already written (a committed table is checked by the tests)."""
    out = []
    if table.get("format") != FORMAT:
        return [f"format {table.get('format')!r} is not {FORMAT}"]
    kind = table.get("kind")
    if kind == "run":
        ident = table.get("identity") or {}
        for k in ("harness_commit", "units_sha256", "pull_manifest_sha256", "point_set_sha256", "sample"):
            if not ident.get(k):
                out.append(f"identity names no {k}")
        if ident.get("sample") not in SAMPLES:
            out.append(f"sample {ident.get('sample')!r} is not one of {SAMPLES}")
        return out
    if kind != "pair":
        return [f"kind {kind!r} is neither run nor pair"]
    b, a = (table.get("before") or {}).get("identity") or {}, (table.get("after") or {}).get("identity") or {}
    for side, ident in (("before", b), ("after", a)):
        for k in ("harness_commit", "units_sha256", "pull_manifest_sha256", "point_set_sha256", "sample"):
            if not ident.get(k):
                out.append(f"{side} identity names no {k}")
        if ident.get("sample") not in SAMPLES:
            out.append(f"{side} sample {ident.get('sample')!r} is not one of {SAMPLES}")
    out += check_identities(b, a)
    if table.get("sample") != b.get("sample"):
        out.append(f"the table is labelled {table.get('sample')!r} but its runs are {b.get('sample')!r}")
    return out


# ------------------------------------------------------------------------------------- figures

def _errs(points, metric):
    return [abs(p[f"pred_{metric}_us"] - p[f"meas_{metric}_us"]) / p[f"meas_{metric}_us"] * 100
            for p in points if p[f"meas_{metric}_us"] > 0 and p[f"pred_{metric}_us"] > 0]


def _shape(points, metric):
    sweeps = defaultdict(list)
    for p in points:
        sweeps[p["sweep"]].append(p)
    vals = []
    for pts in sweeps.values():
        vals += list(bs.sweep_shape(pts, metric).values())
    vals = [abs(v) for v in vals if v is not None]
    return vals


def _fig(vals):
    n = len(vals)
    return {"n": n, "value": hl.TOO_FEW if n < hl.MIN_POINTS else sum(vals) / n}


def accuracy(points: list[dict]) -> dict:
    """MAPE (absolute percent) and shape, TTFT and TPOT, over scored points; each with its n."""
    pts = [p for p in points if p["status"] == "scored"]
    return {"points": len(pts),
            **{m: {"mape": _fig(_errs(pts, m)), "shape": _fig(_shape(pts, m))} for m in ("ttft", "tpot")},
            "noise_floor_pct": bs.FALLBACK_NOISE_FLOOR_PCT, "noise_floor_source": "fallback; none measured per point"}


def by_grade(points: list[dict]) -> dict:
    total = len(points)
    graded = [p for p in points if p["grade"] in gr.GRADED]
    out = {}
    for g in gr.GRADES:
        pts = [p for p in points if p["grade"] == g]
        row = {"points": len(pts), "share_of_all": len(pts) / total if total else None,
               "share_of_graded": (len(pts) / len(graded) if graded else None) if g in gr.GRADED else None}
        for k in ("share_of_all", "share_of_graded"):
            if row[k] is not None and len(pts) < hl.MIN_POINTS:
                row[k] = hl.TOO_FEW
        if g in gr.GRADED:
            row["accuracy"] = accuracy(pts)
        out[g] = row
    failed = sum(1 for p in points if p["status"] == "failed")
    out["failed"] = {"points": failed}
    return out


def reasons(points: list[dict]) -> dict:
    """Per G5 (code, subject): blocks (points carrying it), alone (points whose only reason it is)."""
    out = defaultdict(lambda: {"blocks": 0, "alone": 0})
    for p in points:
        if p["status"] == "scored":
            continue
        rs = set(p["g5_reasons"])
        for code, subject in rs:
            e = out[f"{code}:{subject}" if subject else code]
            e["blocks"] += 1
            e["alone"] += len(rs) == 1
    return dict(out)


def primary_reasons(points: list[dict]) -> dict:
    def rank(r):
        return (gr.G5_CODES.index(r[0]) if r[0] in gr.G5_CODES else len(gr.G5_CODES), r[0], r[1])
    c = Counter(sorted(p["g5_reasons"], key=rank)[0][0]
                for p in points if p["status"] != "scored" and p["g5_reasons"])
    return dict(sorted(c.items()))


def coverage(points: list[dict]) -> dict:
    out = {}
    for name, pts in (("all", points),
                      (SCOPE_IN, [p for p in points if scope(p["hardware"]) == SCOPE_IN]),
                      (SCOPE_OUT, [p for p in points if scope(p["hardware"]) == SCOPE_OUT])):
        scored = sum(1 for p in pts if p["status"] == "scored")
        out[name] = {"points": len(pts), "scored": scored,
                     "not_scored": sum(1 for p in pts if p["status"] == "not_scored"),
                     "failed": sum(1 for p in pts if p["status"] == "failed"),
                     "share_scored": scored / len(pts) if pts else None,
                     "by_grade": dict(Counter(p["grade"] for p in pts)),
                     "primary_reason": primary_reasons(pts), "reasons": reasons(pts)}
    out["out_of_scope_by_chip"] = dict(sorted(Counter(p["hardware"] for p in points
                                                        if scope(p["hardware"]) == SCOPE_OUT).items()))
    return out


def backlog_for(points: list[dict]) -> list[dict]:
    """Design §11.6 backlog entries (blocks / alone / demotes) over all engines, ranked."""
    rows = [{"framework": p["framework"], "grade": p["grade"], "substitutions": p["substitutions"],
             "g5_reasons": [{"code": c, "subject": s} for c, s in p["g5_reasons"]]}
            for p in points if p["status"] != "failed"]
    merged = defaultdict(lambda: {"blocks": 0, "alone": 0, "demotes": 0})
    for entries in bl.build(rows).values():
        for e in entries:
            for k in ("blocks", "alone", "demotes"):
                merged[e["entry"]][k] += e[k]
    return [{"entry": k, **v} for k, v in sorted(merged.items(),
            key=lambda kv: (-kv[1]["alone"], -kv[1]["blocks"], -kv[1]["demotes"], kv[0]))]


def attribution(points: list[dict]) -> dict:
    """MAPE by model, chip, precision, spec method and engine, for the given scored points."""
    out = {}
    for key in ("model", "hardware", "precision", "spec", "framework"):
        groups = defaultdict(list)
        for p in points:
            groups[p[key]].append(p)
        out[key] = {k: accuracy(v) for k, v in sorted(groups.items())}
    return out


def unlock_table(points: list[dict]) -> list[dict]:
    """What would unlock the rest: per blocker, the in-scope points it holds at G5 (blocks) and
    the ones that would be scored if only it were fixed (alone). Out-of-scope points are one
    line of their own and are not counted in any blocker."""
    ins = [p for p in points if p["status"] != "scored" and scope(p["hardware"]) == SCOPE_IN]
    rows = [{"blocker": k, **v} for k, v in sorted(reasons(ins).items(),
            key=lambda kv: (-kv[1]["alone"], -kv[1]["blocks"], kv[0]))]
    out_n = sum(1 for p in points if p["status"] != "scored" and scope(p["hardware"]) == SCOPE_OUT)
    rows.append({"blocker": "out of scope (AMD, TPU)", "blocks": out_n, "alone": out_n, "out_of_scope": True})
    return rows


def run_report(run: Run, sample: str) -> dict:
    problems = check_run(run, sample)
    if problems:
        raise CompareError("; ".join(problems))
    pts = list(run.points.values())
    return {"format": FORMAT, "kind": "run", "sample": sample, "sample_text": SAMPLE_TEXT[sample],
            "identity": run.identity(sample), "inputs": run.inputs(),
            "headline": accuracy([p for p in pts if p["grade"] in gr.GRADED]),
            "grades": by_grade(pts), "coverage": coverage(pts), "backlog": backlog_for(pts),
            "unlock": unlock_table(pts)}


def _movement(before: dict, after: dict) -> dict:
    keys = sorted(set(before) | set(after))
    return {k: {"before": before.get(k, {"blocks": 0, "alone": 0}), "after": after.get(k, {"blocks": 0, "alone": 0}),
                "delta_blocks": after.get(k, {"blocks": 0})["blocks"] - before.get(k, {"blocks": 0})["blocks"],
                "delta_alone": after.get(k, {"alone": 0})["alone"] - before.get(k, {"alone": 0})["alone"]}
            for k in keys}


def _brief(p):
    return {"id": p["id"], "model": p["model"], "hardware": p["hardware"], "precision": p["precision"],
            "conc": p.get("concurrency"), "grade": p["grade"], "scope": scope(p["hardware"]),
            "reasons": [f"{c}:{s}" if s else c for c, s in p["g5_reasons"]]}


def pair_report(before: Run, after: Run, sample: str) -> dict:
    check_pair(before, after, sample, sample)
    b, a = before.points, after.points
    sb = {i for i, p in b.items() if p["status"] == "scored"}
    sa = {i for i, p in a.items() if p["status"] == "scored"}
    both, new, lost = sorted(sb & sa), sorted(sa - sb), sorted(sb - sa)
    bpts, apts = [b[i] for i in both], [a[i] for i in both]
    cov_b, cov_a = coverage(list(b.values())), coverage(list(a.values()))
    return {"format": FORMAT, "kind": "pair", "sample": sample, "sample_text": SAMPLE_TEXT[sample],
            "before": {"identity": before.identity(sample), "inputs": before.inputs(),
                       "headline": accuracy([p for p in b.values() if p["grade"] in gr.GRADED]),
                       "grades": by_grade(list(b.values())), "coverage": cov_b,
                       "backlog": backlog_for(list(b.values()))},
            "after": {"identity": after.identity(sample), "inputs": after.inputs(),
                      "headline": accuracy([p for p in a.values() if p["grade"] in gr.GRADED]),
                      "grades": by_grade(list(a.values())), "coverage": cov_a,
                      "backlog": backlog_for(list(a.values()))},
            "scored_in_both": {"points": len(both), "before": accuracy(bpts), "after": accuracy(apts),
                               "grade_moves": dict(sorted(Counter(f"{b[i]['grade']}->{a[i]['grade']}" for i in both).items())),
                               "attribution": {"before": attribution(bpts), "after": attribution(apts)}},
            "newly_scored": {"points": len(new), "after": accuracy([a[i] for i in new]),
                             "list": [_brief(a[i]) | {"before": b[i]["status"], "before_reasons": _brief(b[i])["reasons"]} for i in new]},
            "newly_refused": {"points": len(lost), "before": accuracy([b[i] for i in lost]),
                              "list": [_brief(b[i]) | {"after": a[i]["status"], "after_reasons": _brief(a[i])["reasons"]} for i in lost]},
            "reason_movement": {name: {"primary": {k: {"before": cov_b[name]["primary_reason"].get(k, 0),
                                                       "after": cov_a[name]["primary_reason"].get(k, 0)}
                                                   for k in sorted(set(cov_b[name]["primary_reason"]) | set(cov_a[name]["primary_reason"]))},
                                       "all_reasons": _movement(cov_b[name]["reasons"], cov_a[name]["reasons"])}
                                for name in ("all", SCOPE_IN, SCOPE_OUT)},
            "unlock": {"before": unlock_table(list(b.values())), "after": unlock_table(list(a.values()))}}


# ------------------------------------------------------------------------------------ markdown

def _f(fig) -> str:
    return fig["value"] if isinstance(fig["value"], str) else f"{fig['value']:.1f}"


def _acc_cells(acc: dict) -> str:
    return " | ".join(f"{_f(acc[m][k])} (n={acc[m][k]['n']})" for m in ("ttft", "tpot") for k in ("mape", "shape"))


def _pct(x) -> str:
    return x if isinstance(x, str) else ("-" if x is None else f"{100 * x:.1f}%")


def _identity_md(ident: dict) -> list[str]:
    return [f"- harness commit `{ident['harness_commit']}`",
            f"- units sha256 `{ident['units_sha256']}` ({ident['units_count']} units)",
            f"- pull manifest sha256 `{ident['pull_manifest_sha256']}`",
            f"- point set sha256 `{ident['point_set_sha256']}` ({ident['points']} points)"]


def _grades_md(title: str, g: dict) -> list[str]:
    lines = [f"**{title}**", "", "| Grade | Points | Share of all | Share of graded | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |",
             "|---|---|---|---|---|---|---|---|"]
    for k in gr.GRADES:
        r = g[k]
        if k in gr.GRADED:
            lines.append(f"| {k} | {r['points']} | {_pct(r['share_of_all'])} | {_pct(r['share_of_graded'])} | "
                         + _acc_cells(r["accuracy"]).replace(" | ", " | ") + " |")
        else:
            lines.append(f"| {k} | {r['points']} | {_pct(r['share_of_all'])} | - | - | - | - | - |")
    if g["failed"]["points"]:
        lines.append(f"| failed | {g['failed']['points']} | | | | | | |")
    return lines + [""]


def run_markdown(t: dict) -> str:
    ident = t["identity"]
    L = [f"# Scored run ({t['sample'].replace('_', '-')})", "", t["sample_text"], "", *_identity_md(ident), ""]
    L += [f"Simulator `{(t['inputs'].get('simulator') or {}).get('build')}`, engine {t['inputs'].get('engine')}, "
          f"fields sha256 `{t['inputs'].get('fields_sha256')}`.", ""]
    h = t["headline"]
    L += ["## Headline (G1 to G4)", "", "| Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % | Noise floor % |", "|---|---|---|---|---|---|",
          f"| {h['points']} | {_acc_cells(h)} | {h['noise_floor_pct']} ({h['noise_floor_source']}) |", ""]
    L += ["## By grade", ""] + _grades_md("All points", t["grades"])
    L += _coverage_md({"": t["coverage"]}) + _unlock_md(t["unlock"], "What would unlock the rest")
    L += ["## Why points are below G1 or at G5 (design §11.6)", "", "| Entry | Blocks | Alone | Demotes |", "|---|---|---|---|"]
    L += [f"| `{e['entry']}` | {e['blocks']} | {e['alone']} | {e['demotes']} |" for e in t["backlog"]]
    return "\n".join(L) + "\n"


def _coverage_md(covs: dict) -> list[str]:
    L = ["## Coverage", "", "| Set | Points | Scored | Not scored | Failed | Share scored |", "|---|---|---|---|---|---|"]
    for label, c in covs.items():
        for name, title in (("all", "all points"), (SCOPE_IN, "in scope"), (SCOPE_OUT, "out of scope (AMD, TPU)")):
            r = c[name]
            L.append(f"| {(label + ' ') if label else ''}{title} | {r['points']} | {r['scored']} | {r['not_scored']} | {r['failed']} | {_pct(r['share_scored'])} |")
    L += ["", "Out-of-scope points by chip: " + ", ".join(f"{k} {v}" for k, v in
          next(iter(covs.values()))["out_of_scope_by_chip"].items()) + ".", ""]
    return L


def _unlock_md(rows: list[dict], title: str) -> list[str]:
    L = [f"## {title}", "", "Blocks: in-scope points held at G5 by the blocker. Alone: points that would be scored if only it were fixed.",
         "", "| Blocker | Blocks | Alone |", "|---|---|---|"]
    return L + [f"| {r['blocker']} | {r['blocks']} | {r['alone']} |" for r in rows] + [""]


def pair_markdown(t: dict) -> str:
    b, a = t["before"], t["after"]
    L = [f"# Before and after ({t['sample'].replace('_', '-')})", "", t["sample_text"], "",
         "Both runs share one harness commit, one units file, one frozen pull and one point set:", "", *_identity_md(b["identity"]), "",
         f"Before: simulator `{(b['inputs'].get('simulator') or {}).get('build')}`, fields `{b['inputs'].get('fields_sha256')}`.  ",
         f"After: simulator `{(a['inputs'].get('simulator') or {}).get('build')}`, fields `{a['inputs'].get('fields_sha256')}`.", ""]
    L += ["## Headline (G1 to G4, every graded point)", "", "| Run | Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |", "|---|---|---|---|---|---|",
          f"| before | {b['headline']['points']} | {_acc_cells(b['headline'])} |",
          f"| after | {a['headline']['points']} | {_acc_cells(a['headline'])} |",
          "", f"Noise floor {b['headline']['noise_floor_pct']} % ({b['headline']['noise_floor_source']}).", ""]
    both = t["scored_in_both"]
    L += ["## Accuracy apart from coverage", "",
          "A coverage gain cannot hide an accuracy loss, so the points scored in both runs and the points scored in one only are separate rows.", "",
          "| Set | Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |", "|---|---|---|---|---|---|",
          f"| scored in both, before | {both['points']} | {_acc_cells(both['before'])} |",
          f"| scored in both, after | {both['points']} | {_acc_cells(both['after'])} |",
          f"| newly scored, after | {t['newly_scored']['points']} | {_acc_cells(t['newly_scored']['after'])} |",
          f"| newly refused, before | {t['newly_refused']['points']} | {_acc_cells(t['newly_refused']['before'])} |", ""]
    if both["grade_moves"]:
        L += ["Grade moves of the points scored in both: " + ", ".join(f"{k} {v}" for k, v in both["grade_moves"].items()) + ".", ""]
    L += ["## By grade", ""] + _grades_md("Before", b["grades"]) + _grades_md("After", a["grades"])
    L += _coverage_md({"before": b["coverage"], "after": a["coverage"]})
    L += ["## Coverage movement by reason", "", "Blocks: points carrying the reason. Alone: points whose only reason it is.", ""]
    for name, title in (("all", "All points"), (SCOPE_IN, "In scope"), (SCOPE_OUT, "Out of scope (AMD, TPU)")):
        L += [f"**{title}**", "", "| Reason | Blocks before | after | change | Alone before | after | change |", "|---|---|---|---|---|---|---|"]
        for k, m in t["reason_movement"][name]["all_reasons"].items():
            L.append(f"| `{k}` | {m['before']['blocks']} | {m['after']['blocks']} | {m['delta_blocks']:+d} | "
                     f"{m['before']['alone']} | {m['after']['alone']} | {m['delta_alone']:+d} |")
        L.append("")
    L += ["## Attribution (points scored in both)", ""]
    for key in ("model", "hardware", "precision", "spec", "framework"):
        L += [f"**By {key}**", "", "| Value | Points | TTFT MAPE % before | after | TPOT MAPE % before | after |", "|---|---|---|---|---|---|"]
        for k, ab in both["attribution"]["before"][key].items():
            aa = both["attribution"]["after"][key][k]
            L.append(f"| {k} | {ab['points']} | {_f(ab['ttft']['mape'])} | {_f(aa['ttft']['mape'])} | {_f(ab['tpot']['mape'])} | {_f(aa['tpot']['mape'])} |")
        L.append("")
    L += ["## What moved points up (design §11.6 backlog)", "", "| Entry | Blocks before | after | Alone before | after | Demotes before | after |", "|---|---|---|---|---|---|---|"]
    bb, ba = {e["entry"]: e for e in b["backlog"]}, {e["entry"]: e for e in a["backlog"]}
    z = {"blocks": 0, "alone": 0, "demotes": 0}
    for k in sorted(set(bb) | set(ba), key=lambda k: (-(bb.get(k, z)["blocks"] + bb.get(k, z)["demotes"]), k)):
        L.append(f"| `{k}` | {bb.get(k, z)['blocks']} | {ba.get(k, z)['blocks']} | {bb.get(k, z)['alone']} | {ba.get(k, z)['alone']} | "
                 f"{bb.get(k, z)['demotes']} | {ba.get(k, z)['demotes']} |")
    L += [""] + _unlock_md(t["unlock"]["after"], "What would unlock the rest (after)")
    for key, title in (("newly_scored", "Newly scored points"), ("newly_refused", "Newly refused points")):
        L += [f"## {title} ({t[key]['points']})", ""]
        if t[key]["list"]:
            L += ["| Point | Model | Chip | Precision | Conc | Grade | Reasons |", "|---|---|---|---|---|---|---|"]
            L += [f"| `{x['id'][:12]}` | {x['model']} | {x['hardware']} | {x['precision']} | {x['conc']} | {x['grade']} | "
                  f"{', '.join(x.get('before_reasons' if key == 'newly_scored' else 'after_reasons') or [x.get('before' if key == 'newly_scored' else 'after')])} |"
                  for x in t[key]["list"]]
        else:
            L.append("None.")
        L.append("")
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------------------------------ cli

def _write(table: dict, md: str, prefix: str | None):
    if prefix:
        Path(prefix + ".json").write_text(json.dumps(table, indent=1, sort_keys=True) + "\n")
        Path(prefix + ".md").write_text(md)
        print(f"wrote {prefix}.json and {prefix}.md")
    else:
        print(md)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--dir", required=True)
    r.add_argument("--sample", required=True, choices=SAMPLES)
    r.add_argument("--out")
    p = sub.add_parser("pair")
    p.add_argument("--before", required=True)
    p.add_argument("--after", required=True)
    p.add_argument("--sample", required=True, choices=SAMPLES)
    p.add_argument("--out")
    c = sub.add_parser("check")
    c.add_argument("tables", nargs="+")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "run":
            t = run_report(Run(a.dir), a.sample)
            _write(t, run_markdown(t), a.out)
        elif a.cmd == "pair":
            t = pair_report(Run(a.before), Run(a.after), a.sample)
            _write(t, pair_markdown(t), a.out)
        else:
            bad = 0
            for path in a.tables:
                for pr in check_table(json.loads(Path(path).read_text())):
                    print(f"{path}: {pr}", file=sys.stderr)
                    bad += 1
            return 1 if bad else 0
    except CompareError as e:
        print(f"compare: REFUSED: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
