# Baseline: inference-sim v0.16.0 over the 2026-11-09 snapshot's units

This is the "before" of the M2 before/after. It is a labelled in-sample run (no anchor list exists, so no point is held out; see `table.md`). The "after" run is not here: it waits for the M2 pins (inference-sim PR 4's commands, blis-substrate layer 7, the blis-vllm tips), and it must be run from the same harness commit and over the same pull (below).

## Inputs, every one by commit

| Input | Value |
|---|---|
| Harness | accuracy-dashboard commit `0e9627e219c207593de5bc55d997cf3dca707d64` (branch m2/2-rescore-and-repin). `harness/run.sh` records it as `harness_commit`. |
| Simulator | inference-sim `v0.16.0` = `3f4998e28f922611a2d21d5c7ffe18a5272fe114`, built by run.sh with Go 1.27.2 (its go.mod) |
| Substrate, registry, catalog | blis-substrate `v0.13.0` = `fe6eab10b9795933de38122ba55e5299dcb20b5e` (the release v0.16.0's stack.json pins); `--catalog <checkout>/catalog`, `--registry <checkout>/registry`, both released as `v0.13.0` |
| Ledger | the ledger in that substrate checkout, source revision `db-dump/2026-09-28` |
| Engine | vLLM 0.32.0 (stack.json), field list `fields.json` of blis-vllm `v0.32.0-blis.2` = `1cf030eb888270c114308c3ae3102d02994f015c`, sha256 `d32342c4f9ae5c578ba578fd5e6575aa8db8bce099e0708480d55f7e8de5a6fc` |
| Router | llm-d-router `v1.0.0-blis.3` (stack.json), tag object `c86ebd581a77a1090aed0d2a9f2532a9f90e53c2` |
| Frozen pull | `pull_manifest_sha256` `c8f2ea928b0d4582afdc3fbf11ef9d6847a359791a520f497ee146e806a96166`, 1734 points, frozen from the live InferenceX API with `--today 2026-11-09` (window 2026-05-14 to 2026-11-09) between 2026-11-10T22:44Z and 22:57Z |
| Units | `units.txt` (1740 ledger units), sha256 `d89f860a46c0470a22543dc7fb77b8d1b10e508ce4f5ef5073e96f359f08597e` |
| Point set | the 1734 of those units the pull holds; sha256 of their sorted ids `6818482f91e308ee2b6f844d347de68fef6e90cbc27c22b41d21643d580e5c60` |
| Corpora | HuggingFace `semianalysisai/cc-traces-weka-062126` at `23f152f6f0f9399a85901b89a6458def0ef16729` (sha256 `29b6a19e...`) and `...-256k` at `8fecd2fc56694469f758f0afbbb6335ad3043740` (sha256 `e39cd2ff...`), fetched by `orchestrator/resolve_agentic_corpus.py --all --catalog <substrate>/catalog -o DIR`, which checks the hashes |
| vLLM defaults | `orchestrator/vllm_defaults.json` of the harness commit |

The units are the ledger units of the published snapshot's point ids (`state/last-run-api.json`, 2076 ids of `data/latest/summary.json`), mapped through `data/legacy/point-ids.json`: 1740 units. The other 336 ids have no unit (95 have no API row today, 241 are not in the ledger's source revision).

## Commands

```
# 1. freeze the pull (orchestrator/baseline/freeze.py)
python3 orchestrator/baseline/freeze.py --snapshot-state state/last-run-api.json \
  --legacy-map data/legacy/point-ids.json --ledger SUBSTRATE/catalog/ledger \
  --today 2026-11-09 --out PULL --cache ARTIFACTS

# 2. fetch the corpora
python3 orchestrator/resolve_agentic_corpus.py --all --catalog SUBSTRATE/catalog -o CORPUS

# 3. score, from a clean checkout of the harness commit (git worktree add --detach DIR 54fbe01...)
cd DIR && bash harness/run.sh --sim v0.16.0 --units units.txt --pull PULL --out OUT \
  --catalog SUBSTRATE/catalog --registry SUBSTRATE/registry --corpus-dir CORPUS \
  --fields FIELDS.json --catalog-release v0.13.0 --registry-release v0.13.0

# 4. the table
python3 orchestrator/baseline/compare.py run --dir OUT --sample in_sample --out table
```

`run-baseline.sh` is step 3 as run, with the paths of the machine that ran it. `contract/` is OUT; `table.json` and `table.md` are step 4. Two runs of step 3 gave byte-identical contract files.

## What it cost

| Step | Wall time | Peak RSS |
|---|---|---|
| Freeze the pull (1734 points, 4 download workers, 60 MB of artifacts) | 752 s (first freeze), 1522 s (second, with the recipe lookups) | 2.5 GB |
| Fetch the corpora (2.3 GB) | 39 s | 18 MB |
| Score (build blis, 1687 single-turn on 4 workers, 47 agentic on 1) | 33 to 55 s over five runs | 1.8 to 1.9 GB |

## Where it cannot be reproduced

- The nightly keeps nothing raw (COV-8) and the pull is not persisted. Step 1 needs the live API. The API has moved since the snapshot: it now returns 38 rows dated 2026-11-10 that this baseline does not hold (they are reported separately, never mixed in), and 6 rows whose identity no longer matches the ledger (`drift.json`; 6 units are therefore not in the pull) and 2 frameworks (`rubin-july`, `teacup`, 42 rows) that `engines.FRAMEWORKS` does not name, which `freeze.py` drops and records. A later freeze will differ from `pull_manifest_sha256`; the after run must reuse this pull or re-run both sides.
- Artifacts expire after 90 days. Of 111 disaggregated-vLLM runs fetched on 2026-11-10 for the scope analysis, 69 (dated 2026-05-19 to 2026-08-04) answered HTTP 404, so a freeze made later holds fewer logs than this one. This baseline's own freeze finished with no download error; a freeze made after more runs pass the 90 days will not.
- The published snapshot (`data/latest/summary.json`: schema 2, 747 scored points, TTFT 35.6 and TPOT 16.7 MAPE) was scored by an older scorer that did not gate on the engine's field list. It is not the same measurement as this run, so it is not compared with it; only a rerun at the same harness commit is a before.
- v0.16.0 has no `blis metrics` command, so the scorer could not check that its TTFT and TPOT have the InferenceX client's definitions (`docs/comparability.md`, "Which figures are compared"); the baseline's figures rest on the definitions the scorer assumes. The after-run's simulator has the command and is checked.
- `extractor_version` records `blis-latency-kernel@unknown`: v0.16.0's go.mod does not list the kernel module, so there is nothing for the scorer to read.
- stack.json is read from the v0.16.0 checkout run.sh builds, so it needs network access to GitHub (clone) and the Go module proxy.

## Result

41 of the 1734 points are scored, all G4 (no point can be G1 or G3 while four G1 conditions are unevaluated, and every point is measured on another release or build): TTFT MAPE 47.1 (n=11), TPOT 58.0 (n=11) over the train and validation points: the 30 test points are withheld from every accuracy figure (`../evaluation-protocol.md`, section 6). 10 more points (Kimi-K2.5 on h200) pass the scorer and are refused by the simulator (`blis_refused:scenario`: v0.16.0 will not state `block_size` for that model on that chip), so they are listed as failed. The other 1683 are G5; 546 of those are AMD points (out of scope). The leading blockers over in-scope points are in `table.md`; `table.json` holds every count.

### Change since the first baseline of this directory

The first baseline (harness `0206f24`) scored 20 points. Two harness changes moved it: the node-size stability rule (a label is stable when its size is the same in every recorded version, whatever clusters it maps to) and the naming of `teacup`, `rubin-july` and `tokenspeed`. `value_not_recorded:cluster.gpus_per_node` went from 858 points to 645: h100 (91) and b300 (122) are now stable, and 11 points that had no other blocker are scored (20 to 31). b200 (406) and h200 (239) stay unstable, not because their sizes disagree but because one record has runners outside every cluster and, for b200, the label is absent from the newest runners file. The three named labels hold no unit in the baseline set, so the point set is unchanged.

### Second freeze

The pull was frozen a second time, with the same command, after the freezer began to record the run's recipe draft model (`draft_checkpoint`: 235 points) and a served-path conflict with the recipe (`checkpoint_conflict`: 23 points). The point set is the same 1734 points; the manifest hash changed (`c8f2ea92...`), so the baseline was scored again against it. Scored points: 31, as before. The 235 eagle3 points still read `not_in_catalog:eagle3` here, because this baseline's catalog is blis-substrate v0.13.0, which holds no eagle3 drafter; against the layer 10 catalog all 235 resolve to `minimax-m3-eagle3` (179) or `minimax-m3-eagle3-gqa` (56). The 23 DeepSeek-V4-Pro NVFP4 points read `value_conflict:model` naming the path and the recipe's checkpoint. The 5 Kimi-K3 DSpark points read `value_not_recorded:speculative_config.model` (no recipe names their draft).

### Node size of b200 and h200

The harness now takes a label's node size from the records of its label when no record lists the runner and every record that lists the label states the same size (design §11.3 as merged). b200 and h200 take 8 as a G2 `later_record` substitution naming the label and the records relied on. That moved `value_not_recorded:cluster.gpus_per_node` from 645 points to none, and the scored points from 31 to 41 (the rest of the 645 still carry field reasons in this baseline, whose field list is v0.32.0-blis.2).
