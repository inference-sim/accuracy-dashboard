"""Strict JSON for gate documents: no NaN or infinity, no duplicate object keys.

A gate document is committed state that later decides whether a change may merge, so it is read with no
room for ambiguity. `json` accepts `NaN`, `Infinity` and `-Infinity` (not JSON) and silently keeps the last
of a duplicated object key; both are refused here, naming the offending token or key. Every gate-document
loader reads through `strict_loads` so the refusal is the same wherever a document is read.
"""
from __future__ import annotations

import json


def _reject(constant: str):
    raise ValueError(f"the JSON literal {constant} is not allowed")


def _no_dupes(pairs):
    seen = {}
    for k, v in pairs:
        if k in seen:
            raise ValueError(f"the object key {k!r} appears more than once")
        seen[k] = v
    return seen


def strict_loads(text):
    """Parse JSON text, refusing NaN/Infinity and duplicate object keys with a ValueError that names the cause."""
    return json.loads(text, parse_constant=_reject, object_pairs_hook=_no_dupes)
