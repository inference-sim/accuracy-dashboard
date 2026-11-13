"""A block key that only a modelling blis-vllm release has is written only when the field list models the field."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fields as fl  # noqa: E402
import settings as st  # noqa: E402


def fields_with(status):
    ev = {"traces": ["t"]} if status == "modelled" else {"issue": "x/y#1"}
    f = [{"name": n, "source": "config", "status": status, "evidence": ev, "estimation": {"rule": "none"}}
         for n in ("enable_chunked_prefill", "language_model_only")]
    return fl.parse(json.dumps({"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.32.0"}, "fields": f}))


def decided(status, requested=False):
    s = {n: st.Setting(path=n, value=True, source="resolved_config", requested=requested)
         for n in ("enable_chunked_prefill", "language_model_only")}
    return st.decide(s, fields_with(status))


def test_a_modelled_field_is_written_to_the_engine_block():
    c = decided("modelled")
    assert c.mapped["engine.enable_chunked_prefill"][1] is True and c.mapped["engine.language_model_only"][1] is True
    assert c.reasons == []


def test_a_resolved_value_of_a_field_the_list_does_not_model_is_not_written():
    # v0.16.0's engine block has no such key and refuses the scenario that carries it.
    c = decided("not_modelled")
    assert "engine.enable_chunked_prefill" not in c.mapped and "engine.language_model_only" not in c.mapped
    assert c.reasons == []


def test_a_requested_value_of_such_a_field_is_still_the_field_lists_to_refuse():
    c = decided("not_modelled", requested=True)
    assert sorted(c.reasons) == ["field_not_modelled:enable_chunked_prefill", "field_not_modelled:language_model_only"]
    assert not any(k.startswith("engine.") for k in c.mapped)


def test_the_engine_block_takes_vllms_names_when_the_field_list_is_the_m2_one():
    eng = {"max_num_seqs": 8, "cache_dtype": "fp8", "cudagraph_mode": "FULL", "max_cudagraph_capture_size": 512,
           "speculative": {"method": "eagle3", "num_spec_tokens": 3, "draft_model": "d"}, "eplb": {"enable_eplb": True, "window_size": 5},
           "dbo": {"enable_dbo": True}, "indexer_kv_dtype": "fp8", "env": {"X": "1"}}
    out = st.to_vllm_block(eng)
    assert out == {"max_num_seqs": 8, "kv_cache_dtype": "fp8", "max_cudagraph_capture_size": 512,
                   "compilation_config": {"cudagraph_mode": "FULL"},
                   "speculative_config": {"method": "eagle3", "num_speculative_tokens": 3, "model": "d"},
                   "enable_eplb": True, "eplb_config": {"window_size": 5}, "enable_dbo": True,
                   "attention_config": {"indexer_kv_dtype": "fp8"}, "env": {"X": "1"}}
    assert "cache_dtype" in eng                                  # the argument is not changed


def test_the_m2_field_list_is_told_by_its_value_classes():
    assert st.names_are_vllms(fields_with("modelled")) is False          # no classes: the earlier block
    f = fl.parse(json.dumps({"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.32.0"}, "fields": [
        {"name": "language_model_only", "source": "config", "status": "modelled", "evidence": {"traces": ["t"]},
         "value_classes": {"type": "boolean", "covered": ["true"]}, "estimation": {"rule": "none"}}]}))
    assert st.names_are_vllms(f) is True


def test_a_location_is_translated_to_vllms_name_and_the_rest_are_unchanged():
    assert st.vllm_location("engine.cache_dtype") == "engine.kv_cache_dtype"
    assert st.vllm_location("engine.cudagraph_mode") == "engine.compilation_config.cudagraph_mode"
    assert st.vllm_location("engine.speculative.num_spec_tokens") == "engine.speculative_config.num_speculative_tokens"
    assert st.vllm_location("engine.max_num_seqs") == "engine.max_num_seqs" and st.vllm_location("parallel.tp") == "parallel.tp"
