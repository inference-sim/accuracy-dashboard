"""A committed contract (a scoring run's results) was made by the scorer that is in this tree.

The contract names the harness commit that scored it (provenance.json `harness_commit`, which
harness/run.sh records as the commit of the checkout it ran from). The results are committed after
that commit, so the commit cannot be HEAD; what must hold is that nothing that scores changed in
between. The files that score are harness/, schemas/, requirements-ci.txt and every non-test file
under orchestrator/ except orchestrator/baseline/ and the boundary lint (the table, split and residual tools read a
contract; none writes one). A change to any of them means the contract describes another scorer's output,
and the run is made again (docs/m2/after-run.md).

The gate holds every current contract. A historical contract, one scored from a pull that is no longer held and so can
never be scored again, is exempt only by its exact path in docs/m2/historical-contracts.json, with its harness commit,
pull manifest and reason (contract_currency.py checks the list).

CI checks the repository out in full (fetch-depth 0): the harness commit must be in the history.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract_currency  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
SCORER_PATHS = ["harness", "orchestrator", "schemas", "requirements-ci.txt"]
NOT_THE_SCORER = [":(exclude,glob)orchestrator/**/test_*.py", ":(exclude,glob)orchestrator/**/testdata/**",
                  ":(exclude,glob)orchestrator/**/test_*", ":(exclude,glob)harness/test_*", ":(exclude)orchestrator/baseline",
                  ":(exclude)orchestrator/lint_blis_boundary.py",  # a lint of the source tree; it writes no contract
                  ":(exclude)orchestrator/build_summary_v2.py"]  # reads a contract and writes a summary; the contract it inverts a summary to is a test aid


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


def test_moving_an_upstream_pin_does_not_make_a_contract_stale(tmp_path):
    """The upstream builds (inference-sim, blis-substrate, the router fork) are pinned in .github/stack-pins.env, which
    is not a scorer file: replacing a commit by the release tag at that content is a pin-only change."""
    pins = ".github/stack-pins.env"
    listed = git(ROOT, "ls-files", "--", *SCORER_PATHS, *NOT_THE_SCORER).stdout.split()
    assert (ROOT / pins).is_file() and pins not in listed
    assert not [f for f in listed if f.startswith("harness/") and "SIM_" in (ROOT / f).read_text()], "a simulator pin in a scorer file"
    git(tmp_path, "init", "-q")
    for rel in ("orchestrator/ingest/score.py", pins):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("SIM_REF=" + "a" * 40 + "\n")
    git(tmp_path, "add", "-A")
    commit = lambda m: (git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "commit", "-qm", m),
                        git(tmp_path, "rev-parse", "HEAD").stdout.strip())[1]
    base = commit("scored")
    (tmp_path / pins).write_text("SIM_REF=v0.17.0\n")
    git(tmp_path, "add", "-A")
    assert scorer_changes(tmp_path, base, commit("pin to the tag")) == []
