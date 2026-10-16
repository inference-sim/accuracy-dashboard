#!/usr/bin/env python3
"""Validate a summary.json against schemas/summary.v1.json (RFC C3).

Invalid input exits non-zero with a clear message so CI catches a format break before the
static site renders garbage -- never a silent pass.
"""
from __future__ import annotations

import argparse
import json
import sys

try:
    import jsonschema
except ImportError:
    print("FATAL: jsonschema not installed (pip install jsonschema)", file=sys.stderr)
    sys.exit(2)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Validate summary.json against the local schema")
    ap.add_argument("--schema", default="schemas/summary.v1.json")
    ap.add_argument("summary")
    args = ap.parse_args(argv)

    with open(args.schema) as fh:
        schema = json.load(fh)
    with open(args.summary) as fh:
        doc = json.load(fh)

    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        print(f"INVALID: {args.summary} fails schemas/summary.v1.json", file=sys.stderr)
        for e in errors[:25]:
            loc = "/".join(str(p) for p in e.path) or "(root)"
            print(f"  at {loc}: {e.message}", file=sys.stderr)
        return 1

    # schema_version is the format gate (RFC §4.4).
    if doc.get("schema_version") != 1:
        print(f"INVALID: schema_version is {doc.get('schema_version')!r}, expected 1", file=sys.stderr)
        return 1

    print(f"VALID: {args.summary} conforms to schema_version 1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
