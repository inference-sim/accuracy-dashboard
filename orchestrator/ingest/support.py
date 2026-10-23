"""Whether the pinned BLIS release can price a point at all, decided before calling blis
(Discussion #28, "Model, hardware and drafter support").

Everything is read from the catalog and registry the BLIS release pins, so a release that
adds a model, part or drafter changes the outcome with no code change here:

  model     the served checkpoint, or its HuggingFace base_model, is some catalog model's
            source.repo (exact checkpoint first, then the base) -> else model_not_in_catalog;
  hardware  the catalog has the part and the registry scopes coefficients to it
            -> else hardware_no_coefficients;
  drafter   the run's speculative method is the catalog graph's speculator
            -> else drafter_not_in_catalog:<method>.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_HF_REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*/[A-Za-z0-9][A-Za-z0-9_.\-]*$")


def hf_repo(name) -> str | None:
    """A HuggingFace repo id from a checkpoint reference (`hf:org/name`, `org/name`)."""
    if not isinstance(name, str):
        return None
    name = name.strip()
    if name.startswith("hf:"):
        name = name[3:]
    return name if _HF_REPO.match(name) else None


@dataclass
class Catalog:
    root: Path
    models: dict = field(default_factory=dict)        # catalog name -> source.repo
    speculators: dict = field(default_factory=dict)   # catalog name -> speculator method | None
    index_caches: dict = field(default_factory=dict)  # catalog name -> the indexer cache record, e.g. "fp8 (132 B per 2 tokens)"
    hardware: dict = field(default_factory=dict)      # part -> MemoryGiB

    @staticmethod
    def load(root) -> "Catalog":
        import yaml
        root = Path(root)
        c = Catalog(root=root)
        for d in sorted((root / "models").iterdir()):
            m = d / "model.yaml"
            if not m.is_file():
                continue
            doc = yaml.safe_load(m.read_text()) or {}
            repo = ((doc.get("source") or {}).get("repo"))
            if repo:
                c.models[d.name] = repo
            g = d / "graph.yaml"
            if g.is_file():
                graph = yaml.safe_load(g.read_text()) or {}
                spec = graph.get("speculator") if isinstance(graph, dict) else None
                c.speculators[d.name] = spec.get("method") if isinstance(spec, dict) else None
                rec = _index_cache(graph)
                if rec:
                    c.index_caches[d.name] = rec
        for h in sorted((root / "hardware").glob("*.yaml")):
            doc = yaml.safe_load(h.read_text()) or {}
            if "MemoryGiB" in doc:
                c.hardware[h.stem] = float(doc["MemoryGiB"])
        return c


# The indexer K record's width per entry, by format: d_h values plus per-group scales. For the
# DeepSeek sparse indexer (d_h 128): FP8 is 128 B + one 4-byte scale = 132 B; MXFP4 is 64 B + four
# 1-byte scales = 68 B (blis-schemas docs/reference/model.md: "the 68-byte MXFP4 indexer record";
# vLLM v1/attention/backends/mla/indexer.py). A record of another width is reported in bytes.
INDEX_RECORD_FORMAT = {132: "fp8", 68: "mxfp4", 256: "bf16"}


def _index_cache(graph) -> str | None:
    """The indexer cache format the graph prices (its `kind: index` caches), named from the
    record's width -- what BLIS uses for a run whose indexer format it can't state. None for a
    graph with no indexer, or whose indexer records differ in width."""
    widths = set()

    def walk(n):
        if isinstance(n, dict):
            for c in n.get("caches") or []:
                if isinstance(c, dict) and c.get("kind") == "index" and c.get("bytes_per_entry"):
                    widths.add(int(c["bytes_per_entry"]))
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(graph)
    if len(widths) != 1:
        return None
    w = widths.pop()
    return INDEX_RECORD_FORMAT.get(w, f"{w}-byte record")


def registry_parts(registry_root) -> set[str]:
    """Every part some coefficient in the registry is scoped to."""
    import yaml
    parts = set()

    def scopes(node):
        if isinstance(node, dict):
            sc = node.get("scope")
            if isinstance(sc, dict) and isinstance(sc.get("hardware"), list):
                parts.update(str(h) for h in sc["hardware"])
            for v in node.values():
                scopes(v)
        elif isinstance(node, list):
            for v in node:
                scopes(v)

    for f in sorted(Path(registry_root, "coefficients").glob("*.yaml")):
        scopes(yaml.safe_load(f.read_text()))
    return parts


@dataclass
class Support:
    model: str | None = None
    matched_by: str | None = None       # checkpoint | base_model
    checkpoint: str | None = None
    reasons: list = field(default_factory=list)


def check(cat: Catalog, parts: set[str], *, checkpoints: list[str], base_models: dict,
          hardware: str, spec_method: str | None) -> Support:
    """checkpoints: candidate HF repos for the served model, most authoritative first.
    base_models: repo -> its HF base_model (frozen at pull time)."""
    s = Support()
    by_repo = {}
    for name, repo in cat.models.items():
        by_repo.setdefault(repo.lower(), []).append(name)
    for ck in checkpoints:
        bm = base_models.get(ck)
        if isinstance(bm, dict):     # the pull couldn't read its HF card
            s.reasons.append("model_not_in_catalog:base_model_lookup_failed")
            bm = None
        for how, repo in (("checkpoint", ck), ("base_model", bm)):
            hits = sorted(by_repo.get((repo or "").lower(), []))
            if len(hits) == 1:
                s.model, s.matched_by, s.checkpoint = hits[0], how, ck
                break
            if len(hits) > 1:
                s.reasons.append("model_not_in_catalog:ambiguous")
                return s
        if s.model:
            break
    if not s.model:
        s.reasons.append("model_not_in_catalog")
    if hardware not in cat.hardware or hardware not in parts:
        s.reasons.append("hardware_no_coefficients")
    if s.model and spec_method:
        have = cat.speculators.get(s.model)
        if have != spec_method:
            s.reasons.append(f"drafter_not_in_catalog:{spec_method}")
    return s
