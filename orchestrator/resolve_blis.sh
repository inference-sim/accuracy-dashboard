#!/usr/bin/env bash
# Resolve the simulator releases a night scores (COV-9; Discussion #15, "How the triggers are
# detected"). Every stable inference-sim release, in the order they were tagged, from the first
# one scored on graded points (stack.py FIRST_GRADED_RELEASE) on, that state/scored-releases.json
# does not list, is scored once, oldest first. The list is append-only and does not depend on which
# snapshots are retained. When every such release has
# its scores, the night scores the newest stable release's IX-only delta (a new point id), as
# before. There is no IX_TAG to resolve: the InferenceX data is pulled live from the API.
#
# Emits key=value to $GITHUB_OUTPUT (or stdout when run locally):
#   blis_tags  the releases to score tonight, oldest first, space-separated (never empty)
#   blis_tag   the newest stable inference-sim release (never main, never a pre-release)
set -euo pipefail

out="${GITHUB_OUTPUT:-/dev/stdout}"
here="$(cd "$(dirname "$0")" && pwd)"
tags="$(mktemp)"
trap 'rm -f "$tags"' EXIT

# Stable releases in the order they were tagged: gh lists newest first, so reverse it.
gh release list --repo inference-sim/inference-sim --exclude-drafts --exclude-pre-releases \
  -L 1000 --json tagName,createdAt -q 'sort_by(.createdAt) | .[].tagName' > "$tags"
NEWEST=$(tail -n 1 "$tags")
if [[ -z "${NEWEST}" ]]; then
  echo "FATAL: could not resolve a stable BLIS release tag" >&2
  exit 1
fi

UNSCORED=$(python3 "$here/ingest/stack.py" --tags "$tags" --scored "$here/../state/scored-releases.json" | tr '\n' ' ' | sed 's/ *$//')
TONIGHT="${UNSCORED:-$NEWEST}"

echo "blis_tags=${TONIGHT}" | tee -a "$out"
echo "blis_tag=${NEWEST}" | tee -a "$out"
echo "resolved BLIS: score ${TONIGHT} (newest stable ${NEWEST})" >&2
