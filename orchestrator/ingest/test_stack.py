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
        "substrate_commit": SUBSTRATE_COMMIT, "substrate_ref": SUBSTRATE_COMMIT,
        "substrate_version": "v0.0.0-20261105035832-817e83e0018b",
        "vllm_module_commit": VLLM_COMMIT, "vllm_module_ref": VLLM_COMMIT, "vllm_ref": "v0.32.0"}


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
    with pytest.raises(sk.StackError, match="want 40 hex digits"):      # a pseudo-version needs its commit
        sk.pins(sk.parse(json.dumps(bad)))


def test_a_release_names_no_commit_and_the_pins_are_its_tags():
    # inference-sim's stack.json for a release lists each BLIS module by its tag and no commit
    # (LIF-1: a tag names its commit); the pins are the tags to fetch.
    doc = {"kind": "Stack", "toolchain": "go1.27.2",
           "modules": [{"path": sk.SUBSTRATE, "version": "v0.13.0"},
                       {"path": sk.VLLM_MODULE, "version": "v0.32.0-blis.2"}],
           "engines": [{"kind": "vllm", "version": "0.32.0", "commit": "5df63a7203cdb9328d824a27b682e77c7b9928be"}]}
    assert sk.pins(sk.parse(json.dumps(doc))) == {
        "substrate_commit": "", "substrate_ref": "v0.13.0", "substrate_version": "v0.13.0",
        "vllm_module_commit": "", "vllm_module_ref": "v0.32.0-blis.2", "vllm_ref": "v0.32.0"}



@pytest.mark.parametrize("version,name", [
    ("v1.2.3", "v1.2.3"), ("v1.2.3-rc1", "v1.2.3-rc1"), ("v1.2.3-rc.1", "v1.2.3-rc.1"),
    ("v0.0.0-20261105035832-817e83e0018b", None),
    ("v1.0.0-blis.2.0.20261105040605-fd1830412b30", None),
    ("v0.32.1-0.20261105040818-a8bf6ee4fca6", None),
    ("1.2.3", None), ("v1.2", None), ("", None)])
def test_a_release_name_is_a_release_tag_and_not_a_pseudo_version(version, name):
    assert sk.release_name({"path": "p", "version": version, "commit": "c"}) == name


def _repo_with_tag(path):
    def git(*a):
        subprocess.run(["git", "-C", str(path), "-c", "user.email=t@t", "-c", "user.name=t", *a],
                       check=True, capture_output=True)
    path.mkdir()
    git("init", "-q")
    git("commit", "-q", "--allow-empty", "-m", "one")
    git("tag", "v1.0.0")
    git("commit", "-q", "--allow-empty", "-m", "two")
    rev = lambda ref: subprocess.run(["git", "-C", str(path), "rev-parse", ref], capture_output=True,  # noqa: E731
                                     text=True).stdout.strip()
    return git, rev("v1.0.0"), rev("HEAD")


def test_a_checkout_at_the_tags_commit_that_stack_json_pins_has_no_problems(tmp_path):
    git, tagged, _ = _repo_with_tag(tmp_path / "r")
    git("checkout", "-q", "v1.0.0")
    assert sk.verify_checkout(tmp_path / "r", "v1.0.0", tagged) == []


def test_a_checkout_not_at_the_tags_commit_is_refused_naming_both(tmp_path):
    _, tagged, head = _repo_with_tag(tmp_path / "r")
    problems = sk.verify_checkout(tmp_path / "r", "v1.0.0", head)
    assert len(problems) == 2 and all(tagged in p or head in p for p in problems)
    assert any(head in p and tagged in p and "v1.0.0" in p for p in problems)


def test_a_tag_that_does_not_exist_or_a_commit_stack_json_does_not_pin_is_refused(tmp_path):
    git, tagged, head = _repo_with_tag(tmp_path / "r")
    assert sk.verify_checkout(tmp_path / "r", "v9.9.9", head) == [f"{tmp_path / 'r'}: tag v9.9.9 does not exist"]
    git("checkout", "-q", "v1.0.0")
    problems = sk.verify_checkout(tmp_path / "r", "v1.0.0", head)
    assert problems == [f"tag v1.0.0 is commit {tagged}, but stack.json pins {head}"]


COMMIT = "b6748ca9d757f149ba760cf821f96feed3bbf5bf"


@pytest.mark.parametrize("version,commit,pin,fragment", [
    ("v0.15.0", "", "v0.15.0", None),                                              # a tag pins by its name
    ("v0.15.1-0.20261118162118-b6748ca9d757", COMMIT, COMMIT, None),               # a pseudo-version pins by its commit
    (COMMIT, COMMIT, COMMIT, None),                                                # the version is the commit itself
    ("v0.15.1-0.20261118162118-b6748ca9d757", "", None, "pins no full 40-hex commit"),
    ("v0.15.1-0.20261118162118-b6748ca9d757", COMMIT[:12], None, "pins no full 40-hex commit"),
    ("v0.15.1-0.20261118162118-aaaaaaaaaaaa", COMMIT, None, "names the commit aaaaaaaaaaaa"),   # another commit
    ("main", COMMIT, None, "neither a release tag, a pseudo-version nor the pinned commit"),
])
def test_an_exact_pin_is_a_tag_or_the_full_commit_a_pseudo_version_names(version, commit, pin, fragment):
    got, problems = sk.pin_of(version, commit)
    assert got == pin
    assert (not problems) if fragment is None else any(fragment in x for x in problems)


def test_a_checkout_is_exactly_the_commit_pin_or_it_is_refused(tmp_path):
    _, tagged, head = _repo_with_tag(tmp_path / "r")
    assert sk.verify_checkout(tmp_path / "r", head, head) == []            # at the pinned commit, no tag needed
    assert sk.verify_checkout(tmp_path / "r", head, "") == []
    problems = sk.verify_checkout(tmp_path / "r", tagged, tagged)          # HEAD is the later commit
    assert problems == [f"{tmp_path / 'r'} is at {head}, but the pin is commit {tagged}"]
    assert sk.verify_checkout(tmp_path / "r", head, tagged) == [f"the pin is commit {head}, but stack.json pins {tagged}"]


def test_resolve_stack_prints_the_pins_for_a_checkout_and_fails_without_a_stack(tmp_path):
    script = ROOT / "resolve_stack.py"
    (tmp_path / "stack.json").write_bytes(SUBSTRATE_STACK.read_bytes())
    r = subprocess.run([sys.executable, str(script), str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [f"substrate_commit={SUBSTRATE_COMMIT}", f"substrate_ref={SUBSTRATE_COMMIT}",
                                     "substrate_version=v0.0.0-20261105035832-817e83e0018b",
                                     f"vllm_module_commit={VLLM_COMMIT}", f"vllm_module_ref={VLLM_COMMIT}",
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
    assert '--substrate-version "$substrate_version" --substrate-commit "$substrate_commit"' in text
    for gone in ("resolve_versions", "installation.md", "go doc", "blis-catalog", "blis-registry", "go.mod"):
        assert gone not in text.replace("# ", ""), gone
    assert not (ROOT / "resolve_versions.sh").exists()


def test_a_release_whose_substrate_publishes_no_anchor_list_gives_way_to_its_patch_release():
    # v0.16.0 and v0.17.0 pin substrates with no anchor list, so they can never be scored. Once
    # v0.17.1 is tagged, the night scores it and skips them, and never records them as scored.
    tags = ["v0.15.0", "v0.16.0", "v0.17.0", "v0.17.1"]
    assert sk.unscored_releases(tags, {"v0.15.0"}, "v0.16.0") == ["v0.17.1"]
    # Before the patch release exists nothing is skipped, so the gap stays visible.
    assert sk.unscored_releases(tags[:3], {"v0.15.0"}, "v0.16.0") == ["v0.16.0", "v0.17.0"]
    # A release not in the table is never skipped.
    assert sk.unscored_releases(tags, {"v0.15.0"}, "v0.16.0", superseded={}) == ["v0.16.0", "v0.17.0", "v0.17.1"]


# ------------------------------------------------------------------ a simulator commit whose stack embeds the substrate
EMBEDDED = {**DOC, "modules": [{"path": "github.com/inference-sim/llm-d-router", "version": "v1.0.0-blis.5.0.20261121014725-cb8d93fcb0fa",
                                "commit": "c" * 40}],
            "engines": [{"kind": "vllm", "version": "0.34.0+0fda86a35419", "commit": "0fda86a35419" + "0" * 28}]}


def test_an_engine_that_is_a_build_after_a_release_is_measured_from_its_commit():
    s = sk.parse(json.dumps(EMBEDDED))
    assert sk.vllm_ref(s) == "0fda86a35419" + "0" * 28
    assert sk.vllm_ref(sk.parse(json.dumps(DOC))) == "v0.32.0"
    no_commit = {**EMBEDDED, "engines": [{"kind": "vllm", "version": "0.34.0+0fda86a35419"}]}
    with pytest.raises(sk.StackError, match="names no 40-hex commit"):
        sk.vllm_ref(sk.parse(json.dumps(no_commit)))


def test_the_commit_of_a_checkout_pins_the_substrate_it_holds_and_a_stack_that_lists_the_module_is_refused():
    s = sk.parse(json.dumps(EMBEDDED))
    pins = sk.embedded_pins(s, "a" * 40)
    assert pins == {"substrate_embedded": "true", "substrate_ref": "a" * 40, "substrate_commit": "a" * 40,
                    "substrate_version": "a" * 40, "vllm_ref": "0fda86a35419" + "0" * 28}
    assert sk.pin_of(pins["substrate_version"], pins["substrate_commit"]) == ("a" * 40, [])
    with pytest.raises(sk.StackError, match="not a full 40-hex commit"):
        sk.embedded_pins(s, "abc123")
    with pytest.raises(sk.StackError, match="fetched from it"):
        sk.embedded_pins(sk.parse(json.dumps(DOC)), "a" * 40)


def test_only_a_stable_tag_is_a_release_the_list_may_hold(tmp_path):
    assert sk.is_stable_tag("v0.18.1") and not sk.is_stable_tag("a" * 40) and not sk.is_stable_tag("v0.18.1-rc1")
    lst = tmp_path / "s.json"
    lst.write_text(json.dumps({"kind": "ScoredReleases", "releases": []}))
    with pytest.raises(sk.StackError, match="stable release tag"):
        sk.record_scored(lst, "a" * 40)


def test_resolve_stack_reads_the_substrate_a_checkout_holds_itself(tmp_path):
    (tmp_path / "stack.json").write_text(json.dumps(EMBEDDED))
    (tmp_path / "substrate" / "catalog").mkdir(parents=True)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(git + ["init", "-q"], check=True)
    subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "x"], check=True)
    head = subprocess.run(git + ["rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    r = subprocess.run([sys.executable, str(ROOT / "resolve_stack.py"), str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["substrate_embedded=true", f"substrate_ref={head}", f"substrate_commit={head}",
                                     f"substrate_version={head}", "vllm_ref=0fda86a35419" + "0" * 28]
    assert sk.verify_checkout(tmp_path / "substrate", head, head) == []


def test_a_preview_run_names_its_commit_and_neither_deploys_nor_chains():
    import yaml
    text = (ROOT.parent / ".github" / "workflows" / "api-nightly.yml").read_text()
    doc = yaml.safe_load(text)
    inp = doc[True]["workflow_dispatch"]["inputs"]["sim_commit"]
    assert inp["default"] == ""                                   # the schedule and a normal dispatch are unchanged
    assert "^[0-9a-f]{40}$" in text and "FETCH_HEAD" in text
    steps = {s.get("name"): s for s in doc["jobs"]["publish"]["steps"]}
    for name in ("Deploy the published data to Pages", "Score the next unscored release"):
        assert "inputs.sim_commit == ''" in steps[name]["if"], name
