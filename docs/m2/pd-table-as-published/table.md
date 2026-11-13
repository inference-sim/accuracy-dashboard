# Scored run (in-sample)

IN-SAMPLE: the points are the ones the model was calibrated on or tuned against; there is no anchor list yet, so no point is held out. These figures say how well the simulator reproduces data it has seen, not how well it predicts new data.

**Coverage counts include every point, the test split too, by design. Accuracy figures are over train and validation points only, with N stated.** 49 of the points are test or prospective and 0 of them are scored; those 0 are left out of every accuracy figure, so none can be derived by subtraction (docs/m2/evaluation-protocol.md section 6).

- harness commit `0e9627e219c207593de5bc55d997cf3dca707d64`
- units sha256 `69533f0e375706c0a0483b4cd79c5f8dd565c6ac206ee49ba2ae74a90e208477` (188 units)
- pull manifest sha256 `bfa74604f84e64aa2f6c44d73fedee45a816c15d11f66da02396913354f5c3d4`
- point set sha256 `10cdb496f9893d88f59f25d2386e26532ad756e21d107ab6c51552d79ef60c18` (188 points)

Simulator `81a46ba3e0b14ba828eaa46d21191d03dd17376f`, engine {'kind': 'vllm', 'version': '0.32.0'}, fields sha256 `7432f9f82bf551027233a3aae2387fc585408d77d1c44941d037217aed890f1a`.

## Headline (G1 to G4)

| Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % | Noise floor % |
|---|---|---|---|---|---|
| 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) | 1.6 (fallback; none measured per point) |

## By grade

**All points**

| Grade | Points | Share of all | Share of graded | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|---|---|
| G1 | 0 | too few points | - | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G2 | 0 | too few points | - | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G3 | 0 | too few points | - | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G4 | 0 | too few points | - | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G5 | 188 | 100.0% | - | - | - | - | - |

**All scored points: each grade on its own, by serving (aggregated or disaggregated)**

| Serving | Grade | Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|---|
| none scored | | | | | | |

## Development split

Per-split figures use the DEVELOPMENT split of docs/m2/evaluation-protocol.md, not the ledger's held-out: its test set is 'development split, not the ledger's held-out'.

Assignment: sha256 of the salt `blis-dev-split-2` and the series, mod 100; train below 60, validation below 80, test above; a point measured after 2026-11-09 is prospective (test).

| Split | Points | In scope | Scored | Series | Grades | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % | Ranking (groups; Spearman, top-1, regret) |
|---|---|---|---|---|---|---|---|---|---|---|
| train | 114 | 114 | 0 | 6 | G5 114 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) | 0; too few groups, too few groups, too few groups |
| validation | 25 | 25 | 0 | 1 | G5 25 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) | 0; too few groups, too few groups, too few groups |
| test | 49 | | | | withheld: evaluate with `--evaluate-test`, which logs the evaluation | | | | | |
| prospective | 0 | | | | withheld: evaluate with `--evaluate-test`, which logs the evaluation | | | | | |
| unassigned | 0 | 0 | 0 | 0 |  | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) | 0; too few groups, too few groups, too few groups |

## Coverage

Counts of every point, test included, by design.

| Set | Points | Scored | Not scored | Failed | Share scored |
|---|---|---|---|---|---|
| all points | 188 | 0 | 188 | 0 | 0.0% |
| in scope | 188 | 0 | 188 | 0 | 0.0% |
| out of scope (AMD, TPU) | 0 | 0 | 0 | 0 | - |

Out-of-scope points by chip: .

## What would unlock the rest

Blocks: in-scope points held at G5 by the blocker. Alone: points that would be scored if only it were fixed.

| Blocker | Blocks | Alone |
|---|---|---|
| router_unsupported:dynamo-router:revision_not_covered | 186 | 104 |
| field_not_modelled:env.VLLM_FLASHINFER_ALLREDUCE_BACKEND | 48 | 0 |
| field_not_modelled:attention_config.use_trtllm_attention | 28 | 0 |
| field_not_modelled:enforce_eager | 20 | 0 |
| value_not_recorded:workload_category_not_stated | 14 | 0 |
| field_not_in_release:env.VLLM_MINIMAX_M3_MSA_DECODE_BACKEND | 9 | 0 |
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
| `router_unsupported:dynamo-router:revision_not_covered` | 186 | 104 | 0 |
| `field_not_modelled:env.VLLM_FLASHINFER_ALLREDUCE_BACKEND` | 48 | 0 | 0 |
| `field_not_modelled:attention_config.use_trtllm_attention` | 28 | 0 | 0 |
| `field_not_modelled:enforce_eager` | 20 | 0 | 0 |
| `value_not_recorded:workload_category_not_stated` | 14 | 0 | 0 |
| `field_not_in_release:env.VLLM_MINIMAX_M3_MSA_DECODE_BACKEND` | 9 | 0 | 0 |
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
