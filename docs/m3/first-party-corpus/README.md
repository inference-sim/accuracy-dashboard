# Scoring a first-party corpus of runs

InferenceX alone gives no G1 point: none of its in-scope runs used vLLM v0.32.0 (the M3 baseline, accuracy-dashboard#89). Runs made on that release outside InferenceX, with their whole configuration and their per-request exports, can. They also answer the question a user asks of BLIS: does it rank configurations as measurement ranks them? accuracy-dashboard#91 asks the harness to score such a corpus on its own. `orchestrator/baseline/corpus.py` does.

## The corpus is never in this repository

A corpus is read from a path given at run time. The tool refuses a corpus, its work directory (which holds the pull it freezes and the scorer's scenarios and Results), its output directory or a private-names file inside any work tree of this repository (this checkout or another worktree of it). The full report of a private corpus, with every configuration, goes only to `--out`. What may be published (`--public-out`) is the label given on the command line (`--label`) and the grade counts, under design D7's minimum: nothing for a corpus of fewer than 10 runs, and a grade held by fewer than 10 runs shown as "fewer than 10". The label must be a short slug of lower-case letters, digits and hyphens, sharing no word with the corpus's path (which may carry a private name), and holding none of the names in `--private-names` (a file kept with the corpus); the public summary is checked for those names too. A public corpus publishes its whole report.

## The same path as an InferenceX point

A first-party run is not given a scenario of its own. It holds the records an InferenceX run holds: the vLLM server log, the launch configuration where there is one, the client's command line (its job log), and the row InferenceX's API would record for it, with the client's own statistics under InferenceX's names. `corpus.py score` freezes the corpus into a pull of the shape `cli.py pull` writes and scores it with `score.score_points`, the function `harness/run.sh` runs for every InferenceX point. So the scenario is built by design §11.2's State, Estimate, Decide and Price from the run's own records; every field is decided by the engine's field list; every value no record holds is a named substitution or a G5 reason, never a default (X19); the requests are the run's client's (COV-12); and the run is graded by the scorer's own `grade_outcome`. The scorer's inputs are checked and built as `cli.py score` builds them: the build at its release, its stack's engine release, the field list for that release, the checked AgentX corpora, the metric definitions. A private corpus takes no path a public one does not.

The harness can replay a client's requests only where it can recompute them, so each run names its client: `inferencex` (InferenceX's single-turn client, with its job log and its commit) or `agentx` (an AgentX agentic run, with its client export). A run of any other client gets the scorer's reason `client_scenario_not_replayable:<client>`: it is G5 `value_not_recorded`, counted, and never simulated on requests it did not send. A client commit that is not recorded is named on the point as a `client_difference`, as it is for InferenceX.

The tool writes no contract. The contract's point identity is the InferenceX ledger's (`contract.point_id` refuses another source), so a first-party run's id is the same SHA-256 of its identity with source `first-party`; the outcomes, and so the grades and scenarios, are the scorer's either way.

## What is compared

Five metrics of the simulator's registry, by id; `blis metrics` is read at run time and the tool refuses to run if the build defines any of them otherwise (DEV-8). The measured side is the client's own statistics, the simulated side the Result's request rows of the main phase:

| Id | Measured (the client's) | Simulated (the Result's rows) |
|---|---|---|
| `output_tok_s` | `output_tput_per_gpu` times the run's GPUs | output tokens over the span from the first arrival to the last completion |
| `interactivity_p50` | 1000 over `median_tpot` in ms | 1000 over the p50 of TPOT in ms |
| `ttft_p99_ms` | `p99_ttft` | the p99 of TTFT |
| `itl_p50_ms` | `median_itl`, pooled over tokens | none until the Result rows carry per-token times (inference-sim#2128) |
| `cache_hit_rate` | not recorded by the client | cached prompt tokens over prompt tokens |

For each workload's set of configurations: Spearman and Kendall concordance of output throughput per GPU between BLIS and the runs, whether BLIS's top choice is the measured best, and the regret of its top choice (`ranking.group_metrics`).

## Changes to accuracy

The tool scores and reports; it fits nothing. Every accuracy change judged on a first-party corpus follows design §12.3: pre-registered, fitted on the fit split, and judged once on held-out data.

## Command

```
python3 orchestrator/baseline/corpus.py score --corpus /outside/corpus --work /outside/work --out /outside/report \
  --blis INFERENCE_SIM/blis --sim-build v0.17.0 --catalog SUBSTRATE/catalog --catalog-release v0.14.0 \
  --registry SUBSTRATE/registry --registry-release v0.14.0 --fields FIELDS_V0_32_0.json --corpus-dir CORPORA \
  --harness-commit "$(git rev-parse HEAD)" --label a-public-slug --public-out grades.json \
  --private-names /outside/names.txt
```

## Not done here

No corpus has been scored: none in this format exists yet. The private internal-experiment data needs an adapter to this format, run where that data lives; the configiq dataset needs its ingest issue. accuracy-dashboard#91 stays open until a corpus is scored and its grade counts are published.
