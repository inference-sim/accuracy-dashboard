"""What one simulator build runs, from its stack.json (design SIM-3, LIF-6; X8).

Each inference-sim release lists in stack.json the exact version of every BLIS module it was
built with and the one upstream release of each engine it runs. The scorer reads the engine
release from here (engine.version, design §11.2). It never parses installation.md's
"Compatible blis-catalog release" lines.

The reader is strict (SUB-12): unknown keys are refused.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_STACK_KEYS = {"kind", "toolchain", "modules", "engines", "router", "guides_commit"}
_MODULE_KEYS = {"path", "version", "commit", "replaces"}
_UPSTREAM_KEYS = {"kind", "version", "commit"}


class StackError(ValueError):
    pass


@dataclass(frozen=True)
class Stack:
    engines: dict          # kind -> {"version", "commit"}
    modules: dict          # path -> {"version", "commit"}
    router: dict
    toolchain: str

    def engine(self, kind: str) -> str:
        e = self.engines.get(kind)
        if e is None:
            raise StackError(f"stack.json lists no {kind!r} engine; it runs {sorted(self.engines)}")
        return e["version"]


def _keys(obj, allowed, where):
    if not isinstance(obj, dict):
        raise StackError(f"{where}: not an object")
    extra = sorted(set(obj) - allowed)
    if extra:
        raise StackError(f"{where}: unknown key {extra[0]!r}")
    return obj


def parse(text: str) -> Stack:
    doc = _keys(json.loads(text), _STACK_KEYS, "stack.json")
    if doc.get("kind") != "Stack":
        raise StackError(f"stack.json kind {doc.get('kind')!r}, want 'Stack'")
    engines = {}
    for i, e in enumerate(doc.get("engines") or []):
        _keys(e, _UPSTREAM_KEYS, f"engines[{i}]")
        if e.get("kind") in engines:
            raise StackError(f"engines[{i}]: a second {e['kind']!r} engine; each release runs one (LIF-6)")
        engines[e["kind"]] = {"version": e["version"], "commit": e.get("commit")}
    modules = {}
    for i, m in enumerate(doc.get("modules") or []):
        _keys(m, _MODULE_KEYS, f"modules[{i}]")
        modules[m["path"]] = {"version": m["version"], "commit": m.get("commit")}
    return Stack(engines=engines, modules=modules, router=_keys(doc.get("router") or {}, _UPSTREAM_KEYS, "router"),
                 toolchain=doc.get("toolchain", ""))


def load(path) -> Stack:
    return parse(Path(path).read_text())


# ------------------------------------------------------------------ COV-9: each release once

_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def _version(tag: str) -> tuple[int, int, int]:
    m = _TAG.match(tag)
    if not m:
        raise StackError(f"{tag!r} is not a stable release tag vX.Y.Z")
    return tuple(int(x) for x in m.groups())


def unscored_releases(tags_in_tag_order: list[str], scored: set[str], first: str) -> list[str]:
    """The releases a nightly run scores (COV-9): every stable release at or after `first`, in
    the order they were tagged, that has no scores yet. Each is scored exactly once. A tag that is
    not vX.Y.Z (a pre-release) is not a release to score. Empty when no such release exists yet."""
    floor = _version(first)
    return [t for t in tags_in_tag_order if _TAG.match(t) and _version(t) >= floor and t not in scored]


def published_releases(snapshot_dirs: list[str]) -> set[str]:
    """The simulator releases that have published scores: data/snapshots/<date>_blis-<tag>_<ix>."""
    out = set()
    for name in snapshot_dirs:
        m = re.match(r"^\d{4}-\d{2}-\d{2}_blis-(v[^_]+)_", name)
        if m:
            out.add(m.group(1))
    return out


# The first simulator release scored on graded points and stack.json: every stable release from
# it on is scored once (COV-9); the ones before keep their published snapshots.
FIRST_GRADED_RELEASE = "v0.16.0"


def main(argv=None) -> int:
    """Print, one per line in tag order, the simulator releases a night scores (COV-9): every
    stable release from FIRST_GRADED_RELEASE on with no published snapshot under --data-dir.

        python3 orchestrator/ingest/stack.py --tags TAGS --data-dir data
    """
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("--tags", required=True, help="inference-sim tags, one per line, in the order they were tagged")
    ap.add_argument("--data-dir", required=True, help="the published data tree (its snapshots/)")
    a = ap.parse_args(argv)
    tags = [t.strip() for t in Path(a.tags).read_text().splitlines() if t.strip()]
    snaps = Path(a.data_dir) / "snapshots"
    names = [p.name for p in snaps.iterdir()] if snaps.is_dir() else []
    for t in unscored_releases(tags, published_releases(names), FIRST_GRADED_RELEASE):
        print(t)
    return 0


if __name__ == "__main__":
    sys.exit(main())
