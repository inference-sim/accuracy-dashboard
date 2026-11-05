"""The scorer's findings become grade inputs on design §11.4's list only (COV-5).

Run: python3 -m pytest orchestrator/ingest/test_assess.py
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assess as asx  # noqa: E402
import grade as gr  # noqa: E402


def test_every_scorer_reason_maps_onto_the_closed_list():
    assert set(asx.G5_FOR_REASON.values()) <= set(gr.G5_CODES)
    assert asx.g5_of("model_not_in_catalog") == {"code": "not_in_catalog"}
    assert asx.g5_of("conflict:max_num_seqs") == {"code": "value_conflict", "subject": "max_num_seqs"}
    with pytest.raises(asx.AssessError, match="COV-5"):
        asx.g5_of("blis_refused:something")


def test_a_router_blis_does_not_host_is_router_unsupported():
    assert asx.router_reason({"metrics": {"router_name": "vllm-router"}}, None) == ["router_unsupported:vllm-router"]
    assert asx.router_reason({"metrics": {}}, "dynamo-router") == ["router_unsupported:dynamo-router"]
    assert asx.router_reason({"metrics": {"router_name": "llm-d-router"}}, None) == []
    assert asx.router_reason({"metrics": {}}, None) == []


def test_an_engine_no_blis_repository_models_is_engine_unsupported():
    assert asx.engine_reason({"framework": "sglang"}, {"vllm"}) == ["engine_unsupported:sglang"]
    assert asx.engine_reason({"framework": "vllm"}, {"vllm"}) == []
