# The field-list gate with blis-vllm's real classification

Measured 2026-11-10 with the dashboard's coverage command (no simulator), over the baseline's frozen pull (1734 points, second freeze), the layer 10 catalog and registry as a checkout, and blis-vllm's `fields.json` at commit `067bf657de39fe21d0d24cbe361c0faba5047268` of branch `m2/7-refusals-and-engine-block-names` (sha256 `b02574ad6aeb6027d9268de782c9a8edf4bc2dd9c48deb446faf0fcabe0ed65b`; the branch's rebased tip has the same file). Nothing here ran BLIS: v0.16.0 cannot load the layer 10 catalog, and its engine block does not know `enable_chunked_prefill` or `language_model_only`, so the M2 simulator build is needed to see what BLIS says.

| | Points that reach the simulator | Still G5 |
|---|---|---|
| Baseline (v0.13.0 catalog, v0.32.0-blis.2 fields) | 31 | 1703 |
| Real fields, layer 10 catalog, dashboard as it is | 405 | 1329 |
| The same with the node size of b200 and h200 taken as 8 (scratch; not a decision) | 840 | 894 |

The 840 are 71 percent of the 1188 in-scope points; 546 points are AMD and out of scope.

**What still blocks the 894** (reasons a point carries; most carry several). First-reason counts in that scratch run: `not_in_catalog` 290 (546 AMD points count under it in the totals; the 290 here are in-scope: the DeepSeek-V4-Pro and Kimi-K3 points and the models without a catalog entry), `api_server_count` 171, `moe_backend` 146, `linear_backend` 85, `mm_encoder_tp_mode` 65, the removed environment variables `VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8` 37 and `VLLM_MXFP4_USE_MARLIN` 35, a missing server log 35, `api_413` 9, the NVFP4 path against the recipe 9 (23 with other reasons), the connector's CPU bytes 7, `cpu_offload_gb` 5.

**Differences from the classification as described to me**
- `api_server_count`: the file at this commit has `{"rule": "none"}`, not `leave_unset`, so 171 points still carry `field_not_modelled:api_server_count`. With `leave_unset` the scorer would name it as an `estimated` substitution, leave it out of the scenario and let the engine resolve it (fields.decide), and those points would pass the gate as G2/G4.
- `moe_backend` and `linear_backend` are still `not_modelled` (226 and 90 points carry them).
- `stream_interval` is `proven_inert`, `kv_cache_dtype`, `max_cudagraph_capture_size`, `enable_expert_parallel`, `quantization`, `language_model_only` and `enable_chunked_prefill` are `modelled`; every one of them clears.

**Dashboard changes this needed**: `enable_chunked_prefill` and `language_model_only` are written to the engine block (`engine.<name>`), and the field-list loader accepts a numeric value class with no thresholds (one class), which the file uses for the unread environment variables.
