"""Tests for the scoring harness's entrypoint (run.sh) and its release workflow.

run.sh's flags are checked with --check-args, which validates and exits without cloning or
building, so these tests need no network. The workflow is checked as YAML.
"""
from __future__ import annotations

import os
import re
import subprocess
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
