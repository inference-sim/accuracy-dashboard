#!/usr/bin/env bash
# Resolve BOTH inputs live, every run (RFC A2/§4.3). Nothing is hardcoded in this repo: a new
# release on either side becomes the scored input automatically on the next run. Emits
# key=value lines to $GITHUB_OUTPUT (or stdout when run locally).
#
#   BLIS_TAG   latest STABLE inference-sim release (never main, never a pre-release)
#   IX_TAG     latest weekly InferenceX db-dump/* release
#
# The catalog/registry/kernel are DERIVED from BLIS_TAG (resolve_versions.sh), never diffed on.
set -euo pipefail

out="${GITHUB_OUTPUT:-/dev/stdout}"

BLIS_TAG=$(gh release list --repo inference-sim/inference-sim \
             --exclude-drafts --exclude-pre-releases -L1 \
             --json tagName -q '.[0].tagName')
if [[ -z "${BLIS_TAG}" ]]; then
  echo "FATAL: could not resolve a stable BLIS release tag" >&2
  exit 1
fi

# The db-dump/ filter is load-bearing: the repo's newest release is often an unrelated
# "InferenceX skills" tag, not a dump.
IX_TAG=$(gh release list --repo SemiAnalysisAI/InferenceX-app \
             --exclude-drafts --exclude-pre-releases \
             --json tagName -q '[.[].tagName | select(startswith("db-dump/"))] | first')
if [[ -z "${IX_TAG}" ]]; then
  echo "FATAL: could not resolve a db-dump/* InferenceX release tag" >&2
  exit 1
fi

echo "blis_tag=${BLIS_TAG}" | tee -a "$out"
echo "ix_tag=${IX_TAG}" | tee -a "$out"
echo "resolved BLIS=${BLIS_TAG}  InferenceX=${IX_TAG}" >&2
