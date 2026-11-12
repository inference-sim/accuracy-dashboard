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

A substitution is `{kind, subject, detail}`; the record's `substitutions` are sorted by kind, then subject. The G2 kinds are these. `estimated` is a field the engine's fields.json classifies as not modelled, set by the run, whose estimation rule decided the scenario's value; it is also a value the engine needs that the run did not record, taken by that field's rule. Its detail is the rule. `interim_status` is a field the run set whose status is `inert_unproven`, allowed only until M2. `client_difference` is each of `requests.differences` (COV-12). `unevaluated` is a condition of G1 the data could not decide; its subject is the condition (`kernel_hash`, `coefficient_range`, `resolved_differs`, `value_class`), as blis-substrate's point record names it; a substitution of kind `kernel_hash` or another of the four means the condition was decided and is false. `later_record` is a fact of the cluster that the run's own record lacks, taken from InferenceX's later record of the same runner (design §11.3). Its subject is `cluster.gpus_per_node`. Its detail is exactly `taken from InferenceX runners.yaml at <commit>, recorded after the run (<commit> of <date>)`. It also carries `record` (`<path> at <full commit>`) and `date` (YYYY-MM-DD), keys of this kind only, as blis-substrate's point record requires. A `router_differs` substitution (subject the router the run used) carries `policy` and `evidence`, and a `client_difference` and a `resolved_differs` a detail; `grade.grade` refuses a substitution missing its keys or carrying another kind's. Both `<commit>` are the first 8 hex digits of the label's first record in runners.yaml. `<date>` is that record's date as `YYYY-MM-DD`. For example, a row of 2026-06-15 on `mi355x`, whose first record is commit 303669b0 of 2026-07-02, names the detail `taken from InferenceX runners.yaml at 303669b0, recorded after the run (303669b0 of 2026-07-02)`. The rest are the kinds blis-substrate `contracts/spec/pointrecord` names: `coefficient_method`, `coefficient_range`, `execution_mode`, `kernel_hash`, `value_class` and `resolved_differs`. The scorer reads the Result's selected-entry report (`result.coefficient_substitutions`). A coefficient whose method is `transferred`, `literature`, `vendor_spec`, `roofline`, `assumed` or `copied` is a `coefficient_method` substitution (subject `set/name`, detail the method); `measured`, `calibrated` and `not_charged` are not. A Result with no report (an older build) names the single substitution `coefficient_method` on `selected-entry report`, detail `not read`, so no G1 is published for coefficients nobody read. Four of design §11.3's G1 conditions are not graded yet, because no source carries the datum. `coefficient_range` is an extrapolated or unidentified lookup. `kernel_hash` is a recorded library's hash against the one BLIS priced. `value_class` is a modelled field's value against the classes its oracle scenarios cover. `resolved_differs` is a resolved value against the engine's resolution. The Result's selected-entry report carries set, name, method, scope and file only (blis-substrate `contracts/spec/result` at 800ae26), and the run's server log and launch configuration name library versions at most. `g1.py` evaluates each of the four from the Result and the field list when the data is present for the point (a coefficient's `fit_range`, `kernel_impls`, `extrapolated` and `unidentified`, the Result's `resolutions`, a field's `value_classes`); the shape is blis-substrate layer 10's. Extrapolated is evaluated only for a coefficient that states a `fit_range`, unidentified only for one that states a `ci95`, and the kernel hash only for one that states `kernel_impls`; where an entry states none of it the flag is not evaluated, and `closeness_version: 1` says only that the recorder passed on what the entry states. A `router_differs` substitution names the router table `entry` (its name begins with the router), a `policy` the llm-d router offers, and the `evidence`. A condition that is true names nothing; one that is false names a substitution of its kind with the coefficient, library or field as subject; one whose data is absent stays unevaluated. `kernel_hash` stays unevaluated on every point until a source maps a library version to a kernel hash (blis-registry#73). Until a released Result carries the data, `grade.unchecked` names, on a point whose data is absent, one substitution per condition: kind the condition, subject `unevaluated`, detail `<kind> is unevaluated`. No scored point is G1 or G3 until a condition is graded from data and its substitution is removed. A drafter whose acceptance the run did not record is no longer refused. The scenario pins no acceptance (design D8). blis resolves it from the substrate's profile for the workload. The point names `estimated` on `speculative_config.acceptance_length` with the profile the Result's `input.workload_properties` reports (`profile <set>/<key> from the registry`). When the Result does not say, the detail is `profile not reported`. A recorded acceptance is pinned and named by nothing. The G3 and G4 kinds are `other_release`, `changed_functions`, `nightly_or_custom` and `ported_functions_unpublished`.

`grade.check` holds every point of a contract to these rules (COV-4, COV-5, COV-6), and the validator runs it.

## The scenario a point is scored on (design §11.2; COV-3)

The scorer copies the run's recorded configuration, unchanged, into the scenario's engine block (`settings.decide`, `settings.build`). It reads every source a run records: the launch configuration and the arguments the server log prints as passed, the configuration it prints as resolved, and the lines vLLM prints about values it chose. A value any of them records is copied; the passed value where the run passed one, the resolved one otherwise. Two passed sources that disagree, read as vLLM's argument parser reads them, are G5 `value_conflict`. A resolved value that differs from a passed one is not a conflict.

Each value goes under the engine's own name for it (`settings.LOCATIONS`). That is the upstream's name, as blis-vllm's engine block takes it (blis-vllm `rules/engineconfig/fieldnames_test.go`). The exceptions are the renames that block and blis-substrate's Deployment require. `kv_cache_dtype` is `cache_dtype`. The compilation, attention and kernel config fields are top-level. `speculative_config` is `speculative`. The parallel sizes are the Deployment's `parallel`. The KV connector and its CPU bytes are its `offload` block. Every other environment variable goes into the block's `env` as the launch gave it. `engine_version` is the release stack.json names, and the run's own release is the point's `run_release`.

Which fields are modelled, and each field's estimation rule, come only from the engine's fields.json (`fields.py`, VLM-3); the dashboard holds no settings table. Each field the run set is handled by its status. A field the release does not list is G5 `field_not_in_release`. A `not_modelled` field with rule `none` is G5 `field_not_modelled`. A `not_modelled` field with `leave_unset` is left out of the scenario so the engine resolves it (X19). With `substitute`, the rule's stated setting is written instead. Both are named on the point as `estimated`. An `inert_unproven` field is named as `interim_status`. `modelled` and `proven_inert` fields change no grade. The dashboard holds no list of the settings an engine needs (design §11.1). A setting no source recorded is left unset in the engine block and the engine resolves it (X19). Suppose blis refuses the scenario because a value is required (its text says `states no <field>`). The point is then G5 `value_not_recorded`, with the field parsed from the refusal as the subject (`score.value_refusal`). A refusal that names no parseable field uses the refusal's slug as the subject. A field the list does not know is `field_not_in_release`. The estimation rule is consulted for that field only when the engine refuses (`fields.estimate_missing`): the dashboard cannot name an unrecorded field the engine would accept, so it does not state estimates for fields nobody asked about. A field inside a config object that vLLM prints whole (`settings.WHOLE_PRINTED`) is set by the run by this rule (`settings._requested`). vLLM prints only the top-level arguments that differ from their defaults, but prints a config object passed as an argument whole, defaults included. Where the run has a launch config, the launch config decides: a field it states is set, one it does not is not. Where it has none, a field is not set when it equals the default of the run's own release: `orchestrator/vllm_defaults.json` is read at v0.32.0 by `gen_vllm_defaults.py` and is used only for a run whose server-log banner names exactly that release (`settings.defaults_for`). A field with no defaults entry for the run's release, and any such field of a run of another release, is judged unset: nothing says the run set it, so it cannot be `field_not_in_release`. No per-release table is derived from the logs; a table for another release is generated with `gen_vllm_defaults.py --ref`.

The scorer reads the field list from the engine release the simulator it scores with runs: a file passed with `--fields`, the `fields.json` of the pinned engine release (stack.json names it). A list whose `engine` is not that release is refused. The simulator will print the list itself once it has a command for it.

The scenario's cluster follows the packaging rule (design §2.2, SUB-3; blis-substrate `Cluster.Packaging`). For a chip whose catalog entry fixes GPUs per node and per rack (GB200 NVL72, GB300: 4 and 72) the scenario writes neither `gpus_per_node` nor `gpus_per_rack`, and `nodes` is the run's ranks over the entry's node size. For any other chip the node size is decided as the next section says. `gpus_per_rack` is never written. Whether an entry fixes packaging is read from `blis catalog resolve --chip`'s `packaging` field (inference-sim m1/packaging); TEMPORARY until the pinned blis reports it, the catalog checkout's `hardware/<chip>.yaml` `GPUsPerNode` and `GPUsPerRack` answer (`support.Catalog.packaging`, listed in `lint_blis_boundary.py`).

## The node size of InferenceX's machines

A launch configuration usually records `resources.gpus_per_node`. When one does not, the scorer reads the size from `inferencex_runners.json`, which `orchestrator/gen_inferencex_runners.py` writes from InferenceX's `runners.yaml` and `inferencex_runners.py` loads, refusing any key or value it does not define. InferenceX defines `gpus-per-node` per cluster and maps each hardware label to runners, and each runner to a cluster. The first InferenceX commit that records node sizes is 303669b0 (2026-07-02); the earlier runners file lists runners only. The file records the commit, date and path of each version it was read from, and for each label and version the size, the clusters and the file:line of each `gpus-per-node`. `gen_inferencex_runners.py --ix <checkout> --version <commit>:<path> ... --check` regenerates the file and fails if it differs.

Order of sources for a chip whose catalog entry does not fix its packaging: (i) the launch configuration; (ii) the table, for the row's hardware label; (iii) none, which is G5 `value_not_recorded` on `cluster.gpus_per_node`. A launch size and a table size that differ are G5 `value_conflict`. A chip whose entry fixes packaging (`gb200`, `gb300`) uses neither, and its scenario states no node size.

A row dated on or after the label's first record uses the record in force on the row's date. That is not a substitution; the scenario's header names the source as `cluster.gpus_per_node: InferenceX runners.yaml at <commit>`. A row dated before it takes the first record as a `later_record` G2 substitution. This applies only to a stable label.

The stability check, printed by the generator and enforced when the table is loaded: a label is stable when, in every version that records node sizes, it maps to a single size and the size is the same. The clusters it maps to may differ between versions. A label that is absent from a version, has a runner outside every cluster, maps to clusters of different sizes, or changes size is `stable: false`. It is not used for a row dated before its first record; such a row stays `value_not_recorded`. The label-record rule (design §11.3 as merged) then applies: a runner that no record lists may take the fact from the records of its label when every record that lists the label states the same size. A row with no usable record in force takes that size as a G2 `later_record` substitution whose `record` names the label and each record relied on (file and full commit) and whose `date` is the latest of them; a label whose records state two sizes, or none, stays `value_not_recorded`.

## Failed points

A reason that is a fault of the run, not a fact about the point, is not a grade. There are two. `blis_refused` is the simulator refusing the scenario the harness wrote from recorded values, or its Result failing a check. `setting_differs` is the written scenario losing a recorded value. Such a point is listed in `failed.jsonl` with its `faults`, and is counted in coverage as failed, never graded.

The summary builder refuses to publish a contract holding a failed point unless every one of its faults is a runner limit: `blis_refused:insufficient_memory` (the replay exceeded the runner's memory ceiling) and `blis_refused:timeout`. A larger runner or a longer timeout scores those points; any other fault means the run has not finished scoring, so the night publishes nothing (COV-8).

### `points.csv`

The per-point columns `build_summary.py` already reads (`EXPECTED_HEADER`), then two more:

```
scenario,model,gpu,label,concurrency,meas_tpot_us,pred_tpot_us,meas_ttft_us,pred_ttft_us,grade,point_id,measured_date
```

- Latencies are **microseconds**. Measured values come from the InferenceX row; predicted values from BLIS.
- A measured and a predicted value are compared only under one definition (DEV-8). The scorer compares the two figures under the InferenceX client's definitions (`result.CLIENT_DEFINITIONS`): `ttft_mean_ms` is the mean over requests of each request's TTFT, and `tpot_mean_ms` the mean, over requests with two or more output tokens, of each request's (E2E - TTFT) / (output tokens - 1), both over the measured window in milliseconds, unfinished requests excluded. The Result's own validation refuses a figure whose identifier is not in the metric registry; comparing the simulator's definitions with these before scoring waits for a simulator command that prints them.
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

`{"point_id": …, <record>}`, one line per scored point, sorted by `point_id`. The record is described by `schemas/fidelity.v3.json`. It carries the point's `grade` (`G1` to `G4`), its `substitutions` (empty exactly for G1), its `run_release`, the recorded `build`, every classified setting in `args`, the engine outcomes compared in `resolved`, and for an agentic point `replay`, for a single-turn point `requests`. A build never stops a point from being scored. A single-turn point's `requests` says how its client's requests were replayed: `cold` from an empty engine when the run disabled prefix caching, `primed` after `copies` warm-up copies of request 0 otherwise, `copies` being the client's own 2*CONC. Its differences always include `send_gap` (the client's interval between a response ending and its next request, which the simulator does not model), so every single-turn point is at least G2, and `sent_prompt_lengths` where the sent prompt lengths are not verified equal to the replayed targets. An arg is one recorded setting, and its `match` says how the scenario carries it. `exact`: the scenario carries the recorded value under the upstream's own name. `mapped`: it carries the value under the engine block's renamed field (`blis_field`). `inert`: the run set it and the scenario has no place for it (a proven-inert or unproven-inert field). `approximated`: the field's estimation rule decided the value, and `note` is the rule. `conflict`: two same-stage sources disagree, and `values` lists them.

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
 "simulator": {"build": "<release tag>", "engine": {"kind": "vllm", "version": "0.32.0"}},
 "engine": {"kind": "vllm", "version": "0.32.0"}, "points": 2035, "left_out_records": 0,
 "vllm_ref": "v0.32.0", "vllm_max_distance": 2000,
 "fields_sha256": "…", "pulled_at": "<UTC ISO-8601>",
 "corpora": [{"alias": "…", "workload": "…", "dataset": "…", "revision": "<40 hex>", "sha256": "<64 hex>"}, …],
 "pull_manifest_sha256": "…",
 "source": {"name": "SemiAnalysis InferenceX API", "url": "https://inferencex.semianalysis.com/api/v1/"}}
```

`source` names what was pulled: `{"name", "url"}` (the API the pull read), copied into summary.json's `ground_truth`.

`simulator` is the simulator build that scored the run (its release tag) and the engine release it runs. Every fidelity, G5 and failed record carries the same `simulator` (blis-substrate `contracts/spec/pointrecord` Simulator), and the validator refuses a contract whose points name more than one, or another than provenance's (COV-6).

`pointrecords.jsonl` holds the substrate's PointRecord (blis-substrate `contracts/spec/pointrecord`, SUB-19), one per scored and per G5 point, assembled by `pointrecord.py`; the files above are the dashboard's reporting views of the same points and keep their shapes. Its keys are the substrate's (`settings` for `args`, `simulator.data` with the catalog and registry hashes of the Result's `data` block, `predicted_basis` and `measured_basis` on each figure, `harness_commit`); a point that failed in the simulator has none. `docs/pointrecord.md` says how each field is made and what the pulled data cannot yet say.

`harness_commit` is the commit of the accuracy-dashboard checkout whose harness script (`harness/run.sh`) produced every figure, 40 lowercase hex (design §11.7, X8); `run.sh` reads it from the checkout's HEAD and refuses a checkout whose harness files differ from it, so any figure can be regenerated from that commit. Every point's `simulator` carries it too. `experimental` is true unless the simulator build is a release tag (the catalog and registry are required at release tags), and an experimental figure is never published as BLIS's accuracy. `units` records the `--units` file the run scored (its sha256, how many units it names, and those the pull did not hold), or null when the run scored every point of the pull. The nightly scores only the anchor units of the substrate release the build pins (COV-2): it passes as `--units` the published anchor list of the substrate release the build pins (`cli.read_anchor_units`; `blis ledger` replaces the file read in M2, accuracy-dashboard#52), and a release that publishes none fails the night.

`engine` is the engine release the scoring simulator runs, read from its stack.json (LIF-6); every point is scored on it, and graded against it. TEMPORARY until the pinned inference-sim release ships stack.json at its root: `cli.py score --stack FILE` names the file. A simulator checkout with no stack.json and no `--stack` is refused, because the build predates stack.json; the release is never read from installation.md.

`fields_sha256` is the sha256 of the field list the scorer read.

`points` is the number of points the run holds (scored, G5 and failed), and `left_out_records` the number of source records the ledger holds no unit for (the pull manifest's `ledger.unlisted`), published in coverage (COV-7).

`pull_manifest_sha256` is the sha256 of the frozen pull's manifest (each point's frozen inputs and their sha256s), and identifies exactly what that pull scored. On an IX-only nightly merge the published summary keeps this field (and `ground_truth.measurement_sha256`) from the **newest** pull, the one that fetched the delta. It does not come from a manifest covering the whole merged window. The carried-over points come from the prior summary, which was scored under its own pull. So this hash verifies the delta's pull, not the entire window a merged summary shows (no single manifest covers a merged window). A whole-window pull — and a manifest that covers it — is only produced on a seed or a BLIS-release rebuild.

## The summary

`summary.json` v3 carries, beside v1's tree of points:

- `headline`: the accuracy over every graded point, G1 to G4, and for each grade its share of the graded points and its own accuracy (`headline.headline`, COV-11). Each figure is `{mape, n}`; one over fewer than `min_points` (10) points is `"too few points"`, never a number.
- `coverage`: graded points over all points, split by engine, engine release, chip and grade, with the failed points and the records the ledger left out (`headline.coverage`, COV-7). Every anchor unit counts, including repeat runs the tree shows as one point.
- `backlog.top`: the ten most common reasons a point is not G1 (`backlog.top`).
- `not_scored` and `failed`: the two lists, as the contract holds them.

Beside `data/latest/summary.json` the nightly publishes the backlog (`build_summary_v2.backlog_of`, design §11.6): per engine, every G5 reason and every substitution, ranked by the points fixing it alone would grade (`alone`), then the points it blocks (G5) and demotes (graded below G1). The publish job fails when the summary has no coverage or the backlog is missing (COV-7).

## Releases scored

Each simulator release is scored exactly once (COV-9). The nightly scores, in the order they were tagged, every stable inference-sim release from `stack.FIRST_GRADED_RELEASE` on that has no published snapshot (`data/snapshots/*_blis-<tag>_*`), one after another (`resolve_blis.sh`, `stack.unscored_releases`). When none is left, it scores the newest release's IX-only delta. A release's snapshot, once published, never changes (COV-8).

## Frameworks

The pull lists every framework InferenceX reports in the window. `engines.FRAMEWORKS` maps each label to its engine (or none), the router its deployments run behind by construction, and its topology. Only `vllm`, `llmd-vllm`, `vllm-disagg` and `dynamo-vllm` run vLLM; they fetch artifacts and are scored. Every other label's point fetches nothing and is G5 with every reason true of it: `router_unsupported` when it ran behind a router other than llm-d's (the API row's `router_name`, else the label's own router), `field_unclassified` for the SGLang family, `engine_unsupported` for TensorRT-LLM, ATOM and TileRT. Reasons are listed together in `g5_reasons`, sorted by code; `g5_reason` is the first in design §11.4's order, which is `grade.G5_CODES`: `code_not_visible`, `router_unsupported`, `value_not_recorded`, `field_not_modelled`, `field_unclassified`, `engine_unsupported`, `not_in_catalog`, `field_not_in_release`, `value_conflict`, `build_unparseable`. So a point with both a router and an unsupported engine has `router_unsupported` as its `g5_reason`. A label the table does not name stops the pull. The pull records every row: a row in a point's records or listed under `ledger.unlisted` with its reason (`pull.check_placed`), and `cli.py score` refuses a run in which a unit is neither scored, G5 nor failed (`score.check_all_scored`; the contract validator holds the counts to `provenance.points`, COV-1).

## Disaggregated and multi-node runs

The fabric between a run's engines is a catalog property, not a run value, so no fields.json rule can clear it. A scenario of more than one node states a fabric class and the registry's fabric coefficient, and the point names the class it assumed (`cluster.fabric`, `estimated`).

**A prefill/decode row** (`disagg`) is written as two pools (`pd.py`, `score.score_pd`): the pools' counts, GPUs and parallel sizes from the row, each pool's engine arguments from the recipe the run launched from (`pd_recipe.py`, frozen by the pull as the role `recipe`), the NIXL connector, the endpoint picker file of the router table's policy, and the instance counts as `blis replay` flags. The recipe is named on the point as a recovery (`estimated`, subject `engine.<pool>.recipe`). A row the stack cannot yet run is G5 `topology_unsupported` with the part of the layout as the subject: `pd_pool_data_parallel`, `pd_unequal_data_parallel`, `pd_pool_not_recorded`, `pd_agentic` ([grades](../../docs/grades.md)). A row whose recipe is not found is `value_not_recorded` with the subject `recipe_unresolved:<slug>` (and `server_log_missing` where the log is gone too). Where there is no recipe and a log, the topology fields the log records still go through the field list (`settings.topology_reasons`).

**A multi-node colocated row** (`is_multinode`, not `disagg`) is one pool over several nodes, written like any other point (`settings.build` sizes the cluster from the engine's ranks); it is no longer refused for its topology.

## Tests that need a simulator

`test_inferencex_client_sim.py` holds the two COV-12 warm-up tests that run a real `blis replay`. They need a simulator build whose Result has `request_rows` (trace version 4). No released simulator writes `request_rows` yet, so no workflow runs these tests. Without `BLIS_BIN` both fail, and X16 forbids skipping them. A job that always failed would hide real failures, and a gated job has no build to gate on. They run by hand with `BLIS_BIN` and `BLIS_SCENARIO_DIR` set. This is an open item: the job is added with the first simulator build that writes `request_rows`, and no test watches for that build.

## Single-turn data-parallel balancer

A single-turn point with `parallel.dp` above 1 is simulated behind the llm-d endpoint picker profile `vllm-dp-lb`, which stands in for vLLM's internal load balancer. The point names it: `execution_mode` on `data-parallel balancer`.

## No required-field list

The dashboard holds no list of required fields. The engine refuses a scenario it cannot resolve, and the dashboard maps that refusal to `value_not_recorded` (`score.value_refusal`).

## G5 reasons

The closed list of design §11.4 (`grade.G5_CODES`; COV-5). A reason the scorer finds is mapped onto it by `assess.g5_of`; a reason with no place on the list raises, and is never published.

| Code | The scorer's finding |
|---|---|
| `code_not_visible` | An out-of-tree connector or a patched private build. |
| `router_unsupported` | The run was measured behind a router BLIS does not host: the API row's `router_name`, or the launch configuration's frontend, names one other than llm-d's. BLIS is not asked about such a point. |
| `topology_unsupported` | The run was measured on a deployment the scoring harness or the stack cannot yet run as a scenario; the subject names which part (a pool at data-parallel size above 1, pools of unequal size, a pool with no workers, an agentic replay of a prefill/decode deployment). A blocker-backlog entry, cleared when the harness writes that topology or the stack runs it. |
| `value_not_recorded` | A value the simulation needs is not recorded: the server log or the client export is missing, the row has no artifact, a required setting no source states, or a client scenario BLIS does not replay. |
| `field_not_modelled` | The run sets a field the engine classifies as not modelled, with no estimation rule. |
| `field_unclassified` | The engine has not classified a field the run sets, or the engine's repository publishes no field list yet. For the SGLang family (`sglang`, `dynamo-sglang`, `mori-sglang`) the subject is `sglang: no field list published` (`engines.SGLANG_FIELD_LIST_UNPUBLISHED`): blis-sglang is empty until M3. |
| `engine_unsupported` | No BLIS engine repository exists for the run's engine (TensorRT-LLM, ATOM, TileRT). |
| `not_in_catalog` | The run's model, chip or drafter has no catalog entry. |
| `field_not_in_release` | The run sets a field the engine release BLIS runs does not have. |
| `value_conflict` | Two sources that record the same stage of one field disagree. |
| `build_unparseable` | The run's recorded engine build cannot be read. |

## Determinism

- JSON is written with `canonical_dumps`: sorted keys, `(",", ":")` separators, UTF-8. Every JSON file and every JSONL line must equal its own canonical form.
- Lists are sorted: `args` by `arg`, `resolved` by `quantity`, `substitutions` and `g5_reasons` by kind or code then subject, `faults` lexically. `points.csv` rows are sorted by (`scenario`, `label`, `concurrency`, `measured_date`, `point_id`), and `not_scored.jsonl` and `failed.jsonl` by `point_id`.
- Floats the logs print are kept as the decimal string printed; `ratio` is `contract.ratio_str()` (4 significant figures, trailing zeros kept: `"1.000"`, `"1.048"`); integers are exact.
- Same frozen inputs + same BLIS release + same config → byte-identical contract directory.
