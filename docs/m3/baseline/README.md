# The M3 InferenceX baseline and each point's grade ceiling

This is the starting point M3 is measured from (accuracy-dashboard#89): for the vLLM lane and the SGLang lane, how many InferenceX points are in scope, how many are scored, why the rest are not (by reason, with the issue each reason cites, ordered by points blocked as design §11.6 asks), the grade distribution G1 to G5 with each grade's share, count and own accuracy (COV-11), and, for every point, its grade ceiling and the reason for it. The numbers are in [baseline.md](baseline.md); the per-point ceilings in `ceilings.jsonl`.

## Where the numbers come from

| Lane | Points | Source |
|---|---|---|
| vLLM | 1734 (1188 in scope) | The committed M2 after-run, [docs/m2/preliminary-after](../../m2/preliminary-after/preliminary-after-run.md): harness `0e9627e219c207593de5bc55d997cf3dca707d64`, simulator `a8bc3085a7c91c50a1d92862943a695c04adfe11` (the tree inference-sim v0.17.0 was tagged from), blis-substrate v0.14.0, blis-vllm field list sha256 `62743b57...` (the list of v0.32.0-blis.3, which v0.17.0's stack names). Not re-scored: the frozen pull it was scored over is not kept, and a new freeze is a new point set. The figures stay labelled experimental, as the after-run is. |
| SGLang | 1358 (901 in scope) | Every SGLang unit (labels `sglang`, `dynamo-sglang`, `mori-sglang`) of the same window, 2026-05-14 to 2026-11-09, in the ledger of blis-substrate v0.14.0 (source revision `db-dump/2026-09-28`), graded by the scorer's own offline path (`coverage.py`: `score_points` with no simulator), with the v0.17.0 stack and field list. The API rows were read on 2026-11-16; 915 SGLang rows of the window are newer than the ledger's source revision and are no point. `sglang-lane.json` holds one line per unit: its id, chip, label, date, release and G5 reasons, nothing measured. |

BLIS has no SGLang engine yet, so every SGLang point is G5 `field_unclassified` (blis-sglang publishes no field list; blis-sglang#2), and the Dynamo ones also `router_unsupported`. Its engine release, v0.5.23, is read from blis-sglang's `provenance.go` (`Upstream`) into `engines.json` (blis-sglang#10). `sglang-lane.json` keeps each unit's image, so its release can be re-checked.

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
| `other_release` | G3 | The run used another release and no cited function changed. G3 is not reached yet because no engine publishes its list of ported functions. |
| `other_release_unknown` | G3, an upper bound | The run used another release and no comparison of the ported functions exists (the SGLang lane: no SGLang port exists to compare). Whether G3 or only G4 can be reached is unknown until the port exists; the point says so (`ceiling_is_upper_bound`). |
| a G5 reason, by its class in `issues.json` | G5, G2 or none | Each reason not of the codes design §11.4 itself calls BLIS work (`field_*`, `not_in_catalog`, `engine_unsupported`, `code_not_visible`) has one entry: its issue and its class. `data` (the record is gone, was never kept, or two records disagree; no BLIS issue, a reason why) caps at G5; `estimate` (a value the run did not record, which an estimation rule can stand in for) caps at G2; `blis` (BLIS work; the issue that does it) and `source` (the source holds the record and could serve it, as the API's HTTP 413 for a large log) set no cap; `router` is decided by the router table (`engines.json`, blis-substrate v0.14.0's `catalog/routers`): G5 when every entry of the router says no llm-d policy is close enough, G2 when one maps a policy, and an upper bound when the run's mode is not recorded. A reason with no class is refused, never assumed, and a test checks that each class agrees with the issue its entry cites. So the 23 DeepSeek-V4-Pro NVFP4 conflicts (accuracy-dashboard#63) and the `engine_id` conflict (blis-vllm#142) are not yet. |
| `client_difference:client_flags`, `client_difference:failed_requests`, `later_record`, an `estimated` value the run did not record | G2 | A difference from the run that the data, not BLIS, makes: the job log holding the client's flags expired, the run's request counts were not kept, a cluster fact came from a later record. |

Everything else that holds a point down (a field not modelled, a chip without coefficients, a coefficient not measured, a G1 condition not yet evaluated, a refusal by the simulator) is BLIS work and does not lower the ceiling. A G5 or failed point lists its reasons, not the substitutions it would carry once scored, so its ceiling is an upper bound.

What the baseline says, in short: no in-scope InferenceX point can reach G1 or G2 (no run uses vLLM v0.32.0 or SGLang v0.5.23), and no vLLM point can reach G3 (every release in the data has ported functions that changed: `Scheduler.schedule` among them). So every vLLM point that is scored is at its ceiling, G4; the 353 that are not scored but could be G4 are "not yet", and 40 are held at G5 by their own records (a server log that is gone, no recipe fingerprint, or no recipe naming the draft model). For the SGLang lane the G3 ceiling of 616 points is an upper bound only. Raising the ceiling needs other data: InferenceX runs on the releases BLIS runs (accuracy-dashboard#90) and runs made on vLLM v0.32.0 outside InferenceX (accuracy-dashboard#91).

## The ported-function comparison

`ported-changes.json` is generated by `orchestrator/baseline/ported_changes.py` from blis-vllm v0.32.0-blis.3 (`40653dc4a16941ed8a9cc66aa82f5b7995cca461`) and a vLLM checkout. It reads the upstream functions blis-vllm's provenance headers cite with their line ranges at vLLM v0.32.0 (58 functions, those under an `if` or a `try` included, a property's setter apart from its getter), and compares each one's syntax tree at each release in the data, without its docstring or annotations. Every range it cannot resolve to a function is listed in `skipped` with the reason (32 today), so an undercount is visible; `check` fails when the file differs. The report refuses a contract whose runs used a release the comparison does not hold. It proves a change; it cannot prove the absence of one, because the headers are not the engine's list of ported functions (which design §11.3 asks each engine to publish). It is evidence for the ceiling only; no grade reads it.

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
# the SGLang release (blis-sglang's provenance) and the router table, with the commits they were read at
python3 orchestrator/baseline/m3_baseline.py engines --sglang-provenance BLIS_SGLANG/provenance.go \
  --sglang-source "inference-sim/blis-sglang provenance.go at 51014dd255e7744ed8bc1bd42f814487a08f392f (branch m3/integration; main holds no port yet)" \
  --routers SUBSTRATE_V0_14_0/catalog/routers \
  --routers-source "inference-sim/blis-substrate v0.14.0 (965b05834c47882bc0f9f1a960c90327a756ef3d), catalog/routers" \
  --out docs/m3/baseline/engines.json
# the report (from committed files only; test_m3_baseline.py regenerates it)
python3 orchestrator/baseline/m3_baseline.py report --contract docs/m2/preliminary-after/contract \
  --sglang-lane docs/m3/baseline/sglang-lane.json --ported docs/m3/baseline/ported-changes.json \
  --issues docs/m3/baseline/issues.json --engines docs/m3/baseline/engines.json --out docs/m3/baseline/baseline
```

## The count of anchor units whose inputs are recoverable

`recoverable.py` counts, without a simulator, the anchor units whose inputs can be fetched (requirements §3A.8). It needs the blis-substrate checkout `stack.json` pins and network access to the InferenceX API, and no token. The committed report carries no count, because no count has been measured: the check reads the API for each anchor unit, so it is run for real and its output given to `report`.

```bash
python3 orchestrator/baseline/recoverable.py --ledger SUBSTRATE/catalog/ledger \
  --anchor SUBSTRATE/catalog/ledger/published/anchor.yaml --today YYYY-MM-DD \
  --out recoverable.json --units-out recoverable-units.jsonl
# the same report command as above, with --recoverable recoverable.json, adds the section "Anchor units whose inputs are recoverable"
```

A unit is *excluded* (AMD or TPU hardware, or a framework no BLIS engine runs), *recoverable* (the API's `/server-log` returned a server log for the unit's kept record) or *not recovered*, with the reason. The API's `/server-log` is the only source probed, so the count is a floor: GitHub job logs and artifacts, and the recipe at the run's commit, are not read, and a unit that needs an agentic export, a P/D recipe or an SGLang launch command is *not recovered* with a `no_probe:` reason. Probing them is the next addition to `classify` in `recoverable.py`.

## What is not done here

- The same table at v0.18.0, before and after side by side, waits for v0.18.0 (accuracy-dashboard#89 stays open for it).
- The published dashboard does not show the ceiling beside the grade yet. The summary schema (`schemas/summary.v3.json`) admits no ceiling field, and any change under `schemas/` makes every committed contract stale (`test_contracts_current.py`), so the field is added with the next rescoring, at v0.18.0. Until then the ceiling is published here, per point.
