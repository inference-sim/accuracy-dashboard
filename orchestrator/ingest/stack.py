"""What one simulator build runs, from its stack.json (design SIM-3, LIF-6; X8).

Each inference-sim release lists in stack.json the exact version of every BLIS module it was
built with and the one upstream release of each engine it runs. The scorer reads the engine
release from here (engine.version, design §11.2). It never parses installation.md's
"Compatible blis-catalog release" lines.

The reader is strict (SUB-12): unknown keys are refused.
"""
from __future__ import annotations

import json
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
