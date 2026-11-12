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


# ---- COV-12: the send gap and the host_completion coefficient are one unmeasured quantity (777 us); the backlog counts it once

GAP = {"kind": "client_difference", "subject": "send_gap"}
HOST = {"kind": "coefficient_method", "subject": "h200-set/host_completion"}
OTHER = {"kind": "coefficient_method", "subject": "h200-set/attention"}


def test_the_send_gap_and_the_host_completion_coefficient_are_counted_once_per_point():
    pts = [{"framework": "vllm", "grade": "G2", "substitutions": [GAP, HOST, OTHER]} for _ in range(3)]
    v = {e["entry"]: e for e in bl.build(pts)["vllm"]}
    assert v["coefficient_method:h200-set/host_completion"]["demotes"] == 3
    assert "client_difference:send_gap" not in v                          # the alias adds nothing
    assert sum(e["demotes"] for e in v.values()) == 6                     # two causes per point, not three
    top = dict(bl.top(pts))
    assert top == {"coefficient_method: h200-set/host_completion": 3, "coefficient_method: h200-set/attention": 3}


def test_a_send_gap_with_no_host_completion_demoter_on_the_point_still_counts():
    pts = [{"framework": "vllm", "grade": "G2", "substitutions": [GAP, OTHER]}]
    assert {e["entry"] for e in bl.build(pts)["vllm"]} == {"client_difference:send_gap", "coefficient_method:h200-set/attention"}
    assert dict(bl.top(pts)) == {"client_difference: send_gap": 1, "coefficient_method: h200-set/attention": 1}
