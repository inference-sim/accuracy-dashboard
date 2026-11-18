#!/usr/bin/env python3
"""A run's recipes read from a local git clone, in place of the REST tree and blob reads (PROCESS section 16).

`ingest/recipes.py:GitHubRecipes` reads a run's commit, the commit's tree and every master configuration, the runners
file, the launch scripts and the recipe file through the GitHub REST API: tens of calls for each distinct commit.
`GitRecipes` has the same interface and reads all of those from a clone of the repository, so the only REST call left
is the one that names the run's commit (`run_commit`), once per run.

A commit the clone lacks (a fork's pull request, say) is fetched once by its hash over the git protocol, which is not
REST; if the remote no longer holds it either, `RecipesUnavailable` is raised, as for a 404 of the REST reader.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ingest"))
import recipes as rcp  # noqa: E402


class GitRecipes:
    """Same interface as rcp.GitHubRecipes: repo, run_commit, script, blob_text, at."""

    def __init__(self, get, repo: str, git_dir: Path, *, fetch: bool = True):
        self.get, self.repo, self.git_dir, self.fetch = get, repo, Path(git_dir), fetch
        self._sha: dict = {}
        self._at: dict = {}

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "--git-dir", str(self.git_dir), *args], capture_output=True, check=check)

    def _has(self, sha: str) -> bool:
        return self._git("cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode == 0

    def run_commit(self, run_id: str) -> str:
        if run_id not in self._sha:
            self._sha[run_id] = self.get(f"/repos/{self.repo}/actions/runs/{run_id}")["head_sha"]
        return self._sha[run_id]

    def blob_text(self, blob_sha: str) -> str:
        return self._git("cat-file", "blob", blob_sha).stdout.decode()

    def script(self, rc: rcp.Recipes, path: str) -> str:
        return self.blob_text(rc.scripts[path])

    def at(self, sha: str) -> rcp.Recipes:
        if sha not in self._at:
            if not self._has(sha):
                if self.fetch:
                    self._git("fetch", "-q", "origin", sha, check=False)
                if not self._has(sha):
                    raise rcp.RecipesUnavailable(sha)
            out = self._git("ls-tree", "-r", "-z", sha).stdout.decode()
            tree = {}
            for ent in filter(None, out.split("\0")):
                meta, path = ent.split("\t", 1)
                _mode, typ, blob = meta.split()
                if typ == "blob":
                    tree[path] = blob
            masters = [self.blob_text(tree[p]) for p in sorted(tree) if rcp._MASTER.search(p)]
            runners = next((self.blob_text(b) for p, b in tree.items() if rcp._RUNNERS.search(p)), None)
            rc = rcp.parse(masters, runners)
            rc.scripts = {p: b for p, b in tree.items() if p.startswith("benchmarks/") and p.endswith(".sh")}
            rc.tree = dict(tree)
            self._at[sha] = rc
        return self._at[sha]
