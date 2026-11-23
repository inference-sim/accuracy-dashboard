"""The scoring surface: every file the candidate run executes or reads, hashed as a tree.

The surface is state/gate/accuracy-paths.json's list, read from the trusted base, without test modules and without
the simulator pin. A trusted job recomputes the hash from a commit's own files, never from a claim the commit makes,
so a candidate cannot pass off its own scorer or harness as main's.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath

PIN = ".github/stack-pins.env"  # the simulator pin differs between the sides by design; binding.check_side ties each to its own data


def is_test(path: str) -> bool:
    name = PurePosixPath(path).name
    return name.startswith("test_") and name.endswith(".py")


def _entry(path: Path) -> str:
    return "link:" + os.readlink(path) if path.is_symlink() else hashlib.sha256(path.read_bytes()).hexdigest()


def tree(root, paths: list[str]) -> dict[str, str]:
    """Path to content hash for every surface file under `root`; a symlink is hashed by its target, never followed."""
    root, out = Path(root), {}
    for p in paths:
        if p == PIN:
            continue
        top = root / p.rstrip("/")
        if p.endswith("/"):
            for here, dirs, files in os.walk(top):
                for name in sorted(dirs + files):
                    f = Path(here) / name
                    if f.is_symlink() or not f.is_dir():
                        out[f.relative_to(root).as_posix()] = _entry(f)
        elif top.is_symlink() or top.is_file():
            out[p] = _entry(top)
    return {k: v for k, v in sorted(out.items()) if not is_test(k)}


def digest(root, paths: list[str]) -> str:
    h = hashlib.sha256()
    for k, v in tree(root, paths).items():
        h.update(f"{k}\0{v}\n".encode())
    return h.hexdigest()


def differing(a, b, paths: list[str]) -> list[str]:
    ta, tb = tree(a, paths), tree(b, paths)
    return sorted(k for k in ta.keys() | tb.keys() if ta.get(k) != tb.get(k))
