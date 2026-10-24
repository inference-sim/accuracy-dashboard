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
    # Incremental: extend a prior frozen pull. A point's measurement is immutable, so one already
    # frozen is reused verbatim (files + manifest entry), only fresh rows are fetched, and aged-out
    # points leave the store. A cold pull (no --prior, or --prior == --out) freezes every row.
    prior_manifest = pl.load_prior_manifest(Path(a.prior)) if a.prior else None
    prior_points = prior_manifest["points"] if prior_manifest else []
    inc = pl.plan_incremental(p.rows, prior_points)
    prior_dir = Path(a.prior) if a.prior else out
    _log(f"pull: reuse {len(inc.reuse)} frozen, freeze {len(inc.fresh)} fresh, drop {len(inc.dropped)} aged-out")
    token = clients.require_github_token()
    resolver = build.Resolver(registry=clients.DockerHubRegistry(), github=clients.GitHubREST(token))
    gh = art.GitHubArtifacts(pl.IX_REPO, token, Path(a.cache or out / "_artifacts"))
    recipes = rcp.GitHubRecipes(clients.GitHubREST(token)._get, pl.IX_REPO)
    run_artifacts: dict = {}
    points = []
    # Reused points: carry over the manifest entry and copy the frozen files (unless out IS prior).
    for pid, e in sorted(inc.reuse.items()):
        if prior_dir != out:
            src = prior_dir / "points" / pid
            if src.exists():
                shutil.copytree(src, out / "points" / pid, dirs_exist_ok=True)
        points.append(e)
    for i, row in enumerate(inc.fresh, 1):
        try:
            e = pl.freeze_point(row, resolver=resolver, gh=gh, fetch=api.http_fetch, out=out,
                                run_artifacts=run_artifacts, recipes=recipes)
        except Exception as ex:  # noqa: BLE001 -- one row's failure is recorded with why, never kills the pull
            if isinstance(ex, (clients.RateLimited, clients.FetchFailed)):
                raise   # the whole pull is invalid, not this row: stop rather than record noise
            ident = pl.identity(row)
            e = {"point_id": contract.point_id(ident), "identity": ident, "row": row, "files": {},
                 "build": None, "reasons": [PULL_ERROR], "problems": [repr(ex)[:500]]}
        points.append(e)
        _log(f"  [{i}/{len(inc.fresh)}] {row['model']} {row['hardware']} c{row['conc']} -> {e['reasons'] or 'ok'}")
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
    """One night of the API-ingest pipeline (Discussion #15): pull the window into the store
    incrementally, decide from the trigger table, score the window (cached), and publish -- the
    live view always, a frozen snapshot on a BLIS release. Composes `cmd_pull`/`cmd_score` and
    build_summary_v2 as the closures nightly_run.run_night orchestrates and unit-tests with fakes;
    this wires the real ones. Resolve the BLIS tag outside (resolve_inputs.sh) and pass it in."""
    import types
    import nightly_run as nr
    sys.path.insert(0, str(HERE.parent))
    import build_summary_v2 as bsv2  # noqa: E402

    today = date.fromisoformat(a.today) if a.today else date.today()
    store_dir, data_dir, state_path = Path(a.store_dir), Path(a.data_dir), Path(a.state)
    contract_dir = Path(a.work or data_dir.parent / "_contract")

    def pull_fn(store: Path, today_: date) -> str:
        # Incremental, in place: the store is its own prior, so frozen points are kept, only new
        # rows are fetched, and aged-out points' files are pruned.
        rc = cmd_pull(types.SimpleNamespace(out=str(store), today=today_.isoformat(),
                                            window_days=a.window_days, cache=a.cache, prior=str(store)))
        if rc != 0:
            raise RuntimeError(f"pull failed (rc={rc}); the run stops rather than publish a partial pull")
        return json.loads((store / "manifest.json").read_text())["pulled_at"][:10]

    def score_build_fn(store: Path, blis_tag: str, score_ids, pull_date: str):
        rc = cmd_score(types.SimpleNamespace(
            pull=str(store), out=str(contract_dir), blis_dir=a.blis_dir, catalog=a.catalog,
            registry=a.registry, defaults_helper=a.defaults_helper, corpus=a.corpus,
            corpus_sha256=a.corpus_sha256, corpus_dataset=a.corpus_dataset,
            corpus_revision=a.corpus_revision, corpus_cache=a.corpus_cache, work=a.score_work,
            timeout=a.timeout, only=None))
        if rc != 0:
            raise RuntimeError(f"score failed (rc={rc})")
        summary = bsv2.build(contract_dir, generated_at=f"{a.today or today.isoformat()}T00:00:00Z",
                             evaluator_commit=a.evaluator_commit or "local")
        return summary, summary["coverage"]["scored"]

    res = nr.run_night(today, a.blis_tag, store_dir=store_dir, data_dir=data_dir, state_path=state_path,
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

    n = sub.add_parser("nightly", help="one night: pull (incremental) -> decide -> score -> publish")
    n.add_argument("--blis-tag", required=True, help="the stable inference-sim tag resolve_inputs.sh resolved")
    n.add_argument("--store-dir", required=True, help="the ix-store working tree (the frozen pull)")
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

    a = ap.parse_args(argv)
    return {"pull": cmd_pull, "score": cmd_score, "nightly": cmd_nightly}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
