"""An SGLang point's speculative method, read the way an InferenceX row states it (sglang_settings.spec_method_of),
so that row_vs_run (score.py) does not call the row false when the run did what the row says.

Run: python3 -m pytest orchestrator/ingest/test_sglang_spec_method.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import score as sc  # noqa: E402
import settings as st  # noqa: E402
import sglang_settings as ss  # noqa: E402


@pytest.mark.parametrize("algorithm,drafter,want", [
    ("EAGLE", None, "mtp"),        # no draft model: the checkpoint's own multi-token-prediction layer
    ("NEXTN", None, "mtp"),        # SGLang resolves NEXTN to EAGLE (speculative_hook.py)
    ("eagle", None, "mtp"),
    ("EAGLE", "org/draft", "eagle"),
    ("EAGLE3", "org/draft", "eagle3"),
    (None, None, None),
])
def test_the_method_a_row_states_for_a_speculative_algorithm(algorithm, drafter, want):
    assert ss.spec_method_of(algorithm, drafter) == want


def _decided(algorithm=None, drafter=None):
    c = st.Decided()
    if algorithm:
        c.mapped["engine.speculative_algorithm"] = ("speculative_algorithm", algorithm)
    if drafter:
        c.roles["drafter"] = drafter
    return c


def test_an_mtp_row_run_with_eagle_and_no_drafter_is_not_a_conflict():
    row = {"framework": "sglang", "spec_method": "mtp", "disagg": True}
    assert "conflict:spec_method" not in sc.row_vs_run(row, _decided("EAGLE"))


def test_an_mtp_row_whose_run_names_a_draft_model_is_a_conflict():
    row = {"framework": "sglang", "spec_method": "mtp", "disagg": True}
    assert "conflict:spec_method" in sc.row_vs_run(row, _decided("EAGLE", "org/draft"))


def test_an_mtp_row_whose_run_set_no_algorithm_is_a_conflict():
    row = {"framework": "sglang", "spec_method": "mtp", "disagg": True}
    assert "conflict:spec_method" in sc.row_vs_run(row, _decided())


def test_a_row_without_speculation_is_not_a_conflict_for_a_run_without_it():
    row = {"framework": "sglang", "spec_method": "none", "disagg": True}
    assert "conflict:spec_method" not in sc.row_vs_run(row, _decided())


def test_a_vllm_row_is_read_as_before():
    row = {"framework": "vllm", "spec_method": "mtp", "disagg": True}
    c = _decided()
    c.mapped["engine.speculative.method"] = ("speculative_config.method", "mtp")
    assert "conflict:spec_method" not in sc.row_vs_run(row, c)
    assert "conflict:spec_method" in sc.row_vs_run(row, _decided())
