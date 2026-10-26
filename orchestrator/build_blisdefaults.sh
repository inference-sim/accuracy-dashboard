#!/usr/bin/env bash
# Build orchestrator/blisdefaults against ONE BLIS release's own inference-sim / kernel / schemas,
# so its defaults, resolutions and acceptance come from exactly that release (Discussion #15's
# seed: "Build the helper per release against its own inference-sim/kernel/schemas"; v0.11.0 pins
# kernel v0.3.0 + schemas v0.4.0). cli.py score's check_blis_inputs refuses a helper built against
# a different release, so this is what makes a per-release score sound.
#
# The committed go.mod pins the current release (v0.12.0). This rewrites the three require lines to
# the versions the given inference-sim checkout itself states, builds the binary, and prints its
# path. It edits a COPY of the module dir, never the committed one, so a seed that scores two
# releases builds two helpers without a dirty tree.
#
# Usage: build_blisdefaults.sh <inference-sim-checkout> <out-binary>
set -euo pipefail

sim="${1:?usage: build_blisdefaults.sh <inference-sim-checkout> <out-binary>}"
outbin="${2:?usage: build_blisdefaults.sh <inference-sim-checkout> <out-binary>}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src="$here/blisdefaults"

# The versions THIS release states for itself.
sim_tag=$(git -C "$sim" describe --tags --exact-match)
require() { awk -v m="$1" '$1==m {print $2; exit}' "$sim/go.mod"; }
kernel=$(require "github.com/inference-sim/blis-latency-kernel")
schemas=$(require "github.com/inference-sim/blis-schemas")
: "${sim_tag:?inference-sim checkout is not at a release tag}"
: "${kernel:?inference-sim go.mod has no blis-latency-kernel require}"
: "${schemas:?inference-sim go.mod has no blis-schemas require}"

work="$(mktemp -d)"
cp "$src/main.go" "$src/main_test.go" "$src/go.sum" "$work/" 2>/dev/null || cp "$src/main.go" "$work/"
cp "$src/go.mod" "$work/go.mod"
(
  cd "$work"
  go mod edit -require="github.com/inference-sim/inference-sim@${sim_tag}"
  go mod edit -require="github.com/inference-sim/blis-latency-kernel@${kernel}"
  go mod edit -require="github.com/inference-sim/blis-schemas@${schemas}"
  # Point inference-sim at the local checkout under test, so the helper links the SAME build blis
  # does (replace is how evaluate.sh keeps the two in lockstep).
  go mod edit -replace="github.com/inference-sim/inference-sim=${sim}"
  GOFLAGS=-mod=mod go build -o "$outbin" .
)
echo "built blisdefaults for ${sim_tag} (kernel ${kernel}, schemas ${schemas}) -> ${outbin}" >&2
