# Coverage accounting

Coverage is a measured quantity: how many of the points the ledger holds are scored, how many are not and why, and what would change that. The unit of count is the point (a ledger unit), over a fixed point set; every table says which set.

## Reasons and how they are counted

A point that is not scored carries every reason that is true of it, not only the first. From these lists (`backlog.py`, design §11.6) three numbers are kept for each reason:

| Number | Meaning |
|---|---|
| **blocks** | the points that carry the reason |
| **alone** | the points whose *only* reason it is, so removing it alone would score them |
| **demotes** | the scored points a substitution holds below G1 |

A point's *primary* reason is the first of its reasons in the closed order of design §11.4 (`grade.G5_CODES`); primary counts sum to the not-scored total, blocks do not. A point that fails at the simulator is counted apart as *failed*, with the simulator's first error; it has no G5 reason.

`compare.py` prints these per run and, for a pair, the change of each between the two runs: blocks and alone before and after, and the points newly scored and newly refused (with their reasons). A *what would unlock the rest* table ranks the blockers of the in-scope points by blocks and alone: because most points carry several reasons, alone is much smaller than blocks, and the unlocking work is a set of fixes, not one.

## In scope and out of scope

AMD parts (mi300x, mi325x, mi355x) and TPUs are out of scope for the M2 to M4 releases (plan v64): the catalog and registry hold no coefficients for them. The scorer's reason codes are unchanged; the comparison tables classify the points by chip and show them apart, so coverage is stated over in-scope points as well as over all. In the baseline pull, 546 of the 1734 points are AMD (they carry `not_in_catalog`, via `hardware_no_coefficients`) and 1188 are in scope.

## The field-list gate

The engine repository classifies every configuration field and environment variable its release reads (`fields.json`, design VLM-3). A field the run *set* (a value it passed: the launch configuration or the arguments the log prints as passed) is looked up there. A value the engine only *resolved* (printed in the resolved configuration, a default or the engine's own choice for the architecture) is not a setting the run made; see "Resolved-only values" below:

| Status | Effect on a point |
|---|---|
| `modelled` | no effect; the value is written to the engine block and, when the list gives value classes, checked against them |
| `proven_inert` | no effect; the value is not written (the engine ignores it) |
| `not_modelled` | G5 `field_not_modelled`, unless the field has an estimation rule |
| `inert_unproven` | allowed only during a release plan; named as a G2 `interim_status` |
| not listed | G5 `field_not_in_release` |

A field with no place in the engine block cannot be `modelled`: the scorer would report that it lost a recorded value (`setting_differs`). The scorer holds no table of settings; the only table is the engine's `fields.json`, passed as `--fields`. `docs/m2/gate-real-fields.md` measures how many points pass the gate with blis-vllm's classification.

## Resolved-only values (the "only what the run set" rule)

The design's §11.2 (State) said a field the run records only as resolved "is copied as resolved", for every field; since the merge below it says so for a field the engine models or proves inert only. For any other field (not modelled, inert but unproven, or unknown to the release) it does not: the value is recorded on the point (a `resolved_not_stated` row in the fidelity `args`, with the value) and not stated in the scenario. The reason is the kernel's: it cannot tell a stated value from a resolved one, and refuses a stated value for a field it does not price. The case that mattered was `compilation_config.custom_ops`, which the engine fills with `all`, `none` or `+quant_fp8` by architecture and quantisation in every log; copied, it made the simulator refuse 434 points, 340 of which a dry run at the preliminary pins scored once it was left unstated (a dry run, not a committed result). A value the run *set* for such a field is unchanged: it is `field_not_modelled` (or takes the field's estimation rule). A modelled field resolved-only that the scenario has no place for is `setting_differs`, as for a value the run passed.

**Merged.** blis-design pull request [#3](https://github.com/inference-sim/blis-design/pull/3), merged on 2026-11-11 (merge commit bc25a5c86584fa73daedacda098fa4b38a98d3c0), adds to §11.2, State: *"This applies to a field the engine models or proves inert; for any other field the resolved value is the engine's own choice, not a setting the run made, so it is recorded on the point and not stated in the scenario, and the field's estimation rule applies only to a value the run passed."* The rule above is that sentence.

**Follows the field list.** The rule keys on the field list's status, not on the field. When blis-vllm marks `compilation_config.cudagraph_mode` and `cudagraph_capture_sizes` modelled (the kernel prices them), a value the engine only resolved for them is stated again; `test_extract.py` pins both directions.

**Not graded.** A `resolved_not_stated` value is not compared with what BLIS ran, and is not a G2 substitution: when `resolved_differs` is evaluated (G1), it compares the Result's engine resolutions, which are other fields. A resolved-only value that differs from what the engine would choose in BLIS therefore stays unnamed on the point. Naming it is a decision the design has not made.

## Estimation rules (design §11.2)

A field's estimation rule decides what the scenario states when the value is not the run's to state. The merged design (§11.2, published at <https://inference-sim.github.io/blis-design/>, blis-design main at 5e3e2bb) says: a rule applies in two cases, the run did not record the value, or the run recorded a setting the engine does not model. **A rule never replaces the recorded value of a field the engine models or proves inert**: that value is carried into the scenario as stated. For a setting the engine does not model, the rule's stand-in, or leaving the field unset, takes the place of the recorded value, and the point names the field, the recorded value and what stood in for it. A not-modelled field that the engine reads and prices when it is stated is a status to correct (modelled with its evidence, or refused when stated); the rule does not stand in for that. In the code: `leave_unset` leaves the field out so the engine resolves its upstream default, and names an `estimated` substitution; `substitute` writes the rule's stated setting and names it; `none` makes the point G5. The rule is consulted for a missing value only when the engine refuses it (`fields.estimate_missing`): the dashboard cannot name an unrecorded field the engine would accept.

## The label-record rule for cluster facts (design §11.3)

The GPUs per node of a run is recorded in its launch configuration when it is recorded at all. Otherwise InferenceX's `runners.yaml`, at the commits that record node sizes (from 2026-07-02), gives it per cluster. The rules, in the order the scorer applies them (`inferencex_runners.py`):

1. A launch configuration's size is used and is not a substitution.
2. A row dated on or after a label's first single-size record takes the record in force at its date; not a substitution.
3. A row dated before it takes the first record as a G2 `later_record`, for a label whose size is the same in every record that lists it.
4. A **runner that no record lists** (it sits in no cluster, or the newest file omits its label) may take the fact from the records of its label when every record that lists the label states the same size. The point is G2 `later_record`; `record` names the label and each record relied on (file and full commit) and `date` is the latest record's date. A label whose records state two sizes stays `value_not_recorded`.

The row does not carry its runner, so rules 3 and 4 act on the label. Rule 4 is design §11.3 as merged ("for a runner that no record lists, from the records of its label, when every record that lists the label states the same value; the point names the field and the record and its date, or the label and the records it relied on"). The ruling and the evidence are in [the b200/h200 report](m2/node-size-b200-h200.md).

## Prefill/decode reasons, counted apart

The dashboard names why a prefill/decode (P/D) row is not scored by the part of the layout or the record that is missing, not by one generic reason, so the blocks and alone counts above separate a missing engine feature from a missing writer or a missing record. Each is a `code:subject` reason like any other, so `blocks`, `alone` and the primary counts keep them apart:

| Reason | Counted as | Gap |
|---|---|---|
| `topology_unsupported:pd_pool_data_parallel` | a pool at data-parallel size above 1 | engine (blis-vllm#47, M3) |
| `topology_unsupported:pd_unequal_data_parallel` | pools of different data-parallel size | placement (inference-sim#1952, M3) |
| `topology_unsupported:pd_pool_not_recorded` | a pool with no workers or GPUs in the row | the row |
| `topology_unsupported:pd_agentic` | an agentic replay of a P/D deployment | writer (dashboard#64, M3) |
| `value_not_recorded:recipe_unresolved:<slug>` (slug `no_master_entry`, `ambiguous`, `not_in_tree`, `unreadable`, `no_config_file`, `run_commit_unreadable`) | no recipe to give the pools' arguments | record |
| `value_not_recorded:server_log_missing...` | the log is gone (404 or 413 from the API) | record |
| `router_unsupported:dynamo-router` | the router table maps nothing for the run's mode | table (blis-substrate#47) |

A row can carry several; the primary reason is the first in the closed order (`router_unsupported` before `topology_unsupported` before `value_not_recorded`), and `alone` says how many points a single reason holds back by itself. The generated [grade tables](grades.md) list the subjects.

Design §11.4 says `topology_unsupported` is "cleared when the harness can write that topology". For the first two subjects the harness can write the topology and the engine or placement refuses it, so the subject names the issue that clears it; the code stays on the closed list.

## Recovering a pool's arguments from the recipe (design §11.2, §11.3)

When a P/D run's own record of the engine arguments is missing or is one worker's, the arguments come from the recipe the run launched from, at the commit it executed, found by the rule in [disaggregation](disaggregation.md). The point names each pool's recovery as an `estimated` substitution (`engine.prefill.recipe`, `engine.decode.recipe`) with the recipe's path and commit and the fields the recipe states. Only a field the recipe states is written; a size it leaves at vLLM's default is written only where the pool's GPUs equal the product of the sizes; nothing else is invented, so the engine resolves the rest (X19). The recovery is G2 at best (design §11.3's clause "a recorded value was missing and replaced"); a recipe is a statement of intent, not a record of what ran.

## An environment variable the engine does not read

The engine's block takes only the environment variables it reads (`PYTHONHASHSEED`, `VLLM_USE_V2_MODEL_RUNNER` at the pinned list) and refuses any other key. A variable the field list calls `proven_inert` or `inert_unproven` (a timeout, a matmul-precision hint) is therefore recorded on the point (`match: inert` in the fidelity `args`, and for `inert_unproven` the `interim_status` substitution) and not stated in the scenario. Before this rule the scorer stated them and the engine refused all 84 P/D points that reached it.

## Workload mode and category of a speculative point

A speculative point's acceptance profile is keyed by the workload's category and thinking mode (design D8, §11.2). The
dashboard states neither on its own: a server's reasoning parser is a capability of the engine and says nothing about the
prompts it was sent. The order: (1) an acceptance length the run set is pinned; (2) otherwise a length its server logged
is pinned in place of a profile when the engine models the field (named `estimated`, with the log's figures); (3)
otherwise the workload's category and thinking mode must be stated, by a mode the run recorded (the chat-template kwargs) or by
the benchmark's own definition (the AgentX workload file of the catalog states both), or a fallback category the caller
asked for (`--speculative-fallback-category`, named `estimated` on `workload.category`, experimental); (4) otherwise the
point is G5 `value_not_recorded:workload_category_not_stated`, and a pair the substrate holds no profile for is
`value_not_recorded:profile_not_available:<category>/<thinking>`. What each benchmark family states, and which pairs have a
profile, is in [workload statements](m2/workload-statements.md).
