# Scoring a first-party corpus of runs

InferenceX alone gives no G1 point: none of its in-scope runs used vLLM v0.32.0 (the M3 baseline, accuracy-dashboard#89). Runs made on that release outside InferenceX, with their whole configuration and their per-request exports, can. They also answer the question a user asks of BLIS: does it rank configurations as measurement ranks them? accuracy-dashboard#91 asks the harness to score such a corpus on its own. `orchestrator/baseline/corpus.py` does.

## The corpus is never in this repository

A corpus is read from a path given at run time. The tool refuses a corpus directory inside this checkout, and for a private corpus it refuses an output directory inside it. The full report of a private corpus, with every configuration, goes only to `--out`; what may be published (`--public-out`) is the corpus's label and its grade counts, and only under design D7's minimum: nothing for a corpus of fewer than 10 runs, and a grade held by fewer than 10 runs shown as "fewer than 10". The label is checked before anything is written: a short slug of lower-case letters, digits and hyphens, sharing no word with the corpus's path (which may carry a private name), and holding none of the names in `--private-names` (a file kept with the corpus); the public summary is checked for those names too. A public corpus publishes its whole report.

## What a corpus holds

`<corpus>/corpus.json` (format `first-party-corpus-1`) lists the runs. Each run states its workload, its concurrency, its GPUs, its whole configuration as it ran, its recorded build (image and the server log's banner), its measurement, the `blis` command that replays its requests, and every way the replayed requests differ from those the run sent (COV-12). The docstring of `corpus.py` has the exact layout.

The measurement is one of:

- `measured_requests`: one row per request, under the Result's request-row names (arrival, TTFT, TPOT, E2E, prompt, output and cached tokens, fate). The figures are computed from it by the same rule as the simulated side.
- `measured_figures`: the five figures as a source that publishes aggregates states them, with the window its client measured. The Red Hat dataset `redhat-performance/configiq-performance-upstream-data` is such a source: GuideLLM rows with TTFT and TPOT percentiles, ITL, and output throughput per model, accelerator, vLLM release and concurrency. Its own ingest issue settles which of its rows can be replayed (the dataset keeps no runtime arguments).

## What is compared

Per configuration and concurrency, over the steady middle window and across the whole cluster: output throughput, interactivity (output tokens per second per user, p50), TTFT p99, ITL p50, and the prompt cache-read rate. Both sides use one window rule: the requests that arrived inside the middle of the run's arrival span, a stated fraction (0.1 unless the corpus says otherwise) trimmed at each end, so the ramp and the drain are out of both. ITL p50 is the client's: the median of every inter-token latency of the window's requests, pooled (each request row's `itl_us`). BLIS's Result rows carry no per-token times yet (inference-sim#2128), so the simulated ITL p50 is absent, not stood in for by the median TPOT: a measured and a simulated value are compared only under one definition (DEV-8).

For each workload's set of configurations: Spearman and Kendall concordance of output throughput per GPU between BLIS and the runs, whether BLIS's top choice is the measured best, and the regret of its top choice (`ranking.group_metrics`, the measure the development split uses).

## Grades

The engine release BLIS runs is read from the field list of the build it scores with (`--fields`), never given as a flag. A run is scored only on a Result that `blis schema validate result` accepts and that holds a completed request row; anything else is a failed run. A run is graded as an InferenceX point is (`grade.grade`): its release read from its build (`grade.run_release`), the Result's coefficient methods (`result.coefficient_substitutions`), every G1 condition the harness does not yet evaluate named `unevaluated`, and the corpus's stated differences as `client_difference`. A run on v0.32.0 is therefore G2 today, and G1 once the conditions are evaluated from data and nothing is substituted.

## Changes to accuracy

The tool scores and reports; it fits nothing. Every accuracy change judged on a first-party corpus follows design §12.3: pre-registered, fitted on the fit split, and judged once on held-out data.

## Command

```
python3 orchestrator/baseline/corpus.py score --corpus /path/outside/the/checkout --blis BIN \
  --catalog SUBSTRATE/catalog --registry SUBSTRATE/registry --fields FIELDS_V0_32_0.json \
  --private-names /path/outside/the/checkout/names.txt \
  --out /path/outside/the/checkout/report --public-out grades.json
```

## Not done here

No corpus has been scored: none in this format exists yet. The private internal-experiment data needs an adapter to this format, run where that data lives; the configiq dataset needs its ingest issue. accuracy-dashboard#91 stays open until a corpus is scored and its grade counts are published.
