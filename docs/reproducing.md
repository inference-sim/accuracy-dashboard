# Reproducing the baseline and the after run

Everything here was run on one machine (macOS, Apple silicon) on 2026-11-10 and 2026-11-11. A run is *reproducible* when the same inputs give byte-identical contract files: the baseline was scored many times, at different harness commits, with identical `points.csv` and `facets.json` whenever the change did not touch scoring, and twice at one commit with identical files except the harness-commit field.

## Environment

| Item | Version |
|---|---|
| Go | 1.27.2 (the version inference-sim's `go.mod` names; `GOTOOLCHAIN=auto` fetches it) |
| Python | 3.14.6 here; CI uses 3.13. Packages: the pinned list in `requirements-ci.txt` (its hashes are for the Linux wheels; locally install the same versions without hashes) |
| Network | GitHub (clone, Go module proxy, Actions API and artifacts), Hugging Face (corpora), InferenceX API |
| Credentials | a GitHub token in `GH_TOKEN` or from `gh auth token` (the freeze reads Actions artifacts and the recipes) |

## Pins

| Input | Baseline | Preliminary after-run |
|---|---|---|
| Harness | accuracy-dashboard commit recorded in `docs/m2/baseline-v0.16.0/contract/provenance.json` (`0e9627e219c207593de5bc55d997cf3dca707d64`) | the same commit |
| inference-sim | `v0.16.0` = `3f4998e28f922611a2d21d5c7ffe18a5272fe114` | `a8bc3085a7c91c50a1d92862943a695c04adfe11` (the head of its combined pull request, branch `m2/combined-layers`) |
| blis-substrate (catalog, registry, ledger) | `v0.13.0` = `fe6eab10b9795933de38122ba55e5299dcb20b5e` | `v0.14.0` (commit `965b05834c47882bc0f9f1a960c90327a756ef3d`) |
| blis-vllm `fields.json` | `v0.32.0-blis.2` = `1cf030eb888270c114308c3ae3102d02994f015c`, sha256 `d32342c4f9ae5c578ba578fd5e6575aa8db8bce099e0708480d55f7e8de5a6fc` | `df9641b2f6c5782aa7987392f6d979e238ebe1ed`, sha256 `62743b57746f8376b291fdb853eb0eb19edacc5d717e1e7107d6e0f3ed41348d` |
| Corpora | `semianalysisai/cc-traces-weka-062126` at `23f152f6f0f9399a85901b89a6458def0ef16729` (sha256 `29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276`) and `...-256k` at `8fecd2fc56694469f758f0afbbb6335ad3043740` (sha256 `e39cd2ff3eba21d4a3664be51da743ac3d2149a1933898cafc7bfeac8147eeef`) | the same |
| Frozen pull | manifest sha256 `c8f2ea928b0d4582afdc3fbf11ef9d6847a359791a520f497ee146e806a96166` | the same pull |
| Units | `docs/m2/baseline-v0.16.0/units.txt`, 1740 units, sha256 `d89f860a46c0470a22543dc7fb77b8d1b10e508ce4f5ef5073e96f359f08597e` | the same |
| Point set | 1734 points (6 units are not in the pull), sha256 of the sorted ids `6818482f91e308ee2b6f844d347de68fef6e90cbc27c22b41d21643d580e5c60` | the same |

The final after-run uses the audited substrate stack and the final blis-vllm and inference-sim commits; [the command](m2/after-run.md) has the parameters, and `docs/m2/after-run.sh` runs it.

## Commands

All from the harness checkout `H` (the baseline's commit; `git worktree add --detach DIR <commit>` gives a clean one, which `run.sh` requires).

```
# 1. the frozen pull (network, about 25 minutes, 2.5 GB resident; skip if you hold the pull)
python3 orchestrator/baseline/freeze.py --snapshot-state state/last-run-api.json \
  --legacy-map data/legacy/point-ids.json --ledger SUBSTRATE/catalog/ledger \
  --today 2026-11-09 --out PULL --cache ARTIFACTS

# 2. the corpora (2.3 GB, about 40 s)
python3 orchestrator/resolve_agentic_corpus.py --all --catalog SUBSTRATE/catalog -o CORPUS

# 3. the baseline
bash harness/run.sh --sim v0.16.0 --units docs/m2/baseline-v0.16.0/units.txt --pull PULL --out OUT \
  --catalog SUBSTRATE_V013/catalog --registry SUBSTRATE_V013/registry --corpus-dir CORPUS \
  --fields FIELDS_V032_BLIS2.json --catalog-release v0.13.0 --registry-release v0.13.0

# 4. the splits file and the table (the splits file sits beside OUT; compare.py refuses a contract with
#    unscored points and no splits file)
python3 orchestrator/baseline/split.py splits --pull PULL --out splits.json   # then beside OUT, or pass --splits
python3 orchestrator/baseline/compare.py run --dir OUT --sample in_sample --out table

# 5. the preliminary after-run (a commit pin for the simulator, a local clone allowed)
bash harness/run.sh --sim a8bc3085a7c91c50a1d92862943a695c04adfe11 --sim-repo PATH_TO_INFERENCE_SIM \
  --units docs/m2/baseline-v0.16.0/units.txt --pull PULL --out OUT_AFTER \
  --catalog SUBSTRATE_FINAL/catalog --registry SUBSTRATE_FINAL/registry --corpus-dir CORPUS \
  --fields FIELDS_FINAL.json \
  --catalog-release v0.14.0 --registry-release v0.14.0
python3 orchestrator/baseline/compare.py refusals --work OUT_AFTER-work --out refusals.json
python3 orchestrator/baseline/compare.py pair --before OUT --after OUT_AFTER --sample in_sample --out before-after
```

The units file for step 3 is committed; `split.py splits --pull PULL --out splits.json` makes the splits file (committed beside each contract directory).

**A contract is made by the scorer it sits beside.** The harness commit in each `contract/provenance.json` is the checkout `run.sh` ran from; the results are committed after it, so it is not the head. `orchestrator/baseline/test_contracts_current.py` fails if any scoring file (`harness/`, `schemas/`, `requirements-ci.txt`, a non-test file under `orchestrator/` except the boundary lint and `build_summary_v2.py`, which write no contract) differs between that commit and the head: a change to the scorer means every committed contract is scored again and the tables regenerated. CI checks out the full history for this.

## Expected results

| | Baseline | Preliminary after-run |
|---|---|---|
| Points | 1734 (in scope 1188, AMD 546) | 1734 |
| Scored | 41, all G4 (TTFT MAPE 47.1, TPOT 58.0, over the 11 train and validation points) | 795, all G4 (TTFT 27.8, TPOT 19.8, over the 520 train and validation points) |
| Refused by the simulator | 10 | 103 |
| Not scored (G5) | 1683 | 836 |

The committed tables and contract directories are `docs/m2/baseline-v0.16.0/` and `docs/m2/preliminary-after/`; `test_compare.py::test_committed_tables` regenerates each table from its contract directory and fails on any difference.

## Cost

| Step | Wall time | Peak resident memory |
|---|---|---|
| Freeze (1734 points, 4 download workers, 60 MB of artifacts) | 752 s (first), 1522 s (second, with the recipe lookups) | 2.5 GB |
| Corpora | 39 s | 18 MB |
| Baseline | 33 to 184 s | 1.8 GB |
| Preliminary after-run | 110 s to about 20 min (the 450 scored points run longer replays; several heavy jobs shared the machine) | 1.8 GB |

## The prefill/decode and agentic runs

The runs of [prefill/decode coverage](m2/pd-coverage.md) (188 units, `docs/m2/pd-table-as-published/` and `docs/m2/pd-writer-experiment/`) and the 47 points of [agentic coverage](m2/agentic-coverage.md) are scored with the inputs that page lists, by the commands it gives. They use their own frozen pulls, which are not committed. A prefill/decode freeze also reads each row's recipe at the run's commit (the repository's REST API: a tree and a few blobs per run).

## What cannot be reproduced

- **The live API drifts.** Re-freezing today returns rows the snapshot did not hold (new rows, rows that no longer match the ledger, new engine labels). A later freeze has a different manifest hash and is a different point set; compare it only with a rescoring of the baseline over the same pull.
- **Artifacts expire after 90 days.** GitHub deletes them; a freeze made later loses the logs of older runs (their points score as `server_log_missing`). Of 111 disaggregated runs fetched on 2026-11-10, 69 (dated up to 2026-08-04) answered 404. **Use the stored pull**: keep the pull directory (60 MB, manifest hash above) and pass it as `--pull`. It is not committed because it holds third-party artifacts; the committed contract directories hold the outputs.
- **The nightly keeps no raw data**, so the pull behind the published snapshot is not recoverable from the repository.
- **Third-party data.** The pull contains InferenceX's artifacts (logs and results), published by SemiAnalysis, whose terms apply to them; the corpora are Hugging Face datasets under their own licences. None is committed here (design rule X12).
