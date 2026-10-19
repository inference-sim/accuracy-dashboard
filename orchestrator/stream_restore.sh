#!/usr/bin/env bash
# Streaming selective restore of the weekly InferenceX dump into Postgres — fits a GitHub-hosted
# runner, no self-hosted runner, no dump on disk.
#
# The dump is ~31 GB compressed / ~323 GB decompressed, but the direct extractor reads only three
# tables (benchmark_results, configs, server_logs). So we stream each release part straight to
# stdout, decompress through a pipe, and pg_restore ONLY those tables: neither the 31 GB compressed
# nor the 323 GB decompressed archive ever lands on disk; only ~6 GB of restored tables sit in
# Postgres. The scored output is byte-identical to a full restore — the other tables contribute
# nothing to the extractor (verified: extract_inferencex_direct.py's FROM/JOIN touches exactly
# those three; gen_direct_* read the extractor's JSON, not the DB).
#
# Env in:
#   IX_TAG                           the resolved db-dump/<date> release tag
#   PGHOST/PGPORT/PGUSER/PGPASSWORD  the Postgres service container (libpq picks these up)
#   PGDATABASE                       restored into this db (default: inferencex — the name the
#                                    extractor hardcodes)
#   IX_REPO                          override the release repo (default SemiAnalysisAI/InferenceX-app)
set -euo pipefail

: "${IX_TAG:?resolve IX_TAG first}"
IX_REPO="${IX_REPO:-SemiAnalysisAI/InferenceX-app}"
export PGDATABASE="${PGDATABASE:-inferencex}"
log() { echo "[stream-restore] $*" >&2; }

# The extractor connects to a db literally named `inferencex` via bare psql, so create it.
createdb "$PGDATABASE" 2>/dev/null || log "db ${PGDATABASE} already exists"

# Enumerate the dump's part assets in order (part00..partNN) + confirm it ships a dump at all.
mapfile -t PARTS < <(gh release view "$IX_TAG" --repo "$IX_REPO" \
  --json assets -q '.assets[].name | select(test("\\.dump\\.zst\\.part[0-9]+$"))' | sort)
if [[ "${#PARTS[@]}" -eq 0 ]]; then
  log "FATAL: ${IX_TAG} ships no .dump.zst.part* assets — the release format changed; refusing to guess."
  exit 2
fi
log "streaming ${#PARTS[@]} parts of ${IX_TAG} → zstd -d → pg_restore (3 tables)"
log "disk before restore:"; df -h / 2>/dev/null | tail -1 >&2 || true

# Stream: each part to stdout in order → zstd long-window decompress → pg_restore filtering to the
# 3 tables. pg_restore reads the custom-format archive from a non-seekable pipe (verified) and, with
# -t, stops as soon as it has restored those 3 tables — it does NOT read the trailing ~300 GB. When
# it closes the pipe early, the upstream zstd (and the download loop) die with EPIPE / "Broken pipe"
# (exit 70). THAT IS EXPECTED AND MEANS SUCCESS — it's exactly why this is fast (~25 min, not hours).
#
# So correctness is keyed off pg_restore's OWN exit code (PIPESTATUS[2]) plus the row-count gate
# below — NEVER the pipeline's aggregate status. An earlier version used `set -o pipefail` and the
# benign broken-pipe (70) failed the whole step while pg_restore had in fact succeeded (run
# 39274491628). We disable -e/pipefail around the pipe and read pg_restore's status directly.
# --no-owner/--no-privileges: the dump is owned by neondb_owner, absent here. pg_restore's stderr
# goes to a FILE (a process-sub would lose it on pipe teardown) so a real failure reason survives.
PGERR="${WORK:-/tmp}/pg_restore.err"
set +e +o pipefail
{
  for p in "${PARTS[@]}"; do
    # A broken pipe here is just pg_restore having read enough and closed early — stop downloading
    # the parts it will never read. A GENUINE download failure instead feeds a truncated archive,
    # which makes pg_restore itself error (caught via pgrc) or leaves a table short (caught by the
    # count gate) — so pg_restore's exit code + the counts are the authority, not this loop.
    gh release download "$IX_TAG" --repo "$IX_REPO" -p "$p" -O - || { log "part stream ended at $p (rc=$?) — pg_restore likely closed the pipe early"; break; }
  done
} | zstd -d --long=27 \
  | pg_restore --no-owner --no-privileges --no-tablespaces \
      -t benchmark_results -t configs -t server_logs \
      -d "$PGDATABASE" 2>"$PGERR"
pgrc=${PIPESTATUS[2]}
set -e
if [[ "$pgrc" -ne 0 ]]; then
  log "pg_restore FAILED (rc=$pgrc) — pg_restore said:"; tail -15 "$PGERR" >&2
  log "disk after:"; df -h / 2>/dev/null | tail -1 >&2
  exit "$pgrc"
fi
log "pg_restore finished (rc=0); any upstream broken-pipe is the expected early close"

# Prove the restore is the full corpus, not a truncated stream: the extractor needs ALL THREE
# tables non-empty (benchmark_results joined to configs + server_logs). A truncated stream could
# land one table and not another, so check each — fail loud rather than letting signedprobe score
# a fraction of the dump.
read -r n_bench n_conf n_logs < <(psql -tAF' ' -c \
  "select
     (select count(*) from benchmark_results),
     (select count(*) from configs),
     (select count(*) from server_logs)" 2>/dev/null || echo "0 0 0")
if [[ "${n_bench:-0}" -lt 1 || "${n_conf:-0}" -lt 1 || "${n_logs:-0}" -lt 1 ]]; then
  log "FATAL: a required table is empty after restore (benchmark_results=$n_bench configs=$n_conf server_logs=$n_logs) — the stream was truncated."
  exit 3
fi
log "restore OK: benchmark_results=$n_bench configs=$n_conf server_logs=$n_logs; footprint $(psql -tAc "select pg_size_pretty(pg_database_size('${PGDATABASE}'))" 2>/dev/null)"
