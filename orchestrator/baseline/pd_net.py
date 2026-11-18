#!/usr/bin/env python3
"""What keeps a bulk pull inside the shared REST quota (PROCESS section 16): git clones in place of API reads, a disk
cache of every GitHub REST answer, and a floor on the request rate.

  GitCompare       build.GitHub protocol (resolve_commit, tag_commit, compare, merge_base, is_on_release_tag) over a
                   local clone of vllm-project/vllm, so resolving a run's image to a vLLM build costs no REST call.
  install_cache    wraps clients._get_bytes: a GET of api.github.com is answered from the cache directory when it was
                   read before (a rerun costs nothing and the pull resumes), else paced to `min_interval` seconds
                   apart and, every 25 requests, the shared quota is read and the pull stops below `min_core`.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ingest"))

_RELEASE = re.compile(r"v\d+\.\d+\.\d+")


class QuotaLow(RuntimeError):
    pass


class GitCompare:
    """build.GitHub over a local clone. A repo other than the clone's is not answered (KeyError)."""

    def __init__(self, git_dirs: dict[str, Path]):
        self.dirs = {k: Path(v) for k, v in git_dirs.items()}
        self._tags: dict[str, list[str]] = {}

    def _git(self, repo: str, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "--git-dir", str(self.dirs[repo]), *args], capture_output=True, text=True)

    def resolve_commit(self, repo: str, sha_prefix: str) -> str | None:
        if not re.fullmatch(r"[0-9a-f]{7,40}", sha_prefix):
            return None
        r = self._git(repo, "rev-parse", "--verify", "--quiet", f"{sha_prefix}^{{commit}}")
        return r.stdout.strip() or None

    def tag_commit(self, repo: str, tag: str) -> str | None:
        if not _RELEASE.fullmatch(tag):
            return None
        r = self._git(repo, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}")
        return r.stdout.strip() or None

    def compare(self, repo: str, base: str, head: str) -> tuple[str, int, int]:
        r = self._git(repo, "rev-list", "--left-right", "--count", f"{base}...{head}")
        if r.returncode != 0:
            raise LookupError(f"{repo}: no common history readable for {base}...{head}: {r.stderr.strip()[:120]}")
        behind, ahead = (int(x) for x in r.stdout.split())
        status = ("identical" if not (ahead or behind) else "ahead" if not behind
                  else "behind" if not ahead else "diverged")
        return status, ahead, behind

    def merge_base(self, repo: str, a: str, b: str) -> str:
        r = self._git(repo, "merge-base", a, b)
        if r.returncode != 0:
            raise LookupError(f"{repo}: no merge base of {a} and {b}")
        return r.stdout.strip()

    def is_on_release_tag(self, repo: str, sha: str) -> bool:
        if repo not in self._tags:
            names = self._git(repo, "tag", "--list").stdout.split()
            self._tags[repo] = [n for n in names if _RELEASE.fullmatch(n)]
        r = self._git(repo, "tag", "--contains", sha)
        have = set(r.stdout.split())
        return any(t in have for t in self._tags[repo])


def install_cache(clients, cache_dir: Path, *, min_interval: float, min_core: int, core_remaining, clock=time.monotonic,
                  sleep=time.sleep):
    """Wrap clients._get_bytes in place. Returns a counter dict {"hits", "rest"} the caller can read."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    real = clients._get_bytes
    lock = threading.Lock()
    state = {"hits": 0, "rest": 0, "last": float("-inf")}

    def path_of(url: str) -> Path:
        return cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".bin")

    def wrapped(url, headers, timeout=60, **kw):
        if not url.startswith("https://api.github.com/"):
            return real(url, headers, timeout, **kw)
        p = path_of(url)
        if p.is_file():
            state["hits"] += 1
            return p.read_bytes()
        with lock:
            wait = state["last"] + min_interval - clock()
            if wait > 0:
                sleep(wait)
            if state["rest"] % 25 == 0:
                left = core_remaining()
                if left < min_core:
                    raise QuotaLow(f"core quota {left} is below {min_core}: stopping (PROCESS section 16)")
            state["last"] = clock()
            state["rest"] += 1
        body = real(url, headers, timeout, **kw)
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(body)
        tmp.replace(p)
        return body

    clients._get_bytes = wrapped
    return state
