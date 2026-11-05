"""The inference-sim commands the dashboard reads BLIS data through (design §5, the
accuracy-dashboard card; X7). The dashboard imports no BLIS module: what it needs from the
engines and the substrate it asks of the `blis` binary it scores with, so every answer is the
one that build gives.

Each command prints JSON on standard output with --json. An error goes to standard error with a
non-zero exit, and is raised here as a CommandError naming the command and quoting the error.
"""
from __future__ import annotations

import json
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


def ledger_list(blis: str, role: str) -> bytes:
    """`blis ledger --list <role> --json`: the published unit list of that role (fit, anchor or
    report) embedded in the substrate release this build pins, byte for byte. The dashboard reads
    it as blis-substrate's ledger.Published: {"kind": "PublishedUnits", "role", "partition_version",
    "seed_sha256", "units": [unit_id, ...]} (ledger.read_unit_set)."""
    if role not in ("fit", "anchor", "report"):
        raise CommandError(f"ledger --list {role!r}: the published lists are fit, anchor and report")
    return _run(blis, ["ledger", "--list", role, "--json"]).encode("utf-8")


def catalog_resolve(blis: str, catalog: str, *, model: str | None = None, chip: str | None = None) -> str | None:
    """`blis catalog resolve --catalog <catalog> --model|--chip <name> --json`: the catalog
    identity of a model (an entry name, or a source repository its model.yaml names) or of a chip,
    or None when the catalog has none. The command prints {"query", "identity", "reason"}, with
    identity null when no entry exists, and exits non-zero when a name is ambiguous."""
    if (model is None) == (chip is None):
        raise CommandError("catalog resolve takes exactly one of model and chip")
    flag, query = ("--model", model) if model is not None else ("--chip", chip)
    args = ["catalog", "resolve", "--catalog", catalog, flag, query, "--json"]
    text = _run(blis, args)
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        raise CommandError(f"blis {' '.join(args)} printed no JSON: {e}") from None
    if not isinstance(doc, dict) or set(doc) != {"query", "identity", "reason"}:
        raise CommandError(f"blis {' '.join(args)} printed {text.strip()[:200]!r}, "
                           f"not an object of query, identity and reason")
    if doc["query"] != query or not (doc["identity"] is None or isinstance(doc["identity"], str)):
        raise CommandError(f"blis {' '.join(args)} printed query {doc['query']!r} and identity "
                           f"{doc['identity']!r}; want query {query!r} and a name or null")
    return doc["identity"]
