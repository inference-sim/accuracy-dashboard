"""Closeness grades (design §11.3, §11.4; COV-4, COV-5, COV-6).

Run: python3 -m pytest orchestrator/ingest/test_grade.py
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grade as g  # noqa: E402

V = "0.32.0"
REL = g.Release(version=V, nightly_or_custom=False)
EST = {"kind": "estimated", "subject": "max_model_len", "detail": "leave_unset"}


def test_the_release_the_simulator_runs_with_nothing_substituted_is_g1():
    assert g.grade(engine_version=V, release=REL, substitutions=[]).grade == g.G1


def test_any_named_substitution_makes_it_g2():
    out = g.grade(engine_version=V, release=REL, substitutions=[EST])
    assert out.grade == g.G2 and out.substitutions == [EST]


def test_another_release_with_no_published_function_list_is_g4_and_says_so():
    out = g.grade(engine_version=V, release=g.Release("0.25.0", False), substitutions=[])
    assert out.grade == g.G4
    assert {"kind": "ported_functions_unpublished", "subject": "engine release",
            "detail": g.PORTED_FUNCTIONS_UNPUBLISHED} in out.substitutions


def test_another_release_is_g3_when_no_ported_function_changed_and_g4_when_one_did():
    ported = {"functions": ["Scheduler.schedule"], "changed": {"0.31.0": [], "0.25.0": ["Scheduler.schedule"]}}
    assert g.grade(engine_version=V, release=g.Release("0.31.0", False), substitutions=[EST],
                   ported=ported).grade == g.G3
    four = g.grade(engine_version=V, release=g.Release("0.25.0", False), substitutions=[], ported=ported)
    assert four.grade == g.G4 and any(s["kind"] == "changed_functions" for s in four.substitutions)
    # A release no diff covers cannot be told unchanged.
    assert g.grade(engine_version=V, release=g.Release("0.20.0", False), substitutions=[],
                   ported=ported).grade == g.G4


def test_a_nightly_or_custom_build_is_g4_and_names_the_build():
    out = g.grade(engine_version=V, release=g.Release(None, True, "vllm/vllm-openai:nightly-abc"), substitutions=[])
    assert out.grade == g.G4 and out.substitutions[0]["detail"] == "vllm/vllm-openai:nightly-abc"


def test_g5_is_only_for_the_closed_list_and_wins_over_every_other_grade():
    out = g.grade(engine_version=V, release=REL, substitutions=[EST],
                  g5=[{"code": "value_conflict", "subject": "max_num_seqs"},
                      {"code": "router_unsupported", "subject": "vllm-router"}])
    assert out.grade == g.G5 and out.g5 == {"code": "router_unsupported", "subject": "vllm-router"}
    with pytest.raises(g.GradeError, match="COV-5"):
        g.grade(engine_version=V, release=REL, substitutions=[], g5=[{"code": "setting_not_modelled"}])


def test_the_g5_list_is_design_11_4_with_router_unsupported_and_value_conflict():
    assert set(g.G5_CODES) == {"code_not_visible", "router_unsupported", "topology_unsupported", "value_not_recorded",
                               "field_not_modelled", "field_unclassified", "engine_unsupported",
                               "not_in_catalog", "field_not_in_release", "value_conflict", "build_unparseable"}


def test_a_substitution_must_be_a_g2_condition_and_name_its_subject():
    with pytest.raises(g.GradeError):
        g.grade(engine_version=V, release=REL, substitutions=[{"kind": "guess", "subject": "x"}])
    with pytest.raises(g.GradeError):
        g.grade(engine_version=V, release=REL, substitutions=[{"kind": "estimated", "subject": ""}])


def test_run_release_reads_a_release_image_and_calls_anything_else_nightly_or_custom():
    assert g.run_release({"image": "vllm/vllm-openai:v0.32.0"}, "0.32.0") == g.Release("0.32.0", False)
    assert g.run_release({"image": "vllm/vllm-openai:v0.25.0"}, None).version == "0.25.0"
    # A release tag whose banner prints another version is not that release.
    assert g.run_release({"image": "vllm/vllm-openai:v0.25.0"}, "0.25.1rc1.dev3+gabc").nightly_or_custom
    assert g.run_release({"image": "vllm/vllm-openai:nightly-abc"}, "0.30.1rc1.dev493+gac9126e58").nightly_or_custom
    assert g.run_release({"image": "lmsysorg/private:v0.32.0"}, "0.32.0").nightly_or_custom


def test_check_holds_every_point_to_one_grade_and_its_build():
    good = [{"point_id": "a", "grade": "G1", "build": {"release": V}},
            {"point_id": "b", "grade": "G2", "build": {"release": V}, "substitutions": [EST]},
            {"point_id": "c", "grade": "G4", "build": {"release": "0.25.0"},
             "substitutions": [{"kind": "other_release", "subject": "engine release"}]},
            {"point_id": "d", "grade": "G5", "g5_reason": {"code": "not_in_catalog"}}]
    assert g.check(good, V) == []
    bad = [{"point_id": "e", "grade": "G2", "build": {"release": V}},
           {"point_id": "f", "grade": "G1", "build": {"release": "0.25.0"}},
           {"point_id": "h", "grade": "G4", "build": {"release": V}, "substitutions": [EST]},
           {"point_id": "i", "grade": "G5", "g5_reason": {"code": "blis_refused"}},
           {"point_id": "j", "grade": "G6"}]
    assert len(g.check(bad, V)) == 5


def test_check_requires_one_simulator_build_and_engine_release_for_every_point():
    # COV-6: every point of one run is scored by one simulator release.
    sim = {"build": "v0.16.0", "engine": {"kind": "vllm", "version": V}}
    pts = [{"point_id": "a", "grade": "G1", "build": {"release": V}, "simulator": sim},
           {"point_id": "b", "grade": "G5", "g5_reason": {"code": "not_in_catalog"}, "simulator": sim}]
    assert g.check(pts, V) == []
    other = {**sim, "build": "v0.17.0"}
    assert any("COV-6" in x for x in g.check(pts + [{**pts[0], "point_id": "c", "simulator": other}], V))
    wrong = {**sim, "engine": {"kind": "vllm", "version": "0.31.0"}}
    assert any("running '0.31.0'" in x for x in g.check([{**pts[0], "simulator": wrong}], V))


def test_the_four_conditions_that_are_not_graded_yet_are_g2_kinds_named_on_a_subject_of_their_own():
    subs = g.unchecked()
    assert [s["kind"] for s in subs] == ["coefficient_range", "kernel_hash", "resolved_differs", "value_class"]
    assert all(s["kind"] in g.G2_KINDS and s["subject"] == "unevaluated" and s["detail"] == f"{s['kind']} is unevaluated"
               for s in subs)
    out = g.grade(engine_version=V, release=REL, substitutions=subs)
    assert out.grade == g.G2 and out.substitutions == subs
