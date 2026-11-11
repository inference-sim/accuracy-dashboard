"""The substrate point record, one per point (SUB-19).

blis-substrate's contracts/spec/pointrecord defines the per-point record the scoring harness writes; the
dashboard writes it and config search and the substrate's gates read it. The files the harness already wrote
(points.csv, fidelity.jsonl, facets.json, not_scored.jsonl) are the dashboard's reporting views and keep
their shapes; `pointrecords.jsonl` beside them holds the same points under the substrate's names, one record
per line, for every scored point and every G5 point (a point that failed in the simulator is no grade and has
none). `write_contract` writes it; test_pointrecord.py loads every line with the substrate's own loader and
validator.

Where the dashboard's name differs it is mapped here and nowhere else: `args` become `settings`,
`approximated` becomes `estimated`, a setting the engine resolved and the run did not set (`resolved_not_stated`)
becomes a note, the points.csv microsecond means become the registry's millisecond figures with a basis on each
side, and the Result's `data` block becomes `simulator.data`. What the pulled data does not hold is stated, not
invented: see docs/pointrecord.md ("What the record cannot yet say").
"""
from __future__ import annotations

import json
import re

import contract

SCHEMA_VERSION = 2
KIND = "PointRecord"
CLUSTER = {"scope": "cluster"}
HEX40 = re.compile(r"^[0-9a-f]{40}$")

# The keys of a substitution the substrate declares (Substitution in pointrecord.go).
SUBSTITUTION_KEYS = ("kind", "subject", "detail", "record", "date", "policy", "entry", "evidence", "revision",
                     "profile_family", "differed")
SETTING_KEYS = ("arg", "measured", "source", "blis", "field", "match", "rule", "occurrences", "values", "delta",
                "ratio", "note")
REPLAY_KEYS = ("client", "client_version", "scenario", "replayed_as", "concurrency", "duration_s",
               "trajectory_start", "corpus", "corpus_sha256", "seed")
MATCH = {"approximated": "estimated"}
RESOLVED_NOT_STATED_NOTE = ("the engine resolved this value and the run did not set it; it is recorded here "
                            "and not stated in the scenario (design 11.2)")


def _scalar(v):
    """A value as the substrate's record holds it: null, a string, an integer or a boolean. A float is
    kept as its text; a list or mapping as its JSON text."""
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return repr(v)
    return json.dumps(v, sort_keys=True)


def recipe_of(o) -> str:
    """The source's recipe fingerprint, or row:<id> when it has none."""
    return o.identity.get("recipe_fingerprint") or f"row:{o.row['id']}"


def identity_of(o) -> dict:
    i = o.identity
    return {"source": i["source"], "model": i["model"], "hardware": i["hardware"], "precision": i.get("precision") or "",
            "framework": i["framework"], "benchmark_type": i["benchmark_type"], "recipe": recipe_of(o),
            "conc": i["conc"], "measured_date": i["measured_date"]}


# The dashboard's kind for "the engine publishes no list of its ported functions, so a changed one cannot be
# ruled out" is the substrate's changed_functions (a G4 condition); the detail keeps the reason.
KIND_MAP = {"ported_functions_unpublished": "changed_functions"}


def substitutions_of(subs: list[dict]) -> list[dict]:
    out = [{k: s[k] for k in SUBSTITUTION_KEYS if s.get(k) not in (None, "", [])} for s in subs]
    for s in out:
        if s["kind"] in KIND_MAP:
            s["detail"] = s.get("detail") or "no list of the engine's ported functions is published: a changed one is not ruled out"
            s["kind"] = KIND_MAP[s["kind"]]
    out.sort(key=lambda s: (s["kind"], s["subject"]))
    return out


def settings_and_notes(args: list[dict]) -> tuple[list[dict], list[dict]]:
    settings, notes = {}, {}
    for a in args:
        if a.get("match") == "resolved_not_stated":
            notes[a["arg"]] = {"subject": a["arg"], "text": RESOLVED_NOT_STATED_NOTE}
            continue
        s = {k: a[k] for k in SETTING_KEYS if k in a and a[k] is not None or k in ("measured", "blis") and k in a}
        if "blis_field" in a:
            s["field"] = a["blis_field"]
        s["match"] = MATCH.get(s.get("match"), s.get("match"))
        if s["match"] == "estimated" and "rule" not in s:
            # The field list's rule, read from the detail the substitution carries (fields.decide).
            s["rule"] = "substitute" if "stands in" in str(a.get("note", "")) else "leave_unset"
        for k in ("measured", "blis"):
            s[k] = _scalar(s.get(k))
        if "values" in s:
            s["values"] = [_scalar(v) for v in s["values"]]
        if "delta" in s:
            s["delta"] = _scalar(s["delta"])
        settings[a["arg"]] = s
    return [settings[k] for k in sorted(settings)], [notes[k] for k in sorted(notes)]


def resolved_of(items: list[dict]) -> list[dict]:
    out = []
    for r in items:
        o = {k: r[k] for k in ("quantity", "occurrences", "delta", "ratio", "match") if r.get(k) is not None}
        o["measured"], o["blis"] = _scalar(r.get("measured")), _scalar(r.get("blis"))
        for k in ("delta",):
            if k in o:
                o[k] = _scalar(o[k])
        out.append(o)
    return sorted(out, key=lambda r: r["quantity"])


def build_of(o) -> dict:
    b = o.build or {}
    out = {"image": (o.row.get("image") or b.get("image") or "unrecorded")}
    if o.run_release:
        out["release"] = o.run_release
    if HEX40.match(str(b.get("commit") or "")):
        out["commit"] = b["commit"]
        if b.get("source"):
            out["source"] = b["source"]
    if o.banner:
        out["version"] = o.banner
    return out


def replay_of(rep: dict) -> dict:
    out = {k: rep[k] for k in REPLAY_KEYS if rep.get(k) is not None}
    return out


def figures_of(o, csv_row: dict) -> list[dict]:
    p, m = o.samples or (1, 1)
    figs = []
    for metric, pk, mk in (("tpot_mean_ms", "pred_tpot_us", "meas_tpot_us"), ("ttft_mean_ms", "pred_ttft_us", "meas_ttft_us")):
        figs.append({"metric": metric, "predicted_basis": dict(CLUSTER), "measured_basis": dict(CLUSTER),
                     "predicted": float(csv_row[pk]) / 1000.0, "measured": float(csv_row[mk]) / 1000.0,
                     "predicted_samples": max(1, int(p)), "measured_samples": max(1, int(m))})
    return sorted(figs, key=lambda f: f["metric"])


def g5_facets(o) -> dict:
    """Labels for a point that was never scenario-ed: the source's own names stand in."""
    i = identity_of(o)
    deployment = f"{i['model']}-{i['hardware']}-{i['precision'] or 'na'}-{i['framework']}"
    return {"sweep_id": f"{deployment}|{i['benchmark_type']}|{i['recipe']}", "scenario": deployment,
            "label": i["benchmark_type"], "workload": i["benchmark_type"], "model": i["model"], "gpu": i["hardware"],
            "precision": i["precision"], "framework": i["framework"], "serving": "aggregated", "spec_method": "none",
            "parallelism": {"tp": 1, "pp": 1, "dp": 1, "ep": 1}}


def assemble(outcomes: list, provenance: dict, points_csv_rows: dict) -> list[dict]:
    """One substrate record per scored or G5 outcome, sorted by point id. `points_csv_rows` maps a point id
    to its points.csv row (as written). Returns [] when no Result gave the run's data block, since every
    record states it."""
    datas = {json.dumps(o.result_data, sort_keys=True) for o in outcomes if o.fidelity is not None and o.result_data}
    if len(datas) > 1:
        raise ValueError("the Results of one run name more than one catalog and registry data block")
    if not datas:
        return []
    data = json.loads(next(iter(datas)))
    out = []
    for o in sorted(outcomes, key=lambda o: o.point_id):
        sim = o.simulator or {}
        common = {"kind": KIND, "schema_version": SCHEMA_VERSION, "point_id": o.point_id, "unit_id": o.point_id,
                  "identity": identity_of(o), "build": build_of(o),
                  "simulator": {"build": sim["build"], "engine": sim["engine"], "data": data},
                  "harness_commit": provenance["harness_commit"]}
        if o.fidelity is not None:
            f, fa = o.fidelity, o.facets
            settings, notes = settings_and_notes(f.get("args") or [])
            rec = {**common, "grade": f["grade"], "substitutions": substitutions_of(f["substitutions"]),
                   "figures": figures_of(o, points_csv_rows[o.point_id]), "settings": settings,
                   "resolved": resolved_of(f.get("resolved") or []),
                   "facets": {k: fa[k] for k in ("sweep_id", "scenario", "label", "workload", "model", "gpu", "precision",
                                                 "framework", "serving", "spec_method")}
                   | {"parallelism": {k: fa["parallelism"][k] for k in ("tp", "pp", "dp", "ep")}}}
            if notes:
                rec["notes"] = notes
            if f.get("replay"):
                rec["replay"] = replay_of(f["replay"])
            if f.get("blis_kernel_provenance"):
                rec["kernel_provenance"] = f["blis_kernel_provenance"]
        elif not o.faults:
            rec = {**common, "grade": "G5", "g5_reason": dict(o.g5), "facets": g5_facets(o)}
        else:
            continue            # failed in the simulator: no grade, no record
        for k in ("settings", "resolved", "substitutions", "notes"):
            if rec.get(k) == []:
                rec.pop(k)
        out.append(rec)
    return out


def dumps(records: list[dict]) -> str:
    return "".join(contract.canonical_dumps(r) + "\n" for r in records)
