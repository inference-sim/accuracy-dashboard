#!/usr/bin/env python3
"""Build summary.json v2 from an extractor contract directory (Discussion #28, issue #30).

Input: a contract directory (orchestrator/ingest/CONTRACT.md) -- points.csv, fidelity.jsonl,
facets.json, not_scored.jsonl, provenance.json. Output: summary.json v2 (schemas/summary.v2.json).

The arithmetic is v1's, imported from build_summary rather than copied: per-point error, sweep
shape re-anchored at the lowest surviving concurrency, every level averaging |point errors|, and
the self-consistency oracle. What v2 adds per point is its identity (point_id, measured_date)
and its fidelity record; and at the top, the not-scored points (never rendered) with their
reasons counted in coverage. Repeated InferenceX runs of one measurement (same deployment,
concurrency, day and BLIS inputs) are folded into one point (merge_repeats).

Nothing in the nightly pipeline calls this. v1 (build_summary.py) is unchanged.

Usage:
    python3 orchestrator/build_summary_v2.py --contract DIR --out summary.json \
        [--generated-at ISO] [--evaluator-commit SHA]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, OrderedDict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "ingest"))
import build_summary as v1  # noqa: E402
import contract  # noqa: E402

SCHEMA_VERSION = 2


class ContractError(RuntimeError):
    """The contract directory isn't valid; never build a summary from it."""


# A point's tier comes from its fidelity record, not the harness's tier string: an exact point
# (BLIS simulated exactly what the run used) is in the strict tier; an approximate one (a setting
# BLIS can't state was estimated, or a vLLM build BLIS doesn't model) only in "all".
TIER_BY_STATUS = {"exact": "measured_or_resolved", "approximate": "all"}


def read_points(directory: Path, fidelity: dict) -> list[dict]:
    """points.csv rows with numbers parsed, each tiered by its fidelity status."""
    with open(directory / contract.POINTS_CSV, newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != contract.POINTS_HEADER:
            raise ContractError(f"{contract.POINTS_CSV} header {reader.fieldnames} != {contract.POINTS_HEADER}")
        rows = []
        for r in reader:
            r["concurrency"] = int(r["concurrency"])
            for k in ("meas_tpot_us", "pred_tpot_us", "meas_ttft_us", "pred_ttft_us"):
                r[k] = float(r[k])
            status = fidelity[r["point_id"]]["status"]
            if status not in TIER_BY_STATUS:
                raise ContractError(f"point {r['point_id'][:12]} is scored with status {status!r}")
            r["tier"] = TIER_BY_STATUS[status]
            rows.append(r)
    return rows


def _lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


MEAS_KEYS = ("meas_ttft_us", "meas_tpot_us")
PRED_KEYS = ("pred_ttft_us", "pred_tpot_us")


def merge_repeats(rows: list[dict], facets: dict, fidelity: dict) -> tuple[list[dict], dict]:
    """Fold repeated InferenceX runs into one measurement.

    Two runs are repeats when they are one deployment row (scenario, build, drafter, workload),
    at one concurrency, on one day, and BLIS was given exactly the same inputs for both (the
    whole fidelity record) and so predicted the same: InferenceX ran the same experiment twice
    (e.g. two recipe rows whose engines logged identical settings). They become one point whose
    measured value is the runs' mean, carrying every run in `repeats`. The InferenceX sweeps they
    came from are joined into one curve for the trend; if that would put two different points at
    one concurrency, nothing in that group of sweeps is merged. Runs on different days, or with
    different inputs, stay separate points. Returns (rows, {point_id: [runs]}) where each kept
    point's id is the smallest of its runs'."""
    def key(r):
        f = facets[r["point_id"]]
        rec = {k: v for k, v in fidelity[r["point_id"]].items() if k != "point_id"}
        return (f["model"], f["workload"], f["gpu"], f["scenario"], f["label"], f.get("vllm_version") or "",
                f["spec_method"] or "none", r["concurrency"], r["measured_date"],
                contract.canonical_dumps(rec), tuple(r[k] for k in PRED_KEYS))
    groups = _group(sorted(rows, key=lambda r: r["point_id"]), key)
    # Join the sweeps of each merge (union-find on sweep ids).
    parent: dict = {}

    def find(s):
        parent.setdefault(s, s)
        while parent[s] != s:
            parent[s] = parent[parent[s]]
            s = parent[s]
        return s
    for g in groups.values():
        sids = sorted({facets[r["point_id"]]["sweep_id"] for r in g})
        for s in sids[1:]:
            parent[find(s)] = find(sids[0])
    # A joined curve must still hold one point per concurrency once merged; else undo it.
    by_curve: dict = {}
    for g in groups.values():
        by_curve.setdefault(find(facets[g[0]["point_id"]]["sweep_id"]), []).append(g)
    bad = {c for c, gs in by_curve.items()
           if len([g[0]["concurrency"] for g in gs]) != len({g[0]["concurrency"] for g in gs})}
    out, runs = [], {}
    for g in groups.values():
        curve = find(facets[g[0]["point_id"]]["sweep_id"])
        if len(g) == 1 or curve in bad:
            for r in g:
                r["_curve"] = facets[r["point_id"]]["sweep_id"] if curve in bad else curve
                out.append(r)
            continue
        kept = dict(g[0])
        for k in MEAS_KEYS:
            kept[k] = sum(r[k] for r in g) / len(g)
        kept["_curve"] = curve
        runs[kept["point_id"]] = [{"point_id": r["point_id"],
                                   "measured": {"ttft_ms": _ms(r["meas_ttft_us"]), "tpot_ms": _ms(r["meas_tpot_us"])}}
                                  for r in g]
        out.append(kept)
    return out, runs


def _ms(us):
    return round(us / 1000.0, 4) if us and us > 0 else None


def enrich(rows: list[dict], facets: dict) -> "OrderedDict[str, list[dict]]":
    """Per-point error and shape, the shape computed within each measured sweep (facets'
    sweep_id), so two dates or two curves never mix into one shape. A sweep is one curve, one
    point per concurrency (the contract validator already refuses anything else); it's checked
    again here because v1's sweep_shape keys by concurrency and would silently keep the last."""
    curve = lambda r: r.get("_curve") or facets[r["point_id"]]["sweep_id"]  # noqa: E731 (merge_repeats' join)
    sweeps: "OrderedDict[str, list[dict]]" = OrderedDict()
    for r in sorted(rows, key=lambda r: (curve(r), r["concurrency"], r["point_id"])):
        sweeps.setdefault(curve(r), []).append(r)
    for sid, pts in sweeps.items():
        concs = [p["concurrency"] for p in pts]
        if len(concs) != len(set(concs)):
            raise ContractError(f"sweep {sid} has two points at one concurrency")
        for p in pts:
            p["sweep_id"] = sid
        for metric in ("ttft", "tpot"):
            for p in pts:
                p[f"mape_{metric}"] = v1.point_mape(p[f"pred_{metric}_us"], p[f"meas_{metric}_us"])
            sh = v1.sweep_shape(pts, metric)
            for p in pts:
                p[f"shape_{metric}"] = sh.get(p["concurrency"])
        shapeless = len([p for p in pts if p["meas_ttft_us"] > 0 and p["pred_ttft_us"] > 0]) < v1.MIN_SHAPE_POINTS
        for p in pts:
            p["_shapeless"] = shapeless
            p["noise_floor_pct"] = None
    return sweeps


def _group(points, keyfn):
    g: "OrderedDict" = OrderedDict()
    for p in points:
        g.setdefault(keyfn(p), []).append(p)
    return g


def build_matrix(flat: list[dict], facets: dict, fidelity: dict) -> list[dict]:
    """model -> workload -> gpu -> topology -> point, as v1, with v2's point fields."""
    for p in flat:
        p["_f"] = facets[p["point_id"]]
    matrix = []
    for model, mpts in sorted(_group(flat, lambda p: p["_f"]["model"]).items()):
        versions = sorted({p["_f"].get("vllm_version") for p in mpts if p["_f"].get("vllm_version")})
        mnode = {"level": "model", "model": model, "source": "inferencex",
                 "vllm_version": versions[0] if len(versions) == 1 else None,
                 "coverage": {"scored": len(mpts), "total": len(mpts)},
                 "metrics": v1.metric_block_pair(mpts), "rows": []}
        for wl, wpts in sorted(_group(mpts, lambda p: p["_f"]["workload"]).items()):
            isl = osl = None
            if ":" in str(wl):
                isl, osl = (int(x) for x in str(wl).split(":"))
            wnode = {"level": "workload", "label": str(wl), "isl": isl, "osl": osl,
                     "coverage": {"scored": len(wpts), "total": len(wpts)},
                     "metrics": v1.metric_block_pair(wpts), "rows": []}
            for gpu, gpts in sorted(_group(wpts, lambda p: p["_f"]["gpu"]).items()):
                # A GPU's precision only when its rows agree; one GPU can serve fp4 and int4 runs.
                precs = {p["_f"]["precision"] for p in gpts}
                gnode = {"level": "gpu", "label": gpu, "precision": precs.pop() if len(precs) == 1 else None,
                         "coverage": {"scored": len(gpts), "total": len(gpts)},
                         "metrics": v1.metric_block_pair(gpts), "rows": []}
                for _, tpts in sorted(_group(gpts, _deployment).items()):
                    gnode["rows"].append(topology_node(tpts, fidelity))
                _unique_labels(gnode["rows"])
                gnode["rows"].sort(key=lambda n: (n["label"], n["engine_version"] or ""))
                wnode["rows"].append(gnode)
            mnode["rows"].append(wnode)
        matrix.append(mnode)
    return matrix


def _deployment(p: dict) -> tuple:
    """A topology row is one deployment on one vLLM build: the scenario (model, part, precision,
    parallelism), the build, and the drafter, so a spec and a no-spec run never share a row."""
    f = p["_f"]
    return (f["scenario"], f.get("vllm_version") or "", f["spec_method"] or "none")


def _spec(method) -> str | None:
    return None if method in (None, "", "none") else method


def topology_node(tpts: list[dict], fidelity: dict) -> dict:
    f0 = tpts[0]["_f"]
    for p in tpts:
        # The row's labels describe every point under it (the key guarantees it; checked anyway).
        if (p["_f"]["precision"], p["_f"]["parallelism"], p["_f"]["serving"], p["_f"]["framework"]) != \
                (f0["precision"], f0["parallelism"], f0["serving"], f0["framework"]):
            raise ContractError(f"scenario {f0['scenario']} mixes deployments")
    par = {k: v for k, v in sorted(f0["parallelism"].items()) if v is not None}
    base = " · ".join(f"{k}{v}" for k, v in par.items()) or "default"
    spec = _spec(f0["spec_method"])
    ver = f0.get("vllm_version") or None
    return {"level": "topology", "framework": f0["framework"], "engine_version": ver,
            "precision": f0["precision"], "is_multinode": False, "parallelism": par,
            "serving": f0["serving"], "spec_method": f0["spec_method"],
            "label": f"{base} · {f0['precision']}" + (f" · {spec}" if spec else ""),
            "coverage": {"scored": len(tpts), "total": len(tpts)},
            "metrics": v1.metric_block_pair(tpts),
            "rows": [point_node(p, fidelity[p["point_id"]])
                     for p in sorted(tpts, key=lambda p: (p["concurrency"], p["measured_date"], p["sweep_id"]))]}


def _unique_labels(rows: list[dict]) -> None:
    """One deployment measured on two vLLM builds is two rows; the UI keys rows by label, so
    those rows name their build."""
    seen = Counter(r["label"] for r in rows)
    for r in rows:
        if seen[r["label"]] > 1:
            r["label"] += f" · vLLM {r['engine_version'] or 'unknown'}"
    labels = [r["label"] for r in rows]
    if len(labels) != len(set(labels)):
        raise ContractError(f"two deployment rows share the label {Counter(labels).most_common(1)[0][0]!r}")


def point_node(p: dict, fid: dict) -> dict:
    node = v1.point_node(p)
    node["point_id"] = p["point_id"]
    # The measured curve the point's trend is computed in.
    node["sweep_id"] = p["sweep_id"]
    if p.get("_repeats"):
        # InferenceX ran this measurement more than once with identical inputs; `measured` is
        # the runs' mean, and each run is listed with its own measured value.
        node["repeats"] = p["_repeats"]
    node["measured_date"] = p["measured_date"]
    node["fidelity"] = {k: v for k, v in fid.items() if k != "point_id"}
    return node


def build(directory: Path, *, generated_at: str, evaluator_commit: str) -> dict:
    problems = contract.validate_dir(directory)
    if problems:
        raise ContractError("contract directory is invalid:\n  " + "\n  ".join(problems))
    fidelity = {r["point_id"]: r for r in _lines(directory / contract.FIDELITY_JSONL)}
    rows = read_points(directory, fidelity)
    facets = json.loads((directory / contract.FACETS_JSON).read_text())
    not_scored = _lines(directory / contract.NOT_SCORED_JSONL)
    prov_in = json.loads((directory / contract.PROVENANCE_JSON).read_text())

    rows, runs = merge_repeats(rows, facets, fidelity)
    sweeps = enrich(rows, facets)
    flat = [p for pts in sweeps.values() for p in pts]
    for p in flat:
        if p["point_id"] in runs:
            p["_repeats"] = runs[p["point_id"]]
    matrix = build_matrix(flat, facets, fidelity)
    totals = v1.metric_block_pair(flat)
    v1.assert_self_consistent(flat, totals)

    # How many not-scored points carry each reason code (a point counts once per code, so a
    # code's count is a number of points; a point with two codes counts under both).
    reasons = Counter(code for ns in not_scored for code in sorted({r.split(":", 1)[0] for r in ns["reasons"]}))
    folded = sum(len(r) - 1 for r in runs.values())
    coverage = {"scored": len(flat), "not_scored": len(not_scored), "multinode_hidden": 0, "failed": 0,
                "repeat_runs_folded": folded, "not_scored_reasons": dict(sorted(reasons.items()))}
    # The balance: every point the pull holds is scored (alone or as a repeat run of one shown
    # measurement) or not scored, exactly once.
    ids = [p["point_id"] for p in flat if p["point_id"] not in runs] + \
        [x["point_id"] for r in runs.values() for x in r] + [ns["point_id"] for ns in not_scored]
    if len(ids) != len(rows) + folded + len(not_scored):
        raise ContractError("repeat folding lost a point")
    if len(ids) != len(set(ids)):
        raise ContractError("a point is both scored and not scored")

    pull_date = prov_in["pulled_at"][:10]
    dates = sorted({p["measured_date"] for p in flat} | {ns["measured_date"] for ns in not_scored})
    provenance = {
        "blis": prov_in["blis"],
        # What the extractor pulled, as it recorded it (provenance.json's source).
        "ground_truth": {"source": prov_in["source"]["name"], "source_url": prov_in["source"]["url"],
                         "release_tag": f"api-{pull_date}",
                         "measurement_date_through": dates[-1] if dates else None,
                         "measurement_sha256": prov_in["pull_manifest_sha256"]},
        "evaluator_commit": evaluator_commit, "scorer": "signedprobe", "ingest": "api",
        "vllm_ref": prov_in["vllm_ref"], "vllm_max_distance": prov_in["vllm_max_distance"],
        "policy_sha256": prov_in["policy_sha256"], "pulled_at": prov_in["pulled_at"], "corpus": prov_in["corpus"],
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "snapshot_id": f"{generated_at[:10]}_blis-{prov_in['blis']['release']}_ix-api-{pull_date}",
        "generated_at": generated_at,
        "provenance": provenance,
        "coverage": coverage,
        "known_artefacts": [],
        "metrics": ["ttft", "tpot"],
        "metricscore_comparison": None,
        "totals": totals,
        "matrix": matrix,
        "scope": {"multinode": "not scored by the API extractor (blis_refused:disaggregated_or_multinode)",
                  "measured_exclusions": [], "vllm_version_filter": "all"},
        "not_scored": not_scored,
    }


def dumps(summary: dict) -> str:
    return json.dumps(summary, indent=2, sort_keys=False, ensure_ascii=False) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--contract", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--generated-at", help="ISO timestamp; defaults to the pull time, so a rebuild is byte-identical")
    ap.add_argument("--evaluator-commit", default="local")
    a = ap.parse_args(argv)
    prov = json.loads((a.contract / contract.PROVENANCE_JSON).read_text())
    summary = build(a.contract, generated_at=a.generated_at or prov["pulled_at"], evaluator_commit=a.evaluator_commit)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(dumps(summary))
    print(f"summary.json v2 written: {a.out} (scored {summary['coverage']['scored']}, "
          f"not scored {summary['coverage']['not_scored']})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ContractError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        sys.exit(3)
