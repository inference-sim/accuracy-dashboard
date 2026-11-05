"""The inference-sim commands the dashboard reads BLIS data through (design §5, the
accuracy-dashboard card; X7). The dashboard imports no BLIS module: what it needs from the
engines and the substrate it asks of the `blis` binary it scores with, so every answer is the
one that build gives.

Each command prints JSON on standard output with --json. An error goes to standard error with a
non-zero exit, and is raised here as a CommandError naming the command and quoting the error.
"""
from __future__ import annotations

import subprocess


class CommandError(RuntimeError):
    """A blis command failed, or printed something other than what the dashboard reads."""


def _run(blis: str, args: list[str], timeout: int = 600) -> str:
    out = subprocess.run([blis, *args], capture_output=True, text=True, timeout=timeout)
    if out.returncode != 0:
        raise CommandError(f"blis {' '.join(args)} exited {out.returncode}: {out.stderr.strip()[-2000:]}")
    return out.stdout


def fields(blis: str, engine: str) -> bytes:
    """`blis fields --engine <engine> --json`: the engine's fields.json at the release this build
    runs (COV-3), byte for byte."""
    return _run(blis, ["fields", "--engine", engine, "--json"]).encode("utf-8")
