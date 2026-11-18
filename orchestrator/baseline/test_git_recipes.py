"""Behavioural tests of GitRecipes: a run's recipes read from a local clone read the same as through the REST API,
and cost no REST call beyond the run's commit."""
import subprocess
import sys
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ingest"))
import git_recipes as gr  # noqa: E402
import recipes as rcp  # noqa: E402

MASTER = """
cfg-a:
  model: org/Model-A
  image: img:1
  framework: dynamo-vllm
  precision: fp8
  runner: b200-multinode
"""
RUNNERS = """
clusters:
  c1:
    models:
      entries:
        Model-A@x: {dir: ModelA-dir}
"""


def git(cwd, *a):
    subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *a], check=True,
                   capture_output=True)


def make_repo(tmp: Path) -> tuple[Path, str]:
    repo = tmp / "r.git"
    work = tmp / "w"
    work.mkdir()
    git(work, "init", "-q")
    (work / "configs").mkdir()
    (work / "configs" / "nvidia-master.yaml").write_text(MASTER)
    (work / "configs" / "runners.yaml").write_text(RUNNERS)
    (work / "benchmarks").mkdir()
    (work / "benchmarks" / "a_mtp.sh").write_text("echo hi\n")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "c1")
    sha = subprocess.run(["git", "-C", str(work), "rev-parse", "HEAD"], capture_output=True, text=True,
                         check=True).stdout.strip()
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(repo)], check=True, capture_output=True)
    return repo, sha


def test_reads_recipes_without_rest(tmp_path):
    repo, sha = make_repo(tmp_path)
    calls = []

    def get(path):
        calls.append(path)
        return {"head_sha": sha}
    g = gr.GitRecipes(get, "o/InferenceX", repo)
    assert g.run_commit("42") == sha
    rc = g.at(sha)
    assert [r["model"] for r in rc.recipes] == ["org/Model-A"]
    assert rc.dirs == {"ModelA-dir": {"Model-A"}}
    assert "benchmarks/a_mtp.sh" in rc.scripts
    assert set(rc.tree) >= {"configs/nvidia-master.yaml", "configs/runners.yaml"}
    assert g.blob_text(rc.tree["configs/runners.yaml"]) == RUNNERS
    assert g.script(rc, "benchmarks/a_mtp.sh") == "echo hi\n"
    assert calls == ["/repos/o/InferenceX/actions/runs/42"]     # the run's commit is the only REST read


def test_commit_the_clone_does_not_hold_is_unavailable(tmp_path):
    repo, _ = make_repo(tmp_path)
    g = gr.GitRecipes(lambda p: {"head_sha": "0" * 40}, "o/InferenceX", repo, fetch=False)
    try:
        g.at("0" * 40)
    except rcp.RecipesUnavailable:
        return
    raise AssertionError("a commit absent from the clone must be RecipesUnavailable")


def test_run_commit_404_propagates(tmp_path):
    repo, _ = make_repo(tmp_path)

    def get(path):
        raise urllib.error.HTTPError(path, 404, "gone", {}, None)
    g = gr.GitRecipes(get, "o/InferenceX", repo)
    try:
        g.run_commit("7")
    except urllib.error.HTTPError as e:
        assert e.code == 404
        return
    raise AssertionError("pull.py maps an HTTP 404 on the run to no_commit; it must reach it")
