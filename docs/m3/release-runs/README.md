# Runs on the engine releases BLIS runs

A point can be G1 only when its run used the engine release the simulator runs (design §11.3, LIF-6). No in-scope point of the M2 pull did ([the M3 baseline](../baseline/README.md)), so accuracy-dashboard#90 asks for the sources to be read at their latest data and the runs on vLLM v0.32.0, on SGLang v0.5.23 and on a release next to either to be found, counted and graded. [release-runs.md](release-runs.md) is that list; `orchestrator/baseline/release_runs.py` writes it.

## What was read

- **InferenceX**, at its latest published data: the API on 2026-11-16 (8351 rows, measured up to 2026-11-16) and its newest dump, `db-dump/2026-09-28`. That dump is already the ledger's source revision (blis-substrate v0.14.0): no newer dump exists. Every InferenceX run on a target release is newer than it, so none is yet a ledger unit, and only a unit is a point (design §10.2).
- **redhat-performance/configiq-performance-upstream-data** on Hugging Face, at commit `21cc6eb06b1934485a83b17a93e634ef38b5799e` (CC BY 4.0): aggregate GuideLLM rows of plain upstream vLLM releases, each file checked against the dataset's manifest. Its rows keep no runtime arguments and no per-request rows.

Neither source's raw data is committed (X12); the report holds counts and the revisions read.

## What it found

| | Records on the target release, in scope | Next to it |
|---|---|---|
| vLLM 0.32.0, InferenceX | 11 (Dynamo, b200, agentic) | 16 on 0.33.0 (h200, agentic: the [sixteen rows](../../m2/h200-v033/README.md) the substrate already holds as supplements) |
| vLLM 0.32.0, configiq | 51 (gpt-oss-120b, b200) | 40 on 0.31.0, 51 on 0.33.0 |
| SGLang 0.5.23, InferenceX | 12 (b200, h200, agentic) | 192 on 0.5.22 |

## Why none is graded yet, and what each needs

| Records | Blocked by | Who |
|---|---|---|
| InferenceX, vLLM 0.32.0 (11 in scope) | Not ledger units: the substrate's ledger must take them, as it took the H200 v0.33.0 rows (pinned supplements in `catalog/ledger/sources.yaml`), and the units get roles from the keyed rule (D4) only once the seed exists (blis-substrate#31, a ledger owner). Then `freeze_rows.py` freezes them and `harness/run.sh` scores them, with every G1 condition evaluated by `g1.py`. | blis-substrate; a ledger owner for the seed |
| InferenceX, SGLang 0.5.23 | No SGLang engine in BLIS (blis-sglang#2 and the stages after it). | blis-sglang |
| configiq | Not a ledger source yet, and its rows do not record what a G1 point needs: the fields the run set (no runtime arguments) and the requests it sent (no per-request rows). Its own ingest issue will settle what it can be scored as; the finder already reads it as a second source. | the configiq ingest issue |

The "engine release" condition is decided from each record's build; the kernel-hash condition is unevaluated for every point until a source maps a library version to a hash (blis-registry#73); the rest are decided only when a point is scored.

## A further source

Each source is an adapter from its files to one normalised record per measured run point (`source`, `record`, `engine`, `release`, `build`, `model`, `hardware`, `framework`, `benchmark_type`, `date`) and a revision record (`release_runs.inferencex_records`, `configiq_records`, `read_configiq`). The private internal-experiment data, read from a path given at run time, is a third adapter of the same shape; nothing else in the report changes.

## Command

```
python3 orchestrator/baseline/release_runs.py report \
  --inferencex-rows ROWS.json --inferencex-availability AVAILABILITY.json --inferencex-read-at 2026-11-16T12:07Z \
  --dump-tags TAGS.json --configiq DATASET_DIR --configiq-commit 21cc6eb06b1934485a83b17a93e634ef38b5799e \
  --ledger SUBSTRATE_V0_14_0/catalog/ledger --ledger-revision db-dump/2026-09-28 --out docs/m3/release-runs/release-runs
```

ROWS.json is `api.pull`'s rows, AVAILABILITY.json the `/availability` body, TAGS.json `gh api repos/SemiAnalysisAI/InferenceX-app/releases --jq '[.[].tag_name]'`, DATASET_DIR the dataset's `manifest.json` and `pairs/<id>.parquet` (read with pyarrow).

## Not done

The before and after grade distributions (COV-11) wait for those runs to be units and scored: the "before" is [the M3 baseline](../baseline/baseline.md). accuracy-dashboard#90 stays open.
