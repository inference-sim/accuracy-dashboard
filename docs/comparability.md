# Does the dashboard compare like with like?

A point is only as good as the match between what InferenceX measured and what BLIS simulated. This page lists, dimension by dimension, how the InferenceX client measured, how the dashboard rebuilds that, how BLIS simulates it, whether the three agree, and whether the point says so when they do not. It was written from an audit of the client sources and the code on 2026-11-11, and the checks it names are in `orchestrator/ingest/test_comparability.py` and the scorer.

The rule behind it: the request pattern, the measured window and metrics, and the deployment must all match what InferenceX measured, or the point names the difference. A difference named on a point makes it G2 (kind `client_difference`, see [closeness grades](closeness-grades.md)); a difference no point names is listed under "Differences no point names today", and is not a clean bill.

## What is compared

Two numbers per point: mean time to first token (TTFT) and mean time per output token (TPOT), both over requests, in microseconds. The measured side is the `mean_ttft` and `mean_tpot` InferenceX stores (seconds, from the client's `mean_ttft_ms` and `mean_tpot_ms`). The predicted side is computed from the per-request rows of the simulator's Result for single-turn points, and read from the Result's `ttft_mean_ms` and `tpot_mean_ms` for agentic ones. InferenceX stores the same per-request TPOT as `mean_itl`; that is not the registry's pooled `itl`, which BLIS does not compute and the dashboard never compares.

## The matrix

| Dimension | InferenceX client | Dashboard and BLIS | Agree? | Named on the point? |
|---|---|---|---|---|
| TTFT (single-turn) | Clock starts after the semaphore is acquired and before the request is posted, on a new connection; stops at the first streamed chunk with `choices`. | Row TTFT: arrival, render and tokenise, prefill, one output-processing step. No socket, connect or serialisation. | Same definition; the client's own costs are not modelled (0.4 to 0.6 ms per request on the audit's laptop). | `send_gap`, `client_saturation` |
| TPOT | Per request, (latency to the last content chunk minus TTFT) over (output tokens minus 1), for requests of 2 or more tokens; mean over requests. | The same formula from the Result row, E2E minus the completion overhead. | Same formula and population. Check T3 runs the client's own `calculate_metrics`, pinned by commit and sha256, against `summarize` on three cases: one-token, failed and output-length-differs requests. | no (equal) |
| Units | The database writer divides every `*_ms` key by 1000. | Microseconds, times 1e6. | Same. Check T4 runs the writer's loop, pinned the same way. | no (equal) |
| Window (single-turn) | The whole main phase, first send to last completion, `10 x concurrency` requests. | The dashboard averages exactly those rows; it never reads the Result's own aggregate for a single-turn point (check T7). | Same by construction. | no (equal) |
| Request lengths | numpy's `randint` draws with seed 0 (`target_lengths` re-implements them, checked against numpy for six triples), tokens re-encoded and padded to the target. | The trace carries those lengths exactly. | Same where the prompt-length evidence covers the point (360 points, runs from 2026-02-25 to 2026-08-07). | `sent_prompt_lengths` elsewhere |
| Request count and order | `10 x concurrency` prompts, started in order through a semaphore. | `10 x concurrency` sessions in a pool of `concurrency`. Check T1 refuses a run whose count, order, in-flight maximum or mean concurrency is not that. | Same. | refused (`blis_refused:request_pattern_not_the_clients`) when not |
| Warm-up (single-turn) | `2 x concurrency` copies of request 0, drained before the main phase. | The same count, primed only when prefix caching is on. | Same KV state; the client's first-call costs (JIT, autotune) are not reproduced. | not named (open, below) |
| Next-request gap | The next request starts after the final usage chunk, `[DONE]`, the session exit and an event-loop wake-up. | BLIS releases it at the request's completion plus an assumed completion overhead of 777 us. | The real gap is not measured. | `send_gap` |
| Measured requests that failed | A failed request is dropped from every list; a run fails only above 5%. | The simulated run must complete every request. | Differs: the measured mean may be over fewer requests. | `failed_requests` when `completed` and `num_prompts` are not in the pulled data; G5 `conflict:measured.completed` or `conflict:measured.benchmark_outcome` when they say the run lost requests or did not succeed (check T6) |
| Client saturation | One Python process parses every streamed chunk (about 20 us each on the audit's laptop, so about 50,000 chunks a second there). | Not modelled. Check T10 computes the chunk rate, concurrency over TPOT, and flags a run above half of that floor. | Unknown for the real runners. | `client_saturation`, and `client_bound` in the record |
| Agentic request pattern | aiperf's AgentX replay: seed, duration, trajectory window, 10 s whole-system idle cap, grace period, and, in every export, a 300 s per-trajectory idle cap and 10 warm-up requests per lane. | All of these are read from the run's export and passed (`replay.py`): the cap as `trace_idle_gap_cap_s`, the warm-up as a cache-pressure warm-up with `requests_per_lane`. | Same inputs. | no (equal) |
| Agentic client build | The SemiAnalysisAI fork of aiperf, which reports the version string `0.12.0`. | BLIS transcribes ai-dynamo's tag v0.12.0. | Differs in the warm-up handoff, the warm-up lead cap and the first minutes' idle shift. Size not measured. | `client_build` |
| Agentic window | Records tagged profiling without error, including requests that finish in the 30 s grace period. | The Result's measured set follows the same rule. | Same. | no (equal) |
| Deployment | The run's launch flags, environment, engine release, recipe. | What the run set, and the engine-resolved values of fields the engine models or proves inert; a resolved-only value of any other field is recorded and not stated ([coverage accounting](coverage-accounting.md), blis-design#3, merged). Substitutions are named. | Never G1 while the engine release differs: no in-scope point ran the simulator's release. | substitutions on the point |

## Windows

| | InferenceX reports over | BLIS reports over | Can the dashboard select the same window? |
|---|---|---|---|
| Single-turn | The whole main phase: first main send to last completion, no ramp or tail cut. The warm-up is outside it. | Requests that arrived after the warm-up and completed before the window closes. A primed trace carries no phase labels, so the Result's own aggregate would include the warm-up copies. | Yes, by not using the aggregate: `summarize` averages the main-phase rows. Selecting the window inside the Result needs phases (inference-sim 1926, blis-schemas 56). |
| Agentic | aiperf's profiling phase, no trimming of ramp or tail. | From the end of warm-up to the end of the profiling phase. | Yes; the rule is the same and the dashboard reads the Result's aggregate. A run of the simulator with the warm-up passed moves the window start (44.2 s without it, 66.9 s with ten requests per lane, at concurrency 4), so the input is honoured; the run is recorded in [the agentic replay check](m2/agentic-replay-check.md). |

## Differences a point names

Each is a `client_difference` in the point's fidelity record, so a point that names one is G2 at best.

| Subject | When | What it says |
|---|---|---|
| `send_gap` | every single-turn point | BLIS releases the next request at the previous one's completion plus 777 us of assumed overhead; the real client's gap is not measured. |
| `sent_prompt_lengths` | the prompt-length evidence does not cover the point | The sent lengths are not verified equal to the replayed targets. |
| `client_flags` | the job log has expired | The client's flags are taken to be the launcher's defaults. |
| `client_release` | the InferenceX commit of the run is not recorded | The client's release is unknown. |
| `failed_requests` | `completed` and `num_prompts` are in no pulled file | Requests the client lost are not ruled out. |
| `client_saturation` | the chunk rate is above half of 50,000 a second | The measured latencies may include client queueing. |
| `benchmark_client` | every prefill/decode point | The run's client is its recipe's srt-slurm benchmark (`sa-bench` in every recipe read), not InferenceX's `benchmark_serving.py`. The replay sends the InferenceX client's seed-0 lengths; the recipe's benchmark draws its own random prompts (range ratio 0.8, 10 x concurrency prompts, 2 x concurrency warm-ups: the benchmark's defaults at srt-slurm main on 2026-11-11, assumed equal), and sends them through the chat template unless the recipe says otherwise, which can shift the lengths. |
| `client_build` | every agentic point | The export says aiperf 0.12.0; InferenceX pins a fork; BLIS transcribes the tag; the fork commit is not recorded on the point (the pull does not keep an agentic run's InferenceX commit). |

**The send gap counts one number twice.** The 777 us is the registry's `host_completion` coefficient (method `assumed`), which the point also names as a `coefficient_method` substitution. The one unmeasured number is therefore counted twice. Design COV-12 says every difference between the run's client and the simulated one is named and makes the point G2, and it does not say whether a measured gap is a coefficient or a request difference. The dashboard keeps both names until the design decides; measuring the gap clears both together. No grade depends on the second name today, because `coefficient_method` alone holds every single-turn point at G2.

A prefill/decode point also names, as substitutions of the deployment and not of the client: `engine.prefill.recipe` and `engine.decode.recipe` (each pool's arguments are the run's recipe's, not its log), `pool placement` (`execution_mode`: BLIS never puts two pools on one node; a recipe that allows prefill and decode workers to share one says so), and, where the table maps its router, `router_differs` with the entry, policy, evidence, difference and bound.

A scenario of more than one node also names `cluster.fabric`, an `estimated` substitution, because no InferenceX launch configuration, recipe or `runners.yaml` records a cluster's fabric class (`runners.yaml` lists RDMA devices, ports and the GID index, not InfiniBand against Ethernet nor a line rate). Where InferenceX documents the fabric of the chip SKU, the point cites it: the "Chip Specifications & Comparison" page (https://inferencex.semianalysis.com/gpu-specs, fetched 2026-11-12, sha256 `f9ca3c28...ab25d8`) lists InfiniBand NDR 400 Gb/s for h200 and gb200-nvl72, InfiniBand XDR 800 Gb/s for gb300, and RoCEv2 Ethernet at 400 Gb/s for h100 and b200 and 800 Gb/s for b300. The catalog has the InfiniBand classes `ib-400g` and `ib-800g` only, so h200, gb200-nvl72 and gb300 get the documented class, and h100, b200 and b300 get the class of the same line rate as a stand-in that the point labels (the RoCE efficiency is not measured; the registry's value for the InfiniBand class is carried over). A chip nothing documents gets the default `ib-400g`, and the point says no source documents it. Each of these lists `cost-model-fabric` (without it a cross-node transfer is priced at the catalog's nominal rate, 23% fast). A fabric class a launch configuration or recipe records (`resources.fabric`) is used and not named. One switch, `settings.FABRIC_WHEN_UNRECORDED`, set to `refuse`, turns every such point into G5 `value_not_recorded:cluster.fabric`. The RoCE classes and rails are blis-substrate#50 and #51, planned for M3.

A speculative point also records the mean acceptance length its server logged (the `SpecDecoding metrics` lines, weighted by drafted tokens, with the number of lines and tokens) beside what the simulation used, and the acceptance substitution names it. When the engine models `speculative_config.synthetic_acceptance_length` and the run set no length, the logged figure is pinned in place of the registry's profile; otherwise it is only recorded.

## Differences no point names today

Open items, with the tracking issue where there is one. None of these is hidden by a grade; none is yet visible on the point.

- First-call costs on the real engine (JIT, autotune, allocator growth) land in the measured phase at shapes the warm-up lacks. Up to one request in ten at concurrency 1. No issue yet.
- The chat template, when the job log has expired and the run passed `--use-chat-template`: request lengths shift by the template. Named only as the generic `client_flags`.
- The client's version after 2026-08-07: the draws and `calculate_metrics` read as unchanged by diff, but no check runs the post-2026-09-26 client (the audit's T2).
- Round trip of per-request rows through the client's JSON (T5), and replication and noise (T11, COV-10): not built.
- `gpu_memory_utilization` is dropped on most points (named as `estimated`); the engine release differs on all of them (G4).
- Percentiles and distributions: COV-10, planned for M3.
- Mean-only statistics against heavy tails: the agentic standard error of the mean is 3% to 29% for TTFT, so a fixed 1.6% floor is used and is too small for those.

## Which figures are compared

Only TTFT and TPOT (`result.COMPARED_FIGURES`). At the start of every scoring run `cli.py` asks the build for its metric registry (`blis metrics --json`) and `result.check_definitions` requires each figure compared to have the client's definition there in every one of the eight meaning fields (formula, statistic, population, window, unit, percentile method, unfinished, denominator; an empty optional field is a statement, so a denominator the client does not have is refused) and to be defined at the cluster scope; a registry that differs stops the run. The figure read from a Result must be the direct cluster figure, as substrate's `ComparableFigures` requires of the context: cluster scope, no member, no aggregate, no scope ranged over; a Result of schema version 3 that states a pool, an instance or an aggregate over instances for a compared figure is refused (`figure_not_cluster_direct`), and an earlier one states none and is the cluster figure by construction. A build without the command (v0.16.0, the baseline's simulator) has no registry to check: the run says so and its definitions are the ones the scorer assumes.

InferenceX reports other figures with other definitions, and a figure of the same name at another scope is not the same figure: total tokens per second per GPU is input plus output over all the deployment's GPUs, where `output_tok_s_per_gpu` is output tokens only; for a disaggregated run the input rate is over the prefill GPUs and the output rate over the decode GPUs; `mean_intvty` is 1 over the mean ITL, where the registry's `interactivity_mean` is the mean of each request's 1 over ITL (2% to 27% higher on TP8 H200 replays). `result.CLIENT_RATE_DEFINITIONS` holds those definitions, and tests refuse each known-bad pairing. The ids and keys are those blis-substrate#52 shipped in layer 7 (`contracts/metrics/metrics.go`, head 41ae65f): `total_tokens_per_second_per_gpu` (denominator `window_and_gpus`), `output_tokens_per_second_per_decode_gpu` (`window_and_decode_gpus`) and `interactivity_of_mean_tpot` (formula `interactivity`, statistic `mean`); `interactivity_mean` is unchanged and is not the client's figure. InferenceX's `input_tput_per_gpu` has no registry metric yet. No such figure is compared yet.

## How to reproduce

1. Freeze the pull: `orchestrator/baseline/freeze.py` (see [reproducing](reproducing.md)).
2. Score from a clean checkout of the harness commit: `harness/run.sh` (the same page lists every pin).
3. The checks: `python3 -m pytest -q orchestrator/ingest/test_comparability.py orchestrator/ingest/test_extract.py orchestrator/ingest/test_score_e2e.py`.

The checks that run the InferenceX client's own code use the excerpts in `orchestrator/ingest/testdata/client/`, each named with its repository, commit, path and sha256 in `SOURCE.json`: `calculate_metrics` at InferenceX 08d7a9cd and 96d6fb58, and the writer's unit loop at 96d6fb58. The tests fail if an excerpt is edited.

Inputs by commit: InferenceX 08d7a9cd and 96d6fb58; aiperf be53bf29 (the tag) and 754356e9 (the fork, for the one run whose InferenceX commit was resolved); vLLM v0.32.0; the cc-traces-weka-062126 dataset at revision 23f152f6.

## What this page does not show

- Throughput and per-GPU figures: not compared, and their denominators differ (data-parallel replicas are in BLIS's GPU count and not in InferenceX's).
- Percentiles and distributions (COV-10, M3).
- The real runners' client ceiling: the 50,000 chunks a second is a floor measured on a laptop with the server on the same machine.
- Disaggregated runs: their client is a different one (srt-slurm's `sa-bench`), so the single-turn column above does not describe them; a scored prefill/decode point names `benchmark_client`. The first token the Dynamo client sees (the prefill worker's sampled token or the decode worker's) is not established; BLIS reports the decode leg's. The router is substituted by an llm-d policy only through the router table (`router_differs`, [disaggregation](disaggregation.md)).
- AMD and TPU rows: out of scope.

## Sources

The InferenceX client (`benchmark_serving.py`, `backend_request_func.py`, `benchmark_lib.sh`, the result writer) at the commits above; aiperf's AgentX replay at the tag and at the fork; vLLM's `bench serve`; the Hugging Face dataset revision; this repository's frozen pull and the code named in each row.
