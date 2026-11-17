"""Behavioural tests of pd_net: git answers the build resolver's questions as GitHub does, and the REST cache
answers a repeated read without a request and stops on a low quota."""
import subprocess
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pd_net as pn  # noqa: E402


def git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *a], check=True,
                          capture_output=True, text=True).stdout.strip()


def commit(w, name):
    (w / name).write_text(name)
    git(w, "add", "-A")
    git(w, "commit", "-q", "-m", name)
    return git(w, "rev-parse", "HEAD")


def history(tmp):
    w = tmp / "w"
    w.mkdir()
    git(w, "init", "-q", "-b", "main")
    a = commit(w, "a")
    git(w, "tag", "v0.1.0")
    b = commit(w, "b")
    c = commit(w, "c")
    git(w, "checkout", "-q", "-b", "side", a)
    d = commit(w, "d")
    git(w, "checkout", "-q", "main")
    bare = tmp / "v.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(w), str(bare)], check=True, capture_output=True)
    return bare, a, b, c, d


def test_compare_statuses_as_github_names_them(tmp_path):
    bare, a, b, c, d = history(tmp_path)
    g = pn.GitCompare({"v/v": bare})
    assert g.compare("v/v", a, c) == ("ahead", 2, 0)
    assert g.compare("v/v", c, a) == ("behind", 0, 2)
    assert g.compare("v/v", a, a) == ("identical", 0, 0)
    assert g.compare("v/v", d, c) == ("diverged", 2, 1)
    assert g.merge_base("v/v", d, c) == a


def test_tags_and_prefixes(tmp_path):
    bare, a, b, c, d = history(tmp_path)
    g = pn.GitCompare({"v/v": bare})
    assert g.tag_commit("v/v", "v0.1.0") == a
    assert g.tag_commit("v/v", "v9.9.9") is None
    assert g.tag_commit("v/v", "main") is None
    assert g.resolve_commit("v/v", c[:9]) == c
    assert g.resolve_commit("v/v", "f" * 40) is None
    assert g.is_on_release_tag("v/v", a) is True      # the tagged commit itself
    assert g.is_on_release_tag("v/v", c) is False     # added after the only release tag


def fake_clients(bodies):
    calls = []

    def real(url, headers, timeout=60, **kw):
        calls.append(url)
        return bodies[url]
    return types.SimpleNamespace(_get_bytes=real), calls


def test_cache_answers_a_repeat_without_a_request(tmp_path):
    u = "https://api.github.com/repos/o/r/actions/runs/1"
    cl, calls = fake_clients({u: b'{"x":1}'})
    st = pn.install_cache(cl, tmp_path / "c", min_interval=0, min_core=1000, core_remaining=lambda: 5000)
    assert cl._get_bytes(u, {}) == b'{"x":1}'
    assert cl._get_bytes(u, {}) == b'{"x":1}'
    assert calls == [u] and st["rest"] == 1 and st["hits"] == 1


def test_low_quota_stops_before_the_request(tmp_path):
    u = "https://api.github.com/repos/o/r/actions/runs/2"
    cl, calls = fake_clients({u: b"{}"})
    pn.install_cache(cl, tmp_path / "c", min_interval=0, min_core=1000, core_remaining=lambda: 999)
    try:
        cl._get_bytes(u, {})
    except pn.QuotaLow:
        assert calls == []
        return
    raise AssertionError("a quota below the floor must stop the pull")


def test_requests_are_paced(tmp_path):
    t = [0.0]
    slept = []
    urls = [f"https://api.github.com/x/{i}" for i in range(3)]
    cl, _ = fake_clients({u: b"{}" for u in urls})
    pn.install_cache(cl, tmp_path / "c", min_interval=2.0, min_core=0, core_remaining=lambda: 5000,
                     clock=lambda: t[0], sleep=lambda s: (slept.append(s), t.__setitem__(0, t[0] + s)))
    for u in urls:
        cl._get_bytes(u, {})
    assert slept == [2.0, 2.0]
