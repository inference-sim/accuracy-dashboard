"""Which HuggingFace checkpoint a run served, when its server log names only a local path.

InferenceX launches vLLM on a staged copy of the checkpoint (e.g. /lustre/fsw/models/
MiniMax-M3-MXFP8), so the log and the API row name no HF repo. The run's own recipe does: the
`configs/*master.yaml` files at the commit the run executed (its head_sha) bind every recipe
to an HF `model`, with the image, framework, precision and runner it ran on.

A row's checkpoint is taken from its recipe only when two independent sources agree:
  1. the recipes at the run's commit whose image, framework, precision and runner hardware
     are the row's (the model-prefix isn't used: the API's slug and a recipe's prefix have
     differed, e.g. gptoss120b vs gptoss);
  2. the served path's last component is that recipe model's name, or the directory the run's
     `configs/runners.yaml` (same commit) stages that model in.
Exactly one HF repo must survive; anything else is unresolved, never a guess. Read once per
commit and frozen at pull time, so scoring needs no network.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field

import yaml

_MASTER = re.compile(r"(^|/)configs/(.+/)?[^/]*master\.yaml$")
_RUNNERS = re.compile(r"(^|/)configs/runners\.yaml$")


def _image(ref) -> str:
    """An image reference without its digest, and with NVCR's `#` spelled as `/`."""
    return str(ref or "").split("@", 1)[0].replace("#", "/")


def runner_hardware(runner) -> str:
    """A recipe runner label's part: b200, b200-dsv4, cluster:b200-dgxc and b200-multinode are b200."""
    return str(runner or "").removeprefix("cluster:").split("-", 1)[0]


@dataclass
class Recipes:
    """The recipes and model staging directories of one InferenceX commit."""
    recipes: list = field(default_factory=list)     # recipe dicts (each has "model", "image", ...)
    dirs: dict = field(default_factory=dict)        # staged directory name -> {HF model names}


def parse(master_docs: list[str], runners_doc: str | None) -> Recipes:
    """A file that doesn't parse contributes nothing (so no checkpoint is named from it)."""
    out = Recipes()
    for text in master_docs:
        try:
            doc = yaml.safe_load(text) or {}
        except yaml.YAMLError:
            continue
        out.recipes += [v for v in doc.values() if isinstance(v, dict) and isinstance(v.get("model"), str)]
    if runners_doc:
        try:
            doc = yaml.safe_load(runners_doc) or {}
        except yaml.YAMLError:
            doc = {}
        for cluster in (doc.get("clusters") or {}).values():
            entries = ((cluster or {}).get("models") or {}).get("entries") or {}
            for name, e in entries.items():
                if isinstance(e, dict) and e.get("dir"):
                    out.dirs.setdefault(str(e["dir"]), set()).add(str(name).split("@", 1)[0])
    return out


def checkpoint(rc: Recipes, row: dict, served_path: str | None) -> str | None:
    """The HF repo the row's recipe served, or None unless exactly one agrees with the path."""
    if not served_path:
        return None
    leaf = served_path.rstrip("/").rsplit("/", 1)[-1]
    staged = rc.dirs.get(leaf, set())
    hits = {r["model"] for r in rc.recipes
            if r.get("framework") == row.get("framework") and r.get("precision") == row.get("precision")
            and _image(r.get("image")) == _image(row.get("image"))
            and runner_hardware(r.get("runner")) == row.get("hardware")
            and r["model"].rsplit("/", 1)[-1] in ({leaf} | staged)}
    return hits.pop() if len(hits) == 1 else None


class GitHubRecipes:
    """Reads a run's commit and that commit's recipes through the GitHub REST API, cached."""

    def __init__(self, get, repo: str):
        self.get, self.repo = get, repo          # get(path) -> parsed JSON
        self._sha: dict = {}
        self._at: dict = {}

    def run_commit(self, run_id: str) -> str:
        if run_id not in self._sha:
            self._sha[run_id] = self.get(f"/repos/{self.repo}/actions/runs/{run_id}")["head_sha"]
        return self._sha[run_id]

    def at(self, sha: str) -> Recipes:
        if sha not in self._at:
            tree = self.get(f"/repos/{self.repo}/git/trees/{sha}?recursive=1")["tree"]
            blob = lambda t: base64.b64decode(self.get(f"/repos/{self.repo}/git/blobs/{t['sha']}")["content"]).decode()
            masters = [blob(t) for t in sorted(tree, key=lambda t: t["path"]) if _MASTER.search(t["path"])]
            runners = next((blob(t) for t in tree if _RUNNERS.search(t["path"])), None)
            self._at[sha] = parse(masters, runners)
        return self._at[sha]
