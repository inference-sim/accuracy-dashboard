#!/usr/bin/env python3
"""Print what the nightly fetches to score one simulator release, from its stack.json, as
key=value lines for `eval` (design §11: a new release is scored with no change to the
dashboard's code):

    substrate_ref         what to check out of blis-substrate: its release tag, or when stack.json pins it by a
                          commit (a pseudo-version) that commit; its catalog/ and registry/ are the data
    substrate_commit      the commit stack.json names for it: empty when a release tag names it
    substrate_version     its version: a release tag, or a pseudo-version when the module is pinned by commit
    vllm_module_ref       what to fetch of blis-vllm, likewise; fields.json is at its root
    vllm_module_commit    the commit stack.json names for it: empty for a release
    vllm_ref              the vLLM tag of the engine release (v + engines[kind=vllm].version), or the engine's
                          commit when its version is a build after a release (<release>+<12 hex>)
    substrate_embedded    "true" only for an inference-sim checkout (a directory) whose stack.json lists no
                          blis-substrate module: the substrate then lives in the checkout itself, and substrate_ref,
                          substrate_commit and substrate_version are the checkout's own HEAD commit, and the catalog,
                          registry, ledger and engines/vllm/fields.json are read from the checkout

    python3 orchestrator/resolve_stack.py <inference-sim checkout or stack.json>

Exit status 1, with the reason on standard error, when stack.json is missing or unreadable.
"""
from __future__ import annotations

import subprocess
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
    sim_dir = path if path.is_dir() else None
    if sim_dir:
        path = path / "stack.json"
    try:
        loaded = stack.load(path)
        if sim_dir and stack.SUBSTRATE not in loaded.modules:
            head = subprocess.run(["git", "-C", str(sim_dir), "rev-parse", "HEAD"], capture_output=True, text=True)
            pins = stack.embedded_pins(loaded, head.stdout.strip())
        else:
            pins = stack.pins(loaded)
    except (OSError, ValueError) as e:
        print(f"FATAL: {path}: {e}", file=sys.stderr)
        return 1
    for k, v in pins.items():
        print(f"{k}={v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
