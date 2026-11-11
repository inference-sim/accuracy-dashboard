"""The four G1 conditions are evaluated from the Result's and the field list's data, and a condition
whose data is absent stays unevaluated (design 11.3). The Result and field-list shapes are the ones
described for blis-substrate layer 10 and inference-sim PR 5; the fixtures are synthetic."""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fields as fl  # noqa: E402
import g1  # noqa: E402
import grade as gr  # noqa: E402
import score as sc  # noqa: E402

HASH = "a" * 40
OTHER = "b" * 40


def coeff(name="host_launch_per_kernel", **kw):
    """A coefficient as the final layer 10 Result writes it: booleans only when true."""
    return {"set": "cost-model-host-overheads", "name": name, "method": "measured", "scope": "h200", "file": "f.yaml",
            "kernel_impls": [{"library": "flashinfer", "variant": "decode", "code_hash": HASH}],
            "fit_range": [{"dim": "tokens", "low": 1, "high": 64}], "ci95": {"low": 0.9, "high": 1.1}, **kw}


def doc(*cs, resolutions=None):
    d = {"selected_entries": {"closeness_version": 1, "coefficients": list(cs) or [coeff()]}}
    if resolutions is not None:
        d["resolutions"] = resolutions
    return d


def field_list(classes=None, status="modelled"):
    f = {"name": "max_num_seqs", "source": "config", "status": status,
         "evidence": {"traces": ["t.json"]} if status == "modelled" else {"issue": "x/y#1"},
         "estimation": {"rule": "leave_unset"}}
    if classes is not None:
        f["value_classes"] = classes
    import json
    return fl.parse(json.dumps({"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.32.0"}, "fields": [f]}))


# ---- coefficient_range

def test_a_report_whose_entries_state_a_fit_range_and_an_interval_and_no_flags_is_evaluated_and_clean():
    e = g1.coefficient_range(doc())
    assert e.evaluated and e.subs == []


def test_an_extrapolated_or_unidentified_coefficient_is_named_with_its_fit_range():
    e = g1.coefficient_range(doc(coeff("a", extrapolated=True), coeff("b", unidentified=True, fit_range=[]), coeff("c")))
    assert e.evaluated
    assert e.subs == [{"kind": "coefficient_range", "subject": "cost-model-host-overheads/a",
                       "detail": "extrapolated; fit range tokens 1 to 64"},
                      {"kind": "coefficient_range", "subject": "cost-model-host-overheads/b", "detail": "unidentified"}]


def test_a_report_without_the_closeness_marker_leaves_the_range_and_the_hash_unevaluated():
    d = doc()
    del d["selected_entries"]["closeness_version"]
    assert not g1.coefficient_range(d).evaluated and not g1.kernel_hash(d, {"flashinfer": "0.4.1"}, VERSIONS).evaluated
    d["selected_entries"]["closeness_version"] = 2
    assert not g1.coefficient_range(d).evaluated        # only version 1 is read


def test_an_entry_that_states_no_fit_range_or_no_interval_leaves_the_flags_not_evaluated():
    bare = {"set": "s", "name": "n", "method": "assumed", "scope": "h200", "file": "f.yaml"}
    e = g1.coefficient_range(doc(bare))
    assert not e.evaluated and "state no fit range or no interval" in e.why
    no_ci = coeff()
    del no_ci["ci95"]
    assert not g1.coefficient_range(doc(no_ci)).evaluated          # extrapolated is decidable, unidentified is not
    no_fit = coeff()
    del no_fit["fit_range"]
    assert not g1.coefficient_range(doc(coeff(), no_fit)).evaluated
    assert g1.coefficient_range(doc(coeff(), coeff("b"))).evaluated


def test_a_true_flag_is_evidence_even_when_other_entries_state_nothing():
    bare = {"set": "s", "name": "n", "method": "assumed", "scope": "h200", "file": "f.yaml"}
    e = g1.coefficient_range(doc(bare, coeff("a", extrapolated=True)))
    assert e.evaluated and [x["subject"] for x in e.subs] == ["cost-model-host-overheads/a"]


@pytest.mark.parametrize("d", [{}, {"selected_entries": {}}, {"selected_entries": {"coefficients": []}}])
def test_a_result_without_a_report_leaves_the_range_unevaluated(d):
    assert not g1.coefficient_range(d).evaluated


# ---- kernel_hash

VERSIONS = {"flashinfer": {"0.4.1": HASH, "0.5.0": OTHER}}


def test_a_recorded_version_that_maps_to_the_priced_hash_is_true_and_another_is_named():
    e = g1.kernel_hash(doc(), {"flashinfer": "0.4.1"}, VERSIONS)
    assert e.evaluated and e.subs == []
    e = g1.kernel_hash(doc(), {"flashinfer": "0.5.0"}, VERSIONS)
    assert e.subs == [{"kind": "kernel_hash", "subject": "flashinfer",
                       "detail": f"flashinfer 0.5.0 has kernel hash {OTHER}, BLIS priced {HASH}"}]
    assert g1.kernel_hash(doc(), {"flashinfer": "9.9"}, VERSIONS).subs[0]["detail"].startswith("flashinfer 9.9 maps to no")


def test_with_no_published_map_from_a_version_to_a_hash_the_condition_stays_unevaluated():
    # No source exists today (blis-registry#73); the scorer passes none.
    assert not g1.kernel_hash(doc(), {"flashinfer": "0.4.1"}).evaluated
    assert not g1.kernel_hash(doc(), {"flashinfer": "0.4.1"}, {}).evaluated


def test_a_missing_run_version_or_library_or_kernel_impl_leaves_it_unevaluated():
    assert not g1.kernel_hash(doc(), {}, VERSIONS).evaluated
    assert not g1.kernel_hash(doc(), {"flashinfer": "0.4.1"}, {"other": {}}).evaluated
    c = coeff()
    del c["kernel_impls"]
    assert not g1.kernel_hash(doc(c), {"flashinfer": "0.4.1"}, VERSIONS).evaluated


def test_a_coefficient_with_no_kernel_implementation_leaves_the_hash_unevaluated_not_skipped():
    for drop in ("kernel_impls",):
        fitted = coeff("b")
        del fitted[drop]
        assert not g1.kernel_hash(doc(coeff(), fitted), {"flashinfer": "0.4.1"}, VERSIONS).evaluated
    constant = {"set": "s", "name": "c", "method": "assumed", "scope": "h200", "file": "f.yaml"}
    assert not g1.kernel_hash(doc(coeff(), constant), {"flashinfer": "0.4.1"}, VERSIONS).evaluated   # the entry states none


def test_an_entry_listing_several_implementations_of_a_library_accepts_any_priced_hash():
    c = coeff(kernel_impls=[{"library": "flashinfer", "variant": "a", "code_hash": OTHER},
                            {"library": "flashinfer", "variant": "b", "code_hash": HASH}])
    assert g1.kernel_hash(doc(c), {"flashinfer": "0.4.1"}, VERSIONS).subs == []


# ---- value_class: the substrate's rules, pinned

NUMERIC = {"type": "numeric", "thresholds": [{"value": 64, "closed": "above"}, {"value": 512, "closed": "below"}],
           "covered_classes": [0, 2]}
ENUM = {"type": "enumerated", "covered": ["fp8", "auto"]}
BOOL = {"type": "boolean", "covered": ["true"]}


def test_a_numeric_class_counts_the_thresholds_below_the_value_and_a_closed_above_one_includes_equality():
    assert [fl.class_of(x, NUMERIC) for x in (1, 63, 64, 65, 512, 513)] == [0, 0, 1, 1, 1, 2]
    assert [fl.covers(x, NUMERIC) for x in (1, 64, 512, 513, 10000)] == [True, False, False, True, True]
    assert not fl.covers(True, NUMERIC)
    assert fl.covers("32", NUMERIC) and not fl.covers("64", NUMERIC) and not fl.covers("x", NUMERIC)   # a number written as text
    for bad in (float("nan"), float("inf"), float("-inf")):
        assert not fl.covers(bad, NUMERIC)


def test_a_numeric_field_with_no_thresholds_has_one_class():
    one = {"type": "numeric", "covered_classes": [0]}
    assert fl.class_of(5, one) == 0 and fl.covers(5, one) and not fl.covers(5, {"type": "numeric", "covered_classes": [1], "thresholds": [{"value": 9, "closed": "above"}]})
    field_list(one)                                              # the loader accepts it


def test_an_enumerated_or_boolean_value_is_covered_when_it_is_listed():
    assert fl.covers("fp8", ENUM) and not fl.covers("bf16", ENUM)
    assert fl.covers(True, BOOL) and not fl.covers(False, BOOL)


def test_a_value_inside_a_class_is_true_and_one_outside_is_named():
    fls = field_list(NUMERIC)
    assert g1.value_class({"max_num_seqs": 32}, fls).subs == []
    e = g1.value_class({"max_num_seqs": 100}, fls)
    assert e.evaluated and e.subs == [{"kind": "value_class", "subject": "max_num_seqs",
                                       "detail": "100 is outside every value class the evidence covers"}]


def test_a_modelled_field_without_classes_leaves_the_condition_unevaluated():
    assert not g1.value_class({"max_num_seqs": 32}, field_list(None)).evaluated


def test_a_setting_that_is_not_a_modelled_or_inert_field_is_not_asked():
    assert g1.value_class({"max_num_seqs": 32}, field_list(None, status="not_modelled")).evaluated
    assert g1.value_class({"nonesuch": 1}, field_list(NUMERIC)).evaluated


def test_the_field_list_loader_checks_value_classes():
    bad = [{"type": "numeric"},                                                                 # no covered classes
           {"type": "numeric", "thresholds": [{"value": 2, "closed": "above"}, {"value": 1, "closed": "above"}], "covered_classes": [0]},
           {"type": "numeric", "thresholds": [{"value": 1, "closed": "up"}], "covered_classes": [0]},
           {"type": "numeric", "thresholds": [{"value": 1, "closed": "above"}], "covered_classes": [2]},
           {"type": "enumerated"}, {"type": "enumerated", "covered": ["x"], "thresholds": []},
           {"type": "weird", "covered": ["x"]}, [], {"covered": ["x"]}]
    for b in bad:
        with pytest.raises(fl.FieldsError):
            field_list(b)
    with pytest.raises(fl.FieldsError, match="only a modelled or proven-inert"):
        field_list(NUMERIC, status="not_modelled")


# ---- resolved_value

RUN = {"tensor_parallel_size": 8, "data_parallel_size": 1, "enable_expert_parallel": False, "async_scheduling": True,
       "disable_custom_all_reduce": False, "disable_cascade_attn": True, "block_size": 16}


def test_each_resolution_setting_is_read_from_the_vllm_setting_it_answers():
    assert g1.run_value("tensor_parallel_width", RUN) == 8
    assert g1.run_value("data_parallel_width", RUN) == 1
    assert g1.run_value("expert_parallel_width", RUN) == 1                                 # expert parallel off
    assert g1.run_value("expert_parallel_width", {**RUN, "enable_expert_parallel": True, "data_parallel_size": 2,
                                                  "prefill_context_parallel_size": 2}) == 32
    assert g1.run_value("expert_parallel_width", {k: v for k, v in RUN.items() if k != "enable_expert_parallel"}) is None
    assert g1.run_value("all_reduce_backend", RUN) == "custom"
    assert g1.run_value("all_reduce_backend", {**RUN, "disable_custom_all_reduce": True}) == "nccl"
    assert g1.run_value("async_scheduling", RUN) == "true"
    assert g1.run_value("cascade_attention", RUN) == "false"                               # inverse of disable_cascade_attn
    assert g1.run_value("cascade_attention", {**RUN, "disable_cascade_attn": False}) == "true"
    assert g1.run_value("sequence_parallel_moe", RUN) is None                              # no single vLLM name
    assert g1.run_value("block_size", RUN) == 16                                           # a declined request: its own name


def test_a_resolved_value_equal_to_the_engines_is_true_and_a_different_one_is_named():
    d = doc(resolutions=[{"setting": "tensor_parallel_width", "pool": "colocated", "host": "8", "engine": "8"},
                         {"setting": "all_reduce_backend", "pool": "colocated", "engine": "custom"},
                         {"setting": "block_size", "pool": "colocated", "host": "32", "engine": "16", "reason": "the backend needs 16"}])
    assert g1.resolved_value(d, RUN).subs == []
    e = g1.resolved_value(d, {**RUN, "tensor_parallel_size": 4, "block_size": 32, "disable_custom_all_reduce": True})
    assert e.evaluated and [(s["subject"], s["detail"]) for s in e.subs] == [
        ("all_reduce_backend", "the run resolved 'nccl', the engine resolves 'custom'"),
        ("block_size", "the run resolved 32, the engine resolves '16'"),
        ("tensor_parallel_width", "the run resolved 4, the engine resolves '8'")]


def test_a_disaggregated_pointss_pools_are_compared_each_with_the_runs_value_for_that_pool():
    d = doc(resolutions=[{"setting": "tensor_parallel_width", "pool": "decode", "engine": "8"},
                         {"setting": "tensor_parallel_width", "pool": "prefill", "engine": "4"}])
    by_pool = {"prefill": {"tensor_parallel_size": 4}, "decode": {"tensor_parallel_size": 4}}
    e = g1.resolved_value(d, None, by_pool)
    assert e.evaluated and e.subs == [{"kind": "resolved_differs", "subject": "tensor_parallel_width (decode)",
                                       "detail": "the run resolved 4 in the decode pool, the engine resolves '8'"}]
    assert g1.resolved_value(d, None, {"prefill": {"tensor_parallel_size": 4}}).subs == []   # no values for decode: not compared


def test_a_setting_the_run_did_not_log_is_not_compared_and_no_resolutions_is_unevaluated():
    d = doc(resolutions=[{"setting": "expert_parallel_width", "engine": "8"}])
    assert g1.resolved_value(d, {"block_size": 16}).evaluated and g1.resolved_value(d, {"block_size": 16}).subs == []
    assert not g1.resolved_value(doc(), {"block_size": 16}).evaluated
    assert not g1.resolved_value(doc(resolutions=[]), {"block_size": 16}).evaluated


# ---- the point

def full_doc():
    return doc(resolutions=[{"setting": "block_size", "pool": "colocated", "engine": "16", "host": "16"}])


def all_true(**kw):
    return g1.evaluate(full_doc(), field_list=field_list(NUMERIC), requested={"max_num_seqs": kw.get("seqs", 32)},
                       resolved={"block_size": 16}, libraries={"flashinfer": "0.4.1"}, version_hashes=VERSIONS)


def test_a_point_with_every_datum_present_and_true_names_none_of_the_four():
    subs, unevaluated = g1.split(all_true())
    assert subs == [] and unevaluated == []
    assert sc.substitutions([], {}, unevaluated) == []


def test_the_scorer_today_leaves_kernel_hash_unevaluated_because_no_source_maps_versions_to_hashes():
    ev = g1.evaluate(full_doc(), field_list=field_list(NUMERIC), requested={"max_num_seqs": 32},
                     resolved={"block_size": 16}, libraries={"flashinfer": "0.4.1"})
    subs, unevaluated = g1.split(ev)
    assert unevaluated == ["kernel_hash"] and subs == []
    assert [(s["kind"], s["subject"]) for s in sc.substitutions([], {}, unevaluated)] == [("kernel_hash", "unevaluated")]


def test_a_condition_is_unevaluated_only_when_its_data_is_absent():
    ev = g1.evaluate(full_doc(), field_list=field_list(None), requested={"max_num_seqs": 32},
                     resolved={"block_size": 16}, libraries={}, version_hashes=VERSIONS)
    assert g1.split(ev) == ([], ["kernel_hash", "value_class"])
    # the Result of an older build carries none of it: all four stay unevaluated, as before
    old = {"selected_entries": {"coefficients": [{"set": "s", "name": "n", "method": "measured"}]}}   # no marker
    _, unevaluated = g1.split(g1.evaluate(old, field_list=field_list(None), requested={"max_num_seqs": 32}))
    assert sorted(unevaluated) == sorted(gr.UNCHECKED_KINDS)


def test_a_point_whose_four_conditions_are_true_is_g1_on_the_simulators_release():
    rel = gr.Release(version="0.32.0", nightly_or_custom=False)
    g = gr.grade(engine_version="0.32.0", release=rel, substitutions=sc.substitutions([], {}, []))
    assert g.grade == gr.G1
    g = gr.grade(engine_version="0.32.0", release=rel, substitutions=sc.substitutions([], {}, ["kernel_hash"]))
    assert g.grade == gr.G2


def test_a_false_condition_makes_the_point_g2():
    subs, unevaluated = g1.split(all_true(seqs=100))
    rel = gr.Release(version="0.32.0", nightly_or_custom=False)
    g = gr.grade(engine_version="0.32.0", release=rel, substitutions=sc.substitutions(subs, {}, unevaluated))
    assert unevaluated == [] and g.grade == gr.G2 and [s["kind"] for s in g.substitutions] == ["value_class"]
