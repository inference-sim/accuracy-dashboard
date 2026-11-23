#!/usr/bin/env bash
# The checks a nightly data commit can break, run on the tree about to be committed. The commit is [skip ci], so nothing
# checks it after it lands: the 2026-11-17 night pruned a v2 snapshot and left its point ids in the legacy map, and moved
# data/latest to v3 under a test that read it as v2. Run from the repository root with python3, node and the pip and npm
# dependencies installed. Any failing command stops the script (set -e).
set -euo pipefail
# More than 5 percent of the night's points failed (a harness fault; a named G5 is a result): the publish stops.
python3 orchestrator/nightly/night_health.py data/latest/summary.json
# Named simulator refusals never stop a night; a refusal code not met before, or many unclassified ones, is a warning to read.
python3 orchestrator/nightly/night_notes.py data/latest/summary.json
# No file may be near GitHub's 100 MB limit: its pre-receive hook refuses the whole push, after the night is scored.
python3 orchestrator/nightly/file_size.py data state
# The classes page is built from this summary (a missing or stale classes.json would show another night beside it).
python3 orchestrator/build_classes.py check data/latest/classes.json
python3 - <<'PY'
import json, sys
c, s = (json.load(open(f"data/latest/{n}.json")) for n in ("classes", "summary"))
if c["snapshot_id"] != s["snapshot_id"]:
    sys.exit(f"FATAL: data/latest/classes.json is of {c['snapshot_id']}, the summary is {s['snapshot_id']}; refusing to publish")
PY
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
  cp ../data/latest/classes.json public/data/latest/classes.json
  npm run build --silent
  npx playwright install --with-deps chromium
  node browser_smoke.mjs
)
