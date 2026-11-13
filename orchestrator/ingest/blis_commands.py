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


def _catalog_resolve(blis: str, catalog: str, model: str | None, chip: str | None) -> dict:
    """`blis catalog resolve --catalog <catalog> --model|--chip <name> --json`, checked. The
    command prints {"query", "identity", "reason"}, with identity null when no entry exists, and
    exits non-zero when a name is ambiguous. A resolved chip also prints "packaging" (inference-sim
    m1/packaging): {"gpus_per_node", "gpus_per_rack"}, each the value its entry fixes or null."""
    if (model is None) == (chip is None):
        raise CommandError("catalog resolve takes exactly one of model and chip")
    flag, query = ("--model", model) if model is not None else ("--chip", chip)
    args = ["catalog", "resolve", "--catalog", catalog, flag, query, "--json"]
    text = _run(blis, args)
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        raise CommandError(f"blis {' '.join(args)} printed no JSON: {e}") from None
    base = {"query", "identity", "reason"}
    if not isinstance(doc, dict) or not base <= set(doc) or set(doc) - base - {"packaging"}:
        raise CommandError(f"blis {' '.join(args)} printed {text.strip()[:200]!r}, "
                           f"not an object of query, identity and reason")
    if doc["query"] != query or not (doc["identity"] is None or isinstance(doc["identity"], str)):
        raise CommandError(f"blis {' '.join(args)} printed query {doc['query']!r} and identity "
                           f"{doc['identity']!r}; want query {query!r} and a name or null")
    pk = doc.get("packaging")
    if pk is not None:
        ok = isinstance(pk, dict) and set(pk) == {"gpus_per_node", "gpus_per_rack"} and all(
            v is None or (isinstance(v, int) and not isinstance(v, bool) and v > 0) for v in pk.values())
        if not ok:
            raise CommandError(f"blis {' '.join(args)} printed packaging {pk!r}; want gpus_per_node and "
                               f"gpus_per_rack, each a positive integer or null")
    return doc


def catalog_resolve(blis: str, catalog: str, *, model: str | None = None, chip: str | None = None) -> str | None:
    """The catalog identity of a model (an entry name, or a source repository its model.yaml
    names) or of a chip, or None when the catalog has none."""
    return _catalog_resolve(blis, catalog, model, chip)["identity"]


def chip_packaging(blis: str, catalog: str, chip: str) -> dict | None:
    """The packaging `blis catalog resolve --chip` reports for a chip: {"gpus_per_node",
    "gpus_per_rack"}, each the value the chip's catalog entry fixes or None. None when the command
    reports no packaging (a build before inference-sim m1/packaging, or a chip with no entry)."""
    return _catalog_resolve(blis, catalog, None, chip).get("packaging")


def metrics(blis: str) -> dict[str, dict]:
    """`blis metrics --json`: the metric registry of the build, by metric id (DEV-8). The M1 simulator
    has no such command; the error then says it is an unknown command."""
    text = _run(blis, ["metrics", "--json"])
    try:
        recs = json.loads(text)["metrics"]
        return {r["id"]: r for r in recs}
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise CommandError(f"blis metrics --json printed no metric registry: {e}") from None
