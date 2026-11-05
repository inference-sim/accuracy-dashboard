"""Tests for the scoring harness's entrypoint (run.sh) and its release workflow.

run.sh's flags are checked with --check-args, which validates and exits without cloning or
building. The real path is run against a local bare git repository standing in for inference-sim,
with a fake `go`, so these tests need no network. The workflow is checked as YAML.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
RUN = HERE / "run.sh"
WORKFLOW = HERE.parent / ".github" / "workflows" / "harness-release.yml"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
GOOD = ["--units", "units.txt", "--pull", "pull", "--out", "out", "--catalog", "c", "--registry", "r"]


def check(*args, env=None):
    e = {k: v for k, v in os.environ.items() if k != "HARNESS_DIGEST"}
    e.update(env or {})
    return subprocess.run(["bash", str(RUN), "--check-args", *args], capture_output=True, text=True, env=e)


def test_a_release_tag_and_a_full_commit_are_accepted():
    for sim in ("v0.16.0", "v0.16.0-rc.1", COMMIT):
        p = check("--sim", sim, *GOOD)
        assert p.returncode == 0, p.stderr


def test_a_branch_name_is_refused():
    for sim in ("main", "m1/result", COMMIT[:12], "0.16.0"):
        p = check("--sim", sim, *GOOD)
        assert p.returncode == 2
        assert f"--sim {sim}" in p.stderr


def test_a_missing_units_flag_is_refused():
    p = check("--sim", "v0.16.0", "--pull", "pull", "--out", "out")
    assert p.returncode == 2
    assert "--units is required" in p.stderr


def test_an_unknown_flag_is_refused():
    p = check("--sim", "v0.16.0", *GOOD, "--metrics-path", "x")
    assert p.returncode == 2
    assert "unknown flag --metrics-path" in p.stderr


def test_the_field_list_is_not_a_flag():
    # The scorer asks the blis it built for the field list (COV-3); no file stands in for it.
    p = check("--sim", "v0.16.0", *GOOD, "--fields", "fields.json")
    assert p.returncode == 2
    assert "unknown flag --fields" in p.stderr


def test_catalog_and_registry_are_required():
    base = ["--units", "units.txt", "--pull", "pull", "--out", "out"]
    p = check("--sim", "v0.16.0", *base, "--catalog", "cat")
    assert p.returncode == 2 and "--registry is required" in p.stderr
    p = check("--sim", "v0.16.0", *base, "--registry", "reg")
    assert p.returncode == 2 and "--catalog is required" in p.stderr
    assert check("--sim", "v0.16.0", *GOOD).returncode == 0


def test_a_malformed_harness_digest_is_refused():
    assert check("--sim", "v0.16.0", *GOOD, env={"HARNESS_DIGEST": "sha256:" + "a" * 64}).returncode == 0
    p = check("--sim", "v0.16.0", *GOOD, env={"HARNESS_DIGEST": "latest"})
    assert p.returncode == 2
    assert "HARNESS_DIGEST latest" in p.stderr


# ------------------------------------------------------------------ the release workflow

def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def triggers(doc: dict) -> dict:
    # PyYAML reads the bare key `on` as the boolean True.
    return doc.get("on", doc.get(True))


def test_the_workflow_runs_only_on_release_tags_and_dispatch():
    on = triggers(workflow())
    assert set(on) == {"push", "workflow_dispatch"}
    assert on["push"] == {"tags": ["v*"]}


def test_every_action_is_pinned_to_a_commit():
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)", WORKFLOW.read_text(), re.M)
    assert uses
    for u in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", u), f"{u} is not pinned to a commit SHA"


def test_the_image_is_signed_by_digest():
    steps = [s for j in workflow()["jobs"].values() for s in j["steps"]]
    signs = [s for s in steps if "cosign sign" in s.get("run", "")]
    assert len(signs) == 1
    run, env = signs[0]["run"], signs[0].get("env", {})
    # Either the digest is written in the command, or the command names $DIGEST and the step
    # takes DIGEST from the build step's digest output.
    by_literal = re.search(r"@(sha256:|\$\{\{[^}]*digest[^}]*\}\})", run)
    by_env = re.search(r"@\$\{?DIGEST\}?", run) and "outputs.digest" in env.get("DIGEST", "")
    assert by_literal or by_env, run
    assert any("cosign verify" in s.get("run", "") for s in steps)


def test_only_the_release_job_may_request_an_oidc_token():
    doc = workflow()
    assert "id-token" not in (doc.get("permissions") or {})
    holders = [n for n, j in doc["jobs"].items() if (j.get("permissions") or {}).get("id-token") == "write"]
    assert holders == ["release"]


# ------------------------------------------------------------------ the real path

def git(*args, cwd=None):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout.strip()


def tagged_dir(path: Path, tag: str) -> Path:
    path.mkdir(parents=True)
    git("init", "-q", cwd=path)
    git("commit", "-q", "--allow-empty", "-m", "x", cwd=path)
    git("tag", tag, cwd=path)
    return path


STACK = {"kind": "Stack", "engines": [{"kind": "vllm", "version": "0.32.0"}]}
FIELDS = {"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.32.0"}, "fields": []}
MANIFEST = {"window": ["2026-05-01", "2026-10-28"], "pulled_at": "2026-10-28T00:00:00Z", "vllm_ref": "v0.32.0",
            "vllm_max_distance": 2000, "unnamed_slugs": [], "base_models": {}, "undated_row_ids": [],
            "ledger": {"revision": "r", "unlisted": []}, "points": []}


def real_setup(tmp: Path, tag: str = "v0.16.0"):
    """A bare git repository standing in for inference-sim (the tag v0.16.0 and its commit), a fake
    `go` and a python3 that records its arguments, and the smallest pull, units, catalog and registry."""
    work = tmp / "upstream"
    work.mkdir()
    git("init", "-q", cwd=work)
    (work / "main.go").write_text("package main\n")
    (work / "go.mod").write_text("module x\n\nrequire (\n\tgithub.com/inference-sim/blis-latency-kernel v0.3.0\n)\n")
    (work / "stack.json").write_text(json.dumps(STACK))
    git("add", ".", cwd=work)
    git("commit", "-q", "-m", "release", cwd=work)
    git("tag", tag, cwd=work)
    commit = git("rev-parse", "HEAD", cwd=work)
    bare = tmp / "inference-sim.git"
    git("clone", "-q", "--bare", str(work), str(bare))
    bin_ = tmp / "bin"
    bin_.mkdir()
    # `go mod download` does nothing; `go build -o OUT main.go` writes a fake blis script at OUT.
    go = bin_ / "go"
    go.write_text('#!/bin/sh\n'
                  'if [ "$1 $2" = "mod download" ]; then exit 0; fi\n'
                  'if [ "$1 $2" = "build -o" ]; then printf "#!/bin/sh\\ncase \\"\\$1\\" in fields) cat \\"\\$FAKE_FIELDS\\";; metrics) cat \\"\\$FAKE_FIELDS.metrics\\";; esac\\nexit 0\\n" > "$3"; chmod +x "$3"; exit 0; fi\n'
                  'echo "fake go: unexpected $*" >&2; exit 9\n')
    py = bin_ / "python3"
    log = tmp / "python-args.txt"
    # The checkout is removed when run.sh exits, so the wrapper also lists the binary's directory.
    py.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{log}"\n'
                  'prev=""\nfor a in "$@"; do\n'
                  f'  if [ "$prev" = --blis ]; then ls "$(dirname "$a")" > "{log}.ls"; fi\n'
                  '  prev="$a"\ndone\n'
                  f'exec "{sys.executable}" "$@"\n')
    for f in (go, py):
        f.chmod(0o755)
    pull = tmp / "pull"
    pull.mkdir()
    (pull / "manifest.json").write_text(json.dumps(MANIFEST))
    units = tmp / "units.txt"
    units.write_text("")
    fields = tmp / "fields.json"
    fields.write_text(json.dumps(FIELDS))
    # `blis metrics --json`: the client's two definitions (DEV-8).
    sys.path.insert(0, str(HERE.parent / "orchestrator" / "ingest"))
    from test_result import REGISTRY
    (tmp / "fields.json.metrics").write_text(json.dumps({"metrics": list(REGISTRY.values())}))
    cat = tagged_dir(tmp / "cat", "v1.0.0")
    (cat / "models").mkdir()
    (cat / "hardware").mkdir()
    reg = tagged_dir(tmp / "reg", "v1.0.0")
    (reg / "coefficients").mkdir()
    return bare, commit, bin_, log, pull, units, fields, cat, reg


def run_real(tmp: Path, sim_of, extra=(), tag="v0.16.0"):
    bare, commit, bin_, log, pull, units, fields, cat, reg = real_setup(tmp, tag)
    out = tmp / "out"
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "HARNESS_DIGEST": "sha256:" + "b" * 64,
           "FAKE_FIELDS": str(fields)}
    p = subprocess.run(["bash", str(RUN), "--sim", sim_of(commit), "--sim-repo", str(bare), "--units", str(units),
                        "--pull", str(pull), "--out", str(out), "--catalog", str(cat), "--registry", str(reg),
                        *extra], capture_output=True, text=True, env=env)
    return p, out, log, commit


def test_the_real_path_builds_into_the_checkout_and_scores_with_it(tmp_path):
    p, out, log, commit = run_real(tmp_path, lambda c: "v0.16.0")
    assert p.returncode == 0, p.stderr
    argv = log.read_text().splitlines()
    assert "score" in argv, argv
    blis = Path(argv[argv.index("--blis") + 1])
    # The binary sits in the inference-sim checkout, beside its go.mod and stack.json.
    assert blis.name == "blis" and blis.parent.name == "inference-sim"
    assert set(Path(str(log) + ".ls").read_text().split()) == {"blis", "go.mod", "main.go", "stack.json"}
    assert argv[argv.index("--sim-build") + 1] == "v0.16.0"
    assert argv[argv.index("--harness-digest") + 1] == "sha256:" + "b" * 64
    prov = json.loads((out / "provenance.json").read_text())
    # The stack.json of the checkout gave the engine release; the checkout gave the build.
    assert prov["engine"] == {"kind": "vllm", "version": "0.32.0"}
    assert prov["simulator"] == {"build": "v0.16.0", "engine": {"kind": "vllm", "version": "0.32.0"},
                                 "harness_digest": "sha256:" + "b" * 64}
    assert prov["harness_digest"] == "sha256:" + "b" * 64
    assert prov["blis"]["release"] == "v0.16.0" and prov["blis"]["commit_sha"] == commit
    assert prov["blis"]["extractor_version"] == "blis-latency-kernel@v0.3.0"
    assert prov["fields_sha256"] and prov["experimental"] is False and prov["corpus"] is None


def test_the_real_path_scores_a_full_commit(tmp_path):
    p, out, log, commit = run_real(tmp_path, lambda c: c)
    assert p.returncode == 0, p.stderr
    prov = json.loads((out / "provenance.json").read_text())
    assert prov["simulator"]["build"] == commit and prov["experimental"] is True


def test_the_corpus_flags_are_required_only_for_an_agentic_point(tmp_path):
    pid = "a" * 64
    bare, commit, bin_, log, pull, units, fields, cat, reg = real_setup(tmp_path)
    (pull / "manifest.json").write_text(json.dumps(
        {**MANIFEST, "points": [{"point_id": pid, "reasons": [], "row": {"benchmark_type": "agentic_traces"}}]}))
    units.write_text(pid + "\n")
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "FAKE_FIELDS": str(fields)}
    p = subprocess.run(["bash", str(RUN), "--sim", "v0.16.0", "--sim-repo", str(bare), "--units", str(units),
                        "--pull", str(pull), "--out", str(tmp_path / "out"), "--catalog", str(cat),
                        "--registry", str(reg)], capture_output=True, text=True, env=env)
    assert p.returncode == 2
    assert "--corpus and --corpus-revision are required" in p.stderr


def test_the_real_path_scores_a_pre_release_tag_and_marks_its_figures_experimental(tmp_path):
    p, out, log, commit = run_real(tmp_path, lambda c: "v0.16.0-rc1", tag="v0.16.0-rc1")
    assert p.returncode == 0, p.stderr
    prov = json.loads((out / "provenance.json").read_text())
    assert prov["simulator"]["build"] == "v0.16.0-rc1" and prov["experimental"] is True


# ------------------------------------------------------------------ pinned workflows

WORKFLOWS = sorted((HERE.parent / ".github" / "workflows").glob("*.yml"))


def test_every_action_of_every_workflow_is_pinned_to_a_commit_with_its_version_in_a_comment():
    assert len(WORKFLOWS) >= 4
    for wf in WORKFLOWS:
        uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)(.*)$", wf.read_text(), re.M)
        assert uses, wf
        for ref, rest in uses:
            assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), f"{wf.name}: {ref} is not pinned to a commit SHA"
            assert re.fullmatch(r"\s*# v\d+\.\d+\.\d+", rest), f"{wf.name}: {ref} has no version comment"


def test_ci_installs_python_dependencies_only_from_the_hashed_requirements_file():
    req = (HERE.parent / "requirements-ci.txt").read_text()
    pins = [ln for ln in req.splitlines() if ln and not ln.startswith(("#", "-r"))]
    assert {ln.split("==")[0] for ln in pins} >= {"pytest", "numpy"}
    for ln in pins:
        assert re.fullmatch(r"[\w.-]+==[\w.]+ --hash=sha256:[0-9a-f]{64}", ln), ln
    assert "-r harness/requirements.txt" in req
    for wf in WORKFLOWS:
        for ln in re.findall(r"pip install[^\n]*", wf.read_text()):
            assert "--require-hashes -r requirements-ci.txt" in ln, f"{wf.name}: {ln}"
