# The scoring pipeline

All paths are relative to the repository root. The code is in `orchestrator/ingest/` unless stated.

## 1. Ingest from the InferenceX API (`api.py`)

- `GET https://inferencex.semianalysis.com/api/v1/availability` lists every series (model slug, chip, engine, precision, speculation, disaggregation, benchmark type, ISL/OSL, with a date). It is gzip JSON. A series is one deployment shape; it has several rows.
- `GET .../api/v1/benchmarks?model=<display name>` returns the rows of a model: one per concurrency and run. A row carries the identity fields, the engine image, the parallelism of each pool, the measured metrics and the `run_url` of the GitHub Actions run that produced it. The display name of a slug is read from the site's scripts.
- **Window.** `api.in_window` keeps the rows whose `date` is within 180 days ending at the pull's `today` (both ends included). The row `date` is used, not the curve's date. A row whose date does not parse is reported, never dropped silently.
- **Frameworks.** `engines.FRAMEWORKS` names every engine label the API uses, with its engine, router and topology. A label not named stops the pull (`engines.unknown_labels`): the harness will not guess an engine. Only vLLM labels fetch artifacts; every other label's points are G5 without a fetch.

## 2. Ledger units (`ledger.py`, `contract.py`)

A point is a **ledger unit** of blis-substrate's `catalog/ledger` (source revision `db-dump/2026-09-28` in the substrate this work was run against). The unit id is the SHA-256 of the canonical JSON of eleven identity fields: source, model, hardware, precision, framework, benchmark type, configuration hash, recipe fingerprint, concurrency, measured date and benchmark run. The `point_id` of every record is that unit id, so a point is the same point under any BLIS release. Rows the ledger does not hold are counted as `left_out_records` and are in no figure; a row whose recomputed identity differs from the ledger's raises `RowDiffers` and is dropped and recorded.

## 3. Freezing a pull (`cli.py pull`, `pull.py`, `orchestrator/baseline/freeze.py`)

`cli.py pull --window-days 180 --today D --out DIR --cache DIR --ledger DIR [--only UNIT...]` writes, for each unit, the files under `DIR/points/<unit>/` and a `manifest.json` entry:

| Stored per point | Source |
|---|---|
| `server_log.gz` | the API's `/server-log` for the row (the engine's printed arguments and resolved configuration) |
| `result_json.gz`, `job_log.gz`, client files | the GitHub Actions artifact and the client job's log |
| `row`, `identity` | the API row and the ledger identity |
| `build` | the engine build resolved from the image and the log banner (`build.py`) |
| `checkpoint` | the served checkpoint taken from the run's recipe (below), when the log names only a local path |
| `checkpoint_conflict` | the recipe's one checkpoint where the served path names another |
| `draft_checkpoint` | the draft model the run's benchmark script set (below), with script, line and commit |
| `client_args`, `client_commit` | how the load generator was called, from the job log |
| `files` | the stored files and their SHA-256 |

The manifest's own SHA-256 is recorded in every run's `provenance.json` (`pull_manifest_sha256`); two runs are comparable only when it is equal. GitHub expires artifacts after 90 days, and the nightly keeps no raw data, so a pull is made once and kept: [reproducing](reproducing.md) says how. `freeze.py` re-freezes the units of an earlier snapshot (`--snapshot-state`, `--legacy-map`) or any list of units (`--units-file`), and records in `drift.json` what the live API no longer matches (rows that differ from the ledger, labels not named).

## 4. Recipes and checkpoint sources (`recipes.py`)

A run's log often names only a local path (`/scratch/models/MiniMax-M3-NVFP4`), not a Hugging Face repository. InferenceX's own repository says which: `GET /repos/SemiAnalysisAI/InferenceX/actions/runs/<id>` gives the run's `head_sha`; the `configs/*master.yaml` files at that commit bind each recipe to a model, image, framework, precision and runner.

- **Served checkpoint.** The recipes whose image, framework, precision and runner hardware equal the row's are candidates; the served path's last component must equal the recipe model's name (or a directory the commit's `runners.yaml` stages it under). Exactly one repository must survive. Otherwise nothing is taken; if the recipe names one repository and the path names another, the pull records `checkpoint_conflict` and the point is G5 `value_conflict:model` naming both.
- **Draft model.** For a run whose log names the draft model by a local path, the benchmark script `<model-prefix>_<precision>_<hardware>_mtp.sh` at the same commit sets `DRAFT_MODEL`; the pull records the repository, script and line. The scorer takes it only when the logged path's last component equals the repository's name ([evidence](m2/local-path-checkpoints.md)). No recipe draft gives G5 `value_not_recorded:speculative_config.model`.

The recipe at the run's commit is part of the run's own record (the same kind of source as the server log), not a substituted fact.

## 5. The harness: `harness/run.sh`

```
harness/run.sh --sim <tag|40-hex commit> [--sim-repo URL|PATH]
               --units FILE --pull DIR --out DIR
               --catalog DIR --registry DIR --corpus-dir DIR --fields FILE
               --catalog-release <tag|40-hex> --registry-release <tag|40-hex> [--max-rss-mb N]
```

| Flag | Meaning |
|---|---|
| `--sim` | the inference-sim release tag (`vMAJOR.MINOR.PATCH[-suffix]`) or a full 40-hex commit; a branch name is refused because it moves. run.sh clones it (`--sim-repo`, default GitHub; a local path works), builds `blis` with the Go toolchain the repository's `go.mod` names, and runs the scorer. |
| `--units` | the ledger units to score, one id per line; its SHA-256 is recorded. |
| `--pull` | the frozen pull. |
| `--catalog`, `--registry` | the substrate's `catalog/` and `registry/` directories, with `--catalog-release` and `--registry-release` naming what they are at (a release tag or a full 40-hex commit; a short hash or a branch is refused). A pin by commit makes the figures **experimental**, as does a simulator that is not a release tag. |
| `--corpus-dir` | the agentic corpora (`resolve_agentic_corpus.py --all` fetches them at the revisions and SHA-256 the catalog pins). |
| `--fields` | the engine's `fields.json` at the blis-vllm release the simulator runs: which fields are modelled, and each field's estimation rule. |

It refuses to run if the harness files (`harness/`, `orchestrator/`, `schemas/`, `requirements-ci.txt`) differ from the checkout's `HEAD`, and records `HEAD` as `harness_commit` in `provenance.json` and every point's `simulator` block (design rule X8). A tree with no history names its commit in `HARNESS_COMMIT`, which is trusted, not checked.

## 6. Scenario, replay, and a point's TTFT and TPOT

1. **State, decide, estimate** (`settings.py`, `fields.py`). Every setting the run recorded (launch configuration, the arguments the log prints as passed, the resolved configuration, lines the engine printed) is copied into the engine block under the engine's own names; two same-stage sources that disagree are G5 `value_conflict`. Each field the run set is decided by `fields.json`: modelled or proven inert changes nothing; not modelled with no rule is G5 `field_not_modelled`; a rule (`leave_unset`, `substitute`) is applied and named as an `estimated` substitution. See [coverage accounting](coverage-accounting.md).
2. **Support** (`support.py`). The served model, the chip and the drafter must be in the substrate catalog; the chip needs registry coefficients; a stated draft length must be one vLLM accepts.
3. **Cluster.** The node size is taken from the launch configuration, else from InferenceX's `runners.yaml` records (`inferencex_runners.py`).
4. **Replay.** A single-turn point replays the client's own requests (`inferencex_client.py`: prompt lengths from the result file, the client's flags from the job log) through `blis replay`; an agentic point replays the trace corpus at the run's concurrency. One `blis` process per point.
5. **Figures.** The Result's `ttft_mean_ms` and `tpot_mean_ms` (`result.TTFT_MEAN_MS`, `TPOT_MEAN_MS`, mean over the requests of the measured window) are written to `points.csv` in microseconds as `pred_ttft_us` and `pred_tpot_us`; `meas_*` is the mean, over the unit's measurements, of the API row's metrics. MAPE is `|pred - meas| / meas`; the shape error is computed per sweep from both curves anchored at the lowest concurrency (a sweep needs three points).
6. **Outcome.** A point is scored (G1 to G4), not scored (G5, with a reason from a closed list), or failed (the simulator refused a scenario the harness wrote from recorded values; listed in `failed.jsonl` with the fault).

## 7. The contract directory and the table

The six files are specified in `orchestrator/ingest/CONTRACT.md` and validated by `contract.py`. `compare.py run|pair` reads them and writes the table; it refuses two runs that differ in harness commit, units, pull or point set. [Reading the table](before-after.md).
