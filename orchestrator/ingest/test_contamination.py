"""A measurement whose server log holds other requests than its client sent is not scored (contamination.py).

The mirrored pair is the one found in the 2026-11-16 pull: two runs shared a host and a port, the first
server logged 101 requests more than its client sent, the second 101 fewer."""
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import assess as asx  # noqa: E402
import contamination as ct  # noqa: E402
import test_score_e2e as e2e  # noqa: E402

POST = '(APIServer pid=1) INFO:     127.0.0.1:44314 - "POST /v1/completions HTTP/1.1" 200 OK\n'


BARE = "".join(l for l in e2e.LOG.splitlines(keepends=True) if "POST /v1/" not in l)


def _log(n: int) -> str:
    """The fixture's log with exactly n client request lines."""
    return BARE + POST * n


def _row(conc=16):
    return {"benchmark_type": "single_turn", "conc": conc, "disagg": False}


def test_the_expected_count_is_prompts_plus_warmups():
    assert ct.expected_requests(16) == 192 and ct.expected_requests(4) == 48


def test_the_mirrored_pair_is_named_with_both_counts_and_a_clean_log_is_not():
    assert ct.reasons(_log(192), _row()) == []
    assert ct.reasons(_log(293), _row()) == ["measurement_contaminated:request_count_mismatch(expected 192, logged 293)"]
    assert ct.reasons(_log(91), _row(conc=8)) == ["measurement_contaminated:request_count_mismatch(expected 96, logged 91)"]
    assert asx.g5_of(ct.reasons(_log(293), _row())[0])["code"] == "measurement_contaminated"


def test_the_rule_does_not_judge_what_it_cannot_count():
    assert ct.reasons(BARE, _row()) == []                                           # no request lines at all
    assert ct.reasons(_log(293), {**_row(), "benchmark_type": "agentic"}) == []        # not a single-turn client
    assert ct.reasons(_log(293), {**_row(), "disagg": True}) == []                     # prefill/decode


def _scored(n: int, conc: int):
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = e2e._setup(tmp, conc=conc, log=_log(n), client_requests=False)
        o, _ = e2e._score(tmp, entry, env, tmp / "c1")
        return o
    finally:
        shutil.rmtree(tmp)


def test_a_point_scores_with_the_clients_requests_and_is_not_scored_with_another_runs():
    clean = _scored(12 * 4, 4)
    assert clean.fidelity is not None, clean.reasons
    for n in (12 * 4 + 101, 12 * 4 - 17):
        o = _scored(n, 4)
        assert o.fidelity is None
        assert [r for r in o.reasons if r.startswith("measurement_contaminated")] == [
            f"measurement_contaminated:request_count_mismatch(expected 48, logged {n})"]


STATS = "(APIServer pid=1) INFO 05-30 22:23:12 [loggers.py:271] Engine 000: Avg prompt throughput: 1.0 tokens/s, Running: {r} reqs, Waiting: 0 reqs, GPU KV cache usage: 1.0%\n"


def _two_phases(first: int, second: int, gap: bool = True) -> str:
    """A server that served `first` requests, sat idle for a stats interval (or not), then served `second`."""
    return BARE + POST * first + STATS.format(r=4) + (STATS.format(r=0) if gap else STATS.format(r=4)) + POST * second + STATS.format(r=4)


def test_an_eval_run_apart_in_time_from_the_timed_requests_is_not_contamination():
    assert ct.busy_segments(_two_phases(48, 1319)) == [48, 1319]
    assert ct.reasons(_two_phases(48, 1319), _row(conc=4)) == []
    assert ct.reasons(_two_phases(1319, 48), _row(conc=4)) == []


def test_extra_requests_that_overlap_the_timed_ones_or_split_them_are_contamination():
    # no idle interval between the phases: nothing says they are apart
    assert ct.reasons(_two_phases(48, 1319, gap=False), _row(conc=4)) == [
        "measurement_contaminated:request_count_mismatch(expected 48, logged 1367)"]
    # two stretches, but neither is the client's count
    assert ct.reasons(_two_phases(20, 1319), _row(conc=4)) == [
        "measurement_contaminated:request_count_mismatch(expected 48, logged 1339)"]
    # a deficit is never forgiven, even when what is left is a clean stretch
    assert ct.reasons(_two_phases(4, 237), _row(conc=32)) == [
        "measurement_contaminated:request_count_mismatch(expected 384, logged 241)"]
