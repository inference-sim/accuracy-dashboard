# DeepSeek-V4.1-Flash on H200 under vLLM v0.33.0: sixteen rows newer than the ledger

Contents: [What the rows are](#what-the-rows-are) · [How they are pinned and split](#how-they-are-pinned-and-split) · [Result at the final stack pins](#result-at-the-final-stack-pins) · [What it shows and does not show](#what-it-shows-and-does-not-show) · [Inputs](#inputs) · [Grade](#grade) · [How to reproduce](#how-to-reproduce) · [What this does not show](#what-this-does-not-show)

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

The units are the substrate's (`catalog/ledger/units/inferencex.jsonl.gz`, made by its ingest): the dashboard makes no unit, no role key and no ledger report (design 2.2, COV-2). The substrate commit is pinned in [pins.env](pins.env) (`BLIS_SUBSTRATE_COMMIT`: the commit of blis-substrate release v0.14.0). The records of a run are fetched, and refused if any differs from its pin, by `go run ./ledger/cmd/ledger supplement-records -out records.json catalog/ledger`; the file is an input for a run and is never committed. The unit ids are in [units.txt](units.txt) (derived values); they are the same hashes the dashboard's own earlier supplementary units had. **At published pins these sixteen units have no role** until the substrate publishes the seed and the anchor lists, and scoring uses the published anchor lists only (COV-2), so they score 0 of 16 there. The 16 of 16 figures below come from scoring the units named on the command line; they are evidence of the pipeline on the development split, not a result at published pins.

**Split.** Every point of a series takes the series's split, by the same rule as all others (`split.py`, salt `blis-dev-split-2`). The series `["dsv41flash","h200","fp4","vllm","mtp",false]` hashes to **validation**, so all sixteen are development points. They are not prospective: `FREEZE_DATE` is 2026-11-09 and a point is prospective only when measured after it; these were measured on that date. The committed `docs/m2/series-split.json` already lists the same row ids under that series as validation. The assignment is in [splits.json](splits.json). No row of a test or prospective series was opened in making this page: the only row looked at before its split was known was one of these sixteen, and the other newer rows of the API were selected by id.

## Result at the final stack pins

**Development split only (the sixteen are validation-split points; no test or prospective point is in the pull or was read). In-sample. Not a result at published pins: see the next paragraph.** The committed scorer, the engine's own `fields.json` and a simulator built from a commit of inference-sim: no scratch field list, no scratch scorer, no uncommitted change. [contract/](contract/) is the run, [splits.json](splits.json) its splits and [table.md](table.md) its table.

**At published pins these rows score 0 of 16.** The sixteen units are the substrate's and have no role until the release publishes the seed and the anchor lists; scoring uses the published anchor lists only (COV-2). The run below scored the units named on the command line (`--units`), so it is a development-split rescoring and not an anchor result.

**16 of 16 scored, 0 refused, 0 failed, all G4.** Over the sixteen points: **TTFT MAPE 34.8 %, TPOT MAPE 23.5 %** (TTFT shape 31.0 %, TPOT shape 24.0 %, over the 14 points with a shape).

| GPUs | Clients | TTFT measured (ms) | TTFT predicted | Error % | TPOT measured (ms) | TPOT predicted | Error % |
|---|---|---|---|---|---|---|---|
| 4 | 1 | 452.8 | 506.8 | +12 | 2.96 | 3.10 | +5 |
| 4 | 2 | 413.4 | 471.1 | +14 | 3.26 | 3.48 | +7 |
| 4 | 4 | 387.0 | 427.4 | +10 | 3.43 | 3.70 | +8 |
| 4 | 8 | 388.9 | 446.0 | +15 | 4.14 | 4.96 | +20 |
| 4 | 16 | 493.7 | 620.7 | +26 | 6.04 | 7.83 | +30 |
| 4 | 32 | 446.5 | 833.4 | +87 | 8.85 | 13.76 | +55 |
| 4 | 64 | 1116.2 | 1861.4 | +67 | 19.46 | 31.19 | +60 |
| 4 | 128 | 382024.9 | 993737.4 | +160 | 34.54 | 74.97 | +117 |
| 8 | 1 | 391.8 | 390.6 | -0 | 2.71 | 2.55 | -6 |
| 8 | 2 | 342.9 | 346.6 | +1 | 2.94 | 2.74 | -7 |
| 8 | 4 | 325.0 | 311.8 | -4 | 3.08 | 3.00 | -3 |
| 8 | 8 | 314.4 | 324.6 | +3 | 3.65 | 3.55 | -3 |
| 8 | 16 | 361.5 | 398.0 | +10 | 5.26 | 5.08 | -3 |
| 8 | 32 | 359.0 | 522.3 | +45 | 7.94 | 8.77 | +10 |
| 8 | 64 | 468.6 | 780.7 | +67 | 16.89 | 18.95 | +12 |
| 8 | 128 | 5025.1 | 3229.5 | -36 | 44.02 | 56.96 | +29 |

## What it shows and does not show

- Up to 16 clients on 8 GPUs both figures are within 10 % of the run. Error grows with load on both shapes (TTFT +45 % and +67 % at 32 and 64 clients on 8 GPUs; TPOT +55 % to +117 % at 32 to 128 clients on 4 GPUs). The 128-client rows are saturated queues (382 s measured on 4 GPUs) and say little. The twelve points up to 32 clients read TTFT MAPE 19.0 % and TPOT 13.0 %; the four above, 82.3 % and 54.7 %.
- The error comes down from 75.4 % (TTFT) and 38.1 % (TPOT) in the dry run at older pins (the dry run is not kept: it needed scratch files). That change mixes the decoder replay (layers after the last KV layer priced on each request's last 128 tokens), the admission queue (`Service` and `Delay` of the kernel's admission demand) and the move of the substrate and the field list, and the run cannot say how much each gave. None is fitted to these rows.
- The Rust front end is a queue of one server and one thread in this build, which is what the engine states in its plan, though the Rust front end is multithreaded. At 64 clients on 8 GPUs, sixteen render threads gave a mean TTFT of 807.5 ms against 780.7 ms with one in a hand run at the earlier pins; the queue does not explain the error at 32 and 64 clients. That row was not scored.
- The grade is G4 for the reason under [Grade](#grade); nothing else changed it.

## Inputs

- Harness commit: `0e9627e219c207593de5bc55d997cf3dca707d64` (the contract's `provenance.json`).
- Simulator: inference-sim `81a46ba3e0b14ba828eaa46d21191d03dd17376f`, the head of its combined pull request; built by `harness/run.sh` from a clean clone of that commit.
- Catalog and registry: blis-substrate `v0.14.0` (commit `965b05834c47882bc0f9f1a960c90327a756ef3d`), passed as the release tag for `--catalog-release` and `--registry-release`.
- Field list: blis-vllm `33455e4cb2d52b9fc9fa6cfb36cf5c1f5e509f5b` `fields.json`, sha256 `7432f9f82bf551027233a3aae2387fc585408d77d1c44941d037217aed890f1a`.
- Pull: `pull_manifest_sha256` `e650d510ccde4b9027c194d9ca52bd40a03a8b7846f81b8e5a21fb615b052bac` (in `contract/provenance.json`).

## Grade

Each point is **G4**, by the engine-release difference, which is named on the point: `other_release` with detail `0.33.0, scored on 0.32.0`, and `ported_functions_unpublished` (the engine publishes no list of the functions it ports, so a changed one cannot be ruled out). M2 accepts G4 for InferenceX points: no InferenceX data on the simulator's release exists, and the grading system may be revisited. A matched point could be G1 or G2 only at v0.32.0.

The G1 conditions that are not evaluated are named as `unevaluated` substitutions: `coefficient_range` and `kernel_hash` on these points (`value_class` and `resolved_differs` were evaluated, and `value_class` is false for `max_model_len`, `num_speculative_tokens`, `enable_adaptive_verification` and `tensor_parallel_size`, which are outside every value class the evidence covers).

## How to reproduce

```
# 1. freeze (needs GH_TOKEN; artifacts last until about 2027-02-07)
(cd SUBSTRATE && go run ./ledger/cmd/ledger supplement-records -out ../records.json catalog/ledger)   # SUBSTRATE at v0.14.0
python3 orchestrator/baseline/freeze_rows.py --ledger SUBSTRATE/catalog/ledger --records records.json \
  --out PULL --cache CACHE --units-out UNITS
# 2. score, from a clean checkout of the harness commit in contract/provenance.json
bash harness/run.sh --sim 81a46ba3e0b14ba828eaa46d21191d03dd17376f \
  --units docs/m2/h200-v033/units.txt --pull PULL --out OUT \
  --catalog SUBSTRATE/catalog --registry SUBSTRATE/registry --corpus-dir CORPORA \
  --fields FIELDS.json --catalog-release v0.14.0 --registry-release v0.14.0
# 3. splits and the table
python3 orchestrator/baseline/split.py splits --pull PULL --out docs/m2/h200-v033/splits.json
python3 orchestrator/baseline/compare.py run --dir docs/m2/h200-v033/contract --sample in_sample --out docs/m2/h200-v033/table
```

`FIELDS.json` is blis-vllm `33455e4cb2d52b9fc9fa6cfb36cf5c1f5e509f5b`'s `fields.json`; the corpora are fetched as the baseline's README says. Cost: the freeze is about a minute for sixteen rows (artifacts cached); the scoring took 27 minutes with one worker and 2 GB of memory (one replay of an hour-long trace per point, simulated; the machine was shared with the four other runs).

## What this does not show

- Nothing here is held-out: the points are the development split's validation portion and the figures are labelled so.
- The field list is the engine's for vLLM v0.32.0, and the rows ran v0.33.0; the release difference is named on every point and makes each G4.
- The units are the substrate's and hold no role until the seed and lists are published, so nothing here is an anchor and the published scoring of these rows is 0 of 16.
