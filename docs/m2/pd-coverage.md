# Prefill/decode coverage: what the two-pool writer scores, at what error, and what it refuses

Contents: [What was run](#what-was-run) · [Inputs](#inputs) · [Result with the substrate's router table](#result-with-the-substrates-router-table) · [Result of the writer alone](#result-of-the-writer-alone-an-experiment) · [Accuracy](#accuracy-train-and-validation-points-only) · [What is refused, by name](#what-is-refused-by-name) · [Checks of the recovery](#checks-of-the-recovery) · [How to reproduce](#how-to-reproduce) · [What this does not show](#what-this-does-not-show) · [What it needs from other repositories](#what-it-needs-from-other-repositories)

The method is [disaggregation](../disaggregation.md); the reasons are counted as [coverage accounting](../coverage-accounting.md) describes. This page is the measurement.

## What was run

The 188 in-scope single-turn `dynamo-vllm` rows with neither pool on DP attention (minimaxm2.5 152, minimaxm3 29, kimik2.5 5, dsv4 2; b300 61, gb300 55, b200 43, gb200 29), frozen from the live API with the pull of the baseline's command (`--today 2026-11-09`), each with its recipe at the run's commit. The other 308 single-turn Dynamo rows have a pool on DP attention and are refused by name (`pd_pool_data_parallel` for all 308, and `pd_unequal_data_parallel` as well for 290; the writer counts these from the rows' recorded worker shapes, 18 being equal data-parallel size above 1); they are not in this pull. One more row records a pool with no workers (`pd_pool_not_recorded`).

Two runs of the same scorer over the same pull, differing in one input:

| Run | Directory | The router table | Meaning |
|---|---|---|---|
| A | [pd-table-as-published](pd-table-as-published/README.md) | the substrate's own (`catalog/routers` at the pinned commit) | what the dashboard publishes |
| B | [pd-writer-experiment](pd-writer-experiment/README.md) | the same, plus `--router-policy-experiment round-robin` | the writer's accuracy with llm-d's round-robin standing in for Dynamo's; **an experiment, not a grade** (every such point names `router dynamo (experiment)`, and the run is `experimental`) |

## Inputs

| Input | Value |
|---|---|
| Harness | accuracy-dashboard commit in each run's `provenance.json` (`harness_commit`) |
| Simulator | inference-sim `780f661ef9c18a2a9928acf8a63a67667cd597c0` (branch `m2/5-closeness-data-in-the-result`), built with Go 1.27.2 |
| Catalog, registry | blis-substrate `f70c6c7503a47442c4c5d989f8f17b093c14e069` (the pin of the audited M2 stack), as a 40-hex commit for `--catalog-release` and `--registry-release` |
| Field list | blis-vllm `96ea750e3a626ab2f9c60ca3bc871b8a74839cc2` `fields.json`, sha256 `dbe9123a677792edf030a0da584b9fc915c45ec206a5cebbffc3944568b6e879` |
| Pull | `pull_manifest_sha256` `bfa74604f84e64aa2f6c44d73fedee45a816c15d11f66da02396913354f5c3d4`, 188 points; not committed (60 MB of server logs and recipes) |
| Units | the 188 ledger units (`units.txt` of each run directory) |
| Corpora | not used (single-turn) |

Engine: the runs measured vLLM v0.20.1 (152 rows), nightly images and v0.21.0; the simulator runs 0.32.0, so a scored point is G4 (`other_release`, and `ported_functions_unpublished`).

## Result with the substrate's router table

The substrate's table has one Dynamo entry, `dynamo-round-robin`, whose policy is `none`, and which lists no router build. **No point is scored.** All 188 are G5; the primary reason of 186 is `router_unsupported:dynamo-router:revision_not_covered` (every recipe pins Dynamo by a wheel version, which maps to no commit), and of 2, `router_unsupported:dynamo-router` (no recipe to give the mode).

Blocks and alone, over the 188 (the full list is `table.md` of the run):

| Reason | Blocks | Alone |
|---|---|---|
| `router_unsupported:dynamo-router:revision_not_covered` | 186 | **84** |
| `field_not_modelled:env.VLLM_FLASHINFER_ALLREDUCE_BACKEND` | 48 | 0 |
| `field_not_in_release:env.UCX_TLS` | 48 | 0 |
| `field_not_modelled:attention_config.use_trtllm_attention` | 28 | 0 |
| `not_in_catalog` (MiniMax-M3 is not in the catalog at this pin) | 28 | 0 |
| `field_not_modelled:enforce_eager` | 20 | 0 |
| `field_not_modelled:compilation_config.cudagraph_mode` | 15 | 0 |
| `field_not_modelled:env.UCX_RCACHE_MAX_UNRELEASED` | 8 | 0 |
| `field_not_modelled:all2all_backend` | 6 | 0 |
| `value_not_recorded:no_master_entry` (no search-space item is the row) | 2 | 0 |
| `topology_unsupported:pd_pool_not_recorded` (a pool with no workers) | 1 | 0 |
| `value_not_recorded:api_404` | 1 | 0 |

The router alone holds back 84 points. With the substrate's layer 12 entries (`dynamo-round-robin` to llm-d's round-robin policy, with a bound; `dynamo-random`; `dynamo-kv` with policy `none`) read through `--router-table`, and the build assumed to be the entry's (`--assume-router-revision 1682167d3c97f0fc8cd405dee51f17288eeaeb55`, since the recipes record a wheel), the result is still **no point**: all 186 are `no_bound_for_regime`. The entries' bounds were measured for model `minimax-m2.5` on `gb200-nvl72` at 1024/1024, 16 to 1024 clients, shapes 1P3D, 2P3D, 3P2D and 4P1D; the 84 points that clear every other gate are the NVFP4 model `minimax-m2.5-nvfp4`, 90 of the 188 rows are 8192/1024 (no workload kind), and the rest differ in hardware part or shape. A bound for the NVFP4 model, 8192/1024 and the other chips is what would score them.

## Result of the writer alone (an experiment)

Run B stands llm-d's round-robin in for Dynamo's router on every point the table refuses. It scores **84** of the 188 (all G4), refuses 104 and fails none; the contract validates.

| Scored (84) | b200 | b300 | gb200 | gb300 |
|---|---|---|---|---|
| minimaxm2.5 NVFP4, 1k/1k | 16 | 6 | 16 | 9 |
| minimaxm2.5 NVFP4, 8k/1k | 8 | 11 | 8 | 10 |

The 104 refused, by first reason: `field_not_modelled:env.VLLM_FLASHINFER_ALLREDUCE_BACKEND` 48 (the fp8 recipes of MiniMax-M2.5 on b300 and gb300), `attention_config.use_trtllm_attention` 28 (MiniMax-M3 on b200 and b300), `field_not_in_release:env.UCX_TLS` 12 and `field_not_modelled:env.UCX_RCACHE_MAX_UNRELEASED` 8 (NIXL's transport settings, on the NVFP4 recipes that set them), `all2all_backend` 6 (kimik2.5 and one dsv4), and 2 `router_unsupported:dynamo-router` (no recipe). The transport variables are the cheapest to clear: 20 more NVFP4 points score when `blis-vllm` classifies them.

Every scored point names: the recipe recovery of each pool (`engine.prefill.recipe`, `engine.decode.recipe`), `cluster.fabric` (no recipe states a class; the recipes set `UCX_TLS=cuda_copy,rc`. The class comes from the fabric InferenceX documents for the chip SKU, cited on the point: `ib-400g` for gb200-nvl72 (InfiniBand NDR), `ib-800g` for gb300 (InfiniBand XDR), and, as labelled stand-ins of the same line rate for documented RoCEv2 Ethernet, `ib-400g` for b200 and `ib-800g` for b300; see `docs/comparability.md`), the `benchmark_client` difference, the experiment, `pool placement` for the 17 whose recipe allows prefill and decode workers on one node (the check below), and the usual coefficient, release and G1-condition substitutions.

## Accuracy: train and validation points only

Test points are withheld from every figure (the [protocol](evaluation-protocol.md), section 6): 24 of the 84 scored points are test, so the figures below rest on **60** points (41 train, 19 validation). They are in-sample, on the dashboard's development split, and say how well the simulator reproduces data it was not tuned on but which sits in the registry's neighbourhood; they are not held-out results.

| | n | TTFT MAPE % | TPOT MAPE % |
|---|---|---|---|
| all | 60 | 78.8 (median 24.7, bias +54) | 5.0 (median 3.9, bias -2) |
| 1k/1k | 31 | 128.6 (median 28.3, bias +129) | 5.4 |
| 8k/1k | 29 | 25.6 (bias -26) | 4.5 |
| 32 clients or fewer | 24 | 16.3 | 4.4 |
| 33 to 128 clients | 17 | 27.7 | 4.2 |
| more than 128 clients | 19 | 203.6 (median 79.0) | 6.5 |

How to read it. **TPOT is close everywhere** (4% to 7%). **TTFT is close at low load and wrong where the prefill pool saturates.** Up to 128 clients it is within 16% to 28% of the measurement: BLIS over-predicts TTFT at 1k/1k by 0 to 30% and under-predicts it by 11% to 33% at 8k/1k, a bias that does not change with load, so the fixed costs of the Dynamo path (frontend tokenisation, the router hop, the NIXL notification), which BLIS does not model, and the handoff priced over an assumed fabric are the likely terms. Above 128 clients, at 1k/1k, the recipes' single one-GPU prefill worker with a chunk of 2048 tokens saturates in the simulation (TTFT 1.5 to 30 s) and does not in the measurement (0.4 to 15 s): the points are 1P3D and 2P3D shapes at the knee of the curve, where a few percent of throughput moves TTFT by seconds. That is the regime in which the ranking of topologies is decided, so the TTFT figures here say nothing good about ranking; no ranking metric is computed on this set (the groups are too few: 4 train series and 2 validation ones; `table.md`).

No grade other than G4 is possible: the engine release differs on every point, and four G1 conditions are unevaluated.

## What is refused, by name

Counts are over the 188 ([run B's `table.md`](pd-writer-experiment/table.md), "What would unlock the rest"; blocks and alone):

| Reason | Meaning | Blocks | Alone | Cleared by |
|---|---|---|---|---|
| `router_unsupported:...:revision_not_covered` / `no_bound_for_regime` | the table maps nothing for the run's build, or its bound has no regime for the point | 186 | 84 | the substrate: entries for the NVFP4 model and the lengths, and a way to name a wheel's commit |
| `field_not_modelled` / `field_not_in_release` on 18 environment variables and engine fields | the engine's field list | see table | 48 (`VLLM_FLASHINFER_ALLREDUCE_BACKEND`) | blis-vllm |
| `not_in_catalog` | MiniMax-M3 is not in the catalog at this pin (layer 11 adds `minimax-m3-nvfp4`) | 28 | 0 | the substrate bump |
| `value_not_recorded:no_master_entry` | the master configuration at the run's commit has no search-space item that is the row (one dsv4 GB200 row records no decode workers) | 2 | 0 | not removable |
| `topology_unsupported:pd_pool_data_parallel`, `pd_unequal_data_parallel` | the 308 DP-attention rows, not in this pull | 308 (not run) | | blis-vllm#47, inference-sim#1952 (M3) |

## Checks of the recovery

* **The surviving log agrees with the recipe.** 40 of the 188 points have the API's server log (b300 only). Each holds one engine core's resolved configuration; in all 40 it is the decode worker's, and its tensor-parallel size, data-parallel size, KV dtype and prefix-caching flag are the recipe's decode pool's and not the prefill pool's. The scorer makes this check on every point with a log (`conflict:server_log_vs_recipe.<field>`).
* **The recipe is the row.** Workers and GPUs per worker of both pools, sequence lengths, concurrency and precision are compared; none of the 186 recipes disagreed.
* **Two pools never share a node in BLIS; some recipes allow it.** The recipes of 17 of the 84 scored points allow a prefill and a decode worker on one node (`allow_prefill_decode_colocation`); the handoff is priced over the fabric for all, as the recipes' `UCX_TLS=cuda_copy,rc` also routes it.

## How to reproduce

```
# 1. freeze the 188 units with their recipes (network; a GitHub token in GH_TOKEN or `gh auth`; about 10 minutes)
python3 orchestrator/baseline/freeze.py --units-file units.txt --ledger SUBSTRATE/catalog/ledger \
  --today 2026-11-09 --out PULL --cache ARTIFACTS
# 2. run A: the substrate's table
python3 orchestrator/ingest/cli.py score --pull PULL --out OUT_A --units units.txt \
  --blis INFERENCE_SIM/blis --sim-build 780f661ef9c18a2a9928acf8a63a67667cd597c0 \
  --catalog SUBSTRATE/catalog --registry SUBSTRATE/registry \
  --catalog-release f70c6c7503a47442c4c5d989f8f17b093c14e069 --registry-release f70c6c7503a47442c4c5d989f8f17b093c14e069 \
  --fields FIELDS.json --harness-commit HARNESS_COMMIT --corpus-dir CORPORA
# 3. run B: add  --router-policy-experiment round-robin
# 4. the table
python3 orchestrator/baseline/split.py splits --pull PULL --out OUT/../splits.json
python3 orchestrator/baseline/compare.py run --dir OUT --sample in_sample --out table
```

`INFERENCE_SIM` is a checkout at the commit with `go build -o blis .` (about 2 minutes); `SUBSTRATE` a checkout at `f70c6c7503a47442c4c5d989f8f17b093c14e069`; `FIELDS.json` is blis-vllm's `fields.json` at `96ea750e3a626ab2f9c60ca3bc871b8a74839cc2`. The freeze reads the live API and GitHub: the artifacts it needs expire after 90 days, and the server logs of 148 of the 188 rows are already gone (the recipes are not), so a later freeze differs from this one in `server_log` only. Run A takes about 20 s (nothing is simulated) and run B about a minute on an idle laptop (84 simulations; far longer when the machine is loaded), 2 GB. To use the substrate's layer 12 entries: `--router-table SUBSTRATE_L12/catalog/routers --assume-router-revision 1682167d3c97f0fc8cd405dee51f17288eeaeb55`.

## What this does not show

* **Not a ranking result.** Throughput per GPU is not scored and the ranking evaluator is not built; the saturated points show the TTFT error is largest where topologies are compared.
* **Not a Dynamo result.** The router is a stand-in in run B and the substrate maps none in run A. TTFT's definition under Dynamo (the prefill worker's sampled token or the decode worker's) is not established; BLIS reports the decode leg's.
* **The handoff's price is an assumption.** `ib-400g` at the registry's efficiency for a point-to-point pull, with the expert all-to-all floor standing in for a base latency; no KV-pull measurement exists (blis-registry#78).
* **The client differs.** The recipes' benchmark is srt-slurm's `sa-bench`, not InferenceX's client; the replay sends the InferenceX client's seed-0 lengths. The point names it.
* **Engine arguments are the recipe's** (the launcher's intent), checked against the one surviving log only for 40 points.
* **Only 2 of the 4 chips' fp8 or MiniMax-M3 rows score**, and only dp-free rows; the flagship dsv4 and Kimi shapes are DP attention.

## What it needs from other repositories

| From | What |
|---|---|
| blis-vllm | classify `env.UCX_TLS`, `env.UCX_RCACHE_MAX_UNRELEASED` (NIXL's transport; 20 NVFP4 points), `env.VLLM_FLASHINFER_ALLREDUCE_BACKEND` (48), `attention_config.use_trtllm_attention` (28), `enforce_eager`, `cudagraph_mode`, `all2all_backend`; #47 for DP attention in a pool |
| inference-sim | #1952 (pools of unequal data-parallel size) |
| blis-substrate | router entries for the NVFP4 model, 8192/1024 and the other chips, with a way to name a wheel's commit (or a build map), so a Dynamo point can be mapped; the `minimax-m3-nvfp4` catalog entry (layer 11) |
| InferenceX | the Dynamo build commit of a run (a pinned `hash` in the recipe) |
