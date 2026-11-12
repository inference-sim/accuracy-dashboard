# Preliminary after-run

**PRELIMINARY.** The pins are commits that will move, so the figures are marked experimental and will be run again at the final pins. They are an in-sample rescoring of the same 1734 points, not a held-out result, and every accuracy figure leaves out the scored test and prospective points of the development split (`evaluation-protocol.md`, section 6), which is not the ledger's held-out.

## Inputs

| Input | Value |
|---|---|
| Harness | accuracy-dashboard commit `0b8154ccefcb14311cf323e143d8520f59944fbb`; the baseline was scored again at the same commit |
| Simulator | inference-sim `ece61af0eccb863ba527d9e1a6dd2ffc97d0c5cf` (branch `m2/5-closeness-data-in-the-result`, a local checkout; `run.sh --sim-repo` takes the path) |
| Catalog and registry | blis-substrate `f70c6c7503a47442c4c5d989f8f17b093c14e069`, passed as the 40-hex commit for `--catalog-release` and `--registry-release` |
| Engine | vLLM 0.32.0; field list: blis-vllm `5de11f598bf78017429355b368bbb7a93e312ef1` `fields.json`, sha256 `9a3a88857a9462caf7b09433cfb53ac377d042aea10e7da2af3a8f9fd1ecccaa` |
| Pull, units, point set | as the baseline: manifest `c8f2ea928b0d4582afdc3fbf11ef9d6847a359791a520f497ee146e806a96166`, 1734 points |
| Corpora | as the baseline |

Command: `harness/run.sh --sim ece61af0eccb863ba527d9e1a6dd2ffc97d0c5cf --sim-repo <inference-sim checkout> --units units.txt --pull <pull> --out <out> --catalog <substrate>/catalog --registry <substrate>/registry --corpus-dir <corpora> --fields fields.json --catalog-release f70c6c75... --registry-release f70c6c75...`. The simulator has `blis metrics`, so the scorer checked that its TTFT and TPOT have the InferenceX client's definitions; the baseline's v0.16.0 has none.

## Result

| | Before (v0.16.0) | After (this simulator) |
|---|---|---|
| Scored | 41 | 450 |
| Reached the simulator and refused | 10 | 117 |
| Not scored (G5) | 1683 | 1167 |
| Accuracy, train and validation points | TTFT MAPE 47.1 (n=11), TPOT MAPE 58.0 | TTFT MAPE 34.0 (n=361), shape 17.6 (n=290); TPOT MAPE 17.7, shape 12.9 |
| Scored in both runs (41), train and validation | TTFT 47.1, TPOT 58.0 (n=11) | TTFT 24.1, TPOT 19.8 (n=11) |

All scored points in both runs are G4 (no point is measured on the simulator's engine release and four G1 conditions are unevaluated), so there is one grade to compare. The 41 and the 450 are counts of every scored point; the accuracy rows leave out 30 and 89 test points. Only 11 of the baseline's 41 points are train or validation, so its accuracy row rests on eleven points and says little about the baseline as a whole; it is the figure the protocol allows until a test evaluation is logged.

In scope, the baseline scored 41 of 1188 points and this run 450; the 546 AMD points are out of scope (no catalog part). `table.md` has the coverage movement per reason, the figures per serving (all aggregated) and per split.

## What the stated-only rule did

A value the engine only resolved, for a field it neither models nor proves inert, is recorded on the point and not stated in the scenario (`coverage-accounting.md`, "Resolved-only values"; design change merged as blis-design#3). This run applies it. The engine fills `compilation_config.custom_ops` with `all`, `none` or `+quant_fp8` in every log, and the kernel refused each as a stated value: 434 points, of which 340 are scored here; the printed `indexer_kv_dtype` of the DeepSeek-V4 and MiniMax-M3 logs, copied, was a second refusal behind it. The rule also leaves out `cudagraph_mode` and `cudagraph_capture_sizes` where only resolved, which the kernel does price although the field list calls them not modelled (blis-vllm#78): in a dry run, the DeepSeek-V4-Pro points on h200 moved by 5% to 16% in TTFT against a run that stated them.

## What the simulator refuses: the next work list

117 points pass the dashboard's checks and the simulator refuses them. The first error of each, grouped:

| Points | First error |
|---|---|
| 68 | quantization `modelopt_mixed` is stated: it names a ModelOpt MIXED_PRECISION checkpoint whose per-layer algorithms the catalog graph does not place |
| 49 | `minimax-m2.5-nvfp4` on compute capability 10.0 (26) or 10.3 (23) with a KV dtype of fp8 is not a combination the block-size oracle resolves |

The full error of each refused point is in `refusals.json` (point id to text). In the order of the work they ask for:

1. **`modelopt_mixed` (68 points).** A ModelOpt mixed-precision checkpoint (experts NVFP4, the rest MXFP8) with no catalog entry: the dashboard's mapping would price it as bf16, so the refusal is right until the catalog has the entry.
2. **Block size (49 points).** The oracle's table has no row for the NVFP4 sibling of `minimax-m2.5` (blis-vllm).
3. **Speculative runs whose workload states no category (382 points, [workload statements](../workload-statements.md)).** A speculative point whose acceptance length is neither pinned nor logged needs the workload's category and thinking mode to select the acceptance profile (design D8). The fixed-sequence InferenceX client sends random tokens and states no category, so these points are G5 `value_not_recorded:workload_category_not_stated` and do not reach the simulator. The simulator refused many of them for another reason in an earlier version of this run (a named draft model while the target graph already states a speculator); that is not known for them now, since they stop before the simulator. An earlier version of this run scored 80 DeepSeek-V4-Pro MTP points by stating thinking on and the category coding because the server runs a reasoning parser; the reviewer of the prefill/decode pull request showed that a parser says nothing about the workload, and the rule is removed (450 scored, not 530). The acceptance length a run's server logged is pinned in place of the profile where the engine models the field; the pins of this run do not model it.

## Residuals

The systematic biases on the train split are in `residuals.md`: it reads train points only (286 of the 450), groups them by model, hardware, precision, concurrency band, serving, speculation and regime, and lists the ten largest. Validation, test and prospective points were not read for it. Its hypothesis column is empty: the hypotheses written for the first preliminary run described a different train set and are not carried over.

## What this does not show

The per-split figures use the development split, whose test set is `development split, not the ledger's held-out`; the test figures are withheld from every table (they are logged when evaluated). No kernel hash is evaluated (no source maps a library version to a hash), so no point is G1 or G3. These are experimental figures at commit pins that will move; the final after-run replaces them.
