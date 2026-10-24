# Extractor → summary contract (Discussion #28)

The extractor (#29) writes one **contract directory** per scored run (one BLIS release over one frozen API pull). The v2 summary builder (#30) reads it and writes `summary.json` v2 (`schemas/summary.v2.json`).

Nothing here is used by the nightly pipeline. `evaluate.sh`, `build_summary.py`, `schemas/summary.v1.json` and the v1 snapshots are unchanged.

`orchestrator/ingest/contract.py` holds the shared code (point identity, canonical JSON, `ratio_str`, row order, file names), and `python3 orchestrator/ingest/contract.py <dir>` validates a contract directory. The worked example is `testdata/contract/run-a/` and `run-b/`.

## Files

| File | Format | One entry per |
|---|---|---|
| `points.csv` | CSV, header below | scored point |
| `fidelity.jsonl` | one canonical JSON object per line | scored point |
| `facets.json` | one canonical JSON object, keyed by `point_id` | scored point |
| `not_scored.jsonl` | one canonical JSON object per line | point InferenceX measured that this run didn't score |
| `provenance.json` | one canonical JSON object | run |

Every scored `point_id` appears exactly once in each of `points.csv`, `fidelity.jsonl` and `facets.json`. A not-scored `point_id` appears only in `not_scored.jsonl`.

### `points.csv`

The signedprobe per-point columns `build_summary.py` already reads (`EXPECTED_HEADER`), then two more:

```
scenario,model,gpu,label,concurrency,meas_tpot_us,pred_tpot_us,meas_ttft_us,pred_ttft_us,tier_unbracketed,point_id,measured_date
```

- Latencies are **microseconds**. Measured values come from the InferenceX row; predicted values from BLIS.
- `scenario` is the **deployment** name, shared by every concurrency of one sweep. (The agentic driver may write one scenario file per point; their names are an implementation detail and aren't carried here.)
- `label` is the workload label: `8k1k`-style for single-turn, `agentx` for agentic.
- `tier_unbracketed` follows the point's fidelity `status`: `MEASURED-OR-RESOLVED` for `exact`, `ALL (approximate)` for `approximate` (the strings `build_summary.TIER_MAP` already reads). So an approximate point (an approximated setting or an estimated build) counts only in the `all` tier, never in `measured_or_resolved`.
- `measured_date` is the InferenceX row's `date` (`YYYY-MM-DD`). It is **not** `curve_date`, which is InferenceX's curve grouping and can be later than the measurement (append-only points).

### `point_id`

`sha256` (hex) of the canonical JSON (below) of exactly these fields, all in InferenceX's own terms, so a point's id never changes with a BLIS release or a catalog mapping:

| Field | From the InferenceX row |
|---|---|
| `model` | `model` (InferenceX slug, e.g. `dsv41flash`) |
| `hardware` | `hardware` |
| `precision` | `precision` |
| `framework` | `framework` |
| `benchmark_type` | `benchmark_type` (`single_turn` / `agentic_traces`) |
| `recipe` | `recipe_fingerprint`, or `row:<id>` when the row has none |
| `conc` | `conc` (an integer) |
| `measured_date` | `date` |

A re-measurement of the same recipe and concurrency on another date is a different point. Compare intersects on `point_id`.

### `fidelity.jsonl`

`{"point_id": …, <record>}`, one line per scored point, sorted by `point_id`. The record is described by `fidelity.schema.json`, and its shape is explained in Discussion #28 ("Per-point fidelity record"). For a scored point, `status` is `exact` or `approximate`, and there is no `reasons` field (the schema enforces both ways: `not_scored` requires `reasons`, a scored status forbids it). A point is `approximate` exactly when one of its `args` has `match: approximated` (a quantization setting BLIS can't state, scored with what BLIS uses instead), or its `build.match` is `estimated` (the run's vLLM build isn't the one BLIS models: a custom image, a commit off vLLM's mainline or unresolvable, or more than `vllm_max_distance` commits from `vllm_ref`; `build.why` says which). A build never stops a point from being scored. That arg's `blis` is the value BLIS used, and its `note` says why (fixed text from the policy table). A `mapped` arg must name its `blis_field`, a `blis_default` arg its `rule`, an `approximated` arg its `note`, and a `conflict` arg its `values`.

### `facets.json`

```json
{"<point_id>": {"identity": {…the eight fields above…},
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

### `not_scored.jsonl`

```json
{"point_id": …, "identity": {…}, "measured_date": …, "model": …, "hardware": …, "precision": …,
 "framework": …, "benchmark_type": …, "conc": …, "image": …,
 "measured": {"ttft_ms": …, "tpot_ms": …}, "reasons": ["<code>[:<qualifier>]", …],
 "notes": [{"reason": "<one of reasons>", "text": "…"}, …]}
```

One line per point, sorted by `point_id`. `reasons` is sorted and de-duplicated, and each one matches `fidelity.schema.json#/definitions/reason`. `notes` is optional: at most one per reason, sorted by reason, each naming one of the point's own reasons. A note says why the reason applies. Its text is fixed per reason in the policy table, never composed per point, so it stays deterministic. These records are written into `summary.json` v2's `not_scored` list as-is (including `identity`, so the id can be re-derived) and counted in `coverage.not_scored_reasons` by code (the part before `:`). They are never rendered.

### `provenance.json`

```json
{"ingest": "api",
 "blis": {"release": "v0.12.0", "commit_sha": "…", "catalog": "…", "registry": "…", "extractor_version": "…"},
 "vllm_ref": "v0.31.0", "vllm_max_distance": 2000,
 "policy_sha256": "…", "pulled_at": "<UTC ISO-8601>",
 "corpus": {"dataset": "…", "revision": "…", "sha256": "…"} | null,
 "pull_manifest_sha256": "…",
 "source": {"name": "SemiAnalysis InferenceX API", "url": "https://inferencex.semianalysis.com/api/v1/"}}
```

`source` names what was pulled: `{"name", "url"}` (the API the pull read), copied into summary.json's `ground_truth`.

`pull_manifest_sha256` is the sha256 of the frozen pull's manifest (each point's frozen inputs and their sha256s), and identifies exactly what was scored.

## Reason codes

Defined once in `fidelity.schema.json` (`definitions/reason`). An optional `:<qualifier>` names the arg, input or scenario involved (e.g. `setting_not_modelled:prefill_schedule_interval`).

| Code | Meaning |
|---|---|
| `artifact_unmatched` | No result JSON (or more than one) matches the row's `recipe_fingerprint` + `conc`. |
| `server_log_missing` | The point's vLLM server log is unavailable (e.g. artifacts expired). |
| `corpus_changed` | The corpus file's sha256 differs from the one recorded at first use. |
| `conflict` | Two sources disagree on a setting or replay input. |
| `unclassified_arg` | A vLLM arg the policy table doesn't classify. |
| `setting_not_modelled` | A timing-relevant setting BLIS can't represent. |
| `setting_differs` | A timing-relevant setting BLIS was given differs from what the run recorded (`differs` / `absent_in_blis` in the args diff). |
| `required_setting_missing` | A setting BLIS requires that no source records and BLIS has no default for. |
| `client_scenario_not_replayable` | The AgentX client scenario has no BLIS replay counterpart. |
| `model_not_in_catalog` | The served checkpoint (or its HF `base_model`) maps to no catalog model. |
| `hardware_no_coefficients` | The registry has no coefficients for the part. |
| `drafter_not_in_catalog` | The catalog graph doesn't describe the run's drafter. |
| `blis_refused` | BLIS refused the deployment; the qualifier is a short slug and the full message goes in the fidelity record. |

Adding a code is an additive change to `fidelity.schema.json` plus a row here.

## Determinism

- JSON is written with `canonical_dumps`: sorted keys, `(",", ":")` separators, UTF-8. Every JSON file and every JSONL line must equal its own canonical form.
- Lists are sorted: `args` by `arg`, `resolved` by `quantity`, `reasons` lexically. `points.csv` rows are sorted by (`scenario`, `label`, `concurrency`, `measured_date`, `point_id`), and `not_scored.jsonl` by `point_id`.
- Floats the logs print are kept as the decimal string printed; `ratio` is `contract.ratio_str()` (4 significant figures, trailing zeros kept: `"1.000"`, `"1.048"`); integers are exact.
- Same frozen inputs + same BLIS release + same config → byte-identical contract directory.
