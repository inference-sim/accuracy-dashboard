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
import urllib.error
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
    scripts: dict = field(default_factory=dict)     # path of a benchmark script -> its blob sha
    entries: list = field(default_factory=list)     # (key, dict) of every master-configuration entry
    tree: dict = field(default_factory=dict)        # path of every file of the commit -> its blob sha


def parse(master_docs: list[str], runners_doc: str | None) -> Recipes:
    """A file that doesn't parse contributes nothing (so no checkpoint is named from it)."""
    out = Recipes()
    for text in master_docs:
        try:
            doc = yaml.safe_load(text) or {}
        except yaml.YAMLError:
            continue
        out.recipes += [v for v in doc.values() if isinstance(v, dict) and isinstance(v.get("model"), str)]
        out.entries += [(k, v) for k, v in doc.items() if isinstance(v, dict) and isinstance(v.get("model"), str)]
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


def matching(rc: Recipes, row: dict) -> list:
    """The recipes whose framework, precision, image and runner hardware are the row's."""
    return [r for r in rc.recipes
            if r.get("framework") == row.get("framework") and r.get("precision") == row.get("precision")
            and _image(r.get("image")) == _image(row.get("image"))
            and runner_hardware(r.get("runner")) == row.get("hardware")]


def conflicting_checkpoint(rc: Recipes, row: dict, served_path: str | None) -> str | None:
    """The one HF repo the row's recipes serve, when it is not what the served path names: the
    path's last component is neither that repo's name nor a directory staging it. checkpoint()
    gives None for that row; this says the recipe and the run disagree, not that nothing is known."""
    if not served_path or checkpoint(rc, row, served_path):
        return None
    models = {r["model"] for r in matching(rc, row)}
    return next(iter(models)) if len(models) == 1 else None


_DRAFT = re.compile(r"""^\s*(?:export\s+)?DRAFT_MODEL=["']?([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)["']?\s*(?:#.*)?$""")


def draft_script(rc: Recipes, row: dict) -> str | None:
    """The benchmark script the row's recipe ran with a draft model, by InferenceX's naming
    (<model-prefix>_<precision>_<hardware>_mtp.sh), or None unless exactly one script has it."""
    if row.get("spec_method") in (None, "none"):
        return None
    prefixes = {r.get("model-prefix") for r in matching(rc, row)} - {None}
    names = {f"{p}_{row.get('precision')}_{row.get('hardware')}_mtp.sh" for p in prefixes}
    paths = [p for p in rc.scripts if p.rsplit("/", 1)[-1] in names]
    return paths[0] if len(paths) == 1 else None


def launch_script(rc: Recipes, row: dict) -> str | None:
    """The benchmark script that launched the row's engine, by InferenceX's naming
    (<model-prefix>_<precision>_<hardware>[_mtp].sh under benchmarks/single_node), or None unless exactly one
    script has it. The model prefix is the row's model slug, and it must be the prefix of a recipe of the row's
    framework, precision and runner at the run's commit, so a script of another framework that shares the name stem
    is not taken for the row's. (The recipe's image is not compared: the workflow can set the image a run uses.)"""
    prefixes = {r.get("model-prefix") for r in rc.recipes
                if r.get("framework") == row.get("framework") and r.get("precision") == row.get("precision")
                and runner_hardware(r.get("runner")) == row.get("hardware")} & {row.get("model")}
    mtp = "_mtp" if row.get("spec_method") not in (None, "none") else ""
    names = {f"{p}_{row.get('precision')}_{row.get('hardware')}{mtp}.sh" for p in prefixes}
    # The single-turn scripts sit in benchmarks/single_node, or in its fixed_seq_len directory once InferenceX split
    # them from the agentic ones.
    dirs = ("benchmarks/single_node/", "benchmarks/single_node/fixed_seq_len/")
    paths = [p for p in rc.scripts if p.rsplit("/", 1)[0] + "/" in dirs and p.rsplit("/", 1)[-1] in names]
    return paths[0] if len(paths) == 1 else None


def draft_model(text: str) -> tuple[str, int] | None:
    """(the HF repo, the line) of the script's DRAFT_MODEL, or None unless it assigns exactly one."""
    hits = [(m.group(1), i + 1) for i, line in enumerate(text.splitlines()) if (m := _DRAFT.match(line))]
    return hits[0] if len({h[0] for h in hits}) == 1 else None


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


class RecipesUnavailable(Exception):
    """The run's commit or its tree is not readable (HTTP 404: a commit of a fork's pull request, or
    one the repository no longer holds), so nothing of the commit's recipes is known."""


class GitHubRecipes:
    """Reads a run's commit and that commit's recipes through the GitHub REST API, cached."""

    def __init__(self, get, repo: str):
        self.get, self.repo = get, repo          # get(path) -> parsed JSON
        self._sha: dict = {}
        self._at: dict = {}
        self._blob: dict = {}

    def run_commit(self, run_id: str) -> str:
        if run_id not in self._sha:
            self._sha[run_id] = self.get(f"/repos/{self.repo}/actions/runs/{run_id}")["head_sha"]
        return self._sha[run_id]

    def script(self, rc: Recipes, path: str) -> str:
        return base64.b64decode(self.get(f"/repos/{self.repo}/git/blobs/{rc.scripts[path]}")["content"]).decode()

    def blob_text(self, blob_sha: str) -> str:
        # Cached: the pull asks for the launch scripts of a commit once per row of its run.
        if blob_sha not in self._blob:
            self._blob[blob_sha] = base64.b64decode(self.get(f"/repos/{self.repo}/git/blobs/{blob_sha}")["content"]).decode()
        return self._blob[blob_sha]

    def at(self, sha: str) -> Recipes:
        if sha not in self._at:
            try:
                tree = self.get(f"/repos/{self.repo}/git/trees/{sha}?recursive=1")["tree"]
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    raise RecipesUnavailable(sha) from e
                raise
            blob = lambda t: base64.b64decode(self.get(f"/repos/{self.repo}/git/blobs/{t['sha']}")["content"]).decode()
            masters = [blob(t) for t in sorted(tree, key=lambda t: t["path"]) if _MASTER.search(t["path"])]
            runners = next((blob(t) for t in tree if _RUNNERS.search(t["path"])), None)
            rc = parse(masters, runners)
            rc.scripts = {t["path"]: t["sha"] for t in tree if t["path"].startswith("benchmarks/") and t["path"].endswith(".sh")}
            rc.tree = {t["path"]: t["sha"] for t in tree if t.get("type", "blob") == "blob"}
            self._at[sha] = rc
        return self._at[sha]


class GitRecipes(GitHubRecipes):
    """The same reads from a local bare clone of the repository (git --git-dir), so the trees and blobs of a commit cost
    no REST calls (PROCESS §16): only the commit a run executed (`run_commit`, one call per run) is asked of the API.
    A commit the clone lacks is RecipesUnavailable, and the caller records that."""

    def __init__(self, get, repo: str, git_dir):
        super().__init__(get, repo)
        self.git_dir = str(git_dir)

    def _git(self, *args: str) -> bytes:
        import subprocess
        out = subprocess.run(["git", "--git-dir", self.git_dir, *args], capture_output=True)
        if out.returncode != 0:
            raise RecipesUnavailable(out.stderr.decode(errors="replace")[:200])
        return out.stdout

    def script(self, rc: Recipes, path: str) -> str:
        return self.blob_text(rc.scripts[path])

    def blob_text(self, blob_sha: str) -> str:
        if blob_sha not in self._blob:
            self._blob[blob_sha] = self._git("cat-file", "blob", blob_sha).decode()
        return self._blob[blob_sha]

    def _tree(self, sha: str) -> bytes:
        """The commit's files. A commit the clone lacks (a pull request's head, in no branch) is fetched by its sha once:
        a git fetch, which the REST quota does not count."""
        try:
            return self._git("ls-tree", "-r", "-z", sha)
        except RecipesUnavailable:
            import subprocess
            if subprocess.run(["git", "--git-dir", self.git_dir, "fetch", "-q", "origin", sha], capture_output=True).returncode:
                raise
            return self._git("ls-tree", "-r", "-z", sha)

    def at(self, sha: str) -> Recipes:
        if sha not in self._at:
            tree = []
            for line in self._tree(sha).decode().split("\0"):
                if not line:
                    continue
                meta, _, path = line.partition("\t")
                _mode, kind, oid = meta.split()
                if kind == "blob":
                    tree.append({"path": path, "sha": oid, "type": "blob"})
            masters = [self.blob_text(t["sha"]) for t in sorted(tree, key=lambda t: t["path"]) if _MASTER.search(t["path"])]
            runners = next((self.blob_text(t["sha"]) for t in tree if _RUNNERS.search(t["path"])), None)
            rc = parse(masters, runners)
            rc.scripts = {t["path"]: t["sha"] for t in tree if t["path"].startswith("benchmarks/") and t["path"].endswith(".sh")}
            rc.tree = {t["path"]: t["sha"] for t in tree}
            self._at[sha] = rc
        return self._at[sha]
