# The classes page

The dashboard counts three classes of points apart. A point is in exactly one class, and no class is added into another's counts.

| Class | What it is | Grades | Where its numbers come from |
|---|---|---|---|
| InferenceX, regular recipes | Every InferenceX point whose launch the run recorded, vLLM and SGLang. | G1 to G4, or G5 with a named reason | `data/latest/summary.json`, the nightly's own run. The headline is this class. |
| InferenceX, reconstructed recipe | Llama-3.3-70B InferenceX points whose launch the run did not record; the recipe was reconstructed from the model's published configuration. | G4 at best, with the substitutions that say so | `data/supplemental/classes/inferencex-reconstructed.json` |
| Red Hat configiq | The configiq dataset, scored by simulation (see [configiq scored by simulation](../configiq/README.md)). | Provisional, capped at G3 | `data/supplemental/classes/configiq.json` |

The summary builder refuses a contract that carries the reconstructed-recipe marker, so that class cannot reach the headline.

## Where `classes.json` comes from

`data/latest/classes.json` (format `classes-1`, schema [classes.v1.schema.json](classes.v1.schema.json)) is built by `orchestrator/build_classes.py build` from the night's `summary.json` and the files under `data/supplemental/classes/`, and from nothing else. The nightly runs it with no GPU, cluster or census step: no configiq or reconstructed-recipe point is scored there.

Each file under `data/supplemental/classes/` is derived once from a scoring run's output, holds derived values only (counts and errors, no raw data), and records in `provenance` the command that made it, the heads it ran at and the date of the data it read. A file made from a census that is not the final one carries `"interim": true`, and the page says so.

```
python3 orchestrator/build_classes.py derive-contract CONTRACT_DIR --id inferencex-reconstructed --label L --note N --meta META.json --interim --out data/supplemental/classes/inferencex-reconstructed.json
python3 orchestrator/build_classes.py derive-configiq SCORE_DIR    --id configiq --label L --note N --meta META.json --interim --out data/supplemental/classes/configiq.json
python3 orchestrator/build_classes.py build
python3 orchestrator/build_classes.py check data/latest/classes.json
```

## What each figure means

* Accuracy by grade is the mean absolute percent error (MAPE) and the signed median error of the simulator's TTFT and TPOT against the measurement, over the graded points of that grade. A figure over fewer than 10 points reads "too few points" (COV-11).
* configiq reports GuideLLM's statistics: TTFT and ITL are means; ITL is the per-request time per output token after the first, which the InferenceX harness calls TPOT. GuideLLM's own TPOT counts the first token and records no mean, so its median stands for it. Only the development split's train and validation points are simulated; the test split is withheld.
* configiq's mean TTFT is biased high; the cause is not yet explained, and the page says so rather than offering one.
