# Prefill/decode run A: the substrate's router table

The scorer is given the substrate's own router table (policy `none`, no router build listed), so no Dynamo point is scored. This is what the dashboard publishes.

The method, the inputs by commit, the commands, the result and the limits are in [prefill/decode coverage](../pd-coverage.md); this directory holds the run: `contract/` (the five contract files and `pointrecords.jsonl`), `units.txt` (the 188 ledger units), `splits.json` (point id to development split), and [`table.md`](table.md) and `table.json` (made by `orchestrator/baseline/compare.py run --dir contract --sample in_sample`). The run's harness commit is in `contract/provenance.json`; a test (`test_contracts_current.py`) fails if a file that scores changes after it.

Command: `python3 orchestrator/ingest/cli.py score --pull PULL --out contract --units units.txt --blis BLIS --sim-build 81a46ba3e0b14ba828eaa46d21191d03dd17376f --catalog SUBSTRATE/catalog --registry SUBSTRATE/registry --catalog-release v0.14.0 --registry-release v0.14.0 --fields FIELDS.json --harness-commit HARNESS --corpus-dir CORPORA --router-checkout ROUTER` (the router fork at 2a886db5d1be70aa2ae18a7dbed81f5e1cdbd1f8) plus (no extra flag).

The pull (`pull_manifest_sha256` in the provenance) is not committed: it holds the 188 points' server logs and recipes, 60 MB.
