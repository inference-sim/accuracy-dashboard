# Scored run (in-sample)

IN-SAMPLE: the points are the ones the model was calibrated on or tuned against; there is no anchor list yet, so no point is held out. These figures say how well the simulator reproduces data it has seen, not how well it predicts new data.

**Coverage counts include every point, the test split too, by design. Accuracy figures are over train and validation points only, with N stated.** 0 of the points are test or prospective and 0 of them are scored; those 0 are left out of every accuracy figure, so none can be derived by subtraction (docs/m2/evaluation-protocol.md section 6).

- harness commit `0e9627e219c207593de5bc55d997cf3dca707d64`
- units sha256 `a44e14f4d8d35e44a9c6586599ffdcc6d70a932566df3a4da51529aeaab1f0ca` (16 units)
- pull manifest sha256 `e650d510ccde4b9027c194d9ca52bd40a03a8b7846f81b8e5a21fb615b052bac`
- point set sha256 `fa56a43c439ff679d358a2649f94040e917d80279002cf6a0b54d72c651cf7b0` (16 points)

Simulator `a8bc3085a7c91c50a1d92862943a695c04adfe11`, engine {'kind': 'vllm', 'version': '0.32.0'}, fields sha256 `62743b57746f8376b291fdb853eb0eb19edacc5d717e1e7107d6e0f3ed41348d`.

## Headline (G1 to G4)

| Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % | Noise floor % |
|---|---|---|---|---|---|
| 16 | 34.8 (n=16) | 31.0 (n=14) | 23.5 (n=16) | 24.0 (n=14) | 1.6 (fallback; none measured per point) |

## By grade

**All points**

| Grade | Points | Share of all | Share of graded | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|---|---|
| G1 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G2 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G3 | 0 | too few points | too few points | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G4 | 16 | 100.0% | 100.0% | 34.8 (n=16) | 31.0 (n=14) | 23.5 (n=16) | 24.0 (n=14) |
| G5 | 0 | too few points | - | - | - | - | - |

**All scored points: each grade on its own, by serving (aggregated or disaggregated)**

| Serving | Grade | Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|---|
| aggregated | G1 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| aggregated | G2 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| aggregated | G3 | 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| aggregated | G4 | 16 | 34.8 (n=16) | 31.0 (n=14) | 23.5 (n=16) | 24.0 (n=14) |

## Development split

Per-split figures use the DEVELOPMENT split of docs/m2/evaluation-protocol.md, not the ledger's held-out: its test set is 'development split, not the ledger's held-out'.

Assignment: sha256 of the salt `blis-dev-split-2` and the series, mod 100; train below 60, validation below 80, test above; a point measured after 2026-11-09 is prospective (test).

| Split | Points | In scope | Scored | Series | Grades | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % | Ranking (groups; Spearman, top-1, regret) |
|---|---|---|---|---|---|---|---|---|---|---|
| train | 0 | 0 | 0 | 0 |  | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) | 0; too few groups, too few groups, too few groups |
| validation | 16 | 16 | 16 | 1 | G4 16 | 34.8 (n=16) | 31.0 (n=14) | 23.5 (n=16) | 24.0 (n=14) | 0; too few groups, too few groups, too few groups |
| test | 0 | | | | withheld: evaluate with `--evaluate-test`, which logs the evaluation | | | | | |
| prospective | 0 | | | | withheld: evaluate with `--evaluate-test`, which logs the evaluation | | | | | |
| unassigned | 0 | 0 | 0 | 0 |  | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) | 0; too few groups, too few groups, too few groups |

## Coverage

Counts of every point, test included, by design.

| Set | Points | Scored | Not scored | Failed | Share scored |
|---|---|---|---|---|---|
| all points | 16 | 16 | 0 | 0 | 100.0% |
| in scope | 16 | 16 | 0 | 0 | 100.0% |
| out of scope (AMD, TPU) | 0 | 0 | 0 | 0 | - |

Out-of-scope points by chip: .

## What would unlock the rest

Blocks: in-scope points held at G5 by the blocker. Alone: points that would be scored if only it were fixed.

| Blocker | Blocks | Alone |
|---|---|---|
| out of scope (AMD, TPU) | 0 | 0 |

## Why points are below G1 or at G5 (design §11.6)

| Entry | Blocks | Alone | Demotes |
|---|---|---|---|
| `client_difference:client_build` | 0 | 0 | 16 |
| `coefficient_method:cost-model-attention/attention_decode_floor_mla` | 0 | 0 | 16 |
| `coefficient_method:cost-model-attention/attention_decode_rate_block_index_scores` | 0 | 0 | 16 |
| `coefficient_method:cost-model-attention/attention_prefill_floor_block_index_scores` | 0 | 0 | 16 |
| `coefficient_method:cost-model-attention/attention_prefill_per_token_block_index_scores` | 0 | 0 | 16 |
| `coefficient_method:cost-model-attention/attention_prefill_rate_block_index_scores` | 0 | 0 | 16 |
| `coefficient_method:cost-model-host-overheads/host_admission_per_token` | 0 | 0 | 16 |
| `coefficient_method:cost-model-host-overheads/host_admission_per_token_rust_frontend` | 0 | 0 | 16 |
| `coefficient_method:cost-model-host-overheads/host_completion` | 0 | 0 | 16 |
| `coefficient_method:cost-model-host-overheads/host_launch_eager_per_kernel` | 0 | 0 | 16 |
| `coefficient_method:cost-model-host-overheads/host_launch_eager_per_layer` | 0 | 0 | 16 |
| `coefficient_method:cost-model-host-overheads/host_launch_per_kernel` | 0 | 0 | 16 |
| `coefficient_method:cost-model-host-overheads/host_output_token` | 0 | 0 | 16 |
| `coefficient_method:cost-model-host-overheads/host_replay_graph_per_step` | 0 | 0 | 16 |
| `coefficient_method:cost-model-memory/activation_scratch_floor_bytes` | 0 | 0 | 16 |
| `coefficient_method:cost-model-memory/cudagraph_capture_bytes_full_and_piecewise` | 0 | 0 | 16 |
| `coefficient_method:cost-model-primitives/engine_workspace_bytes` | 0 | 0 | 16 |
| `coefficient_method:cost-model-primitives/gemm_eps_max_w8a16_mxfp8` | 0 | 0 | 16 |
| `coefficient_method:cost-model-primitives/gemm_m_half_w8a16_mxfp8` | 0 | 0 | 16 |
| `coefficient_method:cost-model-primitives/hbm_derate` | 0 | 0 | 16 |
| `coefficient_method:cost-model-primitives/host_gather_rate_uva` | 0 | 0 | 16 |
| `estimated:api_server_count` | 0 | 0 | 16 |
| `estimated:engram_config.cpu_offload` | 0 | 0 | 16 |
| `interim_status:device_ids` | 0 | 0 | 16 |
| `interim_status:disable_uvicorn_access_log` | 0 | 0 | 16 |
| `interim_status:enable_auto_tool_choice` | 0 | 0 | 16 |
| `interim_status:env.VLLM_ENGINE_READY_TIMEOUT_S` | 0 | 0 | 16 |
| `interim_status:host` | 0 | 0 | 16 |
| `interim_status:model` | 0 | 0 | 16 |
| `interim_status:model_tag` | 0 | 0 | 16 |
| `interim_status:reasoning_parser` | 0 | 0 | 16 |
| `interim_status:safetensors_load_strategy` | 0 | 0 | 16 |
| `interim_status:served_model_name` | 0 | 0 | 16 |
| `interim_status:speculative_config.draft_sample_method` | 0 | 0 | 16 |
| `interim_status:tokenizer_mode` | 0 | 0 | 16 |
| `interim_status:tool_call_parser` | 0 | 0 | 16 |
| `other_release:engine release` | 0 | 0 | 16 |
| `ported_functions_unpublished:engine release` | 0 | 0 | 16 |
| `resolved_differs:kv_cache_dtype` | 0 | 0 | 16 |
| `unevaluated:coefficient_range` | 0 | 0 | 16 |
| `unevaluated:kernel_hash` | 0 | 0 | 16 |
| `value_class:max_model_len` | 0 | 0 | 16 |
| `value_class:speculative_config.enable_adaptive_verification` | 0 | 0 | 16 |
| `value_class:speculative_config.num_speculative_tokens` | 0 | 0 | 16 |
| `coefficient_method:cost-model-memory/activation_buffer_count_moe_4rank` | 0 | 0 | 8 |
| `coefficient_method:cost-model-memory/activation_buffer_count_moe_8rank` | 0 | 0 | 8 |
| `coefficient_method:cost-model-primitives/nccl_communicator_bytes_4rank` | 0 | 0 | 8 |
| `coefficient_method:cost-model-primitives/nccl_communicator_bytes_8rank` | 0 | 0 | 8 |
| `value_class:max_num_batched_tokens` | 0 | 0 | 8 |
| `value_class:tensor_parallel_size` | 0 | 0 | 8 |
