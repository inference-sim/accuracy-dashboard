# The evaluation protocol: a development split

**This is a development split. It is the dashboard's own, separate from the ledger's official anchor list** (design D7 and COV-2: roles drawn from a seed that no candidate job can read), which stays the ledger owners'. Every report that uses it says *development split, not the ledger's held-out*, as the in-sample label does today. Its purpose is to let estimators and hyperparameters be chosen without looking at the data they are judged on, and to make any peeking visible.

Code: `orchestrator/baseline/split.py` (assignment, folds, the published list, the citation check), `ranking.py` (ranking metrics), `compare.py` (per-split reporting, the evaluation log), `residuals.py` (analysis on the train split). Tests: `test_split.py`, `test_compare.py`, `test_residuals.py`.

## 1. The group is the deployment shape

A **group** is an InferenceX deployment shape: its model, hardware, precision, framework, speculation method and disaggregation flag, six values (the code calls a group's id a *series id*, `split.series_id`). Every point of a group has the same split, whatever its concurrency, ISL, OSL, image or benchmark type, except for the prospective rule below. A group is written as the JSON array of those six values in that order, for example `["minimaxm3","b200","fp8","vllm","none",false]`.

**Why not finer.** The first version of this split keyed on the image, ISL, OSL and benchmark type as well, so that a series was one workload on one image. Then 127 of the 278 model/hardware/precision/framework groups had points in more than one split: a test point was often the same model on the same chip and engine at another ISL/OSL or image as a train point. That makes the test set a test of interpolation across workload and image for a deployment the fitters have seen, not of a deployment they have not. A test that asks whether the simulator predicts a model/hardware/precision/framework/speculation/serving combination nobody fitted on needs the coarser group, so that is the group. The cost is that the groups are few (404 in the API window) and unevenly sized, so a split by group is lumpy: one group of a hundred points moves the proportions of the points.

## 2. Deterministic assignment

`bucket = int.from_bytes(sha256(SALT + b"\0" + series_id)[:8], "big") % 100`, with the salt `blis-dev-split-2`. Below 60 is **train**, below 80 **validation**, otherwise **test** (60, 20 and 20 percent of the groups). The salt, the cut-offs and the field list are constants in `split.py`, and `test_split.py` pins them and the split of known groups: changing any of them changes the split and fails the test. For example, the group above has bucket 74, so it is validation; the same group on h200 has bucket 7, so it is train. The salt changed from `blis-dev-split-1` with the definition of the group, so no earlier assignment carries over.

## 3. The prospective test

A point **measured after 2026-11-09** (`FREEZE_DATE`, the date of the frozen pull) is **prospective**: it is test whatever its series hashes to, is never used in any fit or selection, and is reported apart. `split.kind_of(series, measured_date)` returns `train`, `validation`, `test` or `prospective`. As of 2026-11-11 the API window holds 168 rows dated 2026-11-10 or 2026-11-11 (99 and 69), all agentic traces, 130 on in-scope chips. None has a ledger unit yet (the ledger's source revision is older), so none can be scored; they are the prospective set when a ledger release holds them.

## 4. Model selection

Estimator choice and hyperparameters are selected by **leave-one-group-out cross-validation over train and validation series only** (`split.logo_folds`): each fold holds out one series and fits on the others; test and prospective points are dropped before any fold exists. Only train points may feed a fit (`usable_for_fit`); train and validation may feed a selection (`usable_for_selection`). The test set is evaluated **once per candidate release**, and every evaluation is logged: `compare.py ... --evaluate-test --log docs/m2/evaluation-log.md --estimator NAME` appends a row (date, harness commit, estimator, split, points, scored points). Without `--evaluate-test` the report withholds the test and prospective figures, so a table cannot show them by accident; `--evaluate-test` without a log and an estimator is refused. The log is [evaluation-log.md](evaluation-log.md).

## 5. What the registry's fitters may read

Kernel sweeps and forward-pass measurements are train-only inputs to coefficient fitting; InferenceX end-to-end rows may be used to calibrate a residual term only if they are in the train split. The fitters must never read a validation or test series.

- **The function.** `split_of(series)` (Python) gives the split of a series; the rule above is three lines to copy.
- **The published list (the cleaner route under X7).** `docs/m2/series-split.json` lists every series of the API window with its split, its row ids and its workflow run ids, with the salt, the cut-offs and the freeze date. A registry script reads the JSON at a pinned commit of this repository; it imports no dashboard code, and the dashboard reads no registry file. `split.py check-list` verifies a list against the rule; the committed one is generated by `split.py list --rows ROWS.json --out FILE` from the window's rows and checked by a test.
- **The citation check.** `split.py check-registry --registry DIR --list FILE` fails if a coefficient entry's `sources[].cite` names an InferenceX benchmark row (`row 123456`) or, in a citation that names InferenceX and not CollectiveX, a workflow run, of a validation or test series. It is meant to run in the registry's CI against the pinned list (the registry cites rows and runs in free text, so the check reads those two forms; a citation in another form is not seen).

## 6. Reporting

**The test split is withheld from every figure, not only from its own row.** Unless a logged test evaluation is asked for (`--evaluate-test`), every accuracy figure of a report (the headline, each grade, the attribution tables, the both-scored and newly-scored comparisons, the per-split rows) is computed over the train and validation points only, and says how many scored points it left out (`withheld`). A figure over all scored points next to figures for train and validation would let the test figure be derived by subtraction. Counts of points (how many are scored, how many are G5, per reason) are not accuracy figures and include every point. The committed `contract/points.csv` of a run still holds every point's prediction and measurement: the contract is data, and the protection of the test set from selection is the log and review (section 8), as before.

`compare.py` reports every figure per split (train, validation, test, prospective, and *unassigned* for a point with no known series) and per grade, with n, and shows *too few points* under ten points as everywhere else. It refuses a table labelled *held-out* if any point is not a test or prospective point, and `held_out_figure` refuses a figure that includes a train point. Note the label: `held_out` in these tables means the ledger's anchor list; a development-split test figure is never called that.

Split sizes on the frozen pull (1734 points, the baseline's point set; groups are those that hold a point of the pull):

| Split | Points | In scope | Groups | Baseline scored | Preliminary after-run scored |
|---|---|---|---|---|---|
| train | 956 | 626 | 33 | 0 | 286 |
| validation | 332 | 220 | 9 | 11 | 75 |
| test | 446 | not shown | not shown | 30 | 89 |
| prospective | 0 | 0 | 0 | 0 | 0 |

The scored counts of the test row follow from the totals (41 and 450 scored, less the other splits), and a count is not an accuracy figure; what is withheld is how accurate those points are. The groups are few and uneven (one group can hold a hundred points), so the split by points is 55% train, 19% validation and 26% test of the pull, not 60/20/20; the 60/20/20 is of groups.

Every scored point is G4, so each split has one grade today.

## 7. Metrics

**Accuracy**: MAPE and shape of TTFT and TPOT, as the [overview](../overview.md) defines them.

**Ranking** (`ranking.py`): configuration search asks which of several configurations is best, and MAPE does not say whether the order is right.

- *Group*: the scored points of one (model, hardware, ISL, OSL); the configurations are its points, which differ in concurrency, parallelism, engine, precision and speculation. A group needs at least three points.
- *Value*, computed the same way from measured and predicted figures: request latency `L = TTFT + (OSL - 1) * TPOT`; throughput per GPU `T = concurrency * OSL / L / GPUs`; SLO goodput `T` if `TPOT <= SLO_TPOT` and `TTFT <= SLO_TTFT`, else 0.
- *Per group*: Spearman rank correlation of predicted against measured value (ties get the mean rank); Kendall tau-b; **top-1** (1 if the predicted-best configuration is the measured-best one); **top-3** (1 if the measured-best configuration is among the three predicted-best); **regret** `(best measured - measured value of the predicted-best) / best measured`. Ties for best break by the configuration key.
- *Over groups*: the mean of each, with the number of groups; fewer than ten groups reads *too few groups*.

Worked example, one group with OSL 100 and one GPU except where stated. Times in microseconds:

| Configuration | Concurrency | GPUs | Measured TTFT / TPOT | Predicted TTFT / TPOT | Measured T | Predicted T |
|---|---|---|---|---|---|---|
| c4 | 4 | 1 | 8000 / 4000 | 9000 / 5000 | 990.1 | 793.7 |
| c16 | 16 | 1 | 10000 / 5000 | 11000 / 5500 | 3168.3 | 2880.3 |
| c64 | 64 | 1 | 30000 / 9000 | 25000 / 8000 | 6949.0 | 7833.5 |
| tp2c64 | 64 | 2 | 25000 / 6000 | 28000 / 7000 | 5169.6 | 4438.3 |
| c256 | 256 | 1 | 90000 / 30000 | 150000 / 50000 | 8366.0 | 5019.6 |

Measured order (best first): c256, c64, tp2c64, c16, c4. Predicted order: c64, c256, tp2c64, c16, c4. Spearman 0.9, Kendall 0.8, top-1 0 (the model picks c64, the measured best is c256), top-3 1, regret `(8366.0 - 6949.0) / 8366.0 = 0.169`: the configuration the model picks is 17 percent worse than the best. `test_split.py::test_the_worked_example_of_the_protocol` pins these numbers.

## 8. What is not held out

The ledger's anchor list, when it is published, is the only held-out set. Until then no figure here is held-out; the development test set is a check that stops the analyst from fitting what they judge on, not evidence about unseen data. The salt is in the repository, so an analyst who wanted to could read the test series: the protection is the log and review, not secrecy.
