# Scored run (in-sample)

IN-SAMPLE: the points are the ones the model was calibrated on or tuned against; there is no anchor list yet, so no point is held out. These figures say how well the simulator reproduces data it has seen, not how well it predicts new data.

**Coverage counts include every point, the test split too, by design. Accuracy figures are over train and validation points only, with N stated.** 446 of the points are test or prospective and 89 of them are scored; those 89 are left out of every accuracy figure, so none can be derived by subtraction (docs/m2/evaluation-protocol.md section 6).

- harness commit `9a8b45f55c103044ba6609f7fcef1a6f94826353`
- units sha256 `d89f860a46c0470a22543dc7fb77b8d1b10e508ce4f5ef5073e96f359f08597e` (1740 units)
- pull manifest sha256 `c8f2ea928b0d4582afdc3fbf11ef9d6847a359791a520f497ee146e806a96166`
- point set sha256 `6818482f91e308ee2b6f844d347de68fef6e90cbc27c22b41d21643d580e5c60` (1734 points)

Simulator `ece61af0eccb863ba527d9e1a6dd2ffc97d0c5cf`, engine {'kind': 'vllm', 'version': '0.32.0'}, fields sha256 `9a3a88857a9462caf7b09433cfb53ac377d042aea10e7da2af3a8f9fd1ecccaa`.

## Headline (G1 to G4)

| Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % | Noise floor % |
|---|---|---|---|---|---|
| 441 | 32.6 (n=441) | 18.4 (n=325) | 17.9 (n=441) | 13.1 (n=325) | 1.6 (fallback; none measured per point) |

## By grade

**All points**

| Grade | Points | Share of all | Share of graded | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|---|---|
| G1 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G2 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G3 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G4 | 530 | 30.6% | 100.0% | 32.6 (n=441) | 18.4 (n=325) | 17.9 (n=441) | 13.1 (n=325) |
| G5 | 798 | 46.0% | - | - | - | - | - |
| failed | 406 | | | | | | |

**All scored points: each grade on its own, by serving (aggregated or disaggregated)**

| Serving | Grade | Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|---|
| aggregated | G1 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| aggregated | G2 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| aggregated | G3 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| aggregated | G4 | 441 | 32.6 (n=441) | 18.4 (n=325) | 17.9 (n=441) | 13.1 (n=325) |

## Development split

Per-split figures use the DEVELOPMENT split of docs/m2/evaluation-protocol.md, not the ledger's held-out: its test set is 'development split, not the ledger's held-out'.

Assignment: sha256 of the salt `blis-dev-split-2` and the series, mod 100; train below 60, validation below 80, test above; a point measured after 2026-11-09 is prospective (test).

| Split | Points | In scope | Scored | Series | Grades | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % | Ranking (groups; Spearman, top-1, regret) |
|---|---|---|---|---|---|---|---|---|---|---|
| train | 956 | 626 | 366 | 33 | G4 366, G5 514, failed 76 | 34.6 (n=366) | 18.5 (n=266) | 16.8 (n=366) | 12.9 (n=266) | 19; 0.98, 0.84, 0.03 |
| validation | 332 | 220 | 75 | 9 | G4 75, G5 172, failed 85 | 22.7 (n=75) | 17.9 (n=59) | 23.3 (n=75) | 14.1 (n=59) | 3; too few groups, too few groups, too few groups |
| test | 446 | | | | withheld: evaluate with `--evaluate-test`, which logs the evaluation | | | | | |
| prospective | 0 | | | | withheld: evaluate with `--evaluate-test`, which logs the evaluation | | | | | |
| unassigned | 0 | 0 | 0 | 0 |  | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) | 0; too few groups, too few groups, too few groups |

## Coverage

Counts of every point, test included, by design.

| Set | Points | Scored | Not scored | Failed | Share scored |
|---|---|---|---|---|---|
| all points | 1734 | 530 | 798 | 406 | 30.6% |
| in scope | 1188 | 530 | 252 | 406 | 44.6% |
| out of scope (AMD, TPU) | 546 | 0 | 546 | 0 | 0.0% |

Out-of-scope points by chip: mi300x 95, mi325x 171, mi355x 280.

## What would unlock the rest

Blocks: in-scope points held at G5 by the blocker. Alone: points that would be scored if only it were fixed.

| Blocker | Blocks | Alone |
|---|---|---|
| blis_refused:scenario | 406 | 406 |
| field_not_modelled:linear_backend | 67 | 67 |
| field_not_modelled:moe_backend | 56 | 38 |
| field_not_in_release:env.VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8 | 37 | 37 |
| field_not_in_release:env.VLLM_MXFP4_USE_MARLIN | 35 | 35 |
| value_not_recorded | 35 | 10 |
| value_conflict:model: the log serves /scratch/models/DeepSeek-V4-Pro-NVFP4, the recipe deepseek-ai/DeepSeek-V4-Pro | 23 | 9 |
| value_not_recorded:api_413 | 1 | 1 |
| value_not_recorded:no_recipe_fingerprint | 25 | 0 |
| field_not_modelled:speculative_config.rejection_sample_method | 12 | 0 |
| field_not_modelled:cpu_offload_gb | 7 | 0 |
| field_not_modelled:default_chat_template_kwargs.thinking_mode | 7 | 0 |
| value_not_recorded:kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use | 7 | 0 |
| field_not_modelled:dcp_comm_backend | 5 | 0 |
| field_not_modelled:decode_context_parallel_size | 5 | 0 |
| field_not_modelled:prefix_match_unit | 5 | 0 |
| value_not_recorded:speculative_config.model | 5 | 0 |
| field_not_modelled:enable_eplb | 4 | 0 |
| field_not_modelled:kv_transfer_config.kv_connector_extra_config.load_async | 2 | 0 |
| value_conflict:kv_transfer_config.engine_id | 1 | 0 |
| out of scope (AMD, TPU) | 546 | 546 |

## Why points are below G1 or at G5 (design §11.6)

| Entry | Blocks | Alone | Demotes |
|---|---|---|---|
| `not_in_catalog` | 538 | 298 | 0 |
| `field_not_modelled:linear_backend` | 90 | 67 | 0 |
| `field_not_modelled:moe_backend` | 226 | 38 | 0 |
| `field_not_in_release:env.VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8` | 37 | 37 | 0 |
| `field_not_in_release:env.VLLM_MXFP4_USE_MARLIN` | 35 | 35 | 0 |
| `value_not_recorded` | 35 | 10 | 0 |
| `value_conflict:model: the log serves /scratch/models/DeepSeek-V4-Pro-NVFP4, the recipe deepseek-ai/DeepSeek-V4-Pro` | 23 | 9 | 0 |
| `value_not_recorded:api_413` | 9 | 9 | 0 |
| `field_not_modelled:mm_encoder_tp_mode` | 65 | 0 | 0 |
| `field_not_modelled:env.VLLM_USE_RUST_FRONTEND` | 28 | 0 | 0 |
| `value_not_recorded:no_recipe_fingerprint` | 25 | 0 | 0 |
| `field_not_modelled:speculative_config.rejection_sample_method` | 12 | 0 | 0 |
| `field_not_modelled:cpu_offload_gb` | 7 | 0 | 0 |
| `field_not_modelled:default_chat_template_kwargs.thinking_mode` | 7 | 0 | 0 |
| `value_not_recorded:kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use` | 7 | 0 | 0 |
| `field_not_modelled:dcp_comm_backend` | 5 | 0 | 0 |
| `field_not_modelled:decode_context_parallel_size` | 5 | 0 | 0 |
| `field_not_modelled:prefix_match_unit` | 5 | 0 | 0 |
| `value_not_recorded:speculative_config.model` | 5 | 0 | 0 |
| `field_not_modelled:enable_eplb` | 4 | 0 | 0 |
| `field_not_modelled:kv_transfer_config.kv_connector_extra_config.load_async` | 2 | 0 | 0 |
| `value_conflict:kv_transfer_config.engine_id` | 1 | 0 | 0 |
| `client_difference:client_flags` | 0 | 0 | 530 |
| `client_difference:failed_requests` | 0 | 0 | 530 |
| `client_difference:send_gap` | 0 | 0 | 530 |
| `coefficient_method:cost-model-attention/attention_decode_floor_mla` | 0 | 0 | 530 |
| `coefficient_method:cost-model-host-overheads/host_admission_per_request` | 0 | 0 | 530 |
| `coefficient_method:cost-model-host-overheads/host_admission_per_token` | 0 | 0 | 530 |
| `coefficient_method:cost-model-host-overheads/host_completion` | 0 | 0 | 530 |
| `coefficient_method:cost-model-host-overheads/host_launch_eager_per_layer` | 0 | 0 | 530 |
| `coefficient_method:cost-model-host-overheads/host_launch_per_kernel` | 0 | 0 | 530 |
| `coefficient_method:cost-model-host-overheads/host_output_token` | 0 | 0 | 530 |
| `coefficient_method:cost-model-host-overheads/host_replay_graph_per_step` | 0 | 0 | 530 |
| `coefficient_method:cost-model-memory/activation_scratch_floor_bytes` | 0 | 0 | 530 |
| `coefficient_method:cost-model-memory/cudagraph_capture_bytes_full_and_piecewise` | 0 | 0 | 530 |
| `coefficient_method:cost-model-primitives/engine_workspace_bytes` | 0 | 0 | 530 |
| `coefficient_method:cost-model-primitives/hbm_derate` | 0 | 0 | 530 |
| `interim_status:model` | 0 | 0 | 530 |
| `interim_status:model_tag` | 0 | 0 | 530 |
| `interim_status:port` | 0 | 0 | 530 |
| `kernel_hash:unevaluated` | 0 | 0 | 530 |
| `interim_status:trust_remote_code` | 0 | 0 | 502 |
| `value_class:max_num_batched_tokens` | 0 | 0 | 467 |
| `estimated:gpu_memory_utilization` | 0 | 0 | 455 |
| `later_record:cluster.gpus_per_node` | 0 | 0 | 429 |
| `value_class:block_size` | 0 | 0 | 428 |
| `client_difference:sent_prompt_lengths` | 0 | 0 | 399 |
| `coefficient_range:unevaluated` | 0 | 0 | 395 |
| `interim_status:host` | 0 | 0 | 319 |
| `value_class:tensor_parallel_size` | 0 | 0 | 295 |
| `other_release:engine release` | 0 | 0 | 292 |
| `ported_functions_unpublished:engine release` | 0 | 0 | 292 |
| `coefficient_method:cost-model-memory/activation_buffer_count_moe_8rank` | 0 | 0 | 266 |
| `coefficient_method:cost-model-primitives/nccl_communicator_bytes_8rank` | 0 | 0 | 266 |
| `value_class:max_model_len` | 0 | 0 | 253 |
| `nightly_or_custom:engine build` | 0 | 0 | 238 |
| `coefficient_method:cost-model-primitives/host_gather_rate_uva` | 0 | 0 | 224 |
| `interim_status:reasoning_parser` | 0 | 0 | 220 |
| `interim_status:tool_call_parser` | 0 | 0 | 220 |
| `coefficient_method:cost-model-memory/activation_buffer_count_moe_4rank` | 0 | 0 | 170 |
| `coefficient_method:cost-model-primitives/nccl_communicator_bytes_4rank` | 0 | 0 | 170 |
| `interim_status:enable_auto_tool_choice` | 0 | 0 | 158 |
| `interim_status:served_model_name` | 0 | 0 | 150 |
| `interim_status:tokenizer_mode` | 0 | 0 | 146 |
| `coefficient_method:cost-model-attention/attention_prefill_floor_trtllm_gen_kv_fp8` | 0 | 0 | 135 |
| `coefficient_method:cost-model-attention/attention_prefill_work_scale_trtllm_gen_kv_fp8` | 0 | 0 | 135 |
| `coefficient_range:cost-model-attention/attention_prefill_floor_trtllm_gen_kv_fp8` | 0 | 0 | 135 |
| `coefficient_range:cost-model-attention/attention_prefill_work_scale_trtllm_gen_kv_fp8` | 0 | 0 | 135 |
| `coefficient_method:cost-model-primitives/gemm_eps_max_w8a16_mxfp8` | 0 | 0 | 103 |
| `coefficient_method:cost-model-primitives/gemm_m_half_w8a16_mxfp8` | 0 | 0 | 103 |
| `coefficient_method:cost-model-primitives/nccl_communicator_bytes_2rank` | 0 | 0 | 91 |
| `estimated:speculative_config.acceptance_length` | 0 | 0 | 80 |
| `estimated:workload.thinking_mode` | 0 | 0 | 80 |
| `interim_status:enable_flashinfer_autotune` | 0 | 0 | 71 |
| `coefficient_method:cost-model-memory/activation_buffer_count_moe_1rank` | 0 | 0 | 65 |
| `resolved_differs:all_reduce_backend` | 0 | 0 | 65 |
| `estimated:api_server_count` | 0 | 0 | 62 |
| `execution_mode:data-parallel balancer` | 0 | 0 | 62 |
| `coefficient_method:cost-model-memory/activation_buffer_count_moe_2rank` | 0 | 0 | 29 |
