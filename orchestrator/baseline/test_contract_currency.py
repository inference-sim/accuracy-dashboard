"""Tests of the contract-currency gate's split into current and historical contracts (contract_currency.py and
test_contracts_current.stale_contracts): a current contract made stale by a scorer change fails, a historical one does
not, and the historical list names existing contracts, one by one, at their own provenance."""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import contract_currency as cc  # noqa: E402
import test_contracts_current as gate  # noqa: E402


def add_contract(repo, name, harness_commit, manifest="m" * 64):
    d = repo.root / "docs" / "m2" / name / "contract"
    d.mkdir(parents=True)
    (d / "provenance.json").write_text(json.dumps({"harness_commit": harness_commit, "pull_manifest_sha256": manifest}))
    return f"docs/m2/{name}/contract"


def list_historical(repo, entries):
    (repo.root / cc.LIST).write_text(json.dumps({"historical": entries}))


def entry(path, harness_commit, manifest="m" * 64, reason="its pull is no longer held"):
    return {"path": path, "harness_commit": harness_commit, "pull_manifest_sha256": manifest, "reason": reason}


class Repo:
    """A scratch repository with a scorer file, a doc and two contracts."""

    def __init__(self, root):
        self.root = root
        gate.git(root, "init", "-q")
        self.write("orchestrator/ingest/score.py", "X = 1\n")
        self.write("docs/a.md", "a\n")
        self.base = self.commit("scored")

    def write(self, rel, body):
        (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.root / rel).write_text(body)

    def commit(self, msg):
        gate.git(self.root, "add", "-A")
        assert gate.git(self.root, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                        "commit", "-qm", msg).returncode == 0
        return gate.git(self.root, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = Repo(tmp_path)
    old = add_contract(r, "old", r.base)
    new = add_contract(r, "new", r.base)
    list_historical(r, [entry(old, r.base)])
    r.commit("contracts")
    return r, old, new


def test_a_scorer_change_makes_a_current_contract_stale_and_not_a_historical_one(repo):
    r, old, new = repo
    r.write("orchestrator/ingest/score.py", "X = 2\n")
    head = r.commit("change the scorer")
    stale = gate.stale_contracts(r.root, head)
    assert list(stale) == [new] and "orchestrator/ingest/score.py" in stale[new]


def test_without_the_list_a_scorer_change_makes_every_contract_stale(repo):
    r, old, new = repo
    (r.root / cc.LIST).unlink()
    r.write("orchestrator/ingest/score.py", "X = 2\n")
    assert sorted(gate.stale_contracts(r.root, r.commit("change the scorer, no list"))) == sorted([old, new])


def test_with_no_scorer_change_no_contract_is_stale(repo):
    r, _, _ = repo
    r.write("docs/a.md", "b\n")
    assert gate.stale_contracts(r.root, r.commit("docs only")) == {}


def test_a_contract_is_historical_only_by_its_exact_path(repo):
    r, old, new = repo
    assert cc.current(r.root) == [new]
    list_historical(r, [])
    assert cc.current(r.root) == sorted([old, new])


@pytest.mark.parametrize("bad, match", [
    ({"path": "docs/m2/gone/contract"}, "no contract directory"),
    ({"path": "docs/m2/*/contract"}, "never a pattern"),
    ({"path": "docs/m2/o?d/contract"}, "never a pattern"),
    ({"path": ""}, "never a pattern"),
    ({"harness_commit": "0" * 40}, "harness_commit"),
    ({"pull_manifest_sha256": "f" * 64}, "pull_manifest_sha256"),
    ({"reason": " "}, "no reason"),
])
def test_a_historical_entry_must_name_an_existing_contract_at_its_own_provenance(repo, bad, match):
    r, old, _ = repo
    list_historical(r, [entry(old, r.base) | bad])
    with pytest.raises(cc.CurrencyError, match=match):
        cc.current(r.root)


def test_a_contract_listed_twice_is_refused(repo):
    r, old, _ = repo
    list_historical(r, [entry(old, r.base), entry(old, r.base)])
    with pytest.raises(cc.CurrencyError, match="twice"):
        cc.historical(r.root)


def test_a_contract_scored_again_loses_its_exemption_until_the_entry_is_changed(repo):
    """Re-scoring rewrites provenance.json; the stale entry then no longer matches and the list is refused."""
    r, old, _ = repo
    (r.root / old / "provenance.json").write_text(json.dumps({"harness_commit": "a" * 40, "pull_manifest_sha256": "m" * 64}))
    with pytest.raises(cc.CurrencyError, match="harness_commit"):
        cc.historical(r.root)


def test_the_committed_list_is_the_m2_contracts_each_at_its_own_provenance():
    hist = cc.historical(cc.ROOT)
    assert sorted(hist) == sorted(f"docs/m2/{d}/contract" for d in (
        "baseline-v0.16.0", "h200-v033", "pd-table-as-published", "pd-writer-experiment", "preliminary-after"))
    assert all(p in cc.contracts(cc.ROOT) for p in hist)
