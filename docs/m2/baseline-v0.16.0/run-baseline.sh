#!/bin/bash
# The exact command that produced the baseline; run from a clean checkout of the harness commit.
cd /tmp/harness-H
export PATH=/tmp/ci-venv/bin:$PATH
exec /usr/bin/time -l bash harness/run.sh --sim v0.16.0 \
  --units /tmp/baseline/units.txt --pull /tmp/baseline/pull2 --out /tmp/baseline/out \
  --catalog /tmp/substrate-v013/catalog --registry /tmp/substrate-v013/registry \
  --corpus-dir /tmp/baseline/corpus --fields /tmp/fields.json \
  --catalog-release v0.13.0 --registry-release v0.13.0
