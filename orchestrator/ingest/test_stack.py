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


def test_the_published_releases_are_read_from_the_snapshot_names():
    names = ["2026-10-19_blis-v0.10.0_ix-2026-09-28", "2026-10-31_blis-v0.15.0_ix-api-2026-10-31", "README"]
    assert sk.published_releases(names) == {"v0.10.0", "v0.15.0"}


def test_the_command_lists_every_unscored_stable_release_from_v0_16_0_oldest_first(tmp_path, capsys):
    tags = tmp_path / "tags.txt"
    tags.write_text("v0.15.0\nv0.16.0-rc1\nv0.16.0\nv0.17.0\n")
    snaps = tmp_path / "data" / "snapshots"
    (snaps / "2026-10-31_blis-v0.15.0_ix-api-2026-10-31").mkdir(parents=True)
    assert sk.main(["--tags", str(tags), "--data-dir", str(tmp_path / "data")]) == 0
    assert capsys.readouterr().out.split() == ["v0.16.0", "v0.17.0"]
    (snaps / "2026-11-10_blis-v0.16.0_ix-api-2026-11-10").mkdir()
    sk.main(["--tags", str(tags), "--data-dir", str(tmp_path / "data")])
    assert capsys.readouterr().out.split() == ["v0.17.0"]
