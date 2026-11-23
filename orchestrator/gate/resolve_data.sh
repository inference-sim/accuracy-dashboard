#!/usr/bin/env bash
# What one side of a whole-run gate evaluation scores against, derived from nothing but its simulator ref.
#
#   resolve_data.sh <sim-ref> <workdir>
#
# <sim-ref> is a release tag (vMAJOR.MINOR.PATCH, optional suffix) or a full 40-hex commit of inference-sim,
# the value of SIM_REF in .github/stack-pins.env at the commit the side was dispatched on. The script fetches
# that ref into <workdir>/sim, reads its stack.json (orchestrator/resolve_stack.py), and prints key=value lines
# on stdout for `eval`/a file:
#
#   SIM_COMMIT    the commit the ref names (a tag is peeled)
#   DATA_DIR      the directory holding catalog/, registry/ and catalog/ledger: the checkout's own substrate/ when
#                 its stack.json lists no blis-substrate module, otherwise a blis-substrate clone at the pinned ref
#   DATA_COMMIT   the commit of that data (the sim commit itself when the substrate is embedded)
#   DATA_PIN      what --catalog-release/--registry-release are told: a release tag or DATA_COMMIT
#   FIELDS        the engine's fields.json for that release, copied to <workdir>/fields.json
#   VLLM_REF      the vLLM tag of the engine release
#
# gate-candidate.yml runs it to score a side; whole-run-gate.yml runs it again, from main's checkout, to check
# what the side recorded. Both use this one script so the two cannot disagree about how a ref becomes data.
set -euo pipefail

[ $# -eq 2 ] || { echo "usage: resolve_data.sh <sim-ref> <workdir>" >&2; exit 2; }
sim_ref="$1"
work="$2"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$sim_ref" =~ ^[0-9a-f]{40}$ ]]; then
  kind=commit
elif [[ "$sim_ref" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; then
  kind=tag
else
  echo "resolve_data.sh: $sim_ref is neither a release tag nor a 40-hex commit" >&2
  exit 2
fi

mkdir -p "$work"
sim="$work/sim"
git init -q "$sim"
git -C "$sim" remote add origin https://github.com/inference-sim/inference-sim.git
if [ "$kind" = tag ]; then
  git -C "$sim" fetch -q --depth 1 origin "refs/tags/$sim_ref:refs/tags/$sim_ref"
  git -C "$sim" checkout -q "refs/tags/$sim_ref"
else
  git -C "$sim" fetch -q --depth 1 origin "$sim_ref"
  git -C "$sim" checkout -q FETCH_HEAD
fi
sim_commit="$(git -C "$sim" rev-parse HEAD)"
if [ "$kind" = commit ] && [ "$sim_commit" != "$sim_ref" ]; then
  echo "resolve_data.sh: fetched $sim_commit for the commit $sim_ref" >&2
  exit 1
fi

eval "$(python3 "$here/../resolve_stack.py" "$sim")"
fields="$work/fields.json"
if [ "${substrate_embedded:-}" = true ]; then
  data_dir="$sim/substrate"
  data_commit="$sim_commit"
  data_pin="$sim_commit"
  cp "$sim/engines/vllm/fields.json" "$fields"
else
  git clone -q --filter=blob:none https://github.com/inference-sim/blis-substrate.git "$work/substrate"
  git -C "$work/substrate" checkout -q "$substrate_ref"
  data_dir="$work/substrate"
  data_commit="$(git -C "$data_dir" rev-parse HEAD)"
  data_pin="$data_commit"
  [[ "$substrate_ref" =~ ^v[0-9] ]] && data_pin="$substrate_ref"
  curl -fsSL --retry 3 -o "$fields" \
    "https://raw.githubusercontent.com/inference-sim/blis-vllm/${vllm_module_ref}/fields.json"
fi

printf 'SIM_COMMIT=%s\nDATA_DIR=%s\nDATA_COMMIT=%s\nDATA_PIN=%s\nFIELDS=%s\nVLLM_REF=%s\n' \
  "$sim_commit" "$data_dir" "$data_commit" "$data_pin" "$fields" "$vllm_ref"
