# What each benchmark states about the workload of a speculative run

[Contents](#contents)

## Contents

1. [Why this page](#why-this-page)
2. [What each family states](#what-each-family-states)
3. [Profile pairs the substrate holds](#profile-pairs-the-substrate-holds)
4. [What the dashboard does with it](#what-the-dashboard-does-with-it)
5. [Counts](#counts)
6. [What a measured profile would need](#what-a-measured-profile-would-need)
7. [What this does not show](#what-this-does-not-show)

## Why this page

A speculative point's acceptance profile is keyed by the workload's category and thinking mode (design D8). The server's
reasoning parser is a capability of the engine; the same server can be sent thinking-disabled, non-coding or mixed prompts, so
it is never read as a statement about the workload (design §11.2, X19). The dashboard therefore uses a category or a thinking
mode only where the run's record or the benchmark's own definition states it, and says where. This page lists what each
benchmark family states, with the file and line at the commit the run used, and what follows.

## What each family states

| Family | Rows (speculative) | Thinking mode | Category | Source |
|---|---|---|---|---|
| InferenceX fixed-sequence, single node | 553 (DeepSeek-V4-Pro 137, MiniMax-M3 416) | Stated for DeepSeek-V4-Pro: **on**. Not stated for MiniMax-M3 (the model's jinja template decides, and no source read here says which). | **None.** The prompts are random tokens. | below |
| srt-slurm `sa-bench`, prefill/decode | 16 of the 188 Dynamo rows are speculative; none is scored | Not stated by the recipe (a custom tokenizer or the engine's default decides) | **None** (random tokens) | below |
| AgentX (aiperf), agentic | 47 (Kimi-K3 40, MiniMax-M3 7) | **on** | **coding** | below |

**InferenceX fixed-sequence.** `benchmarks/benchmark_lib.sh`, function `run_benchmark_serving`, builds the client command with
`--dataset-name random ... --random-range-ratio ... --ignore-eos` (lines 522-529 at `238dc77d`, `1ce6f5be`; lines 686-693 at
`0a826be3`): the prompts are random token ids, decoded and re-encoded, with no semantic category. The DeepSeek-V4-Pro
speculative scripts pass `--dsv4` (`benchmarks/single_node/fixed_seq_len/dsv4_fp4_b300_vllm_mtp.sh` lines 99-113 at
`238dc77d`; `dsv4_fp8_h200_mtp.sh` line 105 at `1ce6f5be`; `dsv4_fp4_b200_vllm_mtp.sh` at `238dc77d` and `0a826be3`), whose
comment says it routes prompts "through chat-formatted encoding as required for speculative decoding benchmarks", and
`utils/bench_serving/benchmark_serving.py` `_apply_chat_template` (line 172 at all three commits) calls the DeepSeek-V4
encoder with `thinking_mode="thinking"`. So the thinking mode is stated for those rows and the category for none.
The three run commits (`238dc77d`, `1ce6f5be`, `0a826be3`) are the `client_commit` of the 80 DeepSeek-V4-Pro rows a reasoning-parser
rule used to score (b300 and b200 at `238dc77d`, h200 at `1ce6f5be`, b200 at `0a826be3`). The job logs have expired (`client_args`
is null for all 80), so the scripts are read at the commit, not the run's command line.

**srt-slurm sa-bench.** `src/srtctl/benchmarks/scripts/sa-bench/bench.sh` line 80 (NVIDIA/srt-slurm `main`, the repository the
runners cloned unpinned): `DATASET_NAME=${17:-random}`, with `--random-input-len/--random-output-len/--random-range-ratio`
(lines 131-135). The recipes pass `use_chat_template` and, for DeepSeek-V4, a `custom_tokenizer`
(`sa_bench_tokenizers.*_deepseek_v4`); neither states a thinking mode, and no recipe states a category.

**AgentX.** The catalog's workload file `catalog/workloads/agentx-mvp.yaml` (and `-uncapped`), lines 30-31 at the substrate pin, states
`category: coding` and `thinking: "on"`, citing InferenceX `.github/workflows/benchmark-tmpl.yml:96` and
`inferencex-e2e/infx/launch/request.py:141-146` (not opened here). The run's server log states a synthetic acceptance length
(MiniMax-M3 2.78 at K=3; Kimi-K3 3.84 at K=7 and 3.0 at K=3), which the dashboard pins, so the profile is not consulted.

## Profile pairs the substrate holds

`registry/acceptance/inferencex-golden-al.yaml` at the pinned substrate commit carries measured profiles, all of category
**coding** (its first caveat: no other category has a value).

| Model, method | Thinking on | Thinking off | K |
|---|---|---|---|
| deepseek-v4-pro, mtp | yes | yes | 1-8 |
| deepseek-v4-pro-0813, dspark | yes | no | 1-8 |
| deepseek-v4.1-flash, dspark | yes | yes | 1-5 |
| glm-5.2-fp8, mtp | yes | no | 1-8 |
| glm-5.3, mtp | yes (provisional) | no | 3 |
| minimax-m3, eagle3 | yes | yes | 1-8 |
| kimi-k3 (dspark) | no profile | no profile | |

So the pairs with a profile are (coding, on) for every model above and (coding, off) for the four that list it. Every other
category (random tokens, chat, summarization, ...) has no profile.

## What the dashboard does with it

1. An acceptance length the run set, or one its server logged, is pinned in place of a profile (named `estimated`, with the log's
   figures); it is what the benchmark exercised, and it was 2% (DeepSeek-V4-Pro K=2) to 12% (MiniMax-M3 K=4) from the coding profile.
   The design lists no condition for a figure measured in the run's own server log standing in for an unset setting; the named
   `estimated` substitution is the nearest (§11.3, "a recorded value was missing and replaced"), and the point stays G2 at best
   and G4 where the release differs. This is a question for the design owner.
2. Otherwise the point needs a stated category and thinking mode. A fixed-sequence point states none: it is G5
   `value_not_recorded:workload_category_not_stated`. The caller may ask for a fallback category
   (`--speculative-fallback-category`, design D8); the point then names it (`estimated` on `workload.category`) and the run is
   experimental. A stated pair with no profile is `value_not_recorded:profile_not_available:<category>/<thinking>`.
3. AgentX takes its category and thinking mode from the workload file and its acceptance from the log.

## Counts

Speculative rows of the frozen pull (600: 553 single-turn, 47 agentic), by outcome.

| Run | Family | Scored | G5 `workload_category_not_stated` | Other G5 | Refused by the simulator |
|---|---|---|---|---|---|
| Preliminary after-run (committed; pins `ece61af0`, blis-vllm `5de11f5`, which does not model the logged acceptance) | InferenceX fixed-sequence, 553 | 0 | 382 | 171 | 0 |
| | AgentX, 47 | 0 | 0 | 47 | 0 |
| Head pins (not committed; inference-sim `780f661e`, blis-vllm `96ea750e`, substrate `f70c6c75`) | InferenceX fixed-sequence, 553 | 17 | 51 | 171 | 314 |
| | AgentX, 47 | 0 | 0 | 47 | 0 |

Of the 553 fixed-sequence rows, 171 are G5 for another reason first (AMD parts out of scope, missing logs and the like).
The 80 DeepSeek-V4-Pro MTP rows a reasoning-parser rule used to score are 0 scored at the preliminary pins (they pin no
acceptance length: that engine field is not modelled there) and 17 scored at the head pins, where the server log's realised
acceptance length is pinned in place of a profile (the log field is cited on the point: the interval count and drafted tokens).
Of the other 63, the head-pin simulator refuses the scenario: the dashboard states `indexer_kv_dtype` bf16 for the DeepSeek sparse
indexer and the engine accepts only fp8 or mxfp4 (blis-vllm#84), and the MiniMax-M3 rows name a draft model the target graph
already states. These are engine-side findings, reported; the dashboard does not hide them by guessing a workload.

Pairs without a profile, by what each would unlock: for the 382 fixed-sequence rows with no pinned acceptance, **no pair** is
stated, so none has a profile to miss. If a caller requests the fallback category coding (`--speculative-fallback-category`),
the pair (coding, on) has a profile for DeepSeek-V4-Pro MTP and MiniMax-M3 EAGLE3 and (coding, off) for the same two; a run with
thinking mode unstated for MiniMax-M3 would need the mode named too. Kimi-K3 (40 AgentX rows) has no profile and pins the log's
synthetic length instead; its 35 H200 rows have no server log at all.

The pairs the benchmarks state and the substrate holds a profile for: AgentX (coding, on) for MiniMax-M3 and the Kimi-K3 B300 rows
(not consulted: the log's synthetic length is pinned). The pairs they state and the substrate does not hold: none today.

## What a measured profile would need

For random-token fixed-sequence runs (category "none", thinking on for DeepSeek-V4-Pro; unknown for MiniMax-M3): a profile keyed
by a category that names this content, built from the acceptance the InferenceX runs themselves logged. The frozen pull holds
those logs: 546 of the 553 speculative single-turn logs hold exactly `12 x concurrency` requests, so the server's acceptance
averages are the benchmark's own. The data is the `SpecDecoding metrics` lines of those logs (mean acceptance length and
drafted tokens per 10-second interval); the source is the pull's `server_log.gz` per point and the run URL on the row; the
estimator is the drafted-token-weighted mean per (model, method, K, thinking). What it lacks: per-request acceptance (the
logs give 10-second aggregates, so the spread is unknown), MiniMax-M3's thinking default, and AgentX's Kimi-K3 curves
(the registry does not carry them; the log's synthetic value is pinned instead).

## What this does not show

The counts are of one frozen pull (2026-11-09) at the preliminary pins; they are not an accuracy result. No profile value is
invented here: a pair without a profile stays G5.
