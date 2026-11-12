"""The facts a stand-in's validity is judged on (design 11.2, COV-3).

A `leave_unset` estimation rule of the engine's field list is exact only for some of the values a run can state; the engine repo
writes which (blis-vllm fields.json, `estimation.valid_when`) and the substrate's evaluator decides. The dashboard supplies the
facts, and no rule of its own:

  value              the value the run recorded, trimmed and lowercased
  tp_group_nodes     the nodes the pool's tensor-parallel group spans: ceil(tp / gpus per node)
  compute_capability the part's CUDA compute capability, from the catalog's hardware entry (`ComputeCapability`)

A fact the dashboard cannot supply is left out (never guessed): the evaluator makes a clause that needs it false.
"""
from __future__ import annotations

from pathlib import Path


def tp_group_nodes(tp, gpus_per_node) -> int | None:
    """Nodes a tensor-parallel group of `tp` GPUs spans on nodes of `gpus_per_node`; None where either is not a positive integer."""
    ok = lambda v: isinstance(v, int) and not isinstance(v, bool) and v >= 1
    return -(-tp // gpus_per_node) if ok(tp) and ok(gpus_per_node) else None


def compute_capability(catalog_root, chip: str) -> str | None:
    """The `ComputeCapability` of the chip's catalog hardware entry, or None where the entry states none or there is no entry."""
    import yaml
    f = Path(catalog_root) / "hardware" / f"{chip}.yaml"
    if not f.is_file():
        return None
    v = (yaml.safe_load(f.read_text()) or {}).get("ComputeCapability")
    return str(v) if isinstance(v, (str, int, float)) and not isinstance(v, bool) and str(v).strip() else None


def facts(value, *, tp=None, gpus_per_node=None, capability: str | None = None) -> dict:
    """The facts for one recorded value; a fact that cannot be supplied is absent."""
    out = {}
    if value is not None:
        out["value"] = str(value).strip().lower()
    nodes = tp_group_nodes(tp, gpus_per_node)
    if nodes is not None:
        out["tp_group_nodes"] = nodes
    if capability:
        out["compute_capability"] = str(capability).strip()
    return out
