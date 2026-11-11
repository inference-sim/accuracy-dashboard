# Limits and known gaps

What the numbers do not show, in the order a reader is likely to misread them.

1. **Every figure is in-sample.** There is no anchor list yet (blis-substrate #31; design D7). The development split ([protocol](m2/evaluation-protocol.md)) is the dashboard's own, its salt is in the repository, and its test set is *development split, not the ledger's held-out*. The test figures are withheld and none has been evaluated.
2. **Nothing is G1, G2 or G3.** Every scored point is G4. No in-scope InferenceX point runs the modelled engine release as an official release (the points are other releases or nightly and custom builds), so G1 and G2 are unreachable on today's data; they are tested to be graded right when a point qualifies. G3 needs a published list of ported functions that no engine publishes.
3. **The kernel hash is unevaluated on every point.** No source maps a library version to a kernel hash (blis-registry#73). The other three unevaluated conditions are evaluated only where the Result states the datum, which most registry-measured coefficients do not ([closeness grades](closeness-grades.md)).
4. **The after-run is preliminary.** Its pins are commits that will move, its figures are experimental, and 406 of the 1734 points are refused by the simulator: [the work list](m2/preliminary-after/preliminary-after-run.md).
5. **The accuracy figures rest on few series.** The 450 scored points are in 16 groups of deployment shape (9 in the train split, 2 in validation, 5 in test); a bias in a group of two series (the b200 prefill, say) is a hypothesis, not a finding. Group counts are in [the residuals](m2/preliminary-after/residuals.md).
6. **Coverage is over the ledger's points only.** Rows newer than the ledger's source revision (1720 of 6306 in the window on 2026-11-10) are in no count, so new InferenceX measurements are not scored until a ledger release holds them.
7. **AMD and TPU are out of scope** (546 of the 1734 points). Nothing here says how BLIS does on them.
8. **Disaggregated points are not scored.** `topology_unsupported`, and the Dynamo runs are `router_unsupported`; the router substitution has no usable table entry ([disaggregation](disaggregation.md)).
9. **Recipes the harness could not read.** 149 of the 496 single-turn dynamo-vllm rows belong to two InferenceX runs whose minimax-m2.5 recipe files are in no ref I could pin, so their router mode is unknown, not assumed ([evidence](m2/dynamo-router-evidence.md)).
10. **Several groups of points wait on records, not on BLIS.** 35 Kimi-K3 points have no server log, 25 have no recipe fingerprint, 23 DeepSeek-V4-Pro NVFP4 points disagree with their recipe about the served checkpoint, and 5 Kimi-K3 DSpark points have no recipe draft model. They stay G5 with those reasons.
11. **The noise floor is a documented fallback** (1.6 percent), not measured per point.
12. **The field-list gate is the engine's classification.** A field classified *proven inert* is trusted to be inert; the dashboard does not test it. The dry run of what happens when the gate opens is in [gate with blis-vllm's classification](m2/gate-real-fields.md); the simulator then refuses a share of what passes.
13. **The shape error is anchored at the lowest concurrency of a sweep** and needs three points; it says nothing about the level of the curve.
14. **Reproduction depends on keeping the pull.** The pull cannot be re-created exactly from the live API ([reproducing](reproducing.md)).
