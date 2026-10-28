"""HTTP clients for build resolution: Docker Hub's registry API and GitHub's REST API.

Both are stdlib-only. The GitHub client takes a token from GH_TOKEN / GITHUB_TOKEN (CI) or
`gh auth token` (local); unauthenticated calls work but are rate-limited to 60/hour.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

_MANIFEST_TYPES = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])


class RateLimited(RuntimeError):
    """A host kept refusing with a rate limit after the retries: the run is invalid as a whole
    (every later row would fail the same way), so the pull stops rather than recording it as
    a per-row data problem."""


class FetchFailed(RuntimeError):
    """A host kept failing (5xx, connection errors, timeouts) after the retries. Like
    RateLimited, it stops the pull: an outage would otherwise be filed as per-row data gaps."""


def _get_bytes(url: str, headers: dict, timeout: int = 60, *, retries: int = 4, sleep=None, opener=None,
               max_total_wait: int = 900) -> bytes:
    """GET a body, retrying 5xx, connection errors and rate limits (429, or 403 with no quota
    left) with backoff, honouring Retry-After / x-ratelimit-reset. Other HTTP errors (4xx, and
    a redirect the opener refuses to follow) raise at once as HTTPError; retries that run out
    raise RateLimited or FetchFailed.

    Back-off across all retries of one request is bounded by max_total_wait: a primary rate limit's
    reset can be most of an hour away, but the whole run shares that hourly quota, so waiting it out
    inside one request only idles the runner before the same failure (GitHub #15 idled ~47 min on a
    single request). If the next back-off would exceed the budget, give up now and fail loudly."""
    sleep = sleep or time.sleep
    open_ = opener.open if opener else urllib.request.urlopen
    spent = 0
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers=headers)
        try:
            with open_(req, timeout=timeout) as resp:  # noqa: S310 (fixed hosts)
                return resp.read()
        except urllib.error.HTTPError as e:
            limited = e.code == 429 or (e.code == 403 and e.headers.get("x-ratelimit-remaining") == "0")
            if not (limited or e.code >= 500):
                raise
            wait = e.headers.get("Retry-After")
            reset = e.headers.get("x-ratelimit-reset")
            if wait and wait.isdigit():
                delay = int(wait)
            elif limited and reset and reset.isdigit():
                delay = max(1, int(reset) - int(time.time()))
            else:
                delay = 2 ** attempt
            # Give up when out of attempts, or when the true wait this back-off needs would blow the
            # budget (a far-off reset the run can't afford to sit through -- sleeping a capped partial
            # of it only idles the runner, since the quota won't be back when we retry).
            if attempt == retries or spent + delay > max_total_wait:
                how = f"after {attempt + 1} tr{'y' if attempt == 0 else 'ies'}"
                if limited:
                    raise RateLimited(f"{url.split('?')[0]}: HTTP {e.code} {how}") from e
                raise FetchFailed(f"{url.split('?')[0]}: HTTP {e.code} {how}") from e
            delay = min(delay, 900)   # re-check cadence: never sleep more than 15 min in one go
            sleep(delay)
            spent += delay
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            delay = 2 ** attempt
            if attempt == retries or spent + delay > max_total_wait:
                raise FetchFailed(f"{url.split('?')[0]}: {e!r} after {attempt + 1} tries") from e
            sleep(delay)
            spent += delay
    raise AssertionError("unreachable")


def _get_json(url: str, headers: dict, timeout: int = 60, *, retries: int = 4, sleep=None):
    """GET JSON through _get_bytes's retries."""
    return json.loads(_get_bytes(url, headers, timeout, retries=retries, sleep=sleep))


class DockerHubRegistry:
    """Reads an image's OCI revision label without pulling it: index → platform manifest → config.

    Pull tokens expire (300 s), so each is kept with its expiry and refreshed once on a 401.
    Only a 404 means "no such manifest / label"; any other failure raises, so a transient auth or
    rate-limit error can't quietly change which source a point's commit comes from.
    """

    def __init__(self, architecture: str = "amd64", clock=time.monotonic):
        self.architecture = architecture
        self.clock = clock
        self._tokens: dict[str, tuple[str, float]] = {}

    def _token(self, repository: str, refresh: bool = False) -> str:
        token, expires = self._tokens.get(repository, ("", 0.0))
        if refresh or not token or self.clock() >= expires:
            url = ("https://auth.docker.io/token?service=registry.docker.io&scope="
                   + urllib.parse.quote(f"repository:{repository}:pull"))
            doc = _get_json(url, {})
            # Refresh a little early so a request never carries a token that expires mid-flight.
            token, expires = doc["token"], self.clock() + max(int(doc.get("expires_in", 300)) - 30, 30)
            self._tokens[repository] = (token, expires)
        return token

    def _get(self, repository: str, path: str):
        for attempt in (0, 1):
            headers = {"Authorization": f"Bearer {self._token(repository, refresh=attempt == 1)}",
                       "Accept": _MANIFEST_TYPES}
            try:
                return _get_json(f"https://registry-1.docker.io/v2/{repository}/{path}", headers)
            except urllib.error.HTTPError as e:
                if e.code == 401 and attempt == 0:
                    continue
                raise
        raise AssertionError("unreachable")

    def revision_label(self, repository: str, reference: str) -> str | None:
        try:
            manifest = self._get(repository, f"manifests/{reference}")
            if "manifests" in manifest:   # an index: pick the platform's manifest
                picks = [m for m in manifest["manifests"]
                         if m.get("platform", {}).get("architecture") == self.architecture]
                if not picks:
                    return None
                manifest = self._get(repository, f"manifests/{picks[0]['digest']}")
            digest = (manifest.get("config") or {}).get("digest")
            if not digest:
                return None
            config = self._get(repository, f"blobs/{digest}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
        return ((config.get("config") or {}).get("Labels") or {}).get("org.opencontainers.image.revision")


def require_github_token() -> str:
    """The token the pull needs: artifact downloads require one, and an unauthenticated run is
    rate-limited to 60 requests an hour. Refuse to start without it."""
    tok = _github_token()
    if not tok:
        raise SystemExit("no GitHub token: set GH_TOKEN (or GITHUB_TOKEN) for the pull")
    return tok


def _github_token() -> str | None:
    for var in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(var):
            return os.environ[var]
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


class GitHubREST:
    def __init__(self, token: str | None = None):
        self.token = token if token is not None else _github_token()
        self._release_tags: dict[str, list[str]] = {}
        # compare() is a pure function of (repo, base, head) within a run, and is_on_release_tag
        # walks it over every release tag -- so points built from the same release branch all ask
        # the same (ref branch point -> branch cut) comparison. Memoise it under a lock: one client
        # is shared across the pull's download-worker pool, and a duplicate compare spends quota the
        # nightly has little of (GitHub #15: a release tag's compares exhausted it and 403'd).
        self._compares: dict[tuple[str, str, str], tuple[str, int, int]] = {}
        self._compare_guard = threading.Lock()
        self._compare_locks: dict[tuple[str, str, str], threading.Lock] = {}

    def _get(self, path: str):
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return _get_json(f"https://api.github.com{path}", headers)

    def resolve_commit(self, repo: str, sha_prefix: str) -> str | None:
        if not re.fullmatch(r"[0-9a-f]{7,40}", sha_prefix):
            return None
        try:
            return self._get(f"/repos/{repo}/commits/{sha_prefix}")["sha"]
        except urllib.error.HTTPError as e:
            if e.code in (404, 422):
                return None
            raise

    def tag_commit(self, repo: str, tag: str) -> str | None:
        """The commit a release tag (vX.Y.Z) names in repo, or None if repo has no such tag."""
        if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
            return None
        try:
            return self._get(f"/repos/{repo}/commits/{tag}")["sha"]
        except urllib.error.HTTPError as e:
            if e.code in (404, 422):
                return None
            raise

    def compare(self, repo: str, base: str, head: str) -> tuple[str, int, int]:
        key = (repo, base, head)
        with self._compare_guard:
            lock = self._compare_locks.setdefault(key, threading.Lock())
        with lock:   # the first caller of this (base, head) fetches; the rest reuse its result
            if key not in self._compares:
                d = self._get(f"/repos/{repo}/compare/{base}...{head}?per_page=1")
                self._compares[key] = (d["status"], d["ahead_by"], d["behind_by"])
            return self._compares[key]

    def merge_base(self, repo: str, a: str, b: str) -> str:
        return self._get(f"/repos/{repo}/compare/{b}...{a}?per_page=1")["merge_base_commit"]["sha"]

    def is_on_release_tag(self, repo: str, sha: str) -> bool:
        """Whether some vX.Y.Z tag contains sha. Every release tag is listed (paged), since a build
        far from VLLM_REF is still scored, as estimated."""
        if repo not in self._release_tags:
            names, page = [], 1
            while True:
                got = self._get(f"/repos/{repo}/tags?per_page=100&page={page}")
                names += [t["name"] for t in got if re.fullmatch(r"v\d+\.\d+\.\d+", t["name"])]
                if len(got) < 100:
                    break
                page += 1
            self._release_tags[repo] = names
        for name in self._release_tags[repo]:
            status = self.compare(repo, sha, name)[0]
            if status in ("ahead", "identical"):
                return True
        return False
