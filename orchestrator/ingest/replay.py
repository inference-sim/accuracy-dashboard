"""What an agentic run's client replayed, and how BLIS replays it (Discussion #28, "Replay
inputs (agentic)").

The AgentX client (aiperf, or agentx-harness, its SemiAnalysis build) writes the run's
resolved configuration, after its scenario's defaults, to
aiperf_artifacts/profile_export_aiperf.json -> input_config. That is the authoritative
source. benchmark_command.txt and the API row's `conc` are cross-checks: any flag the command
line states, and the row's concurrency, must agree with the export.

`agentx` (agentx-harness >= 1.0.10) is a defaults-only copy of `inferencex-agentx-mvp`, the
scenario BLIS replays; each run's own values are passed explicitly, so the two replay alike.
Any other scenario is client_scenario_not_replayable.

Not passed, and not recorded per point: trace_idle_gap_cap_seconds and
warmup_requests_per_lane. BLIS can't state either yet (inference-sim#1971), and the points
are scored without them (Discussion #28).
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass, field

REPLAYABLE = {"agentx": "inferencex-agentx-mvp", "inferencex-agentx-mvp": "inferencex-agentx-mvp"}
# The harness release whose scenario behaviour BLIS transcribes (blis-schemas Replay).
BLIS_HARNESS = "0.12.0"
# The global idle cap BLIS's transcription locks (blis-schemas replay.go SystemIdleGapCapS).
LOCKED_SYSTEM_IDLE_CAP_S = 10.0

# Command-line flag -> the export field it states (only flags that set a replay input).
_FLAGS = {
    "--concurrency": ("concurrency", int),
    "--benchmark-duration": ("duration_s", float),
    "--random-seed": ("seed", int),
    "--trajectory-start-min-ratio": ("trajectory_min", float),
    "--trajectory-start-max-ratio": ("trajectory_max", float),
    "--scenario": ("scenario", str),
    "--public-dataset": ("corpus", str),
    "--benchmark-grace-period": ("grace_s", float),
}


# Every key a profiling phase / dataset / endpoint can carry, and what the extractor does with
# it. A key not listed refuses the point (unclassified_arg:replay.<key>), so a client input added
# later can't silently change the workload BLIS replays.
#   read        passed to BLIS (or checked against the one value BLIS's scenario locks)
#   inert       no effect on what is sent or when
#   gap_1971    the two AgentX inputs BLIS can't state yet (inference-sim#1971): not passed, not
#               recorded, and the point is still scored (Discussion #28)
PHASE_KEYS = {
    "name": "inert", "kind": "inert", "type": "read", "timing_mode": "read", "concurrency": "read",
    "duration": "read", "grace_period": "read", "trajectory_start_min_ratio": "read",
    "trajectory_start_max_ratio": "read", "system_idle_gap_cap_seconds": "read",
    "failed_request_threshold": "inert",        # when the client aborts; a scored run didn't
    "agentic_warmup_grace_period": "inert",     # how long warm-up may take before aborting
    "warmup_requests_per_lane": "gap_1971",
}
DATASET_KEYS = {
    "name": "inert", "type": "read", "dataset": "read", "random_seed": "read",
    "entries": "inert",                         # the corpus' own trace count (393), not a sample
    "trace_idle_gap_cap_seconds": "gap_1971",
}
ENDPOINT_KEYS = {"urls": "inert", "type": "read", "path": "inert", "streaming": "read",
                 "use_server_token_count": "inert"}


def _unknown_keys(where: str, doc: dict, known: dict) -> list[str]:
    return [f"unclassified_arg:replay.{where}.{k}" for k in sorted(doc) if k not in known]


@dataclass
class Replay:
    client_version: str | None = None
    scenario: str | None = None
    replayed_as: str | None = None
    concurrency: int | None = None
    duration_s: float | None = None
    grace_s: float | None = None
    seed: int | None = None
    trajectory_min: float | None = None
    trajectory_max: float | None = None
    corpus: str | None = None              # the loader alias
    corpus_repo: str | None = None         # its HF dataset
    corpus_split: str | None = None
    entries: int | None = None
    system_idle_cap_s: float | None = None
    reasons: list = field(default_factory=list)

    def record(self, corpus_sha256: str) -> dict:
        rec = {"client": "aiperf", "client_version": self.client_version, "scenario": self.scenario,
               "replayed_as": self.replayed_as, "concurrency": self.concurrency,
               "duration_s": self.duration_s, "corpus": self.corpus, "corpus_sha256": corpus_sha256,
               "seed": self.seed}
        if self.trajectory_min is not None or self.trajectory_max is not None:
            rec["trajectory_start"] = {k: v for k, v in (("min_ratio", self.trajectory_min),
                                                         ("max_ratio", self.trajectory_max)) if v is not None}
        return {k: v for k, v in rec.items() if v is not None}


def from_export(export: dict) -> Replay:
    ic = export.get("input_config") or {}
    phases = [p for p in ic.get("phases") or [] if p.get("kind", p.get("name")) == "profiling"]
    datasets = ic.get("datasets") or []
    r = Replay(client_version=str(export.get("aiperf_version")) if export.get("aiperf_version") else None,
               scenario=ic.get("scenario"))
    if len(phases) != 1 or len(datasets) != 1:
        r.reasons.append(f"client_scenario_not_replayable:{len(phases)}_profiling_phases_{len(datasets)}_datasets")
        return r
    ph, ds = phases[0], datasets[0]
    ep = ic.get("endpoint") or {}
    r.reasons += _unknown_keys("phase", ph, PHASE_KEYS) + _unknown_keys("dataset", ds, DATASET_KEYS) \
        + _unknown_keys("endpoint", ep, ENDPOINT_KEYS)
    if ep.get("type") not in (None, "chat"):
        r.reasons.append(f"client_scenario_not_replayable:endpoint_{ep.get('type')}")
    r.concurrency = ph.get("concurrency")
    r.duration_s = ph.get("duration")
    r.grace_s = ph.get("grace_period")
    r.trajectory_min = ph.get("trajectory_start_min_ratio")
    r.trajectory_max = ph.get("trajectory_start_max_ratio")
    r.system_idle_cap_s = ph.get("system_idle_gap_cap_seconds")
    r.seed = ds.get("random_seed")
    r.corpus = ds.get("dataset")
    r.entries = ds.get("entries")
    meta = ((export.get("metadata") or {}).get("dataset") or {})
    r.corpus_repo = meta.get("hf_dataset_name")
    r.corpus_split = meta.get("hf_split")
    if meta.get("loader") and r.corpus and meta["loader"] != r.corpus:
        r.reasons.append("conflict:replay.corpus")
    if ph.get("type") != "concurrency" or ph.get("timing_mode") != "agentic_replay":
        r.reasons.append(f"client_scenario_not_replayable:{ph.get('type')}/{ph.get('timing_mode')}")
    if ds.get("type") != "public":
        r.reasons.append(f"client_scenario_not_replayable:dataset_{ds.get('type')}")
    if r.scenario not in REPLAYABLE:
        r.reasons.append(f"client_scenario_not_replayable:{r.scenario}")
    else:
        r.replayed_as = REPLAYABLE[r.scenario]
    if r.system_idle_cap_s is not None and float(r.system_idle_cap_s) != LOCKED_SYSTEM_IDLE_CAP_S:
        r.reasons.append("setting_not_modelled:replay.system_idle_gap_cap_seconds")
    if ep.get("streaming") is False:
        r.reasons.append("setting_not_modelled:replay.streaming")
    for need in ("concurrency", "duration_s", "seed", "corpus"):
        if getattr(r, need) is None:
            r.reasons.append(f"required_setting_missing:replay.{need}")
    return r


def command_flags(command: str) -> dict | None:
    """The replay inputs a client command line states; None when it can't be split."""
    try:
        argv = shlex.split(command)
    except ValueError:
        return None
    out = {}
    for i, a in enumerate(argv):
        flag, eq, val = a.partition("=")
        if flag in _FLAGS:
            if not eq:
                if i + 1 >= len(argv):
                    continue
                val = argv[i + 1]
            name, cast = _FLAGS[flag]
            try:
                out[name] = cast(val)
            except ValueError:
                out[name] = val
    return out


def cross_check(r: Replay, command: str | None, row_conc) -> None:
    """Every source that states an input must agree with the export."""
    stated = command_flags(command) if command else {}
    if stated is None:
        r.reasons.append("conflict:replay.command_unreadable")
        stated = {}
    for name, v in sorted(stated.items()):
        have = getattr(r, name)
        if have is None:
            r.reasons.append(f"conflict:replay.{name}")   # the command sets it; the export doesn't
            continue
        if isinstance(have, (int, float)) and not isinstance(have, bool):
            if float(have) != float(v):
                r.reasons.append(f"conflict:replay.{name}")
        elif str(have) != str(v):
            r.reasons.append(f"conflict:replay.{name}")
    if row_conc is not None and r.concurrency is not None and int(row_conc) != int(r.concurrency):
        r.reasons.append("conflict:replay.concurrency")
    r.reasons = sorted(set(r.reasons))


def workload_spec(r: Replay, corpus_sha256: str, corpus_revision: str, corpus_file: str) -> dict:
    """The blis-schemas Replay document (--workload-spec) for the run's inputs."""
    spec = {
        "scenario": r.replayed_as,
        "harness_version": BLIS_HARNESS,
        "corpus": {"loader": r.corpus, "format": "weka-trace-v7", "encoding": "jsonl",
                   "source": {"huggingface": r.corpus_repo, "revision": corpus_revision,
                              "file": corpus_file},
                   "sha256": corpus_sha256},
        "random_seed": int(r.seed),
        "benchmark_duration_s": float(r.duration_s),
        "concurrency": int(r.concurrency),
    }
    if r.corpus_split:
        spec["corpus"]["source"]["split"] = r.corpus_split
    if r.grace_s is not None:
        spec["grace_period_s"] = float(r.grace_s)
    if r.system_idle_cap_s is not None:
        spec["system_idle_gap_cap_s"] = float(r.system_idle_cap_s)
    ts = {k: float(v) for k, v in (("min_ratio", r.trajectory_min), ("max_ratio", r.trajectory_max)) if v is not None}
    if ts:
        spec["trajectory_start"] = ts
    return spec
