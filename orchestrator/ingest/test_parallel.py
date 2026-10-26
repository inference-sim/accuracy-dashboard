"""Concurrency safety for the parallel artifact-download pool (Discussion #15, revised): the
per-run artifact listing is memoized under a lock so a thread pool freezing many points of one
run lists it exactly once and never races the cache."""
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import artifacts as art  # noqa: E402


def test_list_cached_lists_each_run_once_under_concurrency():
    calls = {"n": 0}

    class G(art.GitHubArtifacts):
        def list(self, run_id):
            calls["n"] += 1
            time.sleep(0.01)          # widen the race window
            return [f"art-{run_id}"]

    g = G("repo", None, tempfile.mkdtemp())
    results = []
    threads = [threading.Thread(target=lambda: results.append(g.list_cached("123"))) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert calls["n"] == 1                       # one HTTP listing despite 12 concurrent callers
    assert all(r == results[0] for r in results)  # all callers saw the same listing


def test_list_cached_separate_runs_list_separately():
    calls = {"n": 0}

    class G(art.GitHubArtifacts):
        def list(self, run_id):
            calls["n"] += 1
            return [run_id]

    g = G("repo", None, tempfile.mkdtemp())
    assert g.list_cached("a") == ["a"]
    assert g.list_cached("b") == ["b"]
    assert g.list_cached("a") == ["a"]           # cached, no new call
    assert calls["n"] == 2                        # one per distinct run
