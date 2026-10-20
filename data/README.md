# data/

CI-produced snapshots live here (RFC §4.2). **Nothing in this directory is hand-authored.**

- `data/latest/summary.json` — the current snapshot the site fetches. First written by a
  nightly/`workflow_dispatch` CI run; every update is a CI commit (provable via `git log`).
- `data/snapshots/<snapshot_id>/summary.json` — immutable history, one per run.

For local UI development, the render tests use `web/testdata/render-fixture.summary.json`
(a real signedprobe-derived snapshot, clearly labeled as a fixture — not the shipped artifact).
