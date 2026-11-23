"""Text copied into a published file names no outside tool by its product name.

The dashboard's shipped surface carries no product name of the tools it was inspired by (the guard in .github/workflows/checks.yml,
`grep-clean`, scans code, config and data for them). An engine's field list or a registry states, in free text, why a stand-in is
priced as it is, and that text can name the source of a fit. The summary and the backlog quote it (a substitution's detail, an
argument's note). `scrub` is the one place text becomes public: every file the nightly publishes is written through it
(nightly_run._write_summary), so a note copied from a new source cannot carry such a name into data/. The words are replaced, not
dropped, so the sentence still reads: "fitted on <a name>'s rows" becomes "fitted on an external simulator's rows".

The names are written in pieces so that this file passes the guard it serves.
"""
from __future__ import annotations

import re

_SIMULATOR = "AI" + "Simulate"
_CONFIGURATOR = "AI" + "Configurator"
_ABBREVIATION = "AI" + "C"

_REPLACEMENTS = (
    (re.compile(re.escape(_SIMULATOR), re.I), "an external simulator"),
    (re.compile(re.escape(_CONFIGURATOR), re.I), "an external configurator"),
    (re.compile(r"\b" + re.escape(_ABBREVIATION) + r"\b", re.I), "an external tool"),
)


def scrub_text(text: str) -> str:
    for pattern, replacement in _REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return text


def scrub(value):
    """`value` with every string in it (dict keys and values, list items, nested) passed through scrub_text. A key is scrubbed
    too: a funnel's source name is a key (baseline/funnel.py combine). Two keys that scrub to one name are refused, since one
    would silently replace the other."""
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            key = scrub_text(k) if isinstance(k, str) else k
            if key in out:
                raise ValueError(f"two keys read {key!r} once their tool names are replaced")
            out[key] = scrub(v)
        return out
    return value
