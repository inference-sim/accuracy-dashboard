#!/usr/bin/env python3
"""Validate a summary.json v2 or v3 against its schema (schemas/summary.v2.json, summary.v3.json).

Each $refs its fidelity record's schema (schemas/fidelity.v2.json, fidelity.v3.json) by its $id,
so the validator is given a registry holding it. v2 is what snapshots published before grades
hold; they never change (COV-8), and are checked as they were. Beyond the schema, for both: the
coverage counts match the lists, no point is both scored and not scored, every not-scored
record's identity hashes to its point_id, and the matrix agrees with itself (tree_problems:
metrics recompute from points, labels match their rows, one point per concurrency per sweep).
v2 also: not_scored_reasons count the not-scored codes, every build is measured from the
snapshot's own vllm_ref, and an exact build sits within its vllm_max_distance. v3 also: every
point's grade agrees with its release and the engine release (grade.check: COV-4 to COV-6),
the headline and coverage recompute from the points and every figure under the minimum is "too
few points" (COV-11), the grade counts sum to the total (COV-1), and no failed point is other
than a runner limit (COV-8). Exits non-zero on any problem, never a silent pass.

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
import contract  # noqa: E402
import legacy_ids  # noqa: E402


def point_id(identity: dict) -> str:
    """The id an identity hashes to: a ledger unit identity, or the eight-field identity of a
    snapshot published before point ids were unit ids (COV-8)."""
    if isinstance(identity, dict) and "recipe" in identity:
        return legacy_ids.legacy_point_id(identity)
    return contract.point_id(identity)
import assess  # noqa: E402
import backlog as bl  # noqa: E402
import grade as gr  # noqa: E402
import headline as hl  # noqa: E402

SCHEMAS = {2: (REPO / "schemas" / "summary.v2.json", REPO / "schemas" / "fidelity.v2.json"),
           3: (REPO / "schemas" / "summary.v3.json", REPO / "schemas" / "fidelity.v3.json")}


def validator(version: int):
    import jsonschema
    from referencing import Registry, Resource
    schema, fidelity = SCHEMAS[version]
    fid = json.loads(fidelity.read_text())
    reg = Registry().with_resource(fid["$id"], Resource.from_contents(fid))
    return jsonschema.Draft7Validator(json.loads(schema.read_text()), registry=reg)


def points(doc: dict) -> list[dict]:
    return [p for m in doc.get("matrix", []) for w in m.get("rows", []) for g in w.get("rows", [])
            for t in g.get("rows", []) for p in t.get("rows", [])]


def problems(doc: dict) -> list[str]:
    version = doc.get("schema_version")
    if version not in SCHEMAS:
        return [f"schema_version is {version!r}, expected one of {sorted(SCHEMAS)}"]
    out = []
    for e in sorted(validator(version).iter_errors(doc), key=lambda e: list(e.path))[:25]:
        out.append(f"at {'/'.join(str(p) for p in e.path) or '(root)'}: {e.message[:300]}")
    if out:
        return out
    pts, ns, cov = points(doc), doc["not_scored"], doc["coverage"]
    if version == 2:
        if cov["scored"] != len(pts):
            out.append(f"coverage.scored {cov['scored']} != {len(pts)} points in the matrix")
        if cov["not_scored"] != len(ns):
            out.append(f"coverage.not_scored {cov['not_scored']} != {len(ns)} not_scored records")
        want = dict(sorted(Counter(c for n in ns for c in sorted({r.split(":", 1)[0] for r in n["reasons"]})).items()))
        if cov["not_scored_reasons"] != want:
            out.append(f"coverage.not_scored_reasons {cov['not_scored_reasons']} != the not_scored codes {want}")
    else:
        out += _v3_problems(doc, pts)
    scored = [p["point_id"] for p in pts]
    if len(set(scored)) != len(scored):
        out.append("a point_id appears twice in the matrix")
    both = set(scored) & {n["point_id"] for n in ns}
    if both:
        out.append(f"{len(both)} point(s) both scored and not scored")
    # Folded repeat runs: each shown point lists itself among its runs, a run appears once, and
    # the shown measured value is the runs' mean.
    folded = []
    for p in pts:
        rs = p.get("repeats") or []
        if not rs:
            continue
        ids = [r["point_id"] for r in rs]
        if p["point_id"] != min(ids):
            out.append(f"{p['point_id'][:12]}: a folded point's id must be the smallest of its runs'")
        folded += [i for i in ids if i != p["point_id"]]
        for m in ("ttft_ms", "tpot_ms"):
            vals = [r["measured"][m] for r in rs]
            shown = (p.get("measured") or {}).get(m)
            if None not in vals and shown is not None and abs(sum(vals) / len(vals) - shown) > METRIC_TOLERANCE:
                out.append(f"{p['point_id'][:12]}: measured {m} {shown} isn't the mean of its runs")
    if len(folded) != len(set(folded)) or set(folded) & (set(scored) | {n["point_id"] for n in ns}):
        out.append("a folded repeat run also appears as another point")
    if cov.get("repeat_runs_folded", 0) != len(folded):
        out.append(f"coverage.repeat_runs_folded {cov.get('repeat_runs_folded', 0)} != {len(folded)} folded runs")
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
    # A scored point's identity must hash to its id too, so summary.json inverts losslessly back
    # to a contract for IX-only merges (Discussion #15, revised 2026-10-25).
    for p in pts:
        if "identity" in p and point_id(p["identity"]) != p["point_id"]:
            out.append(f"scored {p['point_id'][:12]}: identity doesn't hash to its point_id")
    return out + tree_problems(doc)


def _v3_problems(doc: dict, pts: list[dict]) -> list[str]:
    """What schema v3 adds: the grades, headline, coverage and backlog agree with the points."""
    out = []
    ns, failed, cov = doc["not_scored"], doc["failed"], doc["coverage"]
    engine = doc["provenance"]["engine"]["version"]
    # Every graded point, repeats unfolded: each run is an anchor unit of its own.
    runs = []
    for m, w, g, t, p in _leaves(doc):
        for r in p.get("repeats") or [{"point_id": p["point_id"], "identity": p["identity"], "measured": p["measured"]}]:
            runs.append({**p["fidelity"], "point_id": r["point_id"], "build": {"release": p["fidelity"]["run_release"]},
                         "framework": t["framework"], "hardware": r["identity"]["hardware"],
                         "release": p["fidelity"]["run_release"], "grade": p["fidelity"]["grade"],
                         "meas_ttft_us": _us(r["measured"].get("ttft_ms")), "meas_tpot_us": _us(r["measured"].get("tpot_ms")),
                         "pred_ttft_us": _us((p.get("predicted") or {}).get("ttft_ms")),
                         "pred_tpot_us": _us((p.get("predicted") or {}).get("tpot_ms"))})
    g5 = [{**n, "build": {"release": n["run_release"]}, "release": n["run_release"]} for n in ns]
    out += [f"grade: {x}" for x in gr.check(runs + g5, engine)]
    if cov["graded"] != len(runs):
        out.append(f"coverage.graded {cov['graded']} != {len(runs)} graded points")
    if cov["not_scored"] != len(ns) or cov["failed"] != len(failed):
        out.append(f"coverage not_scored/failed {cov['not_scored']}/{cov['failed']} != {len(ns)}/{len(failed)} records")
    if cov["points"] != len(runs) + len(ns) + len(failed):
        out.append(f"coverage.points {cov['points']} != graded + not scored + failed (COV-1)")
    want = hl.coverage(runs + g5, left_out_records=cov["left_out_records"])
    for k in ("by_engine", "by_engine_release", "by_chip", "by_grade"):
        if cov[k] != want[k]:
            out.append(f"coverage.{k} does not recompute from the points")
    if cov["g5_reasons"] != dict(sorted(Counter(n["g5_reason"]["code"] for n in ns).items())):
        out.append("coverage.g5_reasons does not count the not_scored reasons")
    head = doc["headline"]
    out += [f"headline: {x}" for x in hl.check(head)]
    again = hl.headline(runs + g5)
    for m in ("ttft", "tpot"):
        a, b = head["headline"][m], again["headline"][m]
        if a["n"] != b["n"] or (isinstance(a["mape"], float) != isinstance(b["mape"], float)) or \
                (isinstance(a["mape"], float) and abs(a["mape"] - b["mape"]) > HEADLINE_TOLERANCE):
            out.append(f"headline.{m} {a} does not recompute from the points ({b})")
    for g in gr.GRADED:
        if head["grades"][g]["points"] != again["grades"][g]["points"]:
            out.append(f"headline.grades.{g} counts {head['grades'][g]['points']} points, the matrix {again['grades'][g]['points']}")
    if [e["reason"] for e in doc["backlog"]["top"]] != [r for r, _ in bl.top(runs + g5, len(doc["backlog"]["top"]))]:
        out.append("backlog.top does not recompute from the points")
    for f in failed:
        if not set(f["faults"]) <= set(assess.RUNNER_LIMITS):
            out.append(f"failed {f['point_id'][:12]}: {f['faults']} is not a runner limit; nothing may be published (COV-8)")
    return out


def _leaves(doc: dict):
    for m in doc.get("matrix", []):
        for w in m.get("rows", []):
            for g in w.get("rows", []):
                for t in g.get("rows", []):
                    for p in t.get("rows", []):
                        yield m, w, g, t, p


def _us(ms):
    return None if ms is None else float(ms) * 1000.0


# Points carry measured and predicted values rounded to 4 decimals of a millisecond, so a headline
# recomputed from them agrees with the one built from the contract to within this many points of
# percentage error.
HEADLINE_TOLERANCE = 1e-2


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
    # v2 counts the matrix's points as coverage.scored; v3 counts graded anchor units, so the
    # matrix's own count (repeats folded) is what its totals cover.
    shown = doc["coverage"]["scored"] if doc["schema_version"] == 2 else len(points(doc))
    out += _metric_problems("totals", {"coverage": {"scored": shown}, "metrics": doc["totals"]}, points(doc))
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
            print(f"VALID: {path} conforms to schema_version {json.loads(Path(path).read_text())['schema_version']}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
