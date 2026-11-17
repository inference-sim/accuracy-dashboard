#!/usr/bin/env python3
"""Write orchestrator/sglang_declarations.json: what SGLang's own declarations say of each
ServerArgs field, as the scorer needs it to read a run's launch command.

SGLang prints `server_args=ServerArgs(...)` with every field, resolved (a default chosen by
the model or the chip is printed as the value it took), so the printout cannot say which fields
the run set. The launch command can, by flag. The flag-to-field map and each field's literal
default come from blis-sglang's fields/declarations.json (written by its fields/gen_fields.py
from SGLang's source at the pinned commit), never from this repo:

    python3 -I orchestrator/ingest/gen_sglang_declarations.py DECLARATIONS.json --engine-version 0.5.23 \\
        --source "blis-sglang c3c14e2a fields/declarations.json"

A default that is a factory for an empty list or dict is that value; any other non-literal default
is left out, and a field with none is never taken as at its default.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "sglang_declarations.json"
_FACTORIES = {"msgspec.field(default_factory=list)": [], "msgspec.field(default_factory=dict)": {}}


def extract(decl: dict, engine_version: str, source: str, sha256: str) -> dict:
    fields = {}
    for name, f in sorted(decl["server_args"].items()):
        flags = list(f.get("flags") or [])
        for m in f.get("manual_flags") or []:
            flags += m.get("flags") or []
        row = {"flags": sorted(set(flags)), "type": f.get("type")}
        if "default" in f:
            row["default"] = f["default"]
        elif f.get("default_expr") in _FACTORIES:
            row["default"] = _FACTORIES[f["default_expr"]]
        fields[name] = row
    return {"kind": "SGLangDeclarations", "engine": {"kind": "sglang", "version": engine_version},
            "source": source, "source_sha256": sha256, "fields": fields}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("declarations")
    ap.add_argument("--engine-version", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    raw = Path(a.declarations).read_bytes()
    doc = extract(json.loads(raw), a.engine_version, a.source, hashlib.sha256(raw).hexdigest())
    Path(a.out).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
