#!/usr/bin/env python3
"""Shape cmd/signedprobe's per-point CSV into the dashboard's summary.json (RFC-0001 §4.4).

This repo only orchestrates and presents (RFC A4): it computes MAPE / shape / aggregates from
signedprobe's CSV -- the single source of truth -- and holds NO other scoring logic, no copied
extractors, no log parsing, and does not reimplement the scorer's exclusions. Facets the CSV
does not carry (tp/ep/precision/spec_method/serving) are read from the direct-corpus JSON and
joined by (scenario, label).

Numbers in: signedprobe CSV columns, in MICROSECONDS --
    scenario, model, gpu, label, concurrency,
    meas_tpot_us, pred_tpot_us, meas_ttft_us, pred_ttft_us, tier_unbracketed

The MAPE / shape definitions replicated here are cmd/metricscore's simulatedErrors arithmetic
(the documented meaning of the numbers), computed per point and averaged as the mean of
individual |point errors| at every level (RFC §4.4), never child-node means.

Fail-loud contract (RFC A7): if signedprobe renamed its columns or stopped shipping, this exits
non-zero with a clear message rather than mis-parsing or silently falling back.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import os
import sys
from collections import OrderedDict
from typing import Any

# The one external contract. A future release that renames a column must fail the run loudly
# (RFC A7), the same discipline as schema_version on summary.json.
EXPECTED_HEADER = [
    "scenario", "model", "gpu", "label", "concurrency",
    "meas_tpot_us", "pred_tpot_us", "meas_ttft_us", "pred_ttft_us", "tier_unbracketed",
]

# signedprobe emits harness Tier.String(); map onto the schema's two reported tiers.
# ALL (approximate) is the "all" bucket; MEASURED-OR-RESOLVED / STRICT are the apples-to-apples
# "measured_or_resolved" bucket. (STRICT is a stricter subset of measured-or-resolved; v0.1.0
# reports two tiers, so it folds into measured_or_resolved.)
TIER_MAP = {
    "MEASURED-OR-RESOLVED": "measured_or_resolved",
    "STRICT": "measured_or_resolved",
    "ALL (approximate)": "all",
}
# UNSCORABLE is a real tier signedprobe emits for points BLIS cannot score end-to-end — chiefly
# speculative (mtp) sweeps, where `blis replay` refuses a drafting scenario with no acceptance
# rate. Per RFC §4.4 these are NOT scored into the metrics; they are counted in coverage as
# not_scored (reason no_acceptance_rate for mtp). So an UNSCORABLE row is dropped from scoring,
# never folded into "all".
TIER_UNSCORABLE = "UNSCORABLE"
# "all" is the superset: every measured_or_resolved point also counts in "all".
SCHEMA_TIERS = ["measured_or_resolved", "all"]

MIN_SHAPE_POINTS = 3  # a sweep with < 3 concurrencies has no shape (RFC §4.4)
FALLBACK_NOISE_FLOOR_PCT = 1.6  # corpus-wide median; documented fallback only (RFC §4.4)


class ColumnContractError(RuntimeError):
    """signedprobe's CSV header changed or it shipped nothing -- fail loud, never mis-parse."""


# ----------------------------------------------------------------------------- CSV ingest

def read_signedprobe_csv(path: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (scored_rows, unscorable_rows). Scored rows carry a schema tier; unscorable rows
    (chiefly mtp) are held out of scoring and counted as not_scored (RFC §4.4)."""
    with open(path, newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            raise ColumnContractError(
                f"signedprobe CSV {path} is empty -- the probe emitted no header; "
                "it may no longer ship, or the run failed."
            )
        if header != EXPECTED_HEADER:
            raise ColumnContractError(
                "signedprobe columns changed at this release -- update the parser.\n"
                f"  expected: {EXPECTED_HEADER}\n"
                f"  got:      {header}"
            )
        rows: list[dict[str, Any]] = []
        unscorable: list[dict[str, Any]] = []
        for raw in reader:
            if not raw:
                continue
            r = dict(zip(header, raw))
            r["concurrency"] = int(r["concurrency"])
            for k in ("meas_tpot_us", "pred_tpot_us", "meas_ttft_us", "pred_ttft_us"):
                r[k] = float(r[k])
            tier = r["tier_unbracketed"]
            if tier == TIER_UNSCORABLE:
                unscorable.append(r)
                continue
            if tier not in TIER_MAP:
                raise ColumnContractError(
                    f"signedprobe emitted an unknown tier {tier!r} -- update TIER_MAP."
                )
            r["tier"] = TIER_MAP[tier]
            rows.append(r)
    if not rows and not unscorable:
        # A probe that emitted only its header is a failure, not a result (mirrors signedprobe
        # itself, which exits 1 in that case).
        raise ColumnContractError(
            f"signedprobe CSV {path} has a header but no data rows -- nothing was scored."
        )
    return rows, unscorable


def read_corpus_facets(path: str) -> dict[tuple[str, str], dict[str, Any]]:
    """Facets the CSV does not carry, keyed by (scenario, label). Only the clean sweep facet
    fields are read -- never any third-party baseline's per-point relative keys -- so the
    shipped summary.json stays free of those names (RFC C1)."""
    with open(path) as fh:
        doc = json.load(fh)
    facets: dict[tuple[str, str], dict[str, Any]] = {}
    for sw in doc.get("sweeps", []):
        par = sw.get("parallelism", {}) or {}
        facets[(sw["scenario"], sw["label"])] = {
            "precision": sw.get("precision"),
            "serving": sw.get("serving"),
            "spec_method": sw.get("spec_method"),
            "framework": sw.get("framework"),
            "isl_osl": sw.get("workload"),
            "parallelism": {
                "tp": par.get("tp_size"),
                "ep": par.get("moe_ep_size"),
                "pp": par.get("pp_size"),
                "dp": par.get("attention_dp_size"),
            },
        }
    return facets


def _read_engine_versions(path: str) -> dict[tuple[str, str], str]:
    """Per-(scenario,label) resolved engine_version from the engine-settings file. Reads the
    first concurrency's resolved.engine_version. Only this clean field is read."""
    out: dict[tuple[str, str], str] = {}
    with open(path) as fh:
        doc = json.load(fh)
    for sw in doc.get("settings", []):
        bycon = sw.get("by_concurrency", {}) or {}
        ev = None
        for _, ps in sorted(bycon.items(), key=lambda kv: int(kv[0])):
            ev = (ps.get("resolved") or {}).get("engine_version")
            if ev:
                break
        if ev:
            out[(sw["scenario"], sw["label"])] = ev
    return out


def _read_scenario_versions(scenarios_dir: str) -> dict[str, str]:
    """Per-scenario engine_version from the generated scenario YAMLs, keyed by the scenario
    filename. In the direct path the engine-settings `resolved.engine_version` is empty (the
    dump's benchmark rows carry no resolved-engine line), so the authoritative measured version
    is the scenario's own `engine_version:` field, which the scenario generator writes from the
    dump's topology record. Parsed with a plain line scan (no YAML dep)."""
    out: dict[str, str] = {}
    for p in glob.glob(os.path.join(scenarios_dir, "*.yaml")):
        name = os.path.basename(p)
        try:
            with open(p) as fh:
                for line in fh:
                    s = line.strip()
                    if s.startswith("engine_version:"):
                        v = s.split(":", 1)[1].strip().strip('"').strip("'")
                        if v:
                            out[name] = v
                        break
        except OSError:
            continue
    return out


# ------------------------------------------------------------------- MAPE / shape arithmetic
# These replicate cmd/metricscore's simulatedErrors (the documented definition of the numbers).

def point_mape(pred_us: float, meas_us: float) -> float | None:
    """(predicted/measured - 1) * 100, the plain absolute-level error, as a SIGNED percent."""
    if meas_us is None or meas_us <= 0 or pred_us is None or pred_us <= 0:
        return None
    return (pred_us / meas_us - 1.0) * 100.0


def sweep_shape(points: list[dict[str, Any]], metric: str) -> dict[int, float | None]:
    """Signed shape error per concurrency for one metric across a sweep.

    Both sides are re-anchored at the sweep's LOWEST SURVIVING concurrency and the anchor is
    excluded (its shape is 0 by construction). shape = (pred/pred_anchor / meas_relative - 1)*100
    where meas_relative = meas/meas_anchor -- identical to metricscore, both anchors cancelled to
    the same surviving point. Returns {} (no shape) if < 3 points survive.
    """
    pcol, mcol = f"pred_{metric}_us", f"meas_{metric}_us"
    usable = [p for p in points if p[mcol] > 0 and p[pcol] > 0]
    usable.sort(key=lambda p: p["concurrency"])
    if len(usable) < MIN_SHAPE_POINTS:
        return {}
    anchor = usable[0]
    pred_anchor, meas_anchor = anchor[pcol], anchor[mcol]
    out: dict[int, float | None] = {anchor["concurrency"]: None}  # anchor excluded
    for p in usable[1:]:
        meas_rel = p[mcol] / meas_anchor
        pred_rel = p[pcol] / pred_anchor
        out[p["concurrency"]] = (pred_rel / meas_rel - 1.0) * 100.0
    return out


def mean_abs(values: list[float | None]) -> tuple[float | None, int]:
    """Mean of |individual point errors| (RFC §4.4: never child-node means). n is the count."""
    vals = [abs(v) for v in values if v is not None]
    if not vals:
        return None, 0
    return sum(vals) / len(vals), len(vals)


# ----------------------------------------------------------------------- aggregate over points

def aggregate(points: list[dict[str, Any]], tier: str) -> dict[str, Any]:
    """A metricBlock for one tier over a flat list of scored points.

    "all" is the superset (every point); "measured_or_resolved" is the apples-to-apples subset.
    """
    if tier == "measured_or_resolved":
        pts = [p for p in points if p["tier"] == "measured_or_resolved"]
    else:
        pts = points  # all
    mape_ttft = mean_abs([p["mape_ttft"] for p in pts])
    mape_tpot = mean_abs([p["mape_tpot"] for p in pts])
    shape_ttft = mean_abs([p["shape_ttft"] for p in pts])
    shape_tpot = mean_abs([p["shape_tpot"] for p in pts])
    noise = [p["noise_floor_pct"] for p in pts if p.get("noise_floor_pct") is not None]
    return {
        "mape": {"ttft": mape_ttft[0], "tpot": mape_tpot[0], "n": max(mape_ttft[1], mape_tpot[1])},
        "shape": {"ttft": shape_ttft[0], "tpot": shape_tpot[0], "n": max(shape_ttft[1], shape_tpot[1])},
        "noise_floor_pct": (sum(noise) / len(noise)) if noise else FALLBACK_NOISE_FLOOR_PCT,
    }


def metric_block_pair(points: list[dict[str, Any]]) -> dict[str, Any]:
    return {t: aggregate(points, t) for t in SCHEMA_TIERS}


# -------------------------------------------------------------------------------- tree build

def enrich_points(rows: list[dict[str, Any]], noise_by_sweep: dict[tuple[str, str], float | None]):
    """Compute per-point mape + shape in place. Groups by (scenario,label) for the shape anchor."""
    sweeps: "OrderedDict[tuple[str,str], list[dict]]" = OrderedDict()
    for r in rows:
        sweeps.setdefault((r["scenario"], r["label"]), []).append(r)
    for key, pts in sweeps.items():
        for metric in ("ttft", "tpot"):
            for p in pts:
                p[f"mape_{metric}"] = point_mape(p[f"pred_{metric}_us"], p[f"meas_{metric}_us"])
            sh = sweep_shape(pts, metric)
            for p in pts:
                p[f"shape_{metric}"] = sh.get(p["concurrency"])
            p0 = pts[0]  # record whether this sweep is shapeless, for shape_reason
        shapeless = len([p for p in pts if p["meas_ttft_us"] > 0 and p["pred_ttft_us"] > 0]) < MIN_SHAPE_POINTS
        for p in pts:
            p["_shapeless"] = shapeless
            p["noise_floor_pct"] = noise_by_sweep.get(key)
    return sweeps


def point_node(p: dict[str, Any]) -> dict[str, Any]:
    def ms(us: float) -> float | None:
        return round(us / 1000.0, 4) if us and us > 0 else None
    shape = None
    shape_reason = None
    if p["_shapeless"]:
        shape_reason = "< 3 concurrencies"
    else:
        shape = {"ttft": _r(p["shape_ttft"]), "tpot": _r(p["shape_tpot"])}
        if p["shape_ttft"] is None and p["shape_tpot"] is None:
            # the sweep has shape, but this is the excluded anchor point
            shape = {"ttft": None, "tpot": None}
    node = {
        "level": "point",
        "concurrency": p["concurrency"],
        "tier": p["tier"],
        "measured": {"ttft_ms": ms(p["meas_ttft_us"]), "tpot_ms": ms(p["meas_tpot_us"])},
        "predicted": {"ttft_ms": ms(p["pred_ttft_us"]), "tpot_ms": ms(p["pred_tpot_us"])},
        "error_pct": {"ttft": _r(p["mape_ttft"]), "tpot": _r(p["mape_tpot"])},
        "shape": shape,
    }
    if shape_reason:
        node["shape_reason"] = shape_reason
    return node


def _r(v: float | None) -> float | None:
    return round(v, 4) if v is not None else None


def build_matrix(sweeps, facets, vllm_by_sweep, totals_in_scope):
    """model -> workload -> gpu -> topology -> point, each node carrying a metricBlockPair
    recomputed from the leaf points under it (not stored-and-frozen; RFC §4.4 point 1)."""
    # Attach facets + enrich row objects with their grouping keys.
    flat: list[dict[str, Any]] = []
    for (scenario, label), pts in sweeps.items():
        f = facets.get((scenario, label), {})
        for p in pts:
            p["_facets"] = f
            p["_vllm"] = vllm_by_sweep.get((scenario, label))
            flat.append(p)

    def group(points, keyfn):
        g: "OrderedDict[Any, list]" = OrderedDict()
        for p in points:
            g.setdefault(keyfn(p), []).append(p)
        return g

    matrix = []
    for model, mpts in group(flat, lambda p: p["model"]).items():
        model_vllm = next((p["_vllm"] for p in mpts if p["_vllm"]), None)
        model_node = {
            "level": "model",
            "model": model,
            "source": "inferencex",
            "vllm_version": model_vllm,
            "on_target_version": None,  # vLLM version is a facet, not a verdict (no target concept)
            "coverage": {"scored": len(mpts), "total": len(mpts)},
            "metrics": metric_block_pair(mpts),
            "rows": [],
        }
        for wl, wpts in group(mpts, lambda p: p["_facets"].get("isl_osl") or p["label"]).items():
            isl = osl = None
            if wl and ":" in str(wl):
                try:
                    isl, osl = (int(x) for x in str(wl).split(":"))
                except ValueError:
                    pass
            wl_node = {
                "level": "workload", "label": str(wl),
                "isl": isl, "osl": osl,
                "coverage": {"scored": len(wpts), "total": len(wpts)},
                "metrics": metric_block_pair(wpts), "rows": [],
            }
            for gpu, gpts in group(wpts, lambda p: p["gpu"]).items():
                gpu_node = {
                    "level": "gpu", "label": gpu,
                    "precision": next((p["_facets"].get("precision") for p in gpts), None),
                    "coverage": {"scored": len(gpts), "total": len(gpts)},
                    "metrics": metric_block_pair(gpts), "rows": [],
                }
                for topokey, tpts in group(
                    gpts,
                    lambda p: (
                        p["_facets"].get("framework") or "vllm",
                        tuple(sorted((p["_facets"].get("parallelism") or {}).items())),
                        p["_facets"].get("serving"),
                        p["_facets"].get("spec_method"),
                        p["_vllm"],
                    ),
                ).items():
                    framework, par_items, serving, spec_method, tvllm = topokey
                    par = {k: v for k, v in par_items if v is not None}
                    label = " · ".join(f"{k}{v}" for k, v in sorted(par.items())) or "default"
                    topo_node = {
                        "level": "topology",
                        "framework": framework,
                        "engine_version": tvllm,
                        "on_target_version": None,  # facet, not a verdict
                        "is_multinode": False,  # multinode filtered at extraction in v0.1.0
                        "parallelism": par,
                        "serving": serving,
                        "spec_method": spec_method,
                        "label": label,
                        "coverage": {"scored": len(tpts), "total": len(tpts)},
                        "metrics": metric_block_pair(tpts),
                        "rows": [point_node(p) for p in sorted(tpts, key=lambda p: p["concurrency"])],
                    }
                    gpu_node["rows"].append(topo_node)
                gpu_node["rows"].sort(key=lambda n: n["label"])
                wl_node["rows"].append(gpu_node)
            model_node["rows"].append(wl_node)
        matrix.append(model_node)
    matrix.sort(key=lambda n: n["model"])
    return matrix, flat


# ------------------------------------------------------------- self-consistency oracle (A6)

def assert_self_consistent(flat, totals):
    """Re-derive the headline aggregates a second, independent way from the SAME points and
    assert equality (RFC A6/§4.4). Tests our arithmetic, not a second tool, so it never drifts.
    """
    def independent_mean_abs(points, tier, field):
        if tier == "measured_or_resolved":
            points = [p for p in points if p["tier"] == "measured_or_resolved"]
        acc, n = 0.0, 0
        for p in points:
            v = p[field]
            if v is not None:
                acc += abs(v)
                n += 1
        return (acc / n) if n else None, n

    for tier in SCHEMA_TIERS:
        for metric in ("ttft", "tpot"):
            want = totals[tier]["mape"][metric]
            got, _ = independent_mean_abs(flat, tier, f"mape_{metric}")
            if not _close(want, got):
                raise AssertionError(
                    f"self-consistency FAILED: totals.{tier}.mape.{metric} = {want} but an "
                    f"independent re-derivation gives {got}"
                )
            wshape = totals[tier]["shape"][metric]
            gshape, _ = independent_mean_abs(flat, tier, f"shape_{metric}")
            if not _close(wshape, gshape):
                raise AssertionError(
                    f"self-consistency FAILED: totals.{tier}.shape.{metric} = {wshape} but an "
                    f"independent re-derivation gives {gshape}"
                )


def _close(a, b, tol=1e-9):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=tol)


# ------------------------------------------------------------------------------- same-points delta

def same_points_delta(flat, previous_summary):
    """Change vs the previous snapshot over the INTERSECTION of points both snapshots scored
    (RFC §4.4 / Q6). Returns None on the first snapshot."""
    if not previous_summary:
        return None
    prev_pts = _collect_prev_points(previous_summary)
    if not prev_pts:
        return None
    def key(p):
        return (p["scenario"], p["label"], p["concurrency"])
    cur = {key(p): p for p in flat}
    inter = [k for k in cur if k in prev_pts]
    if not inter:
        return None
    def delta(field_cur, field_prev):
        cur_vals = [abs(cur[k][field_cur]) for k in inter if cur[k][field_cur] is not None and prev_pts[k].get(field_prev) is not None]
        prev_vals = [abs(prev_pts[k][field_prev]) for k in inter if cur[k][field_cur] is not None and prev_pts[k].get(field_prev) is not None]
        if not cur_vals:
            return None
        return round(sum(cur_vals) / len(cur_vals) - sum(prev_vals) / len(prev_vals), 4)
    return {
        "tpot_mape": delta("mape_tpot", "error_tpot"),
        "ttft_mape": delta("mape_ttft", "error_ttft"),
        "n_intersect": len(inter),
    }


def _collect_prev_points(prev):
    out = {}
    def walk(node):
        if node.get("level") == "point":
            return
        for child in node.get("rows", []):
            if child.get("level") == "point":
                pass
            walk(child)
    # The previous summary stores per-point error_pct on point nodes; collect them keyed by the
    # topology scenario/label is not stored on the point, so we key by (model, workload, gpu,
    # topo-label, concurrency) which is stable across snapshots.
    def walk2(node, trail):
        lvl = node.get("level")
        if lvl == "point":
            k = (*trail, node["concurrency"])
            ep = node.get("error_pct", {})
            out[k] = {"error_ttft": ep.get("ttft"), "error_tpot": ep.get("tpot")}
            return
        key_part = node.get("model") or node.get("label") or ""
        for child in node.get("rows", []):
            walk2(child, (*trail, key_part) if lvl else trail)
    for m in prev.get("matrix", []):
        walk2(m, ())
    return out


# ------------------------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description="Build summary.json from signedprobe's CSV")
    ap.add_argument("--csv", required=True, help="signedprobe per-point CSV")
    ap.add_argument("--corpus", required=True, help="direct corpus JSON (facets)")
    ap.add_argument("--out", required=True, help="output summary.json")
    ap.add_argument("--provenance", required=True, help="provenance JSON (CI-resolved inputs)")
    ap.add_argument("--previous", help="previous summary.json for same-points delta", default=None)
    ap.add_argument("--engine-settings", help="engine-settings JSON for per-sweep resolved engine_version", default=None)
    ap.add_argument("--scenarios", help="scenario dir; engine_version read from each YAML (direct-path fallback)", default=None)
    ap.add_argument("--metricscore-log", help="metricscore stdout (logged, non-blocking)", default=None)
    args = ap.parse_args(argv)

    with open(args.provenance) as fh:
        prov = json.load(fh)

    rows, unscorable = read_signedprobe_csv(args.csv)
    facets = read_corpus_facets(args.corpus)

    # Per-sweep measured vLLM engine_version comes from the engine-settings file (the run's
    # resolved args), else the scenario YAML's engine_version (the direct path's source). A sweep
    # with neither carries null, which the UI shows as a marker — never NaN, never an assumed value.
    vllm_by_sweep = {}
    noise_by_sweep = {}
    engine_versions = _read_engine_versions(args.engine_settings) if args.engine_settings else {}
    scenario_versions = _read_scenario_versions(args.scenarios) if args.scenarios else {}
    for (scenario, label) in facets:
        ev = engine_versions.get((scenario, label)) or scenario_versions.get(scenario)
        vllm_by_sweep[(scenario, label)] = ev
        noise_by_sweep[(scenario, label)] = None

    sweeps = enrich_points(rows, noise_by_sweep)

    matrix, flat = build_matrix(sweeps, facets, vllm_by_sweep, None)

    totals = metric_block_pair(flat)
    assert_self_consistent(flat, totals)

    previous_summary = None
    if args.previous:
        try:
            with open(args.previous) as fh:
                previous_summary = json.load(fh)
        except FileNotFoundError:
            previous_summary = None

    delta = same_points_delta(flat, previous_summary)
    totals["measured_or_resolved"]["same_points_delta"] = delta
    totals["all"]["same_points_delta"] = delta

    metricscore_comparison = None
    if args.metricscore_log:
        try:
            with open(args.metricscore_log) as fh:
                metricscore_comparison = {"raw": fh.read()[:20000], "gated": False}
        except FileNotFoundError:
            metricscore_comparison = None

    summary = {
        "schema_version": 1,
        "snapshot_id": prov["snapshot_id"],
        "generated_at": prov["generated_at"],
        "previous_snapshot_id": (previous_summary or {}).get("snapshot_id"),
        "provenance": prov["provenance"],
        "coverage": prov["coverage"],
        "known_artefacts": prov.get("known_artefacts", []),
        "metrics": ["ttft", "tpot"],
        "metricscore_comparison": metricscore_comparison,
        "totals": totals,
        "matrix": matrix,
        "scope": {
            "multinode": "toggle (hidden by default; disabled in v0.1.0)",
            "measured_exclusions": ["ttft_spike", "non_monotone_tpot_sweep"],
            "vllm_version_filter": "all",
        },
    }

    with open(args.out, "w") as fh:
        json.dump(summary, fh, indent=2)
        fh.write("\n")

    print(f"summary.json written: {args.out}", file=sys.stderr)
    print(f"  models={len(matrix)} scored_points={len(flat)} "
          f"totals.tpot_mape={totals['all']['mape']['tpot']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ColumnContractError as e:
        print(f"FATAL (column contract): {e}", file=sys.stderr)
        sys.exit(3)
