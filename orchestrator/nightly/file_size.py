#!/usr/bin/env python3
"""Stop a publish when a file it would commit is near GitHub's 100 MB limit.

    file_size.py PATH [PATH ...] [--limit-mb 90]

Each PATH is a file or a directory (every file under it is checked). GitHub's pre-receive hook refuses a push holding a file
over 100 MB (GH001), after the whole night has been scored: the 2026-11-22 preview night's summary.json was 105 MB written
indented. The limit here is 90 MB, so a file that is merely growing is caught the night before it would be refused.
"""
from __future__ import annotations

import sys
from pathlib import Path

LIMIT_MB = 90
MB = 1024 * 1024


def oversize(paths, limit_mb: float = LIMIT_MB) -> list[tuple[str, float]]:
    """(path, size in MB) of every file at or under PATHS larger than the limit, largest first."""
    found = []
    for root in map(Path, paths):
        for f in ([root] if root.is_file() else sorted(root.rglob("*")) if root.is_dir() else []):
            if f.is_file() and not f.is_symlink() and f.stat().st_size > limit_mb * MB:
                found.append((str(f), f.stat().st_size / MB))
    return sorted(found, key=lambda x: -x[1])


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    limit = LIMIT_MB
    if "--limit-mb" in args:
        i = args.index("--limit-mb")
        limit = float(args[i + 1])
        del args[i:i + 2]
    big = oversize(args, limit)
    for path, mb in big:
        print(f"file_size: {path} is {mb:.1f} MB, over the {limit:g} MB limit (GitHub refuses a file over 100 MB); the publish stops",
              file=sys.stderr)
    return 1 if big else 0


if __name__ == "__main__":
    sys.exit(main())
