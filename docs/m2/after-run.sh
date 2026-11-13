#!/bin/bash
# The after run of the M2 before/after, in one command once the pins exist.
#
#   SIM=<inference-sim commit or release tag>        the simulator with PR 4 (fields, ledger, metrics) and PR 5
#   SUBSTRATE=<blis-substrate release tag or commit>                 catalog, registry and ledger; also the --catalog-release and
#                                                     --registry-release the run records (a commit is accepted while
#                                                     the stack is open)
#   BLIS_VLLM=<blis-vllm commit>                      the commit whose fields.json the simulator's engine release carries
#   BASELINE=docs/m2/baseline-v0.16.0                 the baseline's directory (README, units.txt, contract/)
#   PULL=<dir>                                        the baseline's frozen pull (not committed; see its README)
#   CORPUS=<dir>                                      the corpora (resolve_agentic_corpus.py --all fetches them)
#   WORK=<dir>                                        scratch space
#
#   SIM=... SUBSTRATE=... BLIS_VLLM=... PULL=... CORPUS=... WORK=... bash docs/m2/after-run.sh
#
# It scores the same units over the same pull from a checkout of the harness commit the baseline
# records, then writes the before/after table (compare.py refuses two harness commits, unit sets,
# pull sets or point sets). If the after run needs a harness change (any change under harness/,
# orchestrator/ or schemas/ moves the commit), make it first, score the baseline again at the new
# commit with its own pins (README: inference-sim v0.16.0, blis-substrate v0.13.0, blis-vllm
# v0.32.0-blis.2), commit it, and point BASELINE at it; this script does not do that.
set -euo pipefail

need() { [ -n "${!1:-}" ] || { echo "after-run.sh: $1 is required" >&2; exit 2; }; }
for v in SIM SUBSTRATE BLIS_VLLM PULL CORPUS WORK; do need "$v"; done
BASELINE="${BASELINE:-docs/m2/baseline-v0.16.0}"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[[ "$SUBSTRATE" =~ ^([0-9a-f]{40}|v[0-9]+\.[0-9]+\.[0-9]+)$ && "$BLIS_VLLM" =~ ^[0-9a-f]{40}$ ]] || { echo "after-run.sh: SUBSTRATE is a release tag or a full 40-hex commit and BLIS_VLLM a full 40-hex commit" >&2; exit 2; }
[ -f "$PULL/manifest.json" ] || { echo "after-run.sh: $PULL holds no frozen pull; the baseline's pull is not persisted, so freeze it again with orchestrator/baseline/freeze.py (a new pull is a new point set: rescore the baseline too)" >&2; exit 2; }

mkdir -p "$WORK"
# The harness: a clean checkout of the baseline's commit.
H="$(grep -o '`[0-9a-f]\{40\}`' "$repo/$BASELINE/README.md" | head -1 | tr -d '`')"
git -C "$repo" cat-file -e "$H^{commit}" || { echo "after-run.sh: harness commit $H is not in this repository" >&2; exit 2; }
rm -rf "$WORK/harness"; git -C "$repo" worktree add --detach "$WORK/harness" "$H" >/dev/null

# The substrate at the pinned commit, and the engine's field list at the pinned commit.
rm -rf "$WORK/substrate"; git clone -q https://github.com/inference-sim/blis-substrate.git "$WORK/substrate"
git -C "$WORK/substrate" checkout -q "$SUBSTRATE"
curl -fsSL "https://raw.githubusercontent.com/inference-sim/blis-vllm/$BLIS_VLLM/fields.json" -o "$WORK/fields.json"
echo "after-run.sh: fields.json sha256 $(shasum -a 256 "$WORK/fields.json" | cut -d' ' -f1)" >&2

run() {   # run SIM CATALOG REGISTRY CATALOG_TAG FIELDS OUT
  ( cd "$WORK/harness" && bash harness/run.sh --sim "$1" --units "$repo/$BASELINE/units.txt" --pull "$PULL" --out "$6" \
      --catalog "$2/catalog" --registry "$2/registry" --corpus-dir "$CORPUS" --fields "$5" \
      --catalog-release "$4" --registry-release "$4" )
}

before="$repo/$BASELINE/contract"
after="$WORK/after"
rm -rf "$after"; run "$SIM" "$WORK/substrate" "$WORK/substrate" "$SUBSTRATE" "$WORK/fields.json" "$after"

# The table: refuses two harness commits, unit sets, pull sets, point sets, or in-sample against held-out.
python3 "$repo/orchestrator/baseline/compare.py" pair --before "$before" --after "$after" --sample in_sample \
  --out "$repo/docs/m2/before-after"
echo "after-run.sh: wrote docs/m2/before-after.json and .md; commit them with the pins above in the PR body" >&2
