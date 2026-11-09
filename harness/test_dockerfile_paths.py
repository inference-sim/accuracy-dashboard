"""The image holds exactly what its COPY lines put there (harness/Dockerfile). These tests check
that every repository path the scorer reads at run time is among them, and that the scorer runs
from a tree holding nothing else.

Scorer code finds its data files from its own location: `Path(__file__).resolve().parent...`
joined with string literals (contract.py reads schemas/fidelity.v3.json, for example). A file the
Dockerfile does not copy is therefore absent in the image, and the first read fails there, never
in CI, which runs from a full checkout. The first test finds every such path by reading the
scorer's source; the second runs run.sh's real path from a tree built from the COPY lines alone.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import test_run_sh as rs

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DOCKERFILE = HERE / "Dockerfile"
IMAGE_ROOT = "/harness"


def copies() -> list[tuple[str, str]]:
    """The (source, destination) pair of every COPY line, the source relative to the repository."""
    pairs = []
    for line in DOCKERFILE.read_text().splitlines():
        m = re.fullmatch(r"COPY\s+(\S+)\s+(\S+)", line.strip())
        if m:
            pairs.append((m.group(1), m.group(2)))
    return pairs


def covered(rel: str, sources: list[str]) -> bool:
    return any(rel == s or rel.startswith(s.rstrip("/") + "/") for s in sources)


def run_time_paths() -> dict[str, set[str]]:
    """Every path inside the repository that a non-test module under orchestrator/ builds from
    its own location, as repository-relative paths, mapped to the modules that build it."""
    found: dict[str, set[str]] = {}
    for py in sorted((REPO / "orchestrator").rglob("*.py")):
        if py.name.startswith("test_"):
            continue
        tree = ast.parse(py.read_text())
        env: dict[str, object] = {}

        def ev(node):
            """The value of a path expression: strings, Path(__file__), .resolve(), .parent and
            `/` joins, with module-level names already bound. Anything else is not a path."""
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return node.value
            if isinstance(node, ast.Name):
                return env[node.id]
            if isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Name) and f.id == "Path" and len(node.args) == 1:
                    arg = node.args[0]
                    if isinstance(arg, ast.Name) and arg.id == "__file__":
                        return py
                    return Path(ev(arg))
                if isinstance(f, ast.Attribute) and f.attr == "resolve" and not node.args:
                    return ev(f.value).resolve()
            if isinstance(node, ast.Attribute) and node.attr == "parent":
                return ev(node.value).parent
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                return ev(node.left) / ev(node.right)
            raise KeyError(ast.dump(node))

        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if targets and isinstance(node, ast.Assign):
                try:
                    for t in targets:
                        env[t] = ev(node.value)
                except (KeyError, AttributeError, TypeError):
                    pass
        joins = [n for n in ast.walk(tree) if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)]
        inner = {id(c) for n in joins for c in ast.walk(n) if c is not n}
        for n in joins:
            if id(n) in inner:
                continue
            try:
                p = ev(n)
            except (KeyError, AttributeError, TypeError):
                continue
            if isinstance(p, Path) and REPO in p.parents:
                found.setdefault(str(p.relative_to(REPO)), set()).add(str(py.relative_to(REPO)))
    return found


def test_every_copy_lands_at_its_repository_path_under_the_image_root():
    # The scorer finds its files from its own location, so a copy must keep the repository layout.
    layout = [(s, d) for s, d in copies() if s not in ("harness/requirements.txt",)]
    assert layout
    for src, dest in layout:
        assert dest == f"{IMAGE_ROOT}/{src}", f"COPY {src} {dest}"


def test_every_path_the_scorer_reads_at_run_time_is_copied_into_the_image():
    sources = [s for s, _ in copies()]
    paths = run_time_paths()
    # The scan must find the files known to be read, or it would pass by finding nothing.
    for known in ("schemas/fidelity.v3.json", "schemas/summary.v3.json", "orchestrator/vllm_defaults.json",
                  "orchestrator/ingest/testdata/inferencex-workloads/seed0.json",
                  "orchestrator/ingest/inferencex/vllm-dp-lb.epp.yaml"):
        assert known in paths, f"the scan missed {known}: {sorted(paths)}"
    missing = {p: sorted(who) for p, who in paths.items() if not covered(p, sources)}
    assert not missing, f"read at run time but not copied by harness/Dockerfile: {missing}"


def image_tree(dest: Path) -> Path:
    """The files the Dockerfile copies, and only those, laid out as in the image."""
    for src, to in copies():
        target = dest / to.lstrip("/")
        if (REPO / src).is_dir():
            shutil.copytree(REPO / src, target, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / src, target)
    return dest / IMAGE_ROOT.lstrip("/")


def test_the_scorer_finishes_a_run_from_a_tree_holding_only_the_copied_paths(tmp_path):
    root = image_tree(tmp_path / "image")
    run_sh = root / "harness" / "run.sh"
    assert run_sh.is_file()
    work = tmp_path / "work"
    work.mkdir()
    bare, commit, bin_, log, pull, units, fields, cat, reg = rs.real_setup(work)
    out = work / "out"
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "HARNESS_DIGEST": "sha256:" + "b" * 64,
           "FAKE_FIELDS": str(fields)}
    p = subprocess.run(["bash", str(run_sh), "--sim", "v0.16.0", "--sim-repo", str(bare), "--units", str(units),
                        "--pull", str(pull), "--out", str(out), "--catalog", str(cat), "--registry", str(reg),
                        "--corpus-dir", str(work / "corpora"), "--fields", str(fields),
                        "--catalog-release", "v0.3.0", "--registry-release", "v0.2.0"], capture_output=True, text=True, env=env, cwd=root)
    assert p.returncode == 0, p.stderr
    assert json.loads((out / "provenance.json").read_text())["simulator"]["build"] == "v0.16.0"
