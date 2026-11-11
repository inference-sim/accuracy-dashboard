# Scored run (in-sample)

IN-SAMPLE: the points are the ones the model was calibrated on or tuned against; there is no anchor list yet, so no point is held out. These figures say how well the simulator reproduces data it has seen, not how well it predicts new data.

**Coverage counts include every point, the test split too, by design. Accuracy figures are over train and validation points only, with N stated.** 49 of the points are test or prospective and 24 of them are scored; those 24 are left out of every accuracy figure, so none can be derived by subtraction (docs/m2/evaluation-protocol.md section 6).

- harness commit `f2754b1031e8d90962c6ec39675eeede91a42728`
- units sha256 `69533f0e375706c0a0483b4cd79c5f8dd565c6ac206ee49ba2ae74a90e208477` (188 units)
- pull manifest sha256 `bfa74604f84e64aa2f6c44d73fedee45a816c15d11f66da02396913354f5c3d4`
- point set sha256 `10cdb496f9893d88f59f25d2386e26532ad756e21d107ab6c51552d79ef60c18` (188 points)

Simulator `780f661ef9c18a2a9928acf8a63a67667cd597c0`, engine {'kind': 'vllm', 'version': '0.32.0'}, fields sha256 `dbe9123a677792edf030a0da584b9fc915c45ec206a5cebbffc3944568b6e879`.

## Headline (G1 to G4)

| Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % | Noise floor % |
|---|---|---|---|---|---|
| 60 | 78.8 (n=60) | 61.2 (n=37) | 5.0 (n=60) | 5.9 (n=37) | 1.6 (fallback; none measured per point) |

## By grade

**All points**

| Grade | Points | Share of all | Share of graded | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|---|---|
| G1 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G2 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G3 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G4 | 84 | 44.7% | 100.0% | 78.8 (n=60) | 61.2 (n=37) | 5.0 (n=60) | 5.9 (n=37) |
| G5 | 104 | 55.3% | - | - | - | - | - |

**All scored points: each grade on its own, by serving (aggregated or disaggregated)**

| Serving | Grade | Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|---|
| disaggregated | G1 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| disaggregated | G2 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| disaggregated | G3 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| disaggregated | G4 | 60 | 78.8 (n=60) | 61.2 (n=37) | 5.0 (n=60) | 5.9 (n=37) |

## Development split

Per-split figures use the DEVELOPMENT split of docs/m2/evaluation-protocol.md, not the ledger's held-out: its test set is 'development split, not the ledger's held-out'.

Assignment: sha256 of the salt `blis-dev-split-2` and the series, mod 100; train below 60, validation below 80, test above; a point measured after 2026-11-09 is prospective (test).

| Split | Points | In scope | Scored | Series | Grades | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % | Ranking (groups; Spearman, top-1, regret) |
|---|---|---|---|---|---|---|---|---|---|---|
| train | 114 | 114 | 41 | 6 | G4 41, G5 73 | 66.4 (n=41) | 42.2 (n=24) | 5.0 (n=41) | 5.6 (n=24) | 4; too few groups, too few groups, too few groups |
| validation | 25 | 25 | 19 | 1 | G4 19, G5 6 | 105.7 (n=19) | 96.3 (n=13) | 4.9 (n=19) | 6.5 (n=13) | 2; too few groups, too few groups, too few groups |
| test | 49 | | | | withheld: evaluate with `--evaluate-test`, which logs the evaluation | | | | | |
| prospective | 0 | | | | withheld: evaluate with `--evaluate-test`, which logs the evaluation | | | | | |
| unassigned | 0 | 0 | 0 | 0 |  | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) | 0; too few groups, too few groups, too few groups |

## Coverage

Counts of every point, test included, by design.

| Set | Points | Scored | Not scored | Failed | Share scored |
|---|---|---|---|---|---|
| all points | 188 | 84 | 104 | 0 | 44.7% |
| in scope | 188 | 84 | 104 | 0 | 44.7% |
| out of scope (AMD, TPU) | 0 | 0 | 0 | 0 | - |

Out-of-scope points by chip: .

## What would unlock the rest

Blocks: in-scope points held at G5 by the blocker. Alone: points that would be scored if only it were fixed.

| Blocker | Blocks | Alone |
|---|---|---|
| field_not_modelled:env.VLLM_FLASHINFER_ALLREDUCE_BACKEND | 48 | 48 |
| field_not_in_release:env.UCX_TLS | 48 | 12 |
| field_not_modelled:attention_config.use_trtllm_attention | 28 | 0 |
| not_in_catalog | 28 | 0 |
| field_not_modelled:enforce_eager | 20 | 0 |
| field_not_modelled:compilation_config.cudagraph_mode | 15 | 0 |
| field_not_in_release:env.VLLM_MINIMAX_M3_MSA_DECODE_BACKEND | 9 | 0 |
| field_not_modelled:env.UCX_RCACHE_MAX_UNRELEASED | 8 | 0 |
| field_not_in_release:env.NCCL_MNNVL_ENABLE | 6 | 0 |
| field_not_modelled:all2all_backend | 6 | 0 |
| field_not_modelled:env.NCCL_CUMEM_ENABLE | 6 | 0 |
| field_not_modelled:env.NCCL_NVLS_ENABLE | 6 | 0 |
| field_not_modelled:env.VLLM_USE_NCCL_SYMM_MEM | 6 | 0 |
| field_not_in_release:attention_config.use_trtllm_ragged_deepseek_prefill | 5 | 0 |
| field_not_in_release:env.VLLM_USE_FLASHINFER_MOE_FP4 | 5 | 0 |
| field_not_modelled:compilation_config.custom_ops | 5 | 0 |
| router_unsupported:dynamo-router | 2 | 0 |
| value_not_recorded:no_master_entry | 2 | 0 |
| field_not_modelled:compilation_config.mode | 1 | 0 |
| field_not_modelled:enable_sleep_mode | 1 | 0 |
| field_not_modelled:env.TILELANG_CLEANUP_TEMP_FILES | 1 | 0 |
| topology_unsupported:pd_pool_not_recorded | 1 | 0 |
| value_not_recorded | 1 | 0 |
| value_not_recorded:api_404 | 1 | 0 |
| out of scope (AMD, TPU) | 0 | 0 |

## Why points are below G1 or at G5 (design §11.6)

| Entry | Blocks | Alone | Demotes |
|---|---|---|---|
| `field_not_modelled:env.VLLM_FLASHINFER_ALLREDUCE_BACKEND` | 48 | 48 | 0 |
| `field_not_in_release:env.UCX_TLS` | 48 | 12 | 0 |
| `field_not_modelled:attention_config.use_trtllm_attention` | 28 | 0 | 0 |
| `not_in_catalog` | 28 | 0 | 0 |
| `field_not_modelled:enforce_eager` | 20 | 0 | 0 |
| `field_not_modelled:compilation_config.cudagraph_mode` | 15 | 0 | 0 |
| `field_not_in_release:env.VLLM_MINIMAX_M3_MSA_DECODE_BACKEND` | 9 | 0 | 0 |
| `field_not_modelled:env.UCX_RCACHE_MAX_UNRELEASED` | 8 | 0 | 0 |
| `field_not_in_release:env.NCCL_MNNVL_ENABLE` | 6 | 0 | 0 |
| `field_not_modelled:all2all_backend` | 6 | 0 | 0 |
| `field_not_modelled:env.NCCL_CUMEM_ENABLE` | 6 | 0 | 0 |
| `field_not_modelled:env.NCCL_NVLS_ENABLE` | 6 | 0 | 0 |
| `field_not_modelled:env.VLLM_USE_NCCL_SYMM_MEM` | 6 | 0 | 0 |
| `field_not_in_release:attention_config.use_trtllm_ragged_deepseek_prefill` | 5 | 0 | 0 |
| `field_not_in_release:env.VLLM_USE_FLASHINFER_MOE_FP4` | 5 | 0 | 0 |
| `field_not_modelled:compilation_config.custom_ops` | 5 | 0 | 0 |
| `router_unsupported:dynamo-router` | 2 | 0 | 0 |
| `value_not_recorded:no_master_entry` | 2 | 0 | 0 |
| `field_not_modelled:compilation_config.mode` | 1 | 0 | 0 |
| `field_not_modelled:enable_sleep_mode` | 1 | 0 | 0 |
| `field_not_modelled:env.TILELANG_CLEANUP_TEMP_FILES` | 1 | 0 | 0 |
| `topology_unsupported:pd_pool_not_recorded` | 1 | 0 | 0 |
| `value_not_recorded` | 1 | 0 | 0 |
| `value_not_recorded:api_404` | 1 | 0 | 0 |
| `client_difference:benchmark_client` | 0 | 0 | 84 |
| `client_difference:client_flags` | 0 | 0 | 84 |
| `client_difference:failed_requests` | 0 | 0 | 84 |
| `client_difference:send_gap` | 0 | 0 | 84 |
| `client_difference:sent_prompt_lengths` | 0 | 0 | 84 |
| `coefficient_method:cost-model-attention/attention_decode_floor_mla` | 0 | 0 | 84 |
| `coefficient_method:cost-model-fabric/fabric_bandwidth_efficiency` | 0 | 0 | 84 |
| `coefficient_method:cost-model-host-overheads/host_admission_per_request` | 0 | 0 | 84 |
| `coefficient_method:cost-model-host-overheads/host_admission_per_token` | 0 | 0 | 84 |
| `coefficient_method:cost-model-host-overheads/host_completion` | 0 | 0 | 84 |
| `coefficient_method:cost-model-host-overheads/host_launch_eager_per_layer` | 0 | 0 | 84 |
| `coefficient_method:cost-model-host-overheads/host_launch_per_kernel` | 0 | 0 | 84 |
| `coefficient_method:cost-model-host-overheads/host_output_token` | 0 | 0 | 84 |
| `coefficient_method:cost-model-host-overheads/host_replay_graph_per_step` | 0 | 0 | 84 |
| `coefficient_method:cost-model-memory/activation_buffer_count_moe_1rank` | 0 | 0 | 84 |
| `coefficient_method:cost-model-memory/activation_scratch_floor_bytes` | 0 | 0 | 84 |
| `coefficient_method:cost-model-memory/cudagraph_capture_bytes_full_and_piecewise` | 0 | 0 | 84 |
| `coefficient_method:cost-model-primitives/engine_workspace_bytes` | 0 | 0 | 84 |
| `coefficient_method:cost-model-primitives/hbm_derate` | 0 | 0 | 84 |
| `coefficient_range:unevaluated` | 0 | 0 | 84 |
| `estimated:cluster.fabric` | 0 | 0 | 84 |
| `estimated:engine.decode.recipe` | 0 | 0 | 84 |
| `estimated:engine.prefill.recipe` | 0 | 0 | 84 |
| `estimated:gpu_memory_utilization` | 0 | 0 | 84 |
| `execution_mode:router dynamo (experiment)` | 0 | 0 | 84 |
| `interim_status:env.VLLM_ENGINE_READY_TIMEOUT_S` | 0 | 0 | 84 |
| `interim_status:env.VLLM_FLOAT32_MATMUL_PRECISION` | 0 | 0 | 84 |
| `interim_status:trust_remote_code` | 0 | 0 | 84 |
| `kernel_hash:unevaluated` | 0 | 0 | 84 |
| `other_release:engine release` | 0 | 0 | 84 |
| `ported_functions_unpublished:engine release` | 0 | 0 | 84 |
| `resolved_differs:unevaluated` | 0 | 0 | 84 |
| `value_class:unevaluated` | 0 | 0 | 84 |
| `coefficient_method:cost-model-memory/activation_buffer_count_moe_4rank` | 0 | 0 | 83 |
| `coefficient_method:cost-model-primitives/nccl_communicator_bytes_4rank` | 0 | 0 | 83 |
| `client_difference:client_saturation` | 0 | 0 | 21 |
| `execution_mode:pool placement` | 0 | 0 | 17 |
| `coefficient_method:cost-model-memory/activation_buffer_count_moe_8rank` | 0 | 0 | 1 |
| `coefficient_method:cost-model-primitives/nccl_communicator_bytes_8rank` | 0 | 0 | 1 |
