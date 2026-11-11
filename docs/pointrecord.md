# The substrate point record

Every run directory holds `pointrecords.jsonl` beside the five contract files. It has one line per scored point and one per G5 point, in the shape blis-substrate defines (`contracts/spec/pointrecord`, schema version 2). A point that failed in the simulator has no grade and no record. The other files (`points.csv`, `fidelity.jsonl`, `facets.json`, `not_scored.jsonl`) are the dashboard's reporting views; they keep their shapes and `compare.py` reads them. The record is what other tools read: config search, and the substrate's own gates.

The code is `orchestrator/ingest/pointrecord.py`; `score.write_contract` calls it. The ids in `pointrecords.jsonl` must equal the scored ids plus the not-scored ids, sorted and unique; `contract.validate_dir` checks that.

## How the dashboard's fields map

| Dashboard | Record |
|---|---|
| point id | `point_id` and `unit_id` (the same string) |
| the unit's row | `identity`; `recipe` is the source's recipe fingerprint, or `row:<id>` when it has none |
| grade, G5 reason | `grade`, `g5_reason`; the eleven G5 codes are the substrate's |
| substitutions | `substitutions`, sorted by kind and subject, with only the keys the substrate declares |
| `ported_functions_unpublished` | kind `changed_functions` (a G4 condition); the detail says the engine publishes no list of its ported functions, so a changed one is not ruled out |
| `args` | `settings`; `approximated` becomes `estimated`, and its rule is `substitute` when the note says the value stands in, else `leave_unset` |
| a setting the engine resolved and the run did not set | a `notes` entry with fixed text (design 11.2) |
| `pred_ttft_us`, `meas_ttft_us` and the TPOT pair | `figures`, in milliseconds, with `predicted_basis` and `measured_basis` both `{"scope": "cluster"}` |
| the Result's `data` block | `simulator.data`, copied as the simulator wrote it |
| the harness commit | `harness_commit`, 40 hex characters |
| G5 points | `facets` with stand-in labels, since a refused point has no scenario |

A run whose Results carry no `data` block writes an empty file; a run whose Results carry two different blocks is refused.

## What the record cannot yet say

* `measured_samples` is the number of requests the client was asked to send (10 times the concurrency for a single-turn point), not the number it completed; the pulled data does not record that.
* The substrate's `replay` has no field for the idle cap, the warm-up, the grace period or the context filter, so the record omits them. They stay in `fidelity.jsonl`.
* The `profile_value` and `router_differs` revisions are not emitted.
* A `resolved_not_stated` setting has no match value in the substrate, so it is a note, not a setting.

## How it is tested

`orchestrator/ingest/test_pointrecord.py` builds a small Go program (`testdata/pointrecord_validate`) against a checkout of blis-substrate that has the record package, decodes each line strictly and runs the package's `Validate`. It loads three assembled records (single-turn, agentic, G5), the committed runs' files, and refuses seven known-bad records: an empty `build.image`, a missing `identity.recipe`, a sha256 digest as `harness_commit`, the old key `harness_digest`, an unknown substitution kind, an `args` key, and an instance-scope `measured_basis`. Set `BLIS_SUBSTRATE_LAYER10` to the checkout; without it, or without Go, the tests skip and say why. CI sets it, to the blis-substrate commit `e3f3c0ee84cf65f8df053b0327773e81bea6803c` (layer 12 of the substrate stack, which has `harness_commit` and the router table's bounds); the pin is `sha=` in the `simulator` job of `.github/workflows/checks.yml` and moves to a release when the substrate publishes one.
