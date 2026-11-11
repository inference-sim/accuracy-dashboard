# The dashboard against the final substrate stack

Checked 2026-11-10 against a checkout of the layer 10 tip as first pushed (short hash e1a1d97); layers 8 to 10 were then rebased with identical code, and the final pin target is `799dd5af9151eb46b2ef1e3a10c7435adfec8b38` (branch `m2/10-router-table-and-closeness-record`). The hash is a parameter everywhere else (`docs/m2/after-run.sh` takes `SUBSTRATE`), and the files checked were `catalog/`, `registry/` and `docs/contracts/`. No simulator ran on the new catalog (below).

## Names the dashboard reads

| Read by | Name | Result at the tip |
|---|---|---|
| `g1.py` | `selected_entries.closeness_version = 1`; per coefficient `kernel_impls`, `fit_range`, `extrapolated`, `unidentified` | as coded (`result.go`: `ClosenessVersion`, `KernelImpls`, `FitRange`, `Extrapolated`, `Unidentified`) |
| `g1.py` | `resolutions[]` with `pool`; the settings table | as coded (`result.md` table, `result.go:748` `Pool`) |
| `fields.py` | `value_classes` object; `ClassOf` | as coded; `classes.go` `ClassOf` is the rule `fields.class_of` copies |
| `grade.py` | substitution kinds including `router_differs`; keys `record`, `date`, `policy`, `evidence` | as coded (`pointrecord.go`) |
| `support.py` | a model lists `drafters`, a drafter lists `targets` | as coded; a model's `drafters` may also hold the word `speculator`, its own graph's speculator, which the code treats as "no separate drafter" |

## Catalog changes that touched the code

- A drafter can share its target's repository: `minimax-m3.1-flash-dspark` has `source.repo: MiniMaxAI/MiniMax-M3.1-Flash` and `source.path: dspark/config.json`, the same repository as `minimax-m3.1-flash`. A repository lookup for the served model would find two entries. The served-model lookups (`CheckoutCatalog`, `check_unambiguous`) now skip entries that name `targets`, and `Catalog.drafters_of(repo)` finds the drafter entries. A run whose draft checkpoint is such a repository is matched to the drafter entry the served model and it name each other, whose graph speculates by the run's method. Tests use a synthetic catalog of that shape.
- Against the real catalog: MiniMax-M3 with `Inferact/MiniMax-M3-EAGLE3` resolves to `minimax-m3-eagle3`; the MXFP8 model with the GQA repository to `minimax-m3-eagle3-gqa`; Kimi-K3 with `Inferact/Kimi-K3-DSpark` to `kimi-k3-dspark`; MiniMax-M3.1-Flash with its own repository to `minimax-m3.1-flash-dspark`; DeepSeek-V4-Pro self-drafting `mtp` resolves with no drafter; draft length 0 is refused. `nvidia/Kimi-K2.5-NVFP4` and `nvidia/MiniMax-M2.5-NVFP4` now resolve. `moonshotai/Kimi-K3.1` does not: the entry's repository is `moonshotai/Kimi-K3.1-Pro`.
- The router table has one entry, `dynamo-round-robin`, keyed by router, mode and session affinity. The dashboard writes no `router_differs` substitution yet: it needs the Dynamo mode of each run, which the API row and the server logs do not carry (see `dynamo-router-evidence.md`), so a rule that maps the 496 single-turn rows to round-robin by the absence of a flag is a decision, not a lookup.

## Can v0.16.0 run on the new catalog?

No. `blis catalog resolve` at v0.16.0 refuses the final catalog: `models/qwen3-14b/graph.yaml: field holds_engine_kv not found in type model.Node`, and `shared` likewise. The graph files use fields the older loader does not know. So the dry run of `dry-run-field-gate.md` cannot be repeated with the final catalog and the unchanged simulator, and what BLIS says about the new models waits for the simulator that ships with this stack.

## What the gate does with the final catalog

The dashboard's coverage command grades each unit without a simulator (`cli.py coverage`). Over the same 1734 points, with the scratch field list of the dry run (nothing committed) and the baseline's node-size assumption for b200 and h200:

| Catalog | Units reaching the simulator | G5 | `not_in_catalog:eagle3` (all reasons) |
|---|---|---|---|
| blis-substrate v0.13.0 | 689 | 1045 | 419 |
| layer 10 tip | 743 | 991 | 235 |

Only the eagle3 count moves: 54 more points pass the gate. No other reason changes, including the DeepSeek-V4-Pro NVFP4 points (23) and the Kimi-K3 points (35): their checkpoint is named by a local path in the run or the recipe, and the scorer's lookup uses a repository name.

Why 235 eagle3 points stay: 235 name their draft model by a local path (`/scratch/fsw/models/MiniMax-M3-EAGLE3`, `/data/models/MiniMax-M3-EAGLE3-GQA`, and the like), not by a Hugging Face repository, so `hf_repo` gives none and the served model's own graph decides, which has no eagle3. The 184 that name `Inferact/MiniMax-M3-EAGLE3` or the GQA repository (73 and 50 of them AMD, out of scope) resolve. A local path ends in the name of the repository (`MiniMax-M3-EAGLE3`, `MiniMax-M3-EAGLE3-GQA`), which would match one drafter entry of the served model uniquely, but that is a guess from a file name and the dashboard does not make it. It needs a ruling, or the recipe's own statement of the draft repository in the pull.

## The after run

`docs/m2/after-run.sh` is the command, with the pins it needs: the simulator commit (PR 4 and PR 5), the substrate commit, the blis-vllm commit whose `fields.json` the simulator's engine carries, the baseline's frozen pull (not committed) and the corpora. `run.sh` accepts the catalog and registry pins as a release tag or a full 40-hex commit, so the script passes the substrate commit; a figure whose data is pinned by commit is experimental.
