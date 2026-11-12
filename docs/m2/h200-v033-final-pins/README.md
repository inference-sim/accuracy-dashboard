# The sixteen DeepSeek-V4.1-Flash H200 rows at the final stack pins

Contents: [Result](#result) · [What it shows and does not show](#what-it-shows-and-does-not-show) · [Inputs](#inputs) · [Command](#command)

## Result

**Development split only (the sixteen are validation-split points; no test or prospective point is in the pull or was read). In-sample. Not a result of record: the simulator is a draft build, see [Inputs](#inputs).** No scratch field list and no scratch scorer: the committed scorer, the engine's own `fields.json`. [contract/](contract/) is the run, [splits.json](splits.json) its splits and [table.md](table.md) its table. The rows, their pinning and their split are described in [the page of the rows](../h200-v033/README.md).

**Scratch-build figure, not a result at published pins.** The sixteen units are the substrate's and have no role until the seed and the anchor lists are published; scoring uses the published anchor lists only (COV-2), so at published pins they score 0 of 16. The run below scored them with the units forced in.

**16 of 16 scored, 0 refused, 0 failed, all G4.** Over the sixteen points: **TTFT MAPE 34.8 %, TPOT MAPE 23.5 %** (TTFT shape 31.0 %, TPOT shape 24.0 %, over the 14 points with a shape). Before (the dry run with the three fields classified, old pins): 75.4 % and 38.1 %.

| GPUs | Clients | TTFT measured | TTFT predicted | Error | TPOT measured | TPOT predicted | Error |
|---|---|---|---|---|---|---|---|
| 4 | 1 | 452.8 | 506.8 | +12 | 2.96 | 3.10 | +5 |
| 4 | 2 | 413.4 | 471.1 | +14 | 3.26 | 3.48 | +7 |
| 4 | 4 | 387.0 | 427.4 | +10 | 3.43 | 3.70 | +8 |
| 4 | 8 | 388.9 | 446.0 | +15 | 4.14 | 4.96 | +20 |
| 4 | 16 | 493.7 | 620.7 | +26 | 6.04 | 7.83 | +30 |
| 4 | 32 | 446.5 | 833.4 | +87 | 8.85 | 13.76 | +55 |
| 4 | 64 | 1116.2 | 1861.4 | +67 | 19.46 | 31.19 | +60 |
| 4 | 128 | 382024.9 | 993737.4 | +160 | 34.54 | 74.97 | +117 |
| 8 | 1 | 391.8 | 390.6 | 0 | 2.71 | 2.55 | -6 |
| 8 | 2 | 342.9 | 346.6 | +1 | 2.94 | 2.74 | -7 |
| 8 | 4 | 325.0 | 311.8 | -4 | 3.08 | 3.00 | -3 |
| 8 | 8 | 314.4 | 324.6 | +3 | 3.65 | 3.55 | -3 |
| 8 | 16 | 361.5 | 398.0 | +10 | 5.26 | 5.08 | -3 |
| 8 | 32 | 359.0 | 522.3 | +45 | 7.94 | 8.77 | +10 |
| 8 | 64 | 468.6 | 780.7 | +67 | 16.89 | 18.95 | +12 |
| 8 | 128 | 5025.1 | 3229.5 | -36 | 44.02 | 56.96 | +29 |

## What it shows and does not show

- Up to 16 clients on 8 GPUs both figures are within 10 % of the run. Error grows with load on both shapes (TTFT +45 % and +67 % at 32 and 64 clients on 8 GPUs; TPOT +55 % to +117 % at 32 to 128 clients on 4 GPUs). The 128-client rows are saturated queues (382 s measured on 4 GPUs) and say little.
- The gain from 75.4 % to 34.8 % comes from two things that changed together: the decoder replay (layers after the last KV layer priced on each request's last 128 tokens, blis-vllm `98db58ec` with blis-substrate layer 20) and the admission queue (`Service` and `Delay` of the kernel's admission demand). The run cannot say how much each gave. Neither is fitted to these rows. All figures are in-sample.
- The Rust front end is a queue of one server and one thread in this build, which is what the engine states in its plan (`HostPlan.Admission`, blis-vllm `af30ea24`), though the Rust front end is multithreaded. At 64 clients on 8 GPUs, sixteen render threads give a mean TTFT of 807.5 ms against 780.7 ms with one, so the queue is not what keeps the 32 and 64 client rows high. That is one row, run by hand with `--renderer-num-workers 16`; it is not scored.
- The grade is G4 for the reason under [Grade](../h200-v033/README.md#grade); nothing else changed it.

## Inputs

- Harness commit: `8611215558f77ad1d760918dbe1ca698fc70e556` (the contract's `provenance.json`).
- Simulator: inference-sim `75c3359188e1ece7dcc2c4b5e35361614f225463` (branch `m2/10-admission-split`, the latest pushed head), **built with two changes that are not committed anywhere**: its `go.mod` points at blis-vllm `98db58ec502843d2bb4feebf180ba0d39d972472` and blis-substrate `6d53cf403a17d0367a3d17951b42eb2d6215767f` (layer 20) in place of the pins it carries, and `cmd/engine_build.go` reads the admission demand from the kernel (`HostDemand` on its transfer environment; the render time of a request is the demand's `Service`), because that head predates the substrate's `HostDemand`. inference-sim's own repin replaces both; the figures here are to be run again on it. 
- Catalog and registry: blis-substrate `6d53cf403a17d0367a3d17951b42eb2d6215767f`. 
- Field list: blis-vllm `98db58ec502843d2bb4feebf180ba0d39d972472` `fields.json`, sha256 `aa0d3d175827e6ca31a56d0efb54c27727659a44384937e2d285aacf88435db9`. 
- Pull: the same as above (`pull_manifest_sha256` `9e9588ad78ee04870416a0992c2e8eaba865fbf98e7f9b806bfef67eaca32a36`).

## Command

As in [How to reproduce](../h200-v033/README.md#how-to-reproduce), step 2, with those inputs, `--sim-build 75c3359188e1ece7dcc2c4b5e35361614f225463`, and `cli.py score` called directly with `--blis` the binary above (`harness/run.sh` builds from a clean clone of the commit, which cannot carry the two changes). Cost: about 25 minutes, one worker, no GPU. The scored run at this harness commit reused the sixteen replays of an earlier run at the previous harness commit, whose scenarios, workload specs, binary, catalog and registry are the same (the commits between them change only which Result versions the harness reads); its `points.csv` is byte-identical to this one.

