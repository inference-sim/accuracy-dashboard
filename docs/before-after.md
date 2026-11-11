# Reading the before/after report

`compare.py pair --before DIR --after DIR --sample in_sample` writes `table.json` and `table.md`; the committed ones are [the baseline's own table](m2/baseline-v0.16.0/table.md) and [the preliminary after-run's](m2/preliminary-after/table.md). It refuses, with the reason, two runs that differ in harness commit, units, pull or point set (a table that mixed them would measure the difference, not the change), and a held-out label over points that include a train point.

## The sections, in order

1. **The label and the identities.** *In-sample* says no point is held out. The harness commit, the SHA-256 of the units file, of the pull manifest and of the sorted point ids, and the point count; then the simulator, the field-list hash, and whether the figures are experimental.
2. **Headline.** MAPE and shape of TTFT and TPOT over every scored point (G1 to G4), each with n. The noise floor is the documented fallback (1.6 percent); summary v3 measures none per point.
3. **Accuracy apart from coverage.** Four rows: points scored in both runs (before and after) and the points scored in one run only. Read this first: more points scored cannot hide a loss of accuracy on the points that were already scored, and a gain of accuracy on a few points cannot hide a loss of coverage.
4. **By grade.** For each of G1 to G5: points, share of all and of graded, and accuracy of that grade on its own. A share over fewer than ten points reads *too few points*.
5. **By serving.** The same per grade, apart for aggregated and disaggregated points (so a change in prefill/decode modelling shows).
6. **Development split.** Every figure for train and validation; test and prospective are *withheld* unless the table was made with `--evaluate-test`, which logs the evaluation ([protocol](m2/evaluation-protocol.md)). Ranking quality is in the last column.
7. **Coverage.** Scored, not scored, failed, and share scored for all points, in-scope points and out-of-scope points, with the out-of-scope points by chip, and per reason the blocks and alone before and after with the change.
8. **Attribution.** For the points scored in both runs, MAPE before and after by model, chip, precision, speculation, engine and serving.
9. **The backlog and the unlock table** (blocks, alone, demotes per entry; in-scope blockers ranked), then the lists of newly scored and newly refused points. The simulator's first error for each refused point is in the run's `refusals.json`.

## The baseline and the preliminary after-run, in numbers

| Run | Scored | Refused by the simulator | Not scored (G5) | TTFT MAPE | TPOT MAPE |
|---|---|---|---|---|---|
| Baseline: inference-sim v0.16.0, substrate v0.13.0 | 41 | 10 | 1683 | 47.1 (n=11) | 58.0 (n=11) |
| Preliminary after-run: M2 simulator at commit pins | 450 | 117 | 1167 | 34.0 (n=361) | 17.7 (n=361) |

All scored points are G4. The accuracy columns are over the train and validation points only (the test split is withheld from every figure, `m2/evaluation-protocol.md` section 6), so the baseline's rest on eleven. The after-run is preliminary (commit pins, to be re-run at the final ones) and in-sample. The 406 refusals and what each asks for are in [its report](m2/preliminary-after/preliminary-after-run.md); the final after-run replaces it when the pins exist ([command](m2/after-run.md)). The residuals that point to where the model is wrong are on the train split only: [residuals](m2/preliminary-after/residuals.md).

## What a table does not show

A table over the same point set is a rescoring, not a new measurement. It says nothing about points the ledger does not hold, and it does not say how the model would do on data it was not tuned against until an anchor list exists.
