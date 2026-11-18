# configiq points scored by simulation

Red Hat's configiq dataset (`redhat-performance/configiq-performance-upstream-data`, CC BY 4.0, revision `21cc6eb06b1934485a83b17a93e634ef38b5799e`) is now scored by simulation, through the same replay and comparison as InferenceX, and not by gates alone.

## Why no configiq point reached the simulator before

`orchestrator/ingest/configiq.py` turns ledger units into points and decides which are launcher-consistent ("provisional"). Nothing called `points()` except its own test: there was no scenario builder for a dataset row, no workload built from GuideLLM's columns, and no scoring loop, so all 388 provisional points stayed "awaiting simulation" and the configiq view counted 0 simulated of 1702.

## What runs

`orchestrator/ingest/score_configiq.py` (a separate entry point, so `cli.py`'s scorer closure, which committed InferenceX contracts name, is unchanged) reads the ledger, the dataset export and the pinned catalog and registry, then for each unit either refuses it by name or replays it:

- scenario: the catalog model and chip, the simulator's vLLM release, the row's tensor-parallel size and parsed engine flags; `max_model_len` is vLLM's own default for the checkpoint when the row leaves it blank;
- workload: a closed loop at the row's concurrency of `successful_requests` requests of the row's recorded mean prompt and output lengths;
- figures: GuideLLM's own statistics (weighted percentiles, ITL weighted by output tokens - 1, TPOT by output tokens) from the simulator's request rows; the headline pair is mean TTFT and mean ITL, the per-request TPOT the InferenceX harness compares;
- grade: G3 or G4, never better (provisional cap, COV-7); outside the headline (COV-11). Every gap is a named substitution on the point: the launcher's parallelism and blank flags, the unknown frame and client release, the assumed node size, the constant length standing for a recorded distribution, errored requests.

Refused by name, from identity alone: other engines (`engine_unsupported`), chips BLIS does not model, launches that equal no preset of the launcher, multi-turn workloads (think time and per-turn lengths are not recorded), a blank `max_seq_len` for a model whose catalog entry has no `config.json`, a simulator refusal of an unstated `block_size` (blis-vllm#68), and repeat runs that disagree.

Split: the dashboard's development split applied to the unit's role key; train and validation are simulated, test is withheld and its figures are not read.

## Command

```
python3 orchestrator/ingest/score_configiq.py --ledger SUBSTRATE/catalog/ledger --rows EXPORT.jsonl --data-dir DATASET_DIR \
  --blis INFERENCE_SIM_V0_18_0/blis --catalog SUBSTRATE/catalog --registry SUBSTRATE/registry \
  --catalog-release v0.15.0 --registry-release v0.15.0 --fields BLIS_VLLM_V0_33_0_BLIS_1/fields.json \
  --sim-build v0.18.0 --harness-commit HEAD40 --out OUT
```

Output: `configiq-points.jsonl`, `points.csv` (the InferenceX contract's columns) and `summary.json`.

## Needs from M3.1

Unstated `block_size` for gemma-4 on Hopper and for DeepSeek-V4 (blis-vllm#68) refuses 78 otherwise runnable units; a `config.json` in the Nemotron-3-Super catalog entry would admit 35; multi-turn session replay from a configiq row (110 units) needs a think-time statement the dataset lacks.

## What the 135 scored points are, and the TTFT bias

Every scored point is gpt-oss-120b (B200 105, H200 30, TP1): the other models' units are refused or fail on `block_size`. The figures describe that one model on two chips and are not a configiq-wide accuracy.

Mean TTFT is biased high (signed median +101 percent) while mean ITL is -14 percent. Split by chip and load (signed median error of mean TTFT; n):

| chip | concurrency 1 | 25-75 | 100-200 | 300 |
|---|---|---|---|---|
| B200 | -21 percent (21) | +113 (33) | +113 (36) | +1 (15) |
| H200 | +61 percent (6) | +484 (10) | +498 (10) | +442 (4) |

Checked and ruled out as the cause: the definition (TTFT is request start to first token on both sides, and the median is biased as much as the mean: +89 percent B200, +471 percent H200); the window (the simulated steady-state TTFT, requests after the first wave, is within 20 percent of the whole-run mean); prompt length (the recorded 1004-token mean is simulated, and block and batch defaults follow the engine's, 16384 batched tokens on B200); the rate type (the dataset records only the concurrency, the simulated mean in flight is 98 percent of it, and the simulated and recorded request latencies agree within 5 percent at concurrency 100). Prefix caching is on for all 135; whether GuideLLM's synthetic prompts shared prefixes is not recorded, and the simulation has no hits.

The bias is unexplained. It is load-dependent (flat fixed gap at concurrency 1, then growing), both sides run in lockstep waves (recorded request latencies spread 1-3 percent at concurrency 100), and at concurrency 1 a fixed gap remains (B200 1k prompts: 57 ms simulated, 30 ms recorded, which is of the order of the host admission cost). Remaining candidates, none tested: something specific to the configiq H200 runs (tensor-parallel size, chunked-prefill settings the row leaves blank), whether GuideLLM's synthetic prompts shared prefixes (prefix caching is on; the simulation has no hits), or the latency model under lockstep waves. No claim is made here that prefill is over-priced: on InferenceX fit units the H100 prefill slope is under-priced, the opposite sign, and H200 InferenceX cannot separate prefill from the admission constant. No scenario field was changed; these points stay provisional and outside the headline (COV-11).
