"""Tests of lookups.py: a lookup asked once is answered from the record after, and only a new question is asked."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lookups  # noqa: E402


class GH:
    def __init__(self):
        self.calls = []

    def compare(self, repo, base, head):
        self.calls.append((base, head))
        return ("ahead", 3, 1)

    def resolve_commit(self, repo, sha):
        self.calls.append(sha)
        return sha + "0" * (40 - len(sha))

    def other(self):
        return "not recorded"


def test_a_recorded_answer_is_replayed_and_only_a_new_question_is_asked():
    store = {}
    gh = lookups.Recorded(GH(), store, lookups.GITHUB_METHODS)
    assert gh.compare("r", "a", "b") == ("ahead", 3, 1)
    assert gh.resolve_commit("r", "abc")[:3] == "abc"
    assert gh.misses == 2
    replay = GH()
    again = lookups.Recorded(replay, dict(store), lookups.GITHUB_METHODS)
    assert again.compare("r", "a", "b") == ("ahead", 3, 1) and again.resolve_commit("r", "abc")[:3] == "abc"
    assert replay.calls == [] and again.misses == 0
    assert again.compare("r", "a", "c") == ("ahead", 3, 1) and replay.calls == [("a", "c")] and again.misses == 1
    assert again.other() == "not recorded"
