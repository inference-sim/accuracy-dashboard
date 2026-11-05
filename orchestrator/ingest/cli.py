#!/usr/bin/env python3
"""InferenceX API ingest -> BLIS scoring -> contract directory (Discussion #28, issue #29).

  cli.py pull  --window-days N --out PULL [--today YYYY-MM-DD] [--cache DIR]
      Pull the API, resolve builds, join and freeze artifacts. Network: InferenceX API,
      GitHub (artifacts + vllm-project/vllm), Docker Hub, HuggingFace (base_model only).

  cli.py score --pull PULL --out CONTRACT --blis BLIS --catalog CAT --registry REG
               [--stack STACK] --corpus FILE [--work DIR] [--only PID ...]
      Score a frozen pull with one BLIS release. No network. The engine's field list is what
      `blis fields --engine vllm --json` prints.

Nothing in the nightly pipeline calls this. Run by path, like the other orchestrator scripts.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import api  # noqa: E402
import artifacts as art  # noqa: E402
import blis_commands as bc  # noqa: E402
import build  # noqa: E402
import clients  # noqa: E402
import contract  # noqa: E402
import engines  # noqa: E402
import fields as fl  # noqa: E402
import ledger as ldg  # noqa: E402
import pull as pl  # noqa: E402
import recipes as rcp  # noqa: E402
import result  # noqa: E402
import score as sc  # noqa: E402
import settings as st  # noqa: E402
import stack as sk  # noqa: E402
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
    _log(f"pull: {len(p.rows)} rows in {p.window}; slugs with no site name: {p.unnamed_slugs}; "
         f"rows with an unreadable date: {len(p.undated)}")
    unknown = engines.unknown_labels(p.rows)
    if unknown:
        _log("FATAL: engines.FRAMEWORKS does not name the framework(s) " + ", ".join(unknown))
        return 3
    if p.unnamed_slugs:
        # /benchmarks takes display names, so these models' rows can't be listed at all. Fail
        # rather than publish a pull that silently lacks a model.
        _log("FATAL: the site names no display name for " + ", ".join(p.unnamed_slugs))
        return 3
    # Every row becomes a point only through the ledger: the point is the row's unit, and
    # records the ledger joins are one point (design §10.2). Rows the ledger holds no unit for
    # are listed with why, in the manifest, and counted in coverage.
    lg = ldg.load(Path(a.ledger))
    placed = pl.place(p.rows, lg)
    pl.check_placed(p.rows, placed)
    _log(f"pull: {len(placed.points)} points (ledger units) from {len(p.rows)} rows; "
         f"{len(placed.unlisted)} rows hold no unit of {lg.revision}")
    points_in = placed.points
    # --only <point_id ...>: freeze just these window points (the nightly's delta fetch). The
    # manifest then holds only the fetched subset; the whole window is listed by the caller, not
    # here. `None` means "the whole window"; an EMPTY list means "none" (a night whose delta is
    # empty -- an age-out or a true no-op) -- never conflate the two, or such a night re-freezes
    # the whole window.
    if getattr(a, "only", None) is not None:
        want = set(a.only)
        points_in = [x for x in points_in if x.point_id in want]
        _log(f"pull: --only -> {len(points_in)} of the window's points")
    # Incremental: extend a prior frozen pull. A point's measurement is immutable, so one already
    # frozen is reused verbatim (files + manifest entry), only fresh points are fetched, and
    # aged-out points leave the store. A cold pull (no --prior, or --prior == --out) freezes
    # every point.
    prior_manifest = pl.load_prior_manifest(Path(a.prior)) if a.prior else None
    prior_points = prior_manifest["points"] if prior_manifest else []
    if any(PULL_ERROR in (e.get("reasons") or []) for e in prior_points):
        # A prior manifest that still carries a pull error was never a clean window; reusing its
        # entries would re-raise the error (and wedge) every night. Start cold instead.
        _log("pull: prior manifest holds a pull error -- ignoring it and pulling cold")
        prior_manifest, prior_points = None, []
    inc = pl.plan_incremental(points_in, prior_points)
    prior_dir = Path(a.prior) if a.prior else out
    _log(f"pull: reuse {len(inc.reuse)} frozen, freeze {len(inc.fresh)} fresh, drop {len(inc.dropped)} aged-out")
    token = clients.require_github_token()
    # The vLLM ref rides the resolved BLIS release: the nightly exports $VLLM_REF from
    # resolve_stack.py (stack.json's vLLM engine release). It anchors the WHOLE build resolver
    # (exact-vs-estimated commit distance) and is stamped into the manifest, so a local run with
    # nothing resolved falls back to build.VLLM_REF. Resolved once here, used in both places.
    import os
    vllm_ref = os.environ.get("VLLM_REF") or build.VLLM_REF
    resolver = build.Resolver(registry=clients.DockerHubRegistry(), github=clients.GitHubREST(token),
                              ref=vllm_ref)
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

    def _freeze(pt):
        try:
            return pt, pl.freeze_point(pt, resolver=resolver, gh=gh, fetch=api.http_fetch, out=out,
                                       recipes=recipes), None
        except (clients.RateLimited, clients.FetchFailed):
            raise   # the whole pull is invalid, not this point
        except Exception as ex:  # noqa: BLE001 -- one point's failure is recorded with why, never kills the pull
            return pt, {"point_id": pt.point_id, "identity": dict(pt.unit.identity), "row": pt.row,
                        "records": pt.records, "measurements": pt.measurements, "files": {},
                        "build": None, "reasons": [PULL_ERROR], "problems": [repr(ex)[:500]]}, ex

    fresh_results = {}
    if dl_workers <= 1 or len(inc.fresh) <= 1:
        for pt in inc.fresh:
            _, e, _ = _freeze(pt)
            fresh_results[pt.point_id] = e
    else:
        _log(f"pull: freezing {len(inc.fresh)} points on {dl_workers} download workers")
        with ThreadPoolExecutor(max_workers=dl_workers) as ex:
            futs = {ex.submit(_freeze, pt): pt for pt in inc.fresh}
            done = 0
            for fut in as_completed(futs):
                pt, e, _ = fut.result()   # a fatal RateLimited/FetchFailed propagates here, aborting
                fresh_results[pt.point_id] = e
                done += 1
                r = pt.row
                _log(f"  [{done}/{len(inc.fresh)}] {r['model']} {r['hardware']} c{r['conc']} -> {e['reasons'] or 'ok'}")
    # Append in the pull's stable order (by the fresh list), so the manifest is order-stable.
    for pt in inc.fresh:
        points.append(fresh_results[pt.point_id])
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
            "vllm_ref": vllm_ref, "vllm_max_distance": build.VLLM_MAX_DISTANCE,
            "unnamed_slugs": p.unnamed_slugs, "base_models": base,
            "undated_row_ids": sorted(str(r["id"]) for r in p.undated),
            "ledger": {"revision": lg.revision, "unlisted": placed.unlisted}}
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


# A simulator tag: vMAJOR.MINOR.PATCH with an optional pre-release suffix, the same set harness/run.sh
# accepts. A release tag has no suffix; a build at a pre-release tag is experimental (design §11.7).
_SIM_TAG = re.compile(r"^v\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")
_RELEASE_TAG = re.compile(r"^v\d+\.\d+\.\d+$")
_SIM_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^(sha256:[0-9a-f]{64}|unreleased)$")


def check_blis_inputs(blis: Path, catalog: Path, registry: Path, sim_build: str | None = None) -> list[str]:
    """Everything `score` needs to name its simulator build, or what's wrong. The blis binary sits
    in the inference-sim checkout it was built from. With --sim-build the checkout must be at that
    build: the release tag, or the 40-hex commit. Without it the checkout must be at a release
    tag, which is the build. The catalog and registry must be at release tags."""
    out = []
    sim = blis.parent
    if not blis.is_file():
        out.append(f"--blis {blis} is not a file (build it: go build -o blis main.go in an inference-sim checkout)")
    tag = _git(sim, "describe", "--tags", "--exact-match")
    if sim_build is None:
        if not tag:
            out.append(f"--blis {blis}: its checkout {sim} is not at a release tag (fetch tags, or check out the tag)")
    elif _SIM_TAG.match(sim_build):
        if tag != sim_build:
            out.append(f"--sim-build {sim_build}: the checkout {sim} is at {tag or 'no release tag'}")
    elif _SIM_COMMIT.match(sim_build):
        head = _git(sim, "rev-parse", "HEAD")
        if head != sim_build:
            out.append(f"--sim-build {sim_build}: the checkout {sim} is at commit {head or 'unknown'}")
    else:
        out.append(f"--sim-build {sim_build!r} is neither a tag vX.Y.Z[-suffix] nor a 40-hex commit")
    for repo, flag in ((catalog, "--catalog"), (registry, "--registry")):
        if not _git(repo, "describe", "--tags", "--exact-match"):
            out.append(f"{flag} {repo} is not at a release tag")
    return out


def check_harness_digest(digest: str | None) -> list[str]:
    """The harness image digest every figure records (design §11.7, X8): sha256:<64 hex>, or
    unreleased for a harness not run from a released image."""
    if digest is None:
        return ["--harness-digest is required: sha256:<64 hex> of the harness image, or unreleased"]
    return [] if _DIGEST.match(digest) else [f"--harness-digest {digest!r} is neither sha256:<64 hex> nor unreleased"]


def select_units(points: list[dict], units_path: str | None) -> tuple[list[dict], dict | None]:
    """The pull's points a --units file names (design §11.7: the harness scores a set of ledger
    units), and the record of the set: its sha256, its size, and the units the pull does not hold.
    With no --units, every point of the pull and None."""
    if units_path is None:
        return points, None
    want = ldg.read_unit_set(Path(units_path))
    held = {p["point_id"] for p in points}
    return ([p for p in points if p["point_id"] in want],
            {"sha256": art.sha256(Path(units_path).read_bytes()), "count": len(want),
             "not_in_pull": sorted(want - held)})


def read_fields(blis: Path, engine_release: str) -> tuple["fl.FieldList", str]:
    """The engine's field list at the release the scoring build runs, and its sha256: what
    `blis fields --engine vllm --json` prints (COV-3). The list must be for the engine release
    stack.json names; one for another release is refused (LIF-6)."""
    raw = bc.fields(str(blis), "vllm")
    field_list = fl.parse(raw)
    if field_list.engine != {"kind": "vllm", "version": engine_release}:
        raise fl.FieldsError(f"blis fields --engine vllm printed the field list of {field_list.engine}, but the "
                             f"simulator runs vllm {engine_release} (stack.json)")
    return field_list, art.sha256(raw)


def read_anchor_units(blis: Path, out: Path) -> set[str]:
    """The anchor units of the substrate release the scoring build pins (COV-2): the list
    `blis ledger --list anchor --json` prints, written to `out` so the score step can name it as
    --units. An empty list is refused: until the ledger's seed exists the release publishes no
    anchor unit, and a night that scored anything else would publish figures on units that may
    fit or select values (X8)."""
    raw = bc.ledger_list(str(blis), "anchor")
    out.write_bytes(raw)
    units = ldg.read_unit_set(out, role="anchor")
    if not units:
        raise ldg.LedgerError("blis ledger --list anchor printed no unit: the substrate release this build pins "
                              "publishes no anchor list yet (the ledger seed is not created), so there is no unit "
                              "the nightly may score (COV-2)")
    return units


def read_stack(blis: Path, given: str | None) -> sk.Stack:
    """The scoring build's stack.json: the engine release it runs (LIF-6) and the modules it pins.

    TEMPORARY until inference-sim v0.16.0, the first release that writes stack.json at its root
    (inference-sim m1/substrate, task H): --stack names the file for a build that does not ship
    one. Without --stack the file is the simulator checkout's own. A build with neither predates
    stack.json and is refused; the engine release is never read from installation.md."""
    path = Path(given) if given else blis.parent / "stack.json"
    if not path.is_file():
        raise sk.StackError(f"{blis.parent} has no stack.json: this simulator build predates stack.json "
                            f"(inference-sim v0.16.0 writes it), so the engine release it runs is not stated; "
                            f"pass --stack FILE")
    return sk.load(path)


def cmd_score(a) -> int:
    pull_dir = Path(a.pull)
    blis = Path(a.blis).resolve()
    sim_build = getattr(a, "sim_build", None)
    bad = check_blis_inputs(blis, Path(a.catalog), Path(a.registry), sim_build)
    bad += check_harness_digest(getattr(a, "harness_digest", None))
    try:
        stack = read_stack(blis, getattr(a, "stack", None))
        engine_release = stack.engine("vllm")
        field_list, fields_sha = read_fields(blis, engine_release)
        # DEV-8: a predicted figure is compared with a measured one only under one definition.
        bad += result.check_definitions(bc.metrics(str(blis)))
    except (sk.StackError, fl.FieldsError, bc.CommandError, OSError, ValueError) as e:
        bad.append(str(e))
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
    sim = blis.parent
    vdefaults, _ = st.load_vllm_defaults()
    work = Path(a.work or Path(a.out).parent / (Path(a.out).name + "-work"))
    work.mkdir(parents=True, exist_ok=True)
    points, units = select_units(manifest["points"], getattr(a, "units", None))
    if units and units["not_in_pull"]:
        _log(f"score: {len(units['not_in_pull'])} of the {units['count']} units named are not in the pull")
    if a.only is not None:  # None = score the whole manifest; [] = score nothing (never "all")
        points = [p for p in points if any(p["point_id"].startswith(x) for x in a.only)]
    # The corpus is read only by an agentic replay, so it is required only when a point to score
    # is agentic. Superseded by --corpus-dir on the corpus branch.
    corpus = None
    if any(p["row"].get("benchmark_type") == "agentic_traces" for p in points):
        if not a.corpus or not a.corpus_revision:
            _log("FATAL: the points to score include an agentic one, so --corpus and --corpus-revision are required")
            return 2
        # blis runs in its binary's directory, so every path it is given is absolute.
        path = Path(a.corpus).resolve()
        sha = a.corpus_sha256 or art.sha256(path.read_bytes())
        corpus = {"dataset": a.corpus_dataset, "revision": a.corpus_revision, "sha256": sha,
                  "path": str(path), "file": path.name}
    env = sc.Env(
        blis=str(blis), blis_release=_git(sim, "describe", "--tags", "--exact-match") or "unknown",
        blis_commit=_git(sim, "rev-parse", "HEAD"), catalog=Path(a.catalog).resolve(),
        catalog_release=_git(a.catalog, "describe", "--tags") or "unknown", registry=Path(a.registry).resolve(),
        registry_release=_git(a.registry, "describe", "--tags") or "unknown",
        kernel=next((l.split()[1] for l in (sim / "go.mod").read_text().splitlines()
                     if "blis-latency-kernel " in l), "unknown"),
        corpus=corpus,
        corpus_cache=Path(a.corpus_cache).resolve() if a.corpus_cache else None,
        vllm_ref=manifest["vllm_ref"], field_list=field_list, fields_sha256=fields_sha,
        base_models=manifest.get("base_models") or {}, timeout_s=a.timeout, vllm_defaults=vdefaults,
        vllm_defaults_release=st.vllm_defaults_release(),
        max_rss_mb=getattr(a, "max_rss_mb", 0) or 0, engine_release=engine_release)
    # The build every point records: --sim-build, else the release tag the checkout is at
    # (check_blis_inputs required one), with the engine release its stack.json names (COV-6).
    env.sim_build = sim_build or env.blis_release
    env.harness_digest = a.harness_digest
    env.catalog_obj = sp.Catalog(blis=str(blis), root=env.catalog)
    env.parts = sp.registry_parts(env.registry)
    # Score serially or across a process pool. BLIS replays are CPU-bound subprocesses, so the
    # worker count is clamped to the machine's cores (4 on an ubuntu-latest runner) -- more would
    # just thrash. The contract is re-sorted by point_id in write_contract, so the output is
    # identical whatever the worker count; parallelism is only a speed knob.
    import os
    workers = a.workers if a.workers and a.workers > 0 else min(os.cpu_count() or 1, 4)
    # Agentic replays hold the 1.8GB corpus in RAM, so they serialize (default 1) even while
    # single-turn runs `workers`-wide; override only on a box with the RAM for concurrent corpora.
    agentic_workers = a.agentic_workers if getattr(a, "agentic_workers", 0) else 1
    try:
        outcomes = sc.score_points(points, pull_dir, work, env, workers=workers,
                                   agentic_workers=agentic_workers, log=_log)
    except bc.CommandError as e:
        # A blis command the scorer reads catalog identities through failed (an ambiguous
        # name, or a build without the command): no point of the run is graded on a guess.
        _log(f"FATAL: {e}")
        return 2
    problems = sc.check_all_scored(points, outcomes)
    if problems:
        for p in problems:
            _log(f"INVALID: {p}")
        return 1
    prov = {"ingest": "api",
            "blis": {"release": env.blis_release, "commit_sha": env.blis_commit, "catalog": env.catalog_release,
                     "registry": env.registry_release, "extractor_version": f"blis-latency-kernel@{env.kernel}"},
            "simulator": env.simulator(), "engine": {"kind": "vllm", "version": engine_release},
            "harness_digest": a.harness_digest, "units": units,
            # Design §11.7, X8: a figure is experimental unless its build and its data are both
            # released. check_blis_inputs requires the catalog and registry at release tags, so the
            # data is released, and the build is released when it is a release tag.
            "experimental": not _RELEASE_TAG.match(env.sim_build),
            "left_out_records": len((manifest.get("ledger") or {}).get("unlisted") or []),
            "vllm_ref": manifest["vllm_ref"], "vllm_max_distance": manifest["vllm_max_distance"],
            "fields_sha256": fields_sha, "pulled_at": manifest["pulled_at"],
            "corpus": corpus and {k: corpus[k] for k in ("dataset", "revision", "sha256")},
            "pull_manifest_sha256": art.sha256(manifest_text.encode()),
            "source": {"name": "SemiAnalysis InferenceX API", "url": api.API + "/"}}
    sc.write_contract(Path(a.out), outcomes, prov)
    problems = contract.validate_dir(a.out)
    for p in problems:
        _log(f"INVALID: {p}")
    scored = sum(1 for o in outcomes if o.fidelity)
    failed = sum(1 for o in outcomes if o.faults)
    _log(f"score: {scored} scored, {len(outcomes) - scored - failed} not scored, {failed} failed -> {a.out}")
    return 1 if problems else 0


def _has_legacy_ids(summary: dict) -> bool:
    """Whether a published summary carries the eight-field identity of before (legacy_ids.py)."""
    return any("recipe" in (n.get("identity") or {}) for n in summary.get("not_scored", [])) or \
        '"recipe":' in json.dumps(summary.get("matrix", []))


def mergeable(prior: dict | None, schema_version: int) -> bool:
    """Whether tonight's delta can be merged into last night's published summary. A summary of
    another schema version (v2, before grades) or one published before point ids were unit ids
    holds no point tonight's contract can carry over (COV-8 keeps it unchanged), so the night
    fetches and scores the whole window instead."""
    return prior is not None and prior.get("schema_version") == schema_version and not _has_legacy_ids(prior)


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
    # The night scores only the anchor units of the substrate release the build pins (COV-2).
    # The list is read before anything is pulled, so a release without one fails the night
    # at once.
    work_dir.mkdir(parents=True, exist_ok=True)
    anchor_path = work_dir / "anchor-units.json"
    try:
        anchors = read_anchor_units(Path(a.blis), anchor_path)
    except (bc.CommandError, ldg.LedgerError, OSError, ValueError) as e:
        _log(f"FATAL: {e}")
        return 2

    # The catalog is checked once, before any artifact is fetched: a source repository two
    # entries claim makes `blis catalog resolve` refuse, and the night stops here, not
    # mid-score.
    try:
        sp.Catalog(blis=str(Path(a.blis).resolve()), root=Path(a.catalog)).check_unambiguous()
    except (bc.CommandError, OSError, ValueError) as e:
        _log(f"FATAL: the catalog is ambiguous or unreadable: {e}")
        return 2

    def pull_fn(work: Path, today_: date, last_ids: set, blis_changed: bool):
        # List the whole window (cheap -- api.pull hits only the REST API, no artifacts); its points
        # are the anchor units, all of which its rows must hold. Then fetch inputs for the points
        # to score: every point on a BLIS release AND on the seed (no prior ids), otherwise only
        # the new points. A row the pull itself can't read fails the run (cmd_pull returns
        # non-zero).
        p = api.pull(api.http_fetch, today=today_, window_days=a.window_days)
        listed = {x.point_id for x in pl.place(p.rows, ldg.load(Path(a.ledger))).points}
        # Every anchor unit must be in this window's pull, whatever its engine: a unit of a
        # framework no BLIS engine models is a point too, and engines.py gives it its G5 reason
        # without an artifact. An anchor unit with no row in the window would be dropped from the
        # counts without a word, so the night fails (COV-1, COV-2).
        missing = anchors - listed
        if missing:
            raise RuntimeError(f"{len(missing)} of the {len(anchors)} anchor units are neither a point of the "
                               f"window nor listed with a reason (first: {sorted(missing)[0]}); the run stops "
                               f"rather than publish counts that omit them (COV-1)")
        window_ids = set(anchors)
        prior = json.loads(latest_path.read_text()) if latest_path.is_file() else None
        whole = blis_changed or not last_ids or not mergeable(prior, bsv2.SCHEMA_VERSION)
        to_fetch = window_ids if whole else (window_ids - set(last_ids))
        _log(f"nightly: window {len(listed)} units, {len(window_ids)} of them anchor units; "
             f"fetch {'every one' if whole else f'{len(to_fetch)} new'}")
        rc = cmd_pull(types.SimpleNamespace(out=str(work), today=today_.isoformat(),
                                            window_days=a.window_days, cache=a.cache, prior=None,
                                            only=sorted(to_fetch), download_workers=a.download_workers,
                                            ledger=a.ledger))
        if rc != 0:
            raise RuntimeError(f"pull failed (rc={rc}); the run stops rather than publish a partial pull")
        return json.loads((work / "manifest.json").read_text())["pulled_at"][:10], window_ids

    def score_build_fn(work: Path, blis_tag: str, score_ids, pull_date: str, window_ids: set):
        rc = cmd_score(types.SimpleNamespace(
            pull=str(work), out=str(contract_dir), blis=a.blis, catalog=a.catalog, stack=a.stack,
            registry=a.registry, sim_build=None, harness_digest="unreleased", units=str(anchor_path),
            corpus=a.corpus,
            corpus_sha256=a.corpus_sha256, corpus_dataset=a.corpus_dataset,
            corpus_revision=a.corpus_revision, corpus_cache=a.corpus_cache, work=a.score_work,
            timeout=a.timeout, only=None, workers=a.workers, agentic_workers=a.agentic_workers,
            max_rss_mb=a.max_rss_mb))
        if rc != 0:
            raise RuntimeError(f"score failed (rc={rc})")
        prov = json.loads((contract_dir / contract.PROVENANCE_JSON).read_text())
        gen_at = prov["pulled_at"]
        prior = json.loads(latest_path.read_text()) if latest_path.is_file() else None
        # IX-only night: merge the delta contract into last night's published summary (summary.json
        # IS the store). A BLIS release (or the seed) rebuilds the whole window from the contract.
        # A prior that is not mergeable was never merged into: pull_fn fetched the whole window.
        if mergeable(prior, bsv2.SCHEMA_VERSION) and prior["provenance"]["blis"]["release"] == blis_tag:
            summary = bsv2.build_merged(prior, contract_dir, window_ids, generated_at=gen_at,
                                        evaluator_commit=a.evaluator_commit or "local",
                                        work=Path(a.score_work or contract_dir.parent) / "merge")
        else:
            summary = bsv2.build(contract_dir, generated_at=gen_at, evaluator_commit=a.evaluator_commit or "local")
        return summary, summary["coverage"]["graded"]

    res = nr.run_night(today, a.blis_tag, work_dir=work_dir, data_dir=data_dir, state_path=state_path,
                       scored_path=Path(a.scored), pull_fn=pull_fn, score_build_fn=score_build_fn,
                       snapshot_date=a.today or today.isoformat(), keep_api=a.keep_api,
                       backlog_fn=bsv2.backlog_of)
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
    p.add_argument("--ledger", required=True,
                   help="blis-substrate's catalog/ledger at the commit the scoring simulator pins: "
                        "every point is a unit of its unit list (design §10.2). TEMPORARY until an "
                        "inference-sim command prints the full unit list with identities "
                        "(catalog/ledger/units) and the ingest report; `blis ledger --list` prints "
                        "only the published unit ids")
    p.add_argument("--download-workers", type=int, default=0,
                   help="parallel artifact-download workers (default: min(2*cores, 8); I/O-bound)")
    s = sub.add_parser("score")
    s.add_argument("--pull", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--blis", required=True,
                   help="the blis binary, built in an inference-sim checkout at a release tag; it runs in that directory")
    s.add_argument("--catalog", required=True)
    s.add_argument("--registry", required=True)
    s.add_argument("--stack", help="TEMPORARY until inference-sim v0.16.0 ships stack.json: the scoring build's "
                                    "stack.json, when its checkout has none")
    s.add_argument("--sim-build", help="the simulator build: a release tag or a 40-hex commit; the checkout must be at it "
                                        "(default: the release tag the checkout is at)")
    s.add_argument("--harness-digest", required=True, help="sha256:<64 hex> of the harness image, or unreleased (X8)")
    s.add_argument("--units", help="the ledger units to score: a PublishedUnits list or a file of unit ids "
                                    "(default: every point of the pull)")
    s.add_argument("--corpus", help="the agentic corpus file; required only when a point to score is agentic")
    s.add_argument("--corpus-sha256")
    s.add_argument("--corpus-dataset", default="semianalysisai/cc-traces-weka-062126")
    s.add_argument("--corpus-revision", help="the corpus's resolved revision; required with --corpus")
    s.add_argument("--corpus-cache")
    s.add_argument("--work")
    s.add_argument("--timeout", type=int, default=7200)
    s.add_argument("--only", nargs="*")
    s.add_argument("--workers", type=int, default=0,
                   help="single-turn scoring parallelism (default: min(cores, 4))")
    s.add_argument("--agentic-workers", type=int, default=0,
                   help="agentic scoring parallelism (default 1: each replay holds the 1.8GB corpus; raise only with RAM)")
    s.add_argument("--max-rss-mb", type=int, default=0,
                   help="per-replay resident-memory ceiling MB (0=none); over-limit agentic replays -> not_scored:insufficient_memory")

    n = sub.add_parser("nightly", help="one night: list window -> fetch+score delta -> merge -> publish")
    n.add_argument("--blis-tag", required=True, help="the stable inference-sim tag resolve_blis.sh resolved")
    n.add_argument("--work-dir", required=True, help="ephemeral dir for this night's pull (never persisted)")
    n.add_argument("--data-dir", required=True, help="the published data tree (latest/, snapshots/, index.json)")
    n.add_argument("--state", required=True, help="state/last-run.json for the API pipeline")
    n.add_argument("--scored", required=True, help="state/scored-releases.json: the releases with published scores; "
                                                   "this night appends its release when it publishes the scores")
    n.add_argument("--window-days", type=int, default=180)
    n.add_argument("--keep-api", type=int, default=5)
    n.add_argument("--today")
    n.add_argument("--cache")
    n.add_argument("--work", help="the contract directory the scored window is written to")
    n.add_argument("--score-work")
    n.add_argument("--evaluator-commit")
    n.add_argument("--ledger", required=True, help="blis-substrate's catalog/ledger (see pull --ledger)")
    n.add_argument("--blis", required=True, help="the blis binary (see score --blis)")
    n.add_argument("--catalog", required=True)
    n.add_argument("--registry", required=True)
    n.add_argument("--stack", help="TEMPORARY until inference-sim v0.16.0 (see score --stack)")
    n.add_argument("--corpus", required=True)
    n.add_argument("--corpus-sha256")
    n.add_argument("--corpus-dataset", default="semianalysisai/cc-traces-weka-062126")
    n.add_argument("--corpus-revision", required=True)
    n.add_argument("--corpus-cache")
    n.add_argument("--timeout", type=int, default=7200)
    n.add_argument("--workers", type=int, default=0, help="single-turn scoring parallelism (default: min(cores, 4))")
    n.add_argument("--agentic-workers", type=int, default=0, help="agentic scoring parallelism (default 1, corpus-heavy)")
    n.add_argument("--download-workers", type=int, default=0, help="parallel artifact-download workers (default: min(2*cores, 8))")
    n.add_argument("--max-rss-mb", type=int, default=0, help="per-replay RSS ceiling MB (0=none); over-limit agentic -> not_scored:insufficient_memory")

    a = ap.parse_args(argv)
    return {"pull": cmd_pull, "score": cmd_score, "nightly": cmd_nightly}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
