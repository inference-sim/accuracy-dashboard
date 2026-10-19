#!/usr/bin/env bash
# The evaluate pipeline (RFC §4.3/§4.6, M1→M2): build blis+signedprobe+metricscore FROM SOURCE
# at the resolved BLIS tag; derive catalog/registry; ingest the InferenceX dump via the DIRECT
# extractor (vLLM-filtered); run signedprobe per point; shape the CSV into summary.json.
#
# This repo is glue only (RFC A4): it orchestrates upstream tools and shapes their output. No
# scoring logic, no copied extractors, no log parsing lives here.
#
# Ingest fits a GitHub-hosted runner via STREAMING SELECTIVE RESTORE (orchestrator/stream_restore.sh):
# the ~31 GB compressed dump streams straight from the GitHub release through `zstd -d` into
# `pg_restore -t` for only the 3 tables the extractor reads — the 31 GB compressed and the ~323 GB
# decompressed archive NEVER land on disk; only ~6 GB of restored tables sit in the Postgres service
# container. The scored output is the full corpus, byte-identical to a full restore (verified: the
# other tables contribute nothing to the extractor). No self-hosted runner, no on-disk dump.
#
# Env in:
#   BLIS_TAG, IX_TAG                 resolved inputs (resolve_inputs.sh)
#   WORK                             scratch dir (default: $PWD/.work)
#   PGHOST/PGPORT/PGUSER/PGPASSWORD  Postgres service container the extractor's psql reaches
#                                    (stream_restore.sh restores db `inferencex` into it)
#   DASH_DIR                         this repo root (for orchestrator/ + schemas/)
set -euo pipefail

: "${BLIS_TAG:?resolve BLIS_TAG first}"
: "${IX_TAG:?resolve IX_TAG first}"
WORK="${WORK:-$PWD/.work}"
DASH_DIR="${DASH_DIR:-$PWD}"
mkdir -p "$WORK"
# blis replay resolves -catalog/-registry relative to ITS OWN cwd, so every path handed to the
# upstream tools must be absolute (verified: a relative -catalog makes blis fail to find it).
WORK="$(cd "$WORK" && pwd)"
DASH_DIR="$(cd "$DASH_DIR" && pwd)"

log() { echo "[evaluate] $*" >&2; }

# ---------------------------------------------------------------- 1. build upstream FROM SOURCE
log "cloning inference-sim @ ${BLIS_TAG}"
SIM="$WORK/inference-sim"
rm -rf "$SIM"
git clone -q --depth 1 --branch "$BLIS_TAG" https://github.com/inference-sim/inference-sim.git "$SIM"
SIM_SHA=$(git -C "$SIM" rev-parse HEAD)

log "deriving catalog/registry/kernel from ${BLIS_TAG}"
eval "$(bash "$DASH_DIR/orchestrator/resolve_versions.sh" "$SIM" 2>/dev/null | sort -u | sed 's/^/export /;s/=/=/')"
: "${catalog:?}" ; : "${registry:?}" ; : "${kernel:?}"
log "catalog=$catalog registry=$registry kernel=$kernel"

log "building blis, signedprobe, metricscore from source"
( cd "$SIM" && GOFLAGS=-mod=mod go build -o blis main.go \
    && GOFLAGS=-mod=mod go build -o signedprobe ./cmd/signedprobe \
    && GOFLAGS=-mod=mod go build -o metricscore ./cmd/metricscore )

log "fetching catalog ${catalog} + registry ${registry} (from their own repos, by installation.md)"
CAT="$WORK/catalog"; REG="$WORK/registry"
rm -rf "$CAT" "$REG"
git clone -q --depth 1 --branch "$catalog"  https://github.com/inference-sim/blis-catalog.git  "$CAT"
git clone -q --depth 1 --branch "$registry" https://github.com/inference-sim/blis-registry.git "$REG"

# ---------------------------------------------------------------- 2. ingest (DIRECT path only)
# Clone the kernel at the go.mod-pinned tag; its scripts are the extractors (not copied here).
log "cloning blis-latency-kernel @ ${kernel} for the direct extractor"
KER="$WORK/blis-latency-kernel"
rm -rf "$KER"
git clone -q --depth 1 --branch "$kernel" https://github.com/inference-sim/blis-latency-kernel.git "$KER"

CORPUS="$WORK/inferencex_direct_corpus.json"
ABS="$WORK/inferencex_direct_absolutes.json"
SETTINGS="$WORK/inferencex_direct_settings.json"
DIRECT="$WORK/inferencex_direct.json"   # carries each run's real container image → true vLLM version
SCENARIOS="$WORK/scenarios"
mkdir -p "$SCENARIOS"

# Stream the resolved weekly dump into the Postgres service container (3 tables only, nothing on
# disk). This is the single ingest path — the full real corpus, on a hosted runner.
log "streaming selective restore of ${IX_TAG} into Postgres (3 tables, no dump on disk)"
bash "$DASH_DIR/orchestrator/stream_restore.sh"

log "running the direct extractor (vLLM-filtered in SQL) + scenario generation"
# The extractors run at the kernel tag; the corpus is restricted to framework=vllm by the
# direct extractor's own SQL (RFC §4.6). signedprobe has no -framework flag.
python3 "$KER/scripts/extract_inferencex_direct.py"          --out "$WORK/inferencex_direct.raw.json"

# Filter the direct corpus to the vLLM versions worth scoring BEFORE the gen_direct_* scripts read
# it (RFC discussion #2, point 2 — replaces the on-target-v0.31.0 rule). Two reductions, both at the
# superset file: (1) keep only the latest ${VLLM_LATEST_N:-5} NUMBERED versions present in this dump;
# (2) since BLIS's prediction is independent of the vLLM version, keep only the NEWEST surviving
# version per BLIS-input identity — so each prediction is scored ONCE, against the latest build. This
# is glue (selection only); signedprobe + build_summary are unchanged and just see a smaller corpus.
# The output takes the canonical name every downstream step + $DIRECT already read.
log "filtering direct corpus to latest ${VLLM_LATEST_N:-5} numbered vLLM versions (+ dedup to latest)"
python3 "$DASH_DIR/orchestrator/filter_latest_vllm.py" \
  --in "$WORK/inferencex_direct.raw.json" --out "$WORK/inferencex_direct.json" -n "${VLLM_LATEST_N:-5}"

python3 "$KER/scripts/gen_direct_corpus.py"            -c "$WORK/inferencex_direct.json" -o "$CORPUS"
python3 "$KER/scripts/gen_direct_absolutes.py"         -c "$WORK/inferencex_direct.json" -o "$ABS"      2>/dev/null \
  || python3 "$KER/scripts/extract_inferencex_absolutes.py"  --out "$ABS"
python3 "$KER/scripts/gen_direct_engine_settings.py"   -c "$WORK/inferencex_direct.json" -o "$SETTINGS" 2>/dev/null \
  || python3 "$KER/scripts/extract_inferencex_engine_settings.py" -c "$CORPUS" -a "$ABS" -o "$SETTINGS"
# Scenario files the direct corpus references are generated in-pipeline from the current dump
# (RFC §4.6). The kernel repo's scenario generator is discovered by glob rather than named
# here, so this repo's code stays free of any third-party baseline's name (RFC C1); it is run
# as-is from the pinned kernel checkout, not vendored.
gen_scen=$(ls "$KER"/scripts/gen_*scenario*.py 2>/dev/null | head -1 || true)
if [[ -n "$gen_scen" ]]; then
  python3 "$gen_scen" "$CORPUS" -o "$SCENARIOS" 2>/dev/null \
    || python3 "$gen_scen" -c "$CORPUS" -o "$SCENARIOS" 2>/dev/null || true
fi
# Any committed direct scenarios the generator also needs:
cp -n "$KER"/testdata/direct/*.yaml "$SCENARIOS"/ 2>/dev/null || true

# ---------------------------------------------------------------- 3. signedprobe (per-point CSV)
log "running signedprobe (all flags explicit) — the single source of truth"
CSV="$WORK/signedprobe.csv"
"$SIM/signedprobe" \
  -blis "$SIM/blis" \
  -corpus "$CORPUS" \
  -scenarios "$SCENARIOS" \
  -absolutes "$ABS" \
  -engine-settings "$SETTINGS" \
  -catalog "$CAT" \
  -registry "$REG" \
  > "$CSV" 2> "$WORK/signedprobe.err" || {
    log "signedprobe failed — see $WORK/signedprobe.err; publishing nothing"
    tail -20 "$WORK/signedprobe.err" >&2
    exit 4
  }
log "signedprobe emitted $(($(wc -l < "$CSV") - 1)) point rows"

# metricscore is the LOGGED, non-blocking diagnostic (RFC A6/§4.5). Under time pressure it may
# be skipped; signedprobe's points are never cut.
METRIC_LOG="$WORK/metricscore.log"
if [[ "${SKIP_METRICSCORE:-0}" != "1" ]]; then
  log "running metricscore (logged diagnostic, never gated)"
  "$SIM/metricscore" \
    -blis "$SIM/blis" -framework vllm \
    -corpus "$CORPUS" -scenarios "$SCENARIOS" -absolutes "$ABS" \
    -engine-settings "$SETTINGS" -catalog "$CAT" -registry "$REG" \
    > "$METRIC_LOG" 2>&1 || log "metricscore diagnostic failed (non-blocking) — continuing"
else
  : > "$METRIC_LOG"
fi

# ---------------------------------------------------------------- 4. provenance + summary.json
log "assembling provenance from the resolved inputs"
IX_DATE="${IX_TAG#db-dump/}"
TODAY="${SNAPSHOT_DATE:-$IX_DATE}"
MEAS_SHA=$(gh release download "$IX_TAG" --repo SemiAnalysisAI/InferenceX-app -p SHA256SUMS -O - 2>/dev/null \
             | head -1 | awk '{print $1}' || echo "unknown")
PROV="$WORK/provenance.json"
python3 - "$PROV" "$BLIS_TAG" "$SIM_SHA" "$catalog" "$registry" "$kernel" "$IX_TAG" "$IX_DATE" "$MEAS_SHA" "$TODAY" "$CSV" "$CORPUS" "$DIRECT" <<'PY'
import json, sys, csv
(out, blis_tag, sim_sha, catalog, registry, kernel, ix_tag, ix_date, meas_sha, today, csv_path, corpus_path, direct_path) = sys.argv[1:14]
# Coverage: compare the corpus against signedprobe's CSV rows (RFC §4.4) — the pipeline never
# parses signedprobe's stderr. A corpus point with no SCORED CSV row is not_scored. An emitted
# row whose tier is UNSCORABLE (chiefly mtp — blis refuses a drafting scenario with no
# acceptance rate) is counted as not_scored:no_acceptance_rate, never as scored.
scored_keys = set()
unscorable_keys = set()
with open(csv_path, newline="") as fh:
    r = csv.DictReader(fh)
    for row in r:
        key = (row["scenario"], row["label"], row["concurrency"])
        if row["tier_unbracketed"] == "UNSCORABLE":
            unscorable_keys.add(key)
        else:
            scored_keys.add(key)
corpus = json.load(open(corpus_path))
total_points = 0
not_scored = 0
reasons = {}
for sw in corpus.get("sweeps", []):
    spec = (sw.get("spec_method") or "none")
    for p in sw.get("points", []):
        total_points += 1
        key = (sw["scenario"], sw["label"], str(p["concurrency"]))
        if key in scored_keys:
            continue
        not_scored += 1
        if (spec and spec != "none") or key in unscorable_keys:
            reasons["no_acceptance_rate"] = reasons.get("no_acceptance_rate", 0) + 1
        else:
            reasons["skipped_or_run_error"] = reasons.get("skipped_or_run_error", 0) + 1
emitted = scored_keys
# The vLLM-version filter applied before scoring (RFC discussion #2 point 2) is recorded in the
# filtered direct.json; surface it in provenance so the published snapshot is self-describing about
# WHICH vLLM versions it scored (fail-loud / auditable).
vllm_filter = None
try:
    vllm_filter = json.load(open(direct_path)).get("vllm_filter")
except (OSError, json.JSONDecodeError):
    pass
snapshot_id = f"{today}_blis-{blis_tag}_ix-{ix_date}"
doc = {
  "snapshot_id": snapshot_id,
  "generated_at": today + "T00:00:00Z",
  "provenance": {
    "blis": {"release": blis_tag, "commit_sha": sim_sha, "catalog": catalog,
             "registry": registry, "extractor_version": f"blis-latency-kernel@{kernel}"},
    "ground_truth": {"source": "SemiAnalysis InferenceX",
                     "source_url": f"https://github.com/SemiAnalysisAI/InferenceX-app/releases/tag/{ix_tag}",
                     "release_tag": ix_tag, "measurement_date_through": None,
                     "measurement_sha256": meas_sha},
    "evaluator_commit": __import__("os").environ.get("GITHUB_SHA", "local"),
    "scorer": "signedprobe",
    "vllm_filter": vllm_filter
  },
  "coverage": {"scored": len(emitted), "not_scored": not_scored, "multinode_hidden": 0,
               "failed": 0, "measured_excluded": 0, "not_scored_reasons": reasons},
  "known_artefacts": ["gpt-oss-120b/h200 TTFT spikes (4)", "non-monotone-TPOT sweeps"]
}
json.dump(doc, open(out, "w"), indent=2)
print(f"provenance: snapshot_id={snapshot_id} scored={len(emitted)} not_scored={not_scored}", file=sys.stderr)
PY

log "shaping CSV into summary.json"
OUT="$WORK/summary.json"
python3 "$DASH_DIR/orchestrator/build_summary.py" \
  --csv "$CSV" --corpus "$CORPUS" --engine-settings "$SETTINGS" --scenarios "$SCENARIOS" \
  ${DIRECT:+$([ -f "$DIRECT" ] && echo --direct "$DIRECT")} \
  --provenance "$PROV" --out "$OUT" --metricscore-log "$METRIC_LOG"

log "validating summary.json against the local schema"
python3 "$DASH_DIR/orchestrator/validate_summary.py" --schema "$DASH_DIR/schemas/summary.v1.json" "$OUT"

echo "$OUT"
