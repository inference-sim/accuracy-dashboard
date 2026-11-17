#!/usr/bin/env python3
"""InferenceX API ingest -> BLIS scoring -> contract directory (Discussion #28, issue #29).

  cli.py pull  --window-days N --out PULL [--today YYYY-MM-DD] [--cache DIR]
      Pull the API, resolve builds, join and freeze artifacts. Network: InferenceX API,
      GitHub (artifacts + vllm-project/vllm), Docker Hub, HuggingFace (base_model only).

  cli.py score --pull PULL --out CONTRACT --blis BLIS --catalog CAT --registry REG
               [--stack STACK] --corpus-dir DIR [--work DIR] [--only PID ...]
      Score a frozen pull with one BLIS release. No network. The engine's field list is what
      `blis fields --engine vllm --json` prints. --corpus-dir holds each AgentX corpus as
      resolve_agentic_corpus.py --all fetched it from the catalog's replay workloads.

  cli.py coverage --pull PULL --ledger LEDGER --fields FILE --stack FILE --catalog DIR --registry DIR
                  [--rows ROWS.json] [--units FILE] [--out FILE.json]
      The grade split of a frozen pull, graded from its data by the scorer without a simulator, as
      one JSON document counting rows and units apart (coverage.py).

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
sys.path.insert(1, str(HERE.parent))
import api  # noqa: E402
import artifacts as art  # noqa: E402
import blis_commands as bc  # noqa: E402
import build  # noqa: E402
import clients  # noqa: E402
import contract  # noqa: E402
import coverage as cv  # noqa: E402
import engines  # noqa: E402
import fields as fl  # noqa: E402
import ledger as ldg  # noqa: E402
import pull as pl  # noqa: E402
import resolve_agentic_corpus as rac  # noqa: E402
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
    given = getattr(a, "rows", None)
    if given is not None:
        # The rows of the ledger's own pinned source (read_source_rows), not the live API's window.
        dates = sorted(str(r["date"])[:10] for r in given) or [today.isoformat()]
        p = api.Pull(rows=list(given), window=(dates[0], dates[-1]))
    else:
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
    # With clones of vLLM and InferenceX (the ledger extract's freeze), the build resolver's commit questions and
    # the recipes' trees and blobs are read from them, and each run's head commit from the pinned source, with no
    # REST request (gitlocal.py); only the run's artifacts and job logs are asked of GitHub.
    import gitlocal
    vllm_clone, ix_clone = getattr(a, "vllm_clone", None), getattr(a, "ix_clone", None)
    resolver = build.Resolver(registry=clients.DockerHubRegistry(),
                              github=gitlocal.LocalGit(Path(vllm_clone)) if vllm_clone else clients.GitHubREST(token),
                              ref=vllm_ref)
    lookup_store = getattr(a, "lookups", None)
    if lookup_store is not None:
        import lookups as lkp
        lkp.wrap(resolver, lookup_store)
    gh = art.GitHubArtifacts(pl.IX_REPO, token, Path(a.cache or out / "_artifacts"))
    rest_get = clients.GitHubREST(token)._get
    recipes = rcp.GitHubRecipes(gitlocal.local_get(Path(ix_clone), pl.IX_REPO, rest_get) if ix_clone else rest_get,
                                pl.IX_REPO)
    heads = getattr(a, "run_heads", None) or {}
    if heads:
        wanted = {str(api.run_of(x.row)[0]) for x in points_in if api.run_of(x.row)}
        recipes._sha.update({r: h for r, h in heads.items() if r in wanted})
        if ix_clone:
            gh.prefill_runs({r: {"sha": h, "date": gitlocal.commit_date(Path(ix_clone), h)}
                             for r, h in heads.items() if r in wanted})
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
                                       source_log=(getattr(a, "source_logs", None) or {}).get(str(pt.row.get("id"))),
                                       logs_from_source=getattr(a, "source_logs", None) is not None,
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
_HARNESS_COMMIT = re.compile(r"^[0-9a-f]{40}$")
HARNESS_RUN = HERE.parent.parent / "harness" / "run.sh"


# What the catalog and the registry are at: a release tag, or a full commit while a stack is open.
_DATA_PIN = re.compile(r"^(v\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?|[0-9a-f]{40})$")


def check_blis_inputs(blis: Path, catalog_release: str | None, registry_release: str | None,
                      sim_build: str | None = None) -> list[str]:
    """Everything `score` needs to name its simulator build, or what's wrong. The blis binary sits
    in the inference-sim checkout it was built from. With --sim-build the checkout must be at that
    build: the release tag, or the 40-hex commit. Without it the checkout must be at a release
    tag, which is the build. The catalog and registry are named by the release tags they are at;
    the caller names them, because a copy of the data may carry no git history."""
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
    for release, flag in ((catalog_release, "--catalog-release"), (registry_release, "--registry-release")):
        if release is None:
            out.append(f"{flag} is required: the release tag or full 40-hex commit the data is at")
        elif not _DATA_PIN.match(release):
            out.append(f"{flag} {release!r} is neither a release tag nor a full 40-hex commit")
    return out


def check_harness_commit(commit: str | None) -> list[str]:
    """The harness commit every figure records (design §11.7, X8): the full 40-hex commit of the
    accuracy-dashboard checkout that ran the scorer. A tag, a branch or a short hash names no one
    tree, so none is accepted."""
    if commit is None:
        return ["--harness-commit is required: the full 40-hex commit of the harness checkout"]
    return [] if _HARNESS_COMMIT.match(commit) else [f"--harness-commit {commit!r} is not a full 40-hex commit"]


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


def read_fields(path: Path, engine_release: str) -> tuple["fl.FieldList", str]:
    """The engine's field list and its sha256 (COV-3): the file --fields names, which is the pinned
    blis-vllm release's fields.json (stack.json names the module). TEMPORARY until the M2 substrate
    release lets the engine report its own list through `blis fields`, which the M1 simulator does
    not have. The list must be for the engine release stack.json names; one for another release is
    refused (LIF-6)."""
    raw = Path(path).read_bytes()
    field_list = fl.parse(raw)
    if field_list.engine != {"kind": "vllm", "version": engine_release}:
        raise fl.FieldsError(f"{path} is the field list of {field_list.engine}, but the simulator "
                             f"runs vllm {engine_release} (stack.json)")
    return field_list, art.sha256(raw)


def read_anchor_units(substrate_dir: Path, out: Path) -> set[str]:
    """The anchor units of the substrate release the scoring build pins (COV-2): the published list
    at catalog/ledger/published/anchor.yaml in the blis-substrate checkout stack.json names,
    copied to `out` so the score step can name it as --units. TEMPORARY until the M2 substrate
    release lets `blis ledger --list anchor` print it, which the M1 simulator does not have.
    A missing or empty list is refused: until the ledger's seed exists the release publishes no
    anchor unit, and a night that scored anything else would publish figures on units that may
    fit or select values (X8)."""
    src = Path(substrate_dir) / "catalog" / "ledger" / "published" / "anchor.yaml"
    if not src.is_file():
        raise ldg.LedgerError(f"{src} does not exist: the substrate release this build pins publishes no anchor "
                              f"list yet (the ledger seed is not created), so there is no unit the nightly may "
                              f"score (COV-2)")
    out.write_bytes(src.read_bytes())
    units = ldg.read_unit_set(out, role="anchor")
    if not units:
        raise ldg.LedgerError(f"{src} lists no unit: there is no unit the nightly may score (COV-2)")
    return units


# The G5 reason of an anchor unit whose record the ledger's pinned source does not hold.
UNSOURCED = "value_not_recorded:anchor_not_in_source"


def read_source_rows(source: list[dict], lg, anchors: set[str]) -> tuple[list[dict], list[str]]:
    """The records of the anchor units, from the ledger's own pinned source (design §2.2: the dashboard fetches the
    runs of the units the ledger lists): `source` is the rows of the ledger extract (ledger_extract.py), the dump's
    rows as the substrate's export.sql prints them, so every anchor is read as the ledger recorded it, whatever its
    age. Returns (the rows of the anchors' records, the anchors the source holds no record of, sorted). An anchor unit
    the ledger does not hold is refused: the anchor list and the ledger are then not one release's."""
    want, unknown = {}, []
    for u in anchors:
        unit = lg.units.get(u)
        if unit is None:
            unknown.append(u)
            continue
        for r in unit.records():
            want[str(r)] = u
    if unknown:
        raise ldg.LedgerError(f"{len(unknown)} anchor units are not units of the ledger {lg.revision} "
                              f"(first: {sorted(unknown)[0]}); the anchor list and the ledger are not one release's")
    rows, seen = [], set()
    for r in source:
        u = want.get(str(r.get("id")))
        if u is not None:
            rows.append(r)
            seen.add(u)
    return rows, sorted(set(anchors) - seen)


def add_unsourced(work: Path, units: list[str], lg) -> None:
    """Add to the pull's manifest a G5 entry for each anchor unit the pinned source holds no record of: its identity is
    the ledger's, and its reason is UNSOURCED. Nothing is fetched for it, and it is counted (COV-1)."""
    if not units:
        return
    m = json.loads((work / "manifest.json").read_text())
    for u in units:
        ident = dict(lg.units[u].identity)
        row = {"id": None, "model": ident["model"], "hardware": ident["hardware"], "precision": ident["precision"],
               "framework": ident["framework"], "benchmark_type": ident["benchmark_type"], "conc": ident["conc"],
               "date": ident["measured_date"], "metrics": {}}
        m["points"].append({"point_id": u, "identity": ident, "row": row, "records": [], "measurements": [],
                            "reasons": [UNSOURCED], "files": {}, "build": None})
    meta = {k: v for k, v in m.items() if k != "points"}
    pl.write_manifest(work, meta, sorted(m["points"], key=lambda e: e["point_id"]))


def sample_anchors(rows: list[dict], lg, anchors: set[str], n: int, seed: int) -> set[str]:
    """A fixed, seeded, stratified draw of about `n` anchor units, for a rehearsal of the night: first one unit for
    every model, chip, framework and engine image the anchors hold (so each is exercised), then units drawn at
    random to `n`. The same rows, anchors, n and seed give the same draw."""
    import random
    dates = contract.run_dates(rows)
    by_unit = {}
    for r in sorted(rows, key=lambda r: int(r["id"])):
        p = lg.place(r, dates)
        if p is not None and p.unit.unit_id in anchors:
            by_unit.setdefault(p.unit.unit_id, r)
    rng = random.Random(seed)
    order = sorted(by_unit)
    rng.shuffle(order)
    pick, covered = [], set()
    for key in ("model", "hardware", "framework", "image"):
        for u in order:
            v = (key, by_unit[u].get(key))
            if v not in covered:
                covered.add(v)
                if u not in pick:
                    pick.append(u)
    for u in order:
        if len(pick) >= n:
            break
        if u not in pick:
            pick.append(u)
    return set(pick)


def later_ledger_candidates(lg) -> dict:
    """The live InferenceX rows of the last 180 days whose content differs from the record the ledger's pinned source
    holds (ledger.RowDiffers): each is scored at the source's version, and listed here as a candidate for a later
    ledger, one pinned to a newer InferenceX snapshot."""
    import coverage as cv
    p = api.pull(api.http_fetch, today=date.today(), window_days=180)
    _, differing = cv.place_all(p.rows, lg)
    return {"count": len(differing), "ledger_revision": lg.revision,
            "records": sorted((str(r["id"]) for r in differing), key=int)}


def read_stack(blis: Path, given: str | None) -> sk.Stack:
    """The scoring build's stack.json: the engine release it runs (LIF-6) and the modules it pins.

    TEMPORARY until the pinned inference-sim release, the first release that writes stack.json at its root
    (inference-sim m1/substrate, task H): --stack names the file for a build that does not ship
    one. Without --stack the file is the simulator checkout's own. A build with neither predates
    stack.json and is refused; the engine release is never read from installation.md."""
    path = Path(given) if given else blis.parent / "stack.json"
    if not path.is_file():
        raise sk.StackError(f"{blis.parent} has no stack.json: this simulator build predates stack.json "
                            f"(the pinned release writes it), so the engine release it runs is not stated; "
                            f"pass --stack FILE")
    return sk.load(path)


def check_metric_definitions(blis: Path) -> list[str]:
    """Why the simulator's figures cannot be compared with the client's (DEV-8): `blis metrics` gives the
    registry of the build, and each figure the harness compares (result.COMPARED_FIGURES) must have the
    client's definition there. A build without the command (the M1 simulator, v0.16.0) has no registry to
    check; the run says so and goes on, and its figures rest on the definitions the scorer assumes."""
    try:
        registry = bc.metrics(str(blis))
    except bc.CommandError as e:
        if "unknown command" in str(e):
            _log("score: this build has no `blis metrics`: the definitions of the figures compared are not checked")
            return []
        return [str(e)]
    return result.check_definitions(registry)


def cmd_score(a) -> int:
    pull_dir = Path(a.pull)
    blis = Path(a.blis).resolve()
    sim_build = getattr(a, "sim_build", None)
    bad = check_blis_inputs(blis, getattr(a, "catalog_release", None), getattr(a, "registry_release", None), sim_build)
    bad += check_harness_commit(getattr(a, "harness_commit", None))
    if not bad:
        bad += check_metric_definitions(blis)
    try:
        stack = read_stack(blis, getattr(a, "stack", None))
        engine_release = stack.engine("vllm")
        field_list, fields_sha = read_fields(Path(a.fields), engine_release)
    except (sk.StackError, fl.FieldsError, bc.CommandError, OSError, ValueError) as e:
        bad.append(str(e))
    # Every date-pinned AgentX corpus, by the catalog replay workload of its alias, checked against
    # the entry's full sha256 (X12, D3). A point is replayed with its own run's alias (score.py).
    try:
        corpora = rac.checked_corpora(Path(a.catalog), Path(a.corpus_dir))
    except rac.CorpusError as e:
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
    env = sc.Env(
        blis=str(blis), blis_release=_git(sim, "describe", "--tags", "--exact-match") or "unknown",
        blis_commit=_git(sim, "rev-parse", "HEAD"), catalog=Path(a.catalog).resolve(),
        catalog_release=a.catalog_release, registry=Path(a.registry).resolve(),
        registry_release=a.registry_release,
        kernel=next((l.split()[1] for l in (sim / "go.mod").read_text().splitlines()
                     if "blis-latency-kernel " in l), "unknown"),
        corpora=corpora,
        corpus_cache=Path(a.corpus_cache).resolve() if a.corpus_cache else None,
        vllm_ref=manifest["vllm_ref"], field_list=field_list, fields_sha256=fields_sha,
        base_models=manifest.get("base_models") or {}, timeout_s=a.timeout, vllm_defaults=vdefaults,
        vllm_defaults_release=st.vllm_defaults_release(),
        max_rss_mb=getattr(a, "max_rss_mb", 0) or 0, engine_release=engine_release,
        routers_dir=Path(a.router_table).resolve() if getattr(a, "router_table", None) else None,
        assumed_router_revision=getattr(a, "assume_router_revision", None),
        router_policy_experiment=getattr(a, "router_policy_experiment", None),
        speculative_fallback_category=getattr(a, "speculative_fallback_category", None),
        router_checkout=Path(a.router_checkout).resolve() if getattr(a, "router_checkout", None) else None)
    # The build every point records: --sim-build, else the release tag the checkout is at
    # (check_blis_inputs required one), with the engine release its stack.json names (COV-6).
    env.sim_build = sim_build or env.blis_release
    env.harness_commit = a.harness_commit
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
            "harness_commit": a.harness_commit, "units": units,
            # Design §11.7, X8: a figure is experimental unless its build and its data are both
            # released. The build is released when it is a release tag, and the data when the
            # catalog and the registry are named by release tags, not by commits.
            "experimental": env.routers_dir is not None or env.assumed_router_revision is not None or env.router_policy_experiment is not None or env.speculative_fallback_category is not None or not all(
                _RELEASE_TAG.match(x) for x in (env.sim_build, env.catalog_release, env.registry_release)),
            "left_out_records": len((manifest.get("ledger") or {}).get("unlisted") or []),
            "vllm_ref": manifest["vllm_ref"], "vllm_max_distance": manifest["vllm_max_distance"],
            "fields_sha256": fields_sha, "pulled_at": manifest["pulled_at"],
            "corpora": sc.corpora_provenance(env.corpora),
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


def cmd_coverage(a) -> int:
    try:
        doc = cv.run(pull_dir=Path(a.pull), ledger=Path(a.ledger), fields_path=Path(a.fields), stack_path=Path(a.stack),
                     catalog=Path(a.catalog), registry=Path(a.registry), rows_path=Path(a.rows) if a.rows else None,
                     units_path=Path(a.units) if a.units else None, workers=a.workers or 1,
                     work=Path(a.work) if a.work else None)
    except (cv.CoverageError, ldg.LedgerError, fl.FieldsError, sk.StackError, bc.CommandError, OSError, KeyError,
            ValueError) as e:
        _log(f"FATAL: {e}")
        return 2
    text = json.dumps(doc, indent=1, sort_keys=False) + "\n"
    if a.out:
        Path(a.out).write_text(text)
    sys.stdout.write(text)
    return 0


def _has_legacy_ids(summary: dict) -> bool:
    """Whether a published summary carries the eight-field identity of before (legacy_ids.py)."""
    return any("recipe" in (n.get("identity") or {}) for n in summary.get("not_scored", [])) or \
        '"recipe":' in json.dumps(summary.get("matrix", []))


def harness_commit_now() -> str:
    """The commit of the checkout the night's harness runs from (run.sh records the same one)."""
    return _git(HARNESS_RUN.parent.parent, "rev-parse", "HEAD")


def same_harness(prior: dict | None, commit: str) -> bool:
    """Whether last night's summary was scored by this checkout's harness commit. A figure records
    the commit that produced it (X8) and a summary names one, so a delta scored by another commit
    cannot be merged into it: the night rescores the whole window, as for a new BLIS release."""
    return prior is not None and (prior.get("provenance") or {}).get("harness_commit") == commit


def mergeable(prior: dict | None, schema_version: int) -> bool:
    """Whether tonight's delta can be merged into last night's published summary. A summary of
    another schema version (v2, before grades) or one published before point ids were unit ids
    holds no point tonight's contract can carry over (COV-8 keeps it unchanged), so the night
    fetches and scores the whole window instead."""
    return prior is not None and prior.get("schema_version") == schema_version and not _has_legacy_ids(prior)


def run_harness(cmd: list[str]) -> int:
    """Run harness/run.sh with `cmd` (harness_command) and return its exit status."""
    return subprocess.run(cmd).returncode


def harness_command(*, sim: str, units, pull, out, catalog, registry, corpus_dir, fields,
                    catalog_release: str, registry_release: str, max_rss_mb: int = 0) -> list[str]:
    """The harness/run.sh command that scores a night (design §11.7). The harness is the script in
    this checkout, so the commit every figure records is this checkout's HEAD, which run.sh reads."""
    cmd = ["bash", str(HARNESS_RUN), "--sim", sim, "--units", str(Path(units).resolve()),
           "--pull", str(Path(pull).resolve()), "--out", str(Path(out).resolve()),
           "--catalog", str(Path(catalog).resolve()), "--registry", str(Path(registry).resolve()),
           "--corpus-dir", str(Path(corpus_dir).resolve()), "--fields", str(Path(fields).resolve()),
           "--catalog-release", catalog_release, "--registry-release", registry_release]
    if max_rss_mb:
        cmd += ["--max-rss-mb", str(max_rss_mb)]
    return cmd


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
    harness_now = harness_commit_now()
    work_dir, data_dir, state_path = Path(a.work_dir), Path(a.data_dir), Path(a.state)
    contract_dir = Path(a.work or data_dir.parent / "_contract")
    latest_path = data_dir / "latest" / "summary.json"
    # The night scores only the anchor units of the substrate release the build pins (COV-2).
    # The list is read before anything is pulled, so a release without one fails the night
    # at once.
    work_dir.mkdir(parents=True, exist_ok=True)
    anchor_path = work_dir / "anchor-units.json"
    try:
        anchors = read_anchor_units(Path(a.substrate_dir), anchor_path)
    except (bc.CommandError, ldg.LedgerError, OSError, ValueError) as e:
        _log(f"FATAL: {e}")
        return 2

    # The catalog is checked once, before any artifact is fetched: a catalog the build cannot read stops the
    # night here, not mid-score. A source repository several entries claim does not: each run is matched to the
    # entry its deployment is, and a run that matches none is G5 catalog_entry_ambiguous (support.Catalog.model).
    try:
        sp.Catalog(blis=str(Path(a.blis).resolve()), root=Path(a.catalog)).check_readable()
    except (bc.CommandError, OSError, ValueError) as e:
        _log(f"FATAL: the catalog is unreadable: {e}")
        return 2

    later = {}

    def pull_fn(work: Path, today_: date, last_ids: set, blis_changed: bool):
        # The night's points are the anchor units, every one, read from the ledger's own pinned source (design §2.2,
        # COV-1): a unit is scored on the record the ledger was made from, whatever its age, not on the live API's
        # window. An anchor the source holds no record of is G5 UNSOURCED. The live API's newer versions of those
        # records are listed as later-ledger candidates in the backlog, never scored.
        lg = ldg.load(Path(a.ledger))
        import ledger_extract as lx
        records = {str(r) for u in anchors if u in lg.units for r in lg.units[u].records()}
        source, logs = lx.check(Path(a.ledger_extract), json.loads(Path(a.ledger_extract_pin).read_text()), lg,
                                keep_log=records.__contains__)
        if a.sample:
            # A rehearsal (dry run): a seeded, stratified draw of the anchors, scored by the same path.
            drawn = sample_anchors(source, lg, anchors, a.sample, a.sample_seed)
            anchors.intersection_update(drawn)
            anchor_path.write_text(json.dumps({"kind": "PublishedUnits", "role": "anchor", "partition_version": 1,
                                               "seed_sha256": "0" * 64, "units": sorted(anchors)}))
            _log(f"nightly: rehearsal on {len(anchors)} sampled anchor units (seed {a.sample_seed})")
        rows, unsourced = read_source_rows(source, lg, anchors)
        listed = {x.point_id for x in pl.place(rows, lg).points}
        stray = listed - anchors
        if stray:
            raise RuntimeError(f"the source rows place {len(stray)} units that are not anchor units")
        later.update(later_ledger_candidates(lg))
        _log(f"nightly: {len(anchors)} anchor units, {len(listed)} with a record in {lg.revision}, "
             f"{len(unsourced)} without one; {later['count']} live rows differ from it (later-ledger candidates)")
        window_ids = set(anchors)
        prior = json.loads(latest_path.read_text()) if latest_path.is_file() else None
        whole = (blis_changed or not last_ids or not mergeable(prior, bsv2.SCHEMA_VERSION)
                 or not same_harness(prior, harness_now))
        to_fetch = window_ids if whole else (window_ids - set(last_ids))
        _log(f"nightly: window {len(listed)} units, {len(window_ids)} of them anchor units; "
             f"fetch {'every one' if whole else f'{len(to_fetch)} new'}")
        pin = json.loads(Path(a.ledger_extract_pin).read_text())
        if getattr(a, "ledger_pull_pin", None):
            # The pull this run's freeze packed (its sha256 printed for the pin), when the pin names none yet.
            pin["pull"] = json.loads(Path(a.ledger_pull_pin).read_text())
        if pin.get("pull"):
            # The ledger's frozen pull (freeze_ledger.py): every anchor's GitHub inputs, frozen once per ledger version;
            # the night asks GitHub nothing but the lookups a new engine release adds, and counts them.
            import os
            import freeze_ledger as fz
            asked = fz.replay(Path(a.ledger_pull), pin["pull"], work, to_fetch & listed,
                              os.environ.get("VLLM_REF") or build.VLLM_REF, os.environ.get("GH_TOKEN") or None)
            _log(f"nightly: replayed the frozen pull ({pin['pull']['sha256'][:12]}); {asked} GitHub requests")
        else:
            rc = cmd_pull(types.SimpleNamespace(out=str(work), today=today_.isoformat(),
                                                window_days=a.window_days, cache=a.cache, prior=None,
                                                only=sorted(to_fetch & listed), download_workers=a.download_workers,
                                                ledger=a.ledger, rows=rows, source_logs=logs))
            if rc != 0:
                raise RuntimeError(f"pull failed (rc={rc}); the run stops rather than publish a partial pull")
        add_unsourced(work, [u for u in unsourced if u in to_fetch], lg)
        return json.loads((work / "manifest.json").read_text())["pulled_at"][:10], window_ids

    # The catalog and registry are directories of the one substrate checkout, so both are at the
    # release stack.json names for it. A draft build's substrate is a pseudo-version: it is not a
    # release and its figures are not published (X8). The checkout must be that release's commit.
    release = sk.release_name({"version": a.substrate_version})
    if release is None:
        _log(f"FATAL: blis-substrate {a.substrate_version} in stack.json is not a release tag; "
             f"a release is scored on a tagged substrate")
        return 2
    problems = sk.verify_checkout(Path(a.substrate_dir), release, a.substrate_commit)
    if problems:
        _log("FATAL: the blis-substrate checkout is not release " + release + ": " + "; ".join(problems))
        return 2

    def score_build_fn(work: Path, blis_tag: str, score_ids, pull_date: str, window_ids: set):
        # The night scores by running harness/run.sh from this checkout (design §11.7): the
        # figures record the checkout's commit, run.sh clones and builds the release `blis_tag`,
        # and the scorer is not called in this process.
        contract_dir.mkdir(parents=True, exist_ok=True)
        rc = run_harness(harness_command(
            sim=blis_tag, units=anchor_path, pull=work, out=contract_dir,
            catalog=a.catalog, registry=a.registry, corpus_dir=a.corpus_dir, fields=a.fields,
            catalog_release=release, registry_release=release,
            max_rss_mb=a.max_rss_mb))
        if rc != 0:
            raise RuntimeError(f"score failed (rc={rc})")
        prov = json.loads((contract_dir / contract.PROVENANCE_JSON).read_text())
        gen_at = prov["pulled_at"]
        prior = json.loads(latest_path.read_text()) if latest_path.is_file() else None
        # IX-only night: merge the delta contract into last night's published summary (summary.json
        # IS the store). A BLIS release (or the seed) rebuilds the whole window from the contract.
        # A prior that is not mergeable was never merged into: pull_fn fetched the whole window.
        if (mergeable(prior, bsv2.SCHEMA_VERSION) and prior["provenance"]["blis"]["release"] == blis_tag
                and same_harness(prior, harness_now)):
            summary = bsv2.build_merged(prior, contract_dir, window_ids, generated_at=gen_at,
                                        evaluator_commit=a.evaluator_commit or "local",
                                        work=Path(a.score_work or contract_dir.parent) / "merge")
        else:
            summary = bsv2.build(contract_dir, generated_at=gen_at, evaluator_commit=a.evaluator_commit or "local")
        return summary, summary["coverage"]["graded"]

    res = nr.run_night(today, a.blis_tag, work_dir=work_dir, data_dir=data_dir, state_path=state_path,
                       scored_path=Path(a.scored), pull_fn=pull_fn, score_build_fn=score_build_fn,
                       snapshot_date=a.today or today.isoformat(), keep_api=a.keep_api,
                       backlog_fn=lambda summary: {**bsv2.backlog_of(summary), "later_ledger_candidates": later})
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
    s.add_argument("--catalog-release", required=True,
                   help="the release tag the catalog is at (a copy of the data may carry no "
                        "git history, so it is named)")
    s.add_argument("--registry-release", required=True, help="the release tag the registry is at")
    s.add_argument("--fields", required=True,
                   help="the engine's fields.json for the release stack.json names: the pinned blis-vllm release's "
                        "file (TEMPORARY until the M2 substrate release lets `blis fields` print it)")
    s.add_argument("--stack", help="TEMPORARY until the pinned inference-sim release ships stack.json: the scoring build's "
                                    "stack.json, when its checkout has none")
    s.add_argument("--sim-build", help="the simulator build: a release tag or a 40-hex commit; the checkout must be at it "
                                        "(default: the release tag the checkout is at)")
    s.add_argument("--harness-commit", required=True, help="the full 40-hex commit of the harness checkout (X8)")
    s.add_argument("--units", help="the ledger units to score: a PublishedUnits list or a file of unit ids "
                                    "(default: every point of the pull)")
    s.add_argument("--corpus-dir", required=True,
                   help="each AgentX corpus at <dir>/<workload>/<file>, as resolve_agentic_corpus.py --all "
                        "fetched it at the revision its catalog replay workload pins")
    s.add_argument("--corpus-cache")
    s.add_argument("--router-table", help="a directory of router table entries to read in place of <catalog>/routers: for an "
                                          "experiment with a candidate entry. The run is then experimental.")
    s.add_argument("--assume-router-revision", help="a 40-hex commit of the router build to assume where a run records only "
                                                    "a wheel version (an experiment; the point says it was assumed, and the run is experimental)")
    s.add_argument("--router-policy-experiment", help="an llm-d policy to stand in for a router the table does not map, to measure the prefill/decode writer "
                        "apart from the router question (an experiment: each such point names it, and the run is experimental)")
    s.add_argument("--speculative-fallback-category", metavar="CATEGORY",
                   help="the acceptance profile's category to fall back to where the benchmark states none (design D8: a "
                        "fallback the caller requested). Without it a speculative point that pins no acceptance length is G5 "
                        "value_not_recorded:workload_category_not_stated. The point names it, and the run is experimental.")
    s.add_argument("--router-checkout", metavar="DIR", help="a checkout of llm-d's router fork at a pinned commit: it publishes the "
                   "endpoint-picker file of each policy, which a prefill/decode point passes to the simulator unchanged")
    s.add_argument("--work")
    s.add_argument("--timeout", type=int, default=7200)
    s.add_argument("--only", nargs="*")
    s.add_argument("--workers", type=int, default=0,
                   help="single-turn scoring parallelism (default: min(cores, 4))")
    s.add_argument("--agentic-workers", type=int, default=0,
                   help="agentic scoring parallelism (default 1: each replay holds the 1.8GB corpus; raise only with RAM)")
    s.add_argument("--max-rss-mb", type=int, default=0,
                   help="per-replay resident-memory ceiling MB (0=none); over-limit agentic replays -> not_scored:insufficient_memory")

    c = sub.add_parser("coverage", formatter_class=argparse.RawDescriptionHelpFormatter,
                       help="the grade split of a frozen pull, graded from its data without a simulator",
                       description=cv.__doc__ + "\nThe pull's point ids may be of an older identity: with --rows the window's rows "
                       "are placed in --ledger afresh and each unit takes the artifacts of the manifest entry of "
                       "its rows, by row id.")
    c.add_argument("--pull", required=True, help="a frozen pull (manifest.json and points/)")
    c.add_argument("--ledger", required=True, help="blis-substrate's catalog/ledger (see pull --ledger)")
    c.add_argument("--fields", required=True, help="the engine's fields.json, for the release stack.json names")
    c.add_argument("--stack", required=True, help="the scoring build's stack.json (the engine release)")
    c.add_argument("--catalog", required=True,
                   help="a catalog checkout, read as `blis catalog resolve` answers it (TEMPORARY, support.CheckoutCatalog); "
                        "it must hold the replay workload of each AgentX corpus alias")
    c.add_argument("--registry", required=True)
    c.add_argument("--rows", help="a JSON list of the API rows (every framework); those in the pull's window are placed")
    c.add_argument("--units", help="a PublishedUnits list or a file of unit ids (the anchor list): adds the `anchor` section")
    c.add_argument("--work")
    c.add_argument("--workers", type=int, default=1)
    c.add_argument("--out", help="also write the JSON document here")

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
    n.add_argument("--sample", type=int, default=0,
                   help="a rehearsal: score a seeded, stratified draw of about this many anchor units (0: every one)")
    n.add_argument("--sample-seed", type=int, default=1)
    n.add_argument("--ledger-extract", required=True,
                   help="the ledger's pinned source as ledger_extract.py builds it (never committed: X12)")
    n.add_argument("--ledger-pull-pin", help="the pull's own pin, when .github/ledger-extract.json names none yet")
    n.add_argument("--ledger-pull", help="the ledger's frozen pull archive the pin's \"pull\" names (freeze_ledger.py)")
    n.add_argument("--ledger-extract-pin", required=True,
                   help="the pin naming the extract's sha256, size and ledger revision (.github/ledger-extract.json)")
    n.add_argument("--blis", required=True, help="the blis binary (see score --blis)")
    n.add_argument("--catalog", required=True)
    n.add_argument("--registry", required=True)
    n.add_argument("--substrate-dir", required=True, help="the blis-substrate checkout --catalog, --registry and --ledger are in")
    n.add_argument("--substrate-version", required=True,
                   help="the blis-substrate version in stack.json (resolve_stack.py substrate_version); a release tag names the release")
    n.add_argument("--substrate-commit", default="",
                   help="the blis-substrate commit in stack.json (resolve_stack.py substrate_commit); empty for a release, whose tag names it")
    n.add_argument("--fields", required=True, help="see score --fields")
    n.add_argument("--stack", help="TEMPORARY until the pinned inference-sim release (see score --stack)")
    n.add_argument("--corpus-dir", required=True, help="see score --corpus-dir")
    n.add_argument("--corpus-cache")
    n.add_argument("--timeout", type=int, default=7200)
    n.add_argument("--workers", type=int, default=0, help="single-turn scoring parallelism (default: min(cores, 4))")
    n.add_argument("--agentic-workers", type=int, default=0, help="agentic scoring parallelism (default 1, corpus-heavy)")
    n.add_argument("--download-workers", type=int, default=0, help="parallel artifact-download workers (default: min(2*cores, 8))")
    n.add_argument("--max-rss-mb", type=int, default=0, help="per-replay RSS ceiling MB (0=none); over-limit agentic -> not_scored:insufficient_memory")

    a = ap.parse_args(argv)
    return {"pull": cmd_pull, "score": cmd_score, "coverage": cmd_coverage, "nightly": cmd_nightly}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
