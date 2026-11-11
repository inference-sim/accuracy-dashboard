# Scored run (in-sample)

IN-SAMPLE: the points are the ones the model was calibrated on or tuned against; there is no anchor list yet, so no point is held out. These figures say how well the simulator reproduces data it has seen, not how well it predicts new data.

**Coverage counts include every point, the test split too, by design. Accuracy figures are over train and validation points only, with N stated.** 446 of the points are test or prospective and 30 of them are scored; those 30 are left out of every accuracy figure, so none can be derived by subtraction (docs/m2/evaluation-protocol.md section 6).

- harness commit `54fbe017a4b2ea698abd7f8c9ceea19bf2a2ed9c`
- units sha256 `d89f860a46c0470a22543dc7fb77b8d1b10e508ce4f5ef5073e96f359f08597e` (1740 units)
- pull manifest sha256 `c8f2ea928b0d4582afdc3fbf11ef9d6847a359791a520f497ee146e806a96166`
- point set sha256 `6818482f91e308ee2b6f844d347de68fef6e90cbc27c22b41d21643d580e5c60` (1734 points)

Simulator `v0.16.0`, engine {'kind': 'vllm', 'version': '0.32.0'}, fields sha256 `d32342c4f9ae5c578ba578fd5e6575aa8db8bce099e0708480d55f7e8de5a6fc`.

## Headline (G1 to G4)

| Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % | Noise floor % |
|---|---|---|---|---|---|
| 11 | 47.1 (n=11) | too few points (n=9) | 58.0 (n=11) | too few points (n=9) | 1.6 (fallback; none measured per point) |

## By grade

**All points**

| Grade | Points | Share of all | Share of graded | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|---|---|
| G1 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G2 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G3 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G4 | 41 | 2.4% | 100.0% | 47.1 (n=11) | too few points (n=9) | 58.0 (n=11) | too few points (n=9) |
| G5 | 1683 | 97.1% | - | - | - | - | - |
| failed | 10 | | | | | | |

**All scored points: each grade on its own, by serving (aggregated or disaggregated)**

| Serving | Grade | Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|---|
| aggregated | G1 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| aggregated | G2 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| aggregated | G3 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| aggregated | G4 | 11 | 47.1 (n=11) | too few points (n=9) | 58.0 (n=11) | too few points (n=9) |

## Development split

Per-split figures use the DEVELOPMENT split of docs/m2/evaluation-protocol.md, not the ledger's held-out: its test set is 'development split, not the ledger's held-out'.

Assignment: sha256 of the salt `blis-dev-split-2` and the series, mod 100; train below 60, validation below 80, test above; a point measured after 2026-11-09 is prospective (test).

| Split | Points | In scope | Scored | Series | Grades | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % | Ranking (groups; Spearman, top-1, regret) |
|---|---|---|---|---|---|---|---|---|---|---|
| train | 956 | 626 | 0 | 33 | G5 956 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) | 0; too few groups, too few groups, too few groups |
| validation | 332 | 220 | 11 | 9 | G4 11, G5 321 | 47.1 (n=11) | too few points (n=9) | 58.0 (n=11) | too few points (n=9) | 1; too few groups, too few groups, too few groups |
| test | 446 | | | | withheld: evaluate with `--evaluate-test`, which logs the evaluation | | | | | |
| prospective | 0 | | | | withheld: evaluate with `--evaluate-test`, which logs the evaluation | | | | | |
| unassigned | 0 | 0 | 0 | 0 |  | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) | 0; too few groups, too few groups, too few groups |

## Coverage

Counts of every point, test included, by design.

| Set | Points | Scored | Not scored | Failed | Share scored |
|---|---|---|---|---|---|
| all points | 1734 | 41 | 1683 | 10 | 2.4% |
| in scope | 1188 | 41 | 1137 | 10 | 3.5% |
| out of scope (AMD, TPU) | 546 | 0 | 546 | 0 | 0.0% |

Out-of-scope points by chip: mi300x 95, mi325x 171, mi355x 280.

## What would unlock the rest

Blocks: in-scope points held at G5 by the blocker. Alone: points that would be scored if only it were fixed.

| Blocker | Blocks | Alone |
|---|---|---|
| field_not_modelled:max_cudagraph_capture_size | 996 | 28 |
| field_not_modelled:enable_expert_parallel | 422 | 12 |
| value_not_recorded | 35 | 10 |
| blis_refused:scenario | 10 | 10 |
| value_not_recorded:api_413 | 1 | 1 |
| field_not_modelled:stream_interval | 771 | 0 |
| field_not_modelled:kv_cache_dtype | 752 | 0 |
| field_not_modelled:language_model_only | 607 | 0 |
| not_in_catalog:eagle3 | 296 | 0 |
| field_not_modelled:api_server_count | 131 | 0 |
| field_not_modelled:quantization | 71 | 0 |
| field_not_modelled:linear_backend | 67 | 0 |
| field_not_modelled:moe_backend | 56 | 0 |
| field_not_in_release:env.VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8 | 37 | 0 |
| field_not_in_release:env.VLLM_MXFP4_USE_MARLIN | 35 | 0 |
| value_not_recorded:no_recipe_fingerprint | 25 | 0 |
| value_conflict:model: the log serves /scratch/models/DeepSeek-V4-Pro-NVFP4, the recipe deepseek-ai/DeepSeek-V4-Pro | 23 | 0 |
| field_not_modelled:enable_chunked_prefill | 20 | 0 |
| field_not_modelled:speculative_config.rejection_sample_method | 12 | 0 |
| field_not_in_release:env.PYTHONNOUSERSITE | 7 | 0 |
| field_not_modelled:cpu_offload_gb | 7 | 0 |
| field_not_modelled:default_chat_template_kwargs.thinking_mode | 7 | 0 |
| value_not_recorded:kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use | 7 | 0 |
| field_not_modelled:dcp_comm_backend | 5 | 0 |
| field_not_modelled:decode_context_parallel_size | 5 | 0 |
| field_not_modelled:prefix_match_unit | 5 | 0 |
| value_not_recorded:speculative_config.model | 5 | 0 |
| field_not_modelled:enable_eplb | 4 | 0 |
| field_not_in_release:env.MC_ENABLE_DEST_DEVICE_AFFINITY | 2 | 0 |
| field_not_in_release:env.MC_SLICE_SIZE | 2 | 0 |
| field_not_in_release:env.MC_WORKERS_PER_CTX | 2 | 0 |
| field_not_modelled:env.PYTHONHASHSEED | 2 | 0 |
| field_not_modelled:kv_transfer_config.kv_connector_extra_config.load_async | 2 | 0 |
| value_conflict:kv_transfer_config.engine_id | 1 | 0 |
| out of scope (AMD, TPU) | 546 | 546 |

## Why points are below G1 or at G5 (design §11.6)

| Entry | Blocks | Alone | Demotes |
|---|---|---|---|
| `not_in_catalog` | 538 | 82 | 0 |
| `field_not_modelled:max_cudagraph_capture_size` | 996 | 28 | 0 |
| `field_not_modelled:enable_expert_parallel` | 513 | 12 | 0 |
| `value_not_recorded` | 35 | 10 | 0 |
| `value_not_recorded:api_413` | 9 | 9 | 0 |
| `field_not_modelled:kv_cache_dtype` | 997 | 0 | 0 |
| `field_not_modelled:language_model_only` | 834 | 0 | 0 |
| `field_not_modelled:stream_interval` | 771 | 0 | 0 |
| `not_in_catalog:eagle3` | 419 | 0 | 0 |
| `field_not_modelled:moe_backend` | 226 | 0 | 0 |
| `field_not_modelled:api_server_count` | 171 | 0 | 0 |
| `field_not_modelled:quantization` | 127 | 0 | 0 |
| `field_not_modelled:linear_backend` | 90 | 0 | 0 |
| `field_not_modelled:mm_encoder_tp_mode` | 65 | 0 | 0 |
| `field_not_in_release:env.VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8` | 37 | 0 | 0 |
| `field_not_in_release:env.VLLM_MXFP4_USE_MARLIN` | 35 | 0 | 0 |
| `field_not_modelled:env.VLLM_USE_RUST_FRONTEND` | 28 | 0 | 0 |
| `value_not_recorded:no_recipe_fingerprint` | 25 | 0 | 0 |
| `value_conflict:model: the log serves /scratch/models/DeepSeek-V4-Pro-NVFP4, the recipe deepseek-ai/DeepSeek-V4-Pro` | 23 | 0 | 0 |
| `field_not_modelled:enable_chunked_prefill` | 20 | 0 | 0 |
| `field_not_modelled:speculative_config.rejection_sample_method` | 12 | 0 | 0 |
| `field_not_in_release:env.PYTHONNOUSERSITE` | 7 | 0 | 0 |
| `field_not_modelled:cpu_offload_gb` | 7 | 0 | 0 |
| `field_not_modelled:default_chat_template_kwargs.thinking_mode` | 7 | 0 | 0 |
| `value_not_recorded:kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use` | 7 | 0 | 0 |
| `field_not_modelled:dcp_comm_backend` | 5 | 0 | 0 |
| `field_not_modelled:decode_context_parallel_size` | 5 | 0 | 0 |
| `field_not_modelled:prefix_match_unit` | 5 | 0 | 0 |
| `value_not_recorded:speculative_config.model` | 5 | 0 | 0 |
| `field_not_modelled:enable_eplb` | 4 | 0 | 0 |
| `field_not_in_release:env.MC_ENABLE_DEST_DEVICE_AFFINITY` | 2 | 0 | 0 |
| `field_not_in_release:env.MC_SLICE_SIZE` | 2 | 0 | 0 |
| `field_not_in_release:env.MC_WORKERS_PER_CTX` | 2 | 0 | 0 |
| `field_not_modelled:env.PYTHONHASHSEED` | 2 | 0 | 0 |
| `field_not_modelled:kv_transfer_config.kv_connector_extra_config.load_async` | 2 | 0 | 0 |
| `value_conflict:kv_transfer_config.engine_id` | 1 | 0 | 0 |
| `client_difference:client_flags` | 0 | 0 | 41 |
| `client_difference:failed_requests` | 0 | 0 | 41 |
| `client_difference:send_gap` | 0 | 0 | 41 |
| `coefficient_method:cost-model-attention/attention_decode_floor_mla` | 0 | 0 | 41 |
| `coefficient_method:cost-model-host-overheads/host_admission_per_request` | 0 | 0 | 41 |
| `coefficient_method:cost-model-host-overheads/host_admission_per_token` | 0 | 0 | 41 |
| `coefficient_method:cost-model-host-overheads/host_completion` | 0 | 0 | 41 |
| `coefficient_method:cost-model-host-overheads/host_launch_eager_per_layer` | 0 | 0 | 41 |
| `coefficient_method:cost-model-host-overheads/host_launch_per_kernel` | 0 | 0 | 41 |
| `coefficient_method:cost-model-host-overheads/host_output_token` | 0 | 0 | 41 |
| `coefficient_method:cost-model-host-overheads/host_replay_graph_per_step` | 0 | 0 | 41 |
| `coefficient_method:cost-model-memory/activation_scratch_floor_bytes` | 0 | 0 | 41 |
| `coefficient_method:cost-model-memory/cudagraph_capture_bytes_full_and_piecewise` | 0 | 0 | 41 |
| `coefficient_method:cost-model-primitives/engine_workspace_bytes` | 0 | 0 | 41 |
| `coefficient_method:cost-model-primitives/hbm_derate` | 0 | 0 | 41 |
| `coefficient_range:unevaluated` | 0 | 0 | 41 |
| `estimated:gpu_memory_utilization` | 0 | 0 | 41 |
| `interim_status:host` | 0 | 0 | 41 |
| `interim_status:model` | 0 | 0 | 41 |
| `interim_status:model_tag` | 0 | 0 | 41 |
| `interim_status:port` | 0 | 0 | 41 |
| `interim_status:reasoning_parser` | 0 | 0 | 41 |
| `interim_status:tool_call_parser` | 0 | 0 | 41 |
| `interim_status:trust_remote_code` | 0 | 0 | 41 |
| `kernel_hash:unevaluated` | 0 | 0 | 41 |
| `other_release:engine release` | 0 | 0 | 41 |
| `ported_functions_unpublished:engine release` | 0 | 0 | 41 |
| `resolved_differs:unevaluated` | 0 | 0 | 41 |
| `value_class:unevaluated` | 0 | 0 | 41 |
| `interim_status:served_model_name` | 0 | 0 | 31 |
| `client_difference:sent_prompt_lengths` | 0 | 0 | 30 |
| `coefficient_method:cost-model-memory/activation_buffer_count_moe_8rank` | 0 | 0 | 23 |
| `coefficient_method:cost-model-primitives/nccl_communicator_bytes_8rank` | 0 | 0 | 23 |
| `later_record:cluster.gpus_per_node` | 0 | 0 | 21 |
| `coefficient_method:cost-model-memory/activation_buffer_count_moe_4rank` | 0 | 0 | 18 |
| `coefficient_method:cost-model-primitives/nccl_communicator_bytes_4rank` | 0 | 0 | 18 |
