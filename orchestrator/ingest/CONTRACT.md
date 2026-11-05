# Extractor → summary contract (Discussion #28)

The scorer (`score.py`) writes one **contract directory** per scored run (one BLIS release over one frozen API pull). The summary builder (`build_summary_v2.py`) reads it and writes `summary.json` v3 (`schemas/summary.v3.json`). Snapshots published as v2 (`schemas/summary.v2.json`, with the frozen record schema `schemas/fidelity.v2.json`) never change (COV-8); the validator and the web still read them.

The v1 db-dump pipeline has been retired (its workflows and dump-ingest scripts removed). `build_summary.py` (shared arithmetic), `schemas/summary.v1.json` and the three committed db-dump snapshots are unchanged and still read by the UI.

`orchestrator/ingest/contract.py` holds the shared code (point identity, canonical JSON, `ratio_str`, row order, file names), `orchestrator/ingest/ledger.py` reads the ledger's unit list, and `python3 orchestrator/ingest/contract.py <dir>` validates a contract directory. The worked example is `testdata/contract/run-a/` and `run-b/`.

## Files

| File | Format | One entry per |
|---|---|---|
| `points.csv` | CSV, header below | scored point |
| `fidelity.jsonl` | one canonical JSON object per line | scored point |
| `facets.json` | one canonical JSON object, keyed by `point_id` | scored point |
| `not_scored.jsonl` | one canonical JSON object per line | G5 point (design §11.4) |
| `failed.jsonl` | one canonical JSON object per line | point whose scoring failed (below) |
| `provenance.json` | one canonical JSON object | run |

Every scored `point_id` appears exactly once in each of `points.csv`, `fidelity.jsonl` and `facets.json`. A G5 `point_id` appears only in `not_scored.jsonl`, and a failed one only in `failed.jsonl`. The three counts sum to `provenance.json`'s `points` (COV-1).

## Grades

Every point gets exactly one closeness grade, computed from data alone by `grade.grade` (design §11.3): the highest-numbered grade whose conditions apply.

| Grade | When |
|---|---|
| `G1` | The run's engine release is the one the scoring simulator runs (`provenance.engine.version`, from stack.json), and nothing was substituted. |
| `G2` | As G1, and the record names one or more substitutions. |
| `G3` | The run's release is another one, and the engine publishes a function-level diff showing no ported function changed. |
| `G4` | As G3 with a changed function; or the build is nightly or custom; or the engine publishes no ported-function list (every point on another release is G4 until it does). |
| `G5` | Not scored, for one of design §11.4's reasons only (COV-5). |

The run's release (`run_release`) is read by `grade.run_release` from the recorded build: an official `vllm/vllm-openai` or `vllm/vllm-openai-rocm` image tagged `vX.Y.Z` whose server-log banner, when there is one, prints that version; any other build is nightly or custom, and `run_release` is null. The build's `match` (the commit distance from `vllm_ref`) is not a grade input.

A substitution is `{kind, subject, detail}`; the record's `substitutions` are sorted by kind, then subject. The G2 kinds are `estimated` (a field the engine's fields.json classifies as not modelled, set by the run, whose estimation rule decided the scenario's value; or a value the engine needs that the run did not record, taken by that field's rule; the detail is the rule), `interim_status` (a field the run set whose status is `inert_unproven`, allowed only until M2), `client_difference` (each of `requests.differences`, COV-12), and the kinds blis-substrate `contracts/spec/pointrecord` names (`coefficient_method`, `coefficient_range`, `execution_mode`, `kernel_hash`, `value_class`, `interim_status`, `resolved_differs`). The G3 and G4 kinds are `other_release`, `changed_functions`, `nightly_or_custom` and `ported_functions_unpublished`.

`grade.check` holds every point of a contract to these rules (COV-4, COV-5, COV-6), and the validator runs it.

## The scenario a point is scored on (design §11.2; COV-3)

The scorer copies the run's recorded configuration, unchanged, into the scenario's engine block (`settings.decide`, `settings.build`). It reads every source a run records: the launch configuration and the arguments the server log prints as passed, the configuration it prints as resolved, and the lines vLLM prints about values it chose. A value any of them records is copied; the passed value where the run passed one, the resolved one otherwise. Two passed sources that disagree, read as vLLM's argument parser reads them, are G5 `value_conflict`. A resolved value that differs from a passed one is not a conflict.

Each value goes under the engine's own name for it (`settings.LOCATIONS`): the upstream's name, as blis-vllm's engine block takes it (blis-vllm `rules/engineconfig/fieldnames_test.go`), except the renames that block and blis-substrate's Deployment require (`kv_cache_dtype` is `cache_dtype`; the compilation, attention and kernel config fields are top-level; `speculative_config` is `speculative`; the parallel sizes are the Deployment's `parallel`; the KV connector and its CPU bytes are its `offload` block). Every other environment variable goes into the block's `env` as the launch gave it. `engine_version` is the release stack.json names, and the run's own release is the point's `run_release`.

Which fields are modelled, and each field's estimation rule, come only from the engine's fields.json (`fields.py`, VLM-3); the dashboard holds no settings table. For each field the run set: a field the release does not list is G5 `field_not_in_release`; `not_modelled` with rule `none` is G5 `field_not_modelled`; `not_modelled` with `leave_unset` is left out of the scenario so the engine resolves it (X19), and with `substitute` the rule's stated setting is written instead, each named on the point as `estimated`; `inert_unproven` is named as `interim_status`; `modelled` and `proven_inert` change no grade. A value blis-vllm needs that no source recorded (`block_size`, `max_num_batched_tokens`, `max_num_seqs`, a drafter's acceptance) takes its field's estimation rule the same way, or the point is G5 `value_not_recorded`. A field inside a config object that vLLM prints whole is set by the run only when it differs from vLLM's own default, read from vLLM's dataclasses at the release (`orchestrator/vllm_defaults.json`, written by `gen_vllm_defaults.py`).

The scorer reads the field list from the simulator it scores with: `blis fields --engine vllm --json` prints the engine's fields.json at the release that build runs. A list whose `engine` is not the release stack.json names is refused.

## Failed points

A reason that is a fault of the run, not a fact about the point, is not a grade: `blis_refused` (the simulator refused the scenario the harness wrote from recorded values, or its Result failed a check) and `setting_differs` (the written scenario lost a recorded value). Such a point is listed in `failed.jsonl` with its `faults`, and is counted in coverage as failed, never graded.

The summary builder refuses to publish a contract holding a failed point unless every one of its faults is a runner limit: `blis_refused:insufficient_memory` (the replay exceeded the runner's memory ceiling) and `blis_refused:timeout`. A larger runner or a longer timeout scores those points; any other fault means the run has not finished scoring, so the night publishes nothing (COV-8).

### `points.csv`

The per-point columns `build_summary.py` already reads (`EXPECTED_HEADER`), then two more:

```
scenario,model,gpu,label,concurrency,meas_tpot_us,pred_tpot_us,meas_ttft_us,pred_ttft_us,grade,point_id,measured_date
```

- Latencies are **microseconds**. Measured values come from the InferenceX row; predicted values from BLIS.
- `scenario` is the **deployment** name, shared by every concurrency of one sweep. (The agentic driver may write one scenario file per point; their names are an implementation detail and aren't carried here.)
- `label` is the workload label: `8k1k`-style for single-turn, `agentx` for agentic.
- `grade` is the point's grade, `G1` to `G4`, and equals its fidelity record's. In the summary's tree a G1 point is in the strict tier (`measured_or_resolved`), every other one in `all` only.
- `measured_date` is the InferenceX row's `date` (`YYYY-MM-DD`). It is **not** `curve_date`, which is InferenceX's curve grouping and can be later than the measurement (append-only points).

### `point_id`

A point is one ledger unit (design §10.2), and its `point_id` is the unit's `unit_id`. The identity is the source plus ten InferenceX fields: model, hardware, precision, framework, benchmark type, configuration hash, recipe fingerprint, concurrency, measured date and benchmark run. `point_id` is the SHA-256 (hex) of the canonical JSON (below) of exactly these eleven fields:

| Field | From the InferenceX records |
|---|---|
| `source` | `"inferencex"` |
| `model` | `model` (InferenceX slug, e.g. `dsv41flash`) |
| `hardware` | `hardware` |
| `precision` | `precision` |
| `framework` | `framework` |
| `benchmark_type` | `benchmark_type` (`single_turn` / `agentic_traces`) |
| `configuration_hash` | the SHA-256 of the canonical JSON of 17 fields of the record's serving configuration, in InferenceX's own names: `image`, `isl`, `osl`, `offload_mode`, `spec_method`, `disagg`, `is_multinode`, `prefill_tp`, `prefill_ep`, `prefill_dp_attention`, `prefill_num_workers`, `num_prefill_gpu`, `decode_tp`, `decode_ep`, `decode_dp_attention`, `decode_num_workers`, `num_decode_gpu`. All 17 keys are always present; a value the record lacks is JSON null, and integers and booleans keep their JSON types. The image is written with any suffix beginning `@sha256:` removed. |
| `recipe_fingerprint` | `recipe_fingerprint`, or null where the record has none |
| `conc` | `conc` (an integer) |
| `measured_date` | the earliest `date` among all records of the benchmark run, so it is the same for all its attempts; a record with no run id keeps its own `date` |
| `benchmark_run` | the numeric GitHub Actions run id in `run_url`, without its attempt number; null when the record has no run id |

The identity is implemented once, in `contract.unit_identity`, and `test_ledger.py` checks it against a unit list that blis-substrate's own ingest tool generated (`testdata/ledger`).

The harness takes each point's identifier from the ledger's unit list (`ledger.py`), not from the row alone: it finds the row's unit by the row's id, and requires the row's recomputed identity to give the `unit_id` the list names. So:

- Records the ledger merges are one point: the duplicates of a measurement, records with the same measured values under another identity with the same role key, and several measurements of one identity. A unit holding several measurements is scored against their mean.
- The point's other inputs (server log, launch configuration, image) are those of its record with the smallest row id that the pull holds.
- A row the ledger leaves out, or that is newer than the ledger's source revision, is no point. The pull lists it under `ledger.unlisted` in its manifest, with the reason (`left_out:<the ingest report's reason>` or `not_in_source_revision`), and the summary counts it.
- A row whose recomputed identity differs from the unit list's is refused: it is not the record the ledger was generated from.

A re-measurement of the same recipe and concurrency in another benchmark run is a different point. Compare intersects on `point_id`.

Snapshots published before this identity carry `point_id`s of an eight-field identity (model, hardware, precision, framework, benchmark type, `recipe` as the fingerprint or `row:<API row id>`, concurrency and the row's own date). Published snapshots never change (COV-8), so they are matched to units through `data/legacy/point-ids.json`, generated by `legacy_ids.py build` from the API's rows and the ledger, and checked against every published snapshot by `legacy_ids.py check`.

### `fidelity.jsonl`

`{"point_id": …, <record>}`, one line per scored point, sorted by `point_id`. The record is described by `schemas/fidelity.v3.json`. It carries the point's `grade` (`G1` to `G4`), its `substitutions` (empty exactly for G1), its `run_release`, the recorded `build`, every classified setting in `args`, the engine outcomes compared in `resolved`, and for an agentic point `replay`, for a single-turn point `requests`. A build never stops a point from being scored. A single-turn point's `requests` says how its client's requests were replayed: `cold` from an empty engine when the run disabled prefix caching, `primed` after `copies` warm-up copies of request 0 otherwise. Its differences always include `send_gap` (the client's interval between a response ending and its next request, which the simulator does not model), so every single-turn point is at least G2, and `sent_prompt_lengths` where the sent prompt lengths are not verified equal to the replayed targets. An arg is one recorded setting: `exact` when the scenario carries the recorded value under the upstream's own name, `mapped` when under the engine block's renamed field (`blis_field`), `inert` when the run set it and the scenario has no place for it (a proven-inert or unproven-inert field), `approximated` when the field's estimation rule decided the value (`note` is the rule), `conflict` when two same-stage sources disagree (`values`).

### `facets.json`

```json
{"<point_id>": {"identity": {…the eleven fields above…},
                "sweep_id": "…", "scenario": "…", "label": "…", "workload": "8192:1024" | "agentx",
                "model": "<catalog name>", "gpu": "…", "precision": "…", "framework": "vllm",
                "serving": "aggregated", "spec_method": "…",
                "parallelism": {"tp": 1, "pp": 1, "dp": 1, "ep": 1},
                "image": "…", "vllm_version": "…"}}
```

- `sweep_id` groups the points of one measured curve for the shape metric. Shape is computed within a sweep only, so two dates never mix into one curve.
  - A sweep is one deployment: its points share `scenario`, `label`, `workload`, `spec_method`, `vllm_version`, `precision` and `parallelism`.
  - It holds **at most one point per concurrency**, since the trend is anchored at the lowest one. Two InferenceX rows of one deployment at the same concurrency (e.g. a spec and a no-spec run in one workflow, or two recipe rows) are two sweeps.
  - The validator refuses a contract that breaks either rule.
- `model` here is the catalog model BLIS priced, which is what the tables show. `identity.model` stays the InferenceX slug.
- `vllm_version` is the build's version string from the server-log banner (e.g. `0.30.1rc1.dev493+gac9126e58`), shown as the row's vLLM badge.

### `not_scored.jsonl` and `failed.jsonl`

```json
{"point_id": …, "identity": {…}, "measured_date": …, "model": …, "hardware": …, "precision": …,
 "framework": …, "benchmark_type": …, "conc": …, "image": …, "run_release": "0.32.0" | null,
 "measured": {"ttft_ms": …, "tpot_ms": …},
 "grade": "G5", "g5_reason": {"code": …, "subject": …}, "g5_reasons": [{"code": …, "subject": …}, …]}
```

One line per G5 point, sorted by `point_id` (`schemas/fidelity.v3.json#/definitions/notScored`). `g5_reasons` is every G5 reason found, sorted by code then subject, so the backlog counts each; `g5_reason` is the first by design §11.4's order. `subject` names the field, model, chip, router or engine, and is absent when there is none. A `failed.jsonl` line has the same fields up to `measured`, then `faults`, sorted and unique (`#/definitions/failed`). Both lists are copied into `summary.json` as-is (including `identity`, so the id can be re-derived) and never rendered as figures.

### `provenance.json`

```json
{"ingest": "api",
 "blis": {"release": "v0.12.0", "commit_sha": "…", "catalog": "…", "registry": "…", "extractor_version": "…"},
 "simulator": {"build": "v0.16.0", "engine": {"kind": "vllm", "version": "0.32.0"}},
 "engine": {"kind": "vllm", "version": "0.32.0"}, "points": 2035, "left_out_records": 0,
 "vllm_ref": "v0.32.0", "vllm_max_distance": 2000,
 "fields_sha256": "…", "pulled_at": "<UTC ISO-8601>",
 "corpus": {"dataset": "…", "revision": "…", "sha256": "…"} | null,
 "pull_manifest_sha256": "…",
 "source": {"name": "SemiAnalysis InferenceX API", "url": "https://inferencex.semianalysis.com/api/v1/"}}
```

`source` names what was pulled: `{"name", "url"}` (the API the pull read), copied into summary.json's `ground_truth`.

`simulator` is the simulator build that scored the run (its release tag) and the engine release it runs. Every fidelity, G5 and failed record carries the same `simulator` (blis-substrate `contracts/spec/pointrecord` Simulator), and the validator refuses a contract whose points name more than one, or another than provenance's (COV-6).

`harness_digest` is the digest of the harness image that produced every figure (`sha256:<64 hex>`), or `unreleased` (design §11.7, X8); every point's `simulator` carries it too. `experimental` is true unless the simulator build is a release tag (the catalog and registry are required at release tags), and an experimental figure is never published as BLIS's accuracy. `units` records the `--units` file the run scored (its sha256, how many units it names, and those the pull did not hold), or null when the run scored every point of the pull. TEMPORARY until blis-substrate publishes the anchor list (COV-2): the nightly scores the whole window and passes no `--units`.

`engine` is the engine release the scoring simulator runs, read from its stack.json (LIF-6); every point is scored on it, and graded against it. TEMPORARY until inference-sim v0.16.0 ships stack.json at its root: `cli.py score --stack FILE` names the file. A simulator checkout with no stack.json and no `--stack` is refused, because the build predates stack.json; the release is never read from installation.md.

`fields_sha256` is the sha256 of the field list `blis fields --engine vllm --json` printed.

`points` is the number of points the run holds (scored, G5 and failed), and `left_out_records` the number of source records the ledger holds no unit for (the pull manifest's `ledger.unlisted`), published in coverage (COV-7).

`pull_manifest_sha256` is the sha256 of the frozen pull's manifest (each point's frozen inputs and their sha256s), and identifies exactly what that pull scored. On an IX-only nightly merge the published summary keeps this field (and `ground_truth.measurement_sha256`) from the **newest** pull — the one that fetched the delta — not from a manifest covering the whole merged window: the carried-over points come from the prior summary, which was scored under its own pull. So this hash verifies the delta's pull, not the entire window a merged summary shows (no single manifest covers a merged window). A whole-window pull — and a manifest that covers it — is only produced on a seed or a BLIS-release rebuild.

## The summary

`summary.json` v3 carries, beside v1's tree of points:

- `headline`: the accuracy over every graded point, G1 to G4, and for each grade its share of the graded points and its own accuracy (`headline.headline`, COV-11). Each figure is `{mape, n}`; one over fewer than `min_points` (10) points is `"too few points"`, never a number.
- `coverage`: graded points over all points, split by engine, engine release, chip and grade, with the failed points and the records the ledger left out (`headline.coverage`, COV-7). Every anchor unit counts, including repeat runs the tree shows as one point.
- `backlog.top`: the ten most common reasons a point is not G1 (`backlog.top`).
- `not_scored` and `failed`: the two lists, as the contract holds them.

Beside `data/latest/summary.json` the nightly publishes `data/latest/backlog.json` (`build_summary_v2.backlog_of`, design §11.6): per engine, every G5 reason and every substitution, ranked by the points fixing it alone would grade (`alone`), then the points it blocks (G5) and demotes (graded below G1). The publish job fails when the summary has no coverage or the backlog is missing (COV-7).

## Releases scored

Each simulator release is scored exactly once (COV-9). The nightly scores, in the order they were tagged, every stable inference-sim release from v0.16.0 on (`stack.FIRST_GRADED_RELEASE`) that has no published snapshot (`data/snapshots/*_blis-<tag>_*`), one after another (`resolve_blis.sh`, `stack.unscored_releases`). When none is left, it scores the newest release's IX-only delta. A release's snapshot, once published, never changes (COV-8).

## G5 reasons

The closed list of design §11.4 (`grade.G5_CODES`; COV-5). A reason the scorer finds is mapped onto it by `assess.g5_of`; a reason with no place on the list raises, and is never published.

| Code | The scorer's finding |
|---|---|
| `code_not_visible` | An out-of-tree connector or a patched private build. |
| `router_unsupported` | The run was measured behind a router BLIS does not host: the API row's `router_name`, or the launch configuration's frontend, names one other than llm-d's. BLIS is not asked about such a point. |
| `value_not_recorded` | A value the simulation needs is not recorded: the server log or the client export is missing, the row has no artifact, a disaggregated or multi-node run records no fabric, a required setting no source states, or a client scenario BLIS does not replay. |
| `field_not_modelled` | The run sets a field the engine classifies as not modelled, with no estimation rule. |
| `field_unclassified` | The engine has not classified a field the run sets. |
| `engine_unsupported` | No BLIS engine repository models the run's framework. |
| `not_in_catalog` | The run's model, chip or drafter has no catalog entry. |
| `field_not_in_release` | The run sets a field the engine release BLIS runs does not have. |
| `value_conflict` | Two sources that record the same stage of one field disagree. |
| `build_unparseable` | The run's recorded engine build cannot be read. |

## Determinism

- JSON is written with `canonical_dumps`: sorted keys, `(",", ":")` separators, UTF-8. Every JSON file and every JSONL line must equal its own canonical form.
- Lists are sorted: `args` by `arg`, `resolved` by `quantity`, `substitutions` and `g5_reasons` by kind or code then subject, `faults` lexically. `points.csv` rows are sorted by (`scenario`, `label`, `concurrency`, `measured_date`, `point_id`), and `not_scored.jsonl` and `failed.jsonl` by `point_id`.
- Floats the logs print are kept as the decimal string printed; `ratio` is `contract.ratio_str()` (4 significant figures, trailing zeros kept: `"1.000"`, `"1.048"`); integers are exact.
- Same frozen inputs + same BLIS release + same config → byte-identical contract directory.
