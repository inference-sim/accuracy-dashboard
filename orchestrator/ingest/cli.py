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


# A row whose pull raised something unexpected (a bug, not the data): never scored as a gap.
PULL_ERROR = "artifact_unmatched:pull_error"


def cmd_pull(a) -> int:
    import shutil
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
    # --only <point_id ...>: freeze just these window rows (the nightly's delta fetch). The manifest
    # then holds only the fetched subset; the whole window is listed by the caller, not here.
    if getattr(a, "only", None):
        want = set(a.only)
        p.rows = [r for r in p.rows if contract.point_id(pl.identity(r)) in want]
        _log(f"pull: --only -> {len(p.rows)} of the window's rows")
    # Incremental: extend a prior frozen pull. A point's measurement is immutable, so one already
    # frozen is reused verbatim (files + manifest entry), only fresh rows are fetched, and aged-out
    # points leave the store. A cold pull (no --prior, or --prior == --out) freezes every row.
    prior_manifest = pl.load_prior_manifest(Path(a.prior)) if a.prior else None
    prior_points = prior_manifest["points"] if prior_manifest else []
    if any(PULL_ERROR in (e.get("reasons") or []) for e in prior_points):
        # A prior manifest that still carries a pull error was never a clean window; reusing its
        # entries would re-raise the error (and wedge) every night. Start cold instead.
        _log("pull: prior manifest holds a pull error -- ignoring it and pulling cold")
        prior_manifest, prior_points = None, []
    inc = pl.plan_incremental(p.rows, prior_points)
    prior_dir = Path(a.prior) if a.prior else out
    _log(f"pull: reuse {len(inc.reuse)} frozen, freeze {len(inc.fresh)} fresh, drop {len(inc.dropped)} aged-out")
    token = clients.require_github_token()
    resolver = build.Resolver(registry=clients.DockerHubRegistry(), github=clients.GitHubREST(token))
    gh = art.GitHubArtifacts(pl.IX_REPO, token, Path(a.cache or out / "_artifacts"))
    recipes = rcp.GitHubRecipes(clients.GitHubREST(token)._get, pl.IX_REPO)
    points = []
    # Reused points: carry over the manifest entry and copy the frozen files (unless out IS prior).
    for pid, e in sorted(inc.reuse.items()):
        if prior_dir != out:
            src = prior_dir / "points" / pid
            if src.exists():
                shutil.copytree(src, out / "points" / pid, dirs_exist_ok=True)
        points.append(e)
    # Freeze fresh rows across a thread pool: downloads are I/O-bound (network wait), so workers
    # mostly block on sockets -- the pool can exceed the core count, but is bounded so it doesn't
    # trip GitHub's rate limits (the existing 5xx/429 backoff still applies per request). A fatal
    # RateLimited/FetchFailed from any worker aborts the whole pull; a per-row error is recorded.
    import os
    from concurrent.futures import ThreadPoolExecutor, as_completed
    dl_workers = a.download_workers if getattr(a, "download_workers", 0) else min((os.cpu_count() or 4) * 2, 8)

    def _freeze(row):
        try:
            return row, pl.freeze_point(row, resolver=resolver, gh=gh, fetch=api.http_fetch, out=out,
                                        recipes=recipes), None
        except (clients.RateLimited, clients.FetchFailed):
            raise   # the whole pull is invalid, not this row
        except Exception as ex:  # noqa: BLE001 -- one row's failure is recorded with why, never kills the pull
            ident = pl.identity(row)
            return row, {"point_id": contract.point_id(ident), "identity": ident, "row": row, "files": {},
                         "build": None, "reasons": [PULL_ERROR], "problems": [repr(ex)[:500]]}, ex

    fresh_results = {}
    if dl_workers <= 1 or len(inc.fresh) <= 1:
        for row in inc.fresh:
            r, e, _ = _freeze(row)
            fresh_results[contract.point_id(pl.identity(r))] = e
    else:
        _log(f"pull: freezing {len(inc.fresh)} rows on {dl_workers} download workers")
        with ThreadPoolExecutor(max_workers=dl_workers) as ex:
            futs = {ex.submit(_freeze, row): row for row in inc.fresh}
            done = 0
            for fut in as_completed(futs):
                r, e, _ = fut.result()   # a fatal RateLimited/FetchFailed propagates here, aborting
                fresh_results[contract.point_id(pl.identity(r))] = e
                done += 1
                _log(f"  [{done}/{len(inc.fresh)}] {r['model']} {r['hardware']} c{r['conc']} -> {e['reasons'] or 'ok'}")
    # Append in the pull's stable order (by the fresh list), so the manifest is order-stable.
    for row in inc.fresh:
        points.append(fresh_results[contract.point_id(pl.identity(row))])
    # Aged-out points: drop their files so the store holds only the current window.
    for pid in sorted(inc.dropped):
        pl.prune_point_files(out, pid)
    # The served checkpoints' HF base_model, frozen here so scoring needs no network.
    base = {}
    for e in points:
        for f in ("launch_config",):
            if f in e["files"]:
                cfg = json.loads(sc._read(out / "points" / e["point_id"], e["files"], f))
                r = sp.hf_repo((cfg.get("model") or {}).get("path"))
                if r:
                    base.setdefault(r, None)
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
    # Reuse a prior pull's base_model lookups for repos it already resolved: a base_model is a
    # fact about the checkpoint, not about when it was pulled, so an incremental night needn't
    # re-fetch HuggingFace for a repo it saw last night. Only genuinely new repos are looked up.
    prior_base = (prior_manifest or {}).get("base_models") or {}
    for repo in sorted(base):
        if repo in prior_base:
            base[repo] = prior_base[repo]
            continue
        try:
            doc = api.decode(api.http_fetch(f"https://huggingface.co/api/models/{repo}"))
            bm = (doc.get("cardData") or {}).get("base_model")
            base[repo] = (bm[0] if isinstance(bm, list) and len(bm) == 1 else bm if isinstance(bm, str) else None)
        except urllib.error.HTTPError as e:
            # A repo HF doesn't know is "no base_model"; another refusal (a gated repo) is
            # recorded, and scoring turns it into a reason rather than a silent catalog miss. An
            # outage outlasting the retries raises FetchFailed and stops the pull.
            base[repo] = None if e.code == 404 else {"lookup_failed": f"HTTP {e.code}"}
    meta = {"window": list(p.window), "pulled_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "vllm_ref": build.VLLM_REF, "vllm_max_distance": build.VLLM_MAX_DISTANCE,
            "unnamed_slugs": p.unnamed_slugs, "base_models": base,
            "undated_row_ids": sorted(str(r["id"]) for r in p.undated)}
    sha = pl.write_manifest(out, meta, points)
    _log(f"pull: wrote {out / 'manifest.json'} (sha256 {sha})")
    failed = [e for e in points if PULL_ERROR in e["reasons"]]
    if failed:
        # A row the pull itself couldn't read isn't a fact about the data: the run fails, and
        # `score` refuses the manifest, rather than publish a quietly smaller one.
        for e in failed:
            _log(f"  pull error {e['point_id'][:12]}: {e['problems'][0]}")
        _log(f"FATAL: {len(failed)} row(s) failed in the pull itself")
        return 4
    return 0


def _git(dirpath, *args) -> str:
    return subprocess.run(["git", "-C", str(dirpath), *args], capture_output=True, text=True).stdout.strip()


def _go_require(gomod: Path, module: str) -> str | None:
    """The version `gomod` requires of a module (`<module> vX.Y.Z` on a require line)."""
    for line in gomod.read_text().splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0] == module:
            return parts[1]
    return None


def check_blis_inputs(sim: Path, helper: str, catalog: Path, registry: Path) -> list[str]:
    """Everything `score` needs to be one BLIS release, or what's wrong. The defaults helper is
    built against an inference-sim tag; it must be --blis-dir's, with the same kernel and
    schemas, or its defaults / resolutions / acceptance would come from another release. The
    releases recorded in provenance must be real tags, never "unknown"."""
    out = []
    tag = _git(sim, "describe", "--tags", "--exact-match")
    if not tag:
        out.append(f"--blis-dir {sim} is not at a release tag (fetch tags, or check out the tag)")
    for f in ("blis", "signedprobe", "testdata/inferencex-workloads/seed0.json"):
        if not (sim / f).exists():
            out.append(f"--blis-dir {sim} has no {f} (build blis and signedprobe in it)")
    for repo, flag in ((catalog, "--catalog"), (registry, "--registry")):
        if not _git(repo, "describe", "--tags", "--exact-match"):
            out.append(f"{flag} {repo} is not at a release tag")
    try:
        got = json.loads(subprocess.run([helper, "-version"], capture_output=True, text=True,
                                        check=True, timeout=60).stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return out + [f"--defaults-helper {helper} doesn't report its versions ({e})"]
    want = {"inference-sim": tag,
            "blis-latency-kernel": _go_require(sim / "go.mod", "github.com/inference-sim/blis-latency-kernel"),
            "blis-schemas": _go_require(sim / "go.mod", "github.com/inference-sim/blis-schemas")}
    for mod, v in want.items():
        if v and got.get(mod) not in (v, "(devel)"):
            out.append(f"--defaults-helper is built against {mod} {got.get(mod)}, --blis-dir is {v}")
    return out


def cmd_score(a) -> int:
    pull_dir = Path(a.pull)
    bad = check_blis_inputs(Path(a.blis_dir), a.defaults_helper, Path(a.catalog), Path(a.registry))
    if bad:
        for b in bad:
            _log(f"FATAL: {b}")
        return 2
    manifest_text = (pull_dir / "manifest.json").read_text()
    manifest = json.loads(manifest_text)
    failed = [e["point_id"][:12] for e in manifest["points"] if PULL_ERROR in e["reasons"]]
    if failed:
        _log(f"FATAL: the pull has {len(failed)} row(s) it failed to read ({', '.join(failed[:5])}); re-run the pull")
        return 2
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
    # Score serially or across a process pool. BLIS replays are CPU-bound subprocesses, so the
    # worker count is clamped to the machine's cores (4 on an ubuntu-latest runner) -- more would
    # just thrash. The contract is re-sorted by point_id in write_contract, so the output is
    # identical whatever the worker count; parallelism is only a speed knob.
    import os
    workers = a.workers if a.workers and a.workers > 0 else min(os.cpu_count() or 1, 4)
    _log(f"score: {len(points)} points on {workers} worker(s)")
    outcomes = sc.score_points(points, pull_dir, work, env, workers=workers, log=_log)
    prov = {"ingest": "api",
            "blis": {"release": env.blis_release, "commit_sha": env.blis_commit, "catalog": env.catalog_release,
                     "registry": env.registry_release, "extractor_version": f"blis-latency-kernel@{env.kernel}"},
            "vllm_ref": manifest["vllm_ref"], "vllm_max_distance": manifest["vllm_max_distance"],
            "policy_sha256": art.sha256((policy_sha + vdefaults_sha).encode()), "pulled_at": manifest["pulled_at"],
            "corpus": {"dataset": env.corpus["dataset"], "revision": env.corpus["revision"], "sha256": corpus_sha},
            "pull_manifest_sha256": art.sha256(manifest_text.encode()),
            "source": {"name": "SemiAnalysis InferenceX API", "url": api.API + "/"}, "_policy": policy}
    sc.write_contract(Path(a.out), outcomes, prov)
    problems = contract.validate_dir(a.out)
    for p in problems:
        _log(f"INVALID: {p}")
    scored = sum(1 for o in outcomes if o.fidelity)
    _log(f"score: {scored} scored, {len(outcomes) - scored} not scored -> {a.out}")
    return 1 if problems else 0


def cmd_nightly(a) -> int:
    """One night of the no-storage API-ingest pipeline (Discussion #15, revised 2026-10-25):
    list the 180-day window, fetch+score only the delta (or the whole window on a BLIS release),
    merge into last night's published summary, and publish. Nothing raw is persisted -- the work
    dir is ephemeral and summary.json IS the score store. Wires the real pull/score/build as the
    closures nightly_run.run_night orchestrates (and unit-tests with fakes). Resolve the BLIS tag
    outside and pass it in."""
    import types
    import nightly_run as nr
    sys.path.insert(0, str(HERE.parent))
    import build_summary_v2 as bsv2  # noqa: E402

    today = date.fromisoformat(a.today) if a.today else date.today()
    work_dir, data_dir, state_path = Path(a.work_dir), Path(a.data_dir), Path(a.state)
    contract_dir = Path(a.work or data_dir.parent / "_contract")
    latest_path = data_dir / "latest" / "summary.json"

    def pull_fn(work: Path, today_: date, last_ids: set, blis_changed: bool):
        # List the whole window (cheap -- api.pull hits only the REST API, no artifacts), then fetch
        # inputs for the points to score. The whole window is fetched on a BLIS release AND on the
        # seed (no prior ids); otherwise only the new points. A row the pull itself can't read fails
        # the run (cmd_pull returns non-zero).
        p = api.pull(api.http_fetch, today=today_, window_days=a.window_days)
        window_ids = {contract.point_id(pl.identity(r)) for r in p.rows}
        whole = blis_changed or not last_ids
        to_fetch = window_ids if whole else (window_ids - set(last_ids))
        only = None if whole else sorted(to_fetch)
        _log(f"nightly: window {len(window_ids)} points; fetch {'whole window' if whole else f'{len(to_fetch)} new'}")
        rc = cmd_pull(types.SimpleNamespace(out=str(work), today=today_.isoformat(),
                                            window_days=a.window_days, cache=a.cache, prior=None,
                                            only=only, download_workers=a.download_workers))
        if rc != 0:
            raise RuntimeError(f"pull failed (rc={rc}); the run stops rather than publish a partial pull")
        return json.loads((work / "manifest.json").read_text())["pulled_at"][:10], window_ids

    def score_build_fn(work: Path, blis_tag: str, score_ids, pull_date: str, window_ids: set):
        rc = cmd_score(types.SimpleNamespace(
            pull=str(work), out=str(contract_dir), blis_dir=a.blis_dir, catalog=a.catalog,
            registry=a.registry, defaults_helper=a.defaults_helper, corpus=a.corpus,
            corpus_sha256=a.corpus_sha256, corpus_dataset=a.corpus_dataset,
            corpus_revision=a.corpus_revision, corpus_cache=a.corpus_cache, work=a.score_work,
            timeout=a.timeout, only=None, workers=a.workers))
        if rc != 0:
            raise RuntimeError(f"score failed (rc={rc})")
        prov = json.loads((contract_dir / contract.PROVENANCE_JSON).read_text())
        gen_at = prov["pulled_at"]
        prior = json.loads(latest_path.read_text()) if latest_path.is_file() else None
        # IX-only night: merge the delta contract into last night's published summary (summary.json
        # IS the store). A BLIS release (or the seed) rebuilds the whole window from the contract.
        if prior and prior.get("provenance", {}).get("blis", {}).get("release") == blis_tag:
            summary = bsv2.build_merged(prior, contract_dir, window_ids, generated_at=gen_at,
                                        evaluator_commit=a.evaluator_commit or "local",
                                        work=Path(a.score_work or contract_dir.parent) / "merge")
        else:
            summary = bsv2.build(contract_dir, generated_at=gen_at, evaluator_commit=a.evaluator_commit or "local")
        return summary, summary["coverage"]["scored"]

    res = nr.run_night(today, a.blis_tag, work_dir=work_dir, data_dir=data_dir, state_path=state_path,
                       pull_fn=pull_fn, score_build_fn=score_build_fn,
                       snapshot_date=a.today or today.isoformat(), keep_api=a.keep_api)
    _log(f"nightly: {res.action} -- {res.decision.reason}")
    if res.snapshot_id:
        _log(f"nightly: froze snapshot {res.snapshot_id}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pull")
    p.add_argument("--window-days", type=int, required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--today")
    p.add_argument("--cache")
    p.add_argument("--prior", help="a prior frozen pull to extend: reuse its frozen points, freeze "
                                   "only new rows, drop aged-out ones. Omit for a cold pull.")
    p.add_argument("--only", nargs="*", help="freeze only these point_ids of the window (the nightly's delta fetch)")
    p.add_argument("--download-workers", type=int, default=0,
                   help="parallel artifact-download workers (default: min(2*cores, 8); I/O-bound)")
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
    s.add_argument("--workers", type=int, default=0,
                   help="score this many points in parallel (default: min(cores, 4); CPU-bound, don't exceed cores)")

    n = sub.add_parser("nightly", help="one night: list window -> fetch+score delta -> merge -> publish")
    n.add_argument("--blis-tag", required=True, help="the stable inference-sim tag resolve_blis.sh resolved")
    n.add_argument("--work-dir", required=True, help="ephemeral dir for this night's pull (never persisted)")
    n.add_argument("--data-dir", required=True, help="the published data tree (latest/, snapshots/, index.json)")
    n.add_argument("--state", required=True, help="state/last-run.json for the API pipeline")
    n.add_argument("--window-days", type=int, default=180)
    n.add_argument("--keep-api", type=int, default=5)
    n.add_argument("--today")
    n.add_argument("--cache")
    n.add_argument("--work", help="the contract directory the scored window is written to")
    n.add_argument("--score-work")
    n.add_argument("--evaluator-commit")
    n.add_argument("--blis-dir", required=True)
    n.add_argument("--catalog", required=True)
    n.add_argument("--registry", required=True)
    n.add_argument("--defaults-helper", required=True)
    n.add_argument("--corpus", required=True)
    n.add_argument("--corpus-sha256")
    n.add_argument("--corpus-dataset", default="semianalysisai/cc-traces-weka-062126")
    n.add_argument("--corpus-revision", required=True)
    n.add_argument("--corpus-cache")
    n.add_argument("--timeout", type=int, default=7200)
    n.add_argument("--workers", type=int, default=0, help="parallel scoring workers (default: min(cores, 4))")
    n.add_argument("--download-workers", type=int, default=0, help="parallel artifact-download workers (default: min(2*cores, 8))")

    a = ap.parse_args(argv)
    return {"pull": cmd_pull, "score": cmd_score, "nightly": cmd_nightly}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
