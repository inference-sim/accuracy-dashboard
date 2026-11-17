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


def _gone(url="u"):
    import io
    import urllib.error
    return urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))


def test_a_run_github_no_longer_holds_is_asked_once_and_answers_gone_to_every_point():
    # The ledger's source holds runs GitHub has deleted. Each of their points must learn the run is gone, and the run
    # is asked once, not once per point: thousands of points share a few hundred runs, and the token's REST budget
    # is per hour.
    import urllib.error
    calls = {"list": 0, "run": 0}

    class G(art.GitHubArtifacts):
        def list(self, run_id):
            calls["list"] += 1
            raise _gone()

    g = G("repo", None, tempfile.mkdtemp())
    import clients
    real = clients._get_json

    def get_json(url, *a, **k):
        calls["run"] += 1
        raise _gone(url)
    clients._get_json = get_json
    try:
        for _ in range(5):
            for f in (g.list_cached, g.run):
                try:
                    f("123")
                    raise AssertionError("a gone run must raise")
                except urllib.error.HTTPError as e:
                    assert e.code == 404
    finally:
        clients._get_json = real
    assert calls == {"list": 1, "run": 1}


def test_a_listing_error_other_than_gone_is_not_remembered():
    import io
    import urllib.error
    calls = {"n": 0}

    class G(art.GitHubArtifacts):
        def list(self, run_id):
            calls["n"] += 1
            raise urllib.error.HTTPError("u", 500, "boom", {}, io.BytesIO(b""))

    g = G("repo", None, tempfile.mkdtemp())
    for _ in range(2):
        try:
            g.list_cached("1")
        except urllib.error.HTTPError:
            pass
    assert calls["n"] == 2
