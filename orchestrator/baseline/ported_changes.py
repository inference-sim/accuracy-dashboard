#!/usr/bin/env python3
"""Which upstream functions the vLLM engine ports changed between a run's release and the release BLIS runs.

This is evidence for a point's grade ceiling (ceiling.py), not a grade. Design §11.3 grades a point measured
on another release G3 only when the engine publishes the list of upstream functions it ports and none of them
changed between the two releases. blis-vllm publishes no such list yet, so no point is G3, and grade.py says
so (`ported_functions_unpublished`). What can be said from data is narrower and one-sided: when a function the
port says it ports differs between the run's release and the engine release, G3 cannot be reached for any
point of that release, however long the list grows. When no cited function differs, nothing is proved, and
the ceiling stays G3 (not yet reached: the list is unpublished).

Where the cited functions come from. Each ported Go file of blis-vllm starts with a provenance header
(blis-vllm NOTICE): "Derived from vllm/<path> at vLLM <tag> (<commit>)", often followed by the upstream
functions it translates with their line ranges at that commit, e.g. "_get_kv_cache_bytes_per_block
(:1521-1553)" or "(vllm/v1/kv_cache_interface.py:1282-1295)". This script reads every such range, finds the
innermost function or method of the upstream file at the engine release that holds the range's first line,
and compares that function's syntax tree (ast.dump without positions, so a reformatting or a move within the
file is not a change) at each run release. A function missing at a release counts as changed.

    ported_changes.py gen   --port BLIS_VLLM [--port-commit C] --vllm VLLM_CHECKOUT --release 0.21.0 [--release ...] --out FILE
    ported_changes.py check --port BLIS_VLLM --vllm VLLM_CHECKOUT FILE

--port-commit is the blis-vllm commit whose headers are read (default HEAD); use the one the scoring simulator's
stack names.

`check` regenerates the file from the same checkouts and fails if it differs. Both checkouts are read with
git only (`git show <commit>:<path>`), so neither working tree needs to be clean or at the commit.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

FORMAT = "ported-changes-1"
_DERIVED = re.compile(r"^// Derived from (vllm/\S+\.py) at vLLM (v\d+\.\d+\.\d+) \(([0-9a-f]{40})\)")
# A range in a header: "(vllm/x/y.py:12-34)", "x.py:12-34", "(:12-34)", or a bare "12-34" that continues a list.
_RANGE = re.compile(r"(?:(vllm/[\w/]+\.py)|([\w/]+\.py))?:\s?(\d+)-(\d+)|(?:(?<=, )|(?<=and ))(\d+)-(\d+)")


class PortedError(ValueError):
    pass


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise PortedError(f"git {' '.join(args)} in {repo}: {r.stderr.strip()}")
    return r.stdout


def header(text: str) -> list[str]:
    """The comment lines before `package`."""
    out = []
    for line in text.splitlines():
        if line.startswith("package "):
            break
        if line.startswith("//"):
            out.append(line)
    return out


def cited_ranges(text: str) -> tuple[tuple[str, str, str] | None, list[tuple[str, int, int]]]:
    """The file's provenance (path, tag, commit) and every (upstream path, first, last) line range its header
    cites. A range with no path is in the last path the header named before it (at first, the header's own file).
    A short file name is read as the header's own file only when it is that file's name; any other short name
    (a sibling, "nvidia/model.py") is ambiguous, and its ranges are skipped until the header names a full path."""
    lines = header(text)
    prov = None
    for line in lines:
        m = _DERIVED.match(line)
        if m:
            prov = (m.group(1), m.group(2), m.group(3))
            break
    if prov is None:
        return None, []
    base = prov[0]
    current = base
    ranges = []
    body = " ".join(x[2:].strip() for x in lines)
    for m in _RANGE.finditer(body):
        full, short, a, b, ca, cb = m.groups()
        if full:
            current = full
        elif short:
            current = base if short == Path(base).name else None
        if current is None:
            continue
        first, last = (int(a), int(b)) if a is not None else (int(ca), int(cb))
        ranges.append((current, first, last))
    return prov, ranges


def functions(source: str) -> dict[str, tuple[int, int, str]]:
    """Every function and method of a Python file: qualified name to (first line, last line, normalised tree)."""
    tree = ast.parse(source)
    out = {}

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                if not isinstance(child, ast.ClassDef):
                    out[name] = (child.lineno, child.end_lineno, ast.dump(child, include_attributes=False))
                walk(child, name + ".")
    walk(tree, "")
    return out


def innermost(funcs: dict, line: int) -> str | None:
    """The innermost function holding `line`, or None when the line is outside every function."""
    holding = [(e - s, n) for n, (s, e, _) in funcs.items() if s <= line <= e]
    return min(holding)[1] if holding else None


def port_files(port: Path, commit: str) -> list[str]:
    names = git(port, "ls-tree", "-r", "--name-only", commit).split()
    return sorted(n for n in names if n.endswith(".go") and not n.endswith("_test.go"))


def cited_functions(port: Path, port_commit: str, vllm: Path) -> tuple[str, str, list[dict]]:
    """The engine release (tag, commit) the port derives from and every upstream function its headers cite."""
    cited, release = {}, None
    sources = {}
    for f in port_files(port, port_commit):
        text = git(port, "show", f"{port_commit}:{f}")
        prov, ranges = cited_ranges(text)
        if prov is None:
            continue
        if release is None:
            release = prov[1:]
        elif release != prov[1:]:
            raise PortedError(f"{f} derives from vLLM {prov[1]} ({prov[2]}), another file from {release[0]} ({release[1]})")
        for path, first, _last in ranges:
            if path not in sources:
                try:
                    sources[path] = functions(git(vllm, "show", f"{release[1]}:{path}"))
                except (PortedError, SyntaxError):
                    sources[path] = None
            funcs = sources[path]
            name = innermost(funcs, first) if funcs else None
            if name is None:
                continue
            cited.setdefault((path, name), set()).add(f)
    if release is None:
        raise PortedError(f"no file of {port} at {port_commit} states a vLLM provenance header")
    return release[0], release[1], [{"file": p, "function": n, "cited_by": sorted(by)}
                                    for (p, n), by in sorted(cited.items())]


def generate(port: Path, vllm: Path, releases: list[str], port_commit: str = "HEAD") -> dict:
    port_commit = git(port, "rev-parse", f"{port_commit}^{{commit}}").strip()
    tag, commit, cited = cited_functions(port, port_commit, vllm)
    base = {}
    for c in cited:
        if c["file"] not in base:
            base[c["file"]] = functions(git(vllm, "show", f"{commit}:{c['file']}"))
    out = {}
    for rel in sorted(set(releases), key=lambda v: tuple(int(x) for x in v.split("."))):
        rcommit = git(vllm, "rev-parse", f"v{rel}^{{commit}}").strip()
        here, changed, unchanged = {}, [], []
        for c in cited:
            if c["file"] not in here:
                try:
                    here[c["file"]] = functions(git(vllm, "show", f"{rcommit}:{c['file']}"))
                except (PortedError, SyntaxError):
                    here[c["file"]] = {}
            now = here[c["file"]].get(c["function"])
            key = f"{c['file']}:{c['function']}"
            (unchanged if now is not None and now[2] == base[c["file"]][c["function"]][2] else changed).append(key)
        out[rel] = {"commit": rcommit, "changed": changed, "unchanged": unchanged}
    return {"format": FORMAT,
            "about": ("For each run release, the upstream functions blis-vllm's provenance headers cite that differ "
                      "(changed) or not (unchanged) from the engine release. Evidence for grade ceilings: a release "
                      "with a changed function cannot reach G3. Generated by orchestrator/baseline/ported_changes.py."),
            "engine_release": tag.lstrip("v"), "engine_commit": commit,
            "port": {"repository": "inference-sim/blis-vllm", "commit": port_commit},
            "cited": cited, "releases": out}


def changed_functions(doc: dict | None, release: str | None) -> list[str] | None:
    """The cited functions that changed between `release` and the engine release; None when the document
    holds no comparison for that release."""
    if not doc or release is None:
        return None
    e = (doc.get("releases") or {}).get(release)
    return None if e is None else list(e["changed"])


def dumps(doc: dict) -> str:
    return json.dumps(doc, indent=1, sort_keys=True) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen")
    g.add_argument("--port", required=True, type=Path)
    g.add_argument("--port-commit", default="HEAD")
    g.add_argument("--vllm", required=True, type=Path)
    g.add_argument("--release", action="append", required=True)
    g.add_argument("--out", required=True, type=Path)
    c = sub.add_parser("check")
    c.add_argument("--port", required=True, type=Path)
    c.add_argument("--vllm", required=True, type=Path)
    c.add_argument("file", type=Path)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "gen":
            doc = generate(a.port, a.vllm, a.release, a.port_commit)
            a.out.write_text(dumps(doc))
            for rel, e in doc["releases"].items():
                print(f"{rel}: {len(e['changed'])} of {len(doc['cited'])} cited functions changed")
            return 0
        stored = json.loads(a.file.read_text())
        fresh = generate(a.port, a.vllm, list(stored["releases"]), stored["port"]["commit"])
        if dumps(fresh) != dumps(stored):
            print(f"{a.file} is not what ported_changes.py generates from these checkouts", file=sys.stderr)
            return 1
        print(f"{a.file} is current")
        return 0
    except PortedError as e:
        print(f"ported_changes: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
