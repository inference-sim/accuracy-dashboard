# The after run: the command and what it needs

`docs/m2/after-run.sh` is the whole run. It needs these pins:

| Parameter | What | State |
|---|---|---|
| `SIM` | the inference-sim commit with PR 4 (`fields`, `ledger`, `metrics`) and PR 5 (Result data), as a 40-hex commit or release tag | `a8bc3085a7c91c50a1d92862943a695c04adfe11`, the head of inference-sim's combined pull request (branch `m2/combined-layers`); its release tag replaces it once cut (the tag names the merged tree, so the figures do not change; see "Repin to release tags" below) |
| `SUBSTRATE` | blis-substrate release `v0.14.0` (also recorded as `--catalog-release` and `--registry-release`) | `v0.14.0`, commit `965b05834c47882bc0f9f1a960c90327a756ef3d`, the release the pinned simulator's `stack.json` names |
| `BLIS_VLLM` | the blis-vllm commit whose `fields.json` the simulator's engine carries | `df9641b2f6c5782aa7987392f6d979e238ebe1ed`, the commit the pinned simulator's `stack.json` resolves (sha256 of its `fields.json` `62743b57746f8376b291fdb853eb0eb19edacc5d717e1e7107d6e0f3ed41348d`) |
| `PULL` | the baseline's frozen pull: manifest sha256 `c8f2ea928b0d4582afdc3fbf11ef9d6847a359791a520f497ee146e806a96166`, kept on the machine that froze it (60 MB; not committed) | present at `/tmp/baseline/pull2` on this machine |
| `CORPUS` | the corpora, fetched with `orchestrator/resolve_agentic_corpus.py --all --catalog SUBSTRATE_CHECKOUT/catalog -o CORPUS` | `/tmp/baseline/corpus` |
| `WORK` | scratch space | any |

```
cd accuracy-dashboard-wt-m2
SIM=a8bc3085a7c91c50a1d92862943a695c04adfe11 SUBSTRATE=v0.14.0 BLIS_VLLM=df9641b2f6c5782aa7987392f6d979e238ebe1ed \
PULL=/tmp/baseline/pull2 CORPUS=/tmp/baseline/corpus WORK=/tmp/after-work \
bash docs/m2/after-run.sh
```

It runs `harness/run.sh` from a checkout of the harness commit the baseline records, over the baseline's `units.txt` and pull, and writes `docs/m2/before-after.{json,md}` with `compare.py pair`, which refuses two harness commits, unit sets, pull sets or point sets, and an in-sample table beside a held-out one.

**Two things can stop it.** (1) If the after run needs a harness change (anything under `harness/`, `orchestrator/` or `schemas/`), the baseline must be scored again at the new commit first, with its own pins (inference-sim v0.16.0, blis-substrate v0.13.0, blis-vllm v0.32.0-blis.2, `/tmp/baseline/run-baseline.sh` as committed in `docs/m2/baseline-v0.16.0/run-baseline.sh`). (2) The pull's 60 MB of artifacts expire on GitHub after 90 days; the local copy does not.

The after run is the same units over the same pull, so it states a rescoring, not a new measurement; `in_sample` stays the label until the anchor list exists.

## Repin to release tags is pin-only

The three upstream builds the `simulator` job tests against are named in `.github/stack-pins.env` (`SIM_REF`, `SUBSTRATE_REF`, `ROUTER_REF`), each a 40-hex commit or a release tag. That file is not one of the scorer's files (`harness/`, `orchestrator/` outside `baseline/`, tests, test data and the boundary lint, `schemas/`, `requirements-ci.txt`: `orchestrator/baseline/test_contracts_current.py`), and `harness/harness.pin` holds only the Go release. So replacing a pinned commit by the release tag cut at the same content changes no scorer file and leaves every committed contract current; `test_moving_an_upstream_pin_does_not_make_a_contract_stale` keeps it so.

At the tags, change exactly these lines, and no other:

| File | Line | From | To |
|---|---|---|---|
| `.github/stack-pins.env` | `SIM_REF=` | `a8bc3085a7c91c50a1d92862943a695c04adfe11` | `v0.17.0` (done; it differs from that commit by the pin-only commits that moved blis-vllm and the router to their tags) |
| `.github/stack-pins.env` | `ROUTER_REF=` | `2a886db5d1be70aa2ae18a7dbed81f5e1cdbd1f8` | `v1.0.0-blis.4` (done) |
| `.github/stack-pins.env` | `SUBSTRATE_REF=` | `965b05834c47882bc0f9f1a960c90327a756ef3d` | `v0.14.0` (the same commit; already done) |
| `docs/m2/h200-v033/pins.env` | `BLIS_SUBSTRATE_COMMIT=` | `965b05834c47882bc0f9f1a960c90327a756ef3d` | unchanged: it is the commit of the tag `v0.14.0` |
| this page, `docs/reproducing.md`, `docs/m2/pd-coverage.md`, the READMEs of the runs | the inference-sim commit in the pin tables and in the example commands | `a8bc3085...` | the tag, with the commit it names |

Two conditions make it pin-only. (1) The tag must name a tree equal to `a8bc3085a7c91c50a1d92862943a695c04adfe11` (`git diff --stat a8bc3085a7c91c50a1d92862943a695c04adfe11 <tag>` is empty): a merge or squash commit changes the hash and not the tree. (2) The committed contracts keep `blis.commit_sha` = `a8bc3085...`, the build that scored them; that is true of the run and stays so. If the tag's tree differs, the five runs are scored again (the commands of `reproducing.md`) and the pin change is not pin-only.
