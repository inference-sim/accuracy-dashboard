"""HTTP clients for build resolution: Docker Hub's registry API and GitHub's REST API.

Both are stdlib-only. The GitHub client takes a token from GH_TOKEN / GITHUB_TOKEN (CI) or
`gh auth token` (local); unauthenticated calls work but are rate-limited to 60/hour.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
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


def _get_json(url: str, headers: dict, timeout: int = 60):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed hosts)
        return json.loads(resp.read())


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
        d = self._get(f"/repos/{repo}/compare/{base}...{head}?per_page=1")
        return d["status"], d["ahead_by"], d["behind_by"]

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
