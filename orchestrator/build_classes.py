#!/usr/bin/env python3
"""The classes page's data: one entry per class of points, each with its own counts, grades and accuracy by grade.

The dashboard's summary (summary.json) is the regular InferenceX run: its headline, its coverage and its tree. Two further kinds of
point are scored by the same harness but are not regular runs, and are never mixed into the summary's counts:

  reconstructed recipe   InferenceX points (benchmark_run ids are InferenceX workflow runs) whose launch the run did not record;
                         the recipe was reconstructed from the model's published configuration. Graded G4 at best, with the
                         substitutions that say so. The summary builder refuses a contract carrying the marker, by design.
  configiq               Red Hat's GuideLLM aggregates, scored by simulation (configiq_score.py), provisional and capped at G3.

    build_classes.py derive-contract CONTRACT_DIR --id ID --label L --note N --meta META.json --out data/supplemental/classes/X.json
    build_classes.py derive-configiq SCORE_DIR    --id ID --label L --note N --meta META.json --out data/supplemental/classes/X.json
    build_classes.py build [--summary data/latest/summary.json] [--supplemental data/supplemental/classes] --out data/latest/classes.json
    build_classes.py check classes.json

derive-* read a census run's output once and write the small derived file that is committed under data/supplemental/ (derived values
only, with the command that produced them and the heads it ran at); build reads only the summary and those files, so the nightly and
a local run give the same classes.json. Nothing here is estimated: every number is a count or an error computed from the files.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "ingest"))
import headline as hl  # noqa: E402

FORMAT = "classes-1"
SCHEMA = HERE.parent / "docs" / "m3" / "classes" / "classes.v1.schema.json"
GRADES = ("G1", "G2", "G3", "G4", "G5")
GRADED = GRADES[:4]
KINDS = ("regular", "reconstructed", "provisional")
TOO_FEW = hl.TOO_FEW
MIN_POINTS = hl.MIN_POINTS
STATS = ("ttft", "tpot", "itl")
# configiq's statistics (GuideLLM's) behind each figure: TTFT and ITL are the means (ITL is the per-request time per output token after
# the first, the quantity the InferenceX harness calls TPOT); GuideLLM's own TPOT counts the first token and records no mean, so its
# median stands for it.
CONFIGIQ_STAT = {"ttft": "ttft_mean", "itl": "itl_mean", "tpot": "tpot_median"}
SUPPLEMENTAL_ORDER = ("sglang", "inferencex-reconstructed", "configiq")


class ClassesError(ValueError):
    pass


# A refusal reason with fewer points than this is counted under one "other settings" row of its code instead of being listed by name: the
# long tail of one-off settings says little each, and the card stays readable. The points stay in the refused count.
MIN_NAMED_POINTS = 6
OTHER_SETTINGS = "other settings"


def _refusal_rows(counter: Counter) -> list[dict]:
    folded: Counter = Counter()
    for (code, subject), n in counter.items():
        folded[(code, subject if n >= MIN_NAMED_POINTS else OTHER_SETTINGS)] += n
    return [{"code": c, "subject": sub, "points": n} for (c, sub), n in sorted(folded.items(), key=lambda kv: (-kv[1], kv[0]))]


def _figure(errors: list[float]) -> dict:
    """{n, mape, signed_median}: from MIN_POINTS points a number, else "too few points" (COV-11); n always."""
    n = len(errors)
    if n < MIN_POINTS:
        return {"n": n, "mape": TOO_FEW, "signed_median": TOO_FEW}
    return {"n": n, "mape": sum(abs(e) for e in errors) / n, "signed_median": statistics.median(errors)}


def _meta(path: str | None) -> dict:
    meta = json.loads(Path(path).read_text()) if path else {}
    for k in ("command", "heads", "pulled_at"):
        if k not in meta:
            raise ClassesError(f"--meta lacks {k!r}: a derived file names the command that made it, the heads it ran at and its data's date")
    return meta


def _lines(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.is_file() else []


# ---------------------------------------------------------------------------------------------- derive

def _itl_errors(itl_json: Path, manifest: Path, grade_of: dict) -> tuple[dict, int]:
    """Percent error of the simulator's mean ITL against the measured mean ITL, by grade. Only a point whose measured ITL is a per-token
    one counts (mean ITL within 15 percent of mean TPOT); a point that streamed several tokens per chunk is counted apart, since the
    simulator's per-token ITL does not compare with it."""
    itl = json.loads(Path(itl_json).read_text())
    by = {q["point_id"]: q for q in json.loads(Path(manifest).read_text())["points"]}
    err, left_out = {g: [] for g in GRADED}, 0
    for pid, grade in grade_of.items():
        sim = itl.get(pid)
        mt = ((by.get(pid) or {}).get("measurements") or [{}])[0].get("metrics", {})
        if not sim or not mt.get("mean_itl") or not mt.get("mean_tpot") or grade not in err:
            continue
        if abs(mt["mean_itl"] / mt["mean_tpot"] - 1) > 0.15:
            left_out += 1
            continue
        err[grade].append((sim["itl_mean_ms"] - mt["mean_itl"] * 1000) / (mt["mean_itl"] * 1000) * 100)
    return err, left_out


def derive_contract(directory: Path, *, cid: str, label: str, note: str, kind: str, meta: dict, interim: bool = False,
                    itl_json: Path | None = None, manifest: Path | None = None) -> dict:
    """A class from a scored contract directory (fidelity.jsonl, points.csv, not_scored.jsonl, failed.jsonl). With itl_json (the run's
    simulated ITL per point) and the pull's manifest (the measured ITL) the class also has an ITL figure."""
    directory = Path(directory)
    fid = {r["point_id"]: r for r in _lines(directory / "fidelity.jsonl")}
    ns, failed = _lines(directory / "not_scored.jsonl"), _lines(directory / "failed.jsonl")
    grades = Counter(r["grade"] for r in fid.values())
    grades["G5"] = len(ns)
    err = {g: {"ttft": [], "tpot": []} for g in GRADED}
    with open(directory / "points.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            g = r["grade"]
            if g not in err:
                continue
            for s in ("ttft", "tpot"):
                m, p = float(r[f"meas_{s}_us"]), float(r[f"pred_{s}_us"])
                if m > 0 and p > 0:
                    err[g][s].append((p - m) / m * 100)
    subs: dict = {}
    for r in fid.values():
        for s in r["substitutions"]:
            e = subs.setdefault((s["kind"], s["subject"], s.get("detail", "")), {"kind": s["kind"], "subject": s["subject"],
                                                                                 "detail": s.get("detail", ""), "points": 0})
            e["points"] += 1
    refusals = Counter((n["g5_reason"]["code"], n["g5_reason"].get("subject", "")) for n in ns)
    figures = {g: {s: _figure(err[g][s]) for s in ("ttft", "tpot")} for g in GRADED}
    extra = {}
    if itl_json and manifest:
        itl_err, left_out = _itl_errors(itl_json, manifest, {pid: r["grade"] for pid, r in fid.items()})
        for g in GRADED:
            figures[g]["itl"] = _figure(itl_err[g])
        extra["itl_streamed_in_chunks_left_out"] = left_out
    return {"id": cid, "label": label, "kind": kind, "interim": interim, "note": note,
            "counts": {"points": len(fid) + len(ns) + len(failed), "scored": len(fid), "refused": len(ns), "failed": len(failed),
                       "withheld": 0},
            "grades": {g: grades.get(g, 0) for g in GRADES},
            "accuracy_by_grade": figures, **extra,
            "refusals": _refusal_rows(refusals),
            "substitutions": sorted(subs.values(), key=lambda e: (-e["points"], e["kind"], e["subject"])),
            "provenance": meta}


def derive_configiq(directory: Path, *, cid: str, label: str, note: str, meta: dict, interim: bool = False,
                    withheld_figures: dict | None = None, plain_line: str | None = None, model_gaps: dict | None = None) -> dict:
    """The configiq class from a score_configiq output directory (summary.json, configiq-points.jsonl). Errors are by grade over the
    scored train and validation points; the test split is withheld and never appears.

    The card shows the dataset's rows, the rows scored and the partition, and one plain line (plain_line) for the rest: no refusal is
    listed. A statistic named in withheld_figures (stat -> why) is not reported as an accuracy figure and its reason is shown instead;
    which statistics those are is a rule fixed on the data's clarity, never on an error. model_gaps (model -> text) labels a model
    whose larger error is the simulator's, not the data's. Substitutions are named by kind and subject with their point counts."""
    directory = Path(directory)
    withheld_figures = withheld_figures or {}
    model_gaps = model_gaps or {}
    stats = tuple(s for s in STATS if s not in withheld_figures)
    doc = json.loads((directory / "summary.json").read_text())
    cov, br = doc["coverage"], doc["by_source"]
    recs = _lines(directory / "configiq-points.jsonl")
    err = {g: {s: [] for s in stats} for g in GRADED}
    by_model: dict = {}
    subs: dict = {}
    for r in recs:
        if r.get("status") != "scored" or r.get("split") == "test" or r.get("grade") not in err:
            continue
        m = by_model.setdefault(r["model"], {s: [] for s in stats})
        for s in stats:
            e = (r.get("errors_pct") or {}).get(CONFIGIQ_STAT[s])
            if e is not None:
                err[r["grade"]][s].append(e)
                m[s].append(e)
        for sub in r.get("substitutions", []):
            k = (sub["kind"], sub["subject"])
            e = subs.setdefault(k, {"kind": sub["kind"], "subject": sub["subject"], "detail": "", "points": 0})
            e["points"] += 1
    grades = {g: br["provisional_grades"].get(g, 0) for g in GRADED}
    grades["G5"] = br["grades"]["G5"]
    models = [{"model": name, "scored": len(next(iter(v.values()))), "gap": model_gaps.get(name),
               "accuracy": {s: _figure(v[s]) for s in stats}} for name, v in by_model.items()]
    models.sort(key=lambda m: (-m["scored"], m["model"]))
    out = {"id": cid, "label": label, "kind": "provisional", "interim": interim, "note": note,
           "counts": {"points": cov["points"], "scored": cov["scored"], "refused": cov["refused"], "failed": cov["failed"],
                      "withheld": cov["withheld"]},
           "partition": "train and validation rows are simulated; the test partition is withheld",
           "grades": grades,
           "accuracy_by_grade": {g: {s: _figure(err[g][s]) for s in stats} for g in GRADED},
           "by_model": models,
           "figure_notes": dict(withheld_figures),
           "refusals": [],
           "substitutions": sorted(subs.values(), key=lambda e: (-e["points"], e["kind"], e["subject"])),
           "provenance": {**meta, "dataset": doc["provenance"]["dataset"]["revision"], "split": doc["provenance"]["split"]["name"]}}
    if plain_line:
        out["plain_line"] = plain_line
    return out


# ---------------------------------------------------------------------------------------------- build

def regular_class(summary: dict) -> dict:
    """The regular InferenceX class: the summary's own counts, grade mix and headline accuracy, by framework. Read from the summary
    and nothing else, so it can never disagree with the headline."""
    cov, head = summary["coverage"], summary["headline"]
    acc = {}
    for g in GRADED:
        grade = head["grades"][g]
        acc[g] = {s: {"n": grade[s]["n"], "mape": grade[s]["mape"], "signed_median": None} for s in ("ttft", "tpot")}
    engines = [{"engine": k, "points": v["points"], "graded": v["graded"], "grades": v["grades"]}
               for k, v in sorted(cov["by_engine"].items())]
    return {"id": "inferencex", "label": "InferenceX, regular recipes", "kind": "regular", "interim": False,
            "note": "The nightly's summary: every point whose launch the run recorded, graded G1 to G4 by the harness. A framework with no "
                    "graded point is shown with its points and refusals.",
            "counts": {"points": cov["points"], "scored": cov["graded"], "refused": cov["not_scored"], "failed": cov["failed"], "withheld": 0},
            "grades": {g: cov["by_grade"][g] for g in GRADES},
            "accuracy_by_grade": acc,
            "refusals": [{"code": k, "subject": "", "points": n} for k, n in sorted(cov["g5_reasons"].items(), key=lambda kv: (-kv[1], kv[0]))],
            "engines": engines, "substitutions": [],
            "provenance": {"command": "orchestrator/build_summary_v2.py (the nightly)", "heads": {"snapshot_id": summary.get("snapshot_id")},
                           "pulled_at": summary["provenance"]["pulled_at"]}}


def build(summary_path: Path, supplemental: Path, generated_at: str) -> dict:
    summary = json.loads(Path(summary_path).read_text())
    classes = [regular_class(summary)]
    files = {p.stem: p for p in sorted(Path(supplemental).glob("*.json"))}
    unknown = sorted(set(files) - set(SUPPLEMENTAL_ORDER))
    if unknown:
        raise ClassesError(f"{supplemental}: no class {unknown[0]!r} is defined; the classes are {SUPPLEMENTAL_ORDER}")
    for cid in SUPPLEMENTAL_ORDER:
        if cid in files:
            classes.append(json.loads(files[cid].read_text()))
    if any(c["id"] == "sglang" for c in classes):
        # The final census scored SGLang points in its own run; the summary does not score them yet. The two are different runs over
        # partly the same points, so the SGLang card is never added to this card's counts.
        for e in classes[0].get("engines", []):
            if e["engine"] == "sglang":
                e["note"] = "Not scored in this run. The final census scored SGLang points in its own run, shown in the SGLang card and not added here."
    doc = {"format": FORMAT, "generated_at": generated_at, "snapshot_id": summary.get("snapshot_id"), "classes": classes}
    problems = check(doc)
    if problems:
        raise ClassesError("classes.json would be invalid:\n  " + "\n  ".join(problems))
    return doc


# ---------------------------------------------------------------------------------------------- check

def check(doc: dict) -> list[str]:
    """What must hold of a classes document: the counts add up, the grades add up to the points, a class kind is known, a figure under
    the minimum is "too few points", the reconstructed class is never graded better than G4, and the regular class is the only one
    whose counts are the summary's."""
    out = []
    try:
        import jsonschema
        schema = json.loads(SCHEMA.read_text())
        out += [f"schema: {'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message[:160]}"
                for e in jsonschema.Draft7Validator(schema).iter_errors(doc)]
    except ImportError:  # the CI image has it (requirements-ci.txt); a bare checkout still gets the checks below
        pass
    if doc.get("format") != FORMAT:
        out.append(f"format is {doc.get('format')!r}, expected {FORMAT!r}")
    ids = [c.get("id") for c in doc.get("classes", [])]
    if len(set(ids)) != len(ids) or not ids:
        out.append(f"class ids {ids} are empty or repeated")
    if ids and ids[0] != "inferencex":
        out.append("the first class is the regular InferenceX run")
    for c in doc.get("classes", []):
        w = c.get("id")
        for k in ("id", "label", "kind", "note", "counts", "grades", "accuracy_by_grade", "refusals", "substitutions", "provenance"):
            if k not in c:
                out.append(f"{w}: lacks {k}")
        if c.get("kind") not in KINDS:
            out.append(f"{w}: kind {c.get('kind')!r} is not one of {KINDS}")
            continue
        n = c.get("counts", {})
        if n.get("points") != n.get("scored", 0) + n.get("refused", 0) + n.get("failed", 0) + n.get("withheld", 0):
            out.append(f"{w}: points {n.get('points')} != scored + refused + failed + withheld")
        g = c.get("grades", {})
        if sum(g.get(x, 0) for x in GRADED) != n.get("scored"):
            out.append(f"{w}: the graded counts {sum(g.get(x, 0) for x in GRADED)} != scored {n.get('scored')}")
        if g.get("G5", 0) > n.get("refused", 0) + n.get("withheld", 0) + n.get("failed", 0):
            out.append(f"{w}: G5 {g.get('G5')} exceeds the points not scored")
        if c["kind"] == "reconstructed" and any(g.get(x, 0) for x in ("G1", "G2", "G3")):
            out.append(f"{w}: a reconstructed-recipe point is never better than G4")
        if c["kind"] == "provisional" and any(g.get(x, 0) for x in ("G1", "G2")):
            out.append(f"{w}: a provisional point is capped at G3")
        for gr, figs in c.get("accuracy_by_grade", {}).items():
            for s, f in figs.items():
                if f["n"] < MIN_POINTS and f["mape"] != TOO_FEW:
                    out.append(f"{w}: {gr} {s} is a number over {f['n']} points (COV-11)")
                if f["n"] >= MIN_POINTS and not isinstance(f["mape"], (int, float)):
                    out.append(f"{w}: {gr} {s} is {f['mape']!r} over {f['n']} points")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("derive-contract", "derive-configiq"):
        p = sub.add_parser(name)
        p.add_argument("dir")
        p.add_argument("--id", required=True)
        p.add_argument("--label", required=True)
        p.add_argument("--note", required=True)
        p.add_argument("--meta", required=True)
        p.add_argument("--out", required=True)
        p.add_argument("--interim", action="store_true")
        if name == "derive-configiq":
            p.add_argument("--withhold-figure", action="append", default=[], metavar="STAT=REASON",
                           help="a statistic not reported as an accuracy figure, with the sentence shown instead")
            p.add_argument("--plain-line", default=None)
            p.add_argument("--model-gap", action="append", default=[], metavar="MODEL=TEXT")
        if name == "derive-contract":
            p.add_argument("--kind", default="reconstructed", choices=KINDS)
            p.add_argument("--itl-json", default=None, help="the run's simulated ITL per point (itl.json)")
            p.add_argument("--pull-manifest", default=None, help="the pull's manifest.json (the measured ITL)")
    b = sub.add_parser("build")
    b.add_argument("--summary", default="data/latest/summary.json")
    b.add_argument("--supplemental", default="data/supplemental/classes")
    b.add_argument("--out", default="data/latest/classes.json")
    b.add_argument("--generated-at", default=None)
    c = sub.add_parser("check")
    c.add_argument("file")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "derive-contract":
            doc = derive_contract(Path(a.dir), cid=a.id, label=a.label, note=a.note, kind=a.kind, meta=_meta(a.meta), interim=a.interim,
                                 itl_json=a.itl_json, manifest=a.pull_manifest)
            Path(a.out).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
        elif a.cmd == "derive-configiq":
            doc = derive_configiq(Path(a.dir), cid=a.id, label=a.label, note=a.note, meta=_meta(a.meta), interim=a.interim,
                                  withheld_figures=dict(x.split("=", 1) for x in a.withhold_figure), plain_line=a.plain_line,
                                  model_gaps=dict(x.split("=", 1) for x in a.model_gap))
            Path(a.out).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
        elif a.cmd == "build":
            summary = json.loads(Path(a.summary).read_text())
            doc = build(Path(a.summary), Path(a.supplemental), a.generated_at or summary["generated_at"])
            Path(a.out).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
        else:
            problems = check(json.loads(Path(a.file).read_text()))
            for p in problems:
                print(p, file=sys.stderr)
            return 1 if problems else 0
    except (ClassesError, OSError, KeyError, ValueError) as e:
        print(f"build_classes: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
