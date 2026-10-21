#!/usr/bin/env python3
"""Read, from a single-turn InferenceX row's CI job log, how its benchmark client was run.

A `single_turn` row is one run of InferenceX's client, benchmark_serving.py, at one
concurrency. inference-sim's harness replays that run's main phase, but it does not read
the client's settings: it states them as constants (sim/kernelmodel/harness/workload.go),
taken from InferenceX's benchmark scripts:

  --random-range-ratio 0.8      target lengths drawn from [0.8 * ISL, ISL]
  --num-prompts 10*CONC         the main phase
  --num-warmups 2*CONC          copies of request 0 sent before it
  --seed (not passed) -> 0      the NumPy seed those lengths are drawn with

This module reads what the row's CI job log says the client was actually given, and checks
it against those constants. A run whose client settings differ is not the workload the
harness replays, so it must not be scored as if it were.

When the log no longer exists (GitHub expires Actions logs after its retention period, so
older runs return HTTP 410), nothing can be read. The caller then records the settings as
ASSUMED from the constants, never as read, so a reader can tell the two apart.

Nothing here is fetched: callers pass the log text.
"""

from _argv import command_after, flag as flag_value

# The harness's constants (inference-sim sim/kernelmodel/harness/workload.go). A row whose
# client was given anything else is not the workload the harness replays.
HARNESS_RANGE_RATIO = 0.8
HARNESS_PROMPTS_PER_CONC = 10
HARNESS_WARMUPS_PER_CONC = 2
HARNESS_SEED = 0  # benchmark_serving.py's default when --seed is not passed


def bench_command(job_log: str) -> list[str] | None:
    """The argv of the `benchmark_serving.py` invocation in a CI job log, or None."""
    return command_after(job_log, "benchmark_serving.py ")


def parse_job_log(job_log: str) -> dict:
    """The client settings stated in a single-turn job log.

    Keys present only when the log states them: dataset, input_len, output_len,
    range_ratio, num_prompts, concurrency, num_warmups, request_rate, ignore_eos, seed.
    `seed` is HARNESS_SEED when a command was found but passed no --seed (the client's
    default), and absent when no command was found at all.
    """
    argv = bench_command(job_log)
    if argv is None:
        return {}
    out: dict = {"ignore_eos": "--ignore-eos" in argv}
    for flag, key, kind in (("--dataset-name", "dataset", str),
                            ("--random-input-len", "input_len", int),
                            ("--random-output-len", "output_len", int),
                            ("--random-range-ratio", "range_ratio", float),
                            ("--num-prompts", "num_prompts", int),
                            ("--max-concurrency", "concurrency", int),
                            ("--num-warmups", "num_warmups", int),
                            ("--request-rate", "request_rate", str),
                            ("--seed", "seed", int)):
        v = flag_value(argv, flag)
        if v is None:
            continue
        try:
            out[key] = kind(v)
        except ValueError:
            out[key + "_raw"] = v
    out.setdefault("seed", HARNESS_SEED)
    return out


def check_against_harness(job: dict, isl: int, osl: int, conc: int) -> list[str]:
    """Every way the logged client run differs from the workload the harness replays.

    `isl`, `osl` and `conc` are the API row's. An empty list means the run is the harness's
    workload. A non-empty one means the row must not be scored as that workload.
    """
    if not job:
        return ["no benchmark_serving.py command in the job log"]
    diffs = []
    want = {
        "dataset": "random",
        "input_len": isl,
        "output_len": osl,
        "concurrency": conc,
        "range_ratio": HARNESS_RANGE_RATIO,
        "num_prompts": HARNESS_PROMPTS_PER_CONC * conc,
        "num_warmups": HARNESS_WARMUPS_PER_CONC * conc,
        "seed": HARNESS_SEED,
        "request_rate": "inf",
        "ignore_eos": True,
    }
    for key, expected in want.items():
        got = job.get(key)
        if got is None:
            diffs.append(f"{key} not stated (harness assumes {expected!r})")
        elif got != expected:
            diffs.append(f"{key} is {got!r}, harness replays {expected!r}")
    return diffs


def settings_record(job_log: str | None, isl: int, osl: int, conc: int) -> dict:
    """What to store with a row: the settings, whether they were read or assumed, and any
    mismatch.

    `job_log` is None when the log could not be fetched (e.g. HTTP 410, expired). The
    settings are then the harness's constants with source "assumed", and nothing is checked.
    """
    if job_log is None:
        return {
            "source": "assumed",
            "settings": {"dataset": "random", "input_len": isl, "output_len": osl,
                         "concurrency": conc, "range_ratio": HARNESS_RANGE_RATIO,
                         "num_prompts": HARNESS_PROMPTS_PER_CONC * conc,
                         "num_warmups": HARNESS_WARMUPS_PER_CONC * conc,
                         "seed": HARNESS_SEED},
            "mismatches": [],
        }
    job = parse_job_log(job_log)
    return {"source": "read", "settings": job,
            "mismatches": check_against_harness(job, isl, osl, conc)}
