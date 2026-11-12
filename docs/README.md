# Documentation of the BLIS accuracy dashboard

The dashboard asks one question of every InferenceX benchmark point it can read: if BLIS were given the deployment the run recorded, how close would its predicted time to first token (TTFT) and time per output token (TPOT) be to the measured ones, and how close is that comparison to the real run? These pages say how the answer is produced, how to reproduce it, what it shows and what it does not. They are plain markdown; read them in this order, or jump to the one you need.

| Page | What it answers |
|---|---|
| [Overview](overview.md) | What is measured, end to end, in one page. |
| [The scoring pipeline](scoring-pipeline.md) | From the InferenceX API to a point's TTFT and TPOT: ingest, freezing a pull, recipes and checkpoints, ledger units, `harness/run.sh`, the replay, the harness commit. |
| [Closeness grades](closeness-grades.md) | G1 to G5 in prose: each condition, each G5 reason and how it is removed, what an unevaluated condition is, what the Result must carry. |
| [The grade tables, generated](grades.md) | The same grades and reasons, generated from `grade.py` (do not edit). |
| [Coverage accounting](coverage-accounting.md) | Reasons, blocks, alone and demotes; in scope and out of scope; the field-list gate; the label-record rule; estimation rules. |
| [The evaluation protocol](m2/evaluation-protocol.md) | The development split, selection, the evaluation log, ranking metrics. |
| [The evaluation log](m2/evaluation-log.md) | Every evaluation of a test set. |
| [Reproducing the baseline and the after run](reproducing.md) | Every pin by hash, the commands, environment, expected counts, cost, and what cannot be reproduced. |
| [Does the dashboard compare like with like?](comparability.md) | Dimension by dimension: how InferenceX measured, how the dashboard and BLIS rebuild it, whether they agree, which differences a point names and which it does not, how to reproduce the checks. |
| [Reading the before/after report](before-after.md) | How to read `table.md`; the baseline and the preliminary after-run. |
| [The substrate point record](pointrecord.md) | `pointrecords.jsonl`: how each point is written under the substrate's names, what it cannot yet say, how it is tested. |
| [Disaggregated serving and routers](disaggregation.md) | How prefill/decode points are written as two pools, the named refusals, the recipe the pools' arguments come from, the router table and the router substitution. |
| [Coefficients](coefficients.md) | How the cost model's coefficients are produced and graded, with links to the substrate's pages. |
| [Limits and known gaps](limits.md) | What the numbers do not show. |
| [RFC 0001](RFC-0001.md) | The founding design of the dashboard's web page. |

## Reports and evidence under `m2/`

| Page | Content |
|---|---|
| [The baseline, v0.16.0](m2/baseline-v0.16.0/README.md) | Inputs by commit, commands, cost, result, and the committed [table](m2/baseline-v0.16.0/table.md). |
| [The preliminary after-run](m2/preliminary-after/preliminary-after-run.md) | The after-run at commit pins, its [table](m2/preliminary-after/table.md), the simulator's refusals and the [train-split residuals](m2/preliminary-after/residuals.md). |
| [After-run command](m2/after-run.md) | The command and pins for the final after-run ([script](m2/after-run.sh)). |
| [An agentic replay, end to end](m2/agentic-replay-check.md) | The idle cap and the warm-up reach the M2 simulator and change its window and request count; the run's output. |
| [InferenceX series classes](m2/series-classes.md) | What the harness does with each series class. |
| [Gate with blis-vllm's classification](m2/gate-real-fields.md), [dry run](m2/dry-run-field-gate.md) | How many points reach the simulator when the field list is opened. |
| [Local-path checkpoints](m2/local-path-checkpoints.md), [node size of b200/h200](m2/node-size-b200-h200.md) | Two decisions with their evidence. |
| [Prefill/decode coverage](m2/pd-coverage.md) | What the two-pool writer scores on the data-parallel-free Dynamo rows, at what error, what is refused and why; the commands. |
| [Workload statements](m2/workload-statements.md) | What each benchmark family states about the workload's category and thinking mode, which profile pairs the substrate holds, and how many points each unlocks. |
| [Who owns the router policies](m2/policy-table-owner.md) | The policy list and compositions are the substrate router table's; the check that the dashboard's copy matches, and what the owner does not yet state. |
| [Agentic coverage](m2/agentic-coverage.md) | The 47 agentic points: each one's first refusal and the field that blocks it. |
| [DeepSeek-V4.1-Flash on H200, vLLM v0.33.0](m2/h200-v033/README.md) | Sixteen rows newer than the ledger: how they are pinned and split, what BLIS refuses for them by name, and a dry run of their accuracy. |
| [Dynamo router evidence](m2/dynamo-router-evidence.md) | What router the Dynamo runs used. |
| [The dashboard against the final substrate](m2/final-catalog-check.md) | Names the code reads, checked at the audited substrate stack. |

Design terms (D7, COV-2, X8, X19 and the like) are the numbered rules of the BLIS design document; the pages say what each one means where it is used.
