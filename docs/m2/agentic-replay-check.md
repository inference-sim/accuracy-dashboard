# An agentic replay, end to end, through the M2 simulator

The idle cap and the warm-up the dashboard passes (`orchestrator/ingest/replay.py`) are only useful if
the simulator takes them. This page records a run that shows it does.

**What was run.** `docs/m2/agentic_replay_check.py` reads a real aiperf export of the frozen pull (a
MiniMax-M3 run on H100 at concurrency 1 whose export states `trace_idle_gap_cap_seconds` 300 and
`warmup_requests_per_lane` 10), builds the workload spec with the scorer's own code (`from_export`,
`workload_spec`), and runs `blis replay --agentic-scenario inferencex-agentx-mvp` on the inference-sim
m2/5 build (commit ece61af0) four times: as the export states it, without the cap, without the warm-up,
and without both. The deployment is inference-sim's example `agentx-dsv41-flash-h100-2x-tp8-dspark5.yaml`
with an acceptance length of 3.0, not the run's own (the run's model has no agentic example in the
simulator); the duration is 900 s, the shortest the scenario allows, instead of the export's 3600 s.
This is a check that the inputs are honoured, not a score.

**What it shows.** The outputs are `m2/agentic-replay-check-c1.json` (the export's concurrency),
`-c4.json` and `-c16.json`. Each run's Result echoes the replay frame it ran: with the inputs passed, the
frame holds `trace_idle_gap_cap_s: 300` and `warmup: {mode: cache_pressure, requests_per_lane: 10}`;
without them it holds neither, so the simulator parsed them. Their effects:

| Concurrency | Inputs | Window starts (s) | Requests completed | Mean TTFT (ms) | Mean TPOT (ms) |
|---|---|---|---|---|---|
| 1 | as exported | 15.9 | 161 | 715.3 | 3.26 |
| 1 | no cap | 15.9 | 161 | 715.3 | 3.26 |
| 1 | no warm-up | 11.2 | 156 | 676.7 | 3.26 |
| 1 | neither | 11.2 | 156 | 676.7 | 3.26 |
| 4 | as exported | 66.9 | 319 | 567.1 | 4.57 |
| 4 | no cap | 66.9 | 213 | 538.2 | 3.37 |
| 4 | no warm-up | 44.2 | 258 | 607.5 | 3.93 |
| 4 | neither | 44.2 | 245 | 535.6 | 3.85 |
| 16 | as exported | 309.5 | 871 | 988.1 | 9.38 |
| 16 | no cap | 309.5 | 463 | 673.1 | 4.30 |
| 16 | no warm-up | 241.3 | 597 | 839.6 | 6.48 |
| 16 | neither | 241.3 | 223 | 611.3 | 3.40 |

The warm-up moves the start of the measured window (it ends with the warm-up's last return) at every
concurrency. The cap changes nothing at concurrency 1 over 900 s, and a great deal at 4 and 16: with
several lanes it shortens the idle gaps between a trajectory's requests, so more requests are in
flight and more complete. At concurrency 4 the window starts at 44.2 s without the warm-up and 66.9 s
with ten requests per lane, the figure `docs/comparability.md` quotes.

**What it does not show.** It does not show that the simulator's replay equals the fork of aiperf InferenceX ran
(`client_build`), nor how close the means are to the measured ones; no agentic point is scored in any
committed run, because each is held at G5 by a field the engine does not model.

To repeat: `python3 docs/m2/agentic_replay_check.py --blis BLIS --export EXPORT.gz --corpus traces.jsonl
--scenario SCENARIO.yaml --scenarios DIR --duration 900 [--concurrency N] --out OUT.json`, with the
corpus at the sha256 the catalog pins.
