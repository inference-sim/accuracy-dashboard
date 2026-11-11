# InferenceX series classes and what the harness does with each

Measured on 2026-11-10 from the live API: `/api/v1/availability` (7185 series, 2025-09-29 to 2026-11-10) and `/api/v1/benchmarks` for the 180-day window the nightly pulls (6306 rows, 2026-05-15 to 2026-11-10). A series is one deployment shape for one model and chip; a row is one concurrency of it. The treatment columns come from `engines.py` and `assess.py`; the scored and G5 columns come from the baseline run in `baseline-v0.16.0/` (v0.16.0, harness `2190ec7`), which covers only the units of the published snapshot, so they are 0 for every class the snapshot did not hold. Regenerate the table with `series_classes.py` (this directory).

## The table

| Framework | Topology | Type | Series | Window rows | AMD or TPU rows | Rows with no ledger unit | Units | In the baseline set: scored | G5 | Treatment |
|---|---|---|---|---|---|---|---|---|---|---|
| vllm | agg | single_turn | 2393 | 1696 | 555 | 9 | 1687 | 31 | 1656 | fetched; scored by the harness |
| sglang | agg | single_turn | 2037 | 994 | 361 | 144 | 850 | 0 | 0 | G5 field_unclassified (no fetch) |
| sglang | agg | agentic_traces | 207 | 739 | 195 | 624 | 115 | 0 | 0 | G5 field_unclassified (no fetch) |
| dynamo-vllm | disagg | single_turn | 68 | 496 | 0 | 0 | 496 | 0 | 0 | G5 router_unsupported (no fetch) |
| vllm | agg | agentic_traces | 158 | 367 | 120 | 314 | 47 | 0 | 47 | fetched; scored by the harness |
| dynamo-sglang | disagg | single_turn | 230 | 318 | 0 | 53 | 265 | 0 | 0 | G5 router_unsupported, field_unclassified (no fetch) |
| trt | agg | single_turn | 1338 | 315 | 0 | 12 | 303 | 0 | 0 | G5 engine_unsupported (no fetch) |
| atom | agg | single_turn | 106 | 289 | 289 | 66 | 223 | 0 | 0 | G5 engine_unsupported (no fetch) |
| dynamo-trt | disagg | single_turn | 267 | 247 | 0 | 0 | 247 | 0 | 0 | G5 router_unsupported, engine_unsupported (no fetch) |
| mori-sglang | disagg | single_turn | 82 | 135 | 135 | 0 | 135 | 0 | 0 | G5 field_unclassified (no fetch) |
| dynamo-sglang | agg | agentic_traces | 58 | 103 | 0 | 87 | 16 | 0 | 0 | G5 router_unsupported, field_unclassified (no fetch) |
| dynamo-sglang | disagg | agentic_traces | 53 | 100 | 0 | 95 | 5 | 0 | 0 | G5 router_unsupported, field_unclassified (no fetch) |
| atom | agg | agentic_traces | 31 | 72 | 72 | 72 | 0 | 0 | 0 | G5 engine_unsupported (no fetch) |
| vllm-disagg | disagg | single_turn | 14 | 68 | 68 | 0 | 68 | 0 | 0 | fetched; disaggregated: topology reasons, else topology_unsupported |
| dynamo-vllm | disagg | agentic_traces | 29 | 60 | 0 | 54 | 6 | 0 | 0 | G5 router_unsupported (no fetch) |
| dynamo-vllm | agg | agentic_traces | 47 | 56 | 0 | 56 | 0 | 0 | 0 | G5 router_unsupported (no fetch) |
| mooncake-atom | disagg | single_turn | 9 | 54 | 54 | 0 | 54 | 0 | 0 | G5 engine_unsupported (no fetch) |
| dynamo-trt | disagg | agentic_traces | 10 | 42 | 0 | 36 | 6 | 0 | 0 | G5 router_unsupported, engine_unsupported (no fetch) |
| trt | agg | agentic_traces | 7 | 29 | 0 | 7 | 22 | 0 | 0 | G5 engine_unsupported (no fetch) |
| teacup | agg | single_turn | 4 | 28 | 0 | 28 | 0 | 0 | 0 | G5 engine_unsupported (no fetch) |
| atom-disagg | disagg | single_turn | 2 | 20 | 20 | 0 | 20 | 0 | 0 | G5 engine_unsupported (no fetch) |
| rubin-july | agg | single_turn | 1 | 14 | 0 | 14 | 0 | 0 | 0 | G5 engine_unsupported (no fetch) |
| vllm | disagg | agentic_traces | 4 | 12 | 9 | 12 | 0 | 0 | 0 | fetched; disaggregated: topology reasons, else topology_unsupported |
| tokenspeed | agg | agentic_traces | 2 | 9 | 0 | 9 | 0 | 0 | 0 | G5 engine_unsupported (no fetch) |
| mori-sglang | disagg | agentic_traces | 7 | 8 | 8 | 8 | 0 | 0 | 0 | G5 field_unclassified (no fetch) |
| dynamo-trt | agg | agentic_traces | 2 | 7 | 0 | 7 | 0 | 0 | 0 | G5 router_unsupported, engine_unsupported (no fetch) |
| trt | disagg | agentic_traces | 2 | 6 | 0 | 0 | 6 | 0 | 0 | G5 engine_unsupported (no fetch) |
| vllm-disagg | disagg | agentic_traces | 1 | 6 | 6 | 6 | 0 | 0 | 0 | fetched; disaggregated: topology reasons, else topology_unsupported |
| llmd-vllm | disagg | agentic_traces | 1 | 5 | 5 | 5 | 0 | 0 | 0 | fetched; disaggregated: topology reasons, else topology_unsupported |
| llmd-vllm | disagg | single_turn | 2 | 5 | 0 | 0 | 5 | 0 | 0 | fetched; disaggregated: topology reasons, else topology_unsupported |
| tilert | disagg | agentic_traces | 6 | 3 | 2 | 2 | 1 | 0 | 0 | G5 router_unsupported, engine_unsupported (no fetch) |
| tilert | disagg | single_turn | 7 | 3 | 1 | 0 | 3 | 0 | 0 | G5 router_unsupported, engine_unsupported (no fetch) |

Series in availability: 7185. Window rows: 6306. Rows with a ledger unit: 4580.

Reading the columns. "AMD or TPU rows" are out of scope for M2 to M4 (plan v64); they are counted in every row total and listed here apart from the in-scope ones. "Rows with no ledger unit" are rows the ledger's source revision (`db-dump/2026-09-28`) does not hold: newer than that dump, or recorded after it. The harness scores a row only through its ledger unit, so those rows are not in any coverage count until a ledger release holds them (1720 of 6306 rows today). "Units" is the number of rows that have a unit.

## Findings

**(a) Engines other than vLLM are G5, not absent.** `engines.py` names 16 labels. Only the vLLM labels fetch artifacts and are scored. Every other label's points are G5 without a fetch, with every reason true of them: `engine_unsupported` (trt, atom, tilert, mooncake-atom, atom-disagg), `field_unclassified` (sglang, mori-sglang, until blis-sglang publishes a field list), and `router_unsupported` (dynamo-*, tilert). The published snapshot and the baseline above hold none of them, because they hold only the snapshot's units, which are all vLLM. The nightly's pull lists them. Three labels, `teacup`, `rubin-july` and `tokenspeed`, were not named in the table and stopped the pull; they are now named, with no BLIS engine, and are `engine_unsupported`. The 2026-11-09 pull had aborted on `rubin-july` and `teacup` for that reason.

**(b) vllm-disagg and llmd-vllm.** All 74 `vllm-disagg` rows are on mi355x: out of scope, not a candidate in M2 to M4. `llmd-vllm` has 10 rows: 5 gb200 single-turn dsv4 (in scope, August to October) and 5 tpuv7 agentic qwen3.5 (out of scope). Each in-scope `llmd-vllm` row records one prefill and one decode pool: `prefill_num_workers`, `decode_num_workers`, `prefill_tp`/`ep`/`dp_attention`, `decode_tp`/`ep`/`dp_attention`, and the GPU counts of each pool (for example 1 prefill worker of 1 GPU, ep 8 with data-parallel attention, against 1 decode worker of the same shape; or 5 decode workers of tp 8, ep 8). The row's `metrics.router_name` is `llm-d-router` on all 5. The image is `quay.io/rh-ee-imarkov/llm-d-nokube-vllm:vllm0.26@sha256:...`, a private build. What is missing is the run's own record: none of the 5 gb200 runs has a server log or launch configuration in the pull (`files: {}`), so the engine settings (batch limits, memory fraction, connector options) are unrecorded. Under X19 the scenario would state only the topology and the model, and leave every engine setting to the engine; the point would be `server_log_missing`, a G5 `value_not_recorded`, before it was ever graded, under the harness's rule that a run without its log is not scored.

What BLIS can state. `contracts/spec/deployment` in blis-substrate v0.13.0 already has `Pools` with roles `colocated`, `prefill` and `decode`, a node count and a parallelism layout per pool, per-pool engine settings, and `PDTransfer{Connector}`. The scorer writes one colocated pool (`settings.build`); it cannot write several (`score.py`: "the harness builds one colocated pool and cannot write several engines as a scenario"), so every disaggregated row is G5 `topology_unsupported` after its topology fields are decided. blis-vllm `v0.32.0-blis.2` classifies `kv_transfer_config.kv_connector` and `kv_role` as modelled (NIXL golden traces) and `kv_connector_extra_config`, `kv_load_failure_policy` and `kv_connector_module_path` as not modelled (blis-vllm#89, #66). The placement and the NIXL connector for P/D are inference-sim PR 2 and blis-vllm PR 5, which are not in the pins of v0.16.0, so a pooled scenario cannot be run faithfully against the simulator this baseline uses.

Not built. A generated disaggregated scenario needs (1) the writer to emit two pools from the row's per-pool fields, (2) the run's connector and role from a log or launch configuration, and (3) a simulator that places the pools. Of the three, (2) is absent for every in-scope `llmd-vllm` and `vllm`-disagg row today, and (3) is unreleased. A test that the scenario states exactly the recorded topology can be written against the fake simulator the scorer's tests use, but it would not show a faithful run, and the brief asks for both. I propose to build it in the PR that follows inference-sim PR 2 and blis-vllm PR 5, with the `llmd-vllm` rows as the first target.

**Disaggregated vLLM-family series, in scope.** From the 6306 rows (rows, not series):

| Label | Rows | Chips | Router recorded by the row | Server logs in the pull |
|---|---|---|---|---|
| dynamo-vllm | 612 (496 single-turn, 116 agentic) | gb200 168, gb300 181, b300 147, b200 105, vr200 11 | `dynamo-router` on 204, none on 408 | 9 of the 38 dynamo-vllm runs tried (all b300); none on gb200, gb300, b200 |
| vllm-disagg | 74 | mi355x 74 | `vllm-router` on 16 | 0 of 68 (HTTP 404; dated 2026-05-27 to 2026-08-04) |
| llmd-vllm | 10 | gb200 5, tpuv7 5 | `llm-d-router` on 5 | 0 of 5 |
| vllm, `is_multinode` | 65 (agentic kimik3, kimik3.1) | h200 35, b200 11, gb200 10, tpuv7 9 | `vllm-router` on 12 | not fetched (not in the baseline set) |

The 65 multinode `vllm` rows are the 65 points the published snapshot lists as `blis_refused:disaggregated_or_multinode` (35 kimik3 on h200, 11 and 10 kimik3.1 on b200 and gb200, 9 kimik3 on tpuv7). The other 5 `blis_refused` are `insufficient_memory`. In this harness those rows are not refusals by the simulator: a disaggregated or multinode row is decided by its topology fields and ends as G5 `topology_unsupported` (`score.py`), and the scorer's `blis_refused` is a run fault for a scenario the simulator rejects. `vr200` is not in the catalog (blis-substrate v0.13.0 `hardware/` holds a100, b200, b300, gb200-nvl72, gb300, h100, h200, l40s); nor are the mi* and tpu parts. `gb200` maps to `gb200-nvl72`.

**(2) Dynamo's router.** `dynamo-vllm` is 612 in-scope rows behind Dynamo's frontend. The harness marks them `router_unsupported` by label (`engines.py`), so none is scored as if llm-d had routed it. For the maintainer's decision on a named "router differs" substitution, the evidence: the routing policy is chosen per recipe, not per label. In InferenceX's `srt-slurm-recipes` the frontend block sets `router-mode: kv` (Dynamo's KV-aware router) in `dsv41flash/vllm/gb300-fp4/agentx/{agg,disagg}-variants.yaml` and `minimaxm31flash/vllm/{gb200,gb300}-fp4/agentx/*.yaml`, and `router-mode: "least-loaded"` in `kimik3.1/vllm/gb300-fp4/agentx/*.yaml`, each with `router-session-affinity-ttl-secs` (1 second for the least-loaded recipe, 14400 for a kv one). I could not locate the single-turn dynamo-vllm recipes (minimaxm2.5, minimaxm3: 445 of the 612 rows) with the code search; their server logs show the workers, not the frontend flags (the b300 minimaxm3 log: Dynamo 1.3.0.dev20260710, `NixlPullConnector`, `kv_role=kv_both`, decode worker with `kv_events_config` disabled, `--stream-interval=32` propagated to the frontend). So whether a Dynamo run matches an llm-d policy is knowable only per recipe: `least-loaded` corresponds to a load-based scorer, `kv` to a prefix-cache-aware one, and session affinity has no counterpart in the llm-d router BLIS hosts that I can point to. This is not a recommendation to add the substitution. If the maintainer decides to, the substitution would be named per recipe from the recorded `router-mode`, not per label.

**(c) Single-node-expressible disaggregated or multinode rows.** Of the in-scope disaggregated or multinode rows, 357 have a prefill and a decode pool that together use 8 GPUs or fewer, so they fit one node: 222 `dynamo-vllm`, 120 `dynamo-sglang`, 9 `dynamo-trt`, 6 `trt`. None is `llmd-vllm` or plain `vllm`. The `dynamo-vllm` ones are held back by the router, not by the shape. They still need two pools, since a disaggregated deployment is two engines whatever the node count; "single node" removes the multi-node placement question, not the P/D one.

**(d) Agentic traces.** 623 series, 1624 rows in the window (vllm 367 plus 12 disaggregated, sglang 739, dynamo-* 368, atom 72, others). Every agentic row that has a ledger unit is in the pull; the vLLM ones are fetched and scored like the rest. The 47 vLLM agentic units in the baseline set are all G5, primary reason `value_not_recorded` 35 (server log missing), the CPU-offload bytes of the KV connector 7, and `field_not_modelled:cpu_offload_gb` 5. The corpora are fetched and verified, so agentic points are not dropped before grading.

**(e) Newer data and builds.** The nightly pulls rows by `date` (the run's date), not `curve_date`, in a 180-day window ending today (`api.in_window`); it places each row through the ledger. A row newer than the ledger's source revision has no unit, is listed as `unlisted` and counted in `left_out_records` (1643 in the baseline's pull, 1720 today). So new measurements are not scored until a ledger release holds them. New rows that the ledger holds are picked up automatically. The 45 rows dated 2026-11-10 (38 when first checked) are all past the ledger revision. Builds: 1035 of the baseline's 1734 points run a nightly or custom image (599 outside the commit-distance bound with a banner, 456 labelled by tag, 291 custom, 35 with a commit that does not resolve); they are G4 `nightly_or_custom` once scored, not lost. `build_unparseable` and `code_not_visible` are in design §11.4's list but the scorer emits neither today, so no share is lost to them.

**(f) Fixes for the other reasons.** From the baseline's 1714 G5 points (546 AMD, out of scope):

- `value_not_recorded:cluster.gpus_per_node` (858 points in the first baseline, 645 after the stability rule was relaxed to "the same size in every recorded version"): b200 (406) and h200 (239) stay unstable because a record has runners outside every cluster and, for b200, the label is absent from the newest runners file. Fixing the table needs InferenceX's `runners.yaml` to cover those runners; 20 points are blocked by this alone.
- `field_not_modelled:*` (723 primary): blis-vllm models the field, or gives it a rule. The largest: `max_cudagraph_capture_size` 996 points, `stream_interval` 771, `kv_cache_dtype` 752, `language_model_only` 607, `enable_expert_parallel` 422, `api_server_count` 131.
- `not_in_catalog` (82 primary, 561 with others): `eagle3` drafter (296 in scope), `dspark` (5), models.
- `server_log_missing` and `artifact_unmatched` (here `value_not_recorded`, 35 plus 25 `no_recipe_fingerprint`): the run's record is not in the API; nothing in the harness fixes it.
- `value_conflict:kv_transfer_config.engine_id` (1): two sources disagree.
- `unclassified_arg`, `setting_not_modelled`, `hardware_no_coefficients` and the other schema-2 names no longer exist: the v3 scorer reports `field_not_modelled`, `field_not_in_release`, `not_in_catalog` and `value_not_recorded`.

## Proposed scope

M2: (1) the unevaluated G1 conditions (#53), when inference-sim's builder says what the Result carries; (2) the `field_not_modelled` list above, in blis-vllm, ranked by the unlock table in `baseline-v0.16.0/table.md`; (3) done: the node-size stability rule is relaxed; (4) done: `teacup`, `rubin-july` and `tokenspeed` are named in `engines.FRAMEWORKS`. M2 or the next release, once inference-sim PR 2 and blis-vllm PR 5 are pinned: the disaggregated scenario writer for `llmd-vllm` gb200 (5 rows) and the multinode `vllm` rows. M3: sglang (blis-sglang), which is 2037 + 207 series and 1733 window rows. Not planned: AMD, TPU, vr200 (no catalog entry), trt, atom, tilert (no BLIS engine), dynamo-* (router; the substitution is the maintainer's call).
