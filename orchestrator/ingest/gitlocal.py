"""GitHub's answers about commits, trees and blobs, read from a local clone instead of the REST API.

Freezing the ledger's pull asks GitHub two kinds of question that a clone answers with no REST request: the build
resolver's questions about vLLM commits (build.Resolver: resolve_commit, tag_commit, compare, merge_base,
is_on_release_tag), and the P/D recipe reader's trees and blobs of an InferenceX commit (recipes.GitHubRecipes).
A clone made with --filter=blob:none fetches a blob over git when it is first read; nothing here is executed, only
read with git plumbing. One difference: GitHub answers a commit of any fork in the repository's network, and a clone
only its own, so a fork's commit resolves to None here (a custom build).
"""
from __future__ import annotations

import base64
import re
import subprocess
import threading
from pathlib import Path


class LocalGit:
    """build.Resolver's GitHub, answered from a clone of the repository at `path` (with its tags)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._release_tags: list[str] | None = None

    def _git(self, *args, ok=(0,)) -> tuple[int, str]:
        r = subprocess.run(["git", "-C", str(self.path), *args], capture_output=True, text=True)
        if r.returncode not in ok:
            raise RuntimeError(f"git {' '.join(args)} exited {r.returncode}: {r.stderr.strip()[-300:]}")
        return r.returncode, r.stdout.strip()

    def _commit(self, ref: str) -> str | None:
        code, out = self._git("rev-parse", "--verify", "-q", f"{ref}^{{commit}}", ok=(0, 1, 128))
        return out if code == 0 and re.fullmatch(r"[0-9a-f]{40}", out) else None

    def resolve_commit(self, repo: str, sha_prefix: str) -> str | None:
        if not re.fullmatch(r"[0-9a-f]{7,40}", sha_prefix):
            return None
        got = self._commit(sha_prefix)
        return got if got and got.startswith(sha_prefix) else None

    def tag_commit(self, repo: str, tag: str) -> str | None:
        if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
            return None
        return self._commit(f"refs/tags/{tag}")

    def compare(self, repo: str, base: str, head: str) -> tuple[str, int, int]:
        """(status, ahead_by, behind_by) as GitHub's compare gives them: the commits head has that base does not, and
        the reverse."""
        _, out = self._git("rev-list", "--left-right", "--count", f"{base}...{head}")
        behind, ahead = (int(x) for x in out.split())
        status = ("identical" if not ahead and not behind else "ahead" if not behind else
                  "behind" if not ahead else "diverged")
        return status, ahead, behind

    def merge_base(self, repo: str, a: str, b: str) -> str:
        return self._git("merge-base", a, b)[1]

    def is_on_release_tag(self, repo: str, sha: str) -> bool:
        _, out = self._git("tag", "--contains", sha, ok=(0, 1, 129))
        return any(re.fullmatch(r"v\d+\.\d+\.\d+", t) for t in out.split())


def local_get(clone: Path, repo: str, rest_get):
    """A `get(path)` for recipes.GitHubRecipes that answers a commit's tree and a blob from `clone`, and passes every
    other path (a run's head commit) to `rest_get`."""
    g = LocalGit(clone)
    tree_re = re.compile(rf"^/repos/{re.escape(repo)}/git/trees/([0-9a-f]{{40}})\?recursive=1$")
    blob_re = re.compile(rf"^/repos/{re.escape(repo)}/git/blobs/([0-9a-f]{{40}})$")

    def get(path: str):
        m = tree_re.match(path)
        if m:
            code, out = g._git("ls-tree", "-r", "-t", "--full-tree", m.group(1), ok=(0, 128))
            if code != 0:
                import io
                import urllib.error
                raise urllib.error.HTTPError(path, 404, "not in the clone", {}, io.BytesIO(b""))
            tree = []
            for line in out.splitlines():
                meta, name = line.split("\t", 1)
                _, kind, sha = meta.split()
                tree.append({"path": name, "type": kind, "sha": sha})
            return {"tree": tree}
        m = blob_re.match(path)
        if m:
            data = subprocess.run(["git", "-C", str(clone), "cat-file", "blob", m.group(1)], capture_output=True,
                                  check=True).stdout
            return {"content": base64.b64encode(data).decode()}
        return rest_get(path)
    return get


def commit_date(clone: Path, sha: str) -> str | None:
    """A commit's committer date in UTC, as GitHub prints a run's head_commit.timestamp, or None when the clone does
    not have the commit."""
    r = subprocess.run(["git", "-C", str(clone), "show", "-s", "--format=%ct", sha], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    from datetime import datetime, timezone
    return datetime.fromtimestamp(int(r.stdout.strip()), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
