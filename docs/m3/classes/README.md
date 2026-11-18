# The classes page

The dashboard counts four classes of points apart. No class is added into another's counts. The classes come from different scoring runs: the regular class is the nightly's summary, the others are the final census's runs, and the SGLang class's points overlap in part with the SGLang points the summary lists as not scored. The regular card says so beside its SGLang row.

| Class | What it is | Grades | Where its numbers come from |
|---|---|---|---|
| InferenceX, regular recipes | Every InferenceX point whose launch the run recorded, vLLM and SGLang. | G1 to G4, or G5 with a named reason | `data/latest/summary.json`, the nightly's own run. The headline is this class. |
| InferenceX, SGLang (final census) | The SGLang points the final census scored (train and validation only), until the nightly's own summary scores SGLang points. | G1 to G4, or G5 with a named reason | `data/supplemental/classes/sglang.json` |
| InferenceX, reconstructed recipe | Llama-3.3-70B InferenceX points whose launch the run did not record; the recipe was reconstructed from the model's published configuration. | G4 at best, with the substitutions that say so | `data/supplemental/classes/inferencex-reconstructed.json` |
| Red Hat configiq | The configiq dataset, scored by simulation (see [configiq scored by simulation](../configiq/README.md)). | Provisional, capped at G3 | `data/supplemental/classes/configiq.json` |

The summary builder refuses a contract that carries the reconstructed-recipe marker, so that class cannot reach the headline.

## Where `classes.json` comes from

`data/latest/classes.json` (format `classes-1`, schema [classes.v1.schema.json](classes.v1.schema.json)) is built by `orchestrator/build_classes.py build` from the night's `summary.json` and the files under `data/supplemental/classes/`, and from nothing else. The nightly runs it with no GPU, cluster or census step: no configiq or reconstructed-recipe point is scored there.

Each file under `data/supplemental/classes/` is derived once from a scoring run's output, holds derived values only (counts and errors, no raw data), and records in `provenance` the command that made it, the heads it ran at and the date of the data it read. A file made from a census that is not the final one carries `"interim": true`, and the page says so.

```
python3 orchestrator/build_classes.py derive-contract CONTRACT_DIR --id inferencex-reconstructed --label L --note N --meta META.json --interim --out data/supplemental/classes/inferencex-reconstructed.json
python3 orchestrator/build_classes.py derive-contract CONTRACT_DIR --kind regular --id sglang --label L --note N --meta META.json --itl-json itl.json --pull-manifest manifest.json --out data/supplemental/classes/sglang.json
python3 orchestrator/build_classes.py derive-configiq SCORE_DIR    --id configiq --label L --note N --meta META.json --interim --out data/supplemental/classes/configiq.json
python3 orchestrator/build_classes.py build
python3 orchestrator/build_classes.py check data/latest/classes.json
```

## What each figure means

* Accuracy by grade is the mean absolute percent error (MAPE) and the signed median error of the simulator's TTFT and TPOT against the measurement, over the graded points of that grade. A figure over fewer than 10 points reads "too few points" (COV-11).
* configiq's card shows the rows in the dataset, the rows scored and the partition (train and validation are simulated; the test partition is withheld), and one plain line for the rows that are not scored. It lists no refusal. Its accuracy is TPOT (GuideLLM's median, which counts the first token) and ITL (its mean: the per-request time per output token after the first), by grade and by model. A model whose error is larger because of the simulator, not the data, is labelled as such.
* configiq's first-token time (TTFT) is not shown as an accuracy figure, because its definition (client-side delay) is unconfirmed. That rule was fixed on the clarity of the data, before any error was looked at; the class's `figure_notes` says it and nothing else is hidden.
* A refusal reason with fewer than 6 points is counted under "other settings" of its code instead of being listed by name; its points stay in the refused count.
