"""Pull InferenceX rows from its public API (Discussion #28, "Point identity and ingest").

  /api/v1/availability       every (model slug, …, date) InferenceX has published
  /api/v1/benchmarks?model=  every row of one model, by its DISPLAY name

/benchmarks takes the display name, not the slug, and the API exposes no mapping. The site
ships it in its JavaScript (`{dsr1:"DeepSeek-R1-0528", …}`), so `display_names` reads it from
there, and a slug /availability lists that the site doesn't name is reported, never guessed.
Several slugs can share one display name (glm5 and glm5.1 are both "GLM-5"); /benchmarks
returns all of them, and rows are kept by slug.

The window is on the row's `date` (when it was measured), not `curve_date`. Everything goes
through an injectable `fetch(url) -> bytes`, so tests run offline.
"""
from __future__ import annotations

import gzip
import json
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import date, timedelta

BASE = "https://inferencex.semianalysis.com"
API = BASE + "/api/v1"

# The slug -> display-name object literal in the site bundle: `{dsr1:"DeepSeek-R1-0528",…}`.
_MAP_ENTRY = re.compile(r'(?:"([a-z0-9][a-z0-9.\-]*)"|([a-z][a-z0-9]*))\s*:\s*"([^"]+)"')
_SCRIPT = re.compile(r'(/_next/static/[^"\'\s]+\.js)')


def http_fetch(url: str, timeout: int = 120) -> bytes:
    """The body, decompressed: the API and site gzip their responses. Retried like every other
    fetch (clients._get_bytes); an outage that outlasts the retries stops the pull."""
    import clients
    return gunzip(clients._get_bytes(url, {"Accept-Encoding": "gzip", "User-Agent": "accuracy-dashboard-ingest"},
                                     timeout))


def gunzip(body: bytes) -> bytes:
    return gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body


def decode(body: bytes):
    """JSON from a body that may or may not be gzip-encoded."""
    return json.loads(gunzip(body))


def parse_display_map(js: str, slugs: set[str]) -> dict[str, str]:
    """The slug -> display map from a site script: the object literal that names the most of
    `slugs`. Entries for slugs we don't know are ignored."""
    best: dict[str, str] = {}
    for obj in re.finditer(r"\{[^{}]{0,20000}\}", js):
        found = {}
        for m in _MAP_ENTRY.finditer(obj.group(0)):
            slug = m.group(1) or m.group(2)
            if slug in slugs:
                found[slug] = m.group(3)
        if len(found) > len(best):
            best = found
    return best


def display_names(fetch, slugs: set[str]) -> dict[str, str]:
    """Read the slug -> display map the site itself uses."""
    html = gunzip(fetch(BASE + "/")).decode("utf-8", "replace")
    best: dict[str, str] = {}
    for path in sorted(set(_SCRIPT.findall(html))):
        found = parse_display_map(gunzip(fetch(BASE + path)).decode("utf-8", "replace"), slugs)
        if len(found) > len(best):
            best = found
        if len(best) == len(slugs):
            break
    return best


@dataclass
class Pull:
    """One API pull: the rows in the window and what couldn't be pulled."""
    rows: list[dict] = field(default_factory=list)
    unnamed_slugs: list[str] = field(default_factory=list)   # in /availability, not on the site
    undated: list[dict] = field(default_factory=list)        # rows whose date doesn't parse
    window: tuple[str, str] = ("", "")


def in_window(row_date: str, start: date, end: date) -> bool:
    try:
        d = date.fromisoformat(str(row_date)[:10])
    except ValueError:
        return False
    return start <= d <= end


def pull(fetch, *, today: date, window_days: int, framework: str = "vllm") -> Pull:
    """Every `framework` row measured within the last `window_days` days (inclusive of today),
    for every model InferenceX lists. Sorted by row id, so a pull is order-stable."""
    start = today - timedelta(days=window_days)
    avail = decode(fetch(API + "/availability"))
    slugs = {a["model"] for a in avail
             if a.get("framework") == framework and in_window(a.get("date"), start, today)}
    names = display_names(fetch, slugs) if slugs else {}
    if slugs and not names:
        # Nothing at all named: the site changed shape, not the data. Fail rather than
        # publish an empty pull.
        raise RuntimeError("no slug -> display-name map found in the InferenceX site scripts")
    out = Pull(unnamed_slugs=sorted(slugs - set(names)), window=(start.isoformat(), today.isoformat()))
    seen = set()
    for display in sorted(set(names[s] for s in slugs if s in names)):
        rows = decode(fetch(API + "/benchmarks?model=" + urllib.parse.quote(display)))
        if isinstance(rows, dict) and "error" in rows:
            raise RuntimeError(f"/benchmarks?model={display}: {rows['error']}")
        for r in rows:
            if r.get("framework") != framework or r.get("model") not in slugs or str(r["id"]) in seen:
                continue
            try:
                date.fromisoformat(str(r.get("date"))[:10])
            except ValueError:
                seen.add(str(r["id"]))
                out.undated.append(r)      # kept and reported, never silently dropped
                continue
            if in_window(r.get("date"), start, today):
                seen.add(str(r["id"]))
                out.rows.append(r)
    out.rows.sort(key=lambda r: int(r["id"]) if str(r["id"]).isdigit() else str(r["id"]))
    return out


def server_log(fetch, row_id) -> str | None:
    """The API's /server-log for a row (the vLLM log for single-turn rows; agentic rows carry
    the client's log here, not the server's)."""
    doc = decode(fetch(f"{API}/server-log?id={row_id}"))
    text = doc.get("serverLog") if isinstance(doc, dict) else None
    return text or None


_RUN = re.compile(r"/actions/runs/(\d+)(?:/attempts/(\d+))?")


def run_of(row: dict) -> tuple[str, int] | None:
    """(GitHub Actions run id, attempt) from a row's run_url; attempt 1 when unstated."""
    m = _RUN.search(str(row.get("run_url") or ""))
    if not m:
        return None
    return m.group(1), int(m.group(2) or 1)
