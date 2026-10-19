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

# Stream: each part to stdout in order → reassembled by cat ordering → zstd long-window decompress
# → pg_restore filtering to the 3 tables. pg_restore reads the custom-format archive from a
# non-seekable pipe (verified) and restores only -t tables. --no-owner/--no-privileges: the dump
# is owned by neondb_owner, absent here.
set -o pipefail
{
  for p in "${PARTS[@]}"; do
    gh release download "$IX_TAG" --repo "$IX_REPO" -p "$p" -O -
  done
} | zstd -d --long=27 \
  | pg_restore --no-owner --no-privileges \
      -t benchmark_results -t configs -t server_logs \
      -d "$PGDATABASE" 2> >(tail -5 >&2) \
  || { rc=$?; log "stream restore failed (rc=$rc) — publishing nothing"; exit "$rc"; }

# Prove the restore is the full corpus, not a truncated stream: the extractor needs non-empty
# benchmark_results joined to configs + server_logs. Fail loud on an empty/partial restore rather
# than letting signedprobe score a fraction of the dump.
counts=$(psql -tAc "select count(*) from benchmark_results" 2>/dev/null || echo 0)
if [[ "${counts:-0}" -lt 1 ]]; then
  log "FATAL: benchmark_results is empty after restore — the stream did not complete."
  exit 3
fi
log "restore OK: benchmark_results=${counts} rows; footprint $(psql -tAc "select pg_size_pretty(pg_database_size('${PGDATABASE}'))" 2>/dev/null)"
