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
                spec = None
                for line in g.read_text().splitlines():
                    if line.startswith("speculator:"):
                        spec = ""
                    elif spec == "" and line.strip().startswith("method:"):
                        spec = line.split(":", 1)[1].strip()
                        break
                c.speculators[d.name] = spec or None
        for h in sorted((root / "hardware").glob("*.yaml")):
            doc = yaml.safe_load(h.read_text()) or {}
            if "MemoryGiB" in doc:
                c.hardware[h.stem] = float(doc["MemoryGiB"])
        return c


def registry_parts(registry_root) -> set[str]:
    """Every part some coefficient in the registry is scoped to."""
    parts = set()
    for f in sorted(Path(registry_root, "coefficients").glob("*.yaml")):
        for m in re.finditer(r"scope:\s*\{[^}]*hardware:\s*\[([^\]]*)\]", f.read_text()):
            parts |= {p.strip() for p in m.group(1).split(",") if p.strip()}
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
        for how, repo in (("checkpoint", ck), ("base_model", base_models.get(ck))):
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
