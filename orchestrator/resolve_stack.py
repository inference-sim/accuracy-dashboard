#!/usr/bin/env python3
"""Print what the nightly fetches to score one simulator release, from its stack.json, as
key=value lines for `eval` (design §11: a new release is scored with no change to the
dashboard's code):

    substrate_commit      the blis-substrate commit; its catalog/ and registry/ are the data
    substrate_version     its version: a release tag, or a pseudo-version in a draft build
    vllm_module_commit    the blis-vllm commit; fields.json is at its root
    vllm_ref              the vLLM tag of the engine release (v + engines[kind=vllm].version)

    python3 orchestrator/resolve_stack.py <inference-sim checkout or stack.json>

Exit status 1, with the reason on standard error, when stack.json is missing or unreadable.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "ingest"))
import stack  # noqa: E402


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    path = Path(args[0])
    if path.is_dir():
        path = path / "stack.json"
    try:
        pins = stack.pins(stack.load(path))
    except (OSError, ValueError) as e:
        print(f"FATAL: {path}: {e}", file=sys.stderr)
        return 1
    for k, v in pins.items():
        print(f"{k}={v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
