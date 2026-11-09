"""The engine's field list is read strictly, and Decide and Estimate follow it alone (COV-3).

Run: python3 -m pytest orchestrator/ingest/test_fields.py
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fields as fl  # noqa: E402


def _field(name, status, rule="none", source="config", **est):
    ev = {"modelled": {"traces": ["oracle/traces/t.json"]}, "proven_inert": {"proof": "TestX"},
          "not_modelled": {"issue": "inference-sim/blis-vllm#1"}, "inert_unproven": {"note": "believed inert"}}[status]
    return {"name": name, "source": source, "status": status, "evidence": ev, "estimation": {"rule": rule, **est}}


def _doc(*fields):
    return {"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.32.0"},
            "fields": sorted(fields, key=lambda f: (f["name"], f["source"]))}


LIST = fl.parse(json.dumps(_doc(
    _field("max_num_seqs", "modelled"),
    _field("host", "inert_unproven", "leave_unset"),
    _field("attention_config.backend", "not_modelled", "leave_unset"),
    _field("linear_backend", "not_modelled"),
    _field("quantization", "not_modelled", "substitute", setting={"quantization": "fp8"},
           reason="same 1-byte weights"),
    _field("kv_transfer_config.kv_connector_extra_config", "modelled", "leave_unset"),
    _field("max_model_len", "modelled", "leave_unset"),
    _field("block_size", "modelled"),
    _field("VLLM_ROCM_USE_AITER", "not_modelled", source="env"),
    _field("seed", "proven_inert", "leave_unset"),
)))


def test_a_modelled_or_proven_inert_field_changes_no_grade():
    for p in ("max_num_seqs", "seed"):
        d = fl.decide(LIST, p, set_by_run=True)
        assert d.substitution is None and d.g5 is None


def test_an_unproven_inert_field_the_run_sets_is_named_on_the_point():
    d = fl.decide(LIST, "host", set_by_run=True)
    assert d.substitution["kind"] == "interim_status" and d.g5 is None


def test_a_not_modelled_field_takes_its_estimation_rule_or_makes_the_point_g5():
    assert fl.decide(LIST, "attention_config.backend", set_by_run=True).substitution["kind"] == "estimated"
    sub = fl.decide(LIST, "quantization", set_by_run=True).substitution
    assert sub["kind"] == "estimated" and '"fp8"' in sub["detail"] and "same 1-byte weights" in sub["detail"]
    assert fl.decide(LIST, "linear_backend", set_by_run=True).g5 == {"code": "field_not_modelled",
                                                                       "subject": "linear_backend"}
    assert fl.decide(LIST, "env.VLLM_ROCM_USE_AITER", set_by_run=True).g5["code"] == "field_not_modelled"


def test_a_field_the_run_left_to_the_engine_changes_nothing():
    d = fl.decide(LIST, "linear_backend", set_by_run=False)
    assert d.substitution is None and d.g5 is None


def test_a_field_the_release_does_not_have_is_field_not_in_release():
    assert fl.decide(LIST, "monokernel", set_by_run=True).g5 == {"code": "field_not_in_release",
                                                                  "subject": "monokernel"}


def test_a_path_under_a_config_object_takes_the_objects_field():
    f = LIST.lookup("kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use")
    assert f is not None and f.name == "kv_transfer_config.kv_connector_extra_config"


def test_a_missing_value_takes_its_estimation_rule_or_is_value_not_recorded():
    assert fl.estimate_missing(LIST, "max_model_len").substitution["kind"] == "estimated"
    assert fl.estimate_missing(LIST, "block_size").g5 == {"code": "value_not_recorded", "subject": "block_size"}


@pytest.mark.parametrize("mutate,match", [
    (lambda d: d.update(extra=1), "unknown key"),
    (lambda d: d["fields"][0].update(why="x"), "unknown key"),
    (lambda d: d["fields"][0]["evidence"].update(issue="o/r#1"), "takes exactly"),
    (lambda d: d["fields"][0].update(status="mapped"), "status"),
    (lambda d: d["fields"][0]["estimation"].update(rule="substitute"), "setting and a reason"),
    (lambda d: d["fields"][0]["estimation"].update(reason="x"), "only with rule"),
    (lambda d: d["fields"].reverse(), "out of order"),
    (lambda d: d.update(kind="Fields"), "kind"),
])
def test_the_loader_refuses_what_contracts_spec_fields_refuses(mutate, match):
    d = _doc(_field("a", "modelled"), _field("b", "modelled"))
    mutate(d)
    with pytest.raises(fl.FieldsError, match=match):
        fl.parse(json.dumps(d))


def test_the_loader_refuses_a_duplicate_key():
    text = json.dumps(_doc(_field("a", "modelled"))).replace('"kind": "FieldList"', '"kind": "FieldList", "kind": "FieldList"')
    with pytest.raises(fl.FieldsError, match="duplicate"):
        fl.parse(text)
