#!/usr/bin/env python3
"""Accuracy sliced by any recorded attribute, and the rule for small slices (design §11.3, COV-13; requirements §3B;
plan row 19).

A scored unit is cut by an attribute it records: its model, chip, engine, topology, workload, grade, a substitution and so
on. Each slice states its points, its role keys and its coverage beside its accuracy. A role key is one deployment under one
benchmark type (source, model, hardware, precision, framework, benchmark type, configuration): ten concurrencies of one
deployment are ten points and one role key. A slice over fewer than headline.MIN_POINTS role keys, not points, shows no
accuracy: the count stands in its place, its points stay listed, and it is left out of every verdict.

    slices.py --contract DIR [--by chip --by engine ...] --out slices.json

`m3_baseline.py report --slices slices.json` publishes it with the baseline. The summary's own published figures
(summary schema v3, COV-8) still count points; the dashboard applies the role-key rule to them in the browser.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ingest"))
import grade as gr  # noqa: E402
import headline as hl  # noqa: E402

FORMAT = "slices-1"
TOO_FEW = hl.TOO_FEW
DEFAULT_BY = ("engine", "chip", "model", "workload_type", "grade")

# What COV-13 names that a point record does not hold, so it cannot be sliced yet.
UNRECORDED = ("node_count", "interconnect", "offload", "router", "arrival", "prefix", "source_revision",
              "input_length", "output_length")


class SliceError(ValueError):
    pass


def _one(f):
    return lambda r: [str(f(r) if f(r) is not None else "unknown")]


def _topology(r):
    par = r["facets"].get("parallelism") or {}
    return " ".join(f"{k}{v}" for k, v in sorted(par.items())) or "unknown"


def _substitutions(r):
    kinds = sorted({s["kind"] for s in r.get("substitutions") or []})
    return kinds or ["none"]


ATTRS = {
    "source": ("source", _one(lambda r: r["identity"].get("source", "inferencex"))),
    "model": ("model", _one(lambda r: r["facets"].get("model"))),
    "precision": ("precision", _one(lambda r: r["facets"].get("precision"))),
    "chip": ("chip", _one(lambda r: r["facets"].get("gpu"))),
    "engine": ("engine", _one(lambda r: r["facets"].get("framework"))),
    "engine_version": ("engine version", _one(lambda r: (r.get("build") or {}).get("version"))),
    "engine_commit": ("engine commit", _one(lambda r: (r.get("build") or {}).get("commit"))),
    "topology": ("topology", _one(_topology)),
    "serving": ("serving (aggregated or P/D pools)", _one(lambda r: r["facets"].get("serving"))),
    "spec_method": ("speculative method", _one(lambda r: r["facets"].get("spec_method") or "none")),
    "workload": ("workload", _one(lambda r: r["facets"].get("workload"))),
    "workload_type": ("workload type", _one(lambda r: r["identity"].get("benchmark_type"))),
    "concurrency": ("concurrency", _one(lambda r: r["identity"].get("conc"))),
    "measured_month": ("measured month", _one(lambda r: (r["identity"].get("measured_date") or "")[:7] or None)),
    "grade": ("grade", _one(lambda r: r.get("grade"))),
    "commit_distance": ("commit distance (run commit against the modelled commit)",
                        lambda r: [(r.get("commit_distance") or {}).get("state") or "none"]),
    "substitution": ("substitution", _substitutions),
    "role_key": ("deployment (role key)", lambda r: [r["role_key"]]),
}


def role_key(rec: dict) -> str:
    """The ledger's role key where the record carries one; else the key of design Table 1.4 from its identity."""
    if rec.get("role_key"):
        return rec["role_key"]
    i = rec["identity"]
    fields = [i.get("source", "inferencex"), i["model"], i["hardware"], i["precision"], i["framework"],
              i["benchmark_type"], i.get("configuration_hash") or i.get("recipe") or ""]
    return hashlib.sha256("\x1f".join(fields).encode()).hexdigest()


def _error(rec: dict, metric: str):
    for f in rec.get("figures") or []:
        if f["metric"] == metric and f.get("measured") and f.get("predicted") is not None:
            return abs(f["predicted"] - f["measured"]) / f["measured"] * 100
    return None


def _commit_distances(contract: Path) -> dict[str, dict]:
    """point_id -> the commit-distance record of the dashboard's fidelity view (the substrate's strict point record has no
    such field). A contract without that view, or a point it does not list, has none."""
    p = contract / "fidelity.jsonl"
    if not p.is_file():
        return {}
    rows = (json.loads(x) for x in p.read_text().splitlines() if x.strip())
    return {r["point_id"]: r["commit_distance"] for r in rows if r.get("commit_distance")}


def graded_records(contract: Path) -> list[dict]:
    """The graded point records (G1 to G4) of a contract directory, each with its role key."""
    path = Path(contract) / "pointrecords.jsonl"
    states = _commit_distances(Path(contract))
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("grade") in gr.GRADED:
            r["role_key"] = role_key(r)
            r["commit_distance"] = states.get(r.get("point_id"))
            out.append(r)
    return out


def figure(recs: list[dict], metric: str, minimum: int) -> dict:
    """One accuracy with the points and role keys it covers. Under `minimum` role keys it is "too few points"."""
    held = [(r["role_key"], e) for r in recs if (e := _error(r, metric)) is not None]
    keys = len({k for k, _ in held})
    if keys < minimum:
        return {"mape": TOO_FEW, "n": len(held), "role_keys": keys}
    return {"mape": sum(e for _, e in held) / len(held), "n": len(held), "role_keys": keys}


def slice_by(recs: list[dict], by: str, minimum: int, not_scored: list[dict] | None = None) -> list[dict]:
    if by not in ATTRS:
        raise SliceError(f"cannot slice by {by!r}: sliceable attributes are {', '.join(ATTRS)}"
                         + (f"; {by} is not recorded on a point" if by in UNRECORDED else ""))
    label, values = ATTRS[by]
    groups: dict[str, list[dict]] = {}
    for r in recs:
        for v in values(r):
            groups.setdefault(v, []).append(r)
    rows = []
    for value, rs in groups.items():
        keys = len({r["role_key"] for r in rs})
        shown = keys >= minimum
        cov = None
        if by == "chip" and not_scored is not None:
            cov = {"scored": len(rs), "total": len(rs) + sum(1 for n in not_scored if n.get("hardware") == value)}
        rows.append({"value": value, "points": len(rs), "role_keys": keys, "coverage": cov, "shown": shown,
                     "ttft": figure(rs, "ttft_mean_ms", minimum), "tpot": figure(rs, "tpot_mean_ms", minimum),
                     "units": sorted(r["point_id"] for r in rs)})
    return sorted(rows, key=lambda r: (-r["points"], r["value"]))


def _not_scored(contract: Path) -> list[dict] | None:
    p = Path(contract) / "not_scored.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.is_file() else None


def build(contract: Path, by=DEFAULT_BY, minimum: int = hl.MIN_POINTS) -> dict:
    recs = graded_records(contract)
    ns = _not_scored(contract)
    return {"format": FORMAT, "min_role_keys": minimum, "points": len(recs),
            "role_keys": len({r["role_key"] for r in recs}),
            "meaning": (f"A slice over fewer than {minimum} role keys shows no accuracy, however many points it holds: "
                        "a role key is one deployment under one benchmark type, so ten concurrencies of one deployment "
                        "are one. Its points stay listed. It is left out of every verdict."),
            "unrecorded": list(UNRECORDED),
            "slices": {b: slice_by(recs, b, minimum, ns) for b in by}}


def validate(doc: dict) -> dict:
    """The rule, checked on a document already written: no accuracy under the minimum, none withheld above it."""
    if doc.get("format") != FORMAT:
        raise SliceError(f"slices document format {doc.get('format')!r}, expected {FORMAT}")
    minimum = doc["min_role_keys"]
    for by, rows in doc["slices"].items():
        for r in rows:
            where = f"{by}={r['value']}"
            if r["shown"] != (r["role_keys"] >= minimum):
                raise SliceError(f"{where}: {r['role_keys']} role keys, minimum {minimum}, but shown is {r['shown']}")
            if len(r["units"]) != r["points"]:
                raise SliceError(f"{where}: {r['points']} points but {len(r['units'])} units listed")
            for m in ("ttft", "tpot"):
                f = r[m]
                if (f["mape"] == TOO_FEW) != (f["role_keys"] < minimum):
                    raise SliceError(f"{where}: {m} is {f['mape']!r} over {f['role_keys']} role keys, minimum {minimum}")
    return doc


def _pct(f: dict) -> str:
    return f["mape"] if f["mape"] == TOO_FEW else f"{f['mape']:.1f}%"


def markdown(doc: dict) -> list[str]:
    L = ["## Accuracy by slice (design COV-13)", "", doc["meaning"], "",
         f"{doc['points']} graded points, {doc['role_keys']} role keys. Not recorded on a point yet, so not sliceable: "
         + ", ".join(doc["unrecorded"]) + ".", ""]
    for by, rows in doc["slices"].items():
        L += [f"### By {ATTRS[by][0]}", "", "| Slice | Points | Role keys | Coverage | TTFT error | TPOT error |",
              "|---|---|---|---|---|---|"]
        for r in rows:
            cov = "n/a" if r["coverage"] is None else f"{r['coverage']['scored']} of {r['coverage']['total']}"
            if r["shown"]:
                a, b = _pct(r["ttft"]), _pct(r["tpot"])
            else:
                a = b = f"{TOO_FEW} ({r['role_keys']} role keys)"
            L.append(f"| `{r['value']}` | {r['points']} | {r['role_keys']} | {cov} | {a} | {b} |")
        L.append("")
        small = [r for r in rows if not r["shown"]]
        if small:
            L += [f"Slices under {doc['min_role_keys']} role keys list their points:", ""]
            L += [f"- `{r['value']}`: " + ", ".join(f"`{u[:12]}`" for u in r["units"]) for r in small] + [""]
    return L


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--contract", required=True, type=Path, help="the scored contract directory")
    ap.add_argument("--by", action="append", help=f"an attribute to slice by, repeated (default {', '.join(DEFAULT_BY)})")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    try:
        doc = validate(build(a.contract, tuple(a.by) if a.by else DEFAULT_BY))
    except (SliceError, OSError, KeyError, ValueError) as e:
        print(f"slices: {e}", file=sys.stderr)
        return 2
    a.out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    print(f"wrote {a.out}: {doc['points']} points, {doc['role_keys']} role keys, {len(doc['slices'])} cuts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
