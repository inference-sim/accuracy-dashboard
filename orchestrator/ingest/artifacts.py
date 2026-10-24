"""Join an InferenceX API row to its GitHub Actions artifacts, and freeze what a point needs.

InferenceX uploads, per benchmark point of a run:

  bmk_<RESULT_FILENAME> / bmk_agentic_<RESULT_FILENAME>   the result JSON (recipe_fingerprint, conc)
  server_logs_<RESULT_FILENAME>                           the vLLM server log (+ launch config)
  agentic_<RESULT_FILENAME>                               the AgentX client's exports (agentic only)

The API row carries `recipe_fingerprint` + `conc` but not RESULT_FILENAME, so the join goes
through the result JSON: the one whose fingerprint and concurrency match the row names the
point, and its RESULT_FILENAME names the point's other uploads. Failed or cancelled attempts
upload logs with no result JSON; those never match, since only a RESULT_FILENAME that has a
result JSON is a point. If one RESULT_FILENAME has several server_logs_* uploads (a retried
job), the first one created at or after its result JSON is the one that ran with it.

Inside an artifact, files are found by what they contain, not by where they sit, because
the layout has changed over time and will again: a server log is a text file carrying
vLLM's `non-default args:` line or engine banner; a launch config is a YAML file whose
benchmark.env.RESULT_FILENAME is the point's; the client export is
`profile_export_aiperf.json`. Archives nested inside an artifact (srt-single-node-logs.tar.gz)
are searched too.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import tarfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field

import clients

RESULT_PREFIXES = ("bmk_agentic_", "bmk_")
SERVER_LOGS_PREFIX = "server_logs_"
AGENTIC_PREFIX = "agentic_"

_SERVER_LOG_MARKERS = (b"non-default args:", b"Initializing a V1 LLM engine")
_MAX_MEMBER = 2 * 1024 ** 3


@dataclass(frozen=True)
class Artifact:
    id: int
    name: str
    created_at: str
    expired: bool
    size: int

    @staticmethod
    def from_api(a: dict) -> "Artifact":
        return Artifact(id=int(a["id"]), name=a["name"], created_at=a["created_at"],
                        expired=bool(a.get("expired")), size=int(a.get("size_in_bytes") or 0))


def result_filename(name: str) -> str | None:
    for p in RESULT_PREFIXES:
        if name.startswith(p):
            return name[len(p):]
    return None


@dataclass
class Join:
    """The artifacts that belong to one point, or why there are none."""
    result: Artifact | None = None
    result_json: dict | None = None
    result_filename: str | None = None
    server_logs: Artifact | None = None
    agentic: Artifact | None = None
    reasons: list[str] = field(default_factory=list)


def _pick(candidates: list[Artifact], t: str, what: str) -> tuple[Artifact | None, str | None]:
    """The one upload that belongs with a result created at t: the only live one, else the
    only one created at or after t (a retried job re-uploads). Anything else is ambiguous."""
    live = sorted((a for a in candidates if not a.expired), key=lambda a: (a.created_at, a.id))
    if not live:
        return None, ("artifact_expired" if candidates else None)
    if len(live) == 1:
        return live[0], None
    after = [a for a in live if a.created_at >= t]
    if len(after) == 1:
        return after[0], None
    return None, f"artifact_unmatched:several_{what}"


def join(row: dict, artifacts: list[Artifact], read_result, *, agentic: bool) -> Join:
    """Match a row to its point's artifacts.

    read_result(artifact) -> dict reads a result-JSON artifact (downloaded and unzipped).
    Only result JSONs are read; the large logs are not touched here.
    """
    j = Join()
    fp, conc = row.get("recipe_fingerprint"), row.get("conc")
    if not fp:
        j.reasons = ["artifact_unmatched:no_recipe_fingerprint"]
        return j
    results = [a for a in artifacts if result_filename(a.name) and not a.expired]
    matches = []
    for a in sorted(results, key=lambda a: (a.created_at, a.id)):
        doc = read_result(a)
        if isinstance(doc, dict) and doc.get("recipe_fingerprint") == fp and doc.get("conc") == conc:
            matches.append((a, doc))
    if len(matches) > 1:
        # A re-run attempt re-uploads; keep the attempt the row names, when the JSON says.
        attempt = row.get("_attempt")
        same = [(a, d) for a, d in matches if attempt is not None and d.get("run_attempt") == attempt]
        if len(same) == 1:
            matches = same
    if len(matches) != 1:
        j.reasons = [f"artifact_unmatched:{'no_result' if not matches else 'several_results'}"]
        return j
    j.result, j.result_json = matches[0]
    j.result_filename = result_filename(j.result.name)
    named = lambda prefix: [a for a in artifacts if a.name == prefix + j.result_filename]  # noqa: E731
    j.server_logs, why = _pick(named(SERVER_LOGS_PREFIX), j.result.created_at, "server_logs")
    if j.server_logs is None:
        j.reasons.append(why if why and why.startswith("artifact_unmatched") else "server_log_missing")
    if agentic:
        j.agentic, why = _pick(named(AGENTIC_PREFIX), j.result.created_at, "agentic_exports")
        if j.agentic is None:
            j.reasons.append(why if why and why.startswith("artifact_unmatched") else "artifact_unmatched:agentic_export")
    return j


# ------------------------------------------------------------------ reading an artifact

class Unreadable(ValueError):
    """An artifact member that couldn't be read whole (too deep, too large, corrupt)."""


# How much of an oversized member is read, to tell what it is.
_HEAD = 1 << 20


@dataclass
class Oversized:
    """A member too large to read whole, skipped; `head` is its first bytes, so the caller can
    tell whether it's one it needs (a log, a config, a named export, a nested archive)."""
    path: str
    size: int
    head: bytes

    def is_archive(self) -> bool:
        return self.head[:4] == b"PK\x03\x04" or self.head[:2] == b"\x1f\x8b" or _is_tar(self.head)


def iter_files(blob: bytes, name: str = "", depth: int = 0, oversized: list | None = None):
    """(path, bytes) for every file in a zip / tar(.gz) / gzip blob, recursing into nested
    archives. A non-archive yields itself. Anything that can't be read whole raises
    Unreadable rather than being skipped: a dropped member could be the log that disagrees.
    The one exception: given an `oversized` list, a member over the size cap is appended to it
    (an Oversized) instead, and the caller decides whether it was one it needed."""
    if depth > 4:
        raise Unreadable(f"{name}: archives nested more than 4 deep")
    if blob[:4] == b"PK\x03\x04":
        try:
            z = zipfile.ZipFile(io.BytesIO(blob))
        except zipfile.BadZipFile as e:
            raise Unreadable(f"{name}: corrupt zip ({e})")
        with z:
            for info in sorted(z.infolist(), key=lambda i: i.filename):
                if info.is_dir():
                    continue
                path = f"{name}/{info.filename}" if name else info.filename
                try:
                    if info.file_size > _MAX_MEMBER:
                        if oversized is None:
                            raise Unreadable(f"{path}: {info.file_size} bytes")
                        with z.open(info) as f:
                            oversized.append(Oversized(path, info.file_size, f.read(_HEAD)))
                        continue
                    data = z.read(info)
                except (zipfile.BadZipFile, EOFError, OSError) as e:
                    raise Unreadable(f"{path}: corrupt member ({e})")
                yield from iter_files(data, path, depth + 1, oversized)
        return
    if blob[:2] == b"\x1f\x8b":
        try:
            inner = gzip.decompress(blob)
        except (OSError, EOFError) as e:
            raise Unreadable(f"{name}: corrupt gzip ({e})")
        if _is_tar(inner):
            yield from _iter_tar(inner, name, depth, oversized)
        else:
            yield name[:-3] if name.endswith(".gz") else name, inner
        return
    if _is_tar(blob):
        yield from _iter_tar(blob, name, depth, oversized)
        return
    yield name, blob


def _is_tar(b: bytes) -> bool:
    return len(b) > 262 and b[257:262] == b"ustar"


def _iter_tar(b: bytes, name: str, depth: int, oversized: list | None = None):
    with tarfile.open(fileobj=io.BytesIO(b)) as t:
        for m in sorted(t.getmembers(), key=lambda m: m.name):
            if not m.isfile():
                continue
            path = f"{name}/{m.name.lstrip('./')}" if name else m.name.lstrip("./")
            f = t.extractfile(m)
            if f is None:
                continue
            if m.size > _MAX_MEMBER:
                if oversized is None:
                    raise Unreadable(f"{path}: {m.size} bytes")
                oversized.append(Oversized(path, m.size, f.read(_HEAD)))
                continue
            yield from iter_files(f.read(), path, depth + 1, oversized)


def is_server_log(data: bytes) -> bool:
    return any(m in data for m in _SERVER_LOG_MARKERS)


def find_server_logs(files: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    """Every vLLM engine log among the files. One per engine process host (a multi-node or
    multi-worker run has several); the caller requires them to agree."""
    return [(p, d) for p, d in files if is_server_log(d)]


def find_launch_config(files: list[tuple[str, bytes]], result_fn: str):
    """The launch config (a YAML whose benchmark.env.RESULT_FILENAME is this point's), parsed;
    None when the artifact carries none. Several files can name the point (a copy under
    logs/); they must be identical once parsed."""
    import yaml
    found = []
    for p, d in files:
        if not p.endswith((".yaml", ".yml")) or result_fn.encode() not in d:
            continue
        try:
            doc = yaml.safe_load(d)
        except yaml.YAMLError as e:
            raise ValueError(f"{p} names {result_fn} but isn't valid YAML: {e}")
        env = ((doc or {}).get("benchmark") or {}).get("env") or {} if isinstance(doc, dict) else {}
        if env.get("RESULT_FILENAME") == result_fn:
            found.append((p, doc))
    if not found:
        return None, None
    # A copy under logs/ and the recipe lock (the same launch plus a `lock` record) name the
    # point too. They must agree on what was launched; extra metadata doesn't count.
    launched = {json.dumps({k: doc.get(k) for k in LAUNCH_KEYS}, sort_keys=True, default=str) for _, doc in found}
    if len(launched) > 1:
        raise ValueError(f"several different launch configs name {result_fn}: {[p for p, _ in found]}")
    return sorted(found, key=lambda x: (x[0].count("/"), x[0]))[0]


# What a launch config says about the engine: compared across copies of one point's config.
LAUNCH_KEYS = ("model", "roles", "frontend", "engine", "resources")


def find_named(files: list[tuple[str, bytes]], basename: str) -> list[tuple[str, bytes]]:
    return [(p, d) for p, d in files if p.rsplit("/", 1)[-1] == basename]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_gzip(data: bytes) -> bytes:
    """gzip with a fixed mtime and no file name, so the same bytes freeze identically."""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, filename="") as g:
        g.write(data)
    return buf.getvalue()


# ------------------------------------------------------------------ the GitHub client

class GitHubArtifacts:
    """Lists a run's artifacts and downloads them (authenticated; the archive URL redirects to
    blob storage, which must not receive the GitHub token). Downloads are cached by artifact id."""

    def __init__(self, repo: str, token: str | None, cache_dir, sleep=None):
        from pathlib import Path
        self.repo, self.token, self.sleep = repo, token, sleep
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)

    def _headers(self):
        h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def list(self, run_id: str) -> list[Artifact]:
        out, page = [], 1
        while True:
            url = f"https://api.github.com/repos/{self.repo}/actions/runs/{run_id}/artifacts?per_page=100&page={page}"
            doc = clients._get_json(url, self._headers(), 120, sleep=self.sleep)
            arts = doc.get("artifacts") or []
            out += [Artifact.from_api(a) for a in arts]
            if len(out) >= int(doc.get("total_count") or 0) or not arts:
                return out
            page += 1

    def download(self, art: Artifact) -> bytes:
        path = self.cache / f"{art.id}.zip"
        if path.exists():
            return path.read_bytes()

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None

        url = f"https://api.github.com/repos/{self.repo}/actions/artifacts/{art.id}/zip"
        try:
            data = clients._get_bytes(url, self._headers(), 120, sleep=self.sleep,
                                      opener=urllib.request.build_opener(NoRedirect))
        except urllib.error.HTTPError as e:
            if e.code not in (301, 302, 303, 307, 308):
                raise
            # The blob URL is signed: no GitHub token goes to it.
            data = clients._get_bytes(e.headers["Location"], {}, 600, sleep=self.sleep)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
        return data


def read_result_json(blob: bytes) -> dict | None:
    """The result JSON in a bmk_* artifact: exactly one JSON object with a recipe_fingerprint.
    None for an artifact with none (it isn't a point's result); several is an error."""
    found = []
    for p, d in iter_files(blob):
        if p.endswith(".json"):
            try:
                doc = json.loads(d)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(doc, dict) and "recipe_fingerprint" in doc:
                found.append(doc)
    if len(found) > 1:
        raise ValueError(f"{len(found)} result JSONs in one artifact")
    return found[0] if found else None


_RF = re.compile(r"[A-Za-z0-9_.\-]+")
