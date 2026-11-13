# Agentic coverage: the 47 points and what blocks each

Contents: [Result](#result) · [The three groups](#the-three-groups) · [What was changed](#what-was-changed) · [The 47 points](#the-47-points) · [How to reproduce](#how-to-reproduce) · [What this does not show](#what-this-does-not-show)

All 47 `agentic_traces` points of the baseline's frozen pull are in scope (h200 35, h100 7, b300 5), and **none is scored**: no point reaches a G1 to G4 grade. This page says, for each group, the first refusal and every field behind it, and whether the m2/5 simulator could score the group honestly (by a named substitution) or must refuse it. The replay itself is ready: [the agentic replay check](agentic-replay-check.md) shows the idle cap and the warm-up reaching the simulator.

## Result

| Group | Points | First refusal | Honestly scorable by this simulator? |
|---|---|---|---|
| Kimi-K3 on H200, run of 2026-08-07 | 25 | `value_not_recorded` (`server_log_missing`; also `artifact_unmatched:no_recipe_fingerprint`) | No: the run's artifacts (its client export) expired; the replay's inputs are not recorded |
| Kimi-K3 on H200, run of 2026-09-13 | 10 | `field_not_modelled:disable_custom_all_reduce` | No: 13 fields refuse it, and with them opened the simulator refuses the model (`layer kind kda_dense: recurrent state is not mapped to a KV cache spec`) |
| MiniMax-M3 on H100 | 7 | 5 `field_not_modelled:cpu_offload_gb`; 2 `value_not_recorded:kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use` | No: weight offload to the CPU has no honest substitution |
| Kimi-K3 on B300 | 5 | `value_not_recorded:kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use` | No: decode context parallelism, the drafter and the offload size are unmodelled or unrecorded |

## The three groups

**Kimi-K3 on H200, 35 points, two runs.** The 25 points of the run of 2026-08-07 have no server log, no client export and no recipe fingerprint: GitHub expires artifacts after 90 days and this run is older. Their replay cannot be written (the corpus alias, seed and window come from the export), so they stay `value_not_recorded`; the master configuration at their commit has no search-space item that is the row (`no_master_entry`), so no recipe is recovered either. The 10 points of the run of 2026-09-13 have their client export and no log. They are multi-node colocated runs: one engine at tensor-parallel 16 and data-parallel 2 with expert parallelism over four H200 nodes. **Their recipe is recovered** (InferenceX `d76e66d9918f8c9ca2624e2e964c5ca969504e4f`, `benchmarks/multi_node/srt-slurm-recipes/vllm/kimi-k3/agentic/agg-h200-tp16dp2ep32-latency-agentic.yaml`, found as the one `worker` item of `configs/nvidia-master.yaml` that is the row) and the multi-node colocated writer states it: a four-node cluster with a fabric class, one pool at `tp 16, dp 2, enable_expert_parallel`, `max_num_batched_tokens 4096`, `max_num_seqs 5`, the DSpark drafter and the recipe's synthetic acceptance length (2.51). The point names the recovery (`engine.aggregated.recipe`) and the assumed fabric. The recipe's arguments then stop it at the engine's field list:

* `field_not_in_release`: `env.CUDA_LAUNCH_BLOCKING`, `env.GLOO_SOCKET_IFNAME`, `env.HUGGINGFACE_HUB_CACHE`, `env.NCCL_SOCKET_IFNAME`, `env.TRANSFORMERS_CACHE`, `env.VLLM_ROUTED_DOWN_PROJ_STREAM_TOKEN_THRESHOLD`;
* `field_not_modelled`: `disable_custom_all_reduce`, `enforce_eager`, `moe_backend`, `speculative_config.rejection_sample_method`, `env.HF_HUB_CACHE`, `env.NCCL_CUMEM_ENABLE`, `env.PYTORCH_CUDA_ALLOC_CONF`.

*Dry run, not a result.* With those 13 fields marked proven inert in a scratch copy of the field list (placeholder proof, as in [the field-gate dry run](dry-run-field-gate.md)), the simulator is asked about a point and refuses all 10: `layer kind kda_dense: recurrent state is not mapped to a KV cache spec`. Kimi-K3 has linear-attention layers whose recurrent state the engine does not place; so even with the field list opened, the points are not scorable until blis-vllm maps it. Not an invention to work around: the dashboard writes what the run set and the engine refuses.

**MiniMax-M3 on H100, 7 points.** All set `cpu_offload_gb` (weights offloaded to host memory, blis-vllm#65, M4), `default_chat_template_kwargs.thinking_mode` and `speculative_config.rejection_sample_method`; 2 more set `kv_connector_extra_config.load_async` and record no `cpu_bytes_to_use` (the same two), and for one of those the `engine_id` conflicts between its launch configuration and its log. Weight offload moves every step's time by the PCIe transfer of the offloaded weights, so any stand-in (dropping the field) would simulate a different deployment; there is no honest named substitution. The other two fields are the engine's to classify (a chat-template kwarg is the client's; the synthetic rejection sampler is the acceptance model the dashboard already pins by length).

**Kimi-K3 on B300, 5 points.** They set `decode_context_parallel_size` and `dcp_comm_backend` (the KV cache is split across ranks: blis-vllm#109), `prefix_match_unit`, `rejection_sample_method`, and the offload connector with no recorded `cpu_bytes_to_use`; their draft model (`speculative_config.model`) is recorded by no source. None can be dropped honestly.

## What was changed

* A multi-node colocated run (`is_multinode`, not `disagg`) is no longer refused for its topology: it is one pool over several nodes, and the cluster, the fabric and the pool are written as for any engine (`score.score_point`, `settings.build`).
* A colocated multi-node run whose server log is gone has its arguments recovered from its aggregated recipe at the run's commit, as [disaggregation](../disaggregation.md) describes for prefill/decode, and says so on the point. The recipe is found from the `worker` block of the master configuration (an agentic item has no sequence lengths), checked against the row's GPUs and parallel sizes, and kept by the pull.
* A speculative agentic point pins the acceptance length its server states (a synthetic one); the workload's category and thinking mode are the AgentX workload file's ([workload statements](workload-statements.md)). None of these 47 is held by a missing category.

## The 47 points

Scored with the simulator and the pins of [prefill/decode coverage](pd-coverage.md) (inference-sim `81a46ba3`, blis-substrate v0.14.0, blis-vllm `33455e4c`). The first refusal is the G5 reason of the contract (`not_scored.jsonl`); `value_not_recorded` with no subject is the scorer's `server_log_missing`. The first refusal of the ten Kimi-K3 H200 rows (`field_not_modelled:disable_custom_all_reduce`) is from an earlier scoring that had their recipes; the pull of the committed after-run holds no recipe or log for them, so its contract has them as `value_not_recorded`. These rows were not scored again at the final pins, and no agentic point is scored in the committed run.

| Point | Model, chip | Measured | Clients | First refusal |
|---|---|---|---|---|
| `b3934a3e00df` | kimik3 b300 | 2026-08-16 | 1 | `value_not_recorded:kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use` |
| `34cae95814dc` | kimik3 b300 | 2026-08-16 | 2 | `value_not_recorded:kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use` |
| `b07d2b62b1db` | kimik3 b300 | 2026-08-16 | 4 | `value_not_recorded:kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use` |
| `e33b395f105e` | kimik3 b300 | 2026-08-16 | 8 | `value_not_recorded:kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use` |
| `5ebb29f8795a` | kimik3 b300 | 2026-08-16 | 16 | `value_not_recorded:kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use` |
| `c4037822cef9` | kimik3 h200 | 2026-08-07 | 1 | `value_not_recorded` |
| `230d558de66a` | kimik3 h200 | 2026-08-07 | 2 | `value_not_recorded` |
| `0c1cb95b254f` | kimik3 h200 | 2026-08-07 | 3 | `value_not_recorded` |
| `215160539a9d` | kimik3 h200 | 2026-08-07 | 4 | `value_not_recorded` |
| `2cef0352b6fe` | kimik3 h200 | 2026-08-07 | 5 | `value_not_recorded` |
| `6870fd2c41ce` | kimik3 h200 | 2026-08-07 | 6 | `value_not_recorded` |
| `5e4fe27be900` | kimik3 h200 | 2026-08-07 | 7 | `value_not_recorded` |
| `2d6abd94d100` | kimik3 h200 | 2026-08-07 | 8 | `value_not_recorded` |
| `d612b37e7001` | kimik3 h200 | 2026-08-07 | 8 | `value_not_recorded` |
| `7066c5ef3949` | kimik3 h200 | 2026-08-07 | 10 | `value_not_recorded` |
| `8984c91779bb` | kimik3 h200 | 2026-08-07 | 10 | `value_not_recorded` |
| `400a67d7cdb0` | kimik3 h200 | 2026-08-07 | 12 | `value_not_recorded` |
| `5a29abbfe6e4` | kimik3 h200 | 2026-08-07 | 12 | `value_not_recorded` |
| `ae976fc9df61` | kimik3 h200 | 2026-08-07 | 14 | `value_not_recorded` |
| `dafcde3d292a` | kimik3 h200 | 2026-08-07 | 14 | `value_not_recorded` |
| `53006e2a78c9` | kimik3 h200 | 2026-08-07 | 16 | `value_not_recorded` |
| `8754ee6445c0` | kimik3 h200 | 2026-08-07 | 16 | `value_not_recorded` |
| `ce4b8e459d16` | kimik3 h200 | 2026-08-07 | 18 | `value_not_recorded` |
| `d74aab2e10db` | kimik3 h200 | 2026-08-07 | 20 | `value_not_recorded` |
| `d4bb3244cb8c` | kimik3 h200 | 2026-08-07 | 22 | `value_not_recorded` |
| `185c7422e274` | kimik3 h200 | 2026-08-07 | 24 | `value_not_recorded` |
| `f6b96889569e` | kimik3 h200 | 2026-08-07 | 26 | `value_not_recorded` |
| `f8e429a5705e` | kimik3 h200 | 2026-08-07 | 28 | `value_not_recorded` |
| `a0ffa4720878` | kimik3 h200 | 2026-08-07 | 30 | `value_not_recorded` |
| `e34fe5e46a90` | kimik3 h200 | 2026-08-07 | 32 | `value_not_recorded` |
| `1538121d3e0e` | kimik3 h200 | 2026-09-13 | 1 | `field_not_modelled:disable_custom_all_reduce` |
| `bc8b74da98aa` | kimik3 h200 | 2026-09-13 | 2 | `field_not_modelled:disable_custom_all_reduce` |
| `12ac33ae64c0` | kimik3 h200 | 2026-09-13 | 3 | `field_not_modelled:disable_custom_all_reduce` |
| `97c8aee8dc0d` | kimik3 h200 | 2026-09-13 | 4 | `field_not_modelled:disable_custom_all_reduce` |
| `a2d728b4c91b` | kimik3 h200 | 2026-09-13 | 5 | `field_not_modelled:disable_custom_all_reduce` |
| `966e45f1d613` | kimik3 h200 | 2026-09-13 | 6 | `field_not_modelled:disable_custom_all_reduce` |
| `e1d9c5f4b06f` | kimik3 h200 | 2026-09-13 | 7 | `field_not_modelled:disable_custom_all_reduce` |
| `edaf0885722a` | kimik3 h200 | 2026-09-13 | 8 | `field_not_modelled:disable_custom_all_reduce` |
| `21a7f4e21092` | kimik3 h200 | 2026-09-13 | 10 | `field_not_modelled:disable_custom_all_reduce` |
| `5e10e49d79e7` | kimik3 h200 | 2026-09-13 | 12 | `field_not_modelled:disable_custom_all_reduce` |
| `8e6c9c88518d` | minimaxm3 h100 | 2026-09-27 | 1 | `field_not_modelled:cpu_offload_gb` |
| `0d5347193772` | minimaxm3 h100 | 2026-09-27 | 2 | `field_not_modelled:cpu_offload_gb` |
| `22df91c7a6e5` | minimaxm3 h100 | 2026-09-27 | 3 | `field_not_modelled:cpu_offload_gb` |
| `226496c3c1a8` | minimaxm3 h100 | 2026-09-27 | 4 | `field_not_modelled:cpu_offload_gb` |
| `732547f1c73f` | minimaxm3 h100 | 2026-09-27 | 5 | `field_not_modelled:cpu_offload_gb` |
| `811520316e03` | minimaxm3 h100 | 2026-09-27 | 6 | `value_not_recorded:kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use` |
| `ae4ded043abc` | minimaxm3 h100 | 2026-09-27 | 8 | `value_not_recorded:kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use` |

## How to reproduce

The 12 points that are not Kimi-K3 on H200 are in the baseline's frozen pull (`/tmp/baseline/pull2` on the machine that froze it; [reproducing](../reproducing.md)). The 35 Kimi-K3 H200 points were frozen again, with the recipe, by `python3 orchestrator/baseline/freeze.py --units-file units-kimi.txt --ledger SUBSTRATE/catalog/ledger --today 2026-11-09 --out PULL --cache ARTIFACTS` (the unit ids of the baseline's Kimi-K3 H200 points). Score either with `orchestrator/ingest/cli.py score ... --units FILE` as in [prefill/decode coverage](pd-coverage.md); the corpora (`resolve_agentic_corpus.py --all`) are required. About 40 s, 2 GB. The dry run: the same command with `--fields` naming a copy of `fields.json` in which the 13 fields above are `proven_inert` with a placeholder proof.

## What this does not show

* No agentic accuracy: nothing was scored.
* The dry run is a measurement of what the simulator says, not a prediction.
* The 25 points of the run of 2026-08-07 could be recovered only if the artifacts were still available (InferenceX would have to re-upload them).
