# DeepSeek-V4.1-Flash on H200 under vLLM v0.33.0: sixteen rows newer than the ledger

Contents: [What the rows are](#what-the-rows-are) · [How they are pinned and split](#how-they-are-pinned-and-split) · [Result of the scorer as published](#result-of-the-scorer-as-published) · [What BLIS refuses, by name](#what-blis-refuses-by-name) · [Dry run: the rows with the three refusals set aside](#dry-run-the-rows-with-the-three-refusals-set-aside) · [Grade](#grade) · [How to reproduce](#how-to-reproduce) · [What this does not show](#what-this-does-not-show)

These are the first InferenceX rows of the model, chip and workload family the team runs. They were measured on 2026-11-09, after the baseline's ledger source revision (`db-dump/2026-09-28`), so the ledger holds no unit for them and the baseline's frozen pull does not hold them. They are scored here from a pull of their own. The baseline pull and its 1734 points are not touched.

## What the rows are

| | |
|---|---|
| Rows | InferenceX API ids 447774 to 447789, pinned in blis-substrate `catalog/ledger/sources.yaml` (source `inferencex`, supplement `h200-dsv41flash-vllm-v0-33-0`: record id and content SHA-256 of each); no record is committed here (X12) |
| Run | GitHub Actions run 42341901521 of SemiAnalysisAI/InferenceX, attempt 1, 2026-11-09 |
| Model, chip, engine | `dsv41flash` (DeepSeek-V4.1-Flash), `h200`, vLLM, image `vllm/vllm-openai:v0.33.0@sha256:d825baf9ce4b1b6bfc5ecc7b79880c7e6748c65a72d697ce3d47607aafa84c6e` |
| Workload | `agentic_traces`: aiperf replay of the AgentX trace corpus (`agentx-mvp-uncapped`), 3600 s, concurrency 1, 2, 4, 8, 16, 32, 64 and 128 |
| Deployment | one node, no data parallelism, expert parallel 1. **Two shapes: 4 GPUs (tensor parallel 4; rows 447774 to 447781) and 8 GPUs (tensor parallel 8; rows 447782 to 447789).** Not 8 and 16 |
| Speculation | the row says `mtp`; the launch configuration says method `dspark`, 5 speculative tokens, `rejection_sample_method` `synthetic` with `synthetic_acceptance_length` 3.51. The server log's realised mean acceptance length is 3.511. The scenario pins 3.51 (`acceptance.simulated: recorded`) |
| Precision | `fp4` |
| Recipe fingerprints | `7eb22e94...` (4 GPUs), `47e4423b...` (8 GPUs) |

## How they are pinned and split

Pinned by blis-substrate (`catalog/ledger/sources.yaml`: each record's id and content SHA-256) and by the frozen pull's `pull_manifest_sha256` `9e9588ad78ee04870416a0992c2e8eaba865fbf98e7f9b806bfef67eaca32a36` (in `contract/provenance.json`). The artifacts expire 90 days after the run (about 2027-02-07), so a pull can be made again only until then; the pull itself is not committed (it holds the server logs and client exports).

The units are the substrate's (`catalog/ledger/units/inferencex.jsonl.gz`, made by its ingest): the dashboard makes no unit, no role key and no ledger report (design 2.2, COV-2). The substrate commit is pinned in [pins.env](pins.env) (`BLIS_SUBSTRATE_COMMIT`, empty until the final substrate commit is filled in). The records of a run are fetched, and refused if any differs from its pin, by `go run ./ledger/cmd/ledger supplement-records -out records.json catalog/ledger`; the file is an input for a run and is never committed. The unit ids are in [units.txt](units.txt) (derived values); they are the same hashes the dashboard's own earlier supplementary units had. **At published pins these sixteen units have no role** until the substrate publishes the seed and the anchor lists, and scoring uses the published anchor lists only (COV-2), so they score 0 of 16 there. The figures below that say 16 of 16 came from a scratch build with the units forced in and placeholder proofs; they are evidence of the pipeline, not a result at published pins.

**Split.** Every point of a series takes the series's split, by the same rule as all others (`split.py`, salt `blis-dev-split-2`). The series `["dsv41flash","h200","fp4","vllm","mtp",false]` hashes to **validation**, so all sixteen are development points. They are not prospective: `FREEZE_DATE` is 2026-11-09 and a point is prospective only when measured after it; these were measured on that date. The committed `docs/m2/series-split.json` already lists the same row ids under that series as validation. The assignment is in [splits.json](splits.json). No row of a test or prospective series was opened in making this page: the only row looked at before its split was known was one of these sixteen, and the other newer rows of the API were selected by id.

## Result of the scorer as published

Command: `harness/run.sh` with the inputs of [prefill/decode coverage](../pd-coverage.md) (inference-sim `c97c497b`, blis-substrate `6faaccf8`, field list of blis-vllm `28deab08`) over this pull and [units.txt](units.txt); see [How to reproduce](#how-to-reproduce).

**0 of 16 are scored. All 16 are G5.** [contract/](contract/) is the run; [table.md](table.md) is its table (all development points). Each point has the same three reasons:

## What BLIS refuses, by name

| Reason | Field | Where it comes from | What clears it |
|---|---|---|---|
| `field_not_in_release:env.PYTHONUNBUFFERED` | the environment variable the recipe sets | the engine's field list at `28deab08` does not list it | classify it (a Python interpreter setting; not read by vLLM) in blis-vllm |
| `field_not_modelled:env.VLLM_USE_RUST_FRONTEND` | the Rust API frontend | blis-vllm#85, status `not_modelled`, rule `none` | model it, or prove it inert |
| `field_not_modelled:speculative_config.rejection_sample_method` | `synthetic` | blis-vllm#106, status `not_modelled`, rule `none` | model it (the synthetic acceptance length fixes the acceptance; the scorer already pins 3.51) |

The first reason by order is `field_not_modelled:env.VLLM_USE_RUST_FRONTEND`; all three are in `not_scored.jsonl` under `g5_reasons`. Two further facts surfaced when the three were set aside (next section); they are not yet refusals of the published run because the gate stops first:

1. **The engine itself refuses `rejection_sample_method`.** With the field list opened, the engine's own error is `speculative.rejection_sample_method (vLLM's speculative_config.rejection_sample_method) is not modelled: this engine and the cost model read no such setting, so a value other than vLLM's default would be dropped (blis-vllm#106)`. Marking the field inert in the list is therefore not enough; the key must also not reach the scenario, or the engine must read it.
2. **The scorer maps `env.VLLM_USE_RUST_FRONTEND` to `engine.frontend`, and the simulator at this pin refuses that key**: `engine key "frontend" is vLLM's environment variable VLLM_USE_RUST_FRONTEND: write env: {VLLM_USE_RUST_FRONTEND: "1"}`. When blis-vllm#85 lands, `settings.py` must write the variable under `engine.env`. This is not changed here: the field list gates it, and the value form the engine will accept is the engine's to say.

## Dry run: the rows with the three refusals set aside

**Evidence only. Not a result and not a grade of record.** The scratch copies are not committed: (a) a copy of `fields.json` in which `env.PYTHONUNBUFFERED` is added and `env.VLLM_USE_RUST_FRONTEND` and `speculative_config.rejection_sample_method` are `proven_inert` with the placeholder proof `{"proof": "placeholder"}`; (b) a copy of this repository's `settings.py` without the two mappings (`engine.frontend`, `engine.speculative.rejection_sample_method`), so the two values are recorded on the point and not stated in the scenario. The 8 GPU rows and the 4 GPU rows then all reach the simulator and score (16 of 16, all G4). The harness commit in a dry run's provenance is the committed one while the code was the scratch one; that is why the run is not committed.

Accuracy over the sixteen points, all development (validation) points: **TTFT MAPE 204.5 %, TPOT MAPE 36.6 %** (TTFT shape 21.2 %, TPOT shape 40.2 %, over the 14 points with a shape). Per point (times in ms; the error is predicted over measured, in percent):

| GPUs | Clients | TTFT measured | TTFT predicted | Error | TPOT measured | TPOT predicted | Error |
|---|---|---|---|---|---|---|---|
| 4 | 1 | 452.8 | 1322.7 | +192 | 2.96 | 3.11 | +5 |
| 4 | 2 | 413.4 | 1045.0 | +153 | 3.26 | 3.53 | +8 |
| 4 | 4 | 387.0 | 981.4 | +154 | 3.43 | 3.91 | +14 |
| 4 | 8 | 388.9 | 991.3 | +155 | 4.14 | 5.26 | +27 |
| 4 | 16 | 493.7 | 1234.7 | +150 | 6.04 | 8.41 | +39 |
| 4 | 32 | 446.5 | 1835.0 | +311 | 8.85 | 15.86 | +79 |
| 4 | 64 | 1116.2 | 3486.8 | +212 | 19.46 | 36.29 | +86 |
| 4 | 128 | 382024.9 | 1194075.9 | +213 | 34.54 | 97.50 | +182 |
| 8 | 1 | 391.8 | 1223.0 | +212 | 2.71 | 2.54 | -6 |
| 8 | 2 | 342.9 | 912.1 | +166 | 2.94 | 2.77 | -6 |
| 8 | 4 | 325.0 | 843.0 | +159 | 3.08 | 3.09 | +0 |
| 8 | 8 | 314.4 | 885.3 | +182 | 3.65 | 3.74 | +2 |
| 8 | 16 | 361.5 | 1104.3 | +205 | 5.26 | 5.47 | +4 |
| 8 | 32 | 359.0 | 1564.2 | +336 | 7.94 | 9.54 | +20 |
| 8 | 64 | 468.6 | 2342.9 | +400 | 16.89 | 22.27 | +32 |
| 8 | 128 | 5025.1 | 8661.4 | +72 | 44.02 | 76.05 | +73 |

What the table says, and what it does not:

- **TPOT** is close at low load: within 6.1 % of the run at 1 to 4 clients on 8 GPUs and within 14 % up to 4 clients on 4 GPUs. It is under-predicted by at most 6.1 % and over-predicted more as load grows (20 % and 32 % at 32 and 64 clients on 8 GPUs, 79 % and 87 % on 4 GPUs, and 73 % and 182 % at 128 clients).
- **TTFT** is over-predicted by 150 % to 400 % (2.5 to 5 times the measured value) at every concurrency up to 64, and at 128 clients on 4 GPUs both figures are of a saturated queue (382 s measured, 1194 s predicted). A bias that holds at one client, where nothing queues, is not a load effect. The replayed contexts are long (a mean input of 290k tokens at one client), so prefix reuse in the run is a candidate cause; the points also name `engram_config.cpu_offload` as left unset (`estimated`). This page does not test either.
- Sixteen points of one series are one deployment shape, not sixteen findings.

## Grade

Each point is **G4**, by the engine-release difference, which is named on the point: `other_release` with detail `0.33.0, scored on 0.32.0`, and `ported_functions_unpublished` (the engine publishes no list of the functions it ports, so a changed one cannot be ruled out). M2 accepts G4 for InferenceX points: no InferenceX data on the simulator's release exists, and the grading system may be revisited. A matched point could be G1 or G2 only at v0.32.0.

The G1 conditions that are not evaluated are named as `unevaluated` substitutions: `coefficient_range` and `kernel_hash` on these points (`value_class` and `resolved_differs` were evaluated, and `value_class` is false for `max_model_len`, `num_speculative_tokens`, `enable_adaptive_verification` and `tensor_parallel_size`, which are outside every value class the evidence covers).

## How to reproduce

```
# 1. freeze (needs GH_TOKEN; artifacts last until about 2027-02-07)
(cd SUBSTRATE && go run ./ledger/cmd/ledger supplement-records -out ../records.json catalog/ledger)   # SUBSTRATE at pins.env's commit
python3 orchestrator/baseline/freeze_rows.py --ledger SUBSTRATE/catalog/ledger --records records.json \
  --out PULL --cache CACHE --units-out UNITS
# 2. score, from a clean checkout of the harness commit in contract/provenance.json
bash harness/run.sh --sim c97c497b104a556515717599a4468352c1234d28 --sim-repo <inference-sim checkout> \
  --units docs/m2/h200-v033/units.txt --pull PULL --out OUT \
  --catalog SUBSTRATE/catalog --registry SUBSTRATE/registry --corpus-dir CORPORA \
  --fields FIELDS.json --catalog-release 6faaccf8f1a2344918241d6b54fe339de44f7345 \
  --registry-release 6faaccf8f1a2344918241d6b54fe339de44f7345
# 3. splits and the table
python3 orchestrator/baseline/split.py splits --pull PULL --out docs/m2/h200-v033/splits.json
python3 orchestrator/baseline/compare.py run --dir docs/m2/h200-v033/contract --sample in_sample --out docs/m2/h200-v033/table
```

`FIELDS.json` is blis-vllm `28deab082a2fba6762b922c64c7b5b81b7eeac8e`'s `fields.json` (sha256 `2a84767a67027a9237934038a513252d7ed65cf8ff8ee203cad8fc0a8c51cc39`); the corpora are fetched as the baseline's README says. Cost: the freeze is about a minute for sixteen rows; the published scoring is about 40 seconds; the dry run is about 16 minutes (one replay of an hour-long trace per point, one worker) and 2 GB of memory.

## What this does not show

- Nothing here is held-out: the points are the development split's validation portion and the figures are labelled so.
- The dry run is not a score of record. It sets three engine refusals aside with placeholder proofs that prove nothing; with them in place the points are G5.
- The field list is the engine's for vLLM v0.32.0, and the rows ran v0.33.0. A field v0.33.0 added and the list does not know would show as `field_not_in_release`; the published run found one (`PYTHONUNBUFFERED`, which is not a vLLM variable).
- The units are the substrate's and hold no role until the seed and lists are published, so nothing here is an anchor and the published scoring of these rows is 0 of 16.
