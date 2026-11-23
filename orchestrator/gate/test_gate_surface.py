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


# ---- the scoring surface hash ----

import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402

import gate  # noqa: E402
import surface  # noqa: E402

HEX = "a" * 40


def make_tree(root: Path, files: dict) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


TREE = {"harness/run.sh": "run\n", "orchestrator/ingest/score.py": "score\n", "orchestrator/ingest/test_score.py": "t\n",
        ".github/stack-pins.env": "SIM_REF=x\n", "docs/readme.md": "doc\n", "orchestrator/gate/gate.py": "g\n"}
PATHS = [".github/stack-pins.env", "harness/", "orchestrator/ingest/"]


def digest_of(tmp_path, files, name="t"):
    return surface.digest(make_tree(tmp_path / name, files), PATHS)


def test_the_hash_is_a_function_of_the_scoring_files_alone(tmp_path):
    base = digest_of(tmp_path, TREE, "a")
    assert len(base) == 64 and base == digest_of(tmp_path, dict(reversed(list(TREE.items()))), "b")
    for name, edit in {"docs": {"docs/readme.md": "changed\n"}, "a test": {"orchestrator/ingest/test_score.py": "other\n"},
                       "the pin": {".github/stack-pins.env": "SIM_REF=y\n"}, "the gate": {"orchestrator/gate/gate.py": "h\n"}}.items():
        assert digest_of(tmp_path, {**TREE, **edit}, "c") == base, name


@pytest.mark.parametrize("edit", [
    {"orchestrator/ingest/score.py": "scaled\n"}, {"harness/run.sh": "run --fabricate\n"},
    {"orchestrator/ingest/new_module.py": "x\n"}, {"harness/data/x.json": "{}\n"},
])
def test_a_change_to_a_scoring_file_changes_the_hash(tmp_path, edit):
    assert digest_of(tmp_path, {**TREE, **edit}, "c") != digest_of(tmp_path, TREE, "a")


def test_a_deleted_scoring_file_and_a_symlink_change_the_hash(tmp_path):
    base = digest_of(tmp_path, TREE, "a")
    assert digest_of(tmp_path, {k: v for k, v in TREE.items() if k != "harness/run.sh"}, "b") != base
    linked = make_tree(tmp_path / "c", TREE)
    os.symlink("/etc/passwd", linked / "harness" / "link")
    assert surface.digest(linked, PATHS) != base
    retargeted = make_tree(tmp_path / "e", TREE)
    os.symlink("/etc/hosts", retargeted / "harness" / "link")
    assert surface.digest(retargeted, PATHS) != surface.digest(linked, PATHS)
    other = make_tree(tmp_path / "d", TREE)
    os.symlink("/etc", other / "orchestrator" / "ingest" / "dirlink")
    assert surface.digest(other, PATHS) != base


def test_the_committed_tree_hashes_and_the_command_prints_it(tmp_path, capsys):
    assert gate.main(["surface-hash", "--paths-root", str(REPO), "--root", str(REPO)]) == 0
    out = capsys.readouterr().out.strip()
    assert out == surface.digest(REPO, rule.accuracy_paths(REPO))


def sides(tmp_path, cand_files, *, recorded=None, exception=None, number=7):
    paths_root = tmp_path / "main"
    (paths_root / "state" / "gate").mkdir(parents=True)
    (paths_root / rule.PATHS).write_text(json.dumps({"kind": "AccuracyPaths", "paths": PATHS}))
    if exception is not None:
        (paths_root / rule.EXCEPTIONS).write_text(json.dumps({"kind": "GateExceptions", "exceptions": [exception]}))
    base, cand = make_tree(tmp_path / "base", TREE), make_tree(tmp_path / "cand", {**TREE, **cand_files})
    art = {}
    for name, root in (("base", base), ("cand", cand)):
        art[name] = tmp_path / f"art-{name}"
        art[name].mkdir()
        (art[name] / "surface.sha256").write_text((recorded or {}).get(name, surface.digest(root, PATHS)) + "\n")
    return ["check-surface", "--root", str(paths_root), "--base-root", str(base), "--cand-root", str(cand),
            "--base-artifact", str(art["base"]), "--cand-artifact", str(art["cand"]),
            "--pull-request", str(number), "--head", HEX]


def test_equal_scoring_trees_proceed(tmp_path, capsys):
    assert gate.main(sides(tmp_path, {"docs/readme.md": "doc changed\n"})) == 0


def test_a_candidate_with_its_own_scoring_code_is_refused(tmp_path, capsys):
    assert gate.main(sides(tmp_path, {"orchestrator/ingest/score.py": "copy measured into pred\n"})) == 1
    assert "differs from main's" in capsys.readouterr().out


def test_a_maintainer_exception_for_this_pull_request_and_head_lets_a_differing_tree_proceed(tmp_path, capsys):
    exc = {"pull_request": 7, "head": HEX, "reason": "the harness fix is reviewed by hand"}
    change = {"orchestrator/ingest/score.py": "reviewed change\n"}
    assert gate.main(sides(tmp_path / "ok", change, exception=exc)) == 0
    assert gate.main(sides(tmp_path / "other-pr", change, exception={**exc, "pull_request": 8})) == 1
    assert gate.main(sides(tmp_path / "other-head", change, exception={**exc, "head": "b" * 40})) == 1


def test_a_run_that_records_another_hash_than_its_commit_has_is_refused(tmp_path, capsys):
    assert gate.main(sides(tmp_path, {}, recorded={"cand": "0" * 64})) == 1
    assert "records" in capsys.readouterr().out
