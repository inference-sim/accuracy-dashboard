# Dry run: what BLIS says once the field-list gate is open

Evidence only. It changes no repository: the scratch `fields.json` and the scratch dashboard checkout are not committed.

## What was run

The baseline of `baseline-v0.16.0/` (inference-sim v0.16.0, blis-substrate v0.13.0, the same 1734-point frozen pull, the same harness code from commit `29e8ce4`), scored with three scratch changes:

1. A copy of blis-vllm `v0.32.0-blis.2`'s `fields.json` (`1cf030eb`) in which these fields are `modelled` with the placeholder evidence `{"traces": ["placeholder"]}`: `max_cudagraph_capture_size`, `kv_cache_dtype` (written as `cache_dtype`), `enable_expert_parallel`, `quantization`, `stream_interval`, `enable_eplb`, `moe_backend`, `speculative_config.rejection_sample_method`; and `proven_inert` with the placeholder proof `{"proof": "placeholder"}`: `language_model_only`, `api_server_count`, `enable_chunked_prefill`, `default_chat_template_kwargs`. `linear_backend` is left refused. The sub-field `default_chat_template_kwargs.thinking_mode` is covered by its parent, which is the entry that was changed.
2. The node size of b200 and h200 taken as 8 (as if the maintainer allowed it; see `node-size-b200-h200.md`). No substitution is named for it.
3. The catalog is still blis-substrate v0.13.0, so the eagle3 and dsv4 NVFP4 drafter and model entries of layer 8 are absent.

A first try gave `language_model_only`, `api_server_count` and `enable_chunked_prefill` locations in the engine block (`engine.<name>`) instead of marking them proven inert. BLIS refused all 654 points that reached it: `field enable_chunked_prefill not found in type engineconfig.Engine`, and `language_model_only` and `api_server_count` likewise. The block has no key for any of the three, and the scorer copies a recorded value, resolved ones included (every log resolves `enable_chunked_prefill`), wherever a location exists. A field with no block key must be inert or have its value left out, not mapped.

## Result

| | Points |
|---|---|
| Frozen pull | 1734 |
| Baseline (committed): scored | 31 |
| Dry run: reach the simulator | 654 |
| Dry run: scored (all G4) | 106 (TTFT MAPE 29.4, n=106; TPOT 17.6) |
| Dry run: refused by BLIS | 548 |
| Dry run: still G5 at the gate | 1080 (546 AMD, 534 in scope) |

The gate opened for 654 − 31 = 623 more points than the baseline sends to BLIS (the 31 reached it before); 75 of those 623 are scored, 548 are refused. Roughly four in five points that pass the gate are refused by the engine.

## What BLIS then says

BLIS prints the first error of a scenario only, so a point refused for one reason may carry others. The first errors:

| First BLIS error | Points | Chips and models |
|---|---|---|
| `quantization "mxfp8" is not one this kernel prices` | 238 | b300, h200, b200, h100 `minimaxm3` |
| `stream_interval ... is not modelled ... a value other than vLLM's default would be dropped` | 104 | b200, b300 `minimaxm2.5`; b200 `kimik2.5` |
| `indexer_kv_dtype="bf16" is read only for MiniMax-M3's indexer cache, and this model has none` (blis-vllm#84) | 100 | b300, b200 `dsv4` |
| `quantization "modelopt_mixed" is not one this kernel prices` | 68 | b200, b300 `minimaxm3` |
| `quantization "gpt_oss_mxfp4" is not one this kernel prices` | 28 | h100 `gptoss120b` |
| `deployment block_size is not stated, and kimi-k2.5 on compute capability 9.0 with KV dtype auto is not the same under every setting of what a CPU cannot discover` | 10 | h200 `kimik2.5` |

By field:

- **quantization**: the field-list gate opens, and the kernel then refuses three values it does not price (334 points). The fix is in the kernel's `servedDType` table, not in the field list: `proven_inert` would be false for these.
- **stream_interval**: the engine refuses a value other than its default. Of the 654 points that reach BLIS, 410 set `stream_interval` to 20 (347) or 32 (63); every one of them is refused. All 410 are among the 548 refused, and the 238 + 68 whose first error is quantization carry it as well, so opening `quantization` alone frees none of them. Of the 548 refused, 410 set it and 138 do not (28 `gpt_oss_mxfp4`, 100 `indexer_kv_dtype`, 10 `block_size`). Of the 106 scored, none sets it. (The 5 points at 10 are not among the 654.)
- **indexer_kv_dtype** (100, dsv4): the dashboard writes the run's `indexer_kv_dtype`, the engine reads it only for MiniMax-M3. Whether the scenario should leave it out is a decision for blis-vllm#84; today a stated value is refused.
- **block_size** (10, kimik2.5 on h200): the run did not record `block_size` and the engine will not choose it without `fa3_available`, `flashmla_built` and the like; the scenario cannot state them from a log.
- **Not seen**: none of the 654 produced an unread environment key, a scorer argument difference (`setting_differs`), or an unmarshal refusal once the three block-less fields were inert. The first-error rule may hide some.

Points still G5 at the gate, in scope (534): `not_in_catalog:eagle3` 296 (289 of them have no other reason; layer 8 carries the drafter), `linear_backend` 67, the two removed environment variables 72, `not_in_catalog:mtp` 35, `not_in_catalog` 23 (dsv4 NVFP4), the missing log or fingerprint 43 (35 + 25 overlapping, plus `api_413`), `cpu_offload_gb` 7. `not_in_catalog:mtp` (35) was a defect of this branch, not a catalog gap: the points are DeepSeek-V4-Pro on h200, not MiniMax-M3. vLLM's resolved config names the served model as the draft model of an MTP run, and the draft-checkpoint match then looked it up as a separate drafter. It is fixed in `2190ec7` (the served model's own graph decides). The stated token count (2, against 1 module in the graph) is neither refused nor named.

## Reading

Opening the field list alone moves 31 scored to 106, not to 754. The attrition after the gate is quantization values the kernel does not price (334), the engine's refusal of `stream_interval` other than its default (410 of the points that reach it), and `indexer_kv_dtype` (100). To reach the 754 of the unlock plan each of these needs its own engine change, and the three block-less fields must be proven inert rather than mapped.

Scratch material (not committed): `/tmp/fields-dry.json`, the dry-run output `/tmp/dry-out`, the scratch checkout `/tmp/dry` on branch `scratch/dry-run`.
