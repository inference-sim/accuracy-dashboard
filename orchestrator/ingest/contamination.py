"""A measurement whose server log shows requests the run's own client did not send (or lacks ones it did).

InferenceX's single-turn client sends `--num-warmups 2*CONC` warm-up requests and then `--num-prompts
10*CONC` measured ones (inferencex_client.REQUESTS_PER_CONCURRENCY and WARMUPS_PER_CONCURRENCY), all to
the server whose log the run keeps. On a vLLM point that is exactly 12*CONC `POST /v1/completions` lines;
336 of 352 points in the 2026-11-16 pull have exactly that. Two servers that shared a host and a port split
each other's clients: b4c53d19 (+101 requests) and fcac117a (-101), d1fafe7a (+69) and 458dc24f (-69), each
pair summing to zero. The queue that gives such a point its seconds-long TTFT is the other run's, so the
point does not describe the scenario it is labelled with, and BLIS is not asked to predict it.

A surplus is forgiven only when it cannot overlap the timed requests: the log's busy stretches (separated by an
interval in which the engine held nothing and logged nothing) include one of exactly the client's count, so the
other requests ran before or after it. 9 vLLM points carry exactly 1319 extra requests (the GSM8K test set), and
all 9 split into a stretch of 12*CONC and a stretch of 1319. A deficit is never forgiven.

Only completed requests count: a POST that the server answered with HTTP 200. A response of another status is a request that did not
complete (a 404 probe, a 400 rejection), not a request of the run. Two H100 points (449d09f0, dc13b68d) log their 48 and 96 expected
requests as 200 and 384 and 96 more as 404; counting every line called them contaminated, and their 200s are exactly the client's.
A run whose responses mostly failed (more failed responses than completed ones: minimax-m2.5 H200 conc 2, 20 completed of 24
expected beside 3,230 HTTP 400) is not a completed run either, and is named so (requests_failed), under the same code.

The rule reads the log and the row's concurrency only; it never sees a prediction or an error. It applies
to a vLLM single-turn point that has a server log. A point with no log, an agentic or prefill/decode point,
a log that records no request lines at all, and an SGLang point are not judged: SGLang qwen3.5 logs carry a fixed few extra requests on every point
(its launcher's probes), so an exact count says nothing there.
"""
from __future__ import annotations

import re

import inferencex_client as ix

REASON = "measurement_contaminated"
SUBJECT = "request_count_mismatch"
_COUNTED = ("POST /v1/completions", "POST /v1/chat/completions")
_STATUS = re.compile(r'"POST /v1/(?:chat/)?completions HTTP/[0-9.]+" ([0-9]{3})')
_STATS = re.compile(r"loggers\.py.*Running: (\d+) reqs, Waiting: (\d+) reqs")


def expected_requests(conc: int) -> int:
    return (ix.REQUESTS_PER_CONCURRENCY + ix.WARMUPS_PER_CONCURRENCY) * conc


def _counted(line: str) -> bool:
    return any(p in line for p in _COUNTED)


def _completed(line: str) -> bool:
    """A counted line the server answered with HTTP 200 (a line that states no status is taken as answered)."""
    m = _STATUS.search(line)
    return _counted(line) and (m is None or m.group(1) == "200")


def logged_requests(log: str) -> int:
    """The requests the server completed (HTTP 200)."""
    return sum(1 for line in log.splitlines() if _completed(line))


def failed_requests(log: str) -> int:
    """The counted requests the server answered with another status."""
    return sum(1 for line in log.splitlines() if _counted(line) and not _completed(line))


def busy_segments(log: str) -> list[int]:
    """The client requests logged in each stretch of the run between idle periods. A request is logged when it
    completes; the engine's stats line every 10 s says how many requests it holds. An interval that holds none
    and logs none ends a segment, so two segments are apart in time by at least that interval."""
    segs, cur, total = [], 0, 0
    for line in log.splitlines():
        if _counted(line):
            cur += _completed(line)
            continue
        m = _STATS.search(line)
        if not m:
            continue
        if cur == 0 and int(m.group(1)) == 0 and int(m.group(2)) == 0:
            if total:
                segs.append(total)
            total = 0
        else:
            total += cur
        cur = 0
    total += cur
    if total:
        segs.append(total)
    return segs


def reasons(log: str, row: dict) -> list[str]:
    """[] when the log holds the client's requests exactly, or the rule does not apply; else the one
    reason, naming both counts."""
    conc = row.get("conc")
    if row.get("benchmark_type") != "single_turn" or row.get("disagg") or not isinstance(conc, int) or conc < 1:
        return []
    want, got, bad = expected_requests(conc), logged_requests(log), failed_requests(log)
    if got + bad == 0 or got == want:     # a log with no request lines (access log off) cannot be judged
        return []
    if bad > got:
        return [f"{REASON}:requests_failed({got} of {want} completed)"]
    if got > want and want in busy_segments(log):
        # Surplus only, and the benchmark's own requests make a stretch of the run by themselves: the extra requests
        # (an accuracy eval run before or after it on the same server) are apart in time from the timed ones.
        return []
    return [f"{REASON}:{SUBJECT}(expected {want}, logged {got})"]
