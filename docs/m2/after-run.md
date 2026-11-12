# The after run: the command and what it needs

`docs/m2/after-run.sh` is the whole run. It needs these pins, none of which exists yet except the baseline:

| Parameter | What | State |
|---|---|---|
| `SIM` | the inference-sim commit with PR 4 (`fields`, `ledger`, `metrics`) and PR 5 (Result data), as a 40-hex commit or release tag | `c97c497b104a556515717599a4468352c1234d28` (branch `m2/11-router-configs-command`) |
| `SUBSTRATE` | the blis-substrate layer 10 tip (a 40-hex commit; also recorded as `--catalog-release` and `--registry-release`) | `6faaccf8f1a2344918241d6b54fe339de44f7345`, the commit the pinned simulator's `stack.json` resolves; a pin by commit makes the figure experimental |
| `BLIS_VLLM` | the blis-vllm commit whose `fields.json` the simulator's engine carries | `28deab082a2fba6762b922c64c7b5b81b7eeac8e`, the commit the pinned simulator's `stack.json` resolves (sha256 of its `fields.json` `2a84767a67027a9237934038a513252d7ed65cf8ff8ee203cad8fc0a8c51cc39`) |
| `PULL` | the baseline's frozen pull: manifest sha256 `c8f2ea928b0d4582afdc3fbf11ef9d6847a359791a520f497ee146e806a96166`, kept on the machine that froze it (60 MB; not committed) | present at `/tmp/baseline/pull2` on this machine |
| `CORPUS` | the corpora, fetched with `orchestrator/resolve_agentic_corpus.py --all --catalog SUBSTRATE_CHECKOUT/catalog -o CORPUS` | `/tmp/baseline/corpus` |
| `WORK` | scratch space | any |

```
cd accuracy-dashboard-wt-m2
SIM=c97c497b104a556515717599a4468352c1234d28 SUBSTRATE=6faaccf8f1a2344918241d6b54fe339de44f7345 BLIS_VLLM=28deab082a2fba6762b922c64c7b5b81b7eeac8e \
PULL=/tmp/baseline/pull2 CORPUS=/tmp/baseline/corpus WORK=/tmp/after-work \
bash docs/m2/after-run.sh
```

It runs `harness/run.sh` from a checkout of the harness commit the baseline records, over the baseline's `units.txt` and pull, and writes `docs/m2/before-after.{json,md}` with `compare.py pair`, which refuses two harness commits, unit sets, pull sets or point sets, and an in-sample table beside a held-out one.

**Two things can stop it.** (1) If the after run needs a harness change (anything under `harness/`, `orchestrator/` or `schemas/`), the baseline must be scored again at the new commit first, with its own pins (inference-sim v0.16.0, blis-substrate v0.13.0, blis-vllm v0.32.0-blis.2, `/tmp/baseline/run-baseline.sh` as committed in `docs/m2/baseline-v0.16.0/run-baseline.sh`). (2) The pull's 60 MB of artifacts expire on GitHub after 90 days; the local copy does not.

The after run is the same units over the same pull, so it states a rescoring, not a new measurement; `in_sample` stays the label until the anchor list exists.
