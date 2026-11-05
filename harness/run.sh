#!/usr/bin/env bash
# The scoring harness's entrypoint (design §11.7). It takes the three inputs the design names:
#
#   a simulator build   --sim <tag|commit>, a release tag (vMAJOR.MINOR.PATCH, with an optional
#                       pre-release suffix) or a full 40-hex commit of inference-sim, from
#                       --sim-repo. A branch name is refused: a branch moves, so the figures it
#                       gave could not be regenerated (X8).
#   the data            --catalog DIR and --registry DIR. Both are required until the simulator can
#                       report the data it embeds: the scorer reads the catalog and registry itself
#                       to grade not_in_catalog before the simulator runs.
#   a set of units      --units FILE, the ledger units to score, and --pull DIR, their frozen
#                       recorded runs.
#
# It clones inference-sim at the ref, builds blis, and runs the scorer
# (orchestrator/ingest/cli.py score), which writes the per-point records and aggregates to --out.
# The scorer asks the blis it built for the engine's field list (`blis fields --engine vllm
# --json`; COV-3), so the list is always the one of the engine release that build runs.
#
# The harness digest. Every figure records the digest of the harness that produced it (X8). An
# image cannot hold its own digest, since the digest is known only after the image is built.
# So the caller states it: a repository that runs the harness pulls it by the digest in its pin
# file and passes that digest as the environment variable HARNESS_DIGEST (sha256:<64 hex>). When
# HARNESS_DIGEST is unset the run records "unreleased", and its figures are labelled
# experimental: they may be posted on a pull request, never published as BLIS's accuracy.
#
# Usage:
#   run.sh --sim <tag|commit> [--sim-repo URL] --units FILE --pull DIR --out DIR
#          --catalog DIR --registry DIR
#   run.sh --check-args <the same flags>     validate the flags, do nothing else
#
# Exit status: 0 on success, 2 for a refused flag or value, otherwise the failing step's status.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/.." && pwd)"

refuse() {
  echo "run.sh: $*" >&2
  exit 2
}

sim="" sim_repo="https://github.com/inference-sim/inference-sim.git"
units="" pull="" out="" catalog="" registry="" check_only=0

while [ $# -gt 0 ]; do
  case "$1" in
    --check-args) check_only=1; shift; continue ;;
    --sim|--sim-repo|--units|--pull|--out|--catalog|--registry)
      [ $# -ge 2 ] || refuse "$1 needs a value"
      case "$1" in
        --sim) sim="$2" ;;
        --sim-repo) sim_repo="$2" ;;
        --units) units="$2" ;;
        --pull) pull="$2" ;;
        --out) out="$2" ;;
        --catalog) catalog="$2" ;;
        --registry) registry="$2" ;;
      esac
      shift 2 ;;
    *) refuse "unknown flag $1" ;;
  esac
done

[ -n "$sim" ] || refuse "--sim is required: a release tag or a full 40-hex commit of inference-sim"
if [[ "$sim" =~ ^[0-9a-f]{40}$ ]]; then
  sim_kind=commit
elif [[ "$sim" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; then
  sim_kind=tag
else
  refuse "--sim $sim is neither a release tag (vMAJOR.MINOR.PATCH) nor a full 40-hex commit; a branch name is refused because it moves"
fi
[ -n "$units" ] || refuse "--units is required: the file of ledger units to score"
[ -n "$pull" ] || refuse "--pull is required: the directory of frozen recorded runs"
[ -n "$out" ] || refuse "--out is required: the directory the records are written to"
[ -n "$catalog" ] || refuse "--catalog is required: the catalog the simulator reads"
[ -n "$registry" ] || refuse "--registry is required: the registry the simulator reads"

digest="${HARNESS_DIGEST:-unreleased}"
if [ "$digest" != unreleased ] && ! [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  refuse "HARNESS_DIGEST $digest is not sha256:<64 hex>"
fi

if [ "$check_only" = 1 ]; then
  echo "run.sh: flags valid (--sim $sim is a $sim_kind)"
  exit 0
fi

[ -f "$units" ] || refuse "--units $units is not a file"
[ -d "$pull" ] || refuse "--pull $pull is not a directory"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
src="$work/inference-sim"

# A tag is fetched by name; a commit by its full hash, which GitHub serves for any reachable
# commit, including a pull request's.
git init -q "$src"
git -C "$src" remote add origin "$sim_repo"
if [ "$sim_kind" = tag ]; then
  git -C "$src" fetch -q --depth 1 origin "refs/tags/$sim:refs/tags/$sim"
  git -C "$src" checkout -q "refs/tags/$sim"
else
  git -C "$src" fetch -q --depth 1 origin "$sim"
  git -C "$src" checkout -q FETCH_HEAD
fi
got="$(git -C "$src" rev-parse HEAD)"
echo "run.sh: inference-sim $sim at $got" >&2

( cd "$src" && go mod download && go build -o "$work/blis" main.go )

args=(score --pull "$pull" --out "$out" --blis "$work/blis" --units "$units"
      --sim-build "$sim" --harness-digest "$digest" --catalog "$catalog" --registry "$registry")
python3 "$root/orchestrator/ingest/cli.py" "${args[@]}"
