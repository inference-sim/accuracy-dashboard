#!/usr/bin/env bash
# The checks a nightly data commit can break, run on the tree about to be committed. The commit is [skip ci], so nothing
# checks it after it lands: the 2026-11-17 night pruned a v2 snapshot and left its point ids in the legacy map, and moved
# data/latest to v3 under a test that read it as v2. Run from the repository root with python3, node and the pip and npm
# dependencies installed. Any failing command stops the script (set -e).
set -euo pipefail
# The night prunes v2 snapshots; their point ids leave the map first, so the map stays exact.
python3 orchestrator/ingest/legacy_ids.py prune --map data/legacy/point-ids.json --data data
python3 .github/ci/shards.py run boundary
python3 .github/ci/shards.py run contract
# The snapshot about to be published must still drive the real page: the v1 browser smoke.
(
  cd web
  npm ci --silent
  rm -rf public/data dist
  mkdir -p public/data/latest
  cp ../data/latest/summary.json public/data/latest/summary.json
  npm run build --silent
  npx playwright install --with-deps chromium
  node browser_smoke.mjs
)
