#!/usr/bin/env bash
# Resolve the one input the API-ingest pipeline keys on: the latest STABLE inference-sim release
# (Discussion #15, "How the triggers are detected": a BLIS release is a new stable inference-sim
# tag). Unlike the old dump pipeline (resolve_inputs.sh), there is no IX_TAG to resolve -- the
# InferenceX data is pulled live from the API, and an IX release is detected from the pulled point
# ids, not from a GitHub release. The catalog/registry/kernel are derived from BLIS_TAG
# (resolve_versions.sh), never resolved here.
#
# Emits key=value to $GITHUB_OUTPUT (or stdout when run locally):
#   blis_tag   latest stable inference-sim release (never main, never a pre-release)
set -euo pipefail

out="${GITHUB_OUTPUT:-/dev/stdout}"

BLIS_TAG=$(gh release list --repo inference-sim/inference-sim \
             --exclude-drafts --exclude-pre-releases -L1 \
             --json tagName -q '.[0].tagName')
if [[ -z "${BLIS_TAG}" ]]; then
  echo "FATAL: could not resolve a stable BLIS release tag" >&2
  exit 1
fi

echo "blis_tag=${BLIS_TAG}" | tee -a "$out"
echo "resolved BLIS=${BLIS_TAG}" >&2
