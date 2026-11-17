"""Remembered answers of the network lookups a pull makes, so a pull frozen once is replayed with no new requests.

The build resolver (build.Resolver) asks GitHub about vLLM commits (resolve_commit, tag_commit, compare, merge_base,
is_on_release_tag) and Docker Hub about image labels (revision_label). Each answer is a fact about the named commits
and images, so it is recorded once, when the ledger's pull is frozen (ledger_extract.py freeze), and read back by every
night that replays it. A question not recorded (a new engine release moves the reference the distance is measured
from) is asked live, recorded, and counted, so a night reports how many requests it made.
"""
from __future__ import annotations

import json
import threading

GITHUB_METHODS = ("resolve_commit", "tag_commit", "compare", "merge_base", "is_on_release_tag")
REGISTRY_METHODS = ("revision_label",)


class Recorded:
    """`inner` with the calls to `methods` answered from `store` (by method and arguments), else asked of `inner`
    and recorded. `misses` counts the calls asked of `inner`."""

    def __init__(self, inner, store: dict, methods: tuple[str, ...]):
        self._inner, self._store, self._methods = inner, store, set(methods)
        self._lock = threading.Lock()
        self.misses = 0

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if name not in self._methods:
            return attr

        def call(*args):
            key = json.dumps([name, *args])
            with self._lock:
                if key in self._store:
                    got = self._store[key]
                    return tuple(got) if name == "compare" else got
            got = attr(*args)
            with self._lock:
                self._store[key] = list(got) if isinstance(got, tuple) else got
                self.misses += 1
            return got
        return call


def wrap(resolver, store: dict) -> tuple[Recorded, Recorded]:
    """Point `resolver`'s GitHub and registry at `store` ({"github": {...}, "registry": {...}}), in place."""
    gh = Recorded(resolver.github, store.setdefault("github", {}), GITHUB_METHODS)
    reg = Recorded(resolver.registry, store.setdefault("registry", {}), REGISTRY_METHODS)
    resolver.github, resolver.registry = gh, reg
    return gh, reg
