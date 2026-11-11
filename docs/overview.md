# Overview

## What is measured

InferenceX (SemiAnalysis) publishes benchmark runs of inference engines on GPUs: a model, a chip, an engine and its settings, a workload, and, at each client concurrency, the measured time to first token (TTFT) and time per output token (TPOT). BLIS is a simulator of the same engines. The dashboard takes a recorded run, builds the BLIS scenario that states what the run did, asks BLIS to simulate it, and compares the simulated TTFT and TPOT with the measured ones.

Two things are reported for each such **point** (one concurrency of one run, identified by a ledger unit, below):

- **Accuracy**: the absolute percentage error of TTFT and TPOT (MAPE), and the error in the shape of the curve over concurrency (the **shape** error: both curves re-anchored at the lowest concurrency of the sweep).
- **Closeness**: how nearly the simulation was the run. A point is graded G1 (exact) to G5 (not scored). The grade is computed from data alone and lists every substitution the simulation made. The words are defined on the [closeness page](closeness-grades.md).

A MAPE without its grade says little: a small error from a simulation that guessed half the settings is a different statement from the same error on an exact one. The dashboard therefore reports each grade's accuracy on its own, and counts every point it could not score by the reason.

## From the API to a table

```
InferenceX API  ->  window of rows  ->  ledger units  ->  frozen pull  ->  scenario  ->  BLIS replay  ->  Result
 (availability,      (180 days)         (blis-substrate    (artifacts,      (only what      (blis replay)    (TTFT, TPOT,
  benchmarks)                            ledger: identity)  manifest)        the run          one process      coefficients,
                                                                             recorded)        per point)       resolutions)
                                                                                                                  |
        before/after table  <-  contract directory  <-  grade, substitutions, accuracy  <------------------------+
```

1. **Ingest.** The API lists the series (`availability`) and each series' rows (`benchmarks`). A row is one measured point. The window is the 180 days before the run date, by the row's `date`. See [the scoring pipeline](scoring-pipeline.md).
2. **Ledger units.** A row is scored through the unit the blis-substrate ledger gives it (a hash of its identity). A row newer than the ledger's source revision has no unit and is in no figure.
3. **Freeze.** The artifacts of each unit (server log, result file, job log) are downloaded once and recorded in a manifest. Scoring reads the frozen pull and nothing else from the network, so a run can be repeated.
4. **Scenario.** The scorer builds a BLIS scenario from the values the run recorded and from nothing else (design rule X19: a value no source recorded is left for the engine to resolve, never guessed). A setting BLIS does not model, or a value the run did not record, either makes the point G5 or is replaced by a stated stand-in that is named on the point.
5. **Replay and Result.** `blis replay` runs the scenario with the run's own requests and returns a Result: predicted TTFT and TPOT, the coefficients the price rested on, and the engine's resolution of settings.
6. **Grade and table.** The harness writes a **contract directory** (`points.csv`, `fidelity.jsonl`, `not_scored.jsonl`, `failed.jsonl`, `facets.json`, `provenance.json`) and `compare.py` turns one or two of them into a table. Every figure records the commit of the harness that produced it (design rule X8).

## What the baseline and the after-run are

The **baseline** is the pinned BLIS release v0.16.0 scoring 1734 points. The **after-run** is the M2 stack (a newer simulator, catalog, registry and engine field list) scoring the same 1734 points over the same frozen pull. The difference is the effect of the M2 work, and nothing else: [the reproducing page](reproducing.md) says how to repeat both, and [the before/after page](before-after.md) how to read the table.

## What it is not

It is not a held-out evaluation. There is no anchor list yet (design D7: roles drawn from a seed no candidate job can read), so every figure is in-sample, and the per-split figures use a [development split](m2/evaluation-protocol.md) that is the dashboard's own. See [limits](limits.md).
