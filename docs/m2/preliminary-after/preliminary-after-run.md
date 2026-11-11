# Preliminary after-run

**PRELIMINARY.** The pins are commits that will move, so the figures are marked experimental and will be run again at the final pins. They are an in-sample rescoring of the same 1734 points, not a held-out result, and the per-split figures use the development split (`evaluation-protocol.md`), not the ledger's held-out.

## Inputs

| Input | Value |
|---|---|
| Harness | accuracy-dashboard commit `10b2a36cb91d4c65dd9096d5f4689f3e80ec93b0` (the baseline was scored again at the same commit) |
| Simulator | inference-sim `ece61af0eccb863ba527d9e1a6dd2ffc97d0c5cf` (branch `m2/5-closeness-data-in-the-result`, a local checkout; `run.sh --sim-repo` takes the path) |
| Catalog and registry | blis-substrate `f70c6c7503a47442c4c5d989f8f17b093c14e069`, passed as the 40-hex commit for `--catalog-release` and `--registry-release` |
| Engine | vLLM 0.32.0; field list: blis-vllm `5de11f598bf78017429355b368bbb7a93e312ef1` `fields.json`, sha256 `9a3a88857a9462caf7b09433cfb53ac377d042aea10e7da2af3a8f9fd1ecccaa` |
| Pull, units, point set | as the baseline: manifest `c8f2ea928b0d4582afdc3fbf11ef9d6847a359791a520f497ee146e806a96166`, 1734 points |
| Corpora | as the baseline |

Command: `harness/run.sh --sim ece61af0eccb863ba527d9e1a6dd2ffc97d0c5cf --sim-repo <inference-sim checkout> --units units.txt --pull <pull> --out <out> --catalog <substrate>/catalog --registry <substrate>/registry --corpus-dir <corpora> --fields fields.json --catalog-release f70c6c75... --registry-release f70c6c75...` (full commits in the files above). Wall time 130 s, peak memory 1.8 GB (the baseline: 45 s, 1.8 GB). The table is `table.md`, made with `compare.py pair`.

## Result

| | Before (v0.16.0) | After (this simulator) |
|---|---|---|

| Scored | 41 | 110 |
| Reached the simulator and refused | 10 | 791 |
| Not scored (G5) | 1683 | 833 |
| Accuracy, all scored | TTFT MAPE 31.0 (n=41), shape 18.6 (n=33); TPOT MAPE 16.7, shape 10.9 | TTFT MAPE 30.8 (n=110), shape 17.4 (n=92); TPOT MAPE 17.7, shape 15.3 |

All scored points in both runs are G4 (no point is measured on the simulator's engine release and four G1 conditions are unevaluated), so there is one grade to compare. Points scored in both runs (41): before TTFT MAPE 31.0 (n=41), shape 18.6 (n=33); TPOT MAPE 16.7, shape 10.9; after TTFT MAPE 30.4 (n=41), shape 18.4 (n=33); TPOT MAPE 15.2, shape 11.7. Newly scored: 69 points (TTFT MAPE 31.1 (n=69), shape 16.9 (n=59); TPOT MAPE 19.2, shape 17.3). Newly refused: 0.

In scope, the baseline scored 41 of 1188 points and this run 110; the 546 AMD points are out of scope (no catalog part) and are in no figure above except the totals. `table.md` has the coverage movement per reason, the figures per serving (all aggregated) and per split.

## What the simulator refuses: the next work list

791 points pass the dashboard's checks and the simulator refuses them. The first error of each, grouped (35 more refusals are not in this table: they are recorded as not scored, see item 4):

| Points | First error |
|---|---|
| 313 | compilation_config.custom_ops is stated as "all", and the registry has no measurement that prices it, so the k |
| 117 | the deployment names draft_model minimax-m3-eagle3 and the target graph minimax-m3 already states a speculator |
| 116 | the deployment names draft_model minimax-m3-eagle3 and the target graph minimax-m3-mxfp8 already states a spec |
| 77 | compilation_config.custom_ops is stated as "none", and the registry has no measurement that prices it, so the  |
| 68 | quantization "modelopt_mixed" is stated: it names a ModelOpt MIXED_PRECISION checkpoint, whose per-layer algor |
| 56 | the deployment names draft_model minimax-m3-eagle3-gqa and the target graph minimax-m3-mxfp8 already states a  |
| 44 | compilation_config.custom_ops is stated as "+quant_fp8,none,+quant_fp8", and the registry has no measurement t |

The full error of each refused point is in `refusals.json` (point id to text). The groups, in the order of the work they ask for:

1. **`compilation_config.custom_ops` (434 points: "all" 313, "none" 77, "+quant_fp8,none,+quant_fp8" 44).** The kernel will not price a custom-ops setting it has no measurement for (blis-registry#71). The run stated it; the dashboard writes what the run recorded. Either the registry measures the setting or the field is declared inert for pricing.
2. **A draft model named while the target graph already states a speculator (289 points: minimax-m3-eagle3 233, -gqa 56).** BLIS runs one drafter. The scenario names the EAGLE3 drafter; the target's graph also carries its own MTP speculator. The catalog or the scenario writer must tell BLIS which one this run used.
3. **`quantization "modelopt_mixed"` (68 points).** A ModelOpt mixed-precision checkpoint whose per-layer algorithms the catalog graph does not place.
4. **MTP acceptance (35 points, DeepSeek-V4-Pro on h200, 2 MTP tokens).** The simulator says the workload states no thinking mode, which selects the registry's acceptance profile. The committed contract of this run records them as G5 `field_not_in_release:thinking`: the dashboard's `value_refusal` read "states no thinking" as a missing engine field. That mapping is fixed since (the reason is now `value_not_recorded:workload.thinking_mode`, with a test); the contract here was scored before the fix and is not rerun, so it keeps the old reason. The need itself is a thinking-mode statement in the workload (or an acceptance override), a design question for the workload.

## Residuals

The systematic biases on the train split are in `residuals.md`: it reads train points only (89 of the 110), groups them by model, hardware, precision, concurrency band, serving, speculation and regime, and lists the ten largest with a hypothesis each. Validation and test points were not read for it.

## What this does not show

The per-split figures use the development split, whose test set is `development split, not the ledger's held-out`. The 110 scored points are 9 train series, a few validation series and some test series; the test figures are withheld in `table.md` (they are logged when evaluated). No kernel hash is evaluated (no source maps a library version to a hash), so no point is G1 or G3. These are experimental figures at commit pins.
