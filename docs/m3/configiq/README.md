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
