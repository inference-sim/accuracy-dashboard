# The whole-run held-out gate

M3.2: every change that moves accuracy lands through one held-out evaluation, returned as aggregates on its
pull request. This page is the rule, the pre-registration format, the budget ledger, what the gate job
guarantees about its output, and the steps only a maintainer can take. The design is VAL-6 (the split and the
success criteria are committed first), design 12.3 (a pre-registration is committed before any held-out datum
is read) and design 13.5 (the gate, its job split and its budget).

Nothing here has been run against the real partition seed. The code is exercised with a fake partition
(`orchestrator/gate/fakepartition.py`); the first real evaluation waits for the maintainer steps below.

## The rule

A pull request body holds, on a line of its own, exactly one of:

```
Gate: pre-registration <id>
Gate: not an accuracy change - <reason of at least 10 characters>
```

A change to a path listed in `state/gate/accuracy-paths.json` moves published accuracy. It must cite a
pre-registration, and the pre-registration must already be on `main`: it is committed first, and it is never
edited, renamed or deleted afterwards. A pre-registration added by a pull request is checked to be well
formed; the pull request that adds it cites `not an accuracy change` and needs no evaluation. A pull request
that cites a pre-registration must also show that the gate evaluated it and passed it: `state/gate/ledger.json`
on `main` must hold an evaluation of that pre-registration (the same SHA-256) with verdict `pass`, whose
candidate is the pull request's head commit and whose base is its merge base with `main`. A merged change
therefore always has a recorded passing run of exactly its commits, or a maintainer exception (below). The workflow `gate-rule.yml` checks all of this on every pull request, with no secret. It is a
`pull_request_target` workflow, so GitHub reads it from the base branch and a pull request cannot replace it; it
checks out only the base branch and runs the base branch's checker, reading the base branch's list of accuracy
paths, so a pull request cannot loosen the rule it is judged by. It never checks out or executes the pull
request's code: the body and the changed-file list come from the API (`gh api`), and the head's and the merge base's
trees are unpacked from the API's tarballs outside the checkout and read only as data (hashed, or parsed as JSON for a
pre-registration or an exceptions file). Its permissions are `contents: read` and `pull-requests: read`.
`orchestrator/gate/test_gate_workflow.py` fails if the trigger is anything but `pull_request_target`, if there is more
than one checkout or one that is not of the base ref, or if the workflow holds a secret, a write permission or a
command that brings head code in. The job and check names are unchanged (`gate-rule / rule`).

The list of accuracy paths is the whole scoring surface plus the gate itself, as directory rules: the pin file,
the three gate workflows, `harness/`, `orchestrator/ingest/`, `orchestrator/baseline/`, `schemas/`, the top-level
`orchestrator` modules and data files the candidate run imports or reads, and the gate's own policy and checker:
`state/gate/accuracy-paths.json`, `state/gate/exceptions.json` and `orchestrator/gate/`. A test module
(`test_*.py`) is the one exclusion; the scorer imports none, and the checker's tests are not the checker.
`orchestrator/gate/test_gate_surface.py` fails when a file the candidate run
executes (the import closure of `harness/run.sh`'s scorer, `freeze.py` and `resolve_agentic_corpus.py`) or reads is
outside the list, so a new scoring module cannot slip past it. `state/gate/ledger.json` and the
pre-registrations are data the gate commits after the fact and are not on the list.

**A change to the gate itself is an accuracy change.** A pull request that deletes a path from the list, weakens
`rule.py` or `surface.py`, or edits `exceptions.json` to grant itself an exception cannot say `Gate: not an accuracy
change`: it must cite a pre-registration, and that needs a recorded evaluation of its head and merge base or a
maintainer exception bound to one (below). Otherwise every later pull request would be judged by the weakened `main`.
The first such change, and any change the gate cannot evaluate, is merged by the maintainer, who has bypass on the
required check for that bootstrap; the exception file is then added by its own reviewed pull request.

### The candidate scores with main's code

A candidate run executes the candidate's own harness, scorer and workflows, so the gate must know they are
main's. `surface.py` hashes the scoring surface of a checkout: every file under the accuracy paths, without
test modules and without `.github/stack-pins.env` (the simulator pin differs between the two sides by design;
`check-binding` ties each side to its own pin), a symlink by its target. `gate-candidate.yml` records the hash
(`surface.sha256`). It is never trusted from the artifact:

* `whole-run-gate.yml` downloads each commit's tree through the API, recomputes the hash and refuses a run
  that records another one, then refuses unless the candidate's hash equals the base's.
* `gate-rule.yml` compares the merge base's tree with the head's, from the base branch's list of paths, and
  refuses a pull request whose trees differ, whatever its change list says.

So a pull request that edits scoring code does not reach an evaluation on its own. A maintainer exception
covers it, and an exception records a decision on a held evaluation; it never replaces one (VAL-6).
`state/gate/exceptions.json` (kind `GateExceptions`) on `main` holds entries

```json
{"pull_request": 170, "head": "<40 hex>", "reason": "<at least 10 characters>",
 "preregistration": "<the evaluated pre-registration's id>", "verdict": "unjudged"}
```

with `"verdict": "fail"` and a `"defect": <issue number or the URL of a GitHub issue>` when the evaluation failed.
Entries are read strictly (an unknown field is refused). `gate-rule` lets an exception stand in for a passing
evaluation, or for the surface check, only when `state/gate/ledger.json` on `main` holds an evaluation of the
pull request's cited pre-registration (the same id and SHA-256) whose candidate is the pull request's head and whose
base is its merge base now, and the entry's `verdict` is that evaluation's verdict. With no such evaluation the exception does not make the
check pass. Only `unjudged` is waived on the maintainer's word; a `fail` also needs the defect it was traced to
another term for (VAL-11), checked here for shape only; a `pass` needs no exception. An exception covers that
pull request at that head only, so any new push voids a recorded evaluation and its exception. It is read from
the base branch, never from the pull request, so it is added by its own reviewed pull request that merges first.
`whole-run-gate.yml` still asks only whether an entry names the pull request and head before it will score a
candidate whose surface differs from main's (no evaluation exists yet at that point), so for such a change the
sequence is: commit an entry with `"verdict": "unjudged"` (the verdict the gate returns until the distance
criterion is judged), evaluate, commit the ledger, and, if the gate returned `fail` instead, replace the entry with
one that carries the defect. It does not waive the pre-registration, which must still be cited and on `main`.
The one proof implemented is the tree hash being equal to main's; "the harness commit is an ancestor of main"
is not.

Because the workflow runs from the base branch, a pull request that edits `gate-rule.yml` changes only its own
diff: the check that judges it is still main's. The workflow file is also on the accuracy paths, so editing it needs
a recorded evaluation or an exception bound to one.

## The pre-registration

`state/gate/preregistrations/<id>.json`, read strictly (an unknown or missing field is refused):

```json
{
  "kind": "PreRegistration",
  "id": "example-transfer-rule",
  "partition_version": 1,
  "hypothesis": "one sentence: what the change does and why it should help",
  "layer": "one sentence: the layer of the model it changes",
  "predicted_change": "one sentence: the lanes and metrics it should move, and in which direction",
  "target_lanes": [{"engine": "vllm", "chip": "gb200"}],
  "sources": ["inferencex"],
  "criteria": [{"criterion": "error", "margin": 0.02}, {"criterion": "distance", "margin": 0.05}],
  "metrics": ["tpot_us", "ttft_us"],
  "substream": "gate/example-transfer-rule",
  "measured_sha256": "<64 hex: the SHA-256 of the measured table, printed by the base gate-candidate run>"
}
```

* A pre-registration lists exactly one `error` and exactly one `distance` criterion (VAL-6). One that omits
  either is refused, so an omitted criterion cannot turn unjudged evidence into a pass.
* A target lane names any of `engine`, `modelled_commit`, `chip`, `model`, `layout` (the deployment's
  configuration hash). A lane the pattern does not name is a guard lane.
* A target lane passes when the candidate's error is no worse than the base's, tested against "the
  difference is at least 0"; a guard lane passes when the candidate is not worse than the base by the margin,
  tested against "the difference is at least the margin". Both are one-sided BCa bootstrap tests with 10,000
  resamples over role keys (the unit of independence), with the Holm correction at 0.05 over all tests of the
  evaluation.
* The distance criterion is recorded but judged only when per-request samples exist; today it comes back
  `unjudged`, and with it every verdict that is not a `fail`. Until it is judged, no evaluation returns `pass`, and
  a change lands only by the maintainer exception below. A verdict is `pass`, `fail` or `unjudged`.
* A margin above the invariant registry's ceiling (recorded in the ledger) is refused. The ceiling is
  `null` in the ledger today, so the gate refuses every evaluation until a maintainer copies the registry's
  values into it.

## The budget ledger

`state/gate/ledger.json` (kind `GateLedger`) holds, for each partition version, `budget` (a whole number, or
`null`) and the `evaluations` spent against it, each with the pre-registration, its SHA-256, the base and
candidate commits, the gate run's id and the verdict. A `null` budget means the number is not decided (A5): the
gate refuses to evaluate and nothing supplies a default. A pre-registration is evaluated once. When the
budget is reached the next release uses a new partition version.

The gate job pushes nothing. It writes the next `ledger.json` as an artifact, and a maintainer commits it. The
next run refuses while any earlier successful gate run is missing from the ledger on `main`, so two
evaluations cannot be spent against one count.

## How an evaluation runs

1. Commit the pre-registration to `main` (a pull request that cites `not an accuracy change`).
2. Dispatch `gate-candidate.yml` on `main` (the base) and on the branch under test (the candidate), with the
   same `today` and `label`. There is no `sim` input: each side scores the simulator that `SIM_REF` in its own
   `.github/stack-pins.env` names (the merge base's pin for the base, the pull request head's pin for the
   candidate), over the catalog, registry, ledger and engine fields that simulator's `stack.json` pins
   (`orchestrator/gate/resolve_data.sh`). A pull request that moves the simulator pin or its data is therefore
   evaluated as old build against new build. The base's simulator also defines the lane (`modelled_commit`), so
   the pre-registration is written against the merge base's `SIM_REF`. Each side scores every unit that is not
   on the published fit or anchor list, so neither run can tell which are held, and keeps a contract, a
   Predictions document and a measured table. The base run's summary prints the measured table's SHA-256,
   which goes in the pre-registration. Because the pre-registration is committed before the candidate exists,
   the base run comes first, and the table's hash is pinned by the pre-registration before any held datum is
   read.
3. The pull request body cites the pre-registration. A maintainer or the agent dispatches `whole-run-gate.yml`
   on `main` with the pre-registration, the pull request number and the two run ids (A3).
4. The gate job checks the pull request, the runs and the artifacts, draws the roles from the seed, keeps the
   held units, and posts the aggregates on the pull request as one comment. It does not believe what a run
   recorded about its simulator: it reads each side's `SIM_REF` through the Actions API at that side's commit,
   resolves the simulator and data with main's own `resolve_data.sh`, and refuses unless the run's simulator
   commit, data commit and ledger digest are the resolved ones (`gate.py check-binding`). Both sides must carry
   the same ledger: the held-out partition is one thing for both. The simulator, engine, vLLM ref, field-table,
   pull-manifest and corpus provenance are bound that way and left out of the harness digest; the units, pull
   date, ingest and everything else must still agree.

5. A maintainer commits the run's `ledger.json` artifact to `main` (one pull request, which cites `not an accuracy
   change`). Only then does `gate-rule` pass for the evaluated pull request: it reads the ledger from the tip of
   `main`, and re-running the check after that commit sees it. The ledger commit moves the tip of `main` but not
   the pull request's merge base, so the evaluation still binds. A new push to the pull request, or a merge of
   `main` into it, changes the head or the merge base, and the change needs a new evaluation. Because the
   distance criterion is unjudged today, the verdict is not `pass` yet; until it is, the change lands through a
   maintainer exception that names its pull request and head and records the `unjudged` verdict of its evaluation.

Lanes with fewer than 10 role keys are merged on (engine, commit, chip), then on (engine, commit), and
otherwise only counted. A merged lane is named only by the fields its members share; a regression confined to
one member can pass inside it. Units on a legacy side (their old labels are public) are reported apart and
affect no verdict.

## What the output may hold

Only aggregates over lanes of at least 10 held role keys: lane names, counts, differences, confidence
bounds, p-values, and a verdict. Never a unit id, a role key, a per-unit value, a role, or any part of the
seed. This is enforced twice: the report is checked against an allow-list of keys and types
(`orchestrator/gate/guard.py`), and every text that leaves the job (the comment, the report, the log lines
and every error) is scrubbed against the identifiers and the seed. Any unexpected failure of the evaluation is
reported as its exception type only. `orchestrator/gate/test_gate_run.py` runs the whole path with a fake seed
and asserts that none of its identifiers or values appears on stdout, stderr or in any file written.

## PROPOSAL: the evaluation budget (A5) - takes no effect

**Proposed: 12 held evaluations for partition version 1.** This is a proposal for the maintainer. The ledger
holds `budget: null`, the gate refuses on it, and no code reads this page.

Derivation. Each pre-registered change receives one evaluation. The changes the rows pre-register (plan
Table W):

| Row | Change that moves accuracy | Pre-registrations |
|---|---|---|
| 3 | the blis-vllm upgrade from v0.33.0 to vLLM main `b582592d5a62`, which "has passed the whole-run gate" | 1 |
| 7 | the cross-generation transfer rule, used only if it beats roofline on the same units | 1 |
| 9 | the GB200 coefficients of Mistral-Large-4 and Inkling-2-Small (one change; no measured runs of these models exist, so its target lanes are expected to come back `unjudged`) | 1 |
| 15 | the SGLang estimation rules (the settings given an estimation rule; the ones proven inert or refused are not accuracy changes) | 1 |
| 23 | GB200 decode cost and the KV pool size (the other items of the row are not yet classified, and count once they are) | 2 |
| 29 | the refit of each engine | 2 |
| | planned | 8 |

The reserve is 4, half the planned count. A failed or `unjudged` evaluation cannot be repeated for the same
pre-registration, so a corrected change needs a new one, and the changes most likely to need one are the
upgrade (row 3), the transfer rule (row 7) and the two refits (row 29): one retry each. That reserve is a
judgement, not a measured rate. 8 planned + 4 reserve = 12.

What the proposal leaves open, for the maintainer:

* Whether the nightly and pre-release runs of design 13.5 (against the previous release and the best published
  release) count against the budget. They are not implemented here; if they count, 12 is too few.
* Whether the release of A2, which publishes the new fit list, starts a new partition version. If it does,
  row 29 (2 planned, 1 reserve) is spent against the new version's budget and version 1 needs 9.
* Rows 9 and 23 may add or remove pre-registrations once their items are classified.

## Maintainer steps

* **A1, merge, and require the check.** Review and merge this change. `gate-rule` is a `pull_request_target`
  workflow, so it runs from the base branch only once this change is on `main` (the run on this pull request's
  own head cannot use it). **It is not yet required:** the active ruleset `main protection` requires only
  `orchestrator`, `grep-clean` and `web`, with no required-workflow rule and no parent ruleset, so until a
  maintainer adds the status context `rule` (the job `rule` of workflow `gate-rule`, shown as `gate-rule / rule`)
  to that ruleset, the rule reports and does not block. Base code makes the check trustworthy; only the ruleset
  makes it mandatory, and no code in this repository can set it. Review `state/gate/accuracy-paths.json`.
* **A3, secret and dispatch.** Provision the environment `ledger` with the secret `LEDGER_SEED` (the 32-byte
  seed, in hex, whose SHA-256 `ledger.yaml` records) and restrict the environment to `main`. Dispatch
  `whole-run-gate.yml` on `main`. The workflow reads the secret by name in one step only. The agent never holds
  it. The candidate runs read public data and need no secret. The gate job refuses a pull request from a
  fork, since its candidate run must be a run of this repository.
* **A5, the budget.** Decide the number and set `partitions["1"].budget` in `state/gate/ledger.json`; copy the
  registry's margin ceilings into `margin_ceiling`. The gate refuses until both are set.
* After each evaluation, commit the `ledger.json` artifact of the gate run to `main`.

## Deviations and what is not verified

* **The two candidate runs and the gate job have not been run.** `gate-candidate.yml` and `whole-run-gate.yml`
  were written from `score-contracts.yml` and the Actions API reference, and checked only for YAML syntax and
  for the repository's own lints; nothing was dispatched. The bindings between runs (that both froze the same
  pull, scored under the same settings, and carry the commit the API reports) are checked by the code and
  tested with fakes; the first real dispatch is their first real test.
* The held-out set is the InferenceX units only; no other source has held units.
* The harness digest that the base and candidate must share is the SHA-256 of `provenance.json` without the
  harness commits; if two freezes of the same day differ, the gate refuses and the runs are repeated.
* The distance criterion is `unjudged` (no per-request samples reach the gate).
* The metrics list is required in the pre-registration because the metric registry is not available to this
  repository.
* Evaluations spent by a dispatch are counted when a maintainer commits the ledger; the next run refuses until
  then. This costs a manual step for each evaluation in return for a gate job that cannot write to the
  repository.
