#!/usr/bin/env python3
"""Behavioural tests for reading a single-turn row's benchmark settings from its CI log.

The fixture is the real command from MiniMax-M3 mi355x TP4 c1 8k1k (InferenceX run
30865586311, job 91857966313, 2026-08-04). Each check is a way a row could be scored
against a workload its client did not run, while every field still parsed.

Run: python3 orchestrator/test_extract_single_turn_bench_args.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from extract_single_turn_bench_args import (  # noqa: E402
    check_against_harness, parse_job_log, settings_record)

REAL = (
    "2026-08-04T02:42:03.2Z + python3 /workspace/utils/bench_serving/benchmark_serving.py "
    "--model amd/MiniMax-M3-MXFP4 --backend vllm --base-url http://0.0.0.0:8891 "
    "--dataset-name random --random-input-len 8192 --random-output-len 1024 "
    "--random-range-ratio 0.8 --num-prompts 10 --max-concurrency 1 --request-rate inf "
    "--ignore-eos --save-result --num-warmups 2 --percentile-metrics ttft,tpot,itl,e2el "
    "--result-dir /workspace/ --result-filename x.json --trust-remote-code\n"
)

FAILURES = []


def ck(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'} {label}{(': ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


def main() -> int:
    job = parse_job_log(REAL)
    ck("the client's lengths, ratio and load are read from the command",
       (job.get("input_len"), job.get("output_len"), job.get("range_ratio"),
        job.get("num_prompts"), job.get("concurrency"), job.get("num_warmups"))
       == (8192, 1024, 0.8, 10, 1, 2), repr(job))
    ck("no --seed means the client's default seed 0, not 'unknown'", job.get("seed") == 0, repr(job))
    ck("the real run matches the harness's workload", check_against_harness(job, 8192, 1024, 1) == [],
       repr(check_against_harness(job, 8192, 1024, 1)))

    # The harness draws 0.8*ISL..ISL; a run at another ratio sends different prompts.
    other = parse_job_log(REAL.replace("--random-range-ratio 0.8", "--random-range-ratio 1.0"))
    d = check_against_harness(other, 8192, 1024, 1)
    ck("a different range ratio is reported, not scored as the harness's workload",
       any("range_ratio" in x for x in d), repr(d))

    # A seeded run draws different lengths from the ones the harness replays.
    seeded = parse_job_log(REAL.replace("--trust-remote-code", "--trust-remote-code --seed 7"))
    ck("an explicit non-default seed is reported", any("seed" in x for x in check_against_harness(seeded, 8192, 1024, 1)))

    # The API row says c=4 but the log ran c=1: the row and its log disagree.
    ck("a concurrency that disagrees with the API row is reported",
       any("concurrency" in x for x in check_against_harness(job, 8192, 1024, 4)))
    ck("prompts and warm-ups scale with the row's concurrency",
       {"num_prompts", "num_warmups"} <= {x.split()[0] for x in check_against_harness(job, 8192, 1024, 4)})

    rec = settings_record(None, 1024, 1024, 8)
    ck("an expired log yields ASSUMED settings, never 'read'",
       rec["source"] == "assumed" and rec["settings"]["num_prompts"] == 80 and rec["mismatches"] == [],
       repr(rec))
    ck("a found log yields 'read' settings and its mismatches",
       settings_record(REAL, 8192, 1024, 1)["source"] == "read")
    ck("a log with no benchmark command is a mismatch, not a match",
       check_against_harness(parse_job_log("no command\n"), 8192, 1024, 1) != [])

    if FAILURES:
        print(f"\n{len(FAILURES)} failed: {FAILURES}")
        return 1
    print("\nall passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
