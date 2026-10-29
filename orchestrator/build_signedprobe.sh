#!/usr/bin/env bash
# Build orchestrator/signedprobe (the dashboard's copy of inference-sim's single-turn scorer and its
# harness) against ONE BLIS release's own inference-sim / kernel / schemas / blis-vllm, exactly as
# build_blisdefaults.sh builds the defaults helper. signedprobe imports inference-sim's sim and
# sim/workload packages and blis-vllm's compat packages, so they must be the versions the scored
# blis was built from, or the scenario it writes and the metrics it reads could disagree with blis.
#
# Unlike build_blisdefaults.sh this builds IN PLACE, with -modfile pointing at a temporary go.mod:
# the harness finds its committed request-length fixtures (testdata/inferencex-workloads) next to
# its own source, by the compiled-in path, so the source must not be copied elsewhere. The
# committed go.mod / go.sum are never modified.
#
# Usage: build_signedprobe.sh <inference-sim-checkout> <out-binary>
set -euo pipefail

sim="${1:?usage: build_signedprobe.sh <inference-sim-checkout> <out-binary>}"
outbin="${2:?usage: build_signedprobe.sh <inference-sim-checkout> <out-binary>}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src="$here/signedprobe"
sim="$(cd "$sim" && pwd)"

# The versions THIS release states for itself.
sim_tag=$(git -C "$sim" describe --tags --exact-match)
require() { awk -v m="$1" '$1==m {print $2; exit}' "$sim/go.mod"; }
kernel=$(require "github.com/inference-sim/blis-latency-kernel")
schemas=$(require "github.com/inference-sim/blis-schemas")
vllm=$(require "github.com/inference-sim/blis-vllm")
: "${sim_tag:?inference-sim checkout is not at a release tag}"
: "${kernel:?inference-sim go.mod has no blis-latency-kernel require}"
: "${schemas:?inference-sim go.mod has no blis-schemas require}"
: "${vllm:?inference-sim go.mod has no blis-vllm require}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cp "$src/go.mod" "$work/go.mod"
cp "$src/go.sum" "$work/go.sum" 2>/dev/null || true
(
  cd "$src"
  gm=(-modfile="$work/go.mod")
  go mod edit "${gm[@]}" -require="github.com/inference-sim/inference-sim@${sim_tag}"
  go mod edit "${gm[@]}" -require="github.com/inference-sim/blis-latency-kernel@${kernel}"
  go mod edit "${gm[@]}" -require="github.com/inference-sim/blis-schemas@${schemas}"
  go mod edit "${gm[@]}" -require="github.com/inference-sim/blis-vllm@${vllm}"
  # Link the SAME inference-sim build blis is: the local checkout under test.
  go mod edit "${gm[@]}" -replace="github.com/inference-sim/inference-sim=${sim}"
  GOFLAGS=-mod=mod go build "${gm[@]}" -o "$outbin" .
)
echo "built signedprobe for ${sim_tag} (kernel ${kernel}, schemas ${schemas}, blis-vllm ${vllm}) -> ${outbin}" >&2
