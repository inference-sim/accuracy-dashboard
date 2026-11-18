# The grade filter replaces the tier toggle

The page filtered its table by a tier (exact, estimated, all) that the summary derives from the closeness grade (`orchestrator/build_summary_v2.py`: G1 is `measured_or_resolved`, every other graded point is `all`). With every point at G4 the strict tier was empty and the page fell back to "all". The page now filters by grade directly, cumulatively: G1, up to G2, up to G3, all graded (the default). The control keeps its look; only its labels change. The headline still covers every graded point and ignores the filter (COV-11).

- `tier` stays in the v2 and v3 summary and in `schemas/` as a deprecated field, still emitted, derived from the grade. It is removed in a later release together with a planned rescore, because a change under `schemas/` makes every committed contract stale.
- The page no longer reads `tier` except for a snapshot that has no grades (v1): there `measured_or_resolved` is G1 and every other point is in "all graded" only, so an old release still renders in Compare.
- A link with `?tier=` opens on the grade it meant (`measured_or_resolved` is G1, anything else is all graded) and is rewritten to `?grade=`.
