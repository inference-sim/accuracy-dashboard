# BLIS on AISimulate's points, with AISimulate's metric

AISimulate publishes the end-to-end accuracy of its simulator in a pinned artifact, `e2e-accuracy-web-0d6e4079e36703eb` (blis-substrate `kernel/scripts/aisimulate_e2e.pin.json`: workflow run 36849388864 of ai-dynamo/aisimulate at `cab77b9c7888b1c40df8cd3228f5e03c355ef23c`). Its measurements are InferenceX's own release `db-dump/2026-09-28`, the ledger's source revision. accuracy-dashboard#88 asks for BLIS to be scored on exactly those points, with the same metric, cell by cell, every cell reported. [matched.md](matched.md) is that table; `orchestrator/baseline/matched.py` makes it, in this repository's harness, the one end-to-end scorer (design §2.2, §11.7; COV-1).

## The points

`matched.py points` checks the artifact's zip against the pin's SHA-256 (`a3cdf7b4...`), unpacks `summary.json`, and runs blis-substrate's `extract_aisimulate_e2e.py`, which checks the summary's SHA-256 (`e1a380ad...`) and the pinned run before it reads a row: 204 sweeps, 1066 points over 88 deployments (vLLM 573, SGLang 219, TensorRT-LLM 274). Single node, aggregated serving, no speculation, client-observed.

`matched.py match` finds each point's record in the restored dump (blis-substrate's `ledger/inferencex/restore.sh` and `export.sql`, never committed): same model, chip, framework, precision, sequence lengths, parallel layout and concurrency, measured no later than the artifact's last date (2026-09-27), and the one run whose measured TPOT and TTFT curve is the artifact's, to 0.2 % at every point. Each record's ledger unit is the point BLIS is scored on. `matched.py freeze` freezes those units' artifacts through the harness's own pull, and `harness/run.sh` scores them at inference-sim v0.17.0.

## The metric

AISimulate's, reproduced from its artifact and checked against its own published totals:

- **MAPE**, over every point of a cell: `|pred(c) - meas(c)| / meas(c)`. AISimulate's curves are both divided by the measured value at the sweep's lowest concurrency, so the error of a relative is the error of the absolute; BLIS's prediction is put in the same units.
- **Shape error**, over every point above a sweep's lowest concurrency `c0`: `|pred(c)/pred(c0) - meas(c)/meas(c0)| / (meas(c)/meas(c0))`, each curve normalised to its own value at `c0`. Pooled over the cell's points. (Recomputed this way, the artifact's per-topology shape errors agree with its own to within 0.005 points.)
- **Coverage**: the points with a figure over the cell's points. A point BLIS does not score (refused by the simulator, G5, or no record found) is uncovered, as AISimulate's own failed points are.

A cell is framework × chip × model × serving mode. BLIS wins a cell when both MAPEs and both shape errors are below AISimulate's and its coverage is at least AISimulate's. The M3 target (release plan): BLIS's error below AISimulate's on every metric, with at least its coverage, on the matched points of the vLLM lane and of the SGLang lane. Every lost cell is listed with the reasons BLIS does not cover it; the issue map carries the work.

## The result (inference-sim v0.17.0)

Scored by the harness at accuracy-dashboard `26c22e3b1868fa8311eef3bd32ce194b359c629a`, inference-sim v0.17.0 (`c79c745619b16a8019339e3bbc79ee5e2923b258`), blis-substrate v0.14.0, blis-vllm v0.32.0-blis.3's field list. The figures are a logged test evaluation, so the development split's test points' errors are in them. Every one of the 1066 points has a split, computed from its own series by `split.py`'s rule (and, where a record is found, checked against the record's): 652 train, 255 validation, 159 test, none prospective (the artifact's points were measured by 2026-09-27, before the freeze date). The report names every evaluation-log row it stands for, and `published_test.py` fails the tree on a committed report whose test figures the log does not hold, on a log row no committed report names, and on a malformed row. The evaluation was run four times on 2026-11-16 while the tool was being fixed; the log keeps a pair of rows for each run (one pair was first removed in error and has been put back), and the first three counted 155 test points because the 220 unfrozen or unmatched points then had no split. **v0.17.0's evaluation of the development split's test set is spent**: a full test evaluation of v0.17.0 over InferenceX (its 446 test points of the M2 pull) can no longer be run as a first look, and any later one is a repeat that the log shows. AISimulate's own figures, recomputed here from its points, are its published ones: vLLM TPOT 15.39 and TTFT 38.28, SGLang 15.29 and 64.08. Every figure shows its point count, and one over fewer than 10 points is shown as "too few points" (COV-11); such a cell cannot be won.

- **vLLM lane, 573 points: lost.** BLIS covers 189 (33.0 %; AISimulate 100 %). On them its TPOT MAPE is 18.56 and TTFT MAPE 27.38, its shape errors 18.82 and 20.79; over the same 189 points AISimulate's are 22.08, 43.12, 12.84 and 30.77. So on the points both score BLIS is closer in TPOT, TTFT and TTFT shape, and further in TPOT shape; and its coverage is a third. No cell is won: every cell has less coverage, or one metric worse.
- **SGLang lane, 219 points, and TensorRT-LLM, 274: lost, 0 % coverage.** BLIS has no engine for either.

Why BLIS does not cover the other 384 vLLM points, with the issue that removes each:

| Points | Reason | Removed by |
|---|---|---|
| 213 | `record_gone: HTTP 404`: the Llama-3.1-70B runs of October 2025. GitHub answers 404 for their workflow runs and the InferenceX API for their server logs, so the harness has no record to build a scenario from. Their unit ids are in `unfrozen-units.json`; a pull error other than a 404 or 410 would be listed as `pull_error`, not as gone | data: not BLIS work |
| 56 | `blis_refused:scenario`: 28 gpt-oss-120b (`gpt_oss_mxfp4` not priced) and 28 DeepSeek-V4-Pro (the indexer KV dtype) | inference-sim/blis-substrate#102, inference-sim/blis-vllm#84 |
| 68 | `field_not_in_release`: removed vLLM environment variables on gpt-oss-120b | inference-sim/accuracy-dashboard#63 |
| 22 | `field_not_modelled:linear_backend` (Kimi-K2.5) | inference-sim/blis-vllm#80 |
| 17 | `field_not_modelled:moe_backend` (MiniMax-M2.5) | inference-sim/blis-registry#75 |
| 7 | `no_record`: two MiniMax sweeps whose curve no dump run reproduces to 0.2 % | the matching rule; checked by hand next |
| 1 | `value_not_recorded:api_413` | data |

The full per-cell table, with each cell's uncovered points by reason, is [matched.md](matched.md). The accuracy losses on covered points (TPOT shape across the lane; TPOT MAPE on gpt-oss-120b on H100 and H200 and MiniMax-M2.5 on H200) have no issue yet: filing one, and its place in the plan's issue map, is a decision for the plan's owner.

## The test split

Accuracy over the development split's test and prospective points is evaluated only through the logged path (docs/m2/evaluation-protocol.md): `matched.py report --evaluate-test --log docs/m2/evaluation-log.md --label ...` appends a row per split and records those rows in the report. Without it, errors leave those points out (the Withheld column) and coverage counts every point. Each point's split is computed from its dump record by `split.py`'s rule and checked against the harness's splits file; a point with no record has none, and is withheld from every figure in either case.

## Commands

The committed table is reproduced by these, in order (each path is a scratch directory; none is committed):

```
python3 orchestrator/baseline/matched.py points --zip ARTIFACT.zip --pin SUBSTRATE/kernel/scripts/aisimulate_e2e.pin.json \
  --extractor SUBSTRATE/kernel/scripts/extract_aisimulate_e2e.py --out POINTS.json
bash SUBSTRATE/ledger/inferencex/restore.sh ix && psql -At -d ix -f SUBSTRATE/ledger/inferencex/export.sql > ROWS.jsonl
python3 orchestrator/baseline/matched.py match --points POINTS.json --dump-rows ROWS.jsonl \
  --ledger SUBSTRATE_V0_14_0/catalog/ledger --extractor SUBSTRATE/kernel/scripts/extract_aisimulate_e2e.py \
  --out MATCH.json --units-out UNITS.txt
python3 orchestrator/baseline/matched.py freeze --match MATCH.json --dump-rows ROWS.jsonl \
  --ledger SUBSTRATE_V0_14_0/catalog/ledger --out PULL --cache CACHE --errors-out PULL_ERRORS.json
python3 -c "import json; print('\\n'.join(e['point_id'] for e in json.load(open('PULL/manifest.json'))['points']))" > FROZEN.txt
python3 orchestrator/resolve_agentic_corpus.py --all --catalog SUBSTRATE_V0_14_0/catalog -o CORPUS
bash harness/run.sh --sim v0.17.0 --units FROZEN.txt --pull PULL --out CONTRACT --catalog SUBSTRATE_V0_14_0/catalog \
  --registry SUBSTRATE_V0_14_0/registry --corpus-dir CORPUS --fields FIELDS_V0_32_0_BLIS_3.json \
  --catalog-release v0.14.0 --registry-release v0.14.0
python3 orchestrator/baseline/split.py splits --pull PULL --out SPLITS.json
python3 orchestrator/baseline/matched.py report --points POINTS.json --match MATCH.json --contract CONTRACT \
  --splits SPLITS.json --pull-errors PULL_ERRORS.json --estimator aisimulate --out docs/m3/matched/matched \
  --evaluate-test --log docs/m2/evaluation-log.md --label "BLIS v0.17.0 on the matched points"
```

`report` refuses to run unless `matched.py` is committed at the checkout's HEAD, and records that commit (`matched_py_commit`) beside the harness commit that scored the contract.

The artifact, the dump, the pull and the contract are third-party data or derived from it record by record, and are not committed (X12); the report holds aggregates per cell.
