"""Whether the pinned BLIS release can price a point at all, decided before calling blis
(Discussion #28, "Model, hardware and drafter support").

Catalog identities come from the blis the run scores with (`blis catalog resolve`, design §5),
so a release that adds a model or part changes the outcome with no code change here:

  model     the served checkpoint, or its HuggingFace base_model, is some catalog model's
            source repository (exact checkpoint first, then the base) -> else model_not_in_catalog;
  hardware  the catalog has the part and the registry scopes coefficients to it
            -> else hardware_no_coefficients;
  drafter   the run's speculative method is the catalog graph's speculator
            -> else drafter_not_in_catalog:<method>.

TEMPORARY until inference-sim prints them through a command: the graph's speculator method is
read from <catalog>/models/<model>/graph.yaml (Catalog.speculator), and the parts the registry
scopes coefficients to from <registry>/coefficients/*.yaml (registry_parts). No command in the
brief's table prints either.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import blis_commands as bc

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
    """The catalog the scoring build reads, asked through `blis catalog resolve`. Each answer is
    cached, since the scorer asks the same names for many points."""
    blis: str
    root: Path
    _models: dict = field(default_factory=dict)       # source repository -> identity | None
    _chips: dict = field(default_factory=dict)        # chip name -> identity | None
    _packaging: dict = field(default_factory=dict)    # chip name -> {"gpus_per_node", "gpus_per_rack"}

    def model(self, repo: str) -> str | None:
        """The catalog model whose source repository is `repo`, or None."""
        if repo not in self._models:
            self._models[repo] = bc.catalog_resolve(self.blis, str(self.root), model=repo)
        return self._models[repo]

    def chip(self, name: str) -> str | None:
        """The catalog chip of that name, or None."""
        if name not in self._chips:
            self._chips[name] = bc.catalog_resolve(self.blis, str(self.root), chip=name)
        return self._chips[name]

    def packaging(self, chip: str) -> dict:
        """What the chip's catalog entry fixes about its packaging: {"gpus_per_node",
        "gpus_per_rack"}, each the entry's value or None where the entry leaves it to the scenario
        (blis-substrate scenario.Cluster.Packaging, design SUB-3). The scenario omits a value the
        entry fixes, and states the node size of a chip whose entry fixes none.

        Read from `blis catalog resolve --chip`'s packaging field. TEMPORARY until the pinned blis
        reports that field (inference-sim m1/packaging, 146e13d9): a build that does not is
        answered from <catalog>/hardware/<chip>.yaml, its GPUsPerNode and GPUsPerRack."""
        if chip not in self._packaging:
            pk = bc.chip_packaging(self.blis, str(self.root), chip)
            if pk is None:
                import yaml
                f = Path(self.root) / "hardware" / f"{chip}.yaml"
                if not f.is_file():
                    raise bc.CommandError(f"blis catalog resolve --chip {chip} reports no packaging, and "
                                          f"{f} does not exist to read it from")
                doc = yaml.safe_load(f.read_text()) or {}
                pk = {"gpus_per_node": doc.get("GPUsPerNode") or None, "gpus_per_rack": doc.get("GPUsPerRack") or None}
            self._packaging[chip] = pk
        return self._packaging[chip]

    def check_unambiguous(self) -> None:
        """Ask `blis catalog resolve` for every model entry name and every source repository the
        catalog's entries name, so a repository two entries claim is refused by the command before
        any point is scored. Raises the command's CommandError, which quotes its message naming
        both entries. TEMPORARY until a command lists the catalog's models: the entry names and
        their source repositories are read from <catalog>/models/*/model.yaml."""
        import yaml
        for d in sorted((Path(self.root) / "models").iterdir()):
            m = d / "model.yaml"
            if not m.is_file():
                continue
            self.model(d.name)
            repo = (((yaml.safe_load(m.read_text()) or {}).get("source")) or {}).get("repo")
            if repo:
                self.model(repo)

    def speculator(self, model: str) -> str | None:
        """The speculator method of a catalog model's graph, or None when it has none.
        TEMPORARY until a command prints it: read from the graph file."""
        import yaml
        g = Path(self.root) / "models" / model / "graph.yaml"
        graph = (yaml.safe_load(g.read_text()) or {}) if g.is_file() else {}
        spec = graph.get("speculator") if isinstance(graph, dict) else None
        return spec.get("method") if isinstance(spec, dict) else None

    def drafter_links(self, target: str, drafter: str) -> bool:
        """Whether catalog entry `drafter` and catalog entry `target` name each other: the drafter
        lists the target among its `targets`, and the target lists the drafter among its
        `drafters` (blis-substrate layer 8: a drafter names a list of targets, and the check is two-way).
        TEMPORARY until a command prints it, and written against the schema as the layer 8 author
        described it (a `targets` list on the drafter's model.yaml, a `drafters` list on the
        target's; either may sit under `identity`). Re-check against the layer 8 tip."""
        return (target in self._listed(drafter, "targets")) and (drafter in self._listed(target, "drafters"))

    def _listed(self, entry: str, key: str) -> list:
        import yaml
        f = Path(self.root) / "models" / entry / "model.yaml"
        doc = (yaml.safe_load(f.read_text()) or {}) if f.is_file() else {}
        if not isinstance(doc, dict):
            return []
        v = doc.get(key)
        if v is None and isinstance(doc.get("identity"), dict):
            v = doc["identity"].get(key)
        return [x for x in (v if isinstance(v, list) else []) if isinstance(x, str)]


@dataclass
class CheckoutCatalog(Catalog):
    """The catalog read from a checkout, with no blis binary: the answers `blis catalog resolve`
    gives (a model by entry name or by source repository, compared without regard to case; a chip
    by hardware file, with the packaging its file fixes), taken from <catalog>/models/*/model.yaml
    and <catalog>/hardware/*.yaml.

    TEMPORARY, for `cli.py coverage` only, which runs no simulator and so has no blis build to ask,
    until a command answers a catalog queried offline. The checkout is not validated here: its
    schema check is blis's. A source repository two entries claim raises CommandError, as the
    command does."""
    _read: dict | None = None

    def _checkout(self) -> dict:
        if self._read is None:
            import yaml
            root = Path(self.root)
            repos: dict = {}
            for m in sorted(root.glob("models/*/model.yaml")):
                repo = (((yaml.safe_load(m.read_text()) or {}).get("source")) or {}).get("repo")
                if repo:
                    repos.setdefault(repo.casefold(), []).append(m.parent.name)
            chips = {}
            for h in sorted(root.glob("hardware/*.yaml")):
                doc = yaml.safe_load(h.read_text()) or {}
                chips[h.stem] = {"gpus_per_node": doc.get("GPUsPerNode") or None,
                                 "gpus_per_rack": doc.get("GPUsPerRack") or None}
            self._read = {"entries": {m.parent.name for m in root.glob("models/*/model.yaml")},
                          "repos": repos, "chips": chips}
        return self._read

    def model(self, repo: str) -> str | None:
        if repo not in self._models:
            c = self._checkout()
            names = [repo] if repo in c["entries"] else c["repos"].get(repo.casefold(), [])
            if len(names) > 1:
                raise bc.CommandError(f"model {repo!r} is the source repository of {len(names)} catalog entries "
                                      f"({', '.join(names)}); name the entry instead")
            self._models[repo] = names[0] if names else None
        return self._models[repo]

    def chip(self, name: str) -> str | None:
        return name if name in self._checkout()["chips"] else None

    def packaging(self, chip: str) -> dict:
        return self._checkout()["chips"][chip]


def catalog_part(cat: Catalog, parts: set[str], label: str) -> str | None:
    """The catalog part an InferenceX hardware label names: the part of that name, else the
    one part named `<label>-<variant>` with registry coefficients (InferenceX's `gb200` is the
    catalog's `gb200-nvl72`). None when there is none, or more than one, so a label is never
    matched to a part by guess."""
    if cat.chip(label) is not None:
        return label
    hits = [p for p in sorted(parts) if p.startswith(label + "-") and cat.chip(p) is not None]
    return hits[0] if len(hits) == 1 else None


def registry_parts(registry_root) -> set[str]:
    """Every part some coefficient in the registry is scoped to. TEMPORARY until a command prints
    the registry's coefficient scopes."""
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
    chip: str | None = None             # the catalog chip, or None when the catalog has none
    drafter: str | None = None          # the catalog entry of the run's draft checkpoint, when it named one
    reasons: list = field(default_factory=list)


def check(cat: Catalog, parts: set[str], *, checkpoints: list[str], base_models: dict,
          hardware: str, spec_method: str | None,
          draft_checkpoint: str | None = None) -> Support:
    """checkpoints: candidate HF repos for the served model, most authoritative first.
    draft_checkpoint: the HF repo the run named as its draft model (speculative_config.model), if any.
    When it names one, that checkpoint must be a catalog entry that lists the served model among
    its targets and is listed by it, and its graph's speculator method must be the run's; otherwise
    the served model's own graph decides.
    base_models: repo -> its HF base_model (frozen at pull time). A repository two catalog
    entries claim is refused by `blis catalog resolve`, and raises its CommandError."""
    s = Support()
    lookup_failed = False
    for ck in checkpoints:
        bm = base_models.get(ck)
        if isinstance(bm, dict):     # the pull couldn't read its HF card
            lookup_failed = True
            bm = None
        for how, repo in (("checkpoint", ck), ("base_model", bm)):
            hit = cat.model(repo) if repo else None
            if hit is not None:
                s.model, s.matched_by, s.checkpoint = hit, how, ck
                break
        if s.model:
            break
    if not s.model and lookup_failed:
        # Only a reason when it could have mattered: a checkpoint that matched needs no base.
        s.reasons.append("model_not_in_catalog:base_model_lookup_failed")
    if not s.model:
        s.reasons.append("model_not_in_catalog")
    s.chip = cat.chip(hardware)
    if s.chip is None or hardware not in parts:
        s.reasons.append("hardware_no_coefficients")
    if s.model and spec_method:
        if draft_checkpoint:
            d = cat.model(draft_checkpoint)
            if d is not None and cat.drafter_links(s.model, d) and cat.speculator(d) == spec_method:
                s.drafter = d
            else:
                s.reasons.append(f"drafter_not_in_catalog:{spec_method}")
        elif cat.speculator(s.model) != spec_method:
            s.reasons.append(f"drafter_not_in_catalog:{spec_method}")
    return s
