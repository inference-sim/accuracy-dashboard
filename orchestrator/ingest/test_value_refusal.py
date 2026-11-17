"""An engine refusal that says the scenario lacks a value is a G5 reason about that value."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import score as sc  # noqa: E402

THINKING = ('time="2026-11-10T20:00:00-05:00" level=fatal msg="scenario \\"p-1.yaml\\" drafts 2 \\"mtp\\" tokens, and its '
            'acceptance does not resolve: registry acceptance: the workload states no thinking mode, which selects the '
            'profile; state one ([off on]) or override the acceptance."')


def test_a_workload_with_no_thinking_mode_is_a_workload_statement_not_a_missing_field(tmp_path):
    assert sc.value_refusal(THINKING, tmp_path, None) == "required_setting_missing:workload.thinking_mode"


def test_the_workload_reason_is_not_looked_up_in_the_field_list(tmp_path):
    import fields as fl
    import json
    fls = fl.parse(json.dumps({"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.32.0"}, "fields": []}))
    # the field `thinking` is in no list, which used to give field_not_in_release:thinking
    assert sc.value_refusal(THINKING, tmp_path, fls) == "required_setting_missing:workload.thinking_mode"


def test_a_scenario_that_states_no_field_is_still_read_as_a_field(tmp_path):
    err = 'level=fatal msg="scenario \\"p-1.yaml\\" states no max_model_len: the engine cannot resolve it"'
    assert sc.value_refusal(err, tmp_path, None) == "required_setting_missing:max_model_len"


def test_an_unrelated_refusal_is_not_a_missing_value(tmp_path):
    assert sc.value_refusal('level=fatal msg="something else"', tmp_path, None) is None


NOT_MODELLED = ('time="2026-11-16T21:15:49-05:00" level=fatal msg="scenario \\"p-1.yaml\\": deepseek KV layers: layer kind '
                'csa4_hash_moe: indexer_kv_dtype \\"mxfp4\\" runs as mxfp4, a key record of 68 bytes for an index head of 128, '
                'and the catalog graph\'s index cache states 132; the latency kernel keys the index record by one cache dtype '
                'and prices the graph\'s, so this indexer dtype is not modelled (https://github.com/inference-sim/blis-vllm/issues/84)"')


def test_a_value_the_engine_says_it_does_not_model_is_g5_field_not_modelled_by_the_fields_path(tmp_path):
    # The release's own classification of the run's setting, not a fault of the harness: the point is G5 and the
    # night goes on, where blis_refused would stop the publish (COV-8).
    import fields as fl
    import json
    fls = fl.parse(json.dumps({"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.32.0"}, "fields": [
        {"name": "attention_config.indexer_kv_dtype", "source": "config", "status": "modelled",
         "evidence": {"traces": ["t"]}, "estimation": {"rule": "none"}}]}))
    assert sc.value_refusal(NOT_MODELLED, tmp_path, fls) == "field_not_modelled:attention_config.indexer_kv_dtype"
    assert sc.value_refusal(NOT_MODELLED, tmp_path, None) == "field_not_modelled:indexer_kv_dtype"


# The kernel's refusals begin with their own code (blis-substrate kernel/draft.go).
DRAFT_UNSTATED = ('time="2026-11-17T08:00:00-05:00" level=fatal msg="kernelmodel: draft_passes_unstated: the \\"mtp\\" drafter '
                  'drafts autoregressively and the engine states no DraftPassRequests, so its first pass over the step\'s '
                  'tokens would be priced by guess; the pool\'s plan must state it (sampling or all)"')


def test_a_kernel_refusal_is_g5_engine_unsupported_naming_the_kernels_code_not_a_missing_field(tmp_path):
    import fields as fl
    import json
    fls = fl.parse(json.dumps({"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.32.0"}, "fields": []}))
    # It used to read "states no DraftPassRequests" as a field of the engine's list: field_not_in_release:DraftPassRequests
    # with a list, required_setting_missing:DraftPassRequests without one.
    assert sc.value_refusal(DRAFT_UNSTATED, tmp_path, fls) == "engine_unsupported:draft_passes_unstated"
    assert sc.value_refusal(DRAFT_UNSTATED, tmp_path, None) == "engine_unsupported:draft_passes_unstated"
    unknown = 'level=fatal msg="kernelmodel: draft_passes_unknown: DraftPassRequests is \\"some\\" for the mtp drafter; it is sampling or all"'
    assert sc.value_refusal(unknown, tmp_path, None) == "engine_unsupported:draft_passes_unknown"


def test_a_refusal_that_merely_mentions_a_kernel_code_inside_a_word_is_not_a_kernel_refusal(tmp_path):
    err = 'level=fatal msg="scenario \\"p-1.yaml\\" states no max_model_len: see my_draft_passes_unstated: x"'
    assert sc.value_refusal(err, tmp_path, None) == "required_setting_missing:max_model_len"


# The refusal of inference-sim v0.18.0 for a Kimi K2.5 point (accuracy-dashboard#126): the run's recorded vLLM default was
# stated for a model that has no indexer cache. The simulator's message, as blis wrote it, with the path removed.
NOT_READ = ('time="2026-11-17T18:21:21-05:00" level=fatal msg="scenario \\"p-d6687daeb9104dec.yaml\\": '
            'indexer_kv_dtype=\\"bf16\\" is read only for MiniMax-M3\'s indexer cache, and this model has none, so a '
            'stated value would be dropped (https://github.com/inference-sim/blis-substrate/issues/1)"')


def test_a_value_stated_for_a_part_the_model_lacks_is_a_named_g5_not_the_slug_scenario(tmp_path):
    # Cut to 80 characters after the scenario's name, this message was the bare slug "scenario", and a failure that is
    # not a runner limit stops the whole night (COV-8). It names the field now (COV-1: a bad row is a G5, never an abort).
    assert sc._blis_refusal(NOT_READ, tmp_path) == "blis_refused:scenario"       # what it used to be
    assert sc.value_refusal(NOT_READ, tmp_path, None) == "field_not_modelled:indexer_kv_dtype"


def test_the_field_is_named_by_its_path_in_the_field_list(tmp_path):
    import fields as fl
    import json
    fls = fl.parse(json.dumps({"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.33.0"}, "fields": [
        {"name": "attention_config.indexer_kv_dtype", "source": "config", "status": "modelled",
         "evidence": {"traces": ["t"]}, "estimation": {"rule": "none"}}]}))
    assert sc.value_refusal(NOT_READ, tmp_path, fls) == "field_not_modelled:attention_config.indexer_kv_dtype"


def test_a_refusal_that_is_not_about_an_unread_part_is_not_taken_for_one(tmp_path):
    other = ('level=fatal msg="scenario \\"p-1.yaml\\": cache_dtype=\\"fp4\\" is read only for the draft, in a graph that '
             'is shared"')
    assert sc.value_refusal(other, tmp_path, None) is None
