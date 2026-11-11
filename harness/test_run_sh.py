"""Tests for the scoring harness's entrypoint (run.sh) and the absence of an image path.

run.sh's flags are checked with --check-args, which validates and exits without cloning or
building. The real path is run against a local bare git repository standing in for inference-sim,
with a fake `go`, so these tests need no network. The workflows are checked as YAML.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
RUN = HERE / "run.sh"
WORKFLOWS = sorted((HERE.parent / ".github" / "workflows").glob("*.yml"))
COMMIT = "0123456789abcdef0123456789abcdef01234567"
GOOD = ["--units", "units.txt", "--pull", "pull", "--out", "out", "--catalog", "c", "--registry", "r",
        "--corpus-dir", "k", "--fields", "/dev/null", "--catalog-release", "v0.3.0", "--registry-release", "v0.2.0"]


def check(*args, env=None):
    e = {k: v for k, v in os.environ.items() if k != "HARNESS_DIGEST"}
    e.update(env or {})
    return subprocess.run(["bash", str(RUN), "--check-args", *args], capture_output=True, text=True, env=e)


def test_a_release_tag_and_a_full_commit_are_accepted():
    for sim in ("v0.16.0", "v0.16.0-rc.1", COMMIT):
        p = check("--sim", sim, *GOOD)
        assert p.returncode == 0, p.stderr


def test_the_data_pins_are_a_tag_or_a_full_commit_and_nothing_else():
    flags = ("--catalog-release", "--registry-release")

    def with_pin(flag, value):
        out = list(GOOD)
        out[out.index(flag) + 1] = value
        return out
    for flag in flags:
        for ok in ("v0.3.0", "v0.3.0-rc.1", COMMIT):
            p = check("--sim", "v0.16.0", *with_pin(flag, ok))
            assert p.returncode == 0, (flag, ok, p.stderr)
        for bad in ("main", "m2/10-router-table", COMMIT[:7], COMMIT[:12], COMMIT.upper(), "0.3.0", "v1"):
            p = check("--sim", "v0.16.0", *with_pin(flag, bad))
            assert p.returncode == 2 and f"{flag} {bad}" in p.stderr and "40-hex commit" in p.stderr, (flag, bad)


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


def test_the_field_list_is_a_required_file():
    # The scorer reads the engine's field list (COV-3) from the pinned blis-vllm release's file;
    # the M1 simulator has no `blis fields` to print it.
    without = [x for i, x in enumerate(GOOD) if x != "--fields" and GOOD[i - 1] != "--fields"]
    p = check("--sim", "v0.16.0", *without)
    assert p.returncode == 2 and "--fields is required" in p.stderr
    # A named file that does not exist is refused when the run starts, before anything is built.
    p = subprocess.run(["bash", str(RUN), "--sim", "v0.16.0", *[("/no/such/file" if GOOD[i - 1] == "--fields" else x)
                                                               for i, x in enumerate(GOOD)]],
                       capture_output=True, text=True)
    assert p.returncode == 2 and ("--fields /no/such/file is not a file" in p.stderr or "--units" in p.stderr)


def test_the_data_releases_are_required_and_passed_to_the_scorer():
    without = lambda flag: [x for i, x in enumerate(GOOD) if x != flag and GOOD[i - 1] != flag]  # noqa: E731
    for flag in ("--catalog-release", "--registry-release"):
        p = check("--sim", "v0.16.0", *without(flag))
        assert p.returncode == 2 and f"{flag} is required" in p.stderr, flag


def test_catalog_and_registry_are_required():
    base = ["--units", "units.txt", "--pull", "pull", "--out", "out", "--corpus-dir", "k"]
    p = check("--sim", "v0.16.0", *base, "--catalog", "cat")
    assert p.returncode == 2 and "--registry is required" in p.stderr
    p = check("--sim", "v0.16.0", *base, "--registry", "reg")
    assert p.returncode == 2 and "--catalog is required" in p.stderr
    assert check("--sim", "v0.16.0", *GOOD).returncode == 0


def test_the_corpus_directory_is_required_and_the_corpus_file_flags_are_gone():
    # The corpora come from the catalog's replay workloads, not from flags (D3, X12).
    p = check("--sim", "v0.16.0", *[x for i, x in enumerate(GOOD) if GOOD[max(i - 1, 0)] != "--corpus-dir" and x != "--corpus-dir"])
    assert p.returncode == 2 and "--corpus-dir is required" in p.stderr
    for flag in ("--corpus", "--corpus-revision", "--corpus-sha256", "--corpus-dataset"):
        p = check("--sim", "v0.16.0", *GOOD, flag, "x")
        assert p.returncode == 2 and f"unknown flag {flag}" in p.stderr, flag


def test_a_malformed_harness_commit_is_refused():
    assert check("--sim", "v0.16.0", *GOOD, env={"HARNESS_COMMIT": "a" * 40}).returncode == 0
    for bad in ("latest", "v0.4.0", "a" * 12, "sha256:" + "a" * 64):
        p = check("--sim", "v0.16.0", *GOOD, env={"HARNESS_COMMIT": bad})
        assert p.returncode == 2 and f"HARNESS_COMMIT {bad}" in p.stderr, bad


def test_no_container_or_signing_path_is_left():
    # X23, COV-1: the harness is a script. Nothing in the repository builds, signs, pulls or runs an image.
    for gone in ("harness/Dockerfile", "harness/image.pin", ".github/workflows/harness-release.yml",
                 "orchestrator/ingest/harness_pin.py"):
        assert not (HERE.parent / gone).exists(), gone
    for f in [*WORKFLOWS, RUN, HERE.parent / "orchestrator" / "ingest" / "cli.py", HERE.parent / "README.md"]:
        text = f.read_text()
        for word in ("docker", "cosign", "HARNESS_DIGEST", "harness_pin"):
            assert word not in text, f"{f.name} mentions {word}"


# ------------------------------------------------------------------ the real path

def git(*args, cwd=None):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout.strip()


def mounted_dir(path: Path) -> Path:
    """A data directory as a copy of the data has it, with no .git."""
    path.mkdir(parents=True)
    assert not (path / ".git").exists()
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
                  'if [ "$1 $2" = "build -o" ]; then printf "#!/bin/sh\\nexit 0\\n" > "$3"; chmod +x "$3"; exit 0; fi\n'
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
    cat = mounted_dir(tmp / "cat")
    (cat / "models").mkdir()
    (cat / "hardware").mkdir()
    reg = mounted_dir(tmp / "reg")
    (reg / "coefficients").mkdir()
    write_corpora(cat, tmp / "corpora")
    return bare, commit, bin_, log, pull, units, fields, cat, reg


def write_corpora(cat: Path, corpus_dir: Path) -> None:
    """The two AgentX replay workloads in the catalog, and their corpus files where
    resolve_agentic_corpus.py --all puts them, each with the sha256 its entry pins."""
    (cat / "workloads").mkdir(exist_ok=True)
    for alias, name, repo, rev in (
            ("semianalysis_cc_traces_weka_062126", "agentx-mvp-uncapped",
             "semianalysisai/cc-traces-weka-062126", "23f152f6f0f9399a85901b89a6458def0ef16729"),
            ("semianalysis_cc_traces_weka_062126_256k", "agentx-mvp",
             "semianalysisai/cc-traces-weka-062126-256k", "8fecd2fc56694469f758f0afbbb6335ad3043740")):
        body = f"{name}\n".encode()
        (cat / "workloads" / f"{name}.yaml").write_text(
            f"replay:\n  corpus:\n    loader: {alias}\n    source:\n      huggingface: {repo}\n"
            f"      revision: {rev}\n      file: traces.jsonl\n      split: train\n"
            f"    sha256: {hashlib.sha256(body).hexdigest()}\n")
        (corpus_dir / name).mkdir(parents=True, exist_ok=True)
        (corpus_dir / name / "traces.jsonl").write_bytes(body)


def harness_checkout(tmp: Path, git_history: bool = True) -> tuple[Path, str]:
    """A copy of the harness files in a git repository of its own, committed, so run.sh has a clean
    checkout to read its commit from (the working tree under test may hold uncommitted edits).
    Returns the copy's run.sh and its HEAD."""
    root = tmp / "dashboard"
    for rel in ("harness", "orchestrator", "schemas"):
        shutil.copytree(HERE.parent / rel, root / rel, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    shutil.copy2(HERE.parent / "requirements-ci.txt", root / "requirements-ci.txt")
    if not git_history:
        return root / "harness" / "run.sh", ""
    git("init", "-q", cwd=root)
    git("add", ".", cwd=root)
    git("commit", "-q", "-m", "harness", cwd=root)
    return root / "harness" / "run.sh", git("rev-parse", "HEAD", cwd=root)


def run_real(tmp: Path, sim_of, extra=(), tag="v0.16.0", env_extra=None, history=True, releases=("v0.3.0", "v0.2.0")):
    """run.sh from a committed copy of the harness files, against the stand-in simulator."""
    bare, commit, bin_, log, pull, units, fields, cat, reg = real_setup(tmp, tag)
    run_sh, head = harness_checkout(tmp, history)
    out = tmp / "out"
    env = {k: v for k, v in os.environ.items() if k != "HARNESS_COMMIT"}
    env.update({"PATH": f"{bin_}:{os.environ['PATH']}", "FAKE_FIELDS": str(fields), **(env_extra or {})})
    p = subprocess.run(["bash", str(run_sh), "--sim", sim_of(commit), "--sim-repo", str(bare), "--units", str(units),
                        "--pull", str(pull), "--out", str(out), "--catalog", str(cat), "--registry", str(reg),
                        "--corpus-dir", str(tmp / "corpora"), "--fields", str(fields),
                        "--catalog-release", releases[0], "--registry-release", releases[1], *extra], capture_output=True, text=True, env=env)
    return p, out, log, commit, head, run_sh


def test_the_real_path_builds_into_the_checkout_and_scores_with_it(tmp_path):
    p, out, log, commit, head, _ = run_real(tmp_path, lambda c: "v0.16.0")
    assert p.returncode == 0, p.stderr
    argv = log.read_text().splitlines()
    assert "score" in argv, argv
    blis = Path(argv[argv.index("--blis") + 1])
    # The binary sits in the inference-sim checkout, beside its go.mod and stack.json.
    assert blis.name == "blis" and blis.parent.name == "inference-sim"
    assert set(Path(str(log) + ".ls").read_text().split()) == {"blis", "go.mod", "main.go", "stack.json"}
    assert argv[argv.index("--sim-build") + 1] == "v0.16.0"
    assert argv[argv.index("--harness-commit") + 1] == head and re.fullmatch(r"[0-9a-f]{40}", head)
    prov = json.loads((out / "provenance.json").read_text())
    # The stack.json of the checkout gave the engine release; the checkout gave the build.
    assert prov["engine"] == {"kind": "vllm", "version": "0.32.0"}
    # The data carries no git history; its releases are the names run.sh was given.
    assert (prov["blis"]["catalog"], prov["blis"]["registry"]) == ("v0.3.0", "v0.2.0")
    assert prov["simulator"] == {"build": "v0.16.0", "engine": {"kind": "vllm", "version": "0.32.0"},
                                 "harness_commit": head}
    assert prov["harness_commit"] == head
    assert prov["blis"]["release"] == "v0.16.0" and prov["blis"]["commit_sha"] == commit
    assert prov["blis"]["extractor_version"] == "blis-latency-kernel@v0.3.0"
    assert prov["fields_sha256"] and prov["experimental"] is False and "corpus" not in prov
    assert [c["workload"] for c in prov["corpora"]] == ["agentx-mvp-uncapped", "agentx-mvp"]


def test_the_real_path_scores_a_full_commit(tmp_path):
    p, out, log, commit, head, _ = run_real(tmp_path, lambda c: c)
    assert p.returncode == 0, p.stderr
    prov = json.loads((out / "provenance.json").read_text())
    assert prov["simulator"]["build"] == commit and prov["experimental"] is True


def test_the_real_path_refuses_a_corpus_that_is_not_the_catalog_entrys(tmp_path):
    bare, commit, bin_, log, pull, units, fields, cat, reg = real_setup(tmp_path)
    (tmp_path / "corpora" / "agentx-mvp" / "traces.jsonl").write_bytes(b"other\n")
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "FAKE_FIELDS": str(fields)}
    run_sh, _ = harness_checkout(tmp_path)
    p = subprocess.run(["bash", str(run_sh), "--sim", "v0.16.0", "--sim-repo", str(bare), "--units", str(units),
                        "--pull", str(pull), "--out", str(tmp_path / "out"), "--catalog", str(cat),
                        "--registry", str(reg), "--corpus-dir", str(tmp_path / "corpora"),
                        "--fields", str(fields), "--catalog-release", "v0.3.0", "--registry-release", "v0.2.0"],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 2
    assert "mismatch" in p.stderr


def test_a_checkout_whose_harness_files_differ_from_its_commit_is_refused(tmp_path):
    # X8: a figure names the commit that produced it, so a tree with edits cannot score.
    bare, commit, bin_, log, pull, units, fields, cat, reg = real_setup(tmp_path)
    run_sh, head = harness_checkout(tmp_path)
    (run_sh.parent.parent / "orchestrator" / "ingest" / "cli.py").write_text("# edited\n")
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "FAKE_FIELDS": str(fields)}
    env.pop("HARNESS_COMMIT", None)
    p = subprocess.run(["bash", str(run_sh), "--sim", "v0.16.0", "--sim-repo", str(bare), "--units", str(units),
                        "--pull", str(pull), "--out", str(tmp_path / "out"), "--catalog", str(cat),
                        "--registry", str(reg), "--corpus-dir", str(tmp_path / "corpora"),
                        "--fields", str(fields), "--catalog-release", "v0.3.0", "--registry-release", "v0.2.0"],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 2 and "differ from its commit" in p.stderr and head in p.stderr
    assert not (tmp_path / "out").exists()


def test_an_untracked_file_in_a_script_directory_is_refused(tmp_path):
    # A new module under orchestrator/ingest changes the figures but is not in the commit.
    bare, commit, bin_, log, pull, units, fields, cat, reg = real_setup(tmp_path)
    run_sh, head = harness_checkout(tmp_path)
    (run_sh.parent.parent / "orchestrator" / "ingest" / "shadow.py").write_text("x = 1\n")
    env = {k: v for k, v in os.environ.items() if k != "HARNESS_COMMIT"}
    env.update({"PATH": f"{bin_}:{os.environ['PATH']}", "FAKE_FIELDS": str(fields)})
    p = subprocess.run(["bash", str(run_sh), "--sim", "v0.16.0", "--sim-repo", str(bare), "--units", str(units),
                        "--pull", str(pull), "--out", str(tmp_path / "out"), "--catalog", str(cat),
                        "--registry", str(reg), "--corpus-dir", str(tmp_path / "corpora"),
                        "--fields", str(fields), "--catalog-release", "v0.3.0", "--registry-release", "v0.2.0"],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 2 and "differ from its commit" in p.stderr and not (tmp_path / "out").exists()


def test_a_copy_unpacked_inside_another_repository_does_not_record_that_repositorys_commit(tmp_path):
    outer = tmp_path / "outer"
    outer.mkdir()
    git("init", "-q", cwd=outer)
    (outer / "f").write_text("x")
    git("add", ".", cwd=outer)
    git("commit", "-q", "-m", "outer", cwd=outer)
    outer_head = git("rev-parse", "HEAD", cwd=outer)
    inner = outer / "unpacked"
    inner.mkdir()
    run_sh, _ = harness_checkout(inner, git_history=False)       # no .git of its own
    assert git("rev-parse", "--show-toplevel", cwd=run_sh.parent) == str(outer.resolve())
    (tmp_path / "w").mkdir()
    bare, commit, bin_, log, pull, units, fields, cat, reg = real_setup(tmp_path / "w")
    env = {k: v for k, v in os.environ.items() if k != "HARNESS_COMMIT"}
    env.update({"PATH": f"{bin_}:{os.environ['PATH']}", "FAKE_FIELDS": str(fields)})
    p = subprocess.run(["bash", str(run_sh), "--sim", "v0.16.0", "--sim-repo", str(bare), "--units", str(units),
                        "--pull", str(pull), "--out", str(tmp_path / "out"), "--catalog", str(cat),
                        "--registry", str(reg), "--corpus-dir", str(tmp_path / "w" / "corpora"),
                        "--fields", str(fields), "--catalog-release", "v0.3.0", "--registry-release", "v0.2.0"],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 2 and "HARNESS_COMMIT is not set" in p.stderr, p.stderr
    assert outer_head not in p.stderr


def test_a_tree_without_history_names_its_commit_in_the_environment(tmp_path):
    named = "d" * 40
    (tmp_path / "a").mkdir()
    p, out, log, commit, head, _ = run_real(tmp_path / "a", lambda c: "v0.16.0", history=False, env_extra={"HARNESS_COMMIT": named})
    assert p.returncode == 0, p.stderr
    assert json.loads((out / "provenance.json").read_text())["harness_commit"] == named
    # With no history and no name there is no commit to record: refused, nothing scored.
    (tmp_path / "b").mkdir()
    p, out, *_ = run_real(tmp_path / "b", lambda c: "v0.16.0", history=False)
    assert p.returncode == 2 and "HARNESS_COMMIT is not set" in p.stderr and not out.exists()


def test_a_commit_named_in_the_environment_must_be_the_checkouts_head(tmp_path):
    p, out, *_ = run_real(tmp_path, lambda c: "v0.16.0", env_extra={"HARNESS_COMMIT": "e" * 40})
    assert p.returncode == 2 and "is not the checkout's HEAD" in p.stderr and not out.exists()


def test_the_real_path_scores_a_pre_release_tag_and_marks_its_figures_experimental(tmp_path):
    p, out, log, commit, head, _ = run_real(tmp_path, lambda c: "v0.16.0-rc1", tag="v0.16.0-rc1")
    assert p.returncode == 0, p.stderr
    prov = json.loads((out / "provenance.json").read_text())
    assert prov["simulator"]["build"] == "v0.16.0-rc1" and prov["experimental"] is True


def test_data_pinned_by_commit_is_recorded_as_given_and_marks_the_figures_experimental(tmp_path):
    cat, reg = "c" * 40, "e" * 40
    p, out, *_ = run_real(tmp_path, lambda c: "v0.16.0", releases=(cat, reg))
    assert p.returncode == 0, p.stderr
    prov = json.loads((out / "provenance.json").read_text())
    assert prov["blis"]["catalog"] == cat and prov["blis"]["registry"] == reg
    assert prov["simulator"]["build"] == "v0.16.0" and prov["experimental"] is True
    # tags for the data and a tag for the build: not experimental, as before
    (tmp_path / "t").mkdir()
    p, out, *_ = run_real(tmp_path / "t", lambda c: "v0.16.0")
    assert p.returncode == 0, p.stderr
    assert json.loads((out / "provenance.json").read_text())["experimental"] is False


# ------------------------------------------------------------------ pinned workflows

def test_every_action_of_every_workflow_is_pinned_to_a_commit_with_its_version_in_a_comment():
    assert len(WORKFLOWS) >= 3
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
