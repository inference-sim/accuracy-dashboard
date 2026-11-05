"""Tests for lint_blis_boundary.py (X7): each rule fires on a repository that breaks it, and the
dashboard's own tree passes.

Run: python3 -m pytest orchestrator/test_lint_blis_boundary.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lint_blis_boundary as lint  # noqa: E402


def repo(tmp: Path, files: dict) -> Path:
    for rel, text in files.items():
        (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp / rel).write_text(text)
    subprocess.run(["git", "-C", str(tmp), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(tmp), "add", "-A"], check=True)
    return tmp


@pytest.fixture
def no_sites(monkeypatch):
    monkeypatch.setattr(lint, "GO_IMPORTS", {})
    monkeypatch.setattr(lint, "DATA_READS", {})


def test_the_dashboards_tree_passes():
    assert lint.check(HERE.parent) == []


def test_a_go_mod_naming_a_blis_module_is_refused(tmp_path, no_sites):
    r = repo(tmp_path, {"tools/go.mod": "module x\n\nrequire github.com/inference-sim/blis-substrate v0.1.0\n"})
    assert lint.check(r) == ["tools/go.mod:3: names the BLIS module github.com/inference-sim/blis-substrate; "
                             "the dashboard imports no BLIS module (X7)"]


@pytest.mark.parametrize("line", [
    'import "github.com/inference-sim/blis-vllm"',
    '\t"github.com/inference-sim/blis-substrate/contracts/metrics"',
    '\tm "github.com/inference-sim/blis-substrate/contracts/metrics"',
])
def test_a_go_import_of_a_blis_module_is_refused(tmp_path, no_sites, line):
    r = repo(tmp_path, {"probe/main.go": f"package main\n\nimport (\n{line}\n)\n"
                        if not line.startswith("import") else f"package main\n\n{line}\n"})
    problems = lint.check(r)
    assert len(problems) == 1 and problems[0].startswith("probe/main.go:") and "Go import of a BLIS module" in problems[0]


@pytest.mark.parametrize("code,seg", [
    ('from pathlib import Path\ndef f(root):\n    return (root / "models").iterdir()\n', "models"),
    ('from pathlib import Path\ndef f(r):\n    return Path(r, "coefficients").glob("*.yaml")\n', "coefficients"),
    ('def f(d):\n    return d / "units/inferencex.jsonl.gz"\n', "units"),
    ('def f(c):\n    return c / "hardware" / "h200.yaml"\n', "hardware"),
])
def test_python_that_reads_a_blis_data_checkout_is_refused(tmp_path, no_sites, code, seg):
    r = repo(tmp_path, {"orchestrator/x.py": code})
    problems = lint.check(r)
    assert len(problems) == 1 and problems[0].startswith("orchestrator/x.py:") and f"f builds a path into a BLIS " \
        f"data checkout ({seg!r})" in problems[0]


def test_a_listed_site_passes_and_tests_are_not_linted(tmp_path, monkeypatch):
    monkeypatch.setattr(lint, "GO_IMPORTS", {})
    monkeypatch.setattr(lint, "DATA_READS", {("x.py", "Cat.graph"): "TEMPORARY until a command prints it"})
    r = repo(tmp_path, {"x.py": 'class Cat:\n    def graph(self, root):\n        return root / "models"\n',
                        "test_x.py": 'def test_f(tmp):\n    (tmp / "models").mkdir()\n'})
    assert lint.check(r) == []


def test_a_listed_site_that_no_longer_reads_must_be_removed_from_the_list(tmp_path, monkeypatch):
    monkeypatch.setattr(lint, "GO_IMPORTS", {"gone.py": "TEMPORARY"})
    monkeypatch.setattr(lint, "DATA_READS", {("x.py", "f"): "TEMPORARY"})
    r = repo(tmp_path, {"x.py": "def f():\n    return 1\n", "gone.py": "\n"})
    assert lint.check(r) == [
        "GO_IMPORTS lists gone.py, which holds no Go import of a BLIS module: remove the entry",
        "DATA_READS lists x.py f, which builds no path into a BLIS data checkout: remove the entry"]


def test_every_listed_site_names_what_it_waits_for():
    for why in [*lint.GO_IMPORTS.values(), *lint.DATA_READS.values()]:
        assert why.startswith("TEMPORARY "), why
