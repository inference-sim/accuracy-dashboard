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
