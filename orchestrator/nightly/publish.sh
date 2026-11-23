#!/usr/bin/env bash
# Commit the night's data, only if every check passes.
#
#   publish.sh [--dry-run] MESSAGE
#
# Runs $PUBLISH_CHECKS (default: checks.sh beside this file) on the working tree, then stages data/, the two state
# files and the dump lane's last result (state/dump/, when there is one) and makes one commit with MESSAGE. It never pushes. A failing check stops it with that check's status and
# nothing is committed. With --dry-run it runs the checks and commits nothing.
# Exit status: 0 committed (or dry run passed), 10 nothing to commit, anything else a failed check or git error.
set -euo pipefail
dry=false
if [ "${1:-}" = "--dry-run" ]; then dry=true; shift; fi
msg="${1:?publish.sh: a commit message is required}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
checks="${PUBLISH_CHECKS:-$here/checks.sh}"
bash "$checks"
if [ "$dry" = true ]; then exit 0; fi
stage=(data state/last-run-api.json state/scored-releases.json)
[ -d state/dump ] && stage+=(state/dump)
git add -A "${stage[@]}"
if git diff --cached --quiet; then
  echo "nothing to commit (index unchanged)"
  exit 10
fi
git commit -q -m "$msg"
