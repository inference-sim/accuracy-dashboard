#!/usr/bin/env bash
# detect-diff (RFC §4.6): compare the live-resolved (blis_tag, ix_tag) pair to state/last-run.json.
# Identical ⇒ noop (nothing re-evaluated, prior snapshot kept). Different ⇒ changed=true.
# catalog/registry are derived from blis_tag, so they are NOT part of the diff key.
#
# Emits changed=true|false (+ the resolved tags) to $GITHUB_OUTPUT.
set -euo pipefail

STATE="${STATE_FILE:-state/last-run.json}"
out="${GITHUB_OUTPUT:-/dev/stdout}"

blis_tag="${BLIS_TAG:?}"
ix_tag="${IX_TAG:?}"

prev_blis=""; prev_ix=""
if [[ -f "$STATE" ]]; then
  prev_blis=$(python3 -c "import json;print(json.load(open('$STATE')).get('blis_tag',''))" 2>/dev/null || echo "")
  prev_ix=$(python3 -c "import json;print(json.load(open('$STATE')).get('ix_tag',''))" 2>/dev/null || echo "")
fi

if [[ "$blis_tag" == "$prev_blis" && "$ix_tag" == "$prev_ix" ]]; then
  echo "changed=false" | tee -a "$out"
  echo "no-op: inputs unchanged (blis=$blis_tag ix=$ix_tag)" >&2
else
  echo "changed=true" | tee -a "$out"
  echo "re-evaluate: inputs changed (blis $prev_blis->$blis_tag ; ix $prev_ix->$ix_tag)" >&2
fi
echo "blis_tag=${blis_tag}" | tee -a "$out"
echo "ix_tag=${ix_tag}" | tee -a "$out"
