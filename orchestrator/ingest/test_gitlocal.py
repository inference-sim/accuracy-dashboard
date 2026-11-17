"""Tests of gitlocal.py on a scratch repository: the answers the build resolver and the recipe reader take from
GitHub's REST API, read from a clone with git plumbing."""
import base64
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gitlocal as gl  # noqa: E402


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                           "-c", "tag.gpgsign=false", *args], capture_output=True, text=True, check=True).stdout.strip()


def repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "benchmarks").mkdir()
    (r / "benchmarks" / "a.sh").write_text("echo a\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "one")
    one = git(r, "rev-parse", "HEAD")
    git(r, "tag", "v0.1.0")
    git(r, "checkout", "-qb", "side")
    (r / "s").write_text("s\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "side")
    side = git(r, "rev-parse", "HEAD")
    git(r, "checkout", "-q", "main")
    for k in range(3):
        (r / f"m{k}").write_text(f"{k}\n")
        git(r, "add", "-A")
        git(r, "commit", "-qm", f"m{k}")
    return r, one, side, git(r, "rev-parse", "HEAD")


def test_the_resolvers_questions_are_answered_as_github_answers_them(tmp_path):
    r, one, side, head = repo(tmp_path)
    g = gl.LocalGit(r)
    assert g.resolve_commit("o/r", one[:9]) == one and g.resolve_commit("o/r", "deadbeef") is None
    assert g.tag_commit("o/r", "v0.1.0") == one and g.tag_commit("o/r", "v9.9.9") is None
    assert g.compare("o/r", one, head) == ("ahead", 3, 0)
    assert g.compare("o/r", head, one) == ("behind", 0, 3)
    assert g.compare("o/r", side, head) == ("diverged", 3, 1)
    assert g.compare("o/r", head, head) == ("identical", 0, 0)
    assert g.merge_base("o/r", side, head) == one
    assert g.is_on_release_tag("o/r", one) and not g.is_on_release_tag("o/r", head)


def test_the_recipe_readers_trees_and_blobs_come_from_the_clone_and_anything_else_from_rest(tmp_path):
    r, one, _, _ = repo(tmp_path)
    asked = []
    get = gl.local_get(r, "o/x", lambda p: asked.append(p) or {"head_sha": one})
    tree = get(f"/repos/o/x/git/trees/{one}?recursive=1")["tree"]
    blob = next(t for t in tree if t["path"] == "benchmarks/a.sh")
    assert blob["type"] == "blob"
    assert base64.b64decode(get(f"/repos/o/x/git/blobs/{blob['sha']}")["content"]) == b"echo a\n"
    assert asked == []
    assert get("/repos/o/x/actions/runs/1")["head_sha"] == one and asked == ["/repos/o/x/actions/runs/1"]
