"""A setting the modelled vLLM release removed is read as the setting that replaced it, and the point says so (resolved_differs)."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fields as fl  # noqa: E402
import settings as st  # noqa: E402
import stand_in_facts as sif  # noqa: E402

MLA = {"rule": "none", "approximates": {"mode": {"attention_config.mla_prefill_backend": None}, "evidence": "pooled lanes",
       "differs": "ragged prefill kernel", "when": [{"value_in": ["trtllm_ragged"]}]}}


def _list(*rows):
    return fl.parse(json.dumps({"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.33.0"}, "fields": list(rows)}))


def _row(name, est=None, source="config"):
    return {"name": name, "source": source, "status": "not_modelled", "evidence": {"issue": "o/r#80"}, "estimation": est or {"rule": "none"}}


def _decide(flist, **vals):
    r = st.Reading()
    for k, v in vals.items():
        r.add(k.replace("__", "."), v)
    return st.decide(st.merge({"launch_config": r}, {}), flist, "b200", sif.facts_of(8, "10.0"))


def test_the_removed_ragged_prefill_flag_is_the_backend_that_replaced_it():
    c = _decide(_list(_row("attention_config.mla_prefill_backend", MLA)), attention_config__use_trtllm_ragged_deepseek_prefill=True)
    assert c.reasons == []
    kinds = {x["subject"]: x["kind"] for x in c.substitutions}
    assert kinds == {"attention_config.use_trtllm_ragged_deepseek_prefill": "resolved_differs",
                     "attention_config.mla_prefill_backend": "execution_mode"}


def test_a_removed_flag_stated_false_is_not_translated_and_stays_not_in_the_release():
    c = _decide(_list(_row("attention_config.mla_prefill_backend", MLA)), attention_config__use_trtllm_ragged_deepseek_prefill=False)
    assert c.reasons == ["field_not_in_release:attention_config.use_trtllm_ragged_deepseek_prefill"]


def test_a_removed_name_the_release_still_lists_is_not_translated():
    c = _decide(_list(_row("attention_config.mla_prefill_backend", MLA), _row("attention_config.use_trtllm_ragged_deepseek_prefill")),
                attention_config__use_trtllm_ragged_deepseek_prefill=True)
    assert c.reasons == ["field_not_modelled:attention_config.use_trtllm_ragged_deepseek_prefill"]


MOE_X = {"name": "moe_backend", "source": "config", "status": "modelled", "evidence": {"traces": ["t"]}, "estimation": {"rule": "none"}}
ACT_INERT = {"name": "quantization_config.moe.activation", "source": "config", "status": "inert_unproven",
             "evidence": {"note": "marked inert; no proof yet"}, "estimation": {"rule": "none"}}
TRANSLATED = {"name": "VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8", "source": "env", "status": "not_modelled", "evidence": {"issue": "o/r#276"},
              "estimation": {"rule": "substitute", "setting": {"moe_backend": "flashinfer_trtllm", "quantization_config.moe.activation": "mxfp8"},
                             "reason": "env_var_not_in_release: removed", "preserves": "the MoE kernel the run used",
                             "valid_when": [{"value_in": ["1", "true"], "compute_capability": {"gte": "10.0", "lt": "11.0"}}]}}


def test_a_substitution_whose_second_setting_is_inert_names_it_and_loses_nothing():
    """The translated MXFP8 variable states moe_backend and quantization_config.moe.activation; the scenario has no place for the
    second, which the engine calls inert, so it is not a setting the written scenario lost."""
    c = _decide(_list(TRANSLATED, MOE_X, ACT_INERT), env__VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8=True)
    assert "setting_differs:quantization_config.moe.activation" not in c.reasons
    assert any(a["arg"] == "quantization_config.moe.activation" and a["match"] == "inert" for a in c.args)
