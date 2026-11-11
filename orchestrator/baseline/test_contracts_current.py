"""A committed contract (a scoring run's results) was made by the scorer that is in this tree.

The contract names the harness commit that scored it (provenance.json `harness_commit`, which
harness/run.sh records as the commit of the checkout it ran from). The results are committed after
that commit, so the commit cannot be HEAD; what must hold is that nothing that scores changed in
between. The files that score are harness/, schemas/, requirements-ci.txt and every non-test file
under orchestrator/ except orchestrator/baseline/ and the boundary lint (the table, split and residual tools read a
contract; none writes one). A change to any of them means the contract describes another scorer's output,
and the run is made again (docs/m2/after-run.md).

CI checks the repository out in full (fetch-depth 0): the harness commit must be in the history.
"""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCORER_PATHS = ["harness", "orchestrator", "schemas", "requirements-ci.txt"]
NOT_THE_SCORER = [":(exclude,glob)orchestrator/**/test_*.py", ":(exclude,glob)orchestrator/**/testdata/**",
                  ":(exclude,glob)orchestrator/**/test_*", ":(exclude,glob)harness/test_*", ":(exclude)orchestrator/baseline",
                  ":(exclude)orchestrator/lint_blis_boundary.py"]  # a lint of the source tree; it writes no contract


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def scorer_changes(repo, harness_commit: str, head: str = "HEAD") -> list[str]:
    """The scorer's files that differ between the harness commit and `head`; raises if the commit is
    not in the history."""
    if git(repo, "cat-file", "-e", f"{harness_commit}^{{commit}}").returncode != 0:
        raise AssertionError(f"harness commit {harness_commit} is not in this clone's history "
                             f"(check out with full history: fetch-depth 0)")
    r = git(repo, "diff", "--name-only", harness_commit, head, "--", *SCORER_PATHS, *NOT_THE_SCORER)
    assert r.returncode == 0, r.stderr
    return r.stdout.split()


def contracts():
    return sorted((ROOT / "docs" / "m2").glob("*/contract/provenance.json"))


def test_there_are_committed_contracts_to_check():
    assert len(contracts()) >= 2


def test_every_committed_contract_was_made_by_the_scorer_at_head():
    for path in contracts():
        h = json.loads(path.read_text())["harness_commit"]
        changed = scorer_changes(ROOT, h)
        assert not changed, (f"{path.relative_to(ROOT)} was scored at {h}, and these scoring files changed "
                             f"since: {changed[:8]}; score the run again at the current scorer")


def test_the_check_sees_a_changed_scorer_file_and_ignores_tests_and_docs(tmp_path):
    def commit(msg):
        git(tmp_path, "add", "-A")
        assert git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                   "commit", "-qm", msg).returncode == 0
        return git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    git(tmp_path, "init", "-q")
    for rel in ("orchestrator/ingest/score.py", "orchestrator/ingest/test_score.py", "docs/a.md", "schemas/s.json",
                "orchestrator/baseline/compare.py",
                "harness/run.sh", "orchestrator/ingest/testdata/x.json", "requirements-ci.txt"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("1\n")
    base = commit("base")
    for rel in ("orchestrator/ingest/test_score.py", "docs/a.md", "orchestrator/ingest/testdata/x.json",
                "orchestrator/baseline/compare.py"):
        (tmp_path / rel).write_text("2\n")
    after_tests = commit("tests and docs only")
    assert scorer_changes(tmp_path, base, after_tests) == []
    for rel in ("orchestrator/ingest/score.py", "schemas/s.json", "harness/run.sh", "requirements-ci.txt"):
        (tmp_path / rel).write_text("3\n")
        changed = scorer_changes(tmp_path, base, commit(f"change {rel}"))
        assert rel in changed, rel
        (tmp_path / rel).write_text("1\n")
        commit("restore")
    try:
        scorer_changes(tmp_path, "0" * 40)
        raise SystemExit("a harness commit outside the history must raise")
    except AssertionError as e:
        assert "not in this clone" in str(e)
