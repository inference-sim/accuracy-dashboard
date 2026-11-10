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
    return {"set": "cost-model-host-overheads", "name": name, "method": "measured", "scope": "h200", "file": "f.yaml",
            "extrapolated": False, "unidentified": False,
            "kernel_impl": {"library": "flashinfer", "variant": "decode", "code_hash": HASH,
                            "library_versions": {"0.4.1": HASH, "0.5.0": OTHER}}, **kw}


def doc(*cs, resolutions=None):
    d = {"selected_entries": {"coefficients": list(cs) or [coeff()]}}
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

def test_a_coefficient_with_both_flags_false_is_evaluated_and_names_nothing():
    e = g1.coefficient_range(doc())
    assert e.evaluated and e.subs == []


def test_an_extrapolated_or_unidentified_coefficient_is_named_with_its_fit_range():
    e = g1.coefficient_range(doc(coeff("a", extrapolated=True, fit_range=[1, 64]), coeff("b", unidentified=True),
                                 coeff("c")))
    assert e.evaluated
    assert e.subs == [{"kind": "coefficient_range", "subject": "cost-model-host-overheads/a",
                       "detail": "extrapolated, fit range [1, 64]"},
                      {"kind": "coefficient_range", "subject": "cost-model-host-overheads/b", "detail": "unidentified"}]


@pytest.mark.parametrize("d", [{}, {"selected_entries": {}}, {"selected_entries": {"coefficients": []}}])
def test_a_result_without_a_report_leaves_the_range_unevaluated(d):
    assert not g1.coefficient_range(d).evaluated


def test_one_coefficient_without_flags_leaves_the_condition_unevaluated():
    c = coeff()
    del c["unidentified"]
    assert not g1.coefficient_range(doc(coeff("a", extrapolated=True), c)).evaluated


# ---- kernel_hash

def test_a_recorded_version_that_maps_to_the_priced_hash_is_evaluated_and_true():
    e = g1.kernel_hash(doc(), {"flashinfer": "0.4.1"})
    assert e.evaluated and e.subs == []


def test_a_version_with_another_hash_or_none_is_a_substitution():
    e = g1.kernel_hash(doc(), {"flashinfer": "0.5.0"})
    assert e.evaluated and e.subs == [{"kind": "kernel_hash", "subject": "flashinfer",
                                       "detail": f"flashinfer 0.5.0 has kernel hash {OTHER}, BLIS priced {HASH}"}]
    e = g1.kernel_hash(doc(), {"flashinfer": "9.9"})
    assert e.subs[0]["detail"] == f"flashinfer 9.9 maps to no kernel hash, BLIS priced {HASH}"


def test_no_recorded_version_or_no_kernel_impl_or_no_hash_map_leaves_it_unevaluated():
    assert not g1.kernel_hash(doc(), {}).evaluated                  # the run records no version
    assert not g1.kernel_hash(doc(), None).evaluated
    c = coeff()
    del c["kernel_impl"]
    assert not g1.kernel_hash(doc(c), {"flashinfer": "0.4.1"}).evaluated
    c = coeff()
    del c["kernel_impl"]["library_versions"]
    assert not g1.kernel_hash(doc(c), {"flashinfer": "0.4.1"}).evaluated


# ---- value_class

CLASSES = [{"name": "small", "min": 1, "max": 64}, {"name": "named", "values": [128, 256]}]


def test_a_value_inside_a_class_is_true_and_one_outside_is_named():
    fls = field_list(CLASSES)
    assert g1.value_class({"max_num_seqs": 32}, fls).subs == []
    assert g1.value_class({"max_num_seqs": 256}, fls).subs == []
    e = g1.value_class({"max_num_seqs": 100}, fls)
    assert e.evaluated and e.subs == [{"kind": "value_class", "subject": "max_num_seqs",
                                       "detail": "100 is outside every value class the evidence covers"}]
    assert g1.value_class({"max_num_seqs": True}, fls).subs      # a boolean is not a number in a range


def test_a_modelled_field_without_classes_leaves_the_condition_unevaluated():
    assert not g1.value_class({"max_num_seqs": 32}, field_list(None)).evaluated


def test_a_setting_that_is_not_a_modelled_field_is_not_asked():
    assert g1.value_class({"max_num_seqs": 32}, field_list(None, status="not_modelled")).evaluated
    assert g1.value_class({"nonesuch": 1}, field_list(CLASSES)).evaluated


def test_the_field_list_loader_checks_value_classes():
    for bad in ([], [{"name": "x"}], [{"name": "x", "values": [1], "min": 0}], [{"values": [1]}]):
        with pytest.raises(fl.FieldsError):
            field_list(bad)
    with pytest.raises(fl.FieldsError, match="only a modelled field"):
        field_list(CLASSES, status="not_modelled")


# ---- resolved_value

def test_a_resolved_value_equal_to_the_engines_is_true_and_a_different_one_is_named():
    d = doc(resolutions=[{"setting": "max_num_batched_tokens", "engine": 8192, "host": 8192},
                         {"setting": "block_size", "engine": 16, "host": 16}])
    assert g1.resolved_value(d, {"max_num_batched_tokens": 8192, "block_size": 16}).subs == []
    e = g1.resolved_value(d, {"max_num_batched_tokens": 16384, "block_size": 16})
    assert e.evaluated and e.subs == [{"kind": "resolved_differs", "subject": "max_num_batched_tokens",
                                       "detail": "the run resolved 16384, the engine resolves 8192"}]


def test_a_result_with_no_resolutions_leaves_it_unevaluated():
    assert not g1.resolved_value(doc(), {"block_size": 16}).evaluated
    assert not g1.resolved_value(doc(resolutions=[]), {"block_size": 16}).evaluated


# ---- the point

def full_doc():
    return doc(resolutions=[{"setting": "block_size", "engine": 16, "host": 16}])


def test_a_point_with_every_datum_present_and_true_names_none_of_the_four():
    ev = g1.evaluate(full_doc(), field_list=field_list(CLASSES), requested={"max_num_seqs": 32},
                     resolved={"block_size": 16}, libraries={"flashinfer": "0.4.1"})
    subs, unevaluated = g1.split(ev)
    assert subs == [] and unevaluated == []
    assert sc.substitutions([], {}, unevaluated) == []


def test_a_point_names_a_condition_unevaluated_only_when_its_data_is_absent():
    ev = g1.evaluate(full_doc(), field_list=field_list(None), requested={"max_num_seqs": 32},
                     resolved={"block_size": 16}, libraries={})
    subs, unevaluated = g1.split(ev)
    assert unevaluated == ["kernel_hash", "value_class"] and subs == []
    names = [(s["kind"], s["subject"]) for s in sc.substitutions([], {}, unevaluated)]
    assert names == [("kernel_hash", "unevaluated"), ("value_class", "unevaluated")]
    # the Result of an older build carries none of it: all four stay unevaluated, as before
    _, unevaluated = g1.split(g1.evaluate({"selected_entries": {"coefficients": [{"set": "s", "name": "n", "method": "measured"}]}},
                                          field_list=field_list(None), requested={"max_num_seqs": 32}))
    assert sorted(unevaluated) == sorted(gr.UNCHECKED_KINDS)


def test_a_point_whose_four_conditions_are_true_is_g1_on_the_simulators_release():
    rel = gr.Release(version="0.32.0", nightly_or_custom=False)
    g = gr.grade(engine_version="0.32.0", release=rel, substitutions=sc.substitutions([], {}, []))
    assert g.grade == gr.G1
    g = gr.grade(engine_version="0.32.0", release=rel, substitutions=sc.substitutions([], {}, ["kernel_hash"]))
    assert g.grade == gr.G2


def test_a_false_condition_makes_the_point_g2():
    ev = g1.evaluate(full_doc(), field_list=field_list(CLASSES), requested={"max_num_seqs": 100},
                     resolved={"block_size": 16}, libraries={"flashinfer": "0.4.1"})
    subs, unevaluated = g1.split(ev)
    rel = gr.Release(version="0.32.0", nightly_or_custom=False)
    g = gr.grade(engine_version="0.32.0", release=rel, substitutions=sc.substitutions(subs, {}, unevaluated))
    assert unevaluated == [] and g.grade == gr.G2 and [s["kind"] for s in g.substitutions] == ["value_class"]
