# DeepSeek-V4.1-Flash on H200 under vLLM v0.33.0: sixteen rows newer than the ledger

Contents: [What the rows are](#what-the-rows-are) · [How they are pinned and split](#how-they-are-pinned-and-split) · [Result of the scorer as published](#result-of-the-scorer-as-published) · [What BLIS refuses, by name](#what-blis-refuses-by-name) · [Dry run: the rows with the three refusals set aside](#dry-run-the-rows-with-the-three-refusals-set-aside) · [Dry run with the three fields classified](#dry-run-with-the-three-fields-classified) · [Grade](#grade) · [How to reproduce](#how-to-reproduce) · [What this does not show](#what-this-does-not-show)

These are the first InferenceX rows of the model, chip and workload family the team runs. They were measured on 2026-11-09, after the baseline's ledger source revision (`db-dump/2026-09-28`), so the ledger holds no unit for them and the baseline's frozen pull does not hold them. They are scored here from a pull of their own. The baseline pull and its 1734 points are not touched.

## What the rows are

| | |
|---|---|
| Rows | InferenceX API ids 447774 to 447789, committed as [rows.json](rows.json) (the API's own records, so the set can be named again) |
| Run | GitHub Actions run 42341901521 of SemiAnalysisAI/InferenceX, attempt 1, 2026-11-09 |
| Model, chip, engine | `dsv41flash` (DeepSeek-V4.1-Flash), `h200`, vLLM, image `vllm/vllm-openai:v0.33.0@sha256:d825baf9ce4b1b6bfc5ecc7b79880c7e6748c65a72d697ce3d47607aafa84c6e` |
| Workload | `agentic_traces`: aiperf replay of the AgentX trace corpus (`agentx-mvp-uncapped`), 3600 s, concurrency 1, 2, 4, 8, 16, 32, 64 and 128 |
| Deployment | one node, no data parallelism, expert parallel 1. **Two shapes: 4 GPUs (tensor parallel 4; rows 447774 to 447781) and 8 GPUs (tensor parallel 8; rows 447782 to 447789).** Not 8 and 16 |
| Speculation | the row says `mtp`; the launch configuration says method `dspark`, 5 speculative tokens, `rejection_sample_method` `synthetic` with `synthetic_acceptance_length` 3.51. The server log's realised mean acceptance length is 3.511. The scenario pins 3.51 (`acceptance.simulated: recorded`) |
| Precision | `fp4` |
| Recipe fingerprints | `7eb22e94...` (4 GPUs), `47e4423b...` (8 GPUs) |

## How they are pinned and split

Pinned by their API records ([rows.json](rows.json)) and by the frozen pull's `pull_manifest_sha256` `9e9588ad78ee04870416a0992c2e8eaba865fbf98e7f9b806bfef67eaca32a36` (in `contract/provenance.json`). The artifacts expire 90 days after the run (about 2027-02-07), so a pull can be made again only until then; the pull itself is not committed (it holds the server logs and client exports).

A unit is made for each row by `contract.unit_identity`, the function the ledger's ingest tool is checked against, and written into a supplementary ledger directory, [ledger/](ledger/), in the format the harness reads. It is not the substrate's ledger: its units have role key `00...0` and its report says `revision: supplement/rows-447774-447789`. The unit ids are in [units.txt](units.txt). When a ledger release holds these rows, its units replace these; the unit ids are the same hashes if the rows are unchanged.

**Split.** Every point of a series takes the series's split, by the same rule as all others (`split.py`, salt `blis-dev-split-2`). The series `["dsv41flash","h200","fp4","vllm","mtp",false]` hashes to **validation**, so all sixteen are development points. They are not prospective: `FREEZE_DATE` is 2026-11-09 and a point is prospective only when measured after it; these were measured on that date. The committed `docs/m2/series-split.json` already lists the same row ids under that series as validation. The assignment is in [splits.json](splits.json). No row of a test or prospective series was opened in making this page: the only row looked at before its split was known was one of these sixteen, and the other newer rows of the API were selected by id.

## Result of the scorer as published

Command: `harness/run.sh` with the inputs of [prefill/decode coverage](../pd-coverage.md) (inference-sim `780f661e`, blis-substrate `f70c6c75`, field list of blis-vllm `96ea750e`) over this pull and [units.txt](units.txt); see [How to reproduce](#how-to-reproduce).

**0 of 16 are scored. All 16 are G5.** [contract/](contract/) is the run; [table.md](table.md) is its table (all development points). Each point has the same three reasons:

## What BLIS refuses, by name

| Reason | Field | Where it comes from | What clears it |
|---|---|---|---|
| `field_not_in_release:env.PYTHONUNBUFFERED` | the environment variable the recipe sets | the engine's field list at `96ea750e` does not list it | classify it (a Python interpreter setting; not read by vLLM) in blis-vllm |
| `field_not_modelled:env.VLLM_USE_RUST_FRONTEND` | the Rust API frontend | blis-vllm#85, status `not_modelled`, rule `none` | model it, or prove it inert |
| `field_not_modelled:speculative_config.rejection_sample_method` | `synthetic` | blis-vllm#106, status `not_modelled`, rule `none` | model it (the synthetic acceptance length fixes the acceptance; the scorer already pins 3.51) |

The first reason by order is `field_not_modelled:env.VLLM_USE_RUST_FRONTEND`; all three are in `not_scored.jsonl` under `g5_reasons`. Two further facts surfaced when the three were set aside (next section); they are not yet refusals of the published run because the gate stops first:

1. **The engine itself refuses `rejection_sample_method`.** With the field list opened, the engine's own error is `speculative.rejection_sample_method (vLLM's speculative_config.rejection_sample_method) is not modelled: this engine and the cost model read no such setting, so a value other than vLLM's default would be dropped (blis-vllm#106)`. Marking the field inert in the list is therefore not enough; the key must also not reach the scenario, or the engine must read it.
2. **The scorer maps `env.VLLM_USE_RUST_FRONTEND` to `engine.frontend`, and the simulator at this pin refuses that key**: `engine key "frontend" is vLLM's environment variable VLLM_USE_RUST_FRONTEND: write env: {VLLM_USE_RUST_FRONTEND: "1"}`. When blis-vllm#85 lands, `settings.py` must write the variable under `engine.env`. This is not changed here: the field list gates it, and the value form the engine will accept is the engine's to say. *Changed afterwards: see [Dry run with the three fields classified](#dry-run-with-the-three-fields-classified).*

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

## Dry run with the three fields classified

**Evidence only, until the engine's list is published with these entries.** The three refusals are lifted in blis-vllm
by classification and not by placeholder: `env.PYTHONUNBUFFERED` is `proven_inert` (a proof that no file of vLLM's
serving process names it), `speculative_config.rejection_sample_method` is `modelled` (the run's supplied acceptance
length, 3.51), and `env.VLLM_USE_RUST_FRONTEND` is `modelled` (the engine prices admission at the Rust front end's
per-token rate). The page [docs/h200-v033-fields.md](https://github.com/inference-sim/blis-vllm/blob/m2/15-h200-v033-fields/docs/h200-v033-fields.md)
of blis-vllm's branch `m2/15-h200-v033-fields` says what each does in vLLM v0.32.0 and what stays an assumption. The scorer
change is two things: the Rust front end is written as `env: {VLLM_USE_RUST_FRONTEND: "1"}`, the form the engine takes (the
earlier mapping, `engine.frontend`, is refused by the simulator), and a synthetic run states its acceptance length in the
engine block as well as in the replay, because the engine accepts the method only beside one.

Command: as in [How to reproduce](#how-to-reproduce), with `--fields` the `fields.json` of that branch (sha256
`474e99d960638604b169417a9b7dc0fc4abb7c47b9b1ea5a35e69338e84df573`), harness commit `c474b95c1a86e9763b91ab9cec1987386233d8a1`,
simulator `780f661e` (blis-vllm `96ea750e` inside it, which already reads the Rust variable and a synthetic length). No scratch
file is used. **16 of 16 are scored, 0 refused, 0 failed, all G4** (the engine release, as before). Over the sixteen development
(validation) points: **TTFT MAPE 75.4 %, TPOT MAPE 38.1 %** (TTFT shape 31.7 %, TPOT shape 42.0 %, over the 14 points with a shape).
Errors are predicted over measured, in percent; "before" is the dry run above.

| GPUs | Clients | TTFT measured | TTFT predicted | Error | Error before | TPOT measured | TPOT predicted | Error | Error before |
|---|---|---|---|---|---|---|---|---|---|
| 4 | 1 | 452.8 | 658.2 | +45 | +192 | 2.96 | 3.10 | +5 | +5 |
| 4 | 2 | 413.4 | 602.3 | +46 | +153 | 3.26 | 3.50 | +7 | +8 |
| 4 | 4 | 387.0 | 522.4 | +35 | +154 | 3.43 | 3.80 | +11 | +14 |
| 4 | 8 | 388.9 | 598.8 | +54 | +155 | 4.14 | 5.15 | +24 | +27 |
| 4 | 16 | 493.7 | 865.3 | +75 | +150 | 6.04 | 8.50 | +41 | +39 |
| 4 | 32 | 446.5 | 1116.2 | +150 | +311 | 8.85 | 16.30 | +84 | +79 |
| 4 | 64 | 1116.2 | 2673.3 | +139 | +212 | 19.46 | 36.75 | +89 | +86 |
| 4 | 128 | 382024.9 | 1194036.6 | +213 | +213 | 34.54 | 97.67 | +183 | +182 |
| 8 | 1 | 391.8 | 530.7 | +35 | +212 | 2.71 | 2.55 | -6 | -6 |
| 8 | 2 | 342.9 | 447.4 | +30 | +166 | 2.94 | 2.76 | -6 | -6 |
| 8 | 4 | 325.0 | 402.2 | +24 | +159 | 3.08 | 3.17 | +3 | +0 |
| 8 | 8 | 314.4 | 419.0 | +33 | +182 | 3.65 | 3.79 | +4 | +2 |
| 8 | 16 | 361.5 | 570.0 | +58 | +205 | 5.26 | 5.65 | +7 | +4 |
| 8 | 32 | 359.0 | 761.0 | +112 | +336 | 7.94 | 9.99 | +26 | +20 |
| 8 | 64 | 468.6 | 1063.8 | +127 | +400 | 16.89 | 22.91 | +36 | +32 |
| 8 | 128 | 5025.1 | 6504.0 | +29 | +72 | 44.02 | 78.23 | +78 | +73 |

What changed, and what it does not show:

- **TTFT** fell from 204.5 % to 75.4 %. The cause is the Rust front end: with the variable unstated the engine admitted a prompt at
  the Python server's per-token rate (2.67 us), and the replayed prompts are long (a mean of 290k tokens at one client), so each
  request paid about 0.7 s of admission the run did not (774 ms against 77 ms at 290k tokens). At one client on 8 GPUs the
  prediction fell from 1223 ms to 531 ms, 692 ms. The first dry run left the variable out; this one states it. The Rust rate is the
  registry's, method `assumed` (a vendor speedup applied to the Python rate), and each point names it among its coefficient methods
  (`coefficient_method:cost-model-host-overheads/host_admission_per_token_rust_frontend`). It is not a measurement, so the gain
  is a consequence of an assumed rate and should not be read as the model having been fitted to this run.
- **TPOT** is nearly unchanged (36.6 % to 38.1 %). It is equal within 0.2 ms at one client, where nothing queues, and drifts by a few
  points at higher load, as expected when requests reach the engine earlier. TPOT is still over-predicted by 26 % to 89 % at 32 and 64
  clients and by 78 % and 183 % at 128.
- **TTFT** is still over-predicted at every concurrency, by 24 % to 54 % up to 8 clients, by 58 % and 75 % at 16 and by 112 % to 150 % at 32
  and 64 clients, on both shapes. The causes this page named (prefix reuse in the run, `engram_config.cpu_offload` left unset) are still not tested.
  At 128 clients on 4 GPUs both figures are of a saturated queue (382 s measured, 1194 s predicted) and say little.
- The synthetic acceptance is a mean. The simulator accrues the mean each step, where vLLM accepts by position; they agree while
  every draft is verified (blis-vllm's page says when they differ). The realised mean in the server log, 3.511, suggests they did.
- The grade is G4 for the reason given under [Grade](#grade). The harness commit of the run is `c474b95c`; a later commit, `f7bb446`,
  changes only which substitutions a point names (the Rust variable is read as true, not as the text "1", by the value-class check).

## Grade

Each point is **G4**, by the engine-release difference, which is named on the point: `other_release` with detail `0.33.0, scored on 0.32.0`, and `ported_functions_unpublished` (the engine publishes no list of the functions it ports, so a changed one cannot be ruled out). M2 accepts G4 for InferenceX points: no InferenceX data on the simulator's release exists, and the grading system may be revisited. A matched point could be G1 or G2 only at v0.32.0.

The G1 conditions that are not evaluated are named as `unevaluated` substitutions: `coefficient_range` and `kernel_hash` on these points (`value_class` and `resolved_differs` were evaluated, and `value_class` is false for `max_model_len`, `num_speculative_tokens`, `enable_adaptive_verification` and `tensor_parallel_size`, which are outside every value class the evidence covers).

## How to reproduce

```
# 1. freeze (needs GH_TOKEN; artifacts last until about 2027-02-07)
python3 orchestrator/baseline/freeze_rows.py --rows docs/m2/h200-v033/rows.json \
  --revision supplement/rows-447774-447789 --ledger-out LEDGER --out PULL --cache CACHE --units-out UNITS
# 2. score, from a clean checkout of the harness commit in contract/provenance.json
bash harness/run.sh --sim 780f661ef9c18a2a9928acf8a63a67667cd597c0 --sim-repo <inference-sim checkout> \
  --units docs/m2/h200-v033/units.txt --pull PULL --out OUT \
  --catalog SUBSTRATE/catalog --registry SUBSTRATE/registry --corpus-dir CORPORA \
  --fields FIELDS.json --catalog-release f70c6c7503a47442c4c5d989f8f17b093c14e069 \
  --registry-release f70c6c7503a47442c4c5d989f8f17b093c14e069
# 3. splits and the table
python3 orchestrator/baseline/split.py splits --pull PULL --out docs/m2/h200-v033/splits.json
python3 orchestrator/baseline/compare.py run --dir docs/m2/h200-v033/contract --sample in_sample --out docs/m2/h200-v033/table
```

`FIELDS.json` is blis-vllm `96ea750e3a626ab2f9c60ca3bc871b8a74839cc2`'s `fields.json` (sha256 `dbe9123a677792edf030a0da584b9fc915c45ec206a5cebbffc3944568b6e879`); the corpora are fetched as the baseline's README says. Cost: the freeze is about a minute for sixteen rows; the published scoring is about 40 seconds; the dry run is about 16 minutes (one replay of an hour-long trace per point, one worker) and 2 GB of memory.

## What this does not show

- Nothing here is held-out: the points are the development split's validation portion and the figures are labelled so.
- The dry run is not a score of record. It sets three engine refusals aside with placeholder proofs that prove nothing; with them in place the points are G5.
- The field list is the engine's for vLLM v0.32.0, and the rows ran v0.33.0. A field v0.33.0 added and the list does not know would show as `field_not_in_release`; the published run found one (`PYTHONUNBUFFERED`, which is not a vLLM variable).
- The supplementary ledger is the dashboard's, not the substrate's. Its units carry no role key, so nothing here is an anchor.
