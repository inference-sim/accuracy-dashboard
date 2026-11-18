"""Behavioural tests of pd_freeze: pairs map to ledger units, and the freeze refuses to start on a low REST quota."""
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pd_freeze as pf  # noqa: E402


def rec(unit):
    return SimpleNamespace(unit=SimpleNamespace(unit_id=unit))


def test_pairs_map_to_units_and_say_why_not():
    by_record = {"1": rec("u1"), "2": rec("u2"), "3": rec("u2"), "4": rec("u3")}
    got = pf.units_of_pairs([{"records": ["1"]}, {"records": ["2", "3"]}, {"records": ["9"]},
                             {"records": ["1", "4"]}], by_record)
    assert [(e["unit"], e.get("why")) for e in got] == [("u1", None), ("u2", None), (None, "no_unit"),
                                                         (None, "several_units")]


def test_low_quota_stops_before_any_work(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "core_remaining", lambda: 999)
    args = []
    for k in ("pairs", "dump-rows", "ledger", "git-dir", "vllm-git-dir", "rest-cache", "out", "cache", "units-out", "errors-out"):
        args += [f"--{k}", str(tmp_path / k)]
    try:
        pf.main(args)
    except pf.FreezeError as e:
        assert "999" in str(e)
        assert not (tmp_path / "units-out").exists()
        return
    raise AssertionError("a quota below the floor must stop the freeze")
