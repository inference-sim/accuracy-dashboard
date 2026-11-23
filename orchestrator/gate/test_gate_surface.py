"""The accuracy paths cover everything the candidate run executes or reads, and the scoring surface hash
(gate.py surface-hash) that gate-candidate records is a function of those paths alone.

Run: python3 -m pytest orchestrator/gate/test_gate_surface.py
"""
import ast
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rule  # noqa: E402

REPO = HERE.parent.parent
IMPORT_DIRS = ("orchestrator/ingest", "orchestrator")
DATA_ROOTS = ("harness", "schemas", "orchestrator/ingest", "orchestrator/baseline")


def tracked() -> set[str]:
    out = subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True, check=True).stdout
    return set(out.split())


def entries() -> set[str]:
    """The scripts gate-candidate runs from the candidate's checkout, and the scorer harness/run.sh starts."""
    wf = (REPO / ".github/workflows/gate-candidate.yml").read_text()
    found = {m for m in re.findall(r"\brepo/((?:orchestrator|harness)/[\w/.-]+)", wf)}
    run_sh = (REPO / "harness/run.sh").read_text()
    found |= set(re.findall(r'\$root/(orchestrator/[\w/.-]+\.py)', run_sh))
    return found


def closure(files: set[str]) -> set[str]:
    seen, todo = set(), [e for e in entries() if e.endswith(".py")]
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        names = set()
        for node in ast.walk(ast.parse((REPO / path).read_text(), filename=path)):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.add(node.module.split(".")[0])
        for name in names:
            for d in (str(PurePosixPath(path).parent), *IMPORT_DIRS):
                hit = [c for c in (f"{d}/{name}.py", f"{d}/{name}/__init__.py") if c in files]
                if hit:
                    todo.append(hit[0])
                    break
    return seen


def executed_or_read() -> set[str]:
    files = tracked()
    out = closure(files) | {e for e in entries() if e in files}
    out |= {f for f in files if not f.endswith(".py") and not rule.is_test(f)
            and (any(f.startswith(r + "/") for r in DATA_ROOTS) or PurePosixPath(f).parent == PurePosixPath("orchestrator"))}
    return out


def test_the_entry_points_are_found():
    assert {"orchestrator/ingest/cli.py", "orchestrator/baseline/freeze.py", "orchestrator/resolve_agentic_corpus.py",
            "harness/run.sh"} <= entries()


def test_every_file_the_candidate_run_executes_or_reads_is_an_accuracy_path():
    paths = rule.accuracy_paths(REPO)
    uncovered = sorted(f for f in executed_or_read() if not rule.touches(f, paths))
    assert not uncovered, "scoring files outside state/gate/accuracy-paths.json: " + ", ".join(uncovered)


def test_the_gate_workflows_and_the_simulator_pin_are_accuracy_paths():
    paths = rule.accuracy_paths(REPO)
    for f in (".github/stack-pins.env", ".github/workflows/gate-candidate.yml", ".github/workflows/gate-rule.yml",
              ".github/workflows/whole-run-gate.yml"):
        assert rule.touches(f, paths), f


def test_no_scoring_module_is_a_test_file():
    assert not [f for f in closure(tracked()) if rule.is_test(f)]
