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
    # The simulator's own refusal is a named not-scored reason (design 11.4); a fault of the run and a reason the scorer
    # invented are not on the list.
    assert asx.g5_of("blis_refused:scenario") == {"code": "blis_refused", "subject": "scenario"}
    for not_listed in ("setting_differs:max_num_seqs", "blis_crashed:panic", "something_new"):
        with pytest.raises(asx.AssessError, match="COV-5"):
            asx.g5_of(not_listed)


def test_a_router_blis_does_not_host_is_router_unsupported():
    assert asx.router_reason({"metrics": {"router_name": "vllm-router"}}, None) == ["router_unsupported:vllm-router"]
    assert asx.router_reason({"metrics": {}}, "dynamo-router") == ["router_unsupported:dynamo-router"]
    assert asx.router_reason({"metrics": {"router_name": "llm-d-router"}}, None) == []
    assert asx.router_reason({"metrics": {}}, None) == []
