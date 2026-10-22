#!/usr/bin/env bash
# The evaluate pipeline (RFC §4.3/§4.6, M1→M2): build blis+signedprobe+metricscore FROM SOURCE
# at the resolved BLIS tag; derive catalog/registry; ingest the InferenceX dump via the DIRECT
# extractor (vLLM-filtered); run signedprobe per point; shape the CSV into summary.json.
#
# The dashboard OWNS the Python it runs (issue #20): the direct extractor, the three gen_direct_*
# generators and the scenario generator live in orchestrator/ and are invoked from there, not
# cloned from blis-latency-kernel each run. What is still built FROM the inference-sim source under
# test is only what is being MEASURED — blis, signedprobe and metricscore. The kernel version is
# still derived (resolve_versions.sh, from go.mod) and recorded in provenance, but no longer cloned.
# No scoring logic lives here: signedprobe + build_summary do the scoring; this script is the glue.
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
# Capture resolve_versions' output and its exit status explicitly. The old form piped it through
# `eval "$(… 2>/dev/null | …)"` which swallowed the resolver's FATAL message AND its exit code, so
# a failed resolve surfaced only as a confusing "catalog: parameter null" later (PR #3 review
# P-resolve). Now its stderr reaches the log and a non-zero resolve fails the run loud.
RESOLVED=$(bash "$DASH_DIR/orchestrator/resolve_versions.sh" "$SIM") || {
  log "FATAL: resolve_versions.sh failed for ${BLIS_TAG} — cannot derive catalog/registry/kernel"
  exit 6
}
eval "$(printf '%s\n' "$RESOLVED" | sort -u | sed 's/^/export /')"
: "${catalog:?resolve_versions did not emit catalog}"
: "${registry:?resolve_versions did not emit registry}"
: "${kernel:?resolve_versions did not emit kernel}"
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
# The direct extractor + generators are dashboard-owned (orchestrator/, issue #20): no kernel
# clone. The kernel tag is still DERIVED (resolve_versions.sh, from go.mod) and recorded in
# provenance below, since it is what the registry coefficients were fitted against — but the
# scripts that read the dump now live here and are run from $DASH_DIR/orchestrator.
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
# The extractor is dashboard-owned (orchestrator/); the corpus is restricted to framework=vllm by
# the direct extractor's own SQL (RFC §4.6). signedprobe has no -framework flag.
python3 "$DASH_DIR/orchestrator/extract_inferencex_direct.py" --out "$WORK/inferencex_direct.raw.json"

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

# Each generator reads the filtered direct.json and MUST succeed. No `2>/dev/null || <fallback>`
# chains (PR #3 review point 1): a fallback to a different extractor either silently changes where
# the data comes from, or (for absolutes) can't even run — and both hide the real error. Under
# `set -e` a generation failure now fails the whole run, loud, as RFC §4.6 requires.
python3 "$DASH_DIR/orchestrator/gen_direct_corpus.py"          -c "$WORK/inferencex_direct.json" -o "$CORPUS"
python3 "$DASH_DIR/orchestrator/gen_direct_absolutes.py"       -c "$WORK/inferencex_direct.json" -o "$ABS"
python3 "$DASH_DIR/orchestrator/gen_direct_engine_settings.py" -c "$WORK/inferencex_direct.json" -o "$SETTINGS"

# Scenario files the direct corpus references are generated in-pipeline from the current dump
# (RFC §4.6). The generator is dashboard-owned (orchestrator/gen_scenarios.py) and called by name
# — no glob (there is exactly one, here), and crucially NO `cp -n` of frozen testdata scenarios:
# that fallback would silently score a new dump against stale committed scenarios (PR #3 review
# point 1). It MUST succeed (no `|| true`); under `set -e` a failure fails the whole run.
# The generator takes the corpus positionally and writes into -o.
python3 "$DASH_DIR/orchestrator/gen_scenarios.py" "$CORPUS" -o "$SCENARIOS"
nscen=$(ls "$SCENARIOS"/*.yaml 2>/dev/null | wc -l | tr -d ' ')
log "generated ${nscen} scenario file(s) from the current dump"
if [[ "$nscen" -eq 0 ]]; then
  log "FATAL: scenario generation produced no files — refusing to score against an empty/stale set"
  exit 5
fi

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
# measurement_sha256 identifies the WHOLE dump: the sha256 of the release's SHA256SUMS asset, which
# lists every part's hash. (It used to be line 1 of that file, i.e. part00 only, so a change in any
# other part left it unchanged; and any download failure became "unknown" in published provenance.)
# A missing or empty SHA256SUMS now fails the run (#9).
SUMS="$WORK/SHA256SUMS"
gh release download "$IX_TAG" --repo SemiAnalysisAI/InferenceX-app -p SHA256SUMS -O "$SUMS" --clobber
if [[ ! -s "$SUMS" ]]; then
  log "FATAL: ${IX_TAG} has no usable SHA256SUMS asset — cannot pin the dump in provenance"
  exit 7
fi
MEAS_SHA=$(sha256sum "$SUMS" | awk '{print $1}')
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
# Coverage accounting MUST balance: every corpus point is either scored or not_scored, and the
# not_scored reasons must sum to not_scored (PR #3 review P-coverage). Assert the identity and fail
# loud rather than silently publishing a summary whose counts don't add up. Note `emitted` /
# scored_keys are SETS keyed by (scenario,label,concurrency); a repeat-concurrency row collapses
# here — that's an accepted v0.1.0 limitation, noted, not hidden.
scored = len(emitted)
if scored + not_scored != total_points:
    print(f"FATAL: coverage does not balance: scored({scored}) + not_scored({not_scored}) "
          f"!= total_points({total_points})", file=sys.stderr)
    sys.exit(7)
if sum(reasons.values()) != not_scored:
    print(f"FATAL: not_scored_reasons sum ({sum(reasons.values())}) != not_scored ({not_scored})", file=sys.stderr)
    sys.exit(7)
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
  # No hard-coded artefact claims (PR #3 review point 2): the old "gpt-oss-120b/h200 TTFT spikes (4)"
  # was a fixed string for a rule that runs nowhere, and the count was wrong (5, not 4). v0.1.0
  # applies no exclusions and computes no artefact list, so the honest value is empty.
  "known_artefacts": []
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
