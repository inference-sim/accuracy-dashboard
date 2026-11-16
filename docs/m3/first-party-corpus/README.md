# Scoring a first-party corpus of runs

InferenceX alone gives no G1 point: none of its in-scope runs used vLLM v0.32.0 (the M3 baseline, accuracy-dashboard#89). Runs made on that release outside InferenceX, with their whole configuration and their per-request exports, can. They also answer the question a user asks of BLIS: does it rank configurations as measurement ranks them? accuracy-dashboard#91 asks the harness to score such a corpus on its own. `orchestrator/baseline/corpus.py` does.

## The corpus is never in this repository

A corpus is read from a path given at run time. The tool refuses a corpus, an output directory or a private-names file inside any work tree of this repository (this checkout or another worktree of it). The full report of a private corpus, with every configuration, goes only to `--out`. What may be published (`--public-out`) is the label given on the command line (`--label`) and the grade counts, under design D7's minimum: nothing for a corpus of fewer than 10 runs, and a grade held by fewer than 10 runs shown as "fewer than 10". The label must be a short slug of lower-case letters, digits and hyphens, sharing no word with the corpus's path (which may carry a private name), and holding none of the names in `--private-names` (a file kept with the corpus); the public summary is checked for those names too. For a private corpus no message names a path or quotes the simulator's stderr, which goes to the report directory. The replay runs in the corpus directory, so any file it writes stays there. A public corpus publishes its whole report.

## What a corpus holds

`<corpus>/corpus.json` (format `first-party-corpus-1`) lists the runs. Each run states its workload, its concurrency, its GPUs, its configuration as it ran (the engine arguments it passed), its recorded build (image and the server log's banner), the scenario its replay runs, its measurement, the `blis` command that replays its requests, and every way the replayed requests differ from those the run sent (COV-12). The docstring of `corpus.py` has the exact layout.

The measurement is one of:

- `measured_requests`: one row per request, under the Result's request-row names (arrival, TTFT, TPOT, E2E, prompt, output and cached tokens, fate) and the request's inter-token latencies (`itl_us`).
- `measured_figures`: the figures as a source that publishes aggregates states them, each by its registry id with its scope, aggregate and window. Such a figure is compared only when it is stated at the cluster, with no aggregate, over the window this tool uses (`arrival_middle:<f>`). A source whose client measured another window, such as the configiq dataset's GuideLLM rows, cannot be compared under one definition (DEV-8) and its runs are refused; its own ingest issue settles what of it can be scored.

## What is compared

Five metrics of the simulator's registry, by id, each computed on both sides by its registry definition; `blis metrics` is read at run time and the tool refuses to run if the build defines any of them otherwise (DEV-8):

| Id | What it is |
|---|---|
| `output_tok_s` | output tokens of the window's completed requests over the window's length |
| `interactivity_p50` | 1000 over the p50 of the window's TPOT in ms |
| `ttft_p99_ms` | the p99 of the window's TTFTs |
| `itl_p50_ms` | the p50 of every inter-token latency of the window's requests, pooled over tokens |
| `cache_hit_rate` | prompt tokens served from the prefix cache over the window's prompt tokens |

The window is chosen on the measured run: the requests that arrived inside the middle of its arrival span, a stated fraction (0.1 unless the corpus says otherwise, from 0 to below 0.5) trimmed at each end. The simulated side is read over the same requests, by id. BLIS's Result rows carry no per-token times yet (inference-sim#2128), so the simulated `itl_p50_ms` is absent until they do; nothing stands in for it.

For each workload's set of configurations: Spearman and Kendall concordance of output throughput per GPU between BLIS and the runs, whether BLIS's top choice is the measured best, and the regret of its top choice (`ranking.group_metrics`, the measure the development split uses).

## Grades

The engine release BLIS runs is read from the scoring build's `stack.json` (beside `--blis`), and the field list (`--fields`) must be that release's; it is never a flag. Each run's configuration is graded by that field list as `score.py` grades an InferenceX point (`fields.decide`): a field the release does not list is G5 `field_not_in_release`, a not-modelled field without an estimation rule G5 `field_not_modelled`, an estimated or unproven-inert field a named G2 substitution. The scenario the replay runs must carry exactly the configuration's engine block (COV-3); a run whose scenario differs is failed. A run is scored only on a Result that `blis schema validate result` accepts, that completed every request the run sent (`result.requests_complete`), and that gives a figure; anything else is a failed run. The grade is `grade.grade` over the run's release (`grade.run_release`), the configuration's decisions, the Result's coefficient methods, every G1 condition the harness does not yet evaluate named `unevaluated`, and the corpus's differences as `client_difference`. A run on v0.32.0 is therefore G2 at best today.

## Changes to accuracy

The tool scores and reports; it fits nothing. Every accuracy change judged on a first-party corpus follows design §12.3: pre-registered, fitted on the fit split, and judged once on held-out data.

## Command

```
python3 orchestrator/baseline/corpus.py score --corpus /path/outside/the/checkout --blis BUILD/blis \
  --catalog SUBSTRATE/catalog --registry SUBSTRATE/registry --fields FIELDS_V0_32_0.json \
  --private-names /path/outside/the/checkout/names.txt --label a-public-slug \
  --out /path/outside/the/checkout/report --public-out grades.json
```

## Not done here

No corpus has been scored: none in this format exists yet. The private internal-experiment data needs an adapter to this format, run where that data lives; the configiq dataset needs its ingest issue. accuracy-dashboard#91 stays open until a corpus is scored and its grade counts are published.
