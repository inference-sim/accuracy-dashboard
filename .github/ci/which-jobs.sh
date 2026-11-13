#!/usr/bin/env bash
# Print which checks run for the files a git range changes: which-jobs.sh [BASE [HEAD]] (default origin/main, HEAD),
# using the same three-dot diff the workflow uses.
set -euo pipefail
cd "$(dirname "$0")/../.."
files="$(git diff --name-only --no-renames "${1:-origin/main}...${2:-HEAD}")"
if [ -z "$files" ]; then python3 .github/ci/which_jobs.py --all; exit; fi
list=(); while IFS= read -r l; do list+=("$l"); done <<<"$files"
python3 .github/ci/which_jobs.py "${list[@]}"
