"""Tests of the per-source anchor rule (sources.py, design D9): a ledger.yaml that agrees passes, and each way it can
disagree is reported by name. Offline: the documents are canned."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sources as sr  # noqa: E402


def cp(role, a=0, b=99):
    return {"role": role, "from": a, "to": b}


IX = [cp("fit", 0, 59), cp("select", 60, 69), cp("validate", 70, 79), cp("held", 80, 89), cp("anchor", 90, 99)]
GOOD = {"kind": "Ledger", "partition_version": 2, "rules": {
    "inferencex": {"cut_points": IX},
    "configiq": {"cut_points": [cp("anchor")], "left_out": ["u1", "u2"]},
    "vllm-ci-perf": {"cut_points": [cp("fit", 0, 69), cp("select", 70, 79), cp("validate", 80, 99)]},
    "sglang-nightly": {"cut_points": [cp("fit", 0, 69), cp("select", 70, 79), cp("validate", 80, 99)]},
    "sglang-traces": {"cut_points": [cp("fit", 0, 69), cp("select", 70, 79), cp("validate", 80, 99)]}}}
STALE = copy.deepcopy(GOOD) | {"partition_version": 1}
STALE["rules"]["configiq"] = {"cut_points": IX}


def test_a_ledger_that_follows_d9_has_no_discrepancy_and_names_the_left_out_units():
    assert sr.check_cut_points(GOOD) == []
    assert sr.configiq_left_out(GOOD) == {"u1", "u2"} and sr.configiq_left_out(STALE) == set()


def test_todays_shape_configiq_with_inferencexs_cut_points_is_reported_with_its_version_and_the_maintainer_step():
    found = sr.check_cut_points(STALE)
    assert [d["code"] for d in found] == ["held_outside_inferencex", "configiq_cut_points_not_anchor_only"]
    t = found[1]["text"]
    assert "partition version 1" in t and "maintainer step" in t and "fit" in t
    assert "plan is the rule" in t and "anchor-only" in t and "wrong to that extent" in t


MUTATE = [
    ("held_outside_inferencex", lambda d: d["rules"]["vllm-ci-perf"].update(cut_points=[cp("held")]), "held_outside_inferencex"),
    ("inferencex_not_held", lambda d: d["rules"]["inferencex"].update(cut_points=[cp("fit", 0, 99)]), "inferencex_not_held"),
    ("training_source_has_anchor", lambda d: d["rules"]["sglang-traces"].update(cut_points=[cp("fit", 0, 89), cp("anchor", 90, 99)]),
     "training_source_not_training_only"),
    ("training_source_missing", lambda d: d["rules"].pop("sglang-nightly"), "training_source_no_rule"),
    ("configiq_missing", lambda d: d["rules"].pop("configiq"), "configiq_no_rule"),
]


@pytest.mark.parametrize("name, mutate, code", MUTATE, ids=[m[0] for m in MUTATE])
def test_each_way_a_ledger_can_leave_d9_is_named(name, mutate, code):
    d = copy.deepcopy(GOOD)
    mutate(d)
    assert code in {x["code"] for x in sr.check_cut_points(d)}


def test_anchor_roles_outside_the_two_anchor_sources_are_reported():
    d = copy.deepcopy(GOOD)
    d["rules"]["vllm-ci-perf"]["cut_points"] = [cp("anchor")]
    codes = {(x["source"], x["code"]) for x in sr.check_cut_points(d)}
    assert ("vllm-ci-perf", "anchor_outside_anchor_sources") in codes


def test_a_document_that_is_not_a_ledger_is_refused():
    with pytest.raises(sr.SourcesError):
        sr.check_cut_points({"kind": "Other"})
    with pytest.raises(sr.SourcesError):
        sr.configiq_left_out({"rules": {"configiq": {"left_out": [1]}}})


def test_the_cli_warns_and_exits_nonzero_only_when_strict(tmp_path, capsys):
    import yaml
    p = tmp_path / "ledger.yaml"
    p.write_text(yaml.safe_dump(STALE))
    assert sr.main(["--ledger-yaml", str(p)]) == 0
    cap = capsys.readouterr()
    assert json.loads(cap.out)[0]["source"] == "configiq" and "WARNING: configiq" in cap.err
    assert sr.main(["--ledger-yaml", str(p), "--strict"]) == 1
    p.write_text(yaml.safe_dump(GOOD))
    assert sr.main(["--ledger-yaml", str(p), "--strict"]) == 0


# ------------------------------------------------------------------------------------------------ the units scored, and the guard

IDS = [f"{i:064x}" for i in range(6)]


def _published(directory, role, units, kind="PublishedUnits"):
    import yaml
    (directory / f"{role}.yaml").write_text(yaml.safe_dump({"kind": kind, "role": role, "units": list(units)}))


def test_the_units_scored_are_every_ledger_id_less_the_left_out_list_and_never_anchor_yaml():
    assert sr.configiq_anchor_ids(IDS) == sorted(IDS) and sr.configiq_anchor_ids(IDS, STALE) == sorted(IDS)
    doc = {"rules": {"configiq": {"left_out": [IDS[1], IDS[4]]}}}
    assert sr.configiq_anchor_ids(IDS, doc) == [i for i in sorted(IDS) if i not in (IDS[1], IDS[4])]
    with pytest.raises(sr.SourcesError, match="does not hold"):
        sr.configiq_anchor_ids(IDS, {"rules": {"configiq": {"left_out": ["f" * 64]}}})


@pytest.mark.parametrize("role", ["fit", "select", "validate"])
def test_a_configiq_id_in_any_training_role_list_is_found(tmp_path, role):
    _published(tmp_path, "fit", [])
    _published(tmp_path, "anchor", IDS[:1])             # the anchor list may hold configiq ids: it is the one role allowed
    _published(tmp_path, role, ["e" * 64, IDS[2]])
    assert sr.configiq_in_training(tmp_path, IDS) == [{"file": f"{role}.yaml", "role": role, "units": [IDS[2]]}]


def test_no_configiq_id_in_a_training_list_is_the_clean_answer_and_a_held_list_is_not_read(tmp_path):
    _published(tmp_path, "fit", ["e" * 64])
    _published(tmp_path, "held", IDS)                   # held is InferenceX's role; this guard is for the fit/select/validate lists
    assert sr.configiq_in_training(tmp_path, IDS) == []
    assert sr.configiq_in_training(tmp_path / "fit.yaml", IDS) == []


def test_the_funnel_fails_when_a_configiq_id_is_in_a_training_list_unless_it_is_left_out(tmp_path, monkeypatch):
    """The nightly's path: funnel.py reads the published lists, and a configiq unit read under a training role is a problem."""
    import yaml
    from types import SimpleNamespace
    import funnel as fn
    fake = SimpleNamespace(load=lambda *a: SimpleNamespace(units={i: 1 for i in IDS}, by_record={"1": 1}, left_out={}))
    monkeypatch.setitem(sys.modules, "configiq", fake)
    pub = tmp_path / "pub"
    pub.mkdir()
    _published(pub, "validate", [IDS[3]])
    pts = tmp_path / "points.jsonl"
    pts.write_text("")
    argv = ["--configiq-ledger", str(tmp_path), "--configiq-points", str(pts), "--published", str(pub), "--out", str(tmp_path / "o.json")]
    assert fn.main(argv) == 1
    assert any("validate" in p and IDS[3] in p for p in json.loads((tmp_path / "o.json").read_text())["problems"])
    ly = tmp_path / "ledger.yaml"
    ly.write_text(yaml.safe_dump(copy.deepcopy(GOOD) | {"rules": GOOD["rules"] | {"configiq": {"cut_points": [cp("anchor")], "left_out": [IDS[3]]}}}))
    assert fn.main(argv + ["--ledger-yaml", str(ly)]) == 0
    assert json.loads((tmp_path / "o.json").read_text())["funnels"]["configiq"]["not_anchor"] == {"left_out_by_partition_prep": 1}
