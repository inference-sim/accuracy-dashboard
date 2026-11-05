"""Stage 1: pull and freeze (Discussion #28, "Freeze at ingest").

For each vLLM row in the window: resolve its build, join it to its artifacts, and freeze what
scoring needs (server log, launch config, client export and command) under
<out>/points/<point_id>/, each file stored once with its sha256. Artifacts expire after 90
days and Docker Hub tags move, so nothing scoring needs is fetched again later: `score`
reads only the frozen pull.

<out>/manifest.json lists every row, its identity, its build record and its frozen files;
its sha256 is the provenance's pull_manifest_sha256.
"""
from __future__ import annotations

import json
import urllib.error
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import api  # noqa: E402
import artifacts as art  # noqa: E402
import build  # noqa: E402
import contract  # noqa: E402
import recipes as rcp  # noqa: E402

IX_REPO = "SemiAnalysisAI/InferenceX"
_RUN_REPO = __import__("re").compile(r"github\.com/([^/]+/[^/]+)/actions/runs/")


def run_repo(row: dict) -> str | None:
    m = _RUN_REPO.search(str(row.get("run_url") or ""))
    return m.group(1) if m else None


@dataclass
class Frozen:
    dir: Path
    files: dict = field(default_factory=dict)    # role -> {"path", "sha256", "from"}

    def put(self, role: str, data: bytes, origin: str):
        self.dir.mkdir(parents=True, exist_ok=True)
        name = f"{role}.gz"
        (self.dir / name).write_bytes(art.stable_gzip(data))
        self.files[role] = {"path": name, "sha256": art.sha256(data), "from": origin}


def _row_reasons(row: dict) -> list[str]:
    """Rows this extractor doesn't handle at all, by the row's own shape."""
    out = []
    if row.get("disagg") or row.get("is_multinode"):
        out.append("blis_refused:disaggregated_or_multinode")
    return out


# What a point takes from its agentic upload, by file name -> role.
AGENTIC_FILES = {"profile_export_aiperf.json": "client_export", "benchmark_command.txt": "client_command"}


def read_needed(blob: bytes, entry: dict, needed) -> list[tuple[str, bytes]]:
    """An artifact's files, skipping members over the size cap that the point doesn't need
    (e.g. a multi-GB server_metrics_export.json next to the log). A skipped member that is one
    it needs, or that is itself an archive (whose contents can't be told), makes the artifact
    Unreadable, as before; one it doesn't need is recorded in the entry's problems."""
    big: list = []
    files = list(art.iter_files(blob, oversized=big))
    for o in big:
        if o.is_archive() or needed(o):
            raise art.Unreadable(f"{o.path}: {o.size} bytes")
        entry.setdefault("skipped_members", []).append(f"{o.path} ({o.size} bytes)")
    return files


def recipe_checkpoint(row: dict, server_log: str | None, recipes) -> dict | None:
    """When the run's log serves a local path and names no HF repo, the checkpoint its own
    InferenceX recipe served (recipes.py), with the commit it was read at. None otherwise."""
    if recipes is None or not server_log:
        return None
    import settings as st
    import support as sp
    vals = st.read_args(server_log).values
    named = [x for k in ("served_model_name", "model") for v in vals.get(k, [])
             for x in (v if isinstance(v, list) else [v])]
    if any(sp.hf_repo(x) for x in named):
        return None
    paths = [x for x in named if isinstance(x, str) and x.startswith("/")]
    run = api.run_of(row)
    if not paths or run is None or run_repo(row) != recipes.repo:
        # Only a run of the repository whose recipes we read (another one, e.g. a private
        # repository, isn't readable, and its recipes aren't these).
        return None
    try:
        sha = recipes.run_commit(run[0])
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    repo = rcp.checkpoint(recipes.at(sha), row, paths[0])
    return {"repo": repo, "source": "inferencex_recipe", "commit": sha, "served_path": paths[0]} if repo else None


def freeze_point(point: "Point", *, resolver: build.Resolver, gh: art.GitHubArtifacts, fetch, out: Path,
                 recipes=None) -> dict:
    """Freeze one point's inputs. The point is one ledger unit; its inputs are the kept
    record's (the smallest row id the window holds), and its measured values are each
    measurement's, so the score is against their mean (design §10.2)."""
    row = point.row
    # The unit's identity, from the unit list: the measured date of a benchmark run is the
    # earliest date among all its records, which one row does not show (design §10.2).
    ident = dict(point.unit.identity)
    pid = contract.point_id(ident)
    entry = {"point_id": pid, "identity": ident, "row": row, "records": point.records,
             "measurements": point.measurements, "reasons": _row_reasons(row), "files": {}}
    agentic = row["benchmark_type"] == "agentic_traces"
    run = api.run_of(row)
    frozen = Frozen(out / "points" / pid)
    server_log = None
    # A single-turn point is scored from the API's /server-log (the vLLM log); its artifacts only
    # add the launch config, so a run with none (no fingerprint, expired, another repository)
    # still scores. An agentic point needs its artifacts: the server log and the client export.
    join_reasons = entry["reasons"] if agentic else entry.setdefault("artifact_notes", [])
    if run is None:
        join_reasons.append("artifact_unmatched:no_run_url")
    elif run_repo(row) != gh.repo:
        # The row's run lives in another repository (e.g. a private one) whose artifacts
        # this pull can't read: no server log, so nothing to score from.
        join_reasons.append(f"server_log_missing:run_in_{(run_repo(row) or 'unknown').replace('/', '_')}")
    else:
        run_id, attempt = run
        # Thread-safe memoized listing: one HTTP call per run even when a pool freezes many of its
        # points concurrently. (run_artifacts kept as an optional no-op for older callers.)
        arts = gh.list_cached(run_id)
        j = art.join({**row, "_attempt": attempt}, arts,
                     lambda a: art.read_result_json(gh.download(a)), agentic=agentic)
        join_reasons += j.reasons
        entry["result_filename"] = j.result_filename
        if j.result_json is not None:
            frozen.put("result_json", json.dumps(j.result_json, sort_keys=True).encode(), j.result.name)
        if j.server_logs is not None:
            try:
                # A log can be named anything, so only an oversized JSON that isn't one is skipped.
                files = read_needed(gh.download(j.server_logs), entry,
                                    lambda o: art.is_server_log(o.head) or not o.path.endswith(".json"))
            except art.Unreadable as e:
                # Single-turn takes its log from the API's /server-log below; a bad upload is
                # a note there, a reason only where the upload is the log (agentic).
                join_reasons.append("server_log_missing:unreadable_artifact")
                entry.setdefault("problems", []).append(str(e))
                files = []
            logs = art.find_server_logs(files)
            if logs:
                # One log per engine host; a colocated single-node point has one. Several are
                # kept joined (each prefixed with its path) so every rank's lines are read.
                text = b"".join(b"# == " + p.encode() + b"\n" + d + b"\n" for p, d in sorted(logs))
                frozen.put("server_log", text, j.server_logs.name)
                server_log = text.decode("utf-8", "replace")
                if len(logs) > 1:
                    entry["server_log_files"] = [p for p, _ in sorted(logs)]
            elif not agentic:
                pass   # single-turn: the API's /server-log is the vLLM log (below)
            else:
                entry["reasons"].append("server_log_missing")
            try:
                p, cfg = art.find_launch_config(files, j.result_filename)
            except ValueError as e:
                join_reasons.append("conflict:launch_config")
                entry.setdefault("problems", []).append(str(e))
                p, cfg = None, None
            if cfg is not None:
                frozen.put("launch_config", json.dumps(cfg, sort_keys=True, default=str).encode(),
                           f"{j.server_logs.name}:{p}")
        if agentic and j.agentic is not None:
            try:
                files = read_needed(gh.download(j.agentic), entry,
                                    lambda o: o.path.rsplit("/", 1)[-1] in AGENTIC_FILES)
            except art.Unreadable as e:
                entry["reasons"].append("artifact_unmatched:unreadable_agentic_export")
                entry.setdefault("problems", []).append(str(e))
                files = []
            for base, role in AGENTIC_FILES.items():
                hits = art.find_named(files, base)
                if len({art.sha256(d) for _, d in hits}) == 1:
                    frozen.put(role, hits[0][1], f"{j.agentic.name}:{hits[0][0]}")
                elif len(hits) > 1:
                    entry["reasons"].append(f"conflict:{role}")
                elif role == "client_export":
                    entry["reasons"].append("artifact_unmatched:client_export")
    if not agentic and server_log is None:
        text = api.server_log(fetch, row["id"])
        if text and art.is_server_log(text.encode()):
            frozen.put("server_log", text.encode(), "api:/server-log")
            server_log = text
        else:
            entry["reasons"].append("server_log_missing")
    b = resolver.resolve(row.get("image") or "", server_log)
    # The build never refuses a point; it makes it estimated unless it's the build BLIS models.
    entry["build"] = b.record()
    ck = recipe_checkpoint(row, server_log, recipes)
    if ck:
        entry["checkpoint"] = ck
    entry["files"] = frozen.files
    entry["reasons"] = sorted(set(entry["reasons"]))
    if entry.get("artifact_notes") is not None:
        entry["artifact_notes"] = sorted(set(entry["artifact_notes"]))
        if not entry["artifact_notes"]:
            del entry["artifact_notes"]
    return entry


def write_manifest(out: Path, meta: dict, points: list[dict]) -> str:
    doc = {**meta, "points": sorted(points, key=lambda p: p["point_id"])}
    text = contract.canonical_dumps(doc) + "\n"
    (out / "manifest.json").write_text(text)
    return art.sha256(text.encode())


@dataclass
class Point:
    """One ledger unit the window holds: its kept row, every record of it the window holds, and
    each measurement's measured values (the metrics of the measurement's kept record)."""
    unit: object
    row: dict
    records: list
    measurements: list

    @property
    def point_id(self) -> str:
        return self.unit.unit_id


@dataclass
class Placed:
    """The window's rows, placed in the ledger: the points, and every row that is no point,
    with why (the ingest report's reason for a record it left out, or not_in_source_revision
    for a record newer than the ledger's pinned source revision)."""
    points: list = field(default_factory=list)
    unlisted: list = field(default_factory=list)    # {"record", "reason", "model", "date", ...}


def place(rows: list[dict], lg) -> Placed:
    """Group the window's rows by ledger unit (records the ledger joins are one point) and list
    the rows the ledger holds no unit for. A row whose identity disagrees with the unit list
    raises ledger.LedgerError: it is not the record the ledger was generated from."""
    import ledger as ldg
    by_unit: dict = {}
    out = Placed()
    window_dates = contract.run_dates(rows)
    for r in sorted(rows, key=lambda r: int(r["id"])):
        rid = str(r["id"])
        p = lg.by_record.get(rid)
        if p is None:
            why = lg.left_out.get(rid)
            out.unlisted.append({"record": rid, "reason": f"left_out:{why}" if why else "not_in_source_revision",
                                 "model": r["model"], "hardware": r["hardware"], "framework": r["framework"],
                                 "benchmark_type": r["benchmark_type"], "conc": r["conc"],
                                 "date": str(r["date"])[:10]})
            continue
        # The measured date of a kept or duplicate record is its unit's: the earliest date of
        # its benchmark run over every record of the source, which only the ledger's ingest saw.
        # A merged record's own identity is another unit's, which the list does not hold, so
        # its run's earliest date is taken from the window's rows.
        dates = dict(window_dates)
        run = contract.benchmark_run(r.get("run_url"))
        if run is not None and p.how != ldg.MERGED:
            dates[run] = p.unit.identity["measured_date"]
        lg.place(r, dates)
        by_unit.setdefault(p.unit.unit_id, []).append(r)
    for uid in sorted(by_unit):
        unit = lg.units[uid]
        have = {str(r["id"]): r for r in by_unit[uid]}
        kept = next((have[x] for x in unit.records() if x in have), None)
        meas = [{"record": m["record"], "metrics": have[m["record"]].get("metrics") or {}}
                for m in unit.measurements if m["record"] in have]
        out.points.append(Point(unit=unit, row=kept, records=sorted(have, key=int), measurements=meas))
    return out


@dataclass
class Incremental:
    """How tonight's window splits against a prior frozen pull (Discussion #15, "Store"):

      reuse   point ids the prior pull already froze and this window still holds -- their files
              and manifest entries carry over untouched (a measurement is immutable, so a frozen
              point never needs re-freezing).
      fresh   points in this window the prior pull didn't hold -- freeze them now.
      dropped point ids the prior pull froze that this window no longer holds -- their files and
              manifest entries leave the store (aged out of the 180 days).
    """
    reuse: dict = field(default_factory=dict)    # point_id -> prior manifest entry
    fresh: list = field(default_factory=list)    # Points to freeze
    dropped: set = field(default_factory=set)    # point_ids to remove


def plan_incremental(points: list, prior_points: list[dict]) -> Incremental:
    """Split this window's points against a prior pull's manifest `points`. A point is reused iff
    the prior pull holds its id with the same records; identity is immutable, so the id and its
    records alone decide. The pull itself never applies the window (api.pull already did) --
    this only reconciles against what's frozen."""
    want = {p.point_id: p for p in points}
    prior = {e["point_id"]: e for e in prior_points}
    inc = Incremental()
    for pid, p in want.items():
        if pid in prior and prior[pid].get("records") == p.records:
            inc.reuse[pid] = prior[pid]
        else:
            inc.fresh.append(p)
    inc.dropped = set(prior) - set(want)
    # Freeze fresh points in point-id order, so a pull is order-stable.
    inc.fresh.sort(key=lambda p: p.point_id)
    return inc


def prune_point_files(out: Path, point_id: str) -> None:
    """Remove an aged-out point's frozen files (its points/<id>/ directory). The store keeps only
    the current window (used when pruning an ephemeral work dir's aged-out points)."""
    import shutil
    shutil.rmtree(out / "points" / point_id, ignore_errors=True)


def load_prior_manifest(prior: Path) -> dict | None:
    """A prior frozen pull's manifest, or None if there isn't one to extend."""
    m = prior / "manifest.json"
    if not m.is_file():
        return None
    return json.loads(m.read_text())
