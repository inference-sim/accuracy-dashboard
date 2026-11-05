"""The blocker backlog ranks every blocker by the points it blocks or demotes (design §11.6).

Run: python3 -m pytest orchestrator/ingest/test_backlog.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backlog as bl  # noqa: E402

F = {"code": "field_not_modelled", "subject": "linear_backend"}
C = {"code": "not_in_catalog", "subject": "mi355x"}
PTS = [
    {"framework": "vllm", "grade": "G5", "g5_reasons": [F]},
    {"framework": "vllm", "grade": "G5", "g5_reasons": [F, C]},
    {"framework": "vllm", "grade": "G5", "g5_reasons": [C]},
    {"framework": "vllm", "grade": "G5", "g5_reasons": [C]},
    {"framework": "vllm", "grade": "G2", "substitutions": [{"kind": "estimated", "subject": "max_model_len"}]},
    {"framework": "sglang", "grade": "G5", "g5_reasons": [{"code": "engine_unsupported", "subject": "sglang"}]},
    {"framework": "vllm", "grade": "G1"},
]


def test_each_engines_blockers_are_ranked_by_the_points_fixing_them_alone_would_grade():
    b = bl.build(PTS)
    v = b["vllm"]
    assert [e["entry"] for e in v] == ["not_in_catalog:mi355x", "field_not_modelled:linear_backend",
                                        "estimated:max_model_len"]
    assert v[0] == {"entry": "not_in_catalog:mi355x", "blocks": 3, "alone": 2, "demotes": 0}
    assert v[2]["demotes"] == 1
    assert b["sglang"][0]["entry"] == "engine_unsupported:sglang"


def test_the_most_common_reasons_a_point_is_not_g1():
    assert bl.top(PTS, 2) == [("G5 not_in_catalog: mi355x", 3), ("G5 field_not_modelled: linear_backend", 2)]


def test_the_top_reasons_do_not_depend_on_the_order_of_the_points():
    tied = [{"framework": "vllm", "grade": "G2", "substitutions": [{"kind": "estimated", "subject": s}]}
            for s in ("b", "a")]
    assert bl.top(tied) == bl.top(tied[::-1]) == [("estimated: a", 1), ("estimated: b", 1)]
