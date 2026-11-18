"""A measurement whose server log shows requests the run's own client did not send (or lacks ones it did).

InferenceX's single-turn client sends `--num-warmups 2*CONC` warm-up requests and then `--num-prompts
10*CONC` measured ones (inferencex_client.REQUESTS_PER_CONCURRENCY and WARMUPS_PER_CONCURRENCY), all to
the server whose log the run keeps. On a vLLM point that is exactly 12*CONC `POST /v1/completions` lines;
336 of 352 points in the 2026-11-16 pull have exactly that. Two servers that shared a host and a port split
each other's clients: b4c53d19 (+101 requests) and fcac117a (-101), d1fafe7a (+69) and 458dc24f (-69), each
pair summing to zero. The queue that gives such a point its seconds-long TTFT is the other run's, so the
point does not describe the scenario it is labelled with, and BLIS is not asked to predict it.

The rule reads the log and the row's concurrency only; it never sees a prediction or an error. It applies
to a vLLM single-turn point that has a server log. A point with no log, an agentic or prefill/decode point,
a log that records no request lines at all, and an SGLang point are not judged: SGLang qwen3.5 logs carry a fixed few extra requests on every point
(its launcher's probes), so an exact count says nothing there.
"""
from __future__ import annotations

import inferencex_client as ix

REASON = "measurement_contaminated"
SUBJECT = "request_count_mismatch"
_COUNTED = ("POST /v1/completions", "POST /v1/chat/completions")


def expected_requests(conc: int) -> int:
    return (ix.REQUESTS_PER_CONCURRENCY + ix.WARMUPS_PER_CONCURRENCY) * conc


def logged_requests(log: str) -> int:
    return sum(1 for line in log.splitlines() if any(p in line for p in _COUNTED))


def reasons(log: str, row: dict) -> list[str]:
    """[] when the log holds the client's requests exactly, or the rule does not apply; else the one
    reason, naming both counts."""
    conc = row.get("conc")
    if row.get("benchmark_type") != "single_turn" or row.get("disagg") or not isinstance(conc, int) or conc < 1:
        return []
    want, got = expected_requests(conc), logged_requests(log)
    if got == 0 or got == want:       # a log with no request lines (access log off) cannot be judged
        return []
    return [f"{REASON}:{SUBJECT}(expected {want}, logged {got})"]
