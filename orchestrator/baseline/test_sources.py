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
    assert "partition version 1" in t and "D9" in t and "maintainer step" in t and "fit" in t


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
