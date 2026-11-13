# GPUs per node for b200 and h200: what the records say and what the design permits

Read from `orchestrator/ingest/inferencex_runners.json` (InferenceX `runners.yaml` at four commits) and the 645 points the field gate's dry run found blocked by `value_not_recorded:cluster.gpus_per_node` (`gate-real-fields.md`; the committed baseline has none). Nothing was changed.

## The records

| Commit | Date | Records node sizes | b200 | h200 |
|---|---|---|---|---|
| `303669b0` | 2026-07-02 | yes | cluster `b200-dgxc`: 8. 4 runners in no cluster (first `b200-cw_00`) | clusters `h200-cw`, `h200-dgxc`, `h200-nb`: 8 each. 1 runner in no cluster (`h200-nb_1`) |
| `e9fc9880` | 2026-07-02 | no (runners only) | | |
| `5d06e10c` | 2026-09-27 | yes | cluster `b200-nscale`: 8. The same 4 runners in no cluster | clusters `h200-cw`, `h200-dgxc`: 8. No runner outside a cluster |
| `4a63bf50` | 2026-11-06 | yes | label absent from the file | cluster `h200-dgxc`: 8. No runner outside a cluster |

Every size any record states for either label is 8. No two records disagree. What is incomplete is coverage of the label's runners: b200 has 4 runners that no version places in a cluster, and the newest file does not list b200 at all; h200 has one such runner, in the oldest record only.

## The points

| Label | Points blocked | Dated before 2026-07-02 | 2026-07-02 to 2026-09-26 | Blocked by this reason alone |
|---|---|---|---|---|
| b200 | 406 | 164 | 242 | 10 |
| h200 | 239 | 168 | 71 | 10 |

None is dated 2026-09-27 or later (those would use the record in force). A point blocked by this reason alone would be scored; the other 625 carry other reasons as well (mostly `field_not_modelled`), so they stay G5 whatever is decided here. Every point scored today is G4, so a `later_record` substitution would change which substitutions a point names, not its grade.

## What can and cannot be known per point

A point's runner is not in the pull for almost all of them: no file of 406 b200 and 265 h200 pulled points names a runner (the exceptions are 33 points whose logs mention `b200-nscale`, `b200-nsc` or `h200-dgxc`). So the harness cannot tell which cluster, or which orphan runner, a point ran on.

## What the design says

Design 11.3 (G2): "a fact of the cluster the run's own record lacks was taken from the benchmark's later record of the same runner, such as the GPUs per node of a runner whose definition was written after the run; the point names the field, the record and its date." And 11.4's `value_not_recorded` covers a value no source records.

The text speaks of the same runner. It is silent on a label whose runner is not known for the point, on a runner no record places in a cluster, and on a label that disappears from the newest record. So:

- **h200.** The two later records (`5d06e10c`, `4a63bf50`) place every runner of the label in a cluster of size 8. Reading "the same runner" as "any runner of the label", every one of the 239 points could take 8 from `5d06e10c` (2026-09-27) with `later_record` naming that record and its date. The reading assumes a point did not run on a runner that is in `303669b0` and absent from the later files (the `h200-nb` cluster and its runner `h200-nb_1`, which the 07-02 record leaves outside any cluster). Whether it did is not recorded.
- **b200.** No record places the 4 runners `b200-cw_00` and three others in a cluster, so no record states their node size. The label's clusters state 8, but those runners are the ones most likely to have run b200 points on a CoreWeave machine. A `later_record` from `303669b0` or `5d06e10c` would state a size for runners those records leave without one. The design does not permit that reading without a ruling, and the newest file has no b200 record at all.

## Question for the maintainer

May the facts of a label's clusters stand for a runner of that label that no record places in a cluster, when every cluster of the label states the same size? If yes for h200 only (complete in its later records), 239 points gain a `later_record` substitution and 10 more are scored. If yes for both, 645 points gain a `later_record` substitution and 20 more are scored in all (10 per label). If no, both labels stay `value_not_recorded` and the fix is an InferenceX `runners.yaml` that places every runner in a cluster.
