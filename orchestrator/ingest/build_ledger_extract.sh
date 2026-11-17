#!/usr/bin/env bash
# build_ledger_extract.sh SUBSTRATE_DIR OUT_DIR: build the ledger extract for the blis-substrate checkout SUBSTRATE_DIR
# (ledger_extract.py; docs/nightly.md) into OUT_DIR/ledger-extract.jsonl.gz, and its pin into OUT_DIR/ledger-extract.json.
#
# It restores the four tables the extract reads from the dump catalog/ledger/sources.yaml pins into a scratch
# PostgreSQL 17 cluster (each part checked against its SHA-256, one part on disk at a time), fetches the pinned
# supplements with the substrate's own `ledger supplement-records`, writes the extract, and checks that its rows place
# exactly the ledger's units. The same checkout gives the same bytes. Needs PostgreSQL 17 (PG_BIN, default
# /usr/lib/postgresql/17/bin), zstd, go and the Python packages of requirements-ci.txt. The dump is only restored,
# never executed; the extract is third-party data and is never committed (X12).
set -euo pipefail
sub=${1:?usage: build_ledger_extract.sh SUBSTRATE_DIR OUT_DIR}
out=${2:?usage: build_ledger_extract.sh SUBSTRATE_DIR OUT_DIR}
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pg=${PG_BIN:-/usr/lib/postgresql/17/bin}
work=$(mktemp -d)
cleanup() { "$pg/pg_ctl" -D "$work/pgdata" -m fast stop >/dev/null 2>&1 || true; rm -rf "$work"; }
trap cleanup EXIT
"$pg/initdb" -D "$work/pgdata" -U "$USER" --auth=trust >/dev/null
"$pg/pg_ctl" -D "$work/pgdata" -o "-p 5499 -k $work -c listen_addresses=''" -w -l "$work/pg.log" start >/dev/null
export PGHOST="$work" PGPORT=5499
start=$(date +%s)
python3 "$here/ledger_extract.py" restore --sources "$sub/catalog/ledger/sources.yaml" --bin "$pg"
echo "build_ledger_extract: restored in $(( $(date +%s) - start )) s" >&2
( cd "$sub" && go run ./ledger/cmd/ledger supplement-records -out "$work/supplements.json" catalog/ledger >&2 )
mkdir -p "$out"
python3 "$here/ledger_extract.py" build --psql "$pg/psql" --export-sql "$sub/ledger/inferencex/export.sql" \
  --supplements "$work/supplements.json" --ledger "$sub/catalog/ledger" --sources "$sub/catalog/ledger/sources.yaml" \
  --out "$out/ledger-extract.jsonl.gz" > "$work/info.json"
ref=$(git -C "$sub" describe --tags --exact-match 2>/dev/null || git -C "$sub" rev-parse HEAD)
python3 - "$work/info.json" "$ref" > "$out/ledger-extract.json" <<'PY'
import json, sys
info = json.load(open(sys.argv[1]))
print(json.dumps({"kind": "LedgerExtract", "substrate_ref": sys.argv[2], "ledger_revision": info["ledger_revision"],
                  "sha256": info["sha256"], "bytes": info["bytes"], "rows": info["rows"], "logs": info["logs"],
                  "units": info["units"], "source_sha256": info["source_sha256"],
                  "cache_key": f"ledger-extract-{info['sha256']}"}, indent=1, sort_keys=True))
PY
cat "$out/ledger-extract.json"
