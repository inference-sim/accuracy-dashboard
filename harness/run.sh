#!/usr/bin/env bash
# The scoring harness's entrypoint (design §11.7). It takes the three inputs the design names:
#
#   a simulator build   --sim <tag|commit>, a release tag (vMAJOR.MINOR.PATCH, with an optional
#                       pre-release suffix) or a full 40-hex commit of inference-sim, from
#                       --sim-repo. A branch name is refused: a branch moves, so the figures it
#                       gave could not be regenerated (X8).
#   the data            --catalog DIR and --registry DIR. Both are required: the scorer passes them
#                       to blis, and reads two facts from them that no blis command prints yet,
#                       the graph's speculator method and the registry's coefficient scopes
#                       (orchestrator/ingest/support.py, TEMPORARY).
#                       --catalog-release TAG and --registry-release TAG name the releases the two
#                       directories are at. The directories may carry no git history (a copy
#                       of the data), so the scorer is told the names, not left to read them.
#   a set of units      --units FILE, the ledger units to score, and --pull DIR, their frozen
#                       recorded runs.
#
# It clones inference-sim at the ref, builds blis, and runs the scorer
# (orchestrator/ingest/cli.py score), which writes the per-point records and aggregates to --out.
# The scorer reads the engine's field list (COV-3) from --fields: the fields.json of the pinned
# blis-vllm release (stack.json names the module and its commit), which must be for the engine
# release the build runs. TEMPORARY until the M2 substrate release lets the build print its own
# list through `blis fields`.
#
# The harness commit. Every figure records the commit of the harness that produced it (X8). The
# harness is this script and the scorer beside it, run from a checkout, so the commit is the
# checkout's HEAD. A checkout whose harness files (harness/, orchestrator/, schemas/) differ from
# HEAD is refused: its figures could not be regenerated from any commit. A copy of the tree with
# no git history (an exported archive) names its commit in the environment variable HARNESS_COMMIT
# (40 hex); when both exist the variable is checked against HEAD, and a mismatch is refused.
#
# Usage:
#   run.sh --sim <tag|commit> [--sim-repo URL] --units FILE --pull DIR --out DIR
#          --catalog DIR --registry DIR --corpus-dir DIR
#          --fields FILE --catalog-release TAG --registry-release TAG [--max-rss-mb N]
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
units="" pull="" out="" catalog="" registry="" corpus_dir="" fields="" max_rss_mb="" check_only=0
catalog_release="" registry_release=""

while [ $# -gt 0 ]; do
  case "$1" in
    --check-args) check_only=1; shift; continue ;;
    --sim|--sim-repo|--units|--pull|--out|--catalog|--registry|--corpus-dir|--catalog-release|--registry-release|--max-rss-mb|--fields)
      [ $# -ge 2 ] || refuse "$1 needs a value"
      case "$1" in
        --sim) sim="$2" ;;
        --sim-repo) sim_repo="$2" ;;
        --units) units="$2" ;;
        --pull) pull="$2" ;;
        --out) out="$2" ;;
        --catalog) catalog="$2" ;;
        --registry) registry="$2" ;;
        --corpus-dir) corpus_dir="$2" ;;
        --catalog-release) catalog_release="$2" ;;
        --registry-release) registry_release="$2" ;;
        --max-rss-mb) max_rss_mb="$2" ;;
        --fields) fields="$2" ;;
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
[ -n "$corpus_dir" ] || refuse "--corpus-dir is required: the directory of AgentX corpora, <workload>/<file>, that resolve_agentic_corpus.py --all fetched"
[ -n "$fields" ] || refuse "--fields is required: the engine's fields.json for the release the simulator runs (the pinned blis-vllm release's file)"

[ -n "$catalog_release" ] || refuse "--catalog-release is required: the release tag the catalog is at"
[ -n "$registry_release" ] || refuse "--registry-release is required: the release tag the registry is at"

harness_commit="${HARNESS_COMMIT:-}"
if [ -n "$harness_commit" ] && ! [[ "$harness_commit" =~ ^[0-9a-f]{40}$ ]]; then
  refuse "HARNESS_COMMIT $harness_commit is not a full 40-hex commit"
fi
if [ "$check_only" = 1 ]; then
  echo "run.sh: flags valid (--sim $sim is a $sim_kind)"
  exit 0
fi

[ -f "$units" ] || refuse "--units $units is not a file"
[ -d "$pull" ] || refuse "--pull $pull is not a directory"
[ -d "$corpus_dir" ] || refuse "--corpus-dir $corpus_dir is not a directory"
[ -f "$fields" ] || refuse "--fields $fields is not a file"

# The checkout is this repository only when git's top level is $root itself: a copy unpacked
# inside some other repository would otherwise record that repository's commit.
is_checkout() {
  local top
  top="$(git -C "$root" rev-parse --show-toplevel 2>/dev/null)" || return 1
  [ "$(cd "$top" && pwd -P)" = "$(cd "$root" && pwd -P)" ]
}

# The files that make the figures: the published data beside them changes during a night. An
# untracked file counts, since a new module in a script directory changes the figures too.
check_clean() {
  if [ -n "$(git -C "$root" status --porcelain --untracked-files=normal -- harness orchestrator schemas requirements-ci.txt)" ]; then
    refuse "the harness files of $root differ from its commit $head_commit; its figures could not be regenerated from a commit (X8)"
  fi
}

if is_checkout; then
  head_commit="$(git -C "$root" rev-parse HEAD)"
  if [ -n "$harness_commit" ] && [ "$harness_commit" != "$head_commit" ]; then
    refuse "HARNESS_COMMIT $harness_commit is not the checkout's HEAD $head_commit"
  fi
  check_clean
  harness_commit="$head_commit"
elif [ -z "$harness_commit" ]; then
  refuse "the harness at $root is not a git checkout and HARNESS_COMMIT is not set; every figure records the harness commit (X8)"
fi

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

# The binary is built inside the checkout: cli.py reads the build's release, commit, stack.json
# and go.mod from the directory the binary sits in.
( cd "$src" && go mod download && go build -o "$src/blis" main.go )

args=(score --pull "$pull" --out "$out" --blis "$src/blis" --units "$units"
      --sim-build "$sim" --harness-commit "$harness_commit" --catalog "$catalog" --registry "$registry"
      --corpus-dir "$corpus_dir" --fields "$fields"
      --catalog-release "$catalog_release" --registry-release "$registry_release")
# The replay memory ceiling is passed on only when given.
[ -z "$max_rss_mb" ] || args+=(--max-rss-mb "$max_rss_mb")
# The clone and the build take minutes: look at the harness again just before it runs.
if is_checkout; then
  [ "$(git -C "$root" rev-parse HEAD)" = "$head_commit" ] || refuse "the harness checkout moved from $head_commit while the simulator was built"
  check_clean
fi
python3 "$root/orchestrator/ingest/cli.py" "${args[@]}"
