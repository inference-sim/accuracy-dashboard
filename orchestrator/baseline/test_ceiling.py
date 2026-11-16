"""Tests of the grade ceiling (ceiling.py): which limits the data sets, and what is left as BLIS work."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ceiling as cl  # noqa: E402

ENGINE = "0.32.0"
COEF = {"kind": "coefficient_method", "subject": "cost-model-primitives/hbm_derate", "detail": "assumed"}
UNEVAL = {"kind": "unevaluated", "subject": "kernel_hash", "detail": "kernel_hash is unevaluated"}
PORTED = {"engine_release": ENGINE, "releases": {
    "0.25.0": {"changed": ["vllm/v1/core/sched/scheduler.py:Scheduler.schedule"], "unchanged": []},
    "0.31.0": {"changed": [], "unchanged": ["vllm/v1/core/sched/scheduler.py:Scheduler.schedule"]}}}


def scored(release, grade, subs=(), args=()):
    return {"status": "scored", "grade": grade, "run_release": release, "substitutions": list(subs), "args": list(args)}


def g5(release, *reasons):
    return {"status": "not_scored", "grade": "G5", "run_release": release, "g5_reasons": list(reasons)}


def c(p, ported=PORTED):
    return cl.ceiling(p, engine_version=ENGINE, ported=ported)


def test_a_nightly_build_is_at_its_g4_ceiling():
    r = c(scored(None, "G4", [COEF, UNEVAL]))
    assert (r["ceiling"], r["state"], r["not_yet"]) == ("G4", "at_ceiling", [])
    assert [x["code"] for x in r["limits"]] == ["nightly_or_custom"]


def test_a_release_whose_ported_function_changed_cannot_reach_g3():
    r = c(scored("0.25.0", "G4"))
    assert r["ceiling"] == "G4" and r["limits"][0]["code"] == "changed_functions"
    assert "Scheduler.schedule" in r["limits"][0]["why"]


def test_a_release_with_no_changed_function_or_no_comparison_can_reach_g3_not_yet():
    for release in ("0.31.0", "0.24.0"):
        r = c(scored(release, "G4"))
        assert (r["ceiling"], r["state"]) == ("G3", "not_yet"), release
    assert c(scored("0.25.0", "G4"), ported=None)["ceiling"] == "G3"


def test_a_run_on_the_engine_release_can_reach_g1_and_names_the_work():
    r = c(scored(ENGINE, "G2", [COEF, UNEVAL]))
    assert (r["ceiling"], r["state"], r["limits"]) == ("G1", "not_yet", [])
    assert r["not_yet"] == ["coefficient_method:cost-model-primitives/hbm_derate", "unevaluated:kernel_hash"]


def test_a_substitution_from_the_data_caps_at_g2():
    later = {"kind": "later_record", "subject": "cluster.gpus_per_node", "detail": "runners.yaml"}
    flags = {"kind": "client_difference", "subject": "client_flags", "detail": "job log expired"}
    gap = {"kind": "client_difference", "subject": "send_gap", "detail": "not modelled"}
    for sub in (later, flags):
        r = c(scored(ENGINE, "G2", [sub, gap]))
        assert (r["ceiling"], r["state"]) == ("G2", "at_ceiling"), sub
    assert c(scored(ENGINE, "G2", [gap]))["ceiling"] == "G1"


def test_an_estimate_is_data_only_when_the_run_recorded_no_value():
    est = {"kind": "estimated", "subject": "api_server_count", "detail": "left unset"}
    set_by_run = [{"arg": "api_server_count", "match": "approximated", "measured": 4}]
    assert c(scored(ENGINE, "G2", [est], set_by_run))["ceiling"] == "G1"
    assert c(scored(ENGINE, "G2", [est]))["ceiling"] == "G2"


def test_a_g5_reason_of_the_record_holds_the_point_at_g5():
    for reason in (("value_conflict", "model: two checkpoints"), ("value_not_recorded", ""),
                   ("value_not_recorded", "api_413"), ("value_not_recorded", "no_recipe_fingerprint")):
        r = c(g5(None, reason))
        assert (r["ceiling"], r["state"]) == ("G5", "at_ceiling"), reason


def test_a_g5_reason_that_is_blis_work_leaves_the_build_ceiling():
    r = c(g5(None, ("field_not_modelled", "linear_backend"), ("not_in_catalog", "")))
    assert (r["ceiling"], r["state"]) == ("G4", "not_yet")
    assert r["not_yet"] == ["field_not_modelled:linear_backend", "not_in_catalog"]


def test_a_missing_value_an_estimate_could_cover_caps_at_g2_not_g5():
    r = c(g5(ENGINE, ("value_not_recorded", "workload_category_not_stated")))
    assert (r["ceiling"], r["state"]) == ("G2", "not_yet")


def test_a_point_the_simulator_refused_is_not_yet():
    p = {"status": "failed", "grade": "failed", "run_release": "0.25.0",
         "g5_reasons": [("blis_refused", "scenario")]}
    r = c(p)
    assert (r["ceiling"], r["state"], r["not_yet"]) == ("G4", "not_yet", ["blis_refused:scenario"])
