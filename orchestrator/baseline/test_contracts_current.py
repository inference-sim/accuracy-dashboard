"""A committed contract (a scoring run's results) was made by the scorer that is in this tree.

The contract names the harness commit that scored it (provenance.json `harness_commit`, which
harness/run.sh records as the commit of the checkout it ran from). The results are committed after
that commit, so the commit cannot be HEAD; what must hold is that nothing that scores changed in
between. A change to any scorer file means the contract describes another scorer's output, and the
run is made again (docs/m2/after-run.md).

The scorer files are derived, not listed by hand:
- the Python modules of the scoring entry point's import closure: orchestrator/ingest/cli.py, which
  harness/run.sh runs, and every module it imports, transitively, that resolves to a file under
  orchestrator/ or harness/ (imports are read statically, at the harness commit and at the head, and
  the two closures are joined, so a module that enters or leaves the closure counts either way);
- every other non-test file under harness/ and orchestrator/ (data the scorer reads, such as
  orchestrator/vllm_defaults.json, and harness/run.sh itself), schemas/ and requirements-ci.txt.
A Python file outside the closure, such as a scenario generator no contract reads, is not one.

CI checks the repository out in full (fetch-depth 0): the harness commit must be in the history.
"""
import ast
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract_currency  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
ENTRY = "orchestrator/ingest/cli.py"
SCORER_ROOTS = ("harness", "orchestrator", "schemas", "requirements-ci.txt")
# Directories a scorer module's bare `import x` resolves in: its own, and the two the entry point
# puts on sys.path (orchestrator/ingest and orchestrator).
IMPORT_DIRS = ("orchestrator/ingest", "orchestrator")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _is_test(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return "testdata" in parts or PurePosixPath(path).name.startswith("test_")


def import_closure(repo, rev: str) -> set[str]:
    """The .py files under orchestrator/ and harness/ that the entry point imports at `rev`,
    transitively, read statically with ast."""
    files = set(git(repo, "ls-tree", "-r", "--name-only", rev, "--", "orchestrator", "harness").stdout.split())
    if ENTRY not in files:
        return set()
    seen, todo = set(), [ENTRY]
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        tree = ast.parse(git(repo, "show", f"{rev}:{path}").stdout, filename=path)
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.add(node.module.split(".")[0])
        here = str(PurePosixPath(path).parent)
        for name in names:
            for d in (here, *IMPORT_DIRS):
                for cand in (f"{d}/{name}.py", f"{d}/{name}/__init__.py"):
                    if cand in files:
                        todo.append(cand)
                        break
                else:
                    continue
                break
    return seen


def scorer_files(repo, *revs: str) -> list[str]:
    """The scorer's files at any of `revs`: the import closure's modules, and every non-test,
    non-Python file under the scorer's roots."""
    out = set()
    for rev in revs:
        out |= import_closure(repo, rev)
        for f in git(repo, "ls-tree", "-r", "--name-only", rev, "--", *SCORER_ROOTS).stdout.split():
            if not f.endswith(".py") and not _is_test(f):
                out.add(f)
    return sorted(out)


def scorer_changes(repo, harness_commit: str, head: str = "HEAD") -> list[str]:
    """The scorer's files that differ between the harness commit and `head`; raises if the commit is
    not in the history."""
    if git(repo, "cat-file", "-e", f"{harness_commit}^{{commit}}").returncode != 0:
        raise AssertionError(f"harness commit {harness_commit} is not in this clone's history "
                             f"(check out with full history: fetch-depth 0)")
    files = scorer_files(repo, harness_commit, head)
    if not files:
        return []
    r = git(repo, "diff", "--name-only", harness_commit, head, "--", *files)
    assert r.returncode == 0, r.stderr
    return r.stdout.split()


def stale_contracts(repo, head: str = "HEAD") -> dict[str, list[str]]:
    """Each current contract (every committed one not listed as historical) whose scorer files changed between its
    harness commit and `head`, with the files that changed."""
    out = {}
    for c in contract_currency.current(Path(repo)):
        h = json.loads((Path(repo) / c / "provenance.json").read_text())["harness_commit"]
        changed = scorer_changes(repo, h, head)
        if changed:
            out[c] = changed
    return out


def test_there_are_committed_contracts_to_check():
    assert len(contract_currency.contracts(ROOT)) >= 2


def test_every_current_contract_was_made_by_the_scorer_at_head():
    stale = stale_contracts(ROOT)
    assert not stale, "; ".join(f"{c} was scored at another scorer, and these scoring files changed since: "
                                f"{changed[:8]}; score it again at the current scorer"
                                for c, changed in stale.items())


class Repo:
    """A scratch repository with the scorer's shape: cli.py imports score, which imports
    support; a generator nothing imports sits beside them."""

    def __init__(self, tmp_path):
        self.root = tmp_path
        git(tmp_path, "init", "-q")
        files = {
            "orchestrator/ingest/cli.py": "import json\nimport score\n",
            "orchestrator/ingest/score.py": "import support\n",
            "orchestrator/ingest/support.py": "X = 1\n",
            "orchestrator/ingest/helper.py": "Y = 1\n",
            "orchestrator/gen_scenarios.py": "import support\n",
            "orchestrator/vllm_defaults.json": "{}\n",
            "orchestrator/ingest/test_score.py": "import score\n",
            "orchestrator/ingest/testdata/x.json": "1\n",
            "harness/run.sh": "python3 orchestrator/ingest/cli.py\n",
            "schemas/s.json": "{}\n",
            "requirements-ci.txt": "x==1\n",
            "docs/a.md": "a\n",
        }
        for rel, body in files.items():
            self.write(rel, body)
        self.base = self.commit("scored")

    def write(self, rel, body):
        (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.root / rel).write_text(body)

    def commit(self, msg):
        git(self.root, "add", "-A")
        assert git(self.root, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                   "commit", "-qm", msg).returncode == 0
        return git(self.root, "rev-parse", "HEAD").stdout.strip()

    def changed_after(self, rel, body="# changed\n"):
        old = (self.root / rel).read_text()
        self.write(rel, old + body)
        changed = scorer_changes(self.root, self.base, self.commit(f"change {rel}"))
        self.write(rel, old)
        self.commit("restore")
        return changed


def test_a_file_inside_the_closure_that_changes_fails_the_gate(tmp_path):
    repo = Repo(tmp_path)
    for rel in ("orchestrator/ingest/cli.py", "orchestrator/ingest/score.py", "orchestrator/ingest/support.py",
                "orchestrator/vllm_defaults.json", "harness/run.sh", "schemas/s.json", "requirements-ci.txt"):
        assert rel in repo.changed_after(rel), rel


def test_a_file_outside_the_closure_does_not_fail_the_gate(tmp_path):
    """A generator no scoring module imports, a module nothing imports, tests, test data and docs."""
    repo = Repo(tmp_path)
    for rel in ("orchestrator/gen_scenarios.py", "orchestrator/ingest/helper.py", "orchestrator/ingest/test_score.py",
                "orchestrator/ingest/testdata/x.json", "docs/a.md"):
        assert repo.changed_after(rel) == [], rel


def test_a_new_import_brings_a_file_into_the_closure(tmp_path):
    repo = Repo(tmp_path)
    repo.write("orchestrator/ingest/score.py", "import support\nimport helper\n")
    head = repo.commit("score imports helper")
    assert "orchestrator/ingest/helper.py" in scorer_files(tmp_path, head)
    assert "orchestrator/ingest/helper.py" not in scorer_files(tmp_path, repo.base)
    repo.base = head
    assert "orchestrator/ingest/helper.py" in repo.changed_after("orchestrator/ingest/helper.py")


def test_a_harness_commit_outside_the_history_is_refused(tmp_path):
    repo = Repo(tmp_path)
    try:
        scorer_changes(repo.root, "0" * 40)
        raise SystemExit("a harness commit outside the history must raise")
    except AssertionError as e:
        assert "not in this clone" in str(e)


def test_the_real_entry_points_closure_holds_the_scorer_and_not_the_generators():
    files = scorer_files(ROOT, "HEAD")
    # cli.py imports build_summary_v2, and resolve_agentic_corpus imports constants from
    # extract_agentic_replay_args, so both are scorer modules; the hand list once left the
    # first out.
    for rel in ("orchestrator/ingest/cli.py", "orchestrator/ingest/score.py", "orchestrator/ingest/support.py",
                "orchestrator/build_summary_v2.py", "orchestrator/extract_agentic_replay_args.py",
                "harness/run.sh", "orchestrator/vllm_defaults.json"):
        assert rel in files, rel
    for rel in ("orchestrator/gen_scenarios.py", "orchestrator/run_agentic.py", "orchestrator/lint_blis_boundary.py"):
        assert rel not in files, rel


def test_moving_an_upstream_pin_does_not_make_a_contract_stale(tmp_path):
    """The upstream builds (inference-sim, blis-substrate, the router fork) are pinned in .github/stack-pins.env, which
    is not a scorer file: replacing a commit by the release tag at that content is a pin-only change."""
    pins = ".github/stack-pins.env"
    listed = scorer_files(ROOT, "HEAD")
    assert (ROOT / pins).is_file() and pins not in listed
    assert not [f for f in listed if f.startswith("harness/") and "SIM_" in (ROOT / f).read_text()], "a simulator pin in a scorer file"
    repo = Repo(tmp_path)
    repo.write(pins, "SIM_REF=" + "a" * 40 + "\n")
    repo.base = repo.commit("scored")
    assert repo.changed_after(pins) == []
