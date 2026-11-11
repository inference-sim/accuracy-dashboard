# Before and after (in-sample)

IN-SAMPLE: the points are the ones the model was calibrated on or tuned against; there is no anchor list yet, so no point is held out. These figures say how well the simulator reproduces data it has seen, not how well it predicts new data.

**Accuracy figures leave out the 89 scored test and prospective points** (they are withheld from every figure, so none can be derived by subtraction; docs/m2/evaluation-protocol.md section 6). Every count of points includes them.

Both runs share one harness commit, one units file, one frozen pull and one point set:

- harness commit `a0e899b9c1f433ea99fee80d78ac6f5a54241962`
- units sha256 `d89f860a46c0470a22543dc7fb77b8d1b10e508ce4f5ef5073e96f359f08597e` (1740 units)
- pull manifest sha256 `c8f2ea928b0d4582afdc3fbf11ef9d6847a359791a520f497ee146e806a96166`
- point set sha256 `6818482f91e308ee2b6f844d347de68fef6e90cbc27c22b41d21643d580e5c60` (1734 points)

Before: simulator `v0.16.0`, fields `d32342c4f9ae5c578ba578fd5e6575aa8db8bce099e0708480d55f7e8de5a6fc`.  
After: simulator `ece61af0eccb863ba527d9e1a6dd2ffc97d0c5cf`, fields `9a3a88857a9462caf7b09433cfb53ac377d042aea10e7da2af3a8f9fd1ecccaa`.

## Headline (G1 to G4, every graded point)

| Run | Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|
| before | 11 | 47.1 (n=11) | too few points (n=9) | 58.0 (n=11) | too few points (n=9) |
| after | 361 | 34.0 (n=361) | 17.6 (n=290) | 17.7 (n=361) | 12.9 (n=290) |

Noise floor 1.6 % (fallback; none measured per point).

## Accuracy apart from coverage

A coverage gain cannot hide an accuracy loss, so the points scored in both runs and the points scored in one only are separate rows.

| Set | Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|
| scored in both, before | 41 | 47.1 (n=11) | too few points (n=9) | 58.0 (n=11) | too few points (n=9) |
| scored in both, after | 41 | 24.1 (n=11) | too few points (n=9) | 19.8 (n=11) | too few points (n=9) |
| newly scored, after | 409 | 34.3 (n=350) | 18.0 (n=281) | 17.6 (n=350) | 12.8 (n=281) |
| newly refused, before | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |

Grade moves of the points scored in both: G4->G4 41.

## By grade

**Before**

| Grade | Points | Share of all | Share of graded | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|---|---|
| G1 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G2 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G3 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G4 | 41 | 2.4% | 100.0% | 47.1 (n=11) | too few points (n=9) | 58.0 (n=11) | too few points (n=9) |
| G5 | 1683 | 97.1% | - | - | - | - | - |
| failed | 10 | | | | | | |

**After**

| Grade | Points | Share of all | Share of graded | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|---|---|
| G1 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G2 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G3 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G4 | 450 | 26.0% | 100.0% | 34.0 (n=361) | 17.6 (n=290) | 17.7 (n=361) | 12.9 (n=290) |
| G5 | 878 | 50.6% | - | - | - | - | - |
| failed | 406 | | | | | | |

**Before: each grade on its own, by serving (aggregated or disaggregated)**

| Serving | Grade | Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|---|
| aggregated | G1 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| aggregated | G2 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| aggregated | G3 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| aggregated | G4 | 11 | 47.1 (n=11) | too few points (n=9) | 58.0 (n=11) | too few points (n=9) |

**After: each grade on its own, by serving (aggregated or disaggregated)**

| Serving | Grade | Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|---|
| aggregated | G1 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| aggregated | G2 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| aggregated | G3 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| aggregated | G4 | 361 | 34.0 (n=361) | 17.6 (n=290) | 17.7 (n=361) | 12.9 (n=290) |

## Development split, before

Per-split figures use the DEVELOPMENT split of docs/m2/evaluation-protocol.md, not the ledger's held-out: its test set is 'development split, not the ledger's held-out'.

Assignment: sha256 of the salt `blis-dev-split-2` and the series, mod 100; train below 60, validation below 80, test above; a point measured after 2026-11-09 is prospective (test).

| Split | Points | In scope | Scored | Series | Grades | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % | Ranking (groups; Spearman, top-1, regret) |
|---|---|---|---|---|---|---|---|---|---|---|
| train | 956 | 626 | 0 | 33 | G5 956 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) | 0; too few groups, too few groups, too few groups |
| validation | 332 | 220 | 11 | 9 | G4 11, G5 321 | 47.1 (n=11) | too few points (n=9) | 58.0 (n=11) | too few points (n=9) | 1; too few groups, too few groups, too few groups |
| test | 446 | | | | withheld: evaluate with `--evaluate-test`, which logs the evaluation | | | | | |
| prospective | 0 | | | | withheld: evaluate with `--evaluate-test`, which logs the evaluation | | | | | |
| unassigned | 0 | 0 | 0 | 0 |  | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) | 0; too few groups, too few groups, too few groups |

## Development split, after

Per-split figures use the DEVELOPMENT split of docs/m2/evaluation-protocol.md, not the ledger's held-out: its test set is 'development split, not the ledger's held-out'.

Assignment: sha256 of the salt `blis-dev-split-2` and the series, mod 100; train below 60, validation below 80, test above; a point measured after 2026-11-09 is prospective (test).

| Split | Points | In scope | Scored | Series | Grades | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % | Ranking (groups; Spearman, top-1, regret) |
|---|---|---|---|---|---|---|---|---|---|---|
| train | 956 | 626 | 286 | 33 | G4 286, G5 594, failed 76 | 37.0 (n=286) | 17.5 (n=231) | 16.2 (n=286) | 12.6 (n=231) | 16; 0.98, 0.81, 0.02 |
| validation | 332 | 220 | 75 | 9 | G4 75, G5 172, failed 85 | 22.7 (n=75) | 17.9 (n=59) | 23.3 (n=75) | 14.1 (n=59) | 3; too few groups, too few groups, too few groups |
| test | 446 | | | | withheld: evaluate with `--evaluate-test`, which logs the evaluation | | | | | |
| prospective | 0 | | | | withheld: evaluate with `--evaluate-test`, which logs the evaluation | | | | | |
| unassigned | 0 | 0 | 0 | 0 |  | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) | 0; too few groups, too few groups, too few groups |

## Coverage

| Set | Points | Scored | Not scored | Failed | Share scored |
|---|---|---|---|---|---|
| before all points | 1734 | 41 | 1683 | 10 | 2.4% |
| before in scope | 1188 | 41 | 1137 | 10 | 3.5% |
| before out of scope (AMD, TPU) | 546 | 0 | 546 | 0 | 0.0% |
| after all points | 1734 | 450 | 878 | 406 | 26.0% |
| after in scope | 1188 | 450 | 332 | 406 | 37.9% |
| after out of scope (AMD, TPU) | 546 | 0 | 546 | 0 | 0.0% |

Out-of-scope points by chip: mi300x 95, mi325x 171, mi355x 280.

## Coverage movement by reason

Blocks: points carrying the reason. Alone: points whose only reason it is.

**All points**

| Reason | Blocks before | after | change | Alone before | after | change |
|---|---|---|---|---|---|---|
| `blis_refused:scenario` | 10 | 406 | +396 | 10 | 406 | +396 |
| `field_not_in_release:env.MC_ENABLE_DEST_DEVICE_AFFINITY` | 2 | 0 | -2 | 0 | 0 | +0 |
| `field_not_in_release:env.MC_SLICE_SIZE` | 2 | 0 | -2 | 0 | 0 | +0 |
| `field_not_in_release:env.MC_WORKERS_PER_CTX` | 2 | 0 | -2 | 0 | 0 | +0 |
| `field_not_in_release:env.PYTHONNOUSERSITE` | 7 | 0 | -7 | 0 | 0 | +0 |
| `field_not_in_release:env.VLLM_MXFP4_USE_MARLIN` | 35 | 35 | +0 | 0 | 35 | +35 |
| `field_not_in_release:env.VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8` | 37 | 37 | +0 | 0 | 37 | +37 |
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
| `value_not_recorded:workload.thinking_mode` | 0 | 80 | +80 | 0 | 80 | +80 |

**In scope**

| Reason | Blocks before | after | change | Alone before | after | change |
|---|---|---|---|---|---|---|
| `blis_refused:scenario` | 10 | 406 | +396 | 10 | 406 | +396 |
| `field_not_in_release:env.MC_ENABLE_DEST_DEVICE_AFFINITY` | 2 | 0 | -2 | 0 | 0 | +0 |
| `field_not_in_release:env.MC_SLICE_SIZE` | 2 | 0 | -2 | 0 | 0 | +0 |
| `field_not_in_release:env.MC_WORKERS_PER_CTX` | 2 | 0 | -2 | 0 | 0 | +0 |
| `field_not_in_release:env.PYTHONNOUSERSITE` | 7 | 0 | -7 | 0 | 0 | +0 |
| `field_not_in_release:env.VLLM_MXFP4_USE_MARLIN` | 35 | 35 | +0 | 0 | 35 | +35 |
| `field_not_in_release:env.VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8` | 37 | 37 | +0 | 0 | 37 | +37 |
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
| `value_not_recorded:workload.thinking_mode` | 0 | 80 | +80 | 0 | 80 | +80 |

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
| kimi-k2.5 | 11 | 47.1 | too few points | 58.0 | too few points |

**By hardware**

| Value | Points | TTFT MAPE % before | after | TPOT MAPE % before | after |
|---|---|---|---|---|---|
| b200 | 0 | too few points | too few points | too few points | too few points |
| b300 | 11 | 47.1 | 24.1 | 58.0 | 19.8 |

**By precision**

| Value | Points | TTFT MAPE % before | after | TPOT MAPE % before | after |
|---|---|---|---|---|---|
| fp4 | 11 | 47.1 | 24.1 | 58.0 | 19.8 |
| int4 | 0 | too few points | too few points | too few points | too few points |

**By spec**

| Value | Points | TTFT MAPE % before | after | TPOT MAPE % before | after |
|---|---|---|---|---|---|
| none | 11 | 47.1 | 24.1 | 58.0 | 19.8 |

**By framework**

| Value | Points | TTFT MAPE % before | after | TPOT MAPE % before | after |
|---|---|---|---|---|---|
| vllm | 11 | 47.1 | 24.1 | 58.0 | 19.8 |

**By serving**

| Value | Points | TTFT MAPE % before | after | TPOT MAPE % before | after |
|---|---|---|---|---|---|
| aggregated | 11 | 47.1 | 24.1 | 58.0 | 19.8 |

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
| `client_difference:client_flags` | 0 | 0 | 0 | 0 | 41 | 450 |
| `client_difference:failed_requests` | 0 | 0 | 0 | 0 | 41 | 450 |
| `client_difference:send_gap` | 0 | 0 | 0 | 0 | 41 | 450 |
| `coefficient_method:cost-model-attention/attention_decode_floor_mla` | 0 | 0 | 0 | 0 | 41 | 450 |
| `coefficient_method:cost-model-host-overheads/host_admission_per_request` | 0 | 0 | 0 | 0 | 41 | 450 |
| `coefficient_method:cost-model-host-overheads/host_admission_per_token` | 0 | 0 | 0 | 0 | 41 | 450 |
| `coefficient_method:cost-model-host-overheads/host_completion` | 0 | 0 | 0 | 0 | 41 | 450 |
| `coefficient_method:cost-model-host-overheads/host_launch_eager_per_layer` | 0 | 0 | 0 | 0 | 41 | 450 |
| `coefficient_method:cost-model-host-overheads/host_launch_per_kernel` | 0 | 0 | 0 | 0 | 41 | 450 |
| `coefficient_method:cost-model-host-overheads/host_output_token` | 0 | 0 | 0 | 0 | 41 | 450 |
| `coefficient_method:cost-model-host-overheads/host_replay_graph_per_step` | 0 | 0 | 0 | 0 | 41 | 450 |
| `coefficient_method:cost-model-memory/activation_scratch_floor_bytes` | 0 | 0 | 0 | 0 | 41 | 450 |
| `coefficient_method:cost-model-memory/cudagraph_capture_bytes_full_and_piecewise` | 0 | 0 | 0 | 0 | 41 | 450 |
| `coefficient_method:cost-model-primitives/engine_workspace_bytes` | 0 | 0 | 0 | 0 | 41 | 450 |
| `coefficient_method:cost-model-primitives/hbm_derate` | 0 | 0 | 0 | 0 | 41 | 450 |
| `coefficient_range:unevaluated` | 0 | 0 | 0 | 0 | 41 | 315 |
| `estimated:gpu_memory_utilization` | 0 | 0 | 0 | 0 | 41 | 420 |
| `interim_status:host` | 0 | 0 | 0 | 0 | 41 | 239 |
| `interim_status:model` | 0 | 0 | 0 | 0 | 41 | 450 |
| `interim_status:model_tag` | 0 | 0 | 0 | 0 | 41 | 450 |
| `interim_status:port` | 0 | 0 | 0 | 0 | 41 | 450 |
| `interim_status:reasoning_parser` | 0 | 0 | 0 | 0 | 41 | 140 |
| `interim_status:tool_call_parser` | 0 | 0 | 0 | 0 | 41 | 140 |
| `interim_status:trust_remote_code` | 0 | 0 | 0 | 0 | 41 | 422 |
| `kernel_hash:unevaluated` | 0 | 0 | 0 | 0 | 41 | 450 |
| `other_release:engine release` | 0 | 0 | 0 | 0 | 41 | 212 |
| `ported_functions_unpublished:engine release` | 0 | 0 | 0 | 0 | 41 | 212 |
| `resolved_differs:unevaluated` | 0 | 0 | 0 | 0 | 41 | 0 |
| `value_class:unevaluated` | 0 | 0 | 0 | 0 | 41 | 0 |
| `field_not_in_release:env.VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8` | 37 | 37 | 0 | 37 | 0 | 0 |
| `field_not_in_release:env.VLLM_MXFP4_USE_MARLIN` | 35 | 35 | 0 | 35 | 0 | 0 |
| `value_not_recorded` | 35 | 35 | 10 | 10 | 0 | 0 |
| `interim_status:served_model_name` | 0 | 0 | 0 | 0 | 31 | 123 |
| `client_difference:sent_prompt_lengths` | 0 | 0 | 0 | 0 | 30 | 351 |
| `field_not_modelled:env.VLLM_USE_RUST_FRONTEND` | 28 | 28 | 0 | 0 | 0 | 0 |
| `value_not_recorded:no_recipe_fingerprint` | 25 | 25 | 0 | 0 | 0 | 0 |
| `coefficient_method:cost-model-memory/activation_buffer_count_moe_8rank` | 0 | 0 | 0 | 0 | 23 | 223 |
| `coefficient_method:cost-model-primitives/nccl_communicator_bytes_8rank` | 0 | 0 | 0 | 0 | 23 | 223 |
| `value_conflict:model: the log serves /scratch/models/DeepSeek-V4-Pro-NVFP4, the recipe deepseek-ai/DeepSeek-V4-Pro` | 23 | 23 | 0 | 9 | 0 | 0 |
| `later_record:cluster.gpus_per_node` | 0 | 0 | 0 | 0 | 21 | 376 |
| `field_not_modelled:enable_chunked_prefill` | 20 | 0 | 0 | 0 | 0 | 0 |
| `coefficient_method:cost-model-memory/activation_buffer_count_moe_4rank` | 0 | 0 | 0 | 0 | 18 | 151 |
| `coefficient_method:cost-model-primitives/nccl_communicator_bytes_4rank` | 0 | 0 | 0 | 0 | 18 | 151 |
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
| `coefficient_method:cost-model-attention/attention_prefill_floor_trtllm_gen_kv_fp8` | 0 | 0 | 0 | 0 | 0 | 135 |
| `coefficient_method:cost-model-attention/attention_prefill_work_scale_trtllm_gen_kv_fp8` | 0 | 0 | 0 | 0 | 0 | 135 |
| `coefficient_method:cost-model-memory/activation_buffer_count_moe_1rank` | 0 | 0 | 0 | 0 | 0 | 47 |
| `coefficient_method:cost-model-memory/activation_buffer_count_moe_2rank` | 0 | 0 | 0 | 0 | 0 | 29 |
| `coefficient_method:cost-model-primitives/gemm_eps_max_w8a16_mxfp8` | 0 | 0 | 0 | 0 | 0 | 103 |
| `coefficient_method:cost-model-primitives/gemm_m_half_w8a16_mxfp8` | 0 | 0 | 0 | 0 | 0 | 103 |
| `coefficient_method:cost-model-primitives/host_gather_rate_uva` | 0 | 0 | 0 | 0 | 0 | 189 |
| `coefficient_method:cost-model-primitives/nccl_communicator_bytes_2rank` | 0 | 0 | 0 | 0 | 0 | 73 |
| `coefficient_range:cost-model-attention/attention_prefill_floor_trtllm_gen_kv_fp8` | 0 | 0 | 0 | 0 | 0 | 135 |
| `coefficient_range:cost-model-attention/attention_prefill_work_scale_trtllm_gen_kv_fp8` | 0 | 0 | 0 | 0 | 0 | 135 |
| `estimated:api_server_count` | 0 | 0 | 0 | 0 | 0 | 44 |
| `execution_mode:data-parallel balancer` | 0 | 0 | 0 | 0 | 0 | 44 |
| `interim_status:enable_auto_tool_choice` | 0 | 0 | 0 | 0 | 0 | 78 |
| `interim_status:enable_flashinfer_autotune` | 0 | 0 | 0 | 0 | 0 | 36 |
| `interim_status:tokenizer_mode` | 0 | 0 | 0 | 0 | 0 | 66 |
| `nightly_or_custom:engine build` | 0 | 0 | 0 | 0 | 0 | 238 |
| `resolved_differs:all_reduce_backend` | 0 | 0 | 0 | 0 | 0 | 47 |
| `value_class:block_size` | 0 | 0 | 0 | 0 | 0 | 348 |
| `value_class:max_model_len` | 0 | 0 | 0 | 0 | 0 | 213 |
| `value_class:max_num_batched_tokens` | 0 | 0 | 0 | 0 | 0 | 387 |
| `value_class:tensor_parallel_size` | 0 | 0 | 0 | 0 | 0 | 252 |
| `value_not_recorded:workload.thinking_mode` | 0 | 80 | 0 | 80 | 0 | 0 |

## What would unlock the rest (after)

Blocks: in-scope points held at G5 by the blocker. Alone: points that would be scored if only it were fixed.

| Blocker | Blocks | Alone |
|---|---|---|
| blis_refused:scenario | 406 | 406 |
| value_not_recorded:workload.thinking_mode | 80 | 80 |
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

## Newly scored points (409)

| Point | Model | Chip | Precision | Conc | Grade | Reasons |
|---|---|---|---|---|---|---|
| `01134fd566df` | minimax-m3-mxfp8 | h200 | fp8 | 8 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `014a5d6b1f71` | minimax-m3-mxfp8 | h200 | fp8 | 4 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `0194a5fd59aa` | minimax-m2.5 | b200 | fp8 | 64 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `03216697001b` | minimax-m3-mxfp8 | h100 | fp8 | 4 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `0516682c128a` | kimi-k2.5-nvfp4 | b200 | fp4 | 16 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `0573227f6131` | minimax-m3-mxfp8 | b200 | fp8 | 128 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `05c75fddcc1a` | minimax-m3-mxfp8 | h200 | fp8 | 256 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `060c7883091d` | minimax-m2.5 | b300 | fp8 | 64 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `0657a559835b` | minimax-m3-mxfp8 | b200 | fp8 | 8 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `06618cdd8c68` | minimax-m3-mxfp8 | b200 | fp8 | 2 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `068ce9361728` | minimax-m3-mxfp8 | b300 | fp8 | 1024 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `06be356e2ff4` | minimax-m3-mxfp8 | b200 | fp8 | 256 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `08c50841b18b` | minimax-m3-mxfp8 | h200 | fp8 | 8 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `08d65ee0c5b3` | minimax-m3-mxfp8 | h200 | fp8 | 1 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `08dd73e1a4f2` | minimax-m3-mxfp8 | b300 | fp8 | 512 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `095670853ec7` | minimax-m3-mxfp8 | b200 | fp8 | 256 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `0a985a12e85c` | minimax-m3-mxfp8 | h100 | fp8 | 32 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `0ccef2d20422` | gpt-oss-120b | h100 | fp4 | 4 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `0cd2f59b3f27` | minimax-m3-mxfp8 | b300 | fp8 | 8 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `0d15630197d4` | minimax-m3-mxfp8 | h200 | fp8 | 4 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `0d46dfac5b9c` | minimax-m3-mxfp8 | b300 | fp8 | 256 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `0e2666e54395` | minimax-m3-mxfp8 | b300 | fp8 | 2 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `0e732c0573ac` | minimax-m3-mxfp8 | h100 | fp8 | 16 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `0ffbf2afaafb` | minimax-m2.5 | b200 | fp8 | 64 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `10672638c811` | minimax-m3-mxfp8 | h200 | fp8 | 256 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `10723465d293` | minimax-m2.5 | b300 | fp8 | 128 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `107548f48879` | minimax-m3-mxfp8 | b300 | fp8 | 2 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `10a4c1365c06` | minimax-m3-mxfp8 | b200 | fp8 | 16 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `119e533459a9` | gpt-oss-120b | h100 | fp4 | 64 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `11d9b9b56340` | gpt-oss-120b | h100 | fp4 | 16 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `12814b64bdea` | deepseek-v4-pro | b200 | fp4 | 64 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `12fc9e9d87cb` | deepseek-v4-pro | h200 | fp8 | 32 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `1375877cc43d` | minimax-m3-mxfp8 | b200 | fp8 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `13c4357ea599` | minimax-m2.5 | b300 | fp8 | 8 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `140666e9702a` | gpt-oss-120b | h100 | fp4 | 8 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `14baef193989` | deepseek-v4-pro | h200 | fp8 | 2 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `1638d48299bc` | deepseek-v4-pro | h200 | fp8 | 8 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `17ce25c45338` | minimax-m2.5 | b200 | fp8 | 8 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `17ea99851369` | minimax-m3-mxfp8 | b300 | fp8 | 128 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `183bcf21ebbf` | minimax-m3-mxfp8 | b200 | fp8 | 64 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `1a095ebb0bd8` | deepseek-v4-pro | h200 | fp8 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `1bc81710065f` | minimax-m3-mxfp8 | h200 | fp8 | 64 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `1c0f00a0f899` | minimax-m3-mxfp8 | h200 | fp8 | 4 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `1c9add8661b0` | minimax-m3-mxfp8 | h100 | fp8 | 16 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `1d4158fe4fff` | minimax-m2.5 | h100 | fp8 | 64 | G4 | field_not_modelled:enable_expert_parallel |
| `1e48d6c82111` | deepseek-v4-pro | h200 | fp8 | 16 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `1e99c1b717d9` | minimax-m3-mxfp8 | h100 | fp8 | 2 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `205cdceafc4f` | minimax-m2.5 | h100 | fp8 | 8 | G4 | field_not_modelled:enable_expert_parallel |
| `2074d10caaf2` | deepseek-v4-pro | b300 | fp4 | 8 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `210bed5e0f79` | deepseek-v4-pro | h200 | fp8 | 128 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `2194ac9ebe08` | minimax-m3-mxfp8 | b300 | fp8 | 1 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `220ab9c62582` | minimax-m3-mxfp8 | h100 | fp8 | 128 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `223538e9a615` | minimax-m3-mxfp8 | b300 | fp8 | 128 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `22705934eea5` | minimax-m3-mxfp8 | b200 | fp8 | 4 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `229a49161a9d` | minimax-m3-mxfp8 | b200 | fp8 | 64 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `22d20eb6caae` | minimax-m3-mxfp8 | b300 | fp8 | 64 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `232bedb8db2e` | minimax-m3-mxfp8 | b300 | fp8 | 256 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `24a9ea4dfed8` | minimax-m3-mxfp8 | b200 | fp8 | 1 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `258c8d3b61a6` | deepseek-v4-pro | h200 | fp8 | 4 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `25989c9faaf7` | minimax-m3-mxfp8 | b200 | fp8 | 64 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `277847877499` | minimax-m2.5 | b200 | fp8 | 512 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `279737b22b94` | minimax-m3-mxfp8 | h200 | fp8 | 2 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `2827e57de9c7` | deepseek-v4-pro | h200 | fp8 | 256 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `29b5cd22e391` | gpt-oss-120b | h100 | fp4 | 64 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `2aa20b397287` | deepseek-v4-pro | b200 | fp4 | 2 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `2aca0c6bbd27` | minimax-m3-mxfp8 | b300 | fp8 | 8 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `2af1e401820b` | minimax-m3-mxfp8 | b200 | fp8 | 512 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `2b31d8b4f83b` | minimax-m3-mxfp8 | h200 | fp8 | 4 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `2b84c393169a` | deepseek-v4-pro | b300 | fp4 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `2b9dcb72b6f5` | minimax-m3-mxfp8 | b200 | fp8 | 32 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `2c217195ca20` | minimax-m3-mxfp8 | h200 | fp8 | 64 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `2cc46a1e6e9d` | minimax-m3-mxfp8 | b300 | fp8 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `2ceb421e556d` | minimax-m3-mxfp8 | h200 | fp8 | 1 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `2e963d729818` | minimax-m3-mxfp8 | b300 | fp8 | 128 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `2ef6ed7c0156` | minimax-m3-mxfp8 | h200 | fp8 | 32 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `2ff649131c9f` | deepseek-v4-pro | b300 | fp4 | 1 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `307c4f580643` | minimax-m3-mxfp8 | h100 | fp8 | 256 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `30d29c7b0430` | kimi-k2.5-nvfp4 | b200 | fp4 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `30e6bddeaf15` | minimax-m3-mxfp8 | h200 | fp8 | 512 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `31975d60fc2d` | minimax-m3-mxfp8 | h200 | fp8 | 32 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `31a517ba9695` | gpt-oss-120b | h100 | fp4 | 4 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `31b1674670c0` | minimax-m3-mxfp8 | b300 | fp8 | 32 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `31d57af13649` | minimax-m3-mxfp8 | h200 | fp8 | 2 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `31e1a3c32c14` | minimax-m3-mxfp8 | h200 | fp8 | 128 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `3297bec459de` | minimax-m2.5 | b300 | fp8 | 64 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `3510b6e8413c` | minimax-m3-mxfp8 | b300 | fp8 | 16 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `3594b0d60c5e` | gpt-oss-120b | h100 | fp4 | 32 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `3664b189f5ce` | minimax-m3-mxfp8 | b200 | fp8 | 256 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `37239e858d2b` | deepseek-v4-pro | b300 | fp4 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `380d26c6ed9a` | minimax-m3-mxfp8 | h100 | fp8 | 256 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `3825231d48a2` | minimax-m3-mxfp8 | b200 | fp8 | 8 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `3855a857e26c` | minimax-m2.5 | h100 | fp8 | 4 | G4 | field_not_modelled:enable_expert_parallel |
| `391b1b6aa935` | kimi-k2.5-nvfp4 | b200 | fp4 | 128 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `39b315296f5b` | minimax-m3-mxfp8 | h200 | fp8 | 16 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `3a130829e8da` | gpt-oss-120b | h100 | fp4 | 64 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `3a5d4eb757ef` | minimax-m2.5 | b200 | fp8 | 128 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `3abf9e4cc048` | minimax-m3-mxfp8 | b200 | fp8 | 8 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `3b7440a57b76` | deepseek-v4-pro | h200 | fp8 | 1 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `3b76f441bd0f` | minimax-m3-mxfp8 | b300 | fp8 | 256 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `3b8a23bffb1d` | minimax-m3-mxfp8 | h100 | fp8 | 2 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `3ce26987ff5b` | minimax-m3-mxfp8 | b300 | fp8 | 2 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `3ceb044e7ef2` | minimax-m3-mxfp8 | b200 | fp8 | 128 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `3f520fe250a1` | minimax-m3-mxfp8 | b300 | fp8 | 256 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `3f9ab116255d` | minimax-m3-mxfp8 | b300 | fp8 | 64 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `41869a3923c9` | minimax-m2.5 | b200 | fp8 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `4191fd308fe1` | minimax-m3-mxfp8 | h200 | fp8 | 64 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `4206f69a098c` | minimax-m3-mxfp8 | h100 | fp8 | 1 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `421ad8d6e679` | minimax-m3-mxfp8 | b200 | fp8 | 128 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `421d5e3e480b` | minimax-m3-mxfp8 | b300 | fp8 | 1 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `422305c12297` | minimax-m3-mxfp8 | b200 | fp8 | 1 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `422449ed1885` | minimax-m3-mxfp8 | b300 | fp8 | 512 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `4282a59bab68` | minimax-m3-mxfp8 | b300 | fp8 | 32 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `42eb2cca9988` | minimax-m2.5 | b200 | fp8 | 512 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `443a278b609c` | deepseek-v4-pro | h200 | fp8 | 2 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `44664aca9378` | minimax-m3-mxfp8 | b200 | fp8 | 1024 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `449d09f04fdf` | gpt-oss-120b | h100 | fp4 | 4 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `44f89887cfae` | kimi-k2.5 | h200 | int4 | 32 | G4 | blis_refused:scenario |
| `456bd7903577` | minimax-m3-mxfp8 | b200 | fp8 | 256 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `46a408a6ed87` | deepseek-v4-pro | b300 | fp4 | 1 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `4910aed68d67` | minimax-m3-mxfp8 | b300 | fp8 | 256 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `49fc6383c592` | deepseek-v4-pro | h200 | fp8 | 2 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `4a142358a29b` | minimax-m3-mxfp8 | h200 | fp8 | 8 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `4a7de52ffda6` | minimax-m3-mxfp8 | b300 | fp8 | 64 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `4c95e845e905` | minimax-m3-mxfp8 | b300 | fp8 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `4caaafe7b046` | minimax-m3-mxfp8 | h200 | fp8 | 16 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `4d3cb087b21a` | deepseek-v4-pro | h200 | fp8 | 8 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `4d7a1aeeaa4a` | minimax-m3-mxfp8 | b200 | fp8 | 2 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `4e7b463c3e88` | minimax-m3-mxfp8 | h200 | fp8 | 8 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `4f6dec068991` | minimax-m3-mxfp8 | b300 | fp8 | 16 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `4f7a7b3cf9cb` | deepseek-v4-pro | h200 | fp8 | 16 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `4fb68dff90dc` | minimax-m2.5 | b300 | fp8 | 256 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `500a5016a0ac` | deepseek-v4-pro | h200 | fp8 | 16 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `502c7771ad57` | minimax-m3-mxfp8 | h100 | fp8 | 4 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `50652b27159c` | minimax-m3-mxfp8 | b200 | fp8 | 1 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `5172efab9c5b` | minimax-m3-mxfp8 | h100 | fp8 | 2 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `519e61b11d44` | minimax-m3-mxfp8 | b300 | fp8 | 128 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `52cd1dfc642b` | deepseek-v4-pro | b200 | fp4 | 1 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `530ed9e715a3` | minimax-m3-mxfp8 | b200 | fp8 | 16 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `5326daa32360` | minimax-m3-mxfp8 | b200 | fp8 | 64 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `532fa3cdbee3` | minimax-m3-mxfp8 | b300 | fp8 | 32 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `538e4c9dd6c6` | minimax-m3-mxfp8 | h200 | fp8 | 32 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `55388f1170aa` | minimax-m3-mxfp8 | h100 | fp8 | 128 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `5571269edb7e` | minimax-m3-mxfp8 | h200 | fp8 | 1 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `566bc5cc3758` | minimax-m3-mxfp8 | h200 | fp8 | 1 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `574c26ba824c` | minimax-m2.5 | b300 | fp8 | 1024 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `576b7ba93751` | minimax-m3-mxfp8 | b200 | fp8 | 64 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `57965e0d5d20` | minimax-m2.5 | b300 | fp8 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `58d30e293e17` | deepseek-v4-pro | h200 | fp8 | 2 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `58ef9df8eec9` | minimax-m3-mxfp8 | b300 | fp8 | 32 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `597e9b95250c` | minimax-m3-mxfp8 | b300 | fp8 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `5bf72cd99056` | minimax-m2.5 | h100 | fp8 | 64 | G4 | field_not_modelled:enable_expert_parallel |
| `5c0d55ab00bc` | minimax-m3-mxfp8 | h100 | fp8 | 32 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `5c4484ebb9d7` | kimi-k2.5 | h200 | int4 | 4 | G4 | blis_refused:scenario |
| `5c67ef14a433` | minimax-m3-mxfp8 | h200 | fp8 | 128 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `5d2a707d230e` | minimax-m3-mxfp8 | h100 | fp8 | 8 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `5d301a55e420` | minimax-m3-mxfp8 | b200 | fp8 | 32 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `5d6af5306345` | minimax-m3-mxfp8 | h100 | fp8 | 2 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `5d8e9e8d8251` | minimax-m3-mxfp8 | b300 | fp8 | 128 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `5d98b60f7fc9` | deepseek-v4-pro | b300 | fp4 | 2 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `5dea9a5b164d` | gpt-oss-120b | h100 | fp4 | 4 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `5ee4b4240c0a` | kimi-k2.5 | h200 | int4 | 4 | G4 | blis_refused:scenario |
| `5f48874db155` | minimax-m2.5 | b300 | fp8 | 128 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `60d3741b7036` | kimi-k2.5-nvfp4 | b200 | fp4 | 32 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `620ff9b9c158` | minimax-m3-mxfp8 | b300 | fp8 | 128 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `6269e6521ffb` | deepseek-v4-pro | b300 | fp4 | 64 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `626e712a442c` | minimax-m3-mxfp8 | b300 | fp8 | 128 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `627cdd1e3d6a` | minimax-m3-mxfp8 | h100 | fp8 | 8 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `6360d1715b8c` | minimax-m3-mxfp8 | b200 | fp8 | 1 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `63ba067bb987` | minimax-m3-mxfp8 | h200 | fp8 | 256 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `645c9d32878a` | kimi-k2.5 | h200 | int4 | 64 | G4 | blis_refused:scenario |
| `645cfc9bb432` | minimax-m2.5 | b300 | fp8 | 16 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `65e3e190dd0b` | minimax-m3-mxfp8 | h200 | fp8 | 32 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `663cc7985201` | minimax-m3-mxfp8 | b300 | fp8 | 1 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `66703b2a7f65` | minimax-m3-mxfp8 | b300 | fp8 | 8 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `69571d020693` | minimax-m2.5 | b200 | fp8 | 128 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `697e5ff8fc3e` | deepseek-v4-pro | h200 | fp8 | 64 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `69f1b9972878` | minimax-m3-mxfp8 | b200 | fp8 | 32 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `6a0084576fab` | minimax-m3-mxfp8 | b200 | fp8 | 2 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `6ac7c01b7925` | minimax-m3-mxfp8 | b200 | fp8 | 64 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `6cb832e91574` | gpt-oss-120b | h100 | fp4 | 8 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `6e4338b1670c` | deepseek-v4-pro | b300 | fp4 | 2 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `6e4cd10c9383` | minimax-m3-mxfp8 | b200 | fp8 | 64 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `6ec4878c554e` | minimax-m3-mxfp8 | b300 | fp8 | 32 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `6ef772fdc3a5` | minimax-m2.5 | h100 | fp8 | 4 | G4 | field_not_modelled:enable_expert_parallel |
| `706598517b0f` | minimax-m2.5 | b200 | fp8 | 256 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `708ee6b2de33` | gpt-oss-120b | h100 | fp4 | 32 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `71782393ecd4` | minimax-m3-mxfp8 | h200 | fp8 | 8 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `723e8f7b7cf5` | minimax-m3-mxfp8 | h200 | fp8 | 32 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `7373aecad27b` | minimax-m2.5 | b300 | fp8 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `7429e013a891` | minimax-m3-mxfp8 | h200 | fp8 | 64 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `742d9d262c91` | minimax-m3-mxfp8 | b200 | fp8 | 64 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `754f2b1958e2` | minimax-m3-mxfp8 | b200 | fp8 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `755c1d839076` | minimax-m3-mxfp8 | h200 | fp8 | 1 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `75c711324f8e` | minimax-m3-mxfp8 | b300 | fp8 | 128 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `761febbb814f` | deepseek-v4-pro | h200 | fp8 | 32 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `7623dfb7bbf1` | minimax-m3-mxfp8 | h100 | fp8 | 128 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `765051c52523` | minimax-m3-mxfp8 | b200 | fp8 | 16 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `76a9690ff12e` | minimax-m3-mxfp8 | b200 | fp8 | 4 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `76d67f63f43f` | gpt-oss-120b | h100 | fp4 | 8 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `76edeba6991a` | gpt-oss-120b | h100 | fp4 | 32 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `77db409837dd` | minimax-m2.5 | b300 | fp8 | 16 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `77f6df2e9b3d` | minimax-m3-mxfp8 | b300 | fp8 | 64 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `7847408c918a` | minimax-m3-mxfp8 | h200 | fp8 | 2 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `7aff5eaa70e2` | minimax-m3-mxfp8 | h200 | fp8 | 128 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `7b74eed2ab2f` | deepseek-v4-pro | h200 | fp8 | 64 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `7c4f6dd05499` | minimax-m3-mxfp8 | h200 | fp8 | 8 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `7cf113d366af` | minimax-m3-mxfp8 | b300 | fp8 | 512 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `7d139dc48463` | minimax-m3-mxfp8 | h100 | fp8 | 1 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `7d516424c227` | deepseek-v4-pro | h200 | fp8 | 8 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `7e0754e377cd` | minimax-m3-mxfp8 | b200 | fp8 | 128 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `7e13ef2a1a00` | minimax-m3-mxfp8 | b200 | fp8 | 32 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `7ee402f7549a` | minimax-m3-mxfp8 | h200 | fp8 | 4 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `7f2a56c20240` | minimax-m3-mxfp8 | b300 | fp8 | 2 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `7f81f24169ed` | kimi-k2.5-nvfp4 | b200 | fp4 | 8 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `800614ffee21` | deepseek-v4-pro | b300 | fp4 | 2 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `8190c9b2e3bb` | deepseek-v4-pro | b300 | fp4 | 1 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `81d96055267f` | minimax-m3-mxfp8 | h200 | fp8 | 8 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `81f6417395e6` | minimax-m3-mxfp8 | b300 | fp8 | 16 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `820ef346e560` | minimax-m3-mxfp8 | h200 | fp8 | 8 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `821b5ddbaf2e` | minimax-m3-mxfp8 | h200 | fp8 | 256 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `82e4cb650d59` | minimax-m3-mxfp8 | h200 | fp8 | 1 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `83bb610a7e16` | minimax-m2.5 | h100 | fp8 | 16 | G4 | field_not_modelled:enable_expert_parallel |
| `83fd23372459` | minimax-m3-mxfp8 | h100 | fp8 | 4 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `851bea622eea` | minimax-m2.5 | b200 | fp8 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `8534768eecfb` | deepseek-v4-pro | b200 | fp4 | 16 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `8552d90de12b` | minimax-m2.5 | b200 | fp8 | 64 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `85d30659e7b8` | minimax-m3-mxfp8 | h200 | fp8 | 2 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `87056fbcb41d` | deepseek-v4-pro | b300 | fp4 | 16 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `87b3dca6d415` | minimax-m3-mxfp8 | b200 | fp8 | 1 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `87eb1e74340a` | minimax-m2.5 | b300 | fp8 | 512 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `881ea2338922` | minimax-m3-mxfp8 | b200 | fp8 | 8 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `883f7cf709d3` | minimax-m2.5 | h100 | fp8 | 16 | G4 | field_not_modelled:enable_expert_parallel |
| `890a70cb9815` | minimax-m3-mxfp8 | h200 | fp8 | 64 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `89eab96e09aa` | minimax-m3-mxfp8 | b200 | fp8 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `8b4af3359634` | minimax-m3-mxfp8 | b300 | fp8 | 16 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `8bd8831b869b` | minimax-m2.5 | b200 | fp8 | 256 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `8c216c2046dd` | minimax-m3-mxfp8 | b300 | fp8 | 32 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `8c32e71d8370` | kimi-k2.5 | h200 | int4 | 8 | G4 | blis_refused:scenario |
| `8cc905bcc792` | minimax-m3-mxfp8 | b200 | fp8 | 64 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `8cfadb72fce2` | minimax-m3-mxfp8 | b200 | fp8 | 128 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `8d35471b2ade` | minimax-m3-mxfp8 | b300 | fp8 | 256 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `8e2501550520` | kimi-k2.5-nvfp4 | b200 | fp4 | 1 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `8e88dc669463` | minimax-m3-mxfp8 | h100 | fp8 | 64 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `8fb5760cea6f` | gpt-oss-120b | h100 | fp4 | 4 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `90c3c497bc6c` | minimax-m3-mxfp8 | b200 | fp8 | 512 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `90c74b82c528` | minimax-m3-mxfp8 | b200 | fp8 | 128 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `90e3757dd849` | minimax-m3-mxfp8 | b200 | fp8 | 1 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `916390c7302d` | minimax-m3-mxfp8 | b300 | fp8 | 32 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `9319829a17c6` | minimax-m3-mxfp8 | h200 | fp8 | 16 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `93479930e087` | deepseek-v4-pro | b200 | fp4 | 256 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `93ca37e11e10` | minimax-m3-mxfp8 | b200 | fp8 | 2 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `942f0c44b72f` | minimax-m3-mxfp8 | b200 | fp8 | 2 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `9489b65c7444` | gpt-oss-120b | h100 | fp4 | 16 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `95330f638fb2` | minimax-m3-mxfp8 | b200 | fp8 | 32 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `953f0a913b43` | minimax-m2.5 | b200 | fp8 | 128 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `9548556e6f10` | deepseek-v4-pro | b300 | fp4 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `9731a04d249e` | deepseek-v4-pro | h200 | fp8 | 128 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `980fac560fa1` | minimax-m2.5 | b300 | fp8 | 8 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `9892897c6d05` | minimax-m3-mxfp8 | b300 | fp8 | 512 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `98d2c890b790` | minimax-m3-mxfp8 | b200 | fp8 | 16 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `992a69ed1138` | minimax-m3-mxfp8 | h200 | fp8 | 256 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `9aa062108a58` | minimax-m3-mxfp8 | b200 | fp8 | 512 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `9aac301f1dd0` | minimax-m3-mxfp8 | b200 | fp8 | 16 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `9b132d8a5836` | minimax-m3-mxfp8 | b300 | fp8 | 8 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `9b6ff6d6950a` | minimax-m3-mxfp8 | b200 | fp8 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `9bc4702dba78` | gpt-oss-120b | h100 | fp4 | 4 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `9bf72e9ef812` | minimax-m3-mxfp8 | h200 | fp8 | 16 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `9c93ab131623` | minimax-m3-mxfp8 | h200 | fp8 | 32 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `9f1195d192b0` | minimax-m2.5 | b200 | fp8 | 16 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `9f7b6579eccd` | minimax-m3-mxfp8 | h200 | fp8 | 2 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `9fd37c451ace` | minimax-m3-mxfp8 | h100 | fp8 | 4 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `a00db3d80e75` | deepseek-v4-pro | h200 | fp8 | 64 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `a046294958a2` | deepseek-v4-pro | h200 | fp8 | 256 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `a091af959338` | minimax-m2.5 | b200 | fp8 | 32 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `a0ab6d22dadd` | minimax-m2.5 | h100 | fp8 | 8 | G4 | field_not_modelled:enable_expert_parallel |
| `a0c0edeefb1e` | deepseek-v4-pro | h200 | fp8 | 1 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `a0ca66843a03` | minimax-m3-mxfp8 | h200 | fp8 | 2 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `a2366fc1080e` | kimi-k2.5 | h200 | int4 | 8 | G4 | blis_refused:scenario |
| `a45798d68bb6` | minimax-m3-mxfp8 | h100 | fp8 | 16 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `a4622c432189` | minimax-m2.5 | b300 | fp8 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `a64f767e7614` | minimax-m2.5 | b200 | fp8 | 256 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `a7e56cb11074` | minimax-m3-mxfp8 | b300 | fp8 | 128 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `a88bf6640601` | gpt-oss-120b | h100 | fp4 | 8 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `a90c1a9a7f1b` | deepseek-v4-pro | h200 | fp8 | 128 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `a9bf000bfec9` | minimax-m3-mxfp8 | h200 | fp8 | 64 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `ab4c9a05e1bb` | minimax-m2.5 | b300 | fp8 | 512 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `ac5a53a62363` | gpt-oss-120b | h100 | fp4 | 64 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `ac8d184173e8` | deepseek-v4-pro | h200 | fp8 | 1 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `aca4ec55aa5a` | deepseek-v4-pro | h200 | fp8 | 16 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `acfa2d77d044` | minimax-m3-mxfp8 | h200 | fp8 | 16 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `ade609e01bc4` | minimax-m2.5 | b200 | fp8 | 32 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `afeb414f876a` | kimi-k2.5-nvfp4 | b200 | fp4 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `b06ad9a1b55f` | minimax-m2.5 | h100 | fp8 | 32 | G4 | field_not_modelled:enable_expert_parallel |
| `b199fde32278` | minimax-m2.5 | b200 | fp8 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `b2638a16ee79` | gpt-oss-120b | h100 | fp4 | 8 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `b280ceee8540` | minimax-m3-mxfp8 | b300 | fp8 | 64 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `b35e55f765ca` | minimax-m3-mxfp8 | h200 | fp8 | 16 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `b498e136513b` | minimax-m3-mxfp8 | b300 | fp8 | 16 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `b4eb1c17b4b1` | minimax-m3-mxfp8 | h100 | fp8 | 1 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `b6231c50810f` | deepseek-v4-pro | b300 | fp4 | 128 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `baa345f1947b` | minimax-m2.5 | h100 | fp8 | 32 | G4 | field_not_modelled:enable_expert_parallel |
| `bb51f7c47704` | minimax-m3-mxfp8 | h200 | fp8 | 1 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `bbe19958c382` | minimax-m3-mxfp8 | h200 | fp8 | 4 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `bbff0fe5f2d4` | minimax-m2.5 | b200 | fp8 | 32 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `bc0a109de306` | minimax-m3-mxfp8 | h100 | fp8 | 16 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `bc75391cb9eb` | minimax-m3-mxfp8 | b200 | fp8 | 8 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `bce21a745f0a` | minimax-m3-mxfp8 | h100 | fp8 | 64 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `bd42265fc9c3` | minimax-m3-mxfp8 | b300 | fp8 | 1 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `be22594b745e` | minimax-m3-mxfp8 | h200 | fp8 | 256 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `bfd68a393777` | minimax-m3-mxfp8 | h200 | fp8 | 128 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `c00a95650597` | minimax-m3-mxfp8 | h200 | fp8 | 2 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `c0bdb9f0df21` | minimax-m3-mxfp8 | h100 | fp8 | 64 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `c0d37cd23233` | minimax-m3-mxfp8 | b200 | fp8 | 2 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `c10d4936aaf4` | minimax-m2.5 | h100 | fp8 | 128 | G4 | field_not_modelled:enable_expert_parallel |
| `c3618f626d67` | minimax-m3-mxfp8 | b300 | fp8 | 512 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `c3654b90999e` | kimi-k2.5-nvfp4 | b200 | fp4 | 2 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `c38ca3a9e77e` | minimax-m3-mxfp8 | h200 | fp8 | 1024 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `c5d2e938112a` | kimi-k2.5-nvfp4 | b200 | fp4 | 2 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `c60630fc843e` | minimax-m3-mxfp8 | b300 | fp8 | 64 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `c70d0008896d` | minimax-m3-mxfp8 | b300 | fp8 | 16 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `c7a3d6a98ff8` | minimax-m3-mxfp8 | h200 | fp8 | 2 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `c7f7a34f6bc0` | minimax-m3-mxfp8 | h200 | fp8 | 16 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `c839070241d4` | deepseek-v4-pro | h200 | fp8 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `c93ce7ef883f` | deepseek-v4-pro | b200 | fp4 | 128 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `c96f92c3afdb` | gpt-oss-120b | h100 | fp4 | 16 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `c98ce66c193d` | minimax-m3-mxfp8 | b200 | fp8 | 256 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `ca25a7fb81cc` | minimax-m3-mxfp8 | b300 | fp8 | 256 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `ca9837b7319f` | kimi-k2.5 | h200 | int4 | 16 | G4 | blis_refused:scenario |
| `cd89ffb7c866` | gpt-oss-120b | h100 | fp4 | 16 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `cd9c59847268` | kimi-k2.5-nvfp4 | b200 | fp4 | 1 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `cdb09251c999` | deepseek-v4-pro | h200 | fp8 | 256 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `ce9bc9cf7f8f` | minimax-m3-mxfp8 | h100 | fp8 | 32 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `cee536a70719` | minimax-m3-mxfp8 | h100 | fp8 | 64 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `cf485e6b7d81` | minimax-m3-mxfp8 | b300 | fp8 | 64 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `cfade40bb4a7` | minimax-m3-mxfp8 | h200 | fp8 | 1 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `d007d65046a4` | minimax-m3-mxfp8 | b300 | fp8 | 64 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `d095216a374c` | minimax-m3-mxfp8 | h100 | fp8 | 8 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `d1645de87ad2` | minimax-m2.5 | b200 | fp8 | 8 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `d2a9324b54d5` | minimax-m3-mxfp8 | b200 | fp8 | 512 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `d3910f454cf5` | deepseek-v4-pro | b300 | fp4 | 32 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `d3eccd4fce22` | gpt-oss-120b | h100 | fp4 | 64 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `d3ee50fcfcb8` | minimax-m3-mxfp8 | b200 | fp8 | 8 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `d4cb22378a9a` | minimax-m3-mxfp8 | h200 | fp8 | 64 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `d50c9664014f` | minimax-m3-mxfp8 | h100 | fp8 | 32 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `d5e6d7dd0826` | minimax-m3-mxfp8 | b300 | fp8 | 4 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `d6555ab16de3` | minimax-m2.5 | b300 | fp8 | 8 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `d6cfa960826f` | deepseek-v4-pro | b300 | fp4 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `d8936ecf5c60` | deepseek-v4-pro | b200 | fp4 | 8 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `d9742a74728d` | gpt-oss-120b | h100 | fp4 | 16 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `da2808a64f4c` | minimax-m3-mxfp8 | b300 | fp8 | 64 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `daae3b815c13` | minimax-m2.5 | b300 | fp8 | 1024 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `db0930fc41e3` | minimax-m3-mxfp8 | h100 | fp8 | 1 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `db52d704477f` | minimax-m3-mxfp8 | b200 | fp8 | 256 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `dc13b68d6c25` | gpt-oss-120b | h100 | fp4 | 8 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `dc6256e6efc1` | minimax-m3-mxfp8 | b300 | fp8 | 2 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `dd091912b5aa` | minimax-m3-mxfp8 | b200 | fp8 | 128 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `dd2413c0df90` | deepseek-v4-pro | b300 | fp4 | 16 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `dd72b5b1a6ba` | minimax-m2.5 | b200 | fp8 | 512 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `ded7112951e0` | minimax-m3-mxfp8 | b200 | fp8 | 256 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `dee71e02f299` | minimax-m3-mxfp8 | b300 | fp8 | 512 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `df2d66afee2f` | deepseek-v4-pro | h200 | fp8 | 32 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `df44d6241086` | kimi-k2.5 | h200 | int4 | 16 | G4 | blis_refused:scenario |
| `dffa212e6457` | minimax-m3-mxfp8 | h200 | fp8 | 512 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `e1b5a63a2d31` | minimax-m3-mxfp8 | b300 | fp8 | 16 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `e1caf98b1a99` | deepseek-v4-pro | b300 | fp4 | 2 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `e1e83f068969` | deepseek-v4-pro | b200 | fp4 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `e2566ef8a2fc` | deepseek-v4-pro | h200 | fp8 | 32 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `e2e76df9a3cd` | minimax-m3-mxfp8 | h200 | fp8 | 128 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `e31d7e703970` | gpt-oss-120b | h100 | fp4 | 32 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `e4a35cb18df6` | minimax-m3-mxfp8 | b200 | fp8 | 32 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `e4b12fb9da7e` | gpt-oss-120b | h100 | fp4 | 16 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `e51639f039db` | kimi-k2.5 | h200 | int4 | 64 | G4 | blis_refused:scenario |
| `e54d45a3a281` | minimax-m3-mxfp8 | h200 | fp8 | 128 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `e55d075d03d3` | deepseek-v4-pro | h200 | fp8 | 4 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `e5ae475736de` | minimax-m3-mxfp8 | b300 | fp8 | 1 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `e74c28fc5aed` | deepseek-v4-pro | h200 | fp8 | 64 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `e76775cd4d9d` | minimax-m3-mxfp8 | b200 | fp8 | 16 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `e85f6bf9adc7` | minimax-m3-mxfp8 | b300 | fp8 | 8 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `e8d05239975f` | kimi-k2.5-nvfp4 | b200 | fp4 | 64 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `e9d50fb23a74` | minimax-m3-mxfp8 | b300 | fp8 | 8 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `ea474f6c1cc5` | minimax-m2.5 | b200 | fp8 | 8 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `ebb1ee98b555` | minimax-m2.5 | b200 | fp8 | 16 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `ede33c8dab0b` | deepseek-v4-pro | b300 | fp4 | 64 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `ef03ebc0baae` | minimax-m2.5 | b300 | fp8 | 256 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `f0815c494373` | minimax-m3-mxfp8 | h100 | fp8 | 8 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `f2322cd17afd` | deepseek-v4-pro | h200 | fp8 | 8 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `f2abcf48e1a4` | deepseek-v4-pro | b200 | fp4 | 32 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `f3c4eea987c1` | deepseek-v4-pro | h200 | fp8 | 1 | G4 | field_not_modelled:api_server_count, field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `f45fffce2e4a` | minimax-m3-mxfp8 | h200 | fp8 | 32 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `f4e97141601a` | gpt-oss-120b | h100 | fp4 | 32 | G4 | field_not_modelled:max_cudagraph_capture_size |
| `f4f3f2539882` | minimax-m3-mxfp8 | b300 | fp8 | 1 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `f5967724d93e` | minimax-m3-mxfp8 | b300 | fp8 | 64 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `f5d765be2489` | minimax-m3-mxfp8 | b300 | fp8 | 2 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `f719915bb670` | minimax-m3-mxfp8 | h200 | fp8 | 4 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `f736142b3588` | minimax-m3-mxfp8 | b300 | fp8 | 4 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `f7627191f41e` | minimax-m2.5 | b300 | fp8 | 32 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `f77cda799946` | minimax-m3-mxfp8 | h200 | fp8 | 32 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `f7ad44db9574` | kimi-k2.5 | h200 | int4 | 32 | G4 | blis_refused:scenario |
| `f7c80d6dcb6e` | minimax-m3-mxfp8 | b300 | fp8 | 4 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `f887218179be` | deepseek-v4-pro | b300 | fp4 | 8 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `f8f4513e5ff8` | minimax-m3-mxfp8 | h200 | fp8 | 4 | G4 | field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `f96f5726a44b` | minimax-m2.5 | b200 | fp8 | 512 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `f97a84bd8799` | deepseek-v4-pro | b300 | fp4 | 1 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `f98085cfd277` | deepseek-v4-pro | h200 | fp8 | 128 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `fb02f4040ab6` | deepseek-v4-pro | b300 | fp4 | 32 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size |
| `fc3b819bff0a` | deepseek-v4-pro | h200 | fp8 | 256 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:quantization |
| `fd7920501877` | minimax-m2.5 | b200 | fp8 | 16 | G4 | field_not_modelled:kv_cache_dtype, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |
| `fe3ccff669d3` | minimax-m2.5 | h100 | fp8 | 128 | G4 | field_not_modelled:enable_expert_parallel |
| `fea3edcb6cbf` | minimax-m3-mxfp8 | h200 | fp8 | 16 | G4 | field_not_modelled:enable_expert_parallel, field_not_modelled:language_model_only, field_not_modelled:max_cudagraph_capture_size, field_not_modelled:stream_interval |

## Newly refused points (0)

None.

