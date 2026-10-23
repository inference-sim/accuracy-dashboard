#!/usr/bin/env python3
"""InferenceX API ingest -> BLIS scoring -> contract directory (Discussion #28, issue #29).

  cli.py pull  --window-days N --out PULL [--today YYYY-MM-DD] [--cache DIR]
      Pull the API, resolve builds, join and freeze artifacts. Network: InferenceX API,
      GitHub (artifacts + vllm-project/vllm), Docker Hub, HuggingFace (base_model only).

  cli.py score --pull PULL --out CONTRACT --blis-dir SIM --catalog CAT --registry REG
               --corpus FILE [--work DIR] [--only PID ...]
      Score a frozen pull with one BLIS release. No network.

Nothing in the nightly pipeline calls this. Run by path, like the other orchestrator scripts.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import api  # noqa: E402
import artifacts as art  # noqa: E402
import build  # noqa: E402
import clients  # noqa: E402
import contract  # noqa: E402
import pull as pl  # noqa: E402
import recipes as rcp  # noqa: E402
import score as sc  # noqa: E402
import settings as st  # noqa: E402
import support as sp  # noqa: E402


def _log(msg: str):
    print(msg, file=sys.stderr, flush=True)


def cmd_pull(a) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    today = date.fromisoformat(a.today) if a.today else date.today()
    p = api.pull(api.http_fetch, today=today, window_days=a.window_days)
    _log(f"pull: {len(p.rows)} vllm rows in {p.window}; slugs with no site name: {p.unnamed_slugs}; "
         f"rows with an unreadable date: {len(p.undated)}")
    if p.unnamed_slugs:
        # /benchmarks takes display names, so these models' rows can't be listed at all. Fail
        # rather than publish a pull that silently lacks a model.
        _log("FATAL: the site names no display name for " + ", ".join(p.unnamed_slugs))
        return 3
    token = clients._github_token()
    resolver = build.Resolver(registry=clients.DockerHubRegistry(), github=clients.GitHubREST(token))
    gh = art.GitHubArtifacts(pl.IX_REPO, token, Path(a.cache or out / "_artifacts"))
    recipes = rcp.GitHubRecipes(clients.GitHubREST(token)._get, pl.IX_REPO)
    run_artifacts: dict = {}
    points = []
    for i, row in enumerate(p.rows, 1):
        try:
            e = pl.freeze_point(row, resolver=resolver, gh=gh, fetch=api.http_fetch, out=out,
                                run_artifacts=run_artifacts, recipes=recipes)
        except (OSError, ValueError, KeyError, urllib.error.URLError) as ex:  # recorded, not lost
            ident = pl.identity(row)
            e = {"point_id": contract.point_id(ident), "identity": ident, "row": row, "files": {},
                 "build": None, "reasons": ["artifact_unmatched:pull_error"], "problems": [repr(ex)[:500]]}
        points.append(e)
        _log(f"  [{i}/{len(p.rows)}] {row['model']} {row['hardware']} c{row['conc']} -> {e['reasons'] or 'ok'}")
    # The served checkpoints' HF base_model, frozen here so scoring needs no network.
    base = {}
    for e in points:
        for f in ("launch_config",):
            if f in e["files"]:
                cfg = json.loads(sc._read(out / "points" / e["point_id"], e["files"], f))
                r = sp.hf_repo((cfg.get("model") or {}).get("path"))
                if r:
                    base.setdefault(r, None)
        for v in (e["row"].get("model"),):
            pass
    for e in points:
        if (e.get("checkpoint") or {}).get("repo"):
            base.setdefault(e["checkpoint"]["repo"], None)
        b = sc._read(out / "points" / e["point_id"], e["files"], "server_log")
        if b:
            rd = st.read_args(b.decode("utf-8", "replace"))
            for k in ("served_model_name", "model"):
                for v in rd.values.get(k, []):
                    for x in (v if isinstance(v, list) else [v]):
                        r = sp.hf_repo(x)
                        if r:
                            base.setdefault(r, None)
    for repo in sorted(base):
        try:
            doc = api.decode(api.http_fetch(f"https://huggingface.co/api/models/{repo}"))
            bm = (doc.get("cardData") or {}).get("base_model")
            base[repo] = (bm[0] if isinstance(bm, list) and len(bm) == 1 else bm if isinstance(bm, str) else None)
        except urllib.error.HTTPError as e:
            # A repo HF doesn't know is "no base_model"; any other failure is recorded as one,
            # and scoring turns it into a reason rather than a silent catalog miss.
            base[repo] = None if e.code == 404 else {"lookup_failed": f"HTTP {e.code}"}
        except urllib.error.URLError as e:
            base[repo] = {"lookup_failed": str(e.reason)[:200]}
    meta = {"window": list(p.window), "pulled_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "vllm_ref": build.VLLM_REF, "vllm_max_distance": build.VLLM_MAX_DISTANCE,
            "unnamed_slugs": p.unnamed_slugs, "base_models": base,
            "undated_row_ids": sorted(str(r["id"]) for r in p.undated)}
    sha = pl.write_manifest(out, meta, points)
    _log(f"pull: wrote {out / 'manifest.json'} (sha256 {sha})")
    return 0


def _git(dirpath, *args) -> str:
    return subprocess.run(["git", "-C", str(dirpath), *args], capture_output=True, text=True).stdout.strip()


def cmd_score(a) -> int:
    pull_dir = Path(a.pull)
    manifest_text = (pull_dir / "manifest.json").read_text()
    manifest = json.loads(manifest_text)
    sim = Path(a.blis_dir)
    policy, policy_sha = st.load_policy()
    vdefaults, vdefaults_sha = st.load_vllm_defaults()
    corpus_path = Path(a.corpus)
    corpus_sha = a.corpus_sha256 or art.sha256(corpus_path.read_bytes())
    env = sc.Env(
        blis=str(sim / "blis"), blis_release=_git(sim, "describe", "--tags", "--exact-match") or "unknown",
        blis_commit=_git(sim, "rev-parse", "HEAD"), catalog=Path(a.catalog),
        catalog_release=_git(a.catalog, "describe", "--tags") or "unknown", registry=Path(a.registry),
        registry_release=_git(a.registry, "describe", "--tags") or "unknown",
        kernel=next((l.split()[1] for l in (sim / "go.mod").read_text().splitlines()
                     if "blis-latency-kernel " in l), "unknown"),
        defaults_helper=a.defaults_helper,
        corpus={"dataset": a.corpus_dataset, "revision": a.corpus_revision, "sha256": corpus_sha,
                "path": str(corpus_path), "file": corpus_path.name},
        corpus_cache=Path(a.corpus_cache) if a.corpus_cache else None,
        vllm_ref=manifest["vllm_ref"], policy=policy, policy_sha256=policy_sha,
        base_models=manifest.get("base_models") or {}, timeout_s=a.timeout,
        vllm_defaults=vdefaults, vllm_defaults_sha256=vdefaults_sha)
    env.signedprobe = str(sim / "signedprobe")
    wl = json.loads((sim / "testdata" / "inferencex-workloads" / "seed0.json").read_text())
    env.single_turn_workloads = {(p["isl"], p["osl"], p["concurrency"]) for p in wl["points"]}
    env.catalog_obj = sp.Catalog.load(env.catalog)
    env.parts = sp.registry_parts(env.registry)
    work = Path(a.work or Path(a.out).parent / (Path(a.out).name + "-work"))
    work.mkdir(parents=True, exist_ok=True)
    points = manifest["points"]
    if a.only:
        points = [p for p in points if any(p["point_id"].startswith(x) for x in a.only)]
    outcomes = []
    for i, e in enumerate(points, 1):
        try:
            o = sc.score_point(e, pull_dir, work, env)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as ex:
            # One point that can't be scored is recorded with why, never dropped.
            o = sc.Outcome(point_id=e["point_id"], identity=e["identity"], row=e["row"],
                           reasons=sorted(set(e["reasons"] + ["blis_refused:extractor_error"])))
            _log(f"    extractor error on {e['point_id'][:12]}: {ex!r}"[:400])
        outcomes.append(o)
        _log(f"  [{i}/{len(points)}] {e['row']['model']} {e['row']['hardware']} c{e['row']['conc']} "
             f"{e['point_id'][:12]} -> {o.fidelity['status'] if o.fidelity else o.reasons}")
    prov = {"ingest": "api",
            "blis": {"release": env.blis_release, "commit_sha": env.blis_commit, "catalog": env.catalog_release,
                     "registry": env.registry_release, "extractor_version": f"blis-latency-kernel@{env.kernel}"},
            "vllm_ref": manifest["vllm_ref"], "vllm_max_distance": manifest["vllm_max_distance"],
            "policy_sha256": art.sha256((policy_sha + vdefaults_sha).encode()), "pulled_at": manifest["pulled_at"],
            "corpus": {"dataset": env.corpus["dataset"], "revision": env.corpus["revision"], "sha256": corpus_sha},
            "pull_manifest_sha256": art.sha256(manifest_text.encode()), "_policy": policy}
    sc.write_contract(Path(a.out), outcomes, prov)
    problems = contract.validate_dir(a.out)
    for p in problems:
        _log(f"INVALID: {p}")
    scored = sum(1 for o in outcomes if o.fidelity)
    _log(f"score: {scored} scored, {len(outcomes) - scored} not scored -> {a.out}")
    return 1 if problems else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pull")
    p.add_argument("--window-days", type=int, required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--today")
    p.add_argument("--cache")
    s = sub.add_parser("score")
    s.add_argument("--pull", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--blis-dir", required=True,
                   help="an inference-sim checkout with blis and signedprobe built in it")
    s.add_argument("--catalog", required=True)
    s.add_argument("--registry", required=True)
    s.add_argument("--defaults-helper", required=True, help="orchestrator/blisdefaults built against --blis-dir's tag")
    s.add_argument("--corpus", required=True)
    s.add_argument("--corpus-sha256")
    s.add_argument("--corpus-dataset", default="semianalysisai/cc-traces-weka-062126")
    s.add_argument("--corpus-revision", required=True)
    s.add_argument("--corpus-cache")
    s.add_argument("--work")
    s.add_argument("--timeout", type=int, default=7200)
    s.add_argument("--only", nargs="*")
    a = ap.parse_args(argv)
    return cmd_pull(a) if a.cmd == "pull" else cmd_score(a)


if __name__ == "__main__":
    sys.exit(main())
