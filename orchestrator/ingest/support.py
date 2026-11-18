"""Whether the pinned BLIS release can price a point at all, decided before calling blis
(Discussion #28, "Model, hardware and drafter support").

Catalog identities come from the blis the run scores with (`blis catalog resolve`, design §5),
so a release that adds a model or part changes the outcome with no code change here:

  model     the served checkpoint, or its HuggingFace base_model, is some catalog model's
            source repository (exact checkpoint first, then the base) -> else model_not_in_catalog.
            A repository several entries claim is matched to the one entry the run's deployment
            is (Catalog.model): a drafter is never the served model, and between several served
            entries the run's speculative method decides -> else catalog_entry_ambiguous;
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


class EntryAmbiguous(Exception):
    """A source repository several catalog entries claim, and the run's deployment matches not exactly one of them."""

    def __init__(self, repo: str, entries: list[str]):
        super().__init__(f"{repo} is the source repository of {len(entries)} catalog entries ({', '.join(entries)}), "
                         f"and the run's deployment matches not exactly one")
        self.repo, self.entries = repo, entries


# Staged checkpoint directories whose name is not their repository's, each bound to the repository by a record of the run's
# own harness (dashboard#111, the catalog lead's map): (repository, the evidence). A directory outside this table is not
# guessed at. The evidence is named on every point that uses it (score.staged_substitution).
STAGED_ALIASES = {
    "dsr1-0528-fp8": (
        "deepseek-ai/DeepSeek-R1-0528",
        "SemiAnalysisAI/InferenceX at 6a4fe2a127: runners/launch_b200-dgxc.sh:19-20 sets MODEL_PATH=/lustre/fsw/models/dsr1-0528-fp8 "
        "for MODEL_PREFIX dsr1 at PRECISION fp8, and .github/configs/nvidia-master.yaml:1959 (dsr1-fp8-b200-sglang) binds "
        "prefix dsr1, precision fp8 to model deepseek-ai/DeepSeek-R1-0528"),
}


@dataclass
class Catalog:
    """The catalog the scoring build reads, asked through `blis catalog resolve`. Each answer is
    cached, since the scorer asks the same names for many points."""
    blis: str
    root: Path
    _models: dict = field(default_factory=dict)       # source repository -> identity | None
    _chips: dict = field(default_factory=dict)        # chip name -> identity | None
    _packaging: dict = field(default_factory=dict)    # chip name -> {"gpus_per_node", "gpus_per_rack"}
    _claim_map: dict | None = None                     # see _claims

    def model(self, repo: str, spec_method: str | None = None) -> str | None:
        """The catalog model a run serving `repo` (an entry name or a source repository) is, or None.

        `blis catalog resolve` refuses a repository several entries claim, so such a repository is matched here to
        the one entry the run's deployment is, from the entries' own fields, and that entry is then resolved by its
        name: a drafter entry (one naming `targets`) is never the served model, and between several served entries
        the one whose graph speculates by the run's method (`spec_method`, as the deployment states it; None for a
        run that does not speculate) is. Raises EntryAmbiguous when not exactly one entry is left."""
        c = self._claims()
        claims = [] if repo in c["entries"] else c["repos"].get(repo.casefold(), [])
        if len(claims) > 1:
            served = [n for n, drafter in claims if not drafter]
            if len(served) > 1:
                served = [n for n in served if engine_method(self.speculator(n)) == spec_method]
            if len(served) != 1:
                raise EntryAmbiguous(repo, [n for n, _ in claims])
            repo = served[0]
        if repo not in self._models:
            self._models[repo] = self._ask_model(repo)
        return self._models[repo]

    def _ask_model(self, query: str) -> str | None:
        return bc.catalog_resolve(self.blis, str(self.root), model=query)

    def _claims(self) -> dict:
        """The catalog's entry names, and for each source repository (compared without regard to case) the entries
        that name it, each with whether it is a drafter. TEMPORARY until a command lists the catalog's models: read
        from <catalog>/models/*/model.yaml."""
        if self._claim_map is None:
            import yaml
            entries, repos = set(), {}
            for m in sorted((Path(self.root) / "models").glob("*/model.yaml")):
                doc = yaml.safe_load(m.read_text()) or {}
                entries.add(m.parent.name)
                repo = ((doc.get("source") if isinstance(doc, dict) else None) or {}).get("repo")
                if repo:
                    repos.setdefault(repo.casefold(), []).append((m.parent.name, _is_drafter(doc)))
            self._claim_map = {"entries": entries, "repos": repos}
        return self._claim_map

    def repo_of_local_path(self, path: str) -> str | None:
        """The source repository of the one catalog model whose repository name equals the last component of a local
        checkpoint path (compared without regard to case), else the repository STAGED_ALIASES binds that directory to when
        the catalog has it, else None (no model, or several, fits). A run that serves a staged copy
        (/lustre/fsw/models/GLM-5-FP8) names no Hugging Face id, but the staged directory usually keeps the repository's name;
        a path whose name fits no single catalog repository is not guessed at."""
        base = path.rstrip("/").rsplit("/", 1)[-1].casefold()
        hits = sorted(r for r in self._claims()["repos"] if r.rsplit("/", 1)[-1] == base)
        if len(hits) == 1:
            return hits[0]
        alias = STAGED_ALIASES.get(base)
        if alias and alias[0].casefold() in self._claims()["repos"]:
            return alias[0].casefold()
        return None

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

    def check_readable(self) -> None:
        """Ask `blis catalog resolve` for every model entry name, and for every source repository exactly one entry
        names, so a catalog the build cannot read stops the night before any point is scored. Raises the command's
        CommandError. A repository several entries claim is not asked: each run is matched to its own entry
        (model), and a run that matches none is G5 catalog_entry_ambiguous, not a stopped night."""
        c = self._claims()
        for name in sorted(c["entries"]):
            self.model(name)
        for repo, claims in sorted(c["repos"].items()):
            if len(claims) == 1 and not claims[0][1]:
                self.model(repo)

    def speculator(self, model: str) -> str | None:
        """The speculator method of a catalog model's graph, or None when it has none.
        TEMPORARY until a command prints it: read from the graph file."""
        import yaml
        g = Path(self.root) / "models" / model / "graph.yaml"
        graph = (yaml.safe_load(g.read_text()) or {}) if g.is_file() else {}
        spec = graph.get("speculator") if isinstance(graph, dict) else None
        return spec.get("method") if isinstance(spec, dict) else None

    def drafters_of(self, repo: str) -> list[str]:
        """The catalog entries that are drafters (they name `targets`) whose source repository is
        `repo`, sorted. A drafter may share its repository with its target (a DSpark head in the
        model's own repository, told apart by source.path), so the served-model lookup skips
        drafters and this one finds them. TEMPORARY until a command prints it."""
        import yaml
        out = []
        for m in sorted((Path(self.root) / "models").glob("*/model.yaml")):
            doc = yaml.safe_load(m.read_text()) or {}
            if _is_drafter(doc) and (((doc.get("source")) or {}).get("repo") or "").casefold() == repo.casefold():
                out.append(m.parent.name)
        return out

    def speculator_tokens(self, model: str) -> int | None:
        """The speculative tokens per step of a catalog model's graph (its speculator's
        num_spec_tokens): the checkpoint's default draft length, and for MTP the number of MTP
        modules. None when it has none. TEMPORARY, like speculator()."""
        import yaml
        g = Path(self.root) / "models" / model / "graph.yaml"
        graph = (yaml.safe_load(g.read_text()) or {}) if g.is_file() else {}
        spec = graph.get("speculator") if isinstance(graph, dict) else None
        n = spec.get("num_spec_tokens") if isinstance(spec, dict) else None
        return n if isinstance(n, int) and not isinstance(n, bool) else None

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


def _is_drafter(doc) -> bool:
    """Whether a model.yaml is a drafter entry: it names its target or targets (layer 8)."""
    if not isinstance(doc, dict):
        return False
    ident = doc.get("identity") if isinstance(doc.get("identity"), dict) else {}
    return any(k in doc or k in ident for k in ("targets", "target"))


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
                doc = yaml.safe_load(m.read_text()) or {}
                repo = ((doc.get("source")) or {}).get("repo")
                if repo and not _is_drafter(doc):
                    repos.setdefault(repo.casefold(), []).append(m.parent.name)
            chips = {}
            for h in sorted(root.glob("hardware/*.yaml")):
                doc = yaml.safe_load(h.read_text()) or {}
                chips[h.stem] = {"gpus_per_node": doc.get("GPUsPerNode") or None,
                                 "gpus_per_rack": doc.get("GPUsPerRack") or None}
            self._read = {"entries": {m.parent.name for m in root.glob("models/*/model.yaml")},
                          "repos": repos, "chips": chips}
        return self._read

    def _ask_model(self, query: str) -> str | None:
        c = self._checkout()
        names = [query] if query in c["entries"] else c["repos"].get(query.casefold(), [])
        if len(names) > 1:
            raise bc.CommandError(f"model {query!r} is the source repository of {len(names)} catalog entries "
                                  f"({', '.join(names)}); name the entry instead")
        return names[0] if names else None

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


def _leaf(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1]


def resolve_draft(drafter, served: list, entry: dict) -> tuple[str | None, str | None]:
    """(the draft checkpoint's HF repo, a G5 reason) for the draft model the run's log names.

    A repo the log names is used as it is. A local path is the recipe's: the pull records the
    DRAFT_MODEL the run's benchmark script set at the commit it ran (entry["draft_checkpoint"]),
    taken when the path's last component is that repo's name, a value_conflict when it is not, and
    value_not_recorded when no recipe names one. A path that is the served model's own (MTP names
    the target) is no draft. Nothing is matched by a file name alone."""
    repo = hf_repo(drafter)
    if repo or not isinstance(drafter, str) or not drafter.startswith("/") or drafter in served:
        return repo, None
    dc = entry.get("draft_checkpoint") or {}
    if not dc.get("repo"):
        return None, "value_not_recorded:speculative_config.model"
    if _leaf(drafter) != _leaf(dc["repo"]):
        return None, f"value_conflict:speculative_config.model: the log names {drafter}, the recipe {dc['repo']}"
    return dc["repo"], None


def served_conflict(entry: dict) -> str | None:
    """The G5 reason when the run's served path and its recipe's checkpoint disagree (the pull
    records the recipe's one checkpoint as checkpoint_conflict), naming both."""
    c = entry.get("checkpoint_conflict")
    if not c:
        return None
    return f"value_conflict:model: the log serves {c['served_path']}, the recipe {c['repo']}"


def engine_method(graph_method: str | None) -> str | None:
    """The method a deployment states for a catalog speculator method. vLLM rewrites every
    model-specific MTP name to `mtp` (vllm/config/speculative.py:1141-1145), and the catalog's
    derive_graph.vllm_speculative_method states the same rule; eagle3, dflash and dspark keep their
    names. TEMPORARY: a copy of that rule until a substrate command prints the method as a
    deployment states it (X7)."""
    return "mtp" if graph_method and graph_method.endswith("_mtp") else graph_method


def draft_length_conflict(method: str, k, n_predict: int | None) -> str | None:
    """Why a stated num_speculative_tokens K cannot be a real run's, or None when vLLM accepts it
    and it is simply priced as stated. The rule is the layer 8 model reference's "Stated draft
    lengths" table (vLLM v0.32.0 vllm/config/speculative.py); TEMPORARY copy (X7).

      every method  K >= 1 (:393, :1826-1830)
      mtp           K <= n_predict is valid; K > n_predict must be a multiple of n_predict (:1493-1501),
                    n_predict being the graph's num_spec_tokens (the number of MTP modules)
      eagle, eagle3, draft_model, dflash, dspark   any K >= 1

    The graph's num_spec_tokens is the checkpoint's default draft length, not a value to equal."""
    if isinstance(k, bool) or not isinstance(k, int):
        return None         # a value that is not a count is the field list's to judge
    if k < 1:
        return f"{k} is below 1"
    if engine_method(method) == "mtp" and n_predict and k > n_predict and k % n_predict:
        return f"{k} exceeds the model's {n_predict} MTP modules and is not a multiple of {n_predict}"
    return None


def check(cat: Catalog, parts: set[str], *, checkpoints: list[str], base_models: dict,
          hardware: str, spec_method: str | None,
          draft_checkpoint: str | None = None, num_spec_tokens: int | None = None) -> Support:
    """checkpoints: candidate HF repos for the served model, most authoritative first.
    draft_checkpoint: the HF repo the run named as its draft model (speculative_config.model), if any.
    When it names one, that checkpoint must be a catalog entry that lists the served model among
    its targets and is listed by it, and its graph's speculator method must be the run's; otherwise
    the served model's own graph decides.
    base_models: repo -> its HF base_model (frozen at pull time). A repository two catalog
    entries claim is refused by `blis catalog resolve`, and raises its CommandError."""
    s = Support()
    lookup_failed = False
    ambiguous = None
    for ck in checkpoints:
        bm = base_models.get(ck)
        if isinstance(bm, dict):     # the pull couldn't read its HF card
            lookup_failed = True
            bm = None
        for how, repo in (("checkpoint", ck), ("base_model", bm)):
            try:
                hit = cat.model(repo, spec_method) if repo else None
            except EntryAmbiguous as e:
                ambiguous = e
                break
            if hit is not None:
                s.model, s.matched_by, s.checkpoint = hit, how, ck
                break
        if s.model or ambiguous:
            break
    if ambiguous:
        # The catalog has the repository, more than once, and nothing the run recorded picks one entry.
        s.reasons.append(f"catalog_entry_ambiguous:{ambiguous.repo}: {', '.join(ambiguous.entries)}")
    elif not s.model and lookup_failed:
        # Only a reason when it could have mattered: a checkpoint that matched needs no base.
        s.reasons.append("model_not_in_catalog:base_model_lookup_failed")
    if not s.model and not ambiguous:
        # The subject names what the catalog lacks: the repositories the run could have served.
        s.reasons.append("model_not_in_catalog:" + (",".join(checkpoints) if checkpoints else "no_checkpoint_recorded"))
    s.chip = cat.chip(hardware)
    if s.chip is None or hardware not in parts:
        s.reasons.append(f"hardware_no_coefficients:{hardware}")
    if s.model and spec_method:
        named = cat.drafters_of(draft_checkpoint) if draft_checkpoint else []
        d = None
        if draft_checkpoint and not named:
            try:
                d = cat.model(draft_checkpoint)
            except EntryAmbiguous as e:
                s.reasons.append(f"catalog_entry_ambiguous:{e.repo}: {', '.join(e.entries)}")
                return s
        if named:
            # The checkpoint is a drafter entry's repository (maybe the served model's own, told
            # apart by the entry): one the served model and it name each other, speculating by the run's method.
            linked = [n for n in named if cat.drafter_links(s.model, n) and engine_method(cat.speculator(n)) == spec_method]
            if linked:
                s.drafter = linked[0]
                why = draft_length_conflict(spec_method, num_spec_tokens, None) if num_spec_tokens is not None else None
                if why:
                    s.reasons.append(f"value_conflict:speculative_config.num_speculative_tokens: vLLM refuses {why}")
            else:
                s.reasons.append(f"drafter_not_in_catalog:{spec_method}")
        elif d is not None and d != s.model:
            # A separate drafter checkpoint (eagle3, dspark): a catalog entry the served model and
            # it name each other, whose graph speculates by the run's method.
            if cat.drafter_links(s.model, d) and engine_method(cat.speculator(d)) == spec_method:
                s.drafter = d
                why = draft_length_conflict(spec_method, num_spec_tokens, None) if num_spec_tokens is not None else None
                if why:
                    s.reasons.append(f"value_conflict:speculative_config.num_speculative_tokens: vLLM refuses {why}")
            else:
                s.reasons.append(f"drafter_not_in_catalog:{spec_method}")
        elif draft_checkpoint and d is None:
            s.reasons.append(f"drafter_not_in_catalog:{spec_method}")
        elif engine_method(cat.speculator(s.model)) != spec_method:
            # No separate checkpoint, or vLLM named the served model itself as its drafter (MTP):
            # the served model's own graph decides.
            s.reasons.append(f"drafter_not_in_catalog:{spec_method}")
        elif num_spec_tokens is not None:
            why = draft_length_conflict(spec_method, num_spec_tokens, cat.speculator_tokens(s.model))
            if why:
                s.reasons.append(f"value_conflict:speculative_config.num_speculative_tokens: vLLM refuses {why}")
    return s
