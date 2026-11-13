# Scored run (in-sample)

IN-SAMPLE: the points are the ones the model was calibrated on or tuned against; there is no anchor list yet, so no point is held out. These figures say how well the simulator reproduces data it has seen, not how well it predicts new data.

**Coverage counts include every point, the test split too, by design. Accuracy figures are over train and validation points only, with N stated.** 446 of the points are test or prospective and 275 of them are scored; those 275 are left out of every accuracy figure, so none can be derived by subtraction (docs/m2/evaluation-protocol.md section 6).

- harness commit `0e9627e219c207593de5bc55d997cf3dca707d64`
- units sha256 `d89f860a46c0470a22543dc7fb77b8d1b10e508ce4f5ef5073e96f359f08597e` (1740 units)
- pull manifest sha256 `c8f2ea928b0d4582afdc3fbf11ef9d6847a359791a520f497ee146e806a96166`
- point set sha256 `6818482f91e308ee2b6f844d347de68fef6e90cbc27c22b41d21643d580e5c60` (1734 points)

Simulator `a8bc3085a7c91c50a1d92862943a695c04adfe11`, engine {'kind': 'vllm', 'version': '0.32.0'}, fields sha256 `62743b57746f8376b291fdb853eb0eb19edacc5d717e1e7107d6e0f3ed41348d`.

## Headline (G1 to G4)

| Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % | Noise floor % |
|---|---|---|---|---|---|
| 520 | 27.4 (n=520) | 17.6 (n=353) | 19.7 (n=520) | 15.8 (n=353) | 1.6 (fallback; none measured per point) |

## By grade

**All points**

| Grade | Points | Share of all | Share of graded | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|---|---|
| G1 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G2 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G3 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G4 | 795 | 45.8% | 100.0% | 27.4 (n=520) | 17.6 (n=353) | 19.7 (n=520) | 15.8 (n=353) |
| G5 | 836 | 48.2% | - | - | - | - | - |
| failed | 103 | | | | | | |

**All scored points: each grade on its own, by serving (aggregated or disaggregated)**

| Serving | Grade | Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|---|
| aggregated | G1 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| aggregated | G2 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| aggregated | G3 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| aggregated | G4 | 520 | 27.4 (n=520) | 17.6 (n=353) | 19.7 (n=520) | 15.8 (n=353) |

## Development split

Per-split figures use the DEVELOPMENT split of docs/m2/evaluation-protocol.md, not the ledger's held-out: its test set is 'development split, not the ledger's held-out'.

Assignment: sha256 of the salt `blis-dev-split-2` and the series, mod 100; train below 60, validation below 80, test above; a point measured after 2026-11-09 is prospective (test).

| Split | Points | In scope | Scored | Series | Grades | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % | Ranking (groups; Spearman, top-1, regret) |
|---|---|---|---|---|---|---|---|---|---|---|
| train | 956 | 626 | 367 | 33 | G4 367, G5 535, failed 54 | 27.8 (n=367) | 15.9 (n=274) | 19.3 (n=367) | 15.9 (n=274) | 17; 0.97, 0.71, 0.05 |
| validation | 332 | 220 | 153 | 9 | G4 153, G5 179 | 26.4 (n=153) | 23.2 (n=115) | 20.7 (n=153) | 14.4 (n=115) | 7; too few groups, too few groups, too few groups |
| test | 446 | | | | withheld: evaluate with `--evaluate-test`, which logs the evaluation | | | | | |
| prospective | 0 | | | | withheld: evaluate with `--evaluate-test`, which logs the evaluation | | | | | |
| unassigned | 0 | 0 | 0 | 0 |  | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) | 0; too few groups, too few groups, too few groups |

## Coverage

Counts of every point, test included, by design.

| Set | Points | Scored | Not scored | Failed | Share scored |
|---|---|---|---|---|---|
| all points | 1734 | 795 | 836 | 103 | 45.8% |
| in scope | 1188 | 795 | 290 | 103 | 66.9% |
| out of scope (AMD, TPU) | 546 | 0 | 546 | 0 | 0.0% |

Out-of-scope points by chip: mi300x 95, mi325x 171, mi355x 280.

## What would unlock the rest

Blocks: in-scope points held at G5 by the blocker. Alone: points that would be scored if only it were fixed.

| Blocker | Blocks | Alone |
|---|---|---|
| blis_refused:scenario | 103 | 103 |
| field_not_modelled:linear_backend | 67 | 67 |
| value_not_recorded:workload_category_not_stated | 51 | 38 |
| field_not_in_release:env.VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8 | 37 | 37 |
| field_not_in_release:env.VLLM_MXFP4_USE_MARLIN | 35 | 35 |
| field_not_modelled:moe_backend | 56 | 25 |
| value_not_recorded | 35 | 10 |
| value_conflict:model: the log serves /scratch/models/DeepSeek-V4-Pro-NVFP4, the recipe deepseek-ai/DeepSeek-V4-Pro | 23 | 9 |
| value_not_recorded:api_413 | 1 | 1 |
| value_not_recorded:no_recipe_fingerprint | 25 | 0 |
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
| `not_in_catalog` | 538 | 326 | 0 |
| `field_not_modelled:linear_backend` | 90 | 67 | 0 |
| `value_not_recorded:workload_category_not_stated` | 51 | 38 | 0 |
| `field_not_in_release:env.VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8` | 37 | 37 | 0 |
| `field_not_in_release:env.VLLM_MXFP4_USE_MARLIN` | 35 | 35 | 0 |
| `field_not_modelled:moe_backend` | 226 | 25 | 0 |
| `value_not_recorded` | 35 | 10 | 0 |
| `value_conflict:model: the log serves /scratch/models/DeepSeek-V4-Pro-NVFP4, the recipe deepseek-ai/DeepSeek-V4-Pro` | 23 | 9 | 0 |
| `value_not_recorded:api_413` | 9 | 9 | 0 |
| `field_not_modelled:mm_encoder_tp_mode` | 65 | 0 | 0 |
| `value_not_recorded:no_recipe_fingerprint` | 25 | 0 | 0 |
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
| `client_difference:client_flags` | 0 | 0 | 795 |
| `client_difference:failed_requests` | 0 | 0 | 795 |
| `coefficient_method:cost-model-attention/attention_decode_floor_mla` | 0 | 0 | 795 |
| `coefficient_method:cost-model-host-overheads/host_admission_per_request` | 0 | 0 | 795 |
| `coefficient_method:cost-model-host-overheads/host_admission_per_token` | 0 | 0 | 795 |
| `coefficient_method:cost-model-host-overheads/host_completion` | 0 | 0 | 795 |
| `coefficient_method:cost-model-host-overheads/host_launch_eager_per_layer` | 0 | 0 | 795 |
| `coefficient_method:cost-model-host-overheads/host_launch_per_kernel` | 0 | 0 | 795 |
| `coefficient_method:cost-model-host-overheads/host_output_token` | 0 | 0 | 795 |
| `coefficient_method:cost-model-host-overheads/host_replay_graph_per_step` | 0 | 0 | 795 |
| `coefficient_method:cost-model-memory/activation_scratch_floor_bytes` | 0 | 0 | 795 |
| `coefficient_method:cost-model-primitives/engine_workspace_bytes` | 0 | 0 | 795 |
| `coefficient_method:cost-model-primitives/hbm_derate` | 0 | 0 | 795 |
| `interim_status:model` | 0 | 0 | 795 |
| `interim_status:model_tag` | 0 | 0 | 795 |
| `interim_status:port` | 0 | 0 | 795 |
| `interim_status:trust_remote_code` | 0 | 0 | 795 |
| `unevaluated:coefficient_range` | 0 | 0 | 795 |
| `unevaluated:kernel_hash` | 0 | 0 | 795 |
| `coefficient_method:cost-model-memory/cudagraph_capture_bytes_full_and_piecewise` | 0 | 0 | 742 |
| `value_class:max_num_batched_tokens` | 0 | 0 | 732 |
| `value_class:block_size` | 0 | 0 | 672 |
| `later_record:cluster.gpus_per_node` | 0 | 0 | 627 |
| `client_difference:sent_prompt_lengths` | 0 | 0 | 599 |
| `nightly_or_custom:engine build` | 0 | 0 | 575 |
| `value_class:tensor_parallel_size` | 0 | 0 | 460 |
| `value_class:max_model_len` | 0 | 0 | 369 |
| `coefficient_method:cost-model-memory/activation_buffer_count_moe_8rank` | 0 | 0 | 351 |
| `coefficient_method:cost-model-primitives/nccl_communicator_bytes_8rank` | 0 | 0 | 351 |
| `interim_status:host` | 0 | 0 | 339 |
| `estimated:speculative_config.acceptance_length` | 0 | 0 | 286 |
| `interim_status:speculative_config.attention_backend` | 0 | 0 | 269 |
| `value_class:speculative_config.model` | 0 | 0 | 269 |
| `interim_status:served_model_name` | 0 | 0 | 266 |
| `coefficient_method:cost-model-memory/activation_buffer_count_moe_4rank` | 0 | 0 | 257 |
| `coefficient_method:cost-model-primitives/nccl_communicator_bytes_4rank` | 0 | 0 | 257 |
| `coefficient_method:cost-model-primitives/host_gather_rate_uva` | 0 | 0 | 229 |
| `other_release:engine release` | 0 | 0 | 220 |
| `ported_functions_unpublished:engine release` | 0 | 0 | 220 |
| `coefficient_method:cost-model-primitives/nccl_communicator_bytes_2rank` | 0 | 0 | 167 |
| `coefficient_method:cost-model-primitives/gemm_eps_max_w8a16_mxfp8` | 0 | 0 | 154 |
| `coefficient_method:cost-model-primitives/gemm_m_half_w8a16_mxfp8` | 0 | 0 | 154 |
| `interim_status:reasoning_parser` | 0 | 0 | 127 |
| `interim_status:tool_call_parser` | 0 | 0 | 127 |
| `coefficient_method:cost-model-memory/activation_buffer_count_moe_2rank` | 0 | 0 | 109 |
| `coefficient_method:cost-model-memory/activation_buffer_count_moe_1rank` | 0 | 0 | 78 |
| `interim_status:enable_auto_tool_choice` | 0 | 0 | 65 |
| `estimated:api_server_count` | 0 | 0 | 58 |
| `execution_mode:data-parallel balancer` | 0 | 0 | 58 |
| `coefficient_method:cost-model-memory/cudagraph_capture_bytes_full_decode_only` | 0 | 0 | 53 |
| `interim_status:enable_flashinfer_autotune` | 0 | 0 | 53 |
| `interim_status:tokenizer_mode` | 0 | 0 | 53 |
| `value_class:speculative_config.num_speculative_tokens` | 0 | 0 | 24 |
| `client_difference:client_saturation` | 0 | 0 | 5 |
