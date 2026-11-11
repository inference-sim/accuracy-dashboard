# Before and after (in-sample)

IN-SAMPLE: the points are the ones the model was calibrated on or tuned against; there is no anchor list yet, so no point is held out. These figures say how well the simulator reproduces data it has seen, not how well it predicts new data.

Both runs share one harness commit, one units file, one frozen pull and one point set:

- harness commit `10b2a36cb91d4c65dd9096d5f4689f3e80ec93b0`
- units sha256 `d89f860a46c0470a22543dc7fb77b8d1b10e508ce4f5ef5073e96f359f08597e` (1740 units)
- pull manifest sha256 `c8f2ea928b0d4582afdc3fbf11ef9d6847a359791a520f497ee146e806a96166`
- point set sha256 `6818482f91e308ee2b6f844d347de68fef6e90cbc27c22b41d21643d580e5c60` (1734 points)

Before: simulator `v0.16.0`, fields `d32342c4f9ae5c578ba578fd5e6575aa8db8bce099e0708480d55f7e8de5a6fc`.  
After: simulator `ece61af0eccb863ba527d9e1a6dd2ffc97d0c5cf`, fields `9a3a88857a9462caf7b09433cfb53ac377d042aea10e7da2af3a8f9fd1ecccaa`.

## Headline (G1 to G4, every graded point)

| Run | Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|
| before | 41 | 31.0 (n=41) | 18.6 (n=33) | 16.7 (n=41) | 10.9 (n=33) |
| after | 110 | 30.8 (n=110) | 17.4 (n=92) | 17.7 (n=110) | 15.3 (n=92) |

Noise floor 1.6 % (fallback; none measured per point).

## Accuracy apart from coverage

A coverage gain cannot hide an accuracy loss, so the points scored in both runs and the points scored in one only are separate rows.

| Set | Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|
| scored in both, before | 41 | 31.0 (n=41) | 18.6 (n=33) | 16.7 (n=41) | 10.9 (n=33) |
| scored in both, after | 41 | 30.4 (n=41) | 18.4 (n=33) | 15.2 (n=41) | 11.7 (n=33) |
| newly scored, after | 69 | 31.1 (n=69) | 16.9 (n=59) | 19.2 (n=69) | 17.3 (n=59) |
| newly refused, before | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |

Grade moves of the points scored in both: G4->G4 41.

## By grade

**Before**

| Grade | Points | Share of all | Share of graded | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|---|---|
| G1 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G2 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G3 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G4 | 41 | 2.4% | 100.0% | 31.0 (n=41) | 18.6 (n=33) | 16.7 (n=41) | 10.9 (n=33) |
| G5 | 1683 | 97.1% | - | - | - | - | - |
| failed | 10 | | | | | | |

**After**

| Grade | Points | Share of all | Share of graded | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|---|---|
| G1 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G2 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G3 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G4 | 110 | 6.3% | 100.0% | 30.8 (n=110) | 17.4 (n=92) | 17.7 (n=110) | 15.3 (n=92) |
| G5 | 833 | 48.0% | - | - | - | - | - |
| failed | 791 | | | | | | |

**Before: each grade on its own, by serving (aggregated or disaggregated)**

| Serving | Grade | Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|---|
| aggregated | G1 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| aggregated | G2 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| aggregated | G3 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| aggregated | G4 | 41 | 31.0 (n=41) | 18.6 (n=33) | 16.7 (n=41) | 10.9 (n=33) |

**After: each grade on its own, by serving (aggregated or disaggregated)**

| Serving | Grade | Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|---|
| aggregated | G1 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| aggregated | G2 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| aggregated | G3 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| aggregated | G4 | 110 | 30.8 (n=110) | 17.4 (n=92) | 17.7 (n=110) | 15.3 (n=92) |

## Development split, before

Per-split figures use the DEVELOPMENT split of docs/m2/evaluation-protocol.md, not the ledger's held-out: its test set is 'development split, not the ledger's held-out'.

Assignment: sha256 of the salt `blis-dev-split-1` and the series, mod 100; train below 60, validation below 80, test above; a point measured after 2026-11-09 is prospective (test).

| Split | Points | In scope | Scored | Series | Grades | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % | Ranking (groups; Spearman, top-1, regret) |
|---|---|---|---|---|---|---|---|---|---|---|
| train | 1120 | 792 | 26 | 72 | G4 26, G5 1084, failed 10 | 43.1 (n=26) | 24.0 (n=21) | 21.3 (n=26) | 8.6 (n=21) | 3; too few groups, too few groups, too few groups |
| validation | 282 | 196 | 15 | 21 | G4 15, G5 267 | 10.2 (n=15) | 9.1 (n=12) | 8.6 (n=15) | 14.9 (n=12) | 2; too few groups, too few groups, too few groups |
| test | 332 | | | | withheld: evaluate with `--evaluate-test`, which logs the evaluation | | | | | |
| prospective | 0 | | | | withheld: evaluate with `--evaluate-test`, which logs the evaluation | | | | | |
| unassigned | 0 | 0 | 0 | 0 |  | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) | 0; too few groups, too few groups, too few groups |

## Development split, after

Per-split figures use the DEVELOPMENT split of docs/m2/evaluation-protocol.md, not the ledger's held-out: its test set is 'development split, not the ledger's held-out'.

Assignment: sha256 of the salt `blis-dev-split-1` and the series, mod 100; train below 60, validation below 80, test above; a point measured after 2026-11-09 is prospective (test).

| Split | Points | In scope | Scored | Series | Grades | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % | Ranking (groups; Spearman, top-1, regret) |
|---|---|---|---|---|---|---|---|---|---|---|
| train | 1120 | 792 | 89 | 72 | G4 89, G5 508, failed 523 | 34.0 (n=89) | 19.6 (n=75) | 19.1 (n=89) | 15.1 (n=75) | 9; too few groups, too few groups, too few groups |
| validation | 282 | 196 | 15 | 21 | G4 15, G5 168, failed 99 | 10.2 (n=15) | 9.1 (n=12) | 8.6 (n=15) | 14.9 (n=12) | 2; too few groups, too few groups, too few groups |
| test | 332 | | | | withheld: evaluate with `--evaluate-test`, which logs the evaluation | | | | | |
| prospective | 0 | | | | withheld: evaluate with `--evaluate-test`, which logs the evaluation | | | | | |
| unassigned | 0 | 0 | 0 | 0 |  | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) | 0; too few groups, too few groups, too few groups |

## Coverage

| Set | Points | Scored | Not scored | Failed | Share scored |
|---|---|---|---|---|---|
| before all points | 1734 | 41 | 1683 | 10 | 2.4% |
| before in scope | 1188 | 41 | 1137 | 10 | 3.5% |
| before out of scope (AMD, TPU) | 546 | 0 | 546 | 0 | 0.0% |
| after all points | 1734 | 110 | 833 | 791 | 6.3% |
| after in scope | 1188 | 110 | 287 | 791 | 9.3% |
| after out of scope (AMD, TPU) | 546 | 0 | 546 | 0 | 0.0% |

Out-of-scope points by chip: mi300x 95, mi325x 171, mi355x 280.

## Coverage movement by reason

Blocks: points carrying the reason. Alone: points whose only reason it is.

**All points**

| Reason | Blocks before | after | change | Alone before | after | change |
|---|---|---|---|---|---|---|
| `blis_refused:scenario` | 10 | 791 | +781 | 10 | 791 | +781 |
| `field_not_in_release:env.MC_ENABLE_DEST_DEVICE_AFFINITY` | 2 | 0 | -2 | 0 | 0 | +0 |
| `field_not_in_release:env.MC_SLICE_SIZE` | 2 | 0 | -2 | 0 | 0 | +0 |
| `field_not_in_release:env.MC_WORKERS_PER_CTX` | 2 | 0 | -2 | 0 | 0 | +0 |
| `field_not_in_release:env.PYTHONNOUSERSITE` | 7 | 0 | -7 | 0 | 0 | +0 |
| `field_not_in_release:env.VLLM_MXFP4_USE_MARLIN` | 35 | 35 | +0 | 0 | 35 | +35 |
| `field_not_in_release:env.VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8` | 37 | 37 | +0 | 0 | 37 | +37 |
| `field_not_in_release:thinking` | 0 | 35 | +35 | 0 | 35 | +35 |
| `field_not_modelled:api_server_count` | 171 | 0 | -171 | 0 | 0 | +0 |
| `field_not_modelled:cpu_offload_gb` | 7 | 7 | +0 | 0 | 0 | +0 |
| `field_not_modelled:dcp_comm_backend` | 5 | 5 | +0 | 0 | 0 | +0 |
| `field_not_modelled:decode_context_parallel_size` | 5 | 5 | +0 | 0 | 0 | +0 |
| `field_not_modelled:default_chat_template_kwargs.thinking_mode` | 7 | 7 | +0 | 0 | 0 | +0 |
| `field_not_modelled:enable_chunked_prefill` | 20 | 0 | -20 | 0 | 0 | +0 |
| `field_not_modelled:enable_eplb` | 4 | 4 | +0 | 0 | 0 | +0 |
| `field_not_modelled:enable_expert_parallel` | 513 | 0 | -513 | 12 | 0 | -12 |
| `field_not_modelled:env.PYTHONHASHSEED` | 2 | 0 | -2 | 0 | 0 | +0 |
| `field_not_modelled:env.VLLM_USE_RUST_FRONTEND` | 28 | 28 | +0 | 0 | 0 | +0 |
| `field_not_modelled:kv_cache_dtype` | 997 | 0 | -997 | 0 | 0 | +0 |
| `field_not_modelled:kv_transfer_config.kv_connector_extra_config.load_async` | 2 | 2 | +0 | 0 | 0 | +0 |
| `field_not_modelled:language_model_only` | 834 | 0 | -834 | 0 | 0 | +0 |
| `field_not_modelled:linear_backend` | 90 | 90 | +0 | 0 | 67 | +67 |
| `field_not_modelled:max_cudagraph_capture_size` | 996 | 0 | -996 | 28 | 0 | -28 |
| `field_not_modelled:mm_encoder_tp_mode` | 65 | 65 | +0 | 0 | 0 | +0 |
| `field_not_modelled:moe_backend` | 226 | 226 | +0 | 0 | 38 | +38 |
| `field_not_modelled:prefix_match_unit` | 5 | 5 | +0 | 0 | 0 | +0 |
| `field_not_modelled:quantization` | 127 | 0 | -127 | 0 | 0 | +0 |
| `field_not_modelled:speculative_config.rejection_sample_method` | 12 | 12 | +0 | 0 | 0 | +0 |
| `field_not_modelled:stream_interval` | 771 | 0 | -771 | 0 | 0 | +0 |
| `not_in_catalog` | 538 | 538 | +0 | 82 | 298 | +216 |
| `not_in_catalog:eagle3` | 419 | 0 | -419 | 0 | 0 | +0 |
| `value_conflict:kv_transfer_config.engine_id` | 1 | 1 | +0 | 0 | 0 | +0 |
| `value_conflict:model: the log serves /scratch/models/DeepSeek-V4-Pro-NVFP4, the recipe deepseek-ai/DeepSeek-V4-Pro` | 23 | 23 | +0 | 0 | 9 | +9 |
| `value_not_recorded` | 35 | 35 | +0 | 10 | 10 | +0 |
| `value_not_recorded:api_413` | 9 | 9 | +0 | 9 | 9 | +0 |
| `value_not_recorded:kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use` | 7 | 7 | +0 | 0 | 0 | +0 |
| `value_not_recorded:no_recipe_fingerprint` | 25 | 25 | +0 | 0 | 0 | +0 |
| `value_not_recorded:speculative_config.model` | 5 | 5 | +0 | 0 | 0 | +0 |

**In scope**

| Reason | Blocks before | after | change | Alone before | after | change |
|---|---|---|---|---|---|---|
| `blis_refused:scenario` | 10 | 791 | +781 | 10 | 791 | +781 |
| `field_not_in_release:env.MC_ENABLE_DEST_DEVICE_AFFINITY` | 2 | 0 | -2 | 0 | 0 | +0 |
| `field_not_in_release:env.MC_SLICE_SIZE` | 2 | 0 | -2 | 0 | 0 | +0 |
| `field_not_in_release:env.MC_WORKERS_PER_CTX` | 2 | 0 | -2 | 0 | 0 | +0 |
| `field_not_in_release:env.PYTHONNOUSERSITE` | 7 | 0 | -7 | 0 | 0 | +0 |
| `field_not_in_release:env.VLLM_MXFP4_USE_MARLIN` | 35 | 35 | +0 | 0 | 35 | +35 |
| `field_not_in_release:env.VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8` | 37 | 37 | +0 | 0 | 37 | +37 |
| `field_not_in_release:thinking` | 0 | 35 | +35 | 0 | 35 | +35 |
| `field_not_modelled:api_server_count` | 131 | 0 | -131 | 0 | 0 | +0 |
| `field_not_modelled:cpu_offload_gb` | 7 | 7 | +0 | 0 | 0 | +0 |
| `field_not_modelled:dcp_comm_backend` | 5 | 5 | +0 | 0 | 0 | +0 |
| `field_not_modelled:decode_context_parallel_size` | 5 | 5 | +0 | 0 | 0 | +0 |
| `field_not_modelled:default_chat_template_kwargs.thinking_mode` | 7 | 7 | +0 | 0 | 0 | +0 |
| `field_not_modelled:enable_chunked_prefill` | 20 | 0 | -20 | 0 | 0 | +0 |
| `field_not_modelled:enable_eplb` | 4 | 4 | +0 | 0 | 0 | +0 |
| `field_not_modelled:enable_expert_parallel` | 422 | 0 | -422 | 12 | 0 | -12 |
| `field_not_modelled:env.PYTHONHASHSEED` | 2 | 0 | -2 | 0 | 0 | +0 |
| `field_not_modelled:kv_cache_dtype` | 752 | 0 | -752 | 0 | 0 | +0 |
| `field_not_modelled:kv_transfer_config.kv_connector_extra_config.load_async` | 2 | 2 | +0 | 0 | 0 | +0 |
| `field_not_modelled:language_model_only` | 607 | 0 | -607 | 0 | 0 | +0 |
| `field_not_modelled:linear_backend` | 67 | 67 | +0 | 0 | 67 | +67 |
| `field_not_modelled:max_cudagraph_capture_size` | 996 | 0 | -996 | 28 | 0 | -28 |
| `field_not_modelled:moe_backend` | 56 | 56 | +0 | 0 | 38 | +38 |
| `field_not_modelled:prefix_match_unit` | 5 | 5 | +0 | 0 | 0 | +0 |
| `field_not_modelled:quantization` | 71 | 0 | -71 | 0 | 0 | +0 |
| `field_not_modelled:speculative_config.rejection_sample_method` | 12 | 12 | +0 | 0 | 0 | +0 |
| `field_not_modelled:stream_interval` | 771 | 0 | -771 | 0 | 0 | +0 |
| `not_in_catalog:eagle3` | 296 | 0 | -296 | 0 | 0 | +0 |
| `value_conflict:kv_transfer_config.engine_id` | 1 | 1 | +0 | 0 | 0 | +0 |
| `value_conflict:model: the log serves /scratch/models/DeepSeek-V4-Pro-NVFP4, the recipe deepseek-ai/DeepSeek-V4-Pro` | 23 | 23 | +0 | 0 | 9 | +9 |
| `value_not_recorded` | 35 | 35 | +0 | 10 | 10 | +0 |
| `value_not_recorded:api_413` | 1 | 1 | +0 | 1 | 1 | +0 |
| `value_not_recorded:kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use` | 7 | 7 | +0 | 0 | 0 | +0 |
| `value_not_recorded:no_recipe_fingerprint` | 25 | 25 | +0 | 0 | 0 | +0 |
| `value_not_recorded:speculative_config.model` | 5 | 5 | +0 | 0 | 0 | +0 |

**Out of scope (AMD, TPU)**

| Reason | Blocks before | after | change | Alone before | after | change |
|---|---|---|---|---|---|---|
| `field_not_modelled:api_server_count` | 40 | 0 | -40 | 0 | 0 | +0 |
| `field_not_modelled:enable_expert_parallel` | 91 | 0 | -91 | 0 | 0 | +0 |
| `field_not_modelled:env.VLLM_USE_RUST_FRONTEND` | 28 | 28 | +0 | 0 | 0 | +0 |
| `field_not_modelled:kv_cache_dtype` | 245 | 0 | -245 | 0 | 0 | +0 |
| `field_not_modelled:language_model_only` | 227 | 0 | -227 | 0 | 0 | +0 |
| `field_not_modelled:linear_backend` | 23 | 23 | +0 | 0 | 0 | +0 |
| `field_not_modelled:mm_encoder_tp_mode` | 65 | 65 | +0 | 0 | 0 | +0 |
| `field_not_modelled:moe_backend` | 170 | 170 | +0 | 0 | 0 | +0 |
| `field_not_modelled:quantization` | 56 | 0 | -56 | 0 | 0 | +0 |
| `not_in_catalog` | 538 | 538 | +0 | 82 | 298 | +216 |
| `not_in_catalog:eagle3` | 123 | 0 | -123 | 0 | 0 | +0 |
| `value_not_recorded:api_413` | 8 | 8 | +0 | 8 | 8 | +0 |

## Attribution (points scored in both)

**By model**

| Value | Points | TTFT MAPE % before | after | TPOT MAPE % before | after |
|---|---|---|---|---|---|
| kimi-k2.5 | 41 | 31.0 | 32.7 | 16.7 | 13.5 |

**By hardware**

| Value | Points | TTFT MAPE % before | after | TPOT MAPE % before | after |
|---|---|---|---|---|---|
| b200 | 10 | 33.7 | 33.7 | 14.7 | 14.7 |
| b300 | 31 | 30.2 | 29.4 | 17.3 | 15.3 |

**By precision**

| Value | Points | TTFT MAPE % before | after | TPOT MAPE % before | after |
|---|---|---|---|---|---|
| fp4 | 11 | 26.5 | 24.1 | 25.3 | 19.8 |
| int4 | 30 | 32.7 | 32.7 | 13.5 | 13.5 |

**By spec**

| Value | Points | TTFT MAPE % before | after | TPOT MAPE % before | after |
|---|---|---|---|---|---|
| none | 41 | 31.0 | 30.4 | 16.7 | 15.2 |

**By framework**

| Value | Points | TTFT MAPE % before | after | TPOT MAPE % before | after |
|---|---|---|---|---|---|
| vllm | 41 | 31.0 | 30.4 | 16.7 | 15.2 |

**By serving**

| Value | Points | TTFT MAPE % before | after | TPOT MAPE % before | after |
|---|---|---|---|---|---|
| aggregated | 41 | 31.0 | 30.4 | 16.7 | 15.2 |

## What moved points up (design §11.6 backlog)

| Entry | Blocks before | after | Alone before | after | Demotes before | after |
|---|---|---|---|---|---|---|
| `field_not_modelled:kv_cache_dtype` | 997 | 0 | 0 | 0 | 0 | 0 |
| `field_not_modelled:max_cudagraph_capture_size` | 996 | 0 | 28 | 0 | 0 | 0 |
| `field_not_modelled:language_model_only` | 834 | 0 | 0 | 0 | 0 | 0 |
| `field_not_modelled:stream_interval` | 771 | 0 | 0 | 0 | 0 | 0 |
| `not_in_catalog` | 538 | 538 | 82 | 298 | 0 | 0 |
| `field_not_modelled:enable_expert_parallel` | 513 | 0 | 12 | 0 | 0 | 0 |
| `not_in_catalog:eagle3` | 419 | 0 | 0 | 0 | 0 | 0 |
| `field_not_modelled:moe_backend` | 226 | 226 | 0 | 38 | 0 | 0 |
| `field_not_modelled:api_server_count` | 171 | 0 | 0 | 0 | 0 | 0 |
| `field_not_modelled:quantization` | 127 | 0 | 0 | 0 | 0 | 0 |
| `field_not_modelled:linear_backend` | 90 | 90 | 0 | 67 | 0 | 0 |
| `field_not_modelled:mm_encoder_tp_mode` | 65 | 65 | 0 | 0 | 0 | 0 |
| `client_difference:client_flags` | 0 | 0 | 0 | 0 | 41 | 110 |
| `client_difference:send_gap` | 0 | 0 | 0 | 0 | 41 | 110 |
| `coefficient_method:cost-model-attention/attention_decode_floor_mla` | 0 | 0 | 0 | 0 | 41 | 110 |
| `coefficient_method:cost-model-host-overheads/host_admission_per_request` | 0 | 0 | 0 | 0 | 41 | 110 |
| `coefficient_method:cost-model-host-overheads/host_admission_per_token` | 0 | 0 | 0 | 0 | 41 | 110 |
| `coefficient_method:cost-model-host-overheads/host_completion` | 0 | 0 | 0 | 0 | 41 | 110 |
| `coefficient_method:cost-model-host-overheads/host_launch_eager_per_layer` | 0 | 0 | 0 | 0 | 41 | 110 |
| `coefficient_method:cost-model-host-overheads/host_launch_per_kernel` | 0 | 0 | 0 | 0 | 41 | 110 |
| `coefficient_method:cost-model-host-overheads/host_output_token` | 0 | 0 | 0 | 0 | 41 | 110 |
| `coefficient_method:cost-model-host-overheads/host_replay_graph_per_step` | 0 | 0 | 0 | 0 | 41 | 110 |
| `coefficient_method:cost-model-memory/activation_scratch_floor_bytes` | 0 | 0 | 0 | 0 | 41 | 110 |
| `coefficient_method:cost-model-memory/cudagraph_capture_bytes_full_and_piecewise` | 0 | 0 | 0 | 0 | 41 | 74 |
| `coefficient_method:cost-model-primitives/engine_workspace_bytes` | 0 | 0 | 0 | 0 | 41 | 110 |
| `coefficient_method:cost-model-primitives/hbm_derate` | 0 | 0 | 0 | 0 | 41 | 110 |
| `coefficient_range:unevaluated` | 0 | 0 | 0 | 0 | 41 | 110 |
| `estimated:gpu_memory_utilization` | 0 | 0 | 0 | 0 | 41 | 110 |
| `interim_status:host` | 0 | 0 | 0 | 0 | 41 | 110 |
| `interim_status:model` | 0 | 0 | 0 | 0 | 41 | 110 |
| `interim_status:model_tag` | 0 | 0 | 0 | 0 | 41 | 110 |
| `interim_status:port` | 0 | 0 | 0 | 0 | 41 | 110 |
| `interim_status:reasoning_parser` | 0 | 0 | 0 | 0 | 41 | 110 |
| `interim_status:tool_call_parser` | 0 | 0 | 0 | 0 | 41 | 110 |
| `interim_status:trust_remote_code` | 0 | 0 | 0 | 0 | 41 | 110 |
| `kernel_hash:unevaluated` | 0 | 0 | 0 | 0 | 41 | 110 |
| `other_release:engine release` | 0 | 0 | 0 | 0 | 41 | 110 |
| `ported_functions_unpublished:engine release` | 0 | 0 | 0 | 0 | 41 | 110 |
| `resolved_differs:unevaluated` | 0 | 0 | 0 | 0 | 41 | 0 |
| `value_class:unevaluated` | 0 | 0 | 0 | 0 | 41 | 0 |
| `field_not_in_release:env.VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8` | 37 | 37 | 0 | 37 | 0 | 0 |
| `field_not_in_release:env.VLLM_MXFP4_USE_MARLIN` | 35 | 35 | 0 | 35 | 0 | 0 |
| `value_not_recorded` | 35 | 35 | 10 | 10 | 0 | 0 |
| `interim_status:served_model_name` | 0 | 0 | 0 | 0 | 31 | 31 |
| `client_difference:sent_prompt_lengths` | 0 | 0 | 0 | 0 | 30 | 88 |
| `field_not_modelled:env.VLLM_USE_RUST_FRONTEND` | 28 | 28 | 0 | 0 | 0 | 0 |
| `value_not_recorded:no_recipe_fingerprint` | 25 | 25 | 0 | 0 | 0 | 0 |
| `coefficient_method:cost-model-memory/activation_buffer_count_moe_8rank` | 0 | 0 | 0 | 0 | 23 | 66 |
| `coefficient_method:cost-model-primitives/nccl_communicator_bytes_8rank` | 0 | 0 | 0 | 0 | 23 | 66 |
| `value_conflict:model: the log serves /scratch/models/DeepSeek-V4-Pro-NVFP4, the recipe deepseek-ai/DeepSeek-V4-Pro` | 23 | 23 | 0 | 9 | 0 | 0 |
| `later_record:cluster.gpus_per_node` | 0 | 0 | 0 | 0 | 21 | 90 |
| `field_not_modelled:enable_chunked_prefill` | 20 | 0 | 0 | 0 | 0 | 0 |
| `coefficient_method:cost-model-memory/activation_buffer_count_moe_4rank` | 0 | 0 | 0 | 0 | 18 | 26 |
| `coefficient_method:cost-model-primitives/nccl_communicator_bytes_4rank` | 0 | 0 | 0 | 0 | 18 | 26 |
| `field_not_modelled:speculative_config.rejection_sample_method` | 12 | 12 | 0 | 0 | 0 | 0 |
| `value_not_recorded:api_413` | 9 | 9 | 9 | 9 | 0 | 0 |
| `field_not_in_release:env.PYTHONNOUSERSITE` | 7 | 0 | 0 | 0 | 0 | 0 |
| `field_not_modelled:cpu_offload_gb` | 7 | 7 | 0 | 0 | 0 | 0 |
| `field_not_modelled:default_chat_template_kwargs.thinking_mode` | 7 | 7 | 0 | 0 | 0 | 0 |
| `value_not_recorded:kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use` | 7 | 7 | 0 | 0 | 0 | 0 |
| `field_not_modelled:dcp_comm_backend` | 5 | 5 | 0 | 0 | 0 | 0 |
| `field_not_modelled:decode_context_parallel_size` | 5 | 5 | 0 | 0 | 0 | 0 |
| `field_not_modelled:prefix_match_unit` | 5 | 5 | 0 | 0 | 0 | 0 |
| `value_not_recorded:speculative_config.model` | 5 | 5 | 0 | 0 | 0 | 0 |
| `field_not_modelled:enable_eplb` | 4 | 4 | 0 | 0 | 0 | 0 |
| `field_not_in_release:env.MC_ENABLE_DEST_DEVICE_AFFINITY` | 2 | 0 | 0 | 0 | 0 | 0 |
| `field_not_in_release:env.MC_SLICE_SIZE` | 2 | 0 | 0 | 0 | 0 | 0 |
| `field_not_in_release:env.MC_WORKERS_PER_CTX` | 2 | 0 | 0 | 0 | 0 | 0 |
| `field_not_modelled:env.PYTHONHASHSEED` | 2 | 0 | 0 | 0 | 0 | 0 |
| `field_not_modelled:kv_transfer_config.kv_connector_extra_config.load_async` | 2 | 2 | 0 | 0 | 0 | 0 |
| `value_conflict:kv_transfer_config.engine_id` | 1 | 1 | 0 | 0 | 0 | 0 |
| `coefficient_method:cost-model-memory/activation_buffer_count_moe_1rank` | 0 | 0 | 0 | 0 | 0 | 18 |
| `coefficient_method:cost-model-memory/cudagraph_capture_bytes_full_decode_only` | 0 | 0 | 0 | 0 | 0 | 36 |
| `coefficient_method:cost-model-primitives/host_gather_rate_uva` | 0 | 0 | 0 | 0 | 0 | 58 |
| `coefficient_method:cost-model-primitives/nccl_communicator_bytes_2rank` | 0 | 0 | 0 | 0 | 0 | 18 |
| `estimated:api_server_count` | 0 | 0 | 0 | 0 | 0 | 18 |
| `execution_mode:data-parallel balancer` | 0 | 0 | 0 | 0 | 0 | 18 |
| `field_not_in_release:thinking` | 0 | 35 | 0 | 35 | 0 | 0 |
| `interim_status:enable_auto_tool_choice` | 0 | 0 | 0 | 0 | 0 | 48 |
| `interim_status:enable_flashinfer_autotune` | 0 | 0 | 0 | 0 | 0 | 36 |
| `interim_status:tokenizer_mode` | 0 | 0 | 0 | 0 | 0 | 36 |
| `resolved_differs:all_reduce_backend` | 0 | 0 | 0 | 0 | 0 | 18 |
| `value_class:block_size` | 0 | 0 | 0 | 0 | 0 | 36 |
| `value_class:max_model_len` | 0 | 0 | 0 | 0 | 0 | 38 |
| `value_class:max_num_batched_tokens` | 0 | 0 | 0 | 0 | 0 | 47 |
| `value_class:tensor_parallel_size` | 0 | 0 | 0 | 0 | 0 | 66 |

## What would unlock the rest (after)

Blocks: in-scope points held at G5 by the blocker. Alone: points that would be scored if only it were fixed.

| Blocker | Blocks | Alone |
|---|---|---|
| blis_refused:scenario | 791 | 791 |
| field_not_modelled:linear_backend | 67 | 67 |
| field_not_modelled:moe_backend | 56 | 38 |
| field_not_in_release:env.VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8 | 37 | 37 |
| field_not_in_release:env.VLLM_MXFP4_USE_MARLIN | 35 | 35 |
| field_not_in_release:thinking | 35 | 35 |
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

## Newly scored points (69)

| Point | Model | Chip | Precision | Conc | Grade | Reasons |
|---|---|---|---|---|---|---|
| `0516682c128a` | kimi-k2.5-nvfp4 | b200 | fp4 | 16 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `12fc9e9d87cb` | deepseek-v4-pro | h200 | fp8 | 32 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `14baef193989` | deepseek-v4-pro | h200 | fp8 | 2 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `1638d48299bc` | deepseek-v4-pro | h200 | fp8 | 8 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `1a095ebb0bd8` | deepseek-v4-pro | h200 | fp8 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `1d4158fe4fff` | minimax-m2.5 | h100 | fp8 | 64 | G4 | field_not_modelled:enable_expert_parallel |
| `1e48d6c82111` | deepseek-v4-pro | h200 | fp8 | 16 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `205cdceafc4f` | minimax-m2.5 | h100 | fp8 | 8 | G4 | field_not_modelled:enable_expert_parallel |
| `210bed5e0f79` | deepseek-v4-pro | h200 | fp8 | 128 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `258c8d3b61a6` | deepseek-v4-pro | h200 | fp8 | 4 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `2827e57de9c7` | deepseek-v4-pro | h200 | fp8 | 256 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `30d29c7b0430` | kimi-k2.5-nvfp4 | b200 | fp4 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `3855a857e26c` | minimax-m2.5 | h100 | fp8 | 4 | G4 | field_not_modelled:enable_expert_parallel |
| `391b1b6aa935` | kimi-k2.5-nvfp4 | b200 | fp4 | 128 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `3b7440a57b76` | deepseek-v4-pro | h200 | fp8 | 1 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `443a278b609c` | deepseek-v4-pro | h200 | fp8 | 2 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `44f89887cfae` | kimi-k2.5 | h200 | int4 | 32 | G4 | blis_refused:scenario |
| `49fc6383c592` | deepseek-v4-pro | h200 | fp8 | 2 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `4d3cb087b21a` | deepseek-v4-pro | h200 | fp8 | 8 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `4f7a7b3cf9cb` | deepseek-v4-pro | h200 | fp8 | 16 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `500a5016a0ac` | deepseek-v4-pro | h200 | fp8 | 16 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `58d30e293e17` | deepseek-v4-pro | h200 | fp8 | 2 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `5bf72cd99056` | minimax-m2.5 | h100 | fp8 | 64 | G4 | field_not_modelled:enable_expert_parallel |
| `5c4484ebb9d7` | kimi-k2.5 | h200 | int4 | 4 | G4 | blis_refused:scenario |
| `5ee4b4240c0a` | kimi-k2.5 | h200 | int4 | 4 | G4 | blis_refused:scenario |
| `60d3741b7036` | kimi-k2.5-nvfp4 | b200 | fp4 | 32 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `645c9d32878a` | kimi-k2.5 | h200 | int4 | 64 | G4 | blis_refused:scenario |
| `697e5ff8fc3e` | deepseek-v4-pro | h200 | fp8 | 64 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `6ef772fdc3a5` | minimax-m2.5 | h100 | fp8 | 4 | G4 | field_not_modelled:enable_expert_parallel |
| `761febbb814f` | deepseek-v4-pro | h200 | fp8 | 32 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `7b74eed2ab2f` | deepseek-v4-pro | h200 | fp8 | 64 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `7d516424c227` | deepseek-v4-pro | h200 | fp8 | 8 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `7f81f24169ed` | kimi-k2.5-nvfp4 | b200 | fp4 | 8 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `83bb610a7e16` | minimax-m2.5 | h100 | fp8 | 16 | G4 | field_not_modelled:enable_expert_parallel |
| `883f7cf709d3` | minimax-m2.5 | h100 | fp8 | 16 | G4 | field_not_modelled:enable_expert_parallel |
| `8c32e71d8370` | kimi-k2.5 | h200 | int4 | 8 | G4 | blis_refused:scenario |
| `8e2501550520` | kimi-k2.5-nvfp4 | b200 | fp4 | 1 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `9731a04d249e` | deepseek-v4-pro | h200 | fp8 | 128 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `a00db3d80e75` | deepseek-v4-pro | h200 | fp8 | 64 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `a046294958a2` | deepseek-v4-pro | h200 | fp8 | 256 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `a0ab6d22dadd` | minimax-m2.5 | h100 | fp8 | 8 | G4 | field_not_modelled:enable_expert_parallel |
| `a0c0edeefb1e` | deepseek-v4-pro | h200 | fp8 | 1 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `a2366fc1080e` | kimi-k2.5 | h200 | int4 | 8 | G4 | blis_refused:scenario |
| `a90c1a9a7f1b` | deepseek-v4-pro | h200 | fp8 | 128 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `ac8d184173e8` | deepseek-v4-pro | h200 | fp8 | 1 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `aca4ec55aa5a` | deepseek-v4-pro | h200 | fp8 | 16 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `afeb414f876a` | kimi-k2.5-nvfp4 | b200 | fp4 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `b06ad9a1b55f` | minimax-m2.5 | h100 | fp8 | 32 | G4 | field_not_modelled:enable_expert_parallel |
| `baa345f1947b` | minimax-m2.5 | h100 | fp8 | 32 | G4 | field_not_modelled:enable_expert_parallel |
| `c10d4936aaf4` | minimax-m2.5 | h100 | fp8 | 128 | G4 | field_not_modelled:enable_expert_parallel |
| `c3654b90999e` | kimi-k2.5-nvfp4 | b200 | fp4 | 2 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `c5d2e938112a` | kimi-k2.5-nvfp4 | b200 | fp4 | 2 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `c839070241d4` | deepseek-v4-pro | h200 | fp8 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `ca9837b7319f` | kimi-k2.5 | h200 | int4 | 16 | G4 | blis_refused:scenario |
| `cd9c59847268` | kimi-k2.5-nvfp4 | b200 | fp4 | 1 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `cdb09251c999` | deepseek-v4-pro | h200 | fp8 | 256 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `df2d66afee2f` | deepseek-v4-pro | h200 | fp8 | 32 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `df44d6241086` | kimi-k2.5 | h200 | int4 | 16 | G4 | blis_refused:scenario |
| `e2566ef8a2fc` | deepseek-v4-pro | h200 | fp8 | 32 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `e51639f039db` | kimi-k2.5 | h200 | int4 | 64 | G4 | blis_refused:scenario |
| `e55d075d03d3` | deepseek-v4-pro | h200 | fp8 | 4 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `e74c28fc5aed` | deepseek-v4-pro | h200 | fp8 | 64 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `e8d05239975f` | kimi-k2.5-nvfp4 | b200 | fp4 | 64 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `f2322cd17afd` | deepseek-v4-pro | h200 | fp8 | 8 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `f3c4eea987c1` | deepseek-v4-pro | h200 | fp8 | 1 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `f7ad44db9574` | kimi-k2.5 | h200 | int4 | 32 | G4 | blis_refused:scenario |
| `f98085cfd277` | deepseek-v4-pro | h200 | fp8 | 128 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `fc3b819bff0a` | deepseek-v4-pro | h200 | fp8 | 256 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `fe3ccff669d3` | minimax-m2.5 | h100 | fp8 | 128 | G4 | field_not_modelled:enable_expert_parallel |

## Newly refused points (0)

None.

