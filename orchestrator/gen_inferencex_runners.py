#!/usr/bin/env python3
"""Write orchestrator/ingest/inferencex_runners.json: the GPUs per node of InferenceX's
clusters, read from InferenceX's runners.yaml, for each hardware label the harness knows.

    python3 orchestrator/gen_inferencex_runners.py --ix /path/to/InferenceX \\
        --version 303669b0:configs/runners.yaml --version e9fc9880:configs/runners.yaml \\
        --version 5d06e10c:inferencex-e2e/configs/runners.yaml \\
        --version 4a63bf50:inferencex-e2e/configs/runners.yaml
    python3 orchestrator/gen_inferencex_runners.py ... --check

Each --version is `<commit>:<path of runners.yaml at that commit>`, oldest first. InferenceX
defines `gpus-per-node` per cluster and lists, under `labels:`, the runners of each hardware
label and the runners of each cluster (`cluster:<id>`). A hardware label maps to a cluster
through its runners. A version that holds no `gpus-per-node` line (the file before node sizes
were recorded, or only moved) is listed with records_node_sizes false and contributes no record.

A label has no single size in a version when it is absent, when a runner of the label belongs
to no cluster, when a cluster records no size, or when its clusters differ in size.

STABILITY CHECK, printed always and verified by --check: for every label, the size is the
same in every version that records node sizes (the clusters it maps to may differ). A label for which
that fails is `stable: false`, and the scorer does not use it for a row dated before the
label's first record (inferencex_runners.resolve).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "ingest"))

import inferencex_runners as ir  # noqa: E402

OUT = Path(__file__).resolve().parent / "ingest" / "inferencex_runners.json"
REPOSITORY = "https://github.com/SemiAnalysisAI/InferenceX"

# The hardware labels InferenceX rows carry: the `hardware` of the units the harness scores
# (orchestrator/run_agentic.py, orchestrator/ingest/testdata/logs). rtx6000pro and vr200 have no
# runner label in any version, so they stay without a size.
LABELS = ("h100", "h200", "b200", "b300", "gb200", "gb300", "mi300x", "mi325x", "mi355x", "rtx6000pro", "vr200")


class GenError(ValueError):
    pass


def _git(ix: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(ix), *args], capture_output=True, text=True)
    if p.returncode != 0:
        raise GenError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout


def _size_lines(text: str, section: str, cluster_key: str) -> int | None:
    """The 1-based line of `gpus-per-node:` inside the cluster's block, or None."""
    lines = text.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if l == f"{section}:")
    except StopIteration:
        return None
    key = f"  {cluster_key}:"
    for i in range(start + 1, len(lines)):
        if lines[i] and not lines[i].startswith(" "):
            return None
        if lines[i] == key:
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("  ") and not lines[j].startswith("   "):
                    return None
                if re.match(r"^    gpus-per-node:\s", lines[j]):
                    return j + 1
            return None
    return None


def read_version(ix: Path, spec: str) -> tuple[ir.Version, dict]:
    """The version and, when it records node sizes, {"labels": ..., "sizes": {cluster id:
    (gpus_per_node, file:line)}} from one `<commit>:<path>`; None for a version that records none."""
    import yaml
    commit, sep, path = spec.partition(":")
    if not sep or not commit or not path:
        raise GenError(f"--version {spec!r}: expected <commit>:<path>")
    full = _git(ix, "rev-parse", "--verify", f"{commit}^{{commit}}").strip()
    day = _git(ix, "show", "-s", "--format=%cs", full).strip()
    text = _git(ix, "show", f"{full}:{path}")
    doc = yaml.safe_load(text)
    if not isinstance(doc, dict):
        raise GenError(f"{commit}:{path}: not a mapping")
    if "gpus-per-node" not in text:
        # The layout before node sizes were recorded: runner lists only.
        return ir.Version(full, day, path, False), None
    if not isinstance(doc.get("labels"), dict):
        raise GenError(f"{commit}:{path}: records gpus-per-node but has no `labels:` mapping")
    if "clusters" in doc:
        section, clusters = "clusters", doc["clusters"]
        key = lambda cid: cid
    elif "hardware" in doc:
        section, clusters = "hardware", {k.split(":", 1)[1]: v for k, v in doc["hardware"].items()}
        key = lambda cid: f"cluster:{cid}"
    else:
        section, clusters, key = None, {}, None
    sizes = {}
    for cid, c in clusters.items():
        n = c.get("gpus-per-node") if isinstance(c, dict) else None
        if n is None:
            sizes[cid] = (None, None)
            continue
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise GenError(f"{commit}:{path}: cluster {cid}: gpus-per-node {n!r} is not a positive integer")
        line = _size_lines(text, section, key(cid))
        if line is None:
            raise GenError(f"{commit}:{path}: cannot find the gpus-per-node line of cluster {cid}")
        sizes[cid] = (n, f"{path}:{line}")
    v = ir.Version(full, day, path, any(n is not None for n, _ in sizes.values()))
    return v, {"labels": doc["labels"], "sizes": sizes}


def record(parts: dict, label: str) -> ir.Record:
    labels, sizes = parts["labels"], parts["sizes"]
    runners = labels.get(label)
    if not runners:
        return ir.Record(None, "label not in runners.yaml", ())
    owner = {}
    for name, rs in labels.items():
        if name.startswith("cluster:"):
            for r in rs:
                owner.setdefault(r, []).append(name[len("cluster:"):])
    free = [r for r in runners if r not in owner]
    ids = sorted({c for r in runners for c in owner.get(r, [])})
    clusters = tuple(ir.Cluster(c, *sizes.get(c, (None, None))) for c in ids)
    if free:
        return ir.Record(None, f"{len(free)} runners belong to no cluster (first: {free[0]})", clusters)
    nosize = [c.id for c in clusters if c.gpus_per_node is None]
    if nosize:
        return ir.Record(None, f"cluster {nosize[0]} records no gpus-per-node", clusters)
    distinct = sorted({c.gpus_per_node for c in clusters})
    if len(distinct) > 1:
        return ir.Record(None, f"clusters differ in size ({', '.join(f'{c.id} {c.gpus_per_node}' for c in clusters)})", clusters)
    return ir.Record(distinct[0], None, clusters)


def generate(ix: Path, specs: list[str], labels=LABELS) -> dict:
    read = [read_version(ix, s) for s in specs]
    versions = [v for v, _ in read]
    recording = [(v, p) for v, p in read if v.records_node_sizes]
    if not recording:
        raise GenError("no --version records any gpus-per-node")
    out = {"inferencex": {"repository": REPOSITORY},
           "versions": [{"commit": v.commit, "date": v.date, "path": v.path,
                         "records_node_sizes": v.records_node_sizes} for v in versions],
           "labels": {}}
    for label in labels:
        recs = {v.commit: record(p, label) for v, p in recording}
        stable, problems, first = ir.stability(versions, recs)
        out["labels"][label] = {
            "stable": stable, "problems": problems,
            "first_recorded": None if first is None else {"commit": first.commit, "date": first.date},
            "records": {c: {"gpus_per_node": r.gpus_per_node, "problem": r.problem,
                            "clusters": [{"id": k.id, "gpus_per_node": k.gpus_per_node, "source": k.source}
                                         for k in r.clusters]} for c, r in recs.items()}}
    ir.parse(out)     # the table must satisfy the loader that reads it
    return out


def render(doc: dict) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def stability_report(doc: dict) -> str:
    lines = ["STABILITY CHECK (a label is stable when its size is the same in every version that records sizes)"]
    for label, d in doc["labels"].items():
        per = ", ".join(f"{c[:8]}: " + (f"{r['gpus_per_node']} on {','.join(k['id'] for k in r['clusters'])}"
                                         if r["gpus_per_node"] is not None else f"none ({r['problem']})")
                        for c, r in d["records"].items())
        first = d["first_recorded"]
        lines.append(f"  {label:<11}{'stable' if d['stable'] else 'UNSTABLE':<9}first {first['commit'][:8] + ' ' + first['date'] if first else '-':<20}{per}")
        for p in d["problems"]:
            lines.append(f"{'':<13}problem: {p}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ix", required=True, type=Path, help="an InferenceX checkout with full history")
    ap.add_argument("--version", action="append", required=True, metavar="COMMIT:PATH")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--check", action="store_true", help="fail if the committed file differs from the regenerated one")
    a = ap.parse_args(argv)
    try:
        doc = generate(a.ix, a.version)
    except (GenError, ir.TableError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(stability_report(doc))
    text = render(doc)
    if a.check:
        if not a.out.is_file() or a.out.read_text() != text:
            print(f"error: {a.out} differs from the file regenerated from {a.ix}", file=sys.stderr)
            return 1
        print(f"{a.out} matches")
        return 0
    a.out.write_text(text)
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
