"""Reading a benchmark client's command line out of a CI job log.

Shared by the log readers (extract_agentic_replay_args, extract_single_turn_bench_args) so
there is one copy of how a logged command is located and how a flag's value is read.
"""

import shlex


def command_after(job_log: str, marker: str) -> list[str] | None:
    """The argv following the first line that contains `marker`, or None.

    `marker` ends at the program name (e.g. "benchmark_serving.py " or "aiperf "), so the
    returned argv starts with the program's first argument. A line that does not split as
    shell words is skipped rather than half-read.
    """
    for line in job_log.splitlines():
        i = line.find(marker)
        if i < 0:
            continue
        try:
            return shlex.split(line[i + len(marker):])
        except ValueError:
            continue
    return None


def flag(argv: list[str], name: str) -> str | None:
    """The value of `--name v` or `--name=v`; the last occurrence wins, as argparse does."""
    val = None
    for k, a in enumerate(argv):
        if a == name and k + 1 < len(argv):
            val = argv[k + 1]
        elif a.startswith(name + "="):
            val = a.split("=", 1)[1]
    return val
