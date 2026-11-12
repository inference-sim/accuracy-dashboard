# Scored run (in-sample)

IN-SAMPLE: the points are the ones the model was calibrated on or tuned against; there is no anchor list yet, so no point is held out. These figures say how well the simulator reproduces data it has seen, not how well it predicts new data.

**Coverage counts include every point, the test split too, by design. Accuracy figures are over train and validation points only, with N stated.** 0 of the points are test or prospective and 0 of them are scored; those 0 are left out of every accuracy figure, so none can be derived by subtraction (docs/m2/evaluation-protocol.md section 6).

- harness commit `8170499e5026673be63c4f442057dcb3eee05ec4`
- units sha256 `a44e14f4d8d35e44a9c6586599ffdcc6d70a932566df3a4da51529aeaab1f0ca` (16 units)
- pull manifest sha256 `9e9588ad78ee04870416a0992c2e8eaba865fbf98e7f9b806bfef67eaca32a36`
- point set sha256 `fa56a43c439ff679d358a2649f94040e917d80279002cf6a0b54d72c651cf7b0` (16 points)

Simulator `780f661ef9c18a2a9928acf8a63a67667cd597c0`, engine {'kind': 'vllm', 'version': '0.32.0'}, fields sha256 `dbe9123a677792edf030a0da584b9fc915c45ec206a5cebbffc3944568b6e879`.

## Headline (G1 to G4)

| Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % | Noise floor % |
|---|---|---|---|---|---|
| 0 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) | 1.6 (fallback; none measured per point) |

## By grade

**All points**

| Grade | Points | Share of all | Share of graded | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|---|---|
| G1 | 0 | too few points | - | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G2 | 0 | too few points | - | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G3 | 0 | too few points | - | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G4 | 0 | too few points | - | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) |
| G5 | 16 | 100.0% | - | - | - | - | - |

**All scored points: each grade on its own, by serving (aggregated or disaggregated)**

| Serving | Grade | Points | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % |
|---|---|---|---|---|---|---|
| none scored | | | | | | |

## Development split

Per-split figures use the DEVELOPMENT split of docs/m2/evaluation-protocol.md, not the ledger's held-out: its test set is 'development split, not the ledger's held-out'.

Assignment: sha256 of the salt `blis-dev-split-2` and the series, mod 100; train below 60, validation below 80, test above; a point measured after 2026-11-09 is prospective (test).

| Split | Points | In scope | Scored | Series | Grades | TTFT MAPE % | TTFT shape % | TPOT MAPE % | TPOT shape % | Ranking (groups; Spearman, top-1, regret) |
|---|---|---|---|---|---|---|---|---|---|---|
| train | 0 | 0 | 0 | 0 |  | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) | 0; too few groups, too few groups, too few groups |
| validation | 16 | 16 | 0 | 1 | G5 16 | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) | 0; too few groups, too few groups, too few groups |
| test | 0 | | | | withheld: evaluate with `--evaluate-test`, which logs the evaluation | | | | | |
| prospective | 0 | | | | withheld: evaluate with `--evaluate-test`, which logs the evaluation | | | | | |
| unassigned | 0 | 0 | 0 | 0 |  | too few points (n=0) | too few points (n=0) | too few points (n=0) | too few points (n=0) | 0; too few groups, too few groups, too few groups |

## Coverage

Counts of every point, test included, by design.

| Set | Points | Scored | Not scored | Failed | Share scored |
|---|---|---|---|---|---|
| all points | 16 | 0 | 16 | 0 | 0.0% |
| in scope | 16 | 0 | 16 | 0 | 0.0% |
| out of scope (AMD, TPU) | 0 | 0 | 0 | 0 | - |

Out-of-scope points by chip: .

## What would unlock the rest

Blocks: in-scope points held at G5 by the blocker. Alone: points that would be scored if only it were fixed.

| Blocker | Blocks | Alone |
|---|---|---|
| field_not_in_release:env.PYTHONUNBUFFERED | 16 | 0 |
| field_not_modelled:env.VLLM_USE_RUST_FRONTEND | 16 | 0 |
| field_not_modelled:speculative_config.rejection_sample_method | 16 | 0 |
| out of scope (AMD, TPU) | 0 | 0 |

## Why points are below G1 or at G5 (design §11.6)

| Entry | Blocks | Alone | Demotes |
|---|---|---|---|
| `field_not_in_release:env.PYTHONUNBUFFERED` | 16 | 0 | 0 |
| `field_not_modelled:env.VLLM_USE_RUST_FRONTEND` | 16 | 0 | 0 |
| `field_not_modelled:speculative_config.rejection_sample_method` | 16 | 0 | 0 |
