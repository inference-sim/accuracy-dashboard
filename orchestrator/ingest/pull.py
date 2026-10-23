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
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import api  # noqa: E402
import artifacts as art  # noqa: E402
import build  # noqa: E402
import contract  # noqa: E402

IX_REPO = "SemiAnalysisAI/InferenceX"
_RUN_REPO = __import__("re").compile(r"github\.com/([^/]+/[^/]+)/actions/runs/")


def run_repo(row: dict) -> str | None:
    m = _RUN_REPO.search(str(row.get("run_url") or ""))
    return m.group(1) if m else None


def identity(row: dict) -> dict:
    return {"model": row["model"], "hardware": row["hardware"], "precision": row["precision"],
            "framework": row["framework"], "benchmark_type": row["benchmark_type"],
            "recipe": contract.recipe_key(row.get("recipe_fingerprint"), row.get("id")),
            "conc": int(row["conc"]), "measured_date": str(row["date"])[:10]}


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


def freeze_point(row: dict, *, resolver: build.Resolver, gh: art.GitHubArtifacts, fetch, out: Path,
                 run_artifacts: dict) -> dict:
    ident = identity(row)
    pid = contract.point_id(ident)
    entry = {"point_id": pid, "identity": ident, "row": row, "reasons": _row_reasons(row), "files": {}}
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
        if run_id not in run_artifacts:
            run_artifacts[run_id] = gh.list(run_id)
        arts = run_artifacts[run_id]
        j = art.join({**row, "_attempt": attempt}, arts,
                     lambda a: art.read_result_json(gh.download(a)), agentic=agentic)
        join_reasons += j.reasons
        entry["result_filename"] = j.result_filename
        if j.result_json is not None:
            frozen.put("result_json", json.dumps(j.result_json, sort_keys=True).encode(), j.result.name)
        if j.server_logs is not None:
            try:
                files = list(art.iter_files(gh.download(j.server_logs)))
            except art.Unreadable as e:
                entry["reasons"].append("server_log_missing:unreadable_artifact")
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
                entry["reasons"].append("conflict:launch_config")
                entry["problems"] = [str(e)]
                p, cfg = None, None
            if cfg is not None:
                frozen.put("launch_config", json.dumps(cfg, sort_keys=True, default=str).encode(),
                           f"{j.server_logs.name}:{p}")
        if agentic and j.agentic is not None:
            try:
                files = list(art.iter_files(gh.download(j.agentic)))
            except art.Unreadable as e:
                entry["reasons"].append("artifact_unmatched:unreadable_agentic_export")
                entry.setdefault("problems", []).append(str(e))
                files = []
            for role, base in (("client_export", "profile_export_aiperf.json"),
                               ("client_command", "benchmark_command.txt")):
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
