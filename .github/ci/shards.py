#!/usr/bin/env python3
"""The Python tests CI runs, as one manifest: which command runs each test file, in which job.

    shards.py check             fail unless every tracked test file is in exactly one place
    shards.py matrix            print the shard names as a JSON list (the workflow's matrix)
    shards.py run SHARD         run every command of the shard, all of them even when one fails
    shards.py simulator-tests   print the test files the `simulator` job runs

The workflow reads this file, so a test cannot be added to the repository and be left out of CI
without `check` failing: a test file is either in a shard (run by the `orchestrator` jobs), in
SIMULATOR (run by the `simulator` job, which has a built simulator), or in NOT_RUN with a reason.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


class Cmd:
    """One step. `argv` runs directly; `sh` runs under bash -e. `tests` are the test files it runs."""

    def __init__(self, title, *, argv=None, sh=None, tests=()):
        self.title, self.argv, self.sh, self.tests = title, argv, sh, list(tests)


def script(path, title=None):
    """A standalone test file, run as a program (its own __main__ runs its tests)."""
    return Cmd(title or path, argv=["python3", path], tests=[path])


def pytest(title, *paths):
    return Cmd(title, argv=["python3", "-m", "pytest", "-q", *paths], tests=paths)


SHARDS: dict[str, list[Cmd]] = {
    # The summary builders, the scenario and agentic-replay tools, and the schema checks of the committed fixtures.
    "summary": [
        script("orchestrator/test_build_summary.py", "Orchestrator arithmetic + self-consistency oracle + column contract"),
        script("orchestrator/test_extract_agentic_replay_args.py"),
        script("orchestrator/test_extract_single_turn_bench_args.py"),
        script("orchestrator/test_direct_corpus_common.py"),
        script("orchestrator/test_gen_scenarios.py"),
        script("orchestrator/test_gen_direct_corpus.py"),
        script("orchestrator/test_run_agentic.py"),
        pytest("Agentic corpus pinned by its catalog workload's revision and full sha256", "orchestrator/test_resolve_agentic_corpus.py"),
        Cmd("Schema validates the committed render fixture", argv=[
            "python3", "orchestrator/validate_summary.py", "--schema", "schemas/summary.v1.json", "web/testdata/render-fixture.summary.json"]),
        Cmd("summary.json v3 builder + validator; the committed v3 web fixtures rebuild byte-for-byte; the frozen v2 ones validate",
            tests=["orchestrator/test_build_summary_v2.py"], sh="""
python3 orchestrator/test_build_summary_v2.py
t="$(mktemp -d)"
python3 orchestrator/build_summary_v2.py --contract orchestrator/ingest/testdata/contract/run-a --out "$t/v3a.json"
python3 orchestrator/build_summary_v2.py --contract orchestrator/ingest/testdata/contract/run-b --out "$t/v3b.json" --generated-at 2026-10-22T00:00:00Z
cmp "$t/v3a.json" web/testdata/render-fixture.v3.summary.json
cmp "$t/v3b.json" web/testdata/render-fixture.v3b.summary.json
python3 orchestrator/validate_summary_v2.py web/testdata/render-fixture.v3.summary.json web/testdata/render-fixture.v3b.summary.json
python3 orchestrator/validate_summary_v2.py web/testdata/render-fixture.v2.summary.json web/testdata/render-fixture.v2b.summary.json
"""),
    ],
    # The contract, the harness entrypoint and the vLLM build resolution.
    "contract": [
        Cmd("Contract, fidelity schemas, grades and the summary schemas", tests=["orchestrator/ingest/test_contract.py"], sh="""
python3 orchestrator/ingest/test_contract.py
python3 orchestrator/ingest/contract.py orchestrator/ingest/testdata/contract/run-a orchestrator/ingest/testdata/contract/run-b
"""),
        pytest("Scoring harness entrypoint flags, harness commit and no image path", "harness/test_run_sh.py"),
        script("orchestrator/ingest/test_build.py", "vLLM build resolution + commit-distance gate"),
    ],
    # The two largest standalone suites.
    "ingest": [
        script("orchestrator/ingest/test_extract.py", "API ingest extractor"),
        script("orchestrator/ingest/test_score_e2e.py", "Points through score_point and write_contract, fake BLIS binaries"),
    ],
    # The pytest-fixture suites: the nightly pipeline, the grades, the baseline tools.
    "nightly": [
        pytest("API nightly pipeline, grades, baseline tools",
               "orchestrator/ingest/test_nightly.py", "orchestrator/ingest/test_incremental.py",
               "orchestrator/ingest/test_nightly_run.py", "orchestrator/ingest/test_cli_nightly.py",
               "orchestrator/ingest/test_parallel.py", "orchestrator/ingest/test_score_pool.py",
               "orchestrator/ingest/test_ledger.py", "orchestrator/ingest/test_inferencex_client.py",
               "orchestrator/ingest/test_comparability.py", "orchestrator/ingest/test_inferencex_runners.py",
               "orchestrator/ingest/test_result.py", "orchestrator/ingest/test_grade.py",
               "orchestrator/ingest/test_assess.py", "orchestrator/ingest/test_engines.py",
               "orchestrator/ingest/test_fields.py", "orchestrator/ingest/test_headline.py",
               "orchestrator/ingest/test_backlog.py", "orchestrator/ingest/test_coverage.py",
               "orchestrator/ingest/test_stack.py", "orchestrator/ingest/test_server_log.py",
               "orchestrator/ingest/test_gen_grade_doc.py", "orchestrator/ingest/test_drafter.py",
               "orchestrator/ingest/test_recipe_checkpoints.py", "orchestrator/ingest/test_locations.py",
               "orchestrator/ingest/test_value_refusal.py", "orchestrator/ingest/test_g1.py",
               "orchestrator/ingest/test_pd.py", "orchestrator/ingest/test_thinking_rule.py",
               "orchestrator/baseline/test_compare.py", "orchestrator/baseline/test_split.py",
               "orchestrator/baseline/test_residuals.py", "orchestrator/baseline/test_docs.py",
               "orchestrator/baseline/test_contracts_current.py", "orchestrator/test_update_index.py"),
    ],
    # The two repository-wide checks that were hidden behind earlier failures: they run on their own.
    "boundary": [
        Cmd("Every point id of every published snapshot maps to a ledger unit", argv=[
            "python3", "orchestrator/ingest/legacy_ids.py", "check", "--map", "data/legacy/point-ids.json", "--data", "data"]),
        pytest("BLIS is read only through the inference-sim commands: the lint's own tests", "orchestrator/test_lint_blis_boundary.py"),
        Cmd("BLIS is read only through the inference-sim commands: the lint", argv=["python3", "orchestrator/lint_blis_boundary.py"]),
    ],
}

# Run by the `simulator` job, which builds the pinned simulator (they fail, not skip, without one).
SIMULATOR = [
    "orchestrator/ingest/test_inferencex_client_sim.py",
    "orchestrator/ingest/test_score_real_blis.py",
    "orchestrator/ingest/test_pointrecord.py",
    "orchestrator/ingest/test_pointrecord_pd.py",
    "orchestrator/ingest/test_router_configs.py",
]

# Test files no CI job runs, each with the reason. Before this manifest, CI named its test files by hand
# and these three were in no list; they are listed so the omission is visible, not so it stays.
NOT_RUN = {
    "orchestrator/ingest/test_exact.py": "not run by CI before the manifest; needs review (compares against vectors from the Go evaluator)",
    "orchestrator/ingest/test_stand_in_facts.py": "not run by CI before the manifest",
    "orchestrator/baseline/test_freeze_rows.py": "not run by CI before the manifest; reads a substrate checkout",
}


def tracked_tests() -> list[str]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=True).stdout.decode()
    return sorted(p for p in out.split("\0") if p and Path(p).name.startswith("test_") and p.endswith(".py"))


def placements() -> dict[str, list[str]]:
    where: dict[str, list[str]] = {}
    for shard, cmds in SHARDS.items():
        for c in cmds:
            for t in c.tests:
                where.setdefault(t, []).append(f"shard {shard}")
    for t in SIMULATOR:
        where.setdefault(t, []).append("simulator")
    for t in NOT_RUN:
        where.setdefault(t, []).append("NOT_RUN")
    return where


def check() -> int:
    tracked, where = tracked_tests(), placements()
    problems = [f"{t}: in no shard, not in SIMULATOR, not in NOT_RUN" for t in tracked if t not in where]
    problems += [f"{t}: in {len(w)} places ({', '.join(w)})" for t, w in sorted(where.items()) if len(w) > 1]
    problems += [f"{t}: named by the manifest but not a tracked test file" for t in sorted(where) if t not in set(tracked)]
    for p in problems:
        print(f"::error::{p}")
    ran = sum(1 for t in where if not where[t][0] == "NOT_RUN")
    print(f"{len(tracked)} tracked test files; {ran} run by CI "
          f"({sum(1 for t in where if where[t][0].startswith('shard'))} in shards, {len(SIMULATOR)} by the simulator job), "
          f"{len(NOT_RUN)} listed as not run; {len(problems)} problems")
    return 1 if problems else 0


def run(shard: str) -> int:
    results = []
    for c in SHARDS[shard]:
        print(f"::group::{c.title}", flush=True)
        t0 = time.monotonic()
        argv = ["bash", "-e", "-c", c.sh] if c.sh else c.argv
        rc = subprocess.run(argv, cwd=ROOT).returncode
        dt = time.monotonic() - t0
        print("::endgroup::", flush=True)
        if rc:
            print(f"::error::{c.title} failed (exit {rc})", flush=True)
        results.append((c.title, rc, dt))
    print(f"\nshard {shard}:")
    for title, rc, dt in results:
        print(f"  {'ok  ' if rc == 0 else 'FAIL'} {dt:6.1f}s  {title}")
    return 1 if any(rc for _, rc, _ in results) else 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["check"]:
        return check()
    if argv[:1] == ["matrix"]:
        print(json.dumps(list(SHARDS)))
        return 0
    if argv[:1] == ["simulator-tests"]:
        print(" ".join(SIMULATOR))
        return 0
    if len(argv) == 2 and argv[0] == "run" and argv[1] in SHARDS:
        return run(argv[1])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
