# Closeness grades

Design §11.3 and §11.4 define the grades; `orchestrator/ingest/grade.py` computes them from data alone, and [grades.md](grades.md) lists them, the substitution kinds and every G5 reason, generated from that file (a test fails if it is stale). This page is the prose: what each condition means and why the numbers look as they do.

## The grades

Every point gets exactly one grade: the highest-numbered grade whose conditions apply.

- **G1, exact.** Every condition below was evaluated and is true.
- **G2, estimated.** The simulation ran, and every substitution it made is named on the point: a coefficient that was not measured, a value the engine's estimation rule supplied, a status allowed only during a release plan, a client difference, a cluster fact taken from a record of the same label, a router replaced by an llm-d policy, or a G1 condition whose data was not recorded (named *unevaluated*).
- **G3.** The run measured another release of the engine than the one the simulator models, and no function the engine ports from upstream changed between the two releases.
- **G4.** As G3 but a ported function changed; or the build is a nightly or custom one; or the engine has not published its list of ported functions, so that cannot be told.
- **G5, not scored**, for one reason of a closed list.

A point counts toward the headline when it is G1 to G4. A figure over fewer than ten points is shown as *too few points*.

## The conditions of G1

1. The run's engine release is the release the simulator models (stack.json names it; for this work vLLM 0.32.0).
2. Each library version the run used maps to the kernel hash BLIS priced (`kernel_hash`).
3. Every field the run sets is modelled, or proven inert, and its value is in a value class the engine's evidence covers (`value_class`).
4. Every coefficient the point used is measured or calibrated (`coefficient_method`), and none was extrapolated or unidentified (`coefficient_range`).
5. The value the engine resolves for a setting equals the value the run logged (`resolved_differs`).
6. The simulated requests are the ones the client sent (`client_difference`).

## Unevaluated conditions

A condition is *unevaluated* when no source records the datum it needs. It is then not assumed true: the point names it as a substitution whose subject is `unevaluated`, so the point is at best G2. `orchestrator/ingest/g1.py` evaluates four conditions from the simulator's Result and the field list, and names a condition unevaluated exactly when the Result or the list does not carry what the condition reads:

| Condition | Read from | Evaluated when |
|---|---|---|
| `coefficient_range` | each selected coefficient in `selected_entries` | `closeness_version` is 1 and every coefficient states a `fit_range` (for *extrapolated*) and a `ci95` (for *unidentified*). A true flag is evidence and is always named. |
| `kernel_hash` | the coefficient's `kernel_impls` and a map from a library version to a kernel hash | every coefficient states `kernel_impls`, the run recorded the library's version, and a source maps that version to a hash. No such source exists yet (blis-registry#73), so this condition is unevaluated on every point. |
| `value_class` | each modelled or proven-inert field's `value_classes` in `fields.json` | every field the run set carries its classes; a value outside every covered class is named |
| `resolved_differs` | the Result's `resolutions` (setting, pool, host, engine value) against the run's logged value | the Result lists resolutions; each is compared with the run's value for that setting and pool |

`closeness_version = 1` on `selected_entries` says only that the recorder passed on everything each entry states; it does not say the conditions were decided. Where an entry states no fit range, no interval or no kernel implementation, the corresponding flag, which the Result omits when false, means *not evaluated*, not *false*, so most registry-measured coefficients leave their conditions unevaluated.

## Why G1 and G2 are rare, and G3 is empty

- A point is G1 or G2 only if the run's engine release is the release the simulator models. No in-scope InferenceX point runs vLLM 0.32.0 as an official release: they run other releases or nightly and custom images. So every scored point so far is **G4**, and `grade.py` is tested to grade a point on the modelled release G1 or G2 correctly for when one exists.
- G3 needs the engine to publish which upstream functions it ports and a function-level diff between releases. None does, so a point on another release is G4 (`ported_functions_unpublished`), never G3.
- Whatever else is true of a point, one unevaluated condition makes it G2 at best.

## The G5 reasons and how each is removed

The list is closed (design §11.4); [grades.md](grades.md) has the table with the scorer's own reason codes. In words:

- **`field_not_modelled`**: the run set a field the engine's `fields.json` calls not modelled, with estimation rule `none`. Removed by modelling the field in blis-vllm (with a test that moves the price), proving it inert, or giving it a rule (`leave_unset`: the engine resolves it, named `estimated`).
- **`field_unclassified`**, **`field_not_in_release`**: the engine has not classified a field the run set, or the release does not list it (a removed environment variable). Removed by classifying it, or by scoring the point on a release that lists it.
- **`value_not_recorded`**: no source records a value the simulation needs (no server log, no recipe fingerprint, a node size no record gives, a draft model recorded only as a path no recipe names). Removed only by the record: a log or a recipe, or a rule that takes the fact from a record (the [label-record rule](coverage-accounting.md)).
- **`value_conflict`**: two sources of one stage disagree (the launch configuration against the printed arguments; a served path against the run's recipe checkpoint). The harness never picks one; the source must be corrected, or the draft length is one vLLM would refuse.
- **`not_in_catalog`**: the model, the chip's coefficients or the drafter is not in the catalog or registry. Removed by adding the entry (and measuring a chip's coefficients).
- **`router_unsupported`**: the run was behind a router BLIS does not host (BLIS hosts llm-d's). Removed by a router-table substitution the design allows, or by hosting the router ([disaggregation](disaggregation.md)).
- **`topology_unsupported`**: a prefill/decode or multinode deployment the scenario writer cannot yet state ([disaggregation](disaggregation.md)).
- **`engine_unsupported`**: no BLIS engine exists for the run's engine (TensorRT-LLM, ATOM, TileRT and the like). Removed by adding the engine.
- **`code_not_visible`**, **`build_unparseable`**: in the list, emitted by no scorer path today; a build the scorer cannot resolve is G4.

A run that fails at the simulator is not a G5 reason: it is a **fault** (`blis_refused:<slug>`), listed in `failed.jsonl`, and the next work list ([the preliminary after-run](m2/preliminary-after/preliminary-after-run.md) groups them).
