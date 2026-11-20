"""Tests of the scoring funnels (funnel.py): each stage and each reason, the laws the counts obey, the two sources'
adapters, and the section the baseline report publishes. Offline: units are canned."""
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ingest"))
import funnel as fn  # noqa: E402
import m3_baseline as mb  # noqa: E402


def U(uid, **kw):
    return {"unit_id": uid, "excluded": None, "recoverable": None, "blocked": None, "grade": None,
            "provisional": False, "failed": None, "g5": None, "withheld": None, **kw}


PLACEMENT = [
    # name, unit, the one place it lands
    ("excluded_chip", U("a", excluded="chip_not_modelled"), ("excluded", "chip_not_modelled")),
    ("scored_g3", U("a", recoverable=True, grade="G3"), ("scored", "G3")),
    ("scored_though_not_counted_recoverable", U("a", recoverable=False, blocked="no_probe:pd_recipe", grade="G4"),
     ("scored", "G4")),
    ("g5", U("a", recoverable=True, g5="value_not_recorded"), ("g5", "value_not_recorded")),
    ("provisional_is_not_scored", U("a", recoverable=True, provisional=True, grade="G3"), ("provisional", "G3")),
    ("failed", U("a", recoverable=True, failed="scorer_error"), ("failed", "scorer_error")),
    ("withheld", U("a", withheld="test_split_not_simulated"), ("withheld", "test_split_not_simulated")),
    ("no_result_names_why_not_recovered", U("a", recoverable=False, blocked="api_server_log_404"),
     ("no_outcome", "api_server_log_404")),
    ("no_result_at_all", U("a"), ("no_outcome", fn.NO_OUTCOME)),
]


@pytest.mark.parametrize("name, unit, where", PLACEMENT, ids=[c[0] for c in PLACEMENT])
def test_a_unit_lands_in_exactly_one_place_under_a_named_reason(name, unit, where):
    f = fn.tally("s", 5, [unit])
    bucket, reason = where
    got = {"excluded": f["excluded"], "g5": f["g5"], "failed": f["failed"], "withheld": f["withheld"],
           "no_outcome": f["no_outcome"], "scored": {g: n for g, n in f["scored_by_grade"].items() if n},
           "provisional": f["provisional"]["by_grade"]}
    assert got[bucket] == {reason: 1}
    assert sum(sum(v.values()) for v in got.values()) == 1
    assert fn.check(f) == []


def test_the_stages_shrink_and_the_buckets_add_up_for_a_mixed_source():
    units = [U("1", excluded="amd_or_tpu"), U("2", excluded="amd_or_tpu"), U("3", recoverable=True, grade="G2"),
             U("4", recoverable=True, grade="G3"), U("5", recoverable=True, g5="blis_refused"),
             U("6", recoverable=True, failed="timeout"), U("7", recoverable=False, blocked="no_probe:agentic_export"),
             U("8", recoverable=False, blocked="no_probe:agentic_export", grade="G4")]
    f = fn.tally("inferencex", 20, units, left_out_rows={"duplicate": 2})
    assert f["stages"] == {"rows_held": 20, "units": 8, "in_scope": 6, "recoverable": 4, "scored": 3}
    assert f["excluded"] == {"amd_or_tpu": 2} and f["left_out_rows"] == {"duplicate": 2}
    assert f["scored_by_grade"] == {"G1": 0, "G2": 1, "G3": 1, "G4": 1}
    assert f["not_recovered"] == {"no_probe:agentic_export": 2}
    assert f["unresolved"] == {"units": 1, "unit_ids": ["6"]}
    assert fn.check(f) == []


def test_no_probe_leaves_the_recoverable_stage_null_not_zero():
    f = fn.tally("configiq", 3, [U("1", grade="G3"), U("2", g5="engine_unsupported")])
    assert f["stages"]["recoverable"] is None and f["unresolved"]["units"] == 0


def test_blockers_are_the_largest_reasons_first_then_by_name():
    units = [U(str(i), recoverable=False, blocked="no_probe:pd_recipe") for i in range(3)]
    units += [U(f"g{i}", recoverable=True, g5="value_not_recorded") for i in range(3)]
    units += [U("x", recoverable=True, failed="timeout")]
    f = fn.tally("s", 7, units)
    assert [(b["stage"], b["reason"], b["units"]) for b in f["blockers"]] == [
        ("g5", "value_not_recorded", 3), ("no_outcome", "no_probe:pd_recipe", 3), ("failed", "timeout", 1)]


def test_a_unit_listed_twice_is_refused():
    with pytest.raises(fn.FunnelError, match="listed twice"):
        fn.tally("s", 2, [U("a"), U("a")])


CHECKS = [
    ("in_scope_over_units", lambda f: f["stages"].update(in_scope=f["stages"]["units"] + 1)),
    ("exclusions_do_not_sum", lambda f: f["excluded"].update(extra=1)),
    ("grades_do_not_sum", lambda f: f["scored_by_grade"].update(G1=f["scored_by_grade"]["G1"] + 1)),
    ("outcomes_do_not_sum", lambda f: f["g5"].update(extra=1)),
    ("recoverable_over_in_scope", lambda f: f["stages"].update(recoverable=99)),
]


@pytest.mark.parametrize("name, damage", CHECKS, ids=[c[0] for c in CHECKS])
def test_a_funnel_whose_counts_disagree_is_refused(name, damage):
    f = fn.tally("s", 4, [U("1", excluded="amd_or_tpu"), U("2", recoverable=True, grade="G2"),
                          U("3", recoverable=True, g5="blis_refused")])
    assert fn.check(f) == []
    damage(f)
    assert fn.check(f)
    with pytest.raises(fn.FunnelError):
        fn.validate({"format": fn.FORMAT, "funnels": {"s": f}})


# ------------------------------------------------------------------------------------------------ InferenceX

def _ledger(n=6, left_out=None):
    ids = [f"{i:064x}" for i in range(1, n + 1)]
    return SimpleNamespace(units={i: SimpleNamespace(unit_id=i) for i in ids}, by_record={str(k): 1 for k in range(n + 2)},
                           left_out=left_out or {}), ids


def test_the_inferencex_funnel_places_each_anchor_unit_from_the_probe_and_the_contract(tmp_path):
    lg, ids = _ledger(left_out={"9": "unlisted"})
    (tmp_path / "fidelity.jsonl").write_text(json.dumps({"point_id": ids[0], "grade": "G3"}) + "\n")
    (tmp_path / "not_scored.jsonl").write_text(
        json.dumps({"point_id": ids[1], "g5_reason": {"code": "blis_refused"}}) + "\n" +
        json.dumps({"point_id": ids[2], "g5_reason": {"code": "chip_not_modelled"}}) + "\n")
    (tmp_path / "failed.jsonl").write_text(json.dumps({"point_id": ids[3], "faults": ["scorer_error:boom"]}) + "\n")
    probe = [{"unit_id": ids[0], "status": "recoverable", "detail": "api_server_log"},
             {"unit_id": ids[1], "status": "recoverable", "detail": "api_server_log"},
             {"unit_id": ids[3], "status": "recoverable", "detail": "api_server_log"},
             {"unit_id": ids[4], "status": "excluded", "detail": "amd_or_tpu"},
             {"unit_id": ids[5], "status": "not_recovered", "detail": "api_server_log_404"}]
    f = fn.inferencex(lg, set(ids), probe, fn.contract_outcomes(tmp_path))
    assert f["stages"] == {"rows_held": 8, "units": 6, "in_scope": 4, "recoverable": 3, "scored": 1}
    assert f["excluded"] == {"amd_or_tpu": 1, "chip_not_modelled": 1}
    assert f["g5"] == {"blis_refused": 1} and f["failed"] == {"scorer_error": 1}
    assert f["no_outcome"] == {"api_server_log_404": 1} and f["left_out_rows"] == {"unlisted": 1}
    assert f["unresolved"]["unit_ids"] == [ids[3]]
    assert fn.check(f) == []


def test_an_anchor_unit_is_never_dropped_for_its_date():
    lg, ids = _ledger(2)
    for uid in ids:
        lg.units[uid].identity = {"measured_date": "2019-01-01"}
    f = fn.inferencex(lg, set(ids), None, {i: {"grade": "G4"} for i in ids})
    assert f["stages"]["scored"] == 2 and f["excluded"] == {} and f["no_outcome"] == {}


def test_an_anchor_unit_the_ledger_does_not_hold_is_refused():
    lg, ids = _ledger(1)
    with pytest.raises(fn.FunnelError, match="does not hold"):
        fn.inferencex(lg, set(ids) | {"f" * 64}, None, {})


# ------------------------------------------------------------------------------------------------ configiq

def _rec(uid, **kw):
    return {"point_id": uid, "grade": None, "provisional": False, "failed": False, "g5_reasons": [], "g5_reason": None,
            "status": "scored", **kw}


CONFIGIQ = [
    ("chip_not_modelled", _rec("a", grade="G5", g5_reasons=[{"code": "chip_not_modelled", "subject": "x"}],
                              g5_reason={"code": "chip_not_modelled"}), "excluded", {"chip_not_modelled": 1}),
    ("value_not_recorded", _rec("a", grade="G5", g5_reasons=[{"code": "value_not_recorded", "subject": "engine max_num_seqs"}],
                               g5_reason={"code": "value_not_recorded"}), "not_recovered",
     {"value_not_recorded: engine max_num_seqs": 1}),
    ("provisional", _rec("a", provisional=True, grade="G3"), "provisional", {"G3": 1}),
    ("scored", _rec("a", grade="G4"), "scored_by_grade", {"G4": 1}),
    ("withheld", _rec("a", status="withheld"), "withheld", {"test_split_not_simulated": 1}),
    ("failed", _rec("a", failed=True, faults=["scorer_error:x"]), "failed", {"scorer_error": 1}),
]


@pytest.mark.parametrize("name, rec, key, want", CONFIGIQ, ids=[c[0] for c in CONFIGIQ])
def test_the_configiq_funnel_places_a_point_from_its_record(name, rec, key, want):
    lg = SimpleNamespace(units={"a": 1}, by_record={"1": 1, "2": 1}, left_out={})
    f = fn.configiq(lg, [rec])
    got = f["provisional"]["by_grade"] if key == "provisional" else {k: v for k, v in f[key].items() if v}
    assert got == want
    assert fn.check(f) == []


def test_a_configiq_unit_without_a_record_has_no_result_and_a_stray_record_is_refused():
    lg = SimpleNamespace(units={"a": 1, "b": 1}, by_record={}, left_out={})
    f = fn.configiq(lg, [_rec("a", grade="G3")])
    assert f["no_outcome"] == {fn.NO_OUTCOME: 1} and f["stages"]["scored"] == 1
    with pytest.raises(fn.FunnelError, match="no unit for"):
        fn.configiq(lg, [_rec("z")])


# ------------------------------------------------------------------------------------------------ publishing

def _doc():
    ix = fn.tally("inferencex", 9, [U("1", recoverable=True, grade="G3"), U("2", excluded="amd_or_tpu")])
    cq = fn.tally("configiq", 4, [U("1", grade="G4"), U("2", grade="G3"), U("3", g5="engine_unsupported")])
    return fn.combine([cq, ix])


def test_the_document_publishes_the_scored_count_of_each_source():
    d = _doc()
    assert d["scored"] == {"configiq": 2, "inferencex": 1} and d["problems"] == []
    assert list(d["funnels"]) == ["configiq", "inferencex"]
    with pytest.raises(fn.FunnelError):
        fn.combine([d["funnels"]["configiq"], d["funnels"]["configiq"]])


def test_the_section_states_the_scored_count_and_each_reason():
    text = "\n".join(fn.markdown(_doc()))
    assert "**1 of 1 in-scope units are scored**" in text and "**2 of 3 in-scope units are scored**" in text
    assert "| Excluded | `amd_or_tpu` | 1 |" in text and "| G5 | `engine_unsupported` | 1 |" in text
    assert "| recoverable | not probed |" in text


def _report(**extra):
    import os
    import test_m3_baseline as tb
    kw = tb._inputs()
    kw["contract"] = Path("docs/m2/preliminary-after/contract")
    cwd = os.getcwd()
    os.chdir(tb.ROOT)
    try:
        return mb.report(**kw, **extra)[0]
    finally:
        os.chdir(cwd)


def test_the_report_carries_the_funnels_only_when_they_are_given_and_refuses_inconsistent_ones():
    plain = _report()
    assert "funnel" not in plain and "Scoring funnels" not in mb.markdown(plain)
    with_f = _report(funnel=_doc())
    assert with_f["funnel"] == _doc() and {k: v for k, v in with_f.items() if k != "funnel"} == plain
    assert mb.markdown(with_f).startswith(mb.markdown(plain).rstrip("\n"))
    assert "## Scoring funnels" in mb.markdown(with_f)
    bad = copy.deepcopy(_doc())
    bad["funnels"]["configiq"]["g5"]["extra"] = 1
    with pytest.raises(mb.BaselineError, match="add up"):
        _report(funnel=bad)


def test_the_command_refuses_half_a_source():
    assert fn.main(["--ledger", "l", "--out", "o"]) == 2
    assert fn.main(["--configiq-points", "p", "--out", "o"]) == 2
