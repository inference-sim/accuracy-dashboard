#!/usr/bin/env python3
"""Fetch one agentic InferenceX row and its two logs from the live API, to disk.

An `agentic_traces` row is one AgentX benchmark against one vLLM server. To replay it in
BLIS (and score the replay against the row's measured latencies) three things are needed,
and this fetches all three WITHOUT parsing any of them -- parsing is the job of
`extract_agentic_replay_args.py` (the server + job logs) and `run_agentic.py` (the row):

  the row          GET /api/v1/benchmarks?model=<Display-Name>, then select by id. Carries
                   the measured mean TTFT/TPOT and the metadata the replay needs (conc,
                   spec_method, image, decode_tp/ep, run_url, ...).
  the server log   GET /api/v1/server-log?id=<id> -> {"serverLog": "..."} : the vLLM
                   startup banner (version) and `non-default args` (speculative config).
  the CI job log   the GitHub Actions job behind the row's run_url: the `aiperf profile`
                   command (corpus, seed, concurrency, duration). Fetched with `gh`.

This is the ONLY network component of the agentic path and is meant to be run BY HAND,
locally, against the live API -- it is deliberately NOT wired into the nightly or
ci-verify pipeline (the automated pipeline still scores the db-dump; see discussion #15
for the proposed API migration). It writes three files into an output directory:

    <out>/row-<id>.json          the selected benchmark row, verbatim
    <out>/server-<id>.log        the server log text
    <out>/job-<id>.log           the CI job log text (empty + a note if unavailable/410)

Usage:
    python orchestrator/fetch_agentic_rows.py --model "Kimi-K3" --id 439932 -o .work/agentic
"""

import argparse
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API_BASE = "https://inferencex.semianalysis.com/api/v1"
AGENTIC_TYPE = "agentic_traces"


def _get(url: str, timeout: int = 60) -> bytes:
    """GET url, returning decoded bytes. The API gzips SOME responses unpredictably (e.g.
    DeepSeek-V4-Pro comes back gzipped, Kimi-K3 plain), and urllib does not auto-decompress,
    so we ask for identity and still gunzip defensively if a gzip stream slips through --
    otherwise json.loads chokes on the 0x1f 0x8b header."""
    req = urllib.request.Request(url, headers={"Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed host)
        data = resp.read()
    if data[:2] == b"\x1f\x8b" or resp.headers.get("Content-Encoding") == "gzip":
        import gzip
        data = gzip.decompress(data)
    return data


def fetch_rows(model_display: str) -> list[dict]:
    """Every benchmark row for a model DISPLAY name (e.g. 'Kimi-K3'), verbatim.

    The `model` query parameter is the display name, not the internal slug: a slug or an
    unknown name returns {"error": "Unknown model"} rather than rows.
    """
    url = f"{API_BASE}/benchmarks?model={urllib.parse.quote(model_display)}"
    body = _get(url)
    doc = json.loads(body)
    if isinstance(doc, dict) and "error" in doc:
        raise SystemExit(f"API error for model {model_display!r}: {doc['error']} "
                         f"(the model param is the DISPLAY name, not the slug)")
    if not isinstance(doc, list):
        raise SystemExit(f"unexpected /benchmarks response shape: {type(doc).__name__}")
    return doc


def fetch_server_log(row_id: str) -> str:
    """The server log text for a row id, or '' if the API has none."""
    body = _get(f"{API_BASE}/server-log?id={row_id}")
    doc = json.loads(body)
    return doc.get("serverLog", "") or ""


def fetch_job_log(run_url: str) -> tuple[str, str | None]:
    """The CI job log behind a run_url via `gh`, and a note if it could not be read.

    Returns (text, note). A non-None note (e.g. the log expired -> HTTP 410, or gh is not
    authenticated) means the text is empty and the caller must treat the single-turn-style
    client settings as unreadable -- never defaulted. Agentic replay args come from the
    server log + the job log's aiperf command, so a missing job log is a real gap.
    """
    # run_url looks like https://github.com/<org>/<repo>/actions/runs/<id>[/attempts/N].
    # `gh run view --log` wants the numeric run id and the repo.
    try:
        parts = run_url.rstrip("/").split("/")
        i = parts.index("runs")
        run_id = parts[i + 1]
        repo = "/".join(parts[parts.index("github.com") + 1: parts.index("actions")])
    except (ValueError, IndexError):
        return "", f"could not parse a run id/repo from run_url {run_url!r}"
    try:
        out = subprocess.run(
            ["gh", "run", "view", run_id, "--repo", repo, "--log"],
            capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        return "", "gh CLI not found on PATH (needed to read the CI job log)"
    if out.returncode != 0:
        err = (out.stderr or "").strip()
        return "", f"gh run view failed (run {run_id}, {repo}): {err[:200]}"
    return out.stdout, None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="model DISPLAY name, e.g. 'Kimi-K3'")
    ap.add_argument("--id", required=True, help="the agentic_traces row id to fetch")
    ap.add_argument("-o", "--out", required=True, help="output directory")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = fetch_rows(args.model)
    row = next((r for r in rows if str(r.get("id")) == str(args.id)), None)
    if row is None:
        ids = [str(r.get("id")) for r in rows if r.get("benchmark_type") == AGENTIC_TYPE]
        raise SystemExit(f"row id {args.id} not found for {args.model!r}; "
                         f"agentic ids available: {ids[:20]}")
    if row.get("benchmark_type") != AGENTIC_TYPE:
        raise SystemExit(f"row {args.id} is benchmark_type {row.get('benchmark_type')!r}, "
                         f"not {AGENTIC_TYPE} -- this fetcher is for agentic rows")

    (out / f"row-{args.id}.json").write_text(json.dumps(row, indent=2) + "\n")

    server_log = fetch_server_log(args.id)
    (out / f"server-{args.id}.log").write_text(server_log)

    job_log, note = fetch_job_log(row.get("run_url", ""))
    (out / f"job-{args.id}.log").write_text(job_log)

    print(f"row-{args.id}.json       ({len(json.dumps(row))} bytes)")
    print(f"server-{args.id}.log     ({len(server_log)} bytes)")
    if note:
        print(f"job-{args.id}.log        UNAVAILABLE: {note}", file=sys.stderr)
    else:
        print(f"job-{args.id}.log        ({len(job_log)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
