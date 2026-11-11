# The field-list gate with blis-vllm's real classification

Measured 2026-11-10 with the dashboard's coverage command (no simulator), over the baseline's frozen pull (1734 points, second freeze), the layer 10 catalog and registry as a checkout, and blis-vllm's `fields.json` at commit `067bf657de39fe21d0d24cbe361c0faba5047268` of branch `m2/7-refusals-and-engine-block-names` (sha256 `b02574ad6aeb6027d9268de782c9a8edf4bc2dd9c48deb446faf0fcabe0ed65b`; the branch's rebased tip has the same file). Nothing here ran BLIS: v0.16.0 cannot load the layer 10 catalog, and its engine block does not know `enable_chunked_prefill` or `language_model_only`, so the M2 simulator build is needed to see what BLIS says.

| | Points that reach the simulator | Still G5 |
|---|---|---|
| Baseline (v0.13.0 catalog, v0.32.0-blis.2 fields) | 31 | 1703 |
| Real fields, layer 10 catalog, dashboard as it is | 405 | 1329 |
| The same with the node size of b200 and h200 taken as 8 (scratch; not a decision) | 840 | 894 |

The 840 are 71 percent of the 1188 in-scope points; 546 points are AMD and out of scope.

**The 290 `not_in_catalog` points are all AMD.** In the scratch run (and in the as-is run) the 290 points whose first reason is `not_in_catalog` are mi300x, mi325x and mi355x points: their reason is the chip (`hardware_no_coefficients`, which the scorer files under `not_in_catalog`), and the catalog and registry have no AMD part. Not one in-scope point carries a `not_in_catalog` reason against the layer 10 catalog with this field list (my earlier sentence that said the 290 included DeepSeek-V4-Pro and Kimi-K3 points was wrong). Per-unit breakdown, from the dashboard's own outcomes:

| Model slug | Chip | Served checkpoint (an HF id in every log) | Points | What the catalog lacks | Resolved by |
|---|---|---|---|---|---|
| minimaxm3 | mi325x 67, mi300x 36 | `MiniMaxAI/MiniMax-M3-MXFP8` | 103 | the chip | (c) nothing available |
| minimaxm2.5 | mi355x 34, mi325x 25, mi300x 20 | `MiniMaxAI/MiniMax-M2.5` | 79 | the chip | (c) |
| dsv4 | mi325x 28, mi300x 28 | `deepseek-ai/DeepSeek-V4-Pro` | 56 | the chip | (c) |
| gptoss120b | mi325x 32, mi355x 20 | `openai/gpt-oss-120b` | 52 | the chip | (c) |

Each model entry exists in the catalog (the checkpoint resolves), none is named by a local path, and no drafter, quantisation variant or path-against-repo question arises. (a) a recipe-checkpoint lookup resolves none of them and (b) no catalog entry of layer 8 is missing for them; what is missing is an AMD hardware entry and its coefficients, which plan v64 puts out of scope for M2 to M4. All 546 AMD points carry the reason; 290 carry nothing else.

**What blocks the in-scope points** (1188 in scope, 405 reach the simulator, 783 are G5 as the dashboard stands). Units carrying each reason, and, in brackets, those whose only other reason is `cluster.gpus_per_node` or nothing: `cluster.gpus_per_node` 645 (435 have no other reason), `api_server_count` 131 (96), `linear_backend` 67 (62), `moe_backend` 56 (17), the removed environment variables `VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8` 37 (37) and `VLLM_MXFP4_USE_MARLIN` 35 (35), a missing server log 35 (10), `no_recipe_fingerprint` 25, the NVFP4 path against the recipe 23 (9), `rejection_sample_method` 12, `cpu_offload_gb` 7, `thinking_mode` 7, the connector's CPU bytes 7, the Kimi-K3 DSpark draft 5, `decode_context_parallel_size` 5, `prefix_match_unit` 5, `dcp_comm_backend` 5, `enable_eplb` 4.

**`mm_encoder_tp_mode`** (65 points). The scorer does nothing with it beyond the field list: it has no location (it is not in `settings.LOCATIONS`), and the list classifies it `not_modelled`, rule `none`, evidence `inference-sim/blis-vllm#57`, so each point that sets it is `field_not_modelled:mm_encoder_tp_mode`. All 65 are Kimi-K2.5 on AMD (mi355x 45, mi325x 10, mi300x 10), value `data`, so they are out of scope in any case. If blis-vllm classifies it `proven_inert` no location is needed. If it classifies it `modelled`, a location must be added (`engine.mm_encoder_tp_mode` if the block has that key, from `rules/engineconfig/fieldnames_test.go`), or the scorer reports `setting_differs`.

**Differences from the classification as described to me**
- `api_server_count`: the file at this commit has `{"rule": "none"}`, not `leave_unset`, so 171 points still carry `field_not_modelled:api_server_count`. With `leave_unset` the scorer would name it as an `estimated` substitution, leave it out of the scenario and let the engine resolve it (fields.decide), and those points would pass the gate as G2/G4.
- `moe_backend` and `linear_backend` are still `not_modelled` (226 and 90 points carry them).
- `stream_interval` is `proven_inert`, `kv_cache_dtype`, `max_cudagraph_capture_size`, `enable_expert_parallel`, `quantization`, `language_model_only` and `enable_chunked_prefill` are `modelled`; every one of them clears.

**Dashboard changes this needed**: `enable_chunked_prefill` and `language_model_only` are written to the engine block (`engine.<name>`), and the field-list loader accepts a numeric value class with no thresholds (one class), which the file uses for the unread environment variables.
