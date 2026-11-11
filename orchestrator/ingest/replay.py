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

Two inputs beyond the scenario's locked ones are read from the export and passed:
trace_idle_gap_cap_seconds (the dataset's per-trajectory idle cap, 300 s in every run
InferenceX has made) as the workload spec's trace_idle_gap_cap_s, and warmup_requests_per_lane
(10) as warmup {mode: cache_pressure, requests_per_lane}. inference-sim closed #1971 on
2026-10-24 by implementing both (cmd/replay_agentx.go). Both are recorded on the point.
What the point still differs in is named by `client_differences` below (client build,
which the export does not identify beyond the string "0.12.0").
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
    "--max-context-length": ("max_context_length", int),
    "--trace-idle-gap-cap-seconds": ("trace_idle_gap_cap_s", float),
    "--warmup-requests-per-lane": ("warmup_requests_per_lane", int),
}


# Every key a profiling phase / dataset / endpoint can carry, and what the extractor does with
# it. A key not listed refuses the point (client_scenario_not_replayable:<where>.<key>), so a client
# input added later can't silently change the workload BLIS replays.
#   read        passed to BLIS (or checked against the one value BLIS's scenario locks)
#   inert       no effect on what is sent or when
PHASE_KEYS = {
    "name": "inert", "kind": "inert", "type": "read", "timing_mode": "read", "concurrency": "read",
    "duration": "read", "grace_period": "read", "trajectory_start_min_ratio": "read",
    "trajectory_start_max_ratio": "read", "system_idle_gap_cap_seconds": "read",
    "failed_request_threshold": "inert",        # when the client aborts; a scored run didn't
    "agentic_warmup_grace_period": "inert",     # how long warm-up may take before aborting
    "warmup_requests_per_lane": "read",
}
DATASET_KEYS = {
    "name": "inert", "type": "read", "dataset": "read", "random_seed": "read",
    "entries": "inert",                         # the corpus' own trace count (393), not a sample
    "max_context_length": "read",               # the client's trace filter, a token count
    "trace_idle_gap_cap_seconds": "read",
}
ENDPOINT_KEYS = {"urls": "inert", "type": "read", "path": "inert", "streaming": "read",
                 "use_server_token_count": "inert"}


def _unknown_keys(where: str, doc: dict, known: dict) -> list[str]:
    return [f"client_scenario_not_replayable:{where}.{k}" for k in sorted(doc) if k not in known]


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
    max_context_length: int | None = None  # the client's trace filter; None: it filtered nothing
    system_idle_cap_s: float | None = None
    trace_idle_gap_cap_s: float | None = None   # dataset.trace_idle_gap_cap_seconds, passed to BLIS
    warmup_requests_per_lane: int | None = None  # phase.warmup_requests_per_lane, passed to BLIS
    reasons: list = field(default_factory=list)

    def record(self, corpus_sha256: str) -> dict:
        rec = {"client": "aiperf", "client_version": self.client_version, "scenario": self.scenario,
               "replayed_as": self.replayed_as, "concurrency": self.concurrency,
               "duration_s": self.duration_s, "corpus": self.corpus, "corpus_sha256": corpus_sha256,
               "seed": self.seed, "trace_idle_gap_cap_s": self.trace_idle_gap_cap_s,
               "warmup_requests_per_lane": self.warmup_requests_per_lane,
               "system_idle_gap_cap_s": self.system_idle_cap_s, "grace_period_s": self.grace_s,
               "max_context_length": self.max_context_length}
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
    r.trace_idle_gap_cap_s = ds.get("trace_idle_gap_cap_seconds")
    r.warmup_requests_per_lane = ph.get("warmup_requests_per_lane")
    for name, v, integral in (("trace_idle_gap_cap_s", r.trace_idle_gap_cap_s, False),
                              ("warmup_requests_per_lane", r.warmup_requests_per_lane, True)):
        if v is None:
            continue
        ok = isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 and (not integral or float(v) == int(v))
        if not ok:
            r.reasons.append(f"client_scenario_not_replayable:{name}")
    r.seed = ds.get("random_seed")
    r.corpus = ds.get("dataset")
    r.entries = ds.get("entries")
    r.max_context_length = ds.get("max_context_length")
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
        r.reasons.append("client_scenario_not_replayable:system_idle_gap_cap_seconds")
    if ep.get("streaming") is False:
        r.reasons.append("client_scenario_not_replayable:streaming_off")
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


CLIENT_SUBJECT = "aiperf agentx replay"
# The tag BLIS transcribes (ai-dynamo/aiperf v0.12.0).
TRANSCRIBED_TAG_COMMIT = "be53bf29"


def client_differences(r: Replay) -> list[dict]:
    """Every difference between the client that ran and the one BLIS replays that the point
    cannot rule out, each named on the point (grade G2, kind client_difference; design 11.3).

    client_build: the export records only the version string. InferenceX pins SemiAnalysisAI's
    aiperf fork, which reports the same "0.12.0"; BLIS transcribes the ai-dynamo tag (commit
    be53bf29). The fork changes the warm-up handoff, the warm-up lead cap and the first
    minutes' idle shift, so the ramp can differ. The fork commit a run used is the
    utils/aiperf gitlink of that run's InferenceX commit; the pull does not record it for
    agentic runs, so the point cannot name it. Nothing proves the replay equal to the fork's,
    so the difference is always named."""
    return [{"kind": "client_difference", "subject": "client_build",
             "detail": f"the export states aiperf {r.client_version or 'version unrecorded'}; InferenceX pins "
                       f"SemiAnalysisAI's aiperf fork, BLIS transcribes ai-dynamo/aiperf v0.12.0 "
                       f"({TRANSCRIBED_TAG_COMMIT}); the fork's warm-up handoff and ramp differ, "
                       f"and the point does not record the fork commit"}]


def workload_spec(r: Replay, corpus: dict) -> dict:
    """The blis-schemas Replay document (--workload-spec) for the run's inputs. `corpus` is the
    catalog replay workload entry of the alias the run loaded (resolve_agentic_corpus): it pins
    the corpus by repository, revision and full sha256."""
    spec = {
        "scenario": r.replayed_as,
        "harness_version": BLIS_HARNESS,
        "corpus": {"loader": r.corpus, "format": "weka-trace-v7", "encoding": "jsonl",
                   "source": {"huggingface": corpus["repo"], "revision": corpus["revision"],
                              "file": corpus["file"]},
                   "sha256": corpus["sha256"]},
        "random_seed": int(r.seed),
        "benchmark_duration_s": float(r.duration_s),
        "concurrency": int(r.concurrency),
    }
    if r.corpus_split or corpus.get("split"):
        spec["corpus"]["source"]["split"] = r.corpus_split or corpus["split"]
    # The client's trace filter, as it recorded it. An unset one filtered nothing, and is left
    # unset. It is a token count, never the deployment's max_model_len, which the scenario states.
    if r.max_context_length is not None:
        spec["max_context_length"] = int(r.max_context_length)
    if r.grace_s is not None:
        spec["grace_period_s"] = float(r.grace_s)
    if r.system_idle_cap_s is not None:
        spec["system_idle_gap_cap_s"] = float(r.system_idle_cap_s)
    if r.trace_idle_gap_cap_s is not None:
        spec["trace_idle_gap_cap_s"] = float(r.trace_idle_gap_cap_s)
    if r.warmup_requests_per_lane is not None:
        spec["warmup"] = {"mode": "cache_pressure", "requests_per_lane": int(r.warmup_requests_per_lane)}
    ts = {k: float(v) for k, v in (("min_ratio", r.trajectory_min), ("max_ratio", r.trajectory_max)) if v is not None}
    if ts:
        spec["trajectory_start"] = ts
    return spec
