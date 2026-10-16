#!/usr/bin/env bash
# Stage a small, REAL direct-corpus trio for budget mode (RFC D3 ci-verify proof) — the full
# pipeline (build from source → signedprobe per point → summary.json → schema validate →
# headless render → publish) runs green on a hosted runner WITHOUT the 34GB dump.
#
# The scenarios are the kernel's own committed testdata/direct/*.yaml (real deployments). The
# measured absolutes here are plausible per-point values: signedprobe's PREDICTED side is a
# genuine `blis replay`; only the measured anchors are stand-ins (the real dump supplies them
# in a non-budget run). This proves the machinery end to end, not the production numbers.
#
# Env in:  BLIS_TAG, WORK (scratch), KERNEL_TAG (optional; else derived)
set -euo pipefail

WORK="${WORK:-$PWD/.work}"
mkdir -p "$WORK"
DASH_DIR="${DASH_DIR:-$PWD}"

# Need the kernel's committed direct scenarios. Derive the kernel tag from the BLIS release.
SIM="$WORK/inference-sim"
if [[ ! -d "$SIM" ]]; then
  git clone -q --depth 1 --branch "${BLIS_TAG:?}" https://github.com/inference-sim/inference-sim.git "$SIM"
fi
KERNEL_TAG="${KERNEL_TAG:-$(grep -E 'blis-latency-kernel ' "$SIM/go.mod" | awk '{print $2}')}"
KER="$WORK/blis-latency-kernel"
if [[ ! -d "$KER" ]]; then
  git clone -q --depth 1 --branch "$KERNEL_TAG" https://github.com/inference-sim/blis-latency-kernel.git "$KER"
fi

SCEN_SRC="$KER/testdata/direct"
SCENARIOS="$WORK/scenarios"
mkdir -p "$SCENARIOS"
cp "$SCEN_SRC"/*.yaml "$SCENARIOS"/ 2>/dev/null || true

python3 "$DASH_DIR/orchestrator/make_budget_fixture.py" \
  --scenarios "$SCEN_SRC" \
  --corpus "$WORK/inferencex_direct_corpus.json" \
  --absolutes "$WORK/inferencex_direct_absolutes.json" \
  --settings "$WORK/inferencex_direct_settings.json"

echo "[stage_budget_corpus] staged corpus/absolutes/settings + $(ls "$SCENARIOS" | wc -l) scenarios in $WORK" >&2
