#!/usr/bin/env bash
# Derive catalog/registry/kernel/vllm from a resolved BLIS tag (RFC §4.6). These are NOT separate
# diff axes: each BLIS release states its compatible catalog/registry in installation.md, its
# kernel in go.mod, and the vLLM release its engine models in blis-vllm's own Upstream provenance,
# so they ride BLIS_TAG. Recorded in provenance for traceability.
#
# IMPORTANT (verified): the compatible catalog/registry come from the release's
# installation.md, NOT the kernel's testdata/upstream.lock -- using the lock's pair made the
# kernel refuse the deployment. See orchestrator notes.
#
# Usage: resolve_versions.sh <blis_checkout_dir>
set -euo pipefail

checkout="${1:?usage: resolve_versions.sh <blis_checkout_dir>}"
out="${GITHUB_OUTPUT:-/dev/stdout}"

inst="$checkout/docs/getting-started/installation.md"
gomod="$checkout/go.mod"

# installation.md wraps the registry value onto the next line and carries an HTML-comment
# template line that also matches "Compatible blis-catalog release: `<tag>`". Strip comments,
# flatten to one line, then take the first backtick-quoted token after each "Compatible ...
# release:" marker. python keeps this robust against the wrap + the <tag> decoy.
read -r CATALOG REGISTRY < <(python3 - "$inst" <<'PY'
import re, sys
text = open(sys.argv[1]).read()
text = re.sub(r'<!--.*?-->', ' ', text, flags=re.S)   # drop the <tag> template comment
flat = re.sub(r'\s+', ' ', text)
def first_tag(marker):
    m = re.search(re.escape(marker) + r'\s*`([^`]+)`', flat)
    return m.group(1) if m else ''
print(first_tag('Compatible blis-catalog release:'), first_tag('Compatible blis-registry release:'))
PY
)
KERNEL=$(grep -E 'blis-latency-kernel ' "$gomod" | awk '{print $2}')

# The vLLM release this BLIS build models: read from blis-vllm's own Upstream provenance var, NOT
# the blis-vllm MODULE tag (the two are not guaranteed to match -- Upstream.Tag is the upstream
# vLLM tag, the module tag is blis-vllm's own release). `go doc` prints the composite literal
# without compiling anything, as written in source -- so isolate the Tag: field specifically
# (grep, not a positional field split) to stay correct whether the literal is one line or many.
# Run from inside the checkout so the blis-vllm version is the one this release's go.mod pins.
VLLM=$( cd "$checkout" && GOFLAGS=-mod=mod go doc github.com/inference-sim/blis-vllm Upstream 2>/dev/null \
          | grep -oE 'Tag:[[:space:]]*"[^"]+"' | head -1 | sed -E 's/.*"([^"]+)"/\1/' )

if [[ -z "$CATALOG" || -z "$REGISTRY" || -z "$KERNEL" || -z "$VLLM" ]]; then
  echo "FATAL: could not derive catalog/registry/kernel/vllm from $checkout" >&2
  echo "  catalog=$CATALOG registry=$REGISTRY kernel=$KERNEL vllm=$VLLM" >&2
  exit 1
fi

echo "catalog=${CATALOG}" | tee -a "$out"
echo "registry=${REGISTRY}" | tee -a "$out"
echo "kernel=${KERNEL}" | tee -a "$out"
echo "vllm=${VLLM}" | tee -a "$out"
echo "derived catalog=${CATALOG} registry=${REGISTRY} kernel=${KERNEL} vllm=${VLLM} from ${checkout}" >&2
