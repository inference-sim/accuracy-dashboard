# The M3 InferenceX baseline and each point's grade ceiling

This is the starting point M3 is measured from (accuracy-dashboard#89): for the vLLM lane and the SGLang lane, how many InferenceX points are in scope, how many are scored, why the rest are not (by reason, with the issue each reason cites, ordered by points blocked as design §11.6 asks), the grade distribution G1 to G5 with each grade's share, count and own accuracy (COV-11), and, for every point, its grade ceiling and the reason for it. The numbers are in [baseline.md](baseline.md); the per-point ceilings in `ceilings.jsonl`.

## Where the numbers come from

| Lane | Points | Source |
|---|---|---|
| vLLM | 1734 (1188 in scope) | The committed M2 after-run, [docs/m2/preliminary-after](../../m2/preliminary-after/preliminary-after-run.md): harness `0e9627e219c207593de5bc55d997cf3dca707d64`, simulator `a8bc3085a7c91c50a1d92862943a695c04adfe11` (the tree inference-sim v0.17.0 was tagged from), blis-substrate v0.14.0, blis-vllm field list sha256 `62743b57...` (the list of v0.32.0-blis.3, which v0.17.0's stack names). Not re-scored: the frozen pull it was scored over is not kept, and a new freeze is a new point set. The figures stay labelled experimental, as the after-run is. |
| SGLang | 1358 (901 in scope) | Every SGLang unit (labels `sglang`, `dynamo-sglang`, `mori-sglang`) of the same window, 2026-05-14 to 2026-11-09, in the ledger of blis-substrate v0.14.0 (source revision `db-dump/2026-09-28`), graded by the scorer's own offline path (`coverage.py`: `score_points` with no simulator), with the v0.17.0 stack and field list. The API rows were read on 2026-11-16; 915 SGLang rows of the window are newer than the ledger's source revision and are no point. `sglang-lane.json` holds one line per unit: its id, chip, label, date, release and G5 reasons, nothing measured. |

BLIS has no SGLang engine yet, so every SGLang point is G5 `field_unclassified` (blis-sglang publishes no field list; blis-sglang#2), and the Dynamo ones also `router_unsupported`. Its engine release is the one blis-sglang pins, v0.5.23 (blis-sglang#10).

Accuracy figures leave out the test and prospective points of the development split, as every report does (docs/m2/evaluation-protocol.md, section 6): the 795 scored vLLM points carry figures over the 520 train and validation points, and the 275 test points are counted, not measured. Counts include every point.

## Reading a ceiling

A grade says how close a point's comparison is today. The ceiling says how close it can be with the data that exists for it, if every piece of BLIS work it needs were done. Each point states one of two things:

- **at ceiling**: only new data raises it: another run, a record that was lost, a source corrected;
- **not yet**: BLIS work holds it below its ceiling, and the point names that work (`not_yet` in `ceilings.jsonl`).

The limits the data sets, and the evidence for each (`orchestrator/baseline/ceiling.py`):

| Limit | Caps at | The fact of the data |
|---|---|---|
| `nightly_or_custom` | G4 | The run used a nightly or custom build. G1 to G3 need a release. |
| `changed_functions` | G4 | The run used another release, and an upstream function the engine ports changed between it and the release BLIS runs, so G3 cannot be reached; G1 and G2 need a run on that release. The evidence is `ported-changes.json` (below). |
| `other_release` | G3 | The run used another release and no cited function changed, or no comparison exists (the SGLang lane: no SGLang port exists to compare). G3 is not reached yet because no engine publishes its list of ported functions. |
| `value_conflict`, a lost record (`value_not_recorded` with no subject, `api_413`, `no_recipe_fingerprint`, ...), `pd_pool_not_recorded` | G5 | Two records of one stage disagree, or a record of the run is gone or was never kept. Only the source can remove it. |
| `client_difference:client_flags`, `client_difference:failed_requests`, `later_record`, an `estimated` value the run did not record, `router_unsupported`, a `value_not_recorded` value an estimation rule could cover | G2 | A difference from the run that the data, not BLIS, makes: the job log holding the client's flags expired, the run's request counts were not kept, a cluster fact came from a later record, the run was behind a router BLIS does not host. |

Everything else that holds a point down (a field not modelled, a chip without coefficients, a coefficient not measured, a G1 condition not yet evaluated, a refusal by the simulator) is BLIS work and does not lower the ceiling. A G5 or failed point lists its reasons, not the substitutions it would carry once scored, so its ceiling is an upper bound.

What the baseline says, in short: no in-scope InferenceX point can reach G1 or G2 (no run uses vLLM v0.32.0 or SGLang v0.5.23), and no vLLM point can reach G3 (every release in the data has ported functions that changed: `Scheduler.schedule` among them). So every vLLM point that is scored is at its ceiling, G4; the 333 that are not scored but could be G4 are "not yet", and 60 are held at G5 by their own records. Raising the ceiling needs other data: InferenceX runs on the releases BLIS runs (accuracy-dashboard#90) and runs made on vLLM v0.32.0 outside InferenceX (accuracy-dashboard#91).

## The ported-function comparison

`ported-changes.json` is generated by `orchestrator/baseline/ported_changes.py` from blis-vllm v0.32.0-blis.3 (`40653dc4a16941ed8a9cc66aa82f5b7995cca461`) and a vLLM checkout. It reads the upstream functions blis-vllm's provenance headers cite with their line ranges at vLLM v0.32.0 (58 functions), and compares each one's syntax tree at each release in the data. It proves a change; it cannot prove the absence of one, because the headers are not the engine's list of ported functions (which design §11.3 asks each engine to publish). It is evidence for the ceiling only; no grade reads it.

```
python3 orchestrator/baseline/ported_changes.py gen --port BLIS_VLLM --port-commit v0.32.0-blis.3 --vllm VLLM \
  --release 0.21.0 --release 0.22.0 --release 0.24.0 --release 0.25.0 --release 0.25.1 --out docs/m3/baseline/ported-changes.json
python3 orchestrator/baseline/ported_changes.py check --port BLIS_VLLM --vllm VLLM docs/m3/baseline/ported-changes.json
```

## The issues

`issues.json` holds the issue each refusal reason cites. A field's issue is copied from the field list's own `evidence.issue` (`m3_baseline.py issues`, which records the list's sha256; the report refuses a list other than the run's). The reasons that are not a field, and the simulator's refusals by their text, are written by hand in the same file. A reason the data sets says so instead of naming an issue: no BLIS change removes it.

## Commands

```
# the SGLang lane (reads the InferenceX API rows, written by api.pull, never committed)
python3 orchestrator/baseline/m3_baseline.py sglang-lane --rows ROWS.json --today 2026-11-09 \
  --ledger SUBSTRATE_V0_14_0/catalog/ledger --fields FIELDS_V0_32_0_BLIS_3.json --stack STACK_V0_17_0.json \
  --catalog SUBSTRATE_V0_14_0/catalog --registry SUBSTRATE_V0_14_0/registry --out docs/m3/baseline/sglang-lane.json
# the field issues
python3 orchestrator/baseline/m3_baseline.py issues --fields FIELDS_V0_32_0_BLIS_3.json \
  --source "inference-sim/blis-vllm v0.32.0-blis.3 (40653dc4a16941ed8a9cc66aa82f5b7995cca461), fields.json" \
  --issues docs/m3/baseline/issues.json --contract docs/m2/preliminary-after/contract --sglang-lane docs/m3/baseline/sglang-lane.json
# the report (from committed files only; test_m3_baseline.py regenerates it)
python3 orchestrator/baseline/m3_baseline.py report --contract docs/m2/preliminary-after/contract \
  --sglang-lane docs/m3/baseline/sglang-lane.json --ported docs/m3/baseline/ported-changes.json \
  --issues docs/m3/baseline/issues.json --sglang-release 0.5.23 --out docs/m3/baseline/baseline
```

## What is not done here

- The same table at v0.18.0, before and after side by side, waits for v0.18.0 (accuracy-dashboard#89 stays open for it).
- The published dashboard does not show the ceiling beside the grade yet. The summary schema (`schemas/summary.v3.json`) admits no ceiling field, and any change under `schemas/` makes every committed contract stale (`test_contracts_current.py`), so the field is added with the next rescoring, at v0.18.0. Until then the ceiling is published here, per point.
