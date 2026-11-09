"""The nightly scores through the harness image named by harness/image.pin (design §11.7, X8).

The pin file holds `unpublished` until an image is released: then the pin handling and the
nightly's step fail (X16). With a digest, the step builds the `docker run` with HARNESS_DIGEST
set from the pin and the data mounted, after `cosign verify`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "orchestrator" / "ingest"))
import harness_pin as hp  # noqa: E402

IMAGE = hp.IMAGE
GOOD = f"{IMAGE}@sha256:{'c' * 64}"
WORKFLOW = ROOT / ".github" / "workflows" / "api-nightly.yml"
PIN = HERE / "image.pin"


def pin(tmp_path, text):
    p = tmp_path / "image.pin"
    p.write_text(text)
    return p


def test_the_committed_pin_is_unpublished_until_an_image_is_released():
    assert PIN.read_text().strip() == "unpublished"


def test_an_unpublished_pin_fails_and_says_so(tmp_path):
    with pytest.raises(hp.PinError, match="unpublished: no harness image has been released.*not run from the source tree"):
        hp.read(pin(tmp_path, "unpublished\n"))


@pytest.mark.parametrize("text", [
    f"{IMAGE}@sha256:{'c' * 63}\n",           # short digest
    f"{IMAGE}@sha256:{'C' * 64}\n",           # not lower case
    f"{IMAGE}:v0.4.0\n",                      # a tag, which moves
    f"other.io/x@sha256:{'c' * 64}\n",        # another image
    "\n",                                     # empty
    f"{GOOD}\n{GOOD}\n",                      # two lines
])
def test_a_bad_pin_fails(tmp_path, text):
    with pytest.raises(hp.PinError):
        hp.read(pin(tmp_path, text))


def test_a_good_digest_is_read_and_builds_the_docker_command(tmp_path):
    assert hp.read(pin(tmp_path, GOOD + "\n")) == GOOD
    cmd = hp.docker_command(GOOD, sim="v0.16.0", units=tmp_path / "u.json", pull=tmp_path / "p",
                            out=tmp_path / "o", catalog=tmp_path / "c", registry=tmp_path / "r",
                            corpus_dir=tmp_path / "k", fields=tmp_path / "f.json", catalog_release="v0.3.0",
                            registry_release="v0.2.0", max_rss_mb=13000)
    assert cmd[:3] == ["docker", "run", "--rm"]
    assert f"HARNESS_DIGEST=sha256:{'c' * 64}" in cmd
    i = cmd.index(GOOD)
    assert cmd[i + 1:] == ["--sim", "v0.16.0", "--units", "/data/units.json", "--pull", "/data/pull",
                           "--out", "/data/out", "--catalog", "/data/catalog", "--registry", "/data/registry",
                           "--corpus-dir", "/data/corpora", "--fields", "/data/fields.json",
                           "--catalog-release", "v0.3.0",
                           "--registry-release", "v0.2.0", "--max-rss-mb", "13000"]
    mounts = [cmd[j + 1] for j, v in enumerate(cmd[:i]) if v == "-v"]
    assert f"{(tmp_path / 'u.json').resolve()}:/data/units.json:ro" in mounts
    assert f"{(tmp_path / 'o').resolve()}:/data/out" in mounts          # the output is writable
    assert f"{(tmp_path / 'k').resolve()}:/data/corpora:ro" in mounts   # the corpora are read-only
    assert f"{(tmp_path / 'f.json').resolve()}:/data/fields.json:ro" in mounts   # so is the field list
    assert len(mounts) == 7


def test_every_flag_of_the_command_is_one_run_sh_accepts(tmp_path):
    (tmp_path / "f.json").write_text("{}")
    cmd = hp.docker_command(GOOD, sim="v0.16.0", units="u", pull="p", out="o", catalog="c", registry="r",
                            corpus_dir="k", fields=str(tmp_path / "f.json"), catalog_release="v1",
                            registry_release="v1", max_rss_mb=1)
    flags = cmd[cmd.index(GOOD) + 1:]
    flags = [str(tmp_path / "f.json") if f == "/data/fields.json" else f for f in flags]
    p = subprocess.run(["bash", str(HERE / "run.sh"), "--check-args", *flags], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


def test_the_cli_prints_the_reference_or_fails(tmp_path):
    run = lambda f: subprocess.run([sys.executable, str(ROOT / "orchestrator/ingest/harness_pin.py"), "check", str(f)],  # noqa: E731
                                   capture_output=True, text=True)
    ok = run(pin(tmp_path, GOOD + "\n"))
    assert (ok.returncode, ok.stdout.strip()) == (0, GOOD)
    bad = run(pin(tmp_path, "unpublished\n"))
    assert bad.returncode == 1 and "unpublished" in bad.stderr and bad.stdout == ""


# ------------------------------------------------------------------ the nightly workflow

def steps():
    doc = yaml.safe_load(WORKFLOW.read_text())
    return doc["jobs"]["run-night"]["steps"]


def test_the_nightly_verifies_the_pinned_image_before_it_scores():
    st = steps()
    names = [s.get("name", "") for s in st]
    i, j = names.index("Pin and verify the harness image"), names.index("Score the release")
    assert i < j
    assert any("cosign-installer" in s.get("uses", "") for s in st[:j])
    run = st[i]["run"]
    assert "harness_pin.py check harness/image.pin" in run
    assert "cosign verify" in run and "harness-release\\.yml@refs/(tags/v[0-9].*|heads/main)" in run
    assert "token.actions.githubusercontent.com" in run
    assert run.index("harness_pin.py") < run.index("cosign verify") < run.index("docker pull")


def test_the_nightly_scores_through_the_image_and_not_the_source_tree():
    score = next(s for s in steps() if s.get("name") == "Score the release")["run"]
    assert '--harness-image "$HARNESS_IMAGE"' in score


def test_the_cosign_identity_is_the_one_the_release_workflow_verifies_with():
    def identity(path):
        import re
        return re.search(r"--certificate-identity-regexp '([^']*)'", path.read_text()).group(1)
    assert identity(WORKFLOW) == identity(ROOT / ".github" / "workflows" / "harness-release.yml")
