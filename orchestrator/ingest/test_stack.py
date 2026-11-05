"""stack.json is read strictly (SUB-12), names one release of each engine (LIF-6), and each
simulator release is scored once (COV-9).

Run: python3 -m pytest orchestrator/ingest/test_stack.py
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stack as sk  # noqa: E402

DOC = {"kind": "Stack", "toolchain": "go1.27.2",
       "modules": [{"path": "github.com/inference-sim/blis-substrate", "version": "v0.0.0-x",
                    "commit": "8" * 40}],
       "engines": [{"kind": "vllm", "version": "0.32.0", "commit": "5" * 40}],
       "router": {"kind": "llm-d", "version": "1.0.0", "commit": "b" * 40}, "guides_commit": "4" * 40}


def test_the_engine_release_comes_from_stack_json():
    s = sk.parse(json.dumps(DOC))
    assert s.engine("vllm") == "0.32.0"
    with pytest.raises(sk.StackError, match="no 'sglang' engine"):
        s.engine("sglang")


def test_stack_json_with_an_unknown_key_or_two_releases_of_one_engine_is_refused():
    with pytest.raises(sk.StackError, match="unknown key"):
        sk.parse(json.dumps({**DOC, "blis_catalog": "0.3.0"}))
    with pytest.raises(sk.StackError, match="LIF-6"):
        sk.parse(json.dumps({**DOC, "engines": DOC["engines"] * 2}))


def test_every_unscored_release_from_the_first_on_is_scored_once_in_tag_order():
    tags = ["v0.14.0", "v0.15.0", "v0.16.0-rc1", "v0.16.0", "v0.17.0", "v0.16.1"]
    assert sk.unscored_releases(tags, set(), "v0.16.0") == ["v0.16.0", "v0.17.0", "v0.16.1"]
    assert sk.unscored_releases(tags, {"v0.16.0"}, "v0.16.0") == ["v0.17.0", "v0.16.1"]
    assert sk.unscored_releases(tags, {"v0.16.0", "v0.17.0", "v0.16.1"}, "v0.16.0") == []
    # Before the first release to score is tagged, there is nothing to score.
    assert sk.unscored_releases(["v0.14.0", "v0.15.0"], set(), "v0.16.0") == []
    with pytest.raises(sk.StackError):
        sk.unscored_releases(tags, set(), "0.16")


def _scored(tmp_path, releases):
    p = tmp_path / "scored-releases.json"
    p.write_text(json.dumps({"kind": "ScoredReleases", "releases": releases}))
    return p


def test_a_release_is_recorded_once_and_the_list_only_grows(tmp_path):
    p = _scored(tmp_path, ["v0.15.0"])
    assert sk.record_scored(p, "v0.16.0") is True
    assert sk.record_scored(p, "v0.16.0") is False
    assert sk.read_scored(p) == ["v0.15.0", "v0.16.0"]
    with pytest.raises(sk.StackError, match="not a stable release tag"):
        sk.record_scored(p, "v0.17.0-rc1")


def test_the_list_is_read_strictly_and_a_missing_one_is_an_error_not_an_empty_list(tmp_path):
    with pytest.raises(sk.StackError, match="scored-releases.json"):
        sk.read_scored(tmp_path / "scored-releases.json")
    for doc in ('{"kind": "ScoredReleases"}', '{"kind": "Other", "releases": []}', '[]', 'x',
                '{"kind": "ScoredReleases", "releases": ["main"]}',
                '{"kind": "ScoredReleases", "releases": ["v0.15.0", "v0.15.0"]}'):
        (tmp_path / "bad.json").write_text(doc)
        with pytest.raises(sk.StackError):
            sk.read_scored(tmp_path / "bad.json")


def test_the_command_lists_every_unscored_stable_release_from_v0_16_0_oldest_first(tmp_path, capsys):
    tags = tmp_path / "tags.txt"
    tags.write_text("v0.15.0\nv0.16.0-rc1\nv0.16.0\nv0.17.0\n")
    scored = _scored(tmp_path, ["v0.15.0"])
    assert sk.main(["--tags", str(tags), "--scored", str(scored)]) == 0
    assert capsys.readouterr().out.split() == ["v0.16.0", "v0.17.0"]
    sk.record_scored(scored, "v0.16.0")
    sk.main(["--tags", str(tags), "--scored", str(scored)])
    assert capsys.readouterr().out.split() == ["v0.17.0"]
    assert sk.main(["--tags", str(tags), "--scored", str(tmp_path / "none.json")]) == 1


def test_the_committed_list_holds_every_release_with_a_published_snapshot():
    # Seeded from data/snapshots and data/index.json (v0.10.0 to v0.15.0).
    import re
    data = ROOT.parent / "data"
    in_dirs = {re.match(r"^\d{4}-\d{2}-\d{2}_blis-(v[^_]+)_", p.name).group(1) for p in (data / "snapshots").iterdir()}
    in_index = {r["blis_release"] for r in json.loads((data / "index.json").read_text())["runs"]}
    assert in_dirs == in_index
    assert set(sk.read_scored(ROOT.parent / "state" / "scored-releases.json")) >= in_dirs


# ------------------------------------------------------------------ what a release is scored with

import subprocess  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# inference-sim's stack.json at upstream/m1/substrate (testdata/stack.json is a copy).
SUBSTRATE_STACK = Path(__file__).resolve().parent / "testdata" / "stack.json"
SUBSTRATE_COMMIT = "817e83e0018b98e8042d2e76531fa95b60807068"
VLLM_COMMIT = "a8bf6ee4fca6d019c98b369be10b5ea044033159"


def test_the_pins_come_from_stack_json_modules_and_engines():
    assert sk.pins(sk.load(SUBSTRATE_STACK)) == {
        "substrate_commit": SUBSTRATE_COMMIT, "vllm_module_commit": VLLM_COMMIT, "vllm_ref": "v0.32.0"}


def test_the_vllm_ref_follows_the_engine_release_with_no_code_change():
    doc = json.loads(SUBSTRATE_STACK.read_text())
    doc["engines"][0]["version"] = "0.33.1"
    assert sk.pins(sk.parse(json.dumps(doc)))["vllm_ref"] == "v0.33.1"


def test_a_stack_without_the_substrate_or_blis_vllm_module_or_a_commit_is_refused():
    doc = json.loads(SUBSTRATE_STACK.read_text())
    for path in (sk.SUBSTRATE, sk.VLLM_MODULE):
        bad = {**doc, "modules": [m for m in doc["modules"] if m["path"] != path]}
        with pytest.raises(sk.StackError, match=f"lists no module {path}"):
            sk.pins(sk.parse(json.dumps(bad)))
    bad = json.loads(json.dumps(doc))
    bad["modules"][0]["commit"] = "v0.0.0-2026"
    with pytest.raises(sk.StackError, match="want 40 hex digits"):
        sk.pins(sk.parse(json.dumps(bad)))
    bad["modules"][0].pop("commit")
    with pytest.raises(sk.StackError, match="want 40 hex digits"):
        sk.pins(sk.parse(json.dumps(bad)))


def test_resolve_stack_prints_the_pins_for_a_checkout_and_fails_without_a_stack(tmp_path):
    script = ROOT / "resolve_stack.py"
    (tmp_path / "stack.json").write_bytes(SUBSTRATE_STACK.read_bytes())
    r = subprocess.run([sys.executable, str(script), str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [f"substrate_commit={SUBSTRATE_COMMIT}", f"vllm_module_commit={VLLM_COMMIT}",
                                     "vllm_ref=v0.32.0"]
    empty = tmp_path / "empty"
    empty.mkdir()
    r = subprocess.run([sys.executable, str(script), str(empty)], capture_output=True, text=True)
    assert r.returncode == 1 and "FATAL" in r.stderr and "stack.json" in r.stderr


def test_the_nightly_resolves_through_stack_json_and_not_through_installation_md():
    import yaml
    text = (ROOT.parent / ".github" / "workflows" / "api-nightly.yml").read_text()
    yaml.safe_load(text)
    assert "resolve_stack.py" in text and 'VLLM_REF="$vllm_ref"' in text
    for gone in ("resolve_versions", "installation.md", "go doc", "blis-catalog", "blis-registry", "go.mod"):
        assert gone not in text.replace("# ", ""), gone
    assert not (ROOT / "resolve_versions.sh").exists()
