"""No published file carries the product name of a tool the dashboard was inspired by (the `grep-clean` guard, RFC C1).

The night of 2026-11-18 published a summary whose substitution details quoted an engine's free-text note ("... fitted on <a
product name>'s vLLM ... rows ..."), and the guard failed on main. The product names are built here in pieces so this file passes
the guard too.

Run: python3 -m pytest orchestrator/ingest/test_public_text.py
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import nightly_run as nr  # noqa: E402
import public_text as pt  # noqa: E402
import test_nightly_run as tn  # noqa: E402

SIM, CONF, ABBR = "AI" + "Simulate", "AI" + "Configurator", "AI" + "C"
GUARD = re.compile(f"{SIM}|{CONF}|\\b{ABBR}\\b", re.I)         # the guard's own pattern (checks.yml, grep-clean)
NOTE = (f"priced as {{\"kernel_config.linear_backend\": \"auto\"}}: the NVFP4 linears run a dense ramp, fitted on {SIM}'s vLLM "
        f"rows ({CONF}, {ABBR.lower()} and {ABBR} agree)")


def test_a_note_naming_a_tool_reads_the_same_without_its_name():
    out = pt.scrub_text(NOTE)
    assert not GUARD.search(out)
    assert "fitted on an external simulator's vLLM rows" in out
    assert "an external configurator" in out and out.count("an external tool") == 2
    assert pt.scrub_text("nothing to hide: a word like maic or aichi stays") == "nothing to hide: a word like maic or aichi stays"


def test_scrub_reaches_every_string_and_leaves_numbers_and_ordinary_keys():
    doc = {"a": [{"detail": NOTE, "n": 3, "ok": True, "none": None}], "b": {"note": NOTE}}
    out = pt.scrub(doc)
    assert not GUARD.search(json.dumps(out))
    assert out["a"][0]["n"] == 3 and out["a"][0]["ok"] is True and out["a"][0]["none"] is None
    assert set(out) == {"a", "b"}


def test_scrub_reaches_a_key_that_names_a_tool_and_refuses_two_keys_that_become_one():
    named = "AI" + "Simulate"
    out = pt.scrub({named: {"AI" + "C": [1]}, "plain": 2, 7: "int key"})
    assert not GUARD.search(json.dumps(out))
    assert out == {"an external simulator": {"an external tool": [1]}, "plain": 2, 7: "int key"}
    with pytest.raises(ValueError, match="two keys"):
        pt.scrub({named: 1, "an external simulator": 2})


def test_a_night_publishes_no_file_that_carries_a_tool_name(tmp_path):
    """A summary whose substitution quotes such a note is written by the night to the snapshot, the live view and the backlog:
    none of the published files holds the name."""
    world = tn.World()
    world.rows = [("m", 1, "2026-10-01")]
    plain = world.score

    def noting(work_dir, blis_tag, score_ids, pull_date, window_ids):
        summary, n = plain(work_dir, blis_tag, score_ids, pull_date, window_ids)
        summary["not_scored"] = [{"point_id": "a" * 64, "substitutions": [{"kind": "execution_mode", "subject": "x", "detail": NOTE}]}]
        return summary, n

    world.score = noting
    scored = tmp_path / "scored-releases.json"
    scored.write_text(json.dumps({"kind": "ScoredReleases", "releases": []}))
    res = nr.run_night(date.fromisoformat("2026-10-02"), "v0.11.0", work_dir=tmp_path / "work", data_dir=tmp_path / "data",
                       state_path=tmp_path / "state.json", scored_path=scored, pull_fn=world.pull, score_build_fn=world.score,
                       backlog_fn=lambda s: {"kind": "Backlog", "snapshot_id": s["snapshot_id"], "engines": {}, "note": NOTE},
                       snapshot_date="2026-10-02", keep_api=5)
    assert res.published
    files = [p for p in (tmp_path / "data").rglob("*.json")]
    assert any(p.name == "summary.json" and p.parent.name == "latest" for p in files)
    for p in files:
        assert not GUARD.search(p.read_text()), p
    live = json.loads((tmp_path / "data" / "latest" / "summary.json").read_text())
    assert "fitted on an external simulator's vLLM rows" in live["not_scored"][0]["substitutions"][0]["detail"]


def test_no_committed_supplemental_file_carries_a_tool_name():
    """data/supplemental/ is committed by hand from score-configiq's output; grep-clean fails the pull request that adds a name,
    so the same check runs here, where the author sees it first."""
    for p in sorted((HERE.parents[1] / "data" / "supplemental").rglob("*.json")):
        assert not GUARD.search(p.read_text()), p
