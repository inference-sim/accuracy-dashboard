"""Tests of freeze_ledger.py: the frozen pull's shards, its budget, its archive and its replay."""
import json
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import freeze_ledger as fz  # noqa: E402
import pull as pl  # noqa: E402


def test_runs_split_into_shards_by_id_the_same_way_every_time():
    runs = [str(1000 + k) for k in range(200)]
    a = [fz.shard_of(r, 2) for r in runs]
    assert a == [fz.shard_of(r, 2) for r in runs] and set(a) == {0, 1}
    assert fz.shard_of(None, 2) == 0


def test_the_budget_waits_below_the_floor_and_after_the_hours_share():
    slept, state = [], {"remaining": 900, "reset": 1000}

    def rate(_):
        r = (state["remaining"], state["reset"])
        state["remaining"] = 5000                 # the reset came
        return r
    b = fz.Budget("t", per_hour=1500, floor=1000, sleep=slept.append, clock=lambda: 100.0, rate_fn=rate)
    b.before_batch(log=lambda *_: None)
    assert slept == [905.0]                       # waited for the reset, then went on
    slept.clear()
    b.hour_start, b.hour_left = 100.0, 5000 + 1500
    b2_calls = iter([(5000, 9999), (5000, 9999)])
    b.rate_fn = lambda _: next(b2_calls)
    b.clock = iter([100.0, 3800.0]).__next__
    b.before_batch(log=lambda *_: None)
    assert slept == [3600.0]                      # spent its hour's share: waited for the next hour


def _pull(d: Path, pids):
    pts = []
    for pid in pids:
        (d / "points" / pid).mkdir(parents=True)
        (d / "points" / pid / "server_log.gz").write_bytes(pid.encode())
        pts.append({"point_id": pid, "row": {"image": ""}, "files": {}, "reasons": [], "build": None})
    pl.write_manifest(d, {"pulled_at": "2026-11-17T00:00:00Z", "base_models": {"o/m": None}}, pts)
    (d / fz.LOOKUPS).write_text(json.dumps({"github": {pids[0]: 1}}))


def test_two_shards_merge_into_one_pull_and_a_point_in_both_is_refused(tmp_path):
    _pull(tmp_path / "a", ["p1", "p2"])
    _pull(tmp_path / "b", ["p3"])
    assert fz.merge([tmp_path / "a", tmp_path / "b"], tmp_path / "c") == 3
    m = json.loads((tmp_path / "c" / "manifest.json").read_text())
    assert [e["point_id"] for e in m["points"]] == ["p1", "p2", "p3"]
    assert json.loads((tmp_path / "c" / fz.LOOKUPS).read_text())["github"] == {"p1": 1, "p3": 1}
    _pull(tmp_path / "d", ["p3"])
    with pytest.raises(ValueError, match="two shards"):
        fz.merge([tmp_path / "b", tmp_path / "d"], tmp_path / "e")


def test_the_archive_bytes_depend_only_on_the_files_and_are_checked_before_use(tmp_path):
    _pull(tmp_path / "a", ["p1", "p2"])
    one = fz.pack(tmp_path / "a", tmp_path / "x.tar.gz")
    two = fz.pack(tmp_path / "a", tmp_path / "y.tar.gz")
    assert one == two and one["points"] == 2
    fz.unpack(tmp_path / "x.tar.gz", one, tmp_path / "out")
    assert (tmp_path / "out" / "points" / "p1" / "server_log.gz").read_bytes() == b"p1"
    with pytest.raises(ValueError, match="sha256"):
        fz.unpack(tmp_path / "x.tar.gz", {**one, "sha256": "0" * 64}, tmp_path / "out2")


def test_an_archive_entry_outside_the_pull_is_refused(tmp_path):
    import io
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(bad, "w:gz") as tar:
        info = tarfile.TarInfo("../escape")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    import ledger_extract as lx
    with pytest.raises(ValueError, match="not a file inside"):
        fz.unpack(bad, {"sha256": lx.sha256(bad), "bytes": bad.stat().st_size}, tmp_path / "o")


def test_the_replay_keeps_the_nights_anchors_and_asks_nothing_when_no_build_is_remade(tmp_path):
    _pull(tmp_path / "a", ["p1", "p2", "p3"])
    pin = fz.pack(tmp_path / "a", tmp_path / "x.tar.gz")
    asked = fz.replay(tmp_path / "x.tar.gz", pin, tmp_path / "work", {"p1", "p3"}, "v0.32.0", None)
    m = json.loads((tmp_path / "work" / "manifest.json").read_text())
    assert asked == 0 and [e["point_id"] for e in m["points"]] == ["p1", "p3"]
    assert m["vllm_ref"] == "v0.32.0" and not (tmp_path / "work" / "points" / "p2").exists()
