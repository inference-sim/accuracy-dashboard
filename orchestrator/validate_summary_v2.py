#!/usr/bin/env python3
"""Validate a summary.json v2 against schemas/summary.v2.json (issue #30).

v2 $refs the fidelity record's schema (orchestrator/ingest/fidelity.schema.json) by its $id, so
the validator is given a registry holding it. Beyond the schema: schema_version is 2, the
coverage counts match the lists, not_scored_reasons count the not-scored codes, no point is
both scored and not scored, every build is measured from the snapshot's own vllm_ref and an
exact build sits within its vllm_max_distance, and every not-scored record's identity hashes to
its point_id. Exits non-zero on any problem, never a silent pass.

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
