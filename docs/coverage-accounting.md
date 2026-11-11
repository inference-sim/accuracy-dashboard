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

The merged design (§11.2, State) says a field the run records only as resolved "is copied as resolved", for every field. The scorer does that for a field the engine models or proves inert. For any other field (not modelled, inert but unproven, or unknown to the release) it does not: the value is recorded on the point (a `resolved_not_stated` row in the fidelity `args`, with the value) and not stated in the scenario. The reason is the kernel's: it cannot tell a stated value from a resolved one, and refuses a stated value for a field it does not price. The case that mattered was `compilation_config.custom_ops`, which the engine fills with `all`, `none` or `+quant_fp8` by architecture and quantisation in every log; copied, it made the simulator refuse 434 points, 340 of which a dry run at the preliminary pins scored once it was left unstated (a dry run, not a committed result). A value the run *set* for such a field is unchanged: it is `field_not_modelled` (or takes the field's estimation rule). A modelled field resolved-only that the scenario has no place for is `setting_differs`, as for a value the run passed.

**Pending.** This reads "is copied as resolved" more narrowly than the design as merged. The sentence that makes the design say so is in draft pull request [blis-design#3](https://github.com/inference-sim/blis-design/pull/3), which is open: *"This applies to a field the engine models or proves inert; for any other field the resolved value is the engine's own choice, not a setting the run made, so it is recorded on the point and not stated in the scenario, and the field's estimation rule applies only to a value the run passed."* Until it merges, this rule is the dashboard's reading, not the design's.

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
