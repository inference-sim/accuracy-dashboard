# Preliminary after-run

**PRELIMINARY.** The simulator is pinned by commit (the head of inference-sim's combined pull request, before its release tag), so the figures are marked experimental until the tag is cut; the tag is expected to name the same tree, and moving to it is a pin-only change ([after-run.md](../after-run.md), "Repin to release tags is pin-only"). They are an in-sample rescoring of the same 1734 points, not a held-out result, and every accuracy figure leaves out the scored test and prospective points of the development split (`evaluation-protocol.md`, section 6), which is not the ledger's held-out.

## Inputs

| Input | Value |
|---|---|
| Harness | accuracy-dashboard commit `0e9627e219c207593de5bc55d997cf3dca707d64`; the baseline was scored again at the same commit |
| Simulator | inference-sim `81a46ba3e0b14ba828eaa46d21191d03dd17376f` (the head of its combined pull request, branch `m2/combined-layers`; `run.sh` fetches the commit by its hash) |
| Catalog and registry | blis-substrate `v0.14.0` (commit `965b05834c47882bc0f9f1a960c90327a756ef3d`), passed as the release tag for `--catalog-release` and `--registry-release` |
| Engine | vLLM 0.32.0; field list: blis-vllm `33455e4cb2d52b9fc9fa6cfb36cf5c1f5e509f5b` `fields.json`, sha256 `7432f9f82bf551027233a3aae2387fc585408d77d1c44941d037217aed890f1a` |
| Pull, units, point set | as the baseline: manifest `c8f2ea928b0d4582afdc3fbf11ef9d6847a359791a520f497ee146e806a96166`, 1734 points |
| Corpora | as the baseline |

Command: `harness/run.sh --sim 81a46ba3e0b14ba828eaa46d21191d03dd17376f --units units.txt --pull <pull> --out <out> --catalog <substrate>/catalog --registry <substrate>/registry --corpus-dir <corpora> --fields fields.json --catalog-release v0.14.0 --registry-release v0.14.0`. The simulator has `blis metrics`, so the scorer checked that its TTFT and TPOT have the InferenceX client's definitions; the baseline's v0.16.0 has none. Cost: about 60 minutes on one laptop with four workers when two other jobs share it.

## Result

| | Before (v0.16.0) | After (this simulator) |
|---|---|---|
| Scored | 41 | 795 |
| Reached the simulator and refused | 10 | 103 |
| Not scored (G5) | 1683 | 836 |
| Accuracy, train and validation points | TTFT MAPE 47.1 (n=11), TPOT MAPE 58.0 | TTFT MAPE 27.8 (n=520), shape 17.9 (n=353); TPOT MAPE 19.8, shape 15.9 |
| Scored in both runs (41), train and validation | TTFT 47.1, TPOT 58.0 (n=11) | TTFT 13.1, TPOT 19.6 (n=11) |

All scored points in both runs are G4 (no point is measured on the simulator's engine release and four G1 conditions are unevaluated), so there is one grade to compare: 795 G4 after, 41 G4 before. The 41 and the 795 are counts of every scored point; the accuracy rows leave out 30 and 275 test points. Only 11 of the baseline's 41 points are train or validation, so its accuracy row rests on eleven points and says little about the baseline as a whole; it is the figure the protocol allows until a test evaluation is logged.

In scope, the baseline scored 41 of 1188 points and this run 795; the 546 AMD points are out of scope (no catalog part). `table.md` has the coverage movement per reason, the figures per serving (all aggregated) and per split.

**Against the earlier preliminary run (450 scored, 117 refused by the simulator, 1167 not scored; TTFT MAPE 34.0 and TPOT 17.7 over 361 points).** 403 points are scored that were not, and 58 are no longer: 30 DeepSeek-V4-Pro points and 28 gpt-oss-120b points that the simulator now refuses (next section). MiniMax-M3 went from 238 scored points to 575 (393 on `minimax-m3-mxfp8`, 182 on `minimax-m3-nvfp4`, the entry that did not exist at the earlier pins), and 49 MiniMax-M2.5 NVFP4 points that the block-size oracle refused now score. The earlier figures are not comparable point for point: the accuracy rows rest on 520 points instead of 361.

## What the stated-only rule did

A value the engine only resolved, for a field it neither models nor proves inert, is recorded on the point and not stated in the scenario (`coverage-accounting.md`, "Resolved-only values"; design change merged as blis-design#3). This run applies it. The engine fills `compilation_config.custom_ops` with `all`, `none` or `+quant_fp8` in every log, and the kernel refused each as a stated value. The rule also leaves out `cudagraph_mode` and `cudagraph_capture_sizes` where only resolved, which the kernel does price although the field list calls them not modelled (blis-vllm#78): in a dry run, the DeepSeek-V4-Pro points on h200 moved by 5% to 16% in TTFT against a run that stated them.

## What the simulator refuses: the next work list

103 points pass the dashboard's checks and the simulator refuses them. The first error of each, grouped:

| Points | First error |
|---|---|
| 75 | DeepSeek-V4-Pro (`dsv4`, b300 and b200): `indexer_kv_dtype="bf16"` is refused by vLLM for the DeepSeek sparse indexer, which takes `fp8` or `mxfp4` (blis-vllm#84) |
| 28 | gpt-oss-120b: quantization `gpt_oss_mxfp4` is not one the kernel prices (`servedDType` has no entry) |

The full error of each refused point is in `refusals.json` (point id to text). In the order of the work they ask for:

1. **`indexer_kv_dtype` (75 points).** The run did not set it: the engine's server log prints it among the resolved settings, as `bf16`. The engine's field list now calls the field modelled with no estimation rule, so the scorer states the printed value, and the engine refuses it for this model. 30 of these points scored at the earlier pins of this run. Whether a resolved-only value of a modelled field is stated is the engine owner's decision (blis-vllm#84); the dashboard changes nothing until it is made.
2. **`gpt_oss_mxfp4` (28 points).** The catalog entry of the checkpoint names a quantization the kernel has no weight width for; the 28 points scored at the earlier pins.
3. **Speculative runs whose workload states no category (51 points still held at G5, [workload statements](../workload-statements.md)).** A speculative point whose acceptance length is neither pinned nor logged needs the workload's category and thinking mode to select the acceptance profile (design D8). The fixed-sequence InferenceX client sends random tokens and states no category, so these points are G5 `value_not_recorded:workload_category_not_stated` and do not reach the simulator.

## Residuals

The systematic biases on the train split are in `residuals.md`: it reads train points only (367 of the 795), groups them by model, hardware, precision, concurrency band, serving, speculation and regime, and lists the ten largest. Validation, test and prospective points were not read for it. Its hypothesis column is empty: the hypotheses written for the first preliminary run described a different train set and are not carried over.

## What this does not show

The per-split figures use the development split, whose test set is `development split, not the ledger's held-out`; the test figures are withheld from every table (they are logged when evaluated). No kernel hash is evaluated (no source maps a library version to a hash), so no point is G1 or G3. These figures are experimental while the simulator is pinned by commit; the release tag replaces the pin without a rescore (see above).
