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


def test_the_kv_cache_dtype_block_key_follows_the_field_lists_classification():
    def mapped(status):
        ev = {"traces": ["t"]} if status == "modelled" else {"issue": "x/y#1"}
        f = [{"name": "kv_cache_dtype", "source": "config", "status": status, "evidence": ev, "estimation": {"rule": "none"}}]
        fls = fl.parse(json.dumps({"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.32.0"}, "fields": f}))
        return st.decide({"kv_cache_dtype": st.Setting(path="kv_cache_dtype", value="fp8", source="resolved_config")}, fls).mapped
    assert "engine.cache_dtype" in mapped("not_modelled") and "engine.kv_cache_dtype" not in mapped("not_modelled")
    assert "engine.kv_cache_dtype" in mapped("modelled") and "engine.cache_dtype" not in mapped("modelled")
