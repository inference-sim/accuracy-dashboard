# Scored run (in-sample)

IN-SAMPLE: the points are the ones the model was calibrated on or tuned against; there is no anchor list yet, so no point is held out. These figures say how well the simulator reproduces data it has seen, not how well it predicts new data.

- harness commit `a2ddd723d5c2f75b8f9d5e0b31e7923ed91ff409`
- units sha256 `d89f860a46c0470a22543dc7fb77b8d1b10e508ce4f5ef5073e96f359f08597e` (1740 units)
- pull manifest sha256 `6b37908b08dfbb51af35977dbbd0afd2f764ea564443022a07858b186630a816`
- point set sha256 `6818482f91e308ee2b6f844d347de68fef6e90cbc27c22b41d21643d580e5c60` (1734 points)

Simulator `v0.16.0`, engine {'kind': 'vllm', 'version': '0.32.0'}, fields sha256 `d32342c4f9ae5c578ba578fd5e6575aa8db8bce099e0708480d55f7e8de5a6fc`.

## Headline (G1 to G4)

| Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % | Noise floor % |
|---|---|---|---|---|---|
| 20 | 32.3 (n=20) | 23.8 (n=16) | 12.9 (n=20) | 9.5 (n=16) | 1.6 (fallback; none measured per point) |

## By grade

**All points**

| Grade | Points | Share of all | Share of graded | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|---|---|
| G1 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G2 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G3 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G4 | 20 | 1.2% | 100.0% | 32.3 (n=20) | 23.8 (n=16) | 12.9 (n=20) | 9.5 (n=16) |
| G5 | 1714 | 98.8% | - | - | - | - | - |

## Coverage

| Set | Points | Scored | Not scored | Failed | Share scored |
|---|---|---|---|---|---|
| all points | 1734 | 20 | 1714 | 0 | 1.2% |
| in scope | 1188 | 20 | 1168 | 0 | 1.7% |
| out of scope (AMD, TPU) | 546 | 0 | 546 | 0 | 0.0% |

Out-of-scope points by chip: mi300x 95, mi325x 171, mi355x 280.

## What would unlock the rest

Blocks: in-scope points held at G5 by the blocker. Alone: points that would be scored if only it were fixed.

| Blocker | Blocks | Alone |
|---|---|---|
| value_not_recorded:cluster.gpus_per_node | 858 | 31 |
| value_not_recorded | 35 | 10 |
| value_not_recorded:api_413 | 1 | 1 |
| field_not_modelled:max_cudagraph_capture_size | 996 | 0 |
| field_not_modelled:stream_interval | 771 | 0 |
| field_not_modelled:kv_cache_dtype | 752 | 0 |
| field_not_modelled:language_model_only | 607 | 0 |
| field_not_modelled:enable_expert_parallel | 422 | 0 |
| not_in_catalog:eagle3 | 296 | 0 |
| field_not_modelled:api_server_count | 131 | 0 |
| field_not_modelled:quantization | 71 | 0 |
| field_not_modelled:linear_backend | 67 | 0 |
| field_not_modelled:moe_backend | 56 | 0 |
| field_not_in_release:env.VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8 | 37 | 0 |
| field_not_in_release:env.VLLM_MXFP4_USE_MARLIN | 35 | 0 |
| value_not_recorded:no_recipe_fingerprint | 25 | 0 |
| not_in_catalog | 23 | 0 |
| field_not_modelled:enable_chunked_prefill | 20 | 0 |
| field_not_modelled:speculative_config.rejection_sample_method | 12 | 0 |
| field_not_in_release:env.PYTHONNOUSERSITE | 7 | 0 |
| field_not_modelled:cpu_offload_gb | 7 | 0 |
| field_not_modelled:default_chat_template_kwargs.thinking_mode | 7 | 0 |
| value_not_recorded:kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use | 7 | 0 |
| field_not_modelled:dcp_comm_backend | 5 | 0 |
| field_not_modelled:decode_context_parallel_size | 5 | 0 |
| field_not_modelled:prefix_match_unit | 5 | 0 |
| not_in_catalog:dspark | 5 | 0 |
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
| `not_in_catalog` | 561 | 82 | 0 |
| `value_not_recorded:cluster.gpus_per_node` | 858 | 31 | 0 |
| `value_not_recorded` | 35 | 10 | 0 |
| `value_not_recorded:api_413` | 9 | 9 | 0 |
| `field_not_modelled:kv_cache_dtype` | 997 | 0 | 0 |
| `field_not_modelled:max_cudagraph_capture_size` | 996 | 0 | 0 |
| `field_not_modelled:language_model_only` | 834 | 0 | 0 |
| `field_not_modelled:stream_interval` | 771 | 0 | 0 |
| `field_not_modelled:enable_expert_parallel` | 513 | 0 | 0 |
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
| `field_not_modelled:enable_chunked_prefill` | 20 | 0 | 0 |
| `field_not_modelled:speculative_config.rejection_sample_method` | 12 | 0 | 0 |
| `field_not_in_release:env.PYTHONNOUSERSITE` | 7 | 0 | 0 |
| `field_not_modelled:cpu_offload_gb` | 7 | 0 | 0 |
| `field_not_modelled:default_chat_template_kwargs.thinking_mode` | 7 | 0 | 0 |
| `value_not_recorded:kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use` | 7 | 0 | 0 |
| `field_not_modelled:dcp_comm_backend` | 5 | 0 | 0 |
| `field_not_modelled:decode_context_parallel_size` | 5 | 0 | 0 |
| `field_not_modelled:prefix_match_unit` | 5 | 0 | 0 |
| `not_in_catalog:dspark` | 5 | 0 | 0 |
| `field_not_modelled:enable_eplb` | 4 | 0 | 0 |
| `field_not_in_release:env.MC_ENABLE_DEST_DEVICE_AFFINITY` | 2 | 0 | 0 |
| `field_not_in_release:env.MC_SLICE_SIZE` | 2 | 0 | 0 |
| `field_not_in_release:env.MC_WORKERS_PER_CTX` | 2 | 0 | 0 |
| `field_not_modelled:env.PYTHONHASHSEED` | 2 | 0 | 0 |
| `field_not_modelled:kv_transfer_config.kv_connector_extra_config.load_async` | 2 | 0 | 0 |
| `value_conflict:kv_transfer_config.engine_id` | 1 | 0 | 0 |
| `client_difference:client_flags` | 0 | 0 | 20 |
| `client_difference:send_gap` | 0 | 0 | 20 |
| `client_difference:sent_prompt_lengths` | 0 | 0 | 20 |
| `coefficient_method:cost-model-attention/attention_decode_floor_mla` | 0 | 0 | 20 |
| `coefficient_method:cost-model-host-overheads/host_admission_per_request` | 0 | 0 | 20 |
| `coefficient_method:cost-model-host-overheads/host_admission_per_token` | 0 | 0 | 20 |
| `coefficient_method:cost-model-host-overheads/host_completion` | 0 | 0 | 20 |
| `coefficient_method:cost-model-host-overheads/host_launch_eager_per_layer` | 0 | 0 | 20 |
| `coefficient_method:cost-model-host-overheads/host_launch_per_kernel` | 0 | 0 | 20 |
| `coefficient_method:cost-model-host-overheads/host_output_token` | 0 | 0 | 20 |
| `coefficient_method:cost-model-host-overheads/host_replay_graph_per_step` | 0 | 0 | 20 |
| `coefficient_method:cost-model-memory/activation_scratch_floor_bytes` | 0 | 0 | 20 |
| `coefficient_method:cost-model-memory/cudagraph_capture_bytes_full_and_piecewise` | 0 | 0 | 20 |
| `coefficient_method:cost-model-primitives/engine_workspace_bytes` | 0 | 0 | 20 |
| `coefficient_method:cost-model-primitives/hbm_derate` | 0 | 0 | 20 |
| `coefficient_range:unevaluated` | 0 | 0 | 20 |
| `estimated:gpu_memory_utilization` | 0 | 0 | 20 |
| `interim_status:host` | 0 | 0 | 20 |
| `interim_status:model` | 0 | 0 | 20 |
| `interim_status:model_tag` | 0 | 0 | 20 |
| `interim_status:port` | 0 | 0 | 20 |
| `interim_status:reasoning_parser` | 0 | 0 | 20 |
| `interim_status:served_model_name` | 0 | 0 | 20 |
| `interim_status:tool_call_parser` | 0 | 0 | 20 |
| `interim_status:trust_remote_code` | 0 | 0 | 20 |
| `kernel_hash:unevaluated` | 0 | 0 | 20 |
| `other_release:engine release` | 0 | 0 | 20 |
| `ported_functions_unpublished:engine release` | 0 | 0 | 20 |
| `resolved_differs:unevaluated` | 0 | 0 | 20 |
| `value_class:unevaluated` | 0 | 0 | 20 |
| `coefficient_method:cost-model-memory/activation_buffer_count_moe_4rank` | 0 | 0 | 10 |
| `coefficient_method:cost-model-memory/activation_buffer_count_moe_8rank` | 0 | 0 | 10 |
| `coefficient_method:cost-model-primitives/nccl_communicator_bytes_4rank` | 0 | 0 | 10 |
| `coefficient_method:cost-model-primitives/nccl_communicator_bytes_8rank` | 0 | 0 | 10 |
