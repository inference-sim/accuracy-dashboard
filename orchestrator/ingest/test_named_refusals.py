"""A simulator refusal is a named not-scored point; only a fault of the run stops a night (COV-1, COV-8; design §11.4).

The night of 2026-11-18 on main published nothing: 14 Kimi-K2.5 points were refused by the simulator
(`blis_refused:scenario`), the scorer listed them as failed, and the summary builder stopped the whole publish. A refusal the
simulator explains says something about the point; it is not a fault of the run. These tests feed such refusals through the
scorer's grading and the summary builder and hold the other side too: a crash, a limit of the runner, output the harness cannot
read and a lost setting still stop the night (or, for a runner limit, list the point as failed and let it publish).

Run: python3 -m pytest orchestrator/ingest/test_named_refusals.py
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import assess  # noqa: E402
import build_summary_v2 as b2  # noqa: E402
import contract as c  # noqa: E402
import score as sc  # noqa: E402
import validate_summary_v2 as vs2  # noqa: E402

FIXTURE = HERE / "testdata" / "contract"
STAMP = "2026-10-23T00:00:00Z"
RELEASE = "0.32.0"


def _graded(reasons):
    o = sc.Outcome(point_id="a" * 64, identity={}, row={"image": None}, reasons=list(reasons))
    sc.grade_outcome(o, RELEASE)
    return o


def test_the_simulators_own_refusal_is_a_named_not_scored_point_not_a_fault():
    o = _graded(["blis_refused:scenario"])
    assert o.faults == []
    assert o.g5_reasons == [{"code": "blis_refused", "subject": "scenario"}]
    assert o.g5 and o.g5["code"] == "blis_refused"


@pytest.mark.parametrize("reason", [
    "blis_refused:insufficient_memory",          # the runner's memory: a limit, listed as failed
    "blis_refused:timeout",                      # the runner's time: a limit, listed as failed
    "blis_refused:extractor_error",              # the extractor crashed
    "blis_refused:result_invalid",               # the simulator's output does not validate: malformed
    "blis_refused:result_unreadable",
    "blis_refused:metrics_incomplete",
    "blis_refused:requests_incomplete",
    "blis_refused:warmup_not_drained",
    "blis_refused:request_pattern: 3 in flight",
    "blis_crashed:panic_runtime_error",          # the simulator exited with no message of its own
    "setting_differs:max_num_seqs",              # the written scenario lost a recorded value
    "blis_refused",                              # a refusal with no slug names nothing
])
def test_a_real_fault_of_the_run_is_still_a_fault(reason):
    o = _graded([reason])
    assert o.faults == [reason] and not o.g5_reasons


def test_the_simulator_exiting_with_and_without_a_message_of_its_own():
    work = Path("/w")
    said = 'time=1 level=fatal msg="scenario \\"p-0123456789abcdef.yaml\\": kv cache does not fit the model"\n'
    assert sc._blis_refusal(said, work).startswith("blis_refused:")
    assert assess.is_named_refusal(sc._blis_refusal(said, work))
    for crash in ("panic: runtime error: index out of range\ngoroutine 1 [running]:\n", "", "Killed\n"):
        reason = sc._blis_refusal(crash, work)
        assert reason.startswith("blis_crashed") and assess.is_run_fault(reason) and not assess.is_named_refusal(reason)


def _run_b_with(tmp, fault):
    """Run b of the contract fixture holds one failed point (a timeout). Return a copy whose failed point carries `fault`."""
    d = Path(tmp) / "run-b"
    shutil.copytree(FIXTURE / "run-b", d)
    rec = json.loads((d / c.FAILED_JSONL).read_text().splitlines()[0])
    (d / c.FAILED_JSONL).write_text(c.canonical_dumps({**rec, "faults": [fault]}) + "\n")
    return d, rec


def _as_not_scored(d, rec, reason):
    """The same point as the scorer now writes it: a G5 point with the refusal as its reason, not a failed one."""
    template = json.loads((d / c.NOT_SCORED_JSONL).read_text().splitlines()[0])
    code, _, subject = reason.partition(":")
    g5 = {"code": "blis_refused", "subject": subject}
    row = {**template, **{k: rec[k] for k in rec if k in template and k not in ("g5_reason", "g5_reasons", "grade")},
           "g5_reason": g5, "g5_reasons": [g5], "grade": "G5"}
    rows = [json.loads(x) for x in (d / c.NOT_SCORED_JSONL).read_text().splitlines()] + [row]
    rows.sort(key=lambda r: r["point_id"])
    (d / c.NOT_SCORED_JSONL).write_text("".join(c.canonical_dumps(r) + "\n" for r in rows))
    (d / c.FAILED_JSONL).write_text("")
    return row


def test_the_night_of_2026_11_18_the_old_contract_stops_and_the_new_one_publishes_the_point_named():
    with tempfile.TemporaryDirectory() as tmp:
        # What the old scorer wrote for a simulator refusal: the point failed. The builder (unchanged for a real fault) stops.
        d, rec = _run_b_with(tmp, "blis_refused:scenario")
        with pytest.raises(b2.PublishRefused, match="COV-8"):
            b2.build(d, generated_at=STAMP, evaluator_commit="test")
        # What the scorer writes now: the same point, not scored, reason blis_refused:scenario. The night publishes it, named.
        row = _as_not_scored(d, rec, "blis_refused:scenario")
        doc = b2.build(d, generated_at=STAMP, evaluator_commit="test")
    named = [p for p in doc["not_scored"] if p["point_id"] == row["point_id"]]
    assert named and named[0]["g5_reason"] == {"code": "blis_refused", "subject": "scenario"}
    assert doc["failed"] == [] and doc["coverage"]["failed"] == 0
    assert doc["coverage"]["g5_reasons"]["blis_refused"] == 1                    # counted (COV-1), not dropped
    assert doc["coverage"]["points"] == 14 and doc["new_refusal_codes"] == []   # `scenario` is a known code
    # The headline is the graded points' alone: the same 8 graded points give the same figures whether the ninth point failed
    # at the runner's time limit or was refused by name.
    base = b2.build(FIXTURE / "run-b", generated_at=STAMP, evaluator_commit="test")
    assert doc["headline"]["grades"] == base["headline"]["grades"]
    assert {k: v for k, v in doc["headline"].items() if k not in ("points", "not_scored")} == \
        {k: v for k, v in base["headline"].items() if k not in ("points", "not_scored")}


def test_a_runner_limit_publishes_and_every_other_fault_still_stops():
    with tempfile.TemporaryDirectory() as tmp:
        for fault in ("blis_refused:timeout", "blis_refused:insufficient_memory"):
            d, _ = _run_b_with(tmp, fault)
            assert [f["faults"] for f in b2.build(d, generated_at=STAMP, evaluator_commit="test")["failed"]] == [[fault]]
            shutil.rmtree(d)
        for fault in ("blis_crashed:panic", "blis_refused:extractor_error", "blis_refused:result_invalid", "setting_differs:x"):
            d, _ = _run_b_with(tmp, fault)
            with pytest.raises(b2.PublishRefused):
                b2.build(d, generated_at=STAMP, evaluator_commit="test")
            shutil.rmtree(d)


def test_a_refusal_code_the_nightly_has_not_met_publishes_and_is_listed():
    with tempfile.TemporaryDirectory() as tmp:
        d, rec = _run_b_with(tmp, "blis_refused:timeout")
        _as_not_scored(d, rec, "blis_refused:batch_4096_too_large")
        doc = b2.build(d, generated_at=STAMP, evaluator_commit="test")
    assert doc["new_refusal_codes"] == ["batch_N_too_large"]


def test_refusal_codes_are_the_same_on_every_point_of_a_kind():
    assert assess.refusal_code("Failed_to_load_trace:_parsing_trace_header:_yaml") == "Failed_to_load_trace"
    assert assess.refusal_code("batch_4096_too_large") == assess.refusal_code("batch_512_too_large") == "batch_N_too_large"
    assert len(assess.refusal_code("x" * 200)) == 40


def test_the_validator_holds_new_refusal_codes_to_the_not_scored_points():
    with tempfile.TemporaryDirectory() as tmp:
        d, rec = _run_b_with(tmp, "blis_refused:timeout")
        _as_not_scored(d, rec, "blis_refused:batch_4096_too_large")
        doc = b2.build(d, generated_at=STAMP, evaluator_commit="test")
    assert doc["new_refusal_codes"] == ["batch_N_too_large"] and vs2.problems(doc) == []
    for wrong in ([], ["batch_N_too_large", "invented_code"]):
        bad = {**doc, "new_refusal_codes": wrong}
        assert any("new_refusal_codes does not recompute" in p for p in vs2.problems(bad)), wrong
