#!/usr/bin/env python3
"""Validate a summary.json v2 against schemas/summary.v2.json (issue #30).

v2 $refs the fidelity record's schema (orchestrator/ingest/fidelity.schema.json) by its $id, so
the validator is given a registry holding it. Beyond the schema: schema_version is 2, the
coverage counts match the lists, not_scored_reasons count the not-scored codes, no point is
both scored and not scored, every build is measured from the snapshot's own vllm_ref and an
exact build sits within its vllm_max_distance, every not-scored record's identity hashes to
its point_id, and the matrix agrees with itself (tree_problems: metrics recompute from points,
labels match their rows, one point per concurrency per sweep). Exits non-zero on any problem,
never a silent pass.

v1 snapshots keep using orchestrator/validate_summary.py, unchanged.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "orchestrator" / "ingest"))
from contract import point_id  # noqa: E402
SCHEMA = REPO / "schemas" / "summary.v2.json"
FIDELITY = REPO / "orchestrator" / "ingest" / "fidelity.schema.json"


def validator():
    import jsonschema
    from referencing import Registry, Resource
    fid = json.loads(FIDELITY.read_text())
    reg = Registry().with_resource(fid["$id"], Resource.from_contents(fid))
    return jsonschema.Draft7Validator(json.loads(SCHEMA.read_text()), registry=reg)


def points(doc: dict) -> list[dict]:
    return [p for m in doc.get("matrix", []) for w in m.get("rows", []) for g in w.get("rows", [])
            for t in g.get("rows", []) for p in t.get("rows", [])]


def problems(doc: dict) -> list[str]:
    out = []
    for e in sorted(validator().iter_errors(doc), key=lambda e: list(e.path))[:25]:
        out.append(f"at {'/'.join(str(p) for p in e.path) or '(root)'}: {e.message[:300]}")
    if out:
        return out
    if doc.get("schema_version") != 2:
        return [f"schema_version is {doc.get('schema_version')!r}, expected 2"]
    pts, ns, cov = points(doc), doc["not_scored"], doc["coverage"]
    if cov["scored"] != len(pts):
        out.append(f"coverage.scored {cov['scored']} != {len(pts)} points in the matrix")
    if cov["not_scored"] != len(ns):
        out.append(f"coverage.not_scored {cov['not_scored']} != {len(ns)} not_scored records")
    want = dict(sorted(Counter(c for n in ns for c in sorted({r.split(":", 1)[0] for r in n["reasons"]})).items()))
    if cov["not_scored_reasons"] != want:
        out.append(f"coverage.not_scored_reasons {cov['not_scored_reasons']} != the not_scored codes {want}")
    scored = [p["point_id"] for p in pts]
    if len(set(scored)) != len(scored):
        out.append("a point_id appears twice in the matrix")
    both = set(scored) & {n["point_id"] for n in ns}
    if both:
        out.append(f"{len(both)} point(s) both scored and not scored")
    prov = doc.get("provenance") or {}
    ref, window = prov.get("vllm_ref"), prov.get("vllm_max_distance")
    for p in pts:
        b = p["fidelity"]["build"]
        if ref and b["ref"] != ref:
            out.append(f"{p['point_id'][:12]}: build measured from {b['ref']}, not the snapshot's vllm_ref {ref}")
        if b.get("match") == "exact" and window is not None and (b["distance"] is None or abs(b["distance"]) > window):
            out.append(f"{p['point_id'][:12]}: an exact build {b['distance']} commits from {b['ref']} (window {window})")
    for n in ns:
        if point_id(n["identity"]) != n["point_id"]:
            out.append(f"not_scored {n['point_id'][:12]}: identity doesn't hash to its point_id")
    return out + tree_problems(doc)


# Stored metrics are means of unrounded errors; points carry them rounded to 4 decimals, so a
# recomputation from the points agrees to within half a unit in the 4th place.
METRIC_TOLERANCE = 1e-3
TIERS = ("measured_or_resolved", "all")


def _mean_abs(values):
    vals = [abs(v) for v in values if v is not None]
    return (sum(vals) / len(vals) if vals else None), len(vals)


def recompute(pts: list[dict], tier: str) -> dict:
    """A metric block's mape/shape from its points, as build_summary.aggregate computes it."""
    if tier == "measured_or_resolved":
        pts = [p for p in pts if p["tier"] == "measured_or_resolved"]
    out = {}
    for kind, get in (("mape", lambda p, m: (p.get("error_pct") or {}).get(m)),
                      ("shape", lambda p, m: (p.get("shape") or {}).get(m))):
        (t, nt), (o, no) = (_mean_abs([get(p, m) for p in pts]) for m in ("ttft", "tpot"))
        out[kind] = {"ttft": t, "tpot": o, "n": max(nt, no)}
    return out


def _metric_problems(where: str, node: dict, pts: list[dict]) -> list[str]:
    out = []
    if node["coverage"]["scored"] != len(pts):
        out.append(f"{where}: coverage.scored {node['coverage']['scored']} != its {len(pts)} points")
    for tier in TIERS:
        want, got = recompute(pts, tier), node["metrics"][tier]
        for kind in ("mape", "shape"):
            if got[kind]["n"] != want[kind]["n"]:
                out.append(f"{where}: {tier} {kind} n {got[kind]['n']} != {want[kind]['n']} from its points")
            for m in ("ttft", "tpot"):
                a, b = got[kind][m], want[kind][m]
                if (a is None) != (b is None) or (a is not None and abs(a - b) > METRIC_TOLERANCE):
                    out.append(f"{where}: {tier} {kind}.{m} {a} != {b} from its points")
    return out


def _spec(method) -> str | None:
    return None if method in (None, "", "none") else method


def tree_problems(doc: dict) -> list[str]:
    """The matrix agrees with itself: every level's metrics recompute from the points under it;
    a deployment row's label states its precision and drafter, and is unique within its GPU; a
    GPU states a precision only if all its rows share it; within a row, a sweep has one point per
    concurrency and its lowest one is the trend's anchor (no trend); a sweep lives in one row."""
    out = []
    pts_of = lambda n: points({"matrix": [n]}) if n["level"] == "model" else (  # noqa: E731
        [p for g in n["rows"] for t in g["rows"] for p in t["rows"]] if n["level"] == "workload" else
        [p for t in n["rows"] for p in t["rows"]] if n["level"] == "gpu" else n["rows"])
    out += _metric_problems("totals", {"coverage": {"scored": doc["coverage"]["scored"]}, "metrics": doc["totals"]},
                            points(doc))
    row_of_sweep: dict = {}
    for m in doc["matrix"]:
        out += _metric_problems(f"{m['model']}", m, pts_of(m))
        for w in m["rows"]:
            out += _metric_problems(f"{m['model']} › {w['label']}", w, pts_of(w))
            for g in w["rows"]:
                gw = f"{m['model']} › {w['label']} › {g['label']}"
                out += _metric_problems(gw, g, pts_of(g))
                labels = [t["label"] for t in g["rows"]]
                if len(labels) != len(set(labels)):
                    out.append(f"{gw}: two deployment rows share a label")
                if g.get("precision") is not None and any(t.get("precision") != g["precision"] for t in g["rows"]):
                    out.append(f"{gw}: GPU precision {g['precision']} but a row has another")
                for t in g["rows"]:
                    tw = f"{gw} › {t['label']}"
                    out += _metric_problems(tw, t, t["rows"])
                    # "<parallelism> · <precision>[ · <drafter>][ · vLLM <version>]"
                    label = t["label"].split(" · vLLM ", 1)[0]
                    spec = _spec(t.get("spec_method"))
                    want = f" · {t.get('precision')}" + (f" · {spec}" if spec else "")
                    if not label.endswith(want):
                        out.append(f"{tw}: label doesn't state the row's precision and drafter ({want.lstrip(' ·')})")
                    by_sweep: dict = {}
                    for p in t["rows"]:
                        by_sweep.setdefault(p["sweep_id"], []).append(p)
                    for sid, sp in by_sweep.items():
                        if row_of_sweep.setdefault(sid, tw) != tw:
                            out.append(f"sweep {sid} is split across rows {row_of_sweep[sid]!r} and {tw!r}")
                        concs = [p["concurrency"] for p in sp]
                        if len(concs) != len(set(concs)):
                            out.append(f"{tw}: sweep {sid} has two points at one concurrency")
                        shaped = [p for p in sp if p.get("shape") is not None]
                        if shaped:
                            anchor = min(shaped, key=lambda p: p["concurrency"])
                            if any(v is not None for v in anchor["shape"].values()):
                                out.append(f"{tw}: sweep {sid}'s lowest concurrency has a trend value; it's the anchor")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("summary", nargs="+")
    a = ap.parse_args(argv)
    bad = 0
    for path in a.summary:
        found = problems(json.loads(Path(path).read_text()))
        if found:
            bad += 1
            print(f"INVALID: {path}", file=sys.stderr)
            for p in found:
                print(f"  {p}", file=sys.stderr)
        else:
            print(f"VALID: {path} conforms to schema_version 2")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
