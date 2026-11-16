"""Red Hat's configiq units, as the scoring harness reads them (design §10.1-10.3, COV-7, COV-10, COV-12).

The ledger (blis-substrate catalog/ledger) lists each configiq unit: its identity, role key and the source rows
that measure it (`units/configiq.jsonl.gz`, `reports/configiq.yaml`), and pins the dataset revision and the
SHA-256 of each of its files (`sources.yaml`, source `configiq`). This module reads those files strictly, reads the
dataset's rows at that revision, recomputes every row's identity and requires it to give the unit_id the ledger
names, and turns each unit into a point: what was measured, how it compares, and why it can or cannot be graded.

The dataset holds aggregates only, one row per configuration and concurrency, with no per-request data. So a point
carries the percentiles the row recorded and nothing else: no percentile that was not measured is ever derived.
Rows come in two kinds:

  whole-run rows   carry `measured concurrency`. Repeats of a unit (two whole-run rows) are averaged only when they
                   agree (COV-10): successful requests and every compared metric within 20% of their mean. They are
                   never credited as noise, because no image digest is recorded. A disagreement is value_conflict.
  turn slices      the per-turn breakdown of a multi-turn run (no `measured concurrency`; the dataset drops the turn
                   index). They are kept on the point as a diagnostic input for the event-level comparison and never
                   graded or pooled.

The engine columns (gpu_memory_utilization, max_num_seqs, max_seq_len, chunked_prefill_enabled, precision,
weight_quantization, kv_quantization) are parsed by the publisher from the run's command line, which it then drops:
a blank there means not recorded, never the engine's default (COV-10). Nothing in this module defaults a value.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import contract

SOURCE = "configiq"
# blis-substrate ledger/configiq/configiq.go, IdentityColumns: the identity is the source and these columns.
IDENTITY_COLUMNS = (
    "pair_id", "model", "model_id", "accelerator", "backend", "version", "backend_version",
    "tp", "isl", "osl", "concurrency", "turns", "prefix_tokens", "prefix_count",
    "prefix_caching", "request_type", "spec_decoding", "gpu_memory_utilization",
    "max_num_seqs", "max_seq_len", "chunked_prefill_enabled", "precision",
    "weight_quantization", "kv_quantization",
)
MEASURED_COLUMNS = (
    "measured concurrency", "measured rps", "output_tok/sec", "total_tok/sec",
    "prompt_token_count_mean", "prompt_token_count_p99", "output_token_count_mean", "output_token_count_p99",
    "ttft_mean", "ttft_median", "ttft_p1", "ttft_p95", "ttft_p99", "ttft_p999",
    "tpot_median", "tpot_p1", "tpot_p95", "tpot_p99", "tpot_p999",
    "itl_mean", "itl_median", "itl_p1", "itl_p95", "itl_p99", "itl_p999",
    "request_latency_median", "request_latency_min", "request_latency_max",
    "successful_requests", "errored_requests",
)

# What each recorded statistic is, by GuideLLM's own definitions (vllm-project/guidellm
# src/guidellm/schemas/base/request_stats.py at 3973120daa90fd50b52e08d1b6332772931cbdd3), and the BLIS figure it is
# compared with. GuideLLM's tpot includes the first token: (last token - request start) / output tokens, so it is
# compared with E2E per output token, never with a TPOT. Its itl, (last - first) / (output tokens - 1) per request,
# is the per-request TPOT that InferenceX and vLLM bench call tpot. Values are converted to milliseconds.
METRICS = {
    "ttft": {"blis": "ttft", "definition": "time to first token, per request", "unit_ms": 1.0},
    "itl": {"blis": "itl_per_request", "definition": "(last token - first token) / (output tokens - 1), per request",
            "unit_ms": 1.0},
    "tpot": {"blis": "e2e_per_output_token",
             "definition": "(last token - request start) / output tokens, per request; includes the first token",
             "unit_ms": 1.0},
    "request_latency": {"blis": "e2e", "definition": "request latency, per request", "unit_ms": 1000.0},
}
# The statistics a family records, by column suffix. Only these are compared; none is derived.
STATS = {"ttft": ("mean", "median", "p1", "p95", "p99", "p999"),
         "itl": ("mean", "median", "p1", "p95", "p99", "p999"),
         "tpot": ("median", "p1", "p95", "p99", "p999"),
         "request_latency": ("median", "min", "max")}
# GuideLLM's itl and tpot means are weighted by output tokens (its docs/guides/metrics.md), not means over requests.
TOKEN_WEIGHTED_MEANS = ("itl_mean",)

AGREEMENT = 0.20
# The figures two whole-run rows of one unit must agree on before their mean is scored (COV-10).
AGREEMENT_COLUMNS = ("successful_requests", "ttft_median", "ttft_p95", "itl_median", "itl_p95", "tpot_median",
                     "request_latency_median", "output_tok/sec")

# AMD chips are out of scope until after M4 (inference-sim/blis-substrate#210).
CHIPS_NOT_MODELLED = {"MI300X": "inference-sim/blis-substrate#210", "MI325X": "inference-sim/blis-substrate#210",
                      "MI355X": "inference-sim/blis-substrate#210"}
CHIP_NOT_MODELLED = "chip_not_modelled"
# Design §11.4's order. The scope reasons come first, ahead of every data reason, so the backlog shows a missing chip
# or model as the gap BLIS can close: chip_not_modelled, then not_in_catalog (blis-design#14).
G5_ORDER = (CHIP_NOT_MODELLED, "not_in_catalog", "code_not_visible", "router_unsupported", "topology_unsupported",
            "value_not_recorded", "field_not_modelled", "field_unclassified", "engine_unsupported",
            "field_not_in_release", "value_conflict", "build_unparseable")

# The engine settings the publisher parses from the command line. A blank is value_not_recorded.
ENGINE_COLUMNS = ("gpu_memory_utilization", "max_num_seqs", "max_seq_len", "chunked_prefill_enabled", "precision",
                  "kv_quantization")
# The frame fields COV-10 needs and the dataset never records (the publisher drops guidellm_version, runtime_args
# and the start and end times). GuideLLM's stop rule (--max-seconds / --max-requests) has no default at any release,
# so it cannot be documented; the others depend on a release no row records.
FRAME_NOT_RECORDED = ("frame.stop_rule", "frame.warmup", "frame.measured_window", "client.release")

# The provisional band (COV-7, blis-design#14). The rows were published by openshift-psap/forge's projects/rhaiis,
# among other writers of the same CSV, and record neither their launcher nor their date. A row is consistent with
# forge when it equals one resolved forge preset (FORGE_PRESETS) in every parsed engine column and in TP, and that
# preset was current on or after the row's engine release was published. No preset of these models sets data,
# expert or pipeline parallelism in any commit.
FORGE = ("openshift-psap/forge projects/rhaiis/orchestration/config.d/models.yaml, all 17 commits from "
         "117e2386a31f14c6d00f7fc6da74a2426940216e to 5f6603b77c558d68e965a87ca127169c077ae163")
FORGE_BASE_ARGS = ("openshift-psap/forge projects/rhaiis/orchestration/config.d/rhaiis.yaml engines.vllm.args, "
                   "from b61e356becaaa72727dda419f768ee17e1f0e0be to 5bdf971139c235c26ed1a09b9c8015161037ad3f: "
                   "gpu-memory-utilization 0.92, trust-remote-code, no-enable-log-requests, no-enable-prefix-caching "
                   "unless a preset enables it, uvicorn-log-level debug")
FORGE_HISTORY_START = "2026-06-02"
# Every distinct resolved forge preset of the models configiq covers, as the dataset's parsed columns would show
# it (a flag the preset does not pass is None), with the period it was current ("from" its first commit "to" the
# next change, or the dataset revision's date) and the first commit that states it. Read from every commit of
# config.d/models.yaml and config.d/rhaiis.yaml; none sets data, expert or pipeline parallelism.
FORGE_PRESETS = (
    {"model_id": "RedHatAI/gemma-4-26B-A4B-it-FP8-dynamic", "tp": 2, "kv_quantization": "fp8", "max_seq_len": None, "max_num_seqs": None, "precision": None, "chunked_prefill_enabled": None, "gpu_memory_utilization": "0.92", "from": "2026-09-22", "to": "2026-09-22", "commit": "8f0ede3f3780699156a10f0f620bf5b0cb467af1"},
    {"model_id": "RedHatAI/gemma-4-26B-A4B-it-FP8-dynamic", "tp": 2, "kv_quantization": None, "max_seq_len": None, "max_num_seqs": None, "precision": None, "chunked_prefill_enabled": None, "gpu_memory_utilization": "0.92", "from": "2026-08-17", "to": "2026-11-16", "commit": "cd089e736259548bdc99a4a29668350aa39ab05a"},
    {"model_id": "deepseek-ai/DeepSeek-V4-Pro", "tp": 8, "kv_quantization": "fp8", "max_seq_len": None, "max_num_seqs": None, "precision": None, "chunked_prefill_enabled": None, "gpu_memory_utilization": "0.92", "from": "2026-09-22", "to": "2026-09-22", "commit": "8f0ede3f3780699156a10f0f620bf5b0cb467af1"},
    {"model_id": "deepseek-ai/DeepSeek-V4-Pro", "tp": 8, "kv_quantization": None, "max_seq_len": None, "max_num_seqs": None, "precision": None, "chunked_prefill_enabled": None, "gpu_memory_utilization": "0.92", "from": "2026-06-09", "to": "2026-11-16", "commit": "117e2386a31f14c6d00f7fc6da74a2426940216e"},
    {"model_id": "deepseek-ai/DeepSeek-V4-Pro", "tp": 8, "kv_quantization": None, "max_seq_len": None, "max_num_seqs": None, "precision": None, "chunked_prefill_enabled": None, "gpu_memory_utilization": None, "from": "2026-06-09", "to": "2026-06-09", "commit": "117e2386a31f14c6d00f7fc6da74a2426940216e"},
    {"model_id": "google/gemma-4-31B-it", "tp": 1, "kv_quantization": None, "max_seq_len": None, "max_num_seqs": None, "precision": None, "chunked_prefill_enabled": None, "gpu_memory_utilization": "0.92", "from": "2026-09-22", "to": "2026-11-16", "commit": "8f0ede3f3780699156a10f0f620bf5b0cb467af1"},
    {"model_id": "moonshotai/Kimi-K3", "tp": 8, "kv_quantization": None, "max_seq_len": None, "max_num_seqs": None, "precision": None, "chunked_prefill_enabled": None, "gpu_memory_utilization": "0.92", "from": "2026-09-22", "to": "2026-11-16", "commit": "8f0ede3f3780699156a10f0f620bf5b0cb467af1"},
    {"model_id": "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-FP8", "tp": 2, "kv_quantization": "fp8", "max_seq_len": None, "max_num_seqs": None, "precision": None, "chunked_prefill_enabled": None, "gpu_memory_utilization": "0.92", "from": "2026-09-22", "to": "2026-09-22", "commit": "8f0ede3f3780699156a10f0f620bf5b0cb467af1"},
    {"model_id": "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-FP8", "tp": 2, "kv_quantization": None, "max_seq_len": None, "max_num_seqs": None, "precision": None, "chunked_prefill_enabled": None, "gpu_memory_utilization": "0.92", "from": "2026-08-07", "to": "2026-11-16", "commit": "2e0f8dd3f01c30b0af3e6a7616c38479fc6fda51"},
    {"model_id": "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-FP8", "tp": 4, "kv_quantization": None, "max_seq_len": None, "max_num_seqs": None, "precision": None, "chunked_prefill_enabled": None, "gpu_memory_utilization": "0.92", "from": "2026-06-09", "to": "2026-08-07", "commit": "117e2386a31f14c6d00f7fc6da74a2426940216e"},
    {"model_id": "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-FP8", "tp": 4, "kv_quantization": None, "max_seq_len": None, "max_num_seqs": None, "precision": None, "chunked_prefill_enabled": None, "gpu_memory_utilization": None, "from": "2026-06-09", "to": "2026-06-09", "commit": "117e2386a31f14c6d00f7fc6da74a2426940216e"},
    {"model_id": "openai/gpt-oss-120b", "tp": 1, "kv_quantization": None, "max_seq_len": None, "max_num_seqs": None, "precision": None, "chunked_prefill_enabled": None, "gpu_memory_utilization": "0.92", "from": "2026-06-09", "to": "2026-11-16", "commit": "117e2386a31f14c6d00f7fc6da74a2426940216e"},
    {"model_id": "openai/gpt-oss-120b", "tp": 1, "kv_quantization": None, "max_seq_len": None, "max_num_seqs": None, "precision": None, "chunked_prefill_enabled": None, "gpu_memory_utilization": None, "from": "2026-06-09", "to": "2026-06-09", "commit": "117e2386a31f14c6d00f7fc6da74a2426940216e"},
)

# Publication dates of the vLLM releases the dataset names from forge's start on (github.com/vllm-project/vllm
# releases; v0.33.0's tag object). A release not listed predates forge.
VLLM_RELEASED = {"vLLM-0.23.0": "2026-06-15", "vLLM-0.24.0": "2026-06-29", "vLLM-0.26.0": "2026-07-27",
                 "vLLM-0.27.0": "2026-08-10", "vLLM-0.28.0": "2026-08-26", "vLLM-0.29.0": "2026-09-09",
                 "vLLM-0.30.0": "2026-09-22", "vLLM-0.31.0": "2026-10-05", "vLLM-0.32.0": "2026-10-18",
                 "vLLM-0.33.0": "2026-11-01"}
PROVISIONAL_CAP = "G3"
PROVISIONAL_SUBSTITUTIONS = (
    {"kind": "provisional_parallelism", "subject": "parallelism",
     "detail": "no data or expert parallelism: no preset of the model sets either, in " + FORGE},
    {"kind": "provisional_blank_flags", "subject": "engine flags the row leaves blank",
     "detail": "a blank parsed engine column means the preset did not pass that flag (forge-consistent rows only); "
               + FORGE + "; " + FORGE_BASE_ARGS},
    {"kind": "provisional_frame", "subject": "frame",
     "detail": "stop rule, warm-up, measured window and client release unknown; the dataset drops them"},
)
# The G5 reasons a provisional point's substitutions stand in for: everything the launcher's presets or the
# frame would have recorded. Any other reason keeps the point G5.
PROVISIONAL_COVERS = ("parallelism", "engine ", "frame.", "client.")

UNIT_KEYS = {"unit_id", "role_key", "identity", "measurements"}
MEASUREMENT_KEYS = {"record", "measured", "duplicates", "merged", "recorded"}
REPORT_KEYS = {"kind", "source", "revision", "input", "records", "units", "role_keys", "duplicates", "merged",
               "joined_units", "joined_records", "left_out", "units_by_framework"}


class ConfigiqError(ValueError):
    """The ledger files, the dataset revision, or a row checked against them, are not what the harness requires."""


def _strict(obj, keys: set, where: str) -> dict:
    if not isinstance(obj, dict):
        raise ConfigiqError(f"{where}: not an object")
    extra, missing = set(obj) - keys, keys - set(obj)
    if extra or missing:
        raise ConfigiqError(f"{where}: unexpected keys {sorted(extra)}, missing {sorted(missing)}")
    return obj


def _identity_value(value, column: str):
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and math.isnan(value):
            return None
        if float(value) != math.trunc(float(value)) or abs(value) > 2 ** 53:
            raise ConfigiqError(f"column {column!r}: {value!r} is not a whole number")
        return int(value)
    raise ConfigiqError(f"column {column!r}: a {type(value).__name__} is not an identifying value")


def identity(columns: dict) -> dict:
    """A row's identity, in the ledger's canonical form: null stays null, a string is kept, a whole number is an
    integer whatever the file's column type."""
    missing = [c for c in IDENTITY_COLUMNS if c not in columns]
    if missing:
        raise ConfigiqError(f"row lacks identifying columns {missing}")
    out = {"source": SOURCE}
    for c in IDENTITY_COLUMNS:
        out[c] = _identity_value(columns[c], c)
    return out


def unit_id(ident: dict) -> str:
    return hashlib.sha256(contract.canonical_dumps(ident).encode("utf-8")).hexdigest()


@dataclass
class Unit:
    unit_id: str
    role_key: str
    identity: dict
    measurements: list

    def records(self) -> list[str]:
        out = []
        for m in self.measurements:
            out.append(m["record"])
            out += m["duplicates"]
            out += [x["record"] for x in m["merged"]]
        return out


@dataclass
class Ledger:
    units: dict = field(default_factory=dict)        # unit_id -> Unit
    by_record: dict = field(default_factory=dict)    # "path:row" -> (Unit, own unit_id)
    left_out: dict = field(default_factory=dict)     # "path:row" -> reason
    revision: str = ""
    assets: dict = field(default_factory=dict)       # file name -> sha256


def load(units_path: Path, report_path: Path, sources_path: Path) -> Ledger:
    """The configiq units, left-out rows and pinned files, from the ledger's unit list
    (catalog/ledger/units/configiq.jsonl.gz), ingest report (reports/configiq.yaml) and sources.yaml. The caller
    names the files, so the read is listed once at its site (X7, lint_blis_boundary.DATA_READS)."""
    import yaml
    lg = Ledger()
    raw = gzip.decompress(Path(units_path).read_bytes()).decode("utf-8")
    for n, line in enumerate(raw.splitlines(), 1):
        u = _strict(json.loads(line), UNIT_KEYS, f"{units_path}:{n}")
        for i, m in enumerate(u["measurements"]):
            _strict(m, MEASUREMENT_KEYS, f"{units_path}:{n}: measurements[{i}]")
        unit = Unit(u["unit_id"], u["role_key"], u["identity"], u["measurements"])
        if unit_id(unit.identity) != unit.unit_id:
            raise ConfigiqError(f"unit {unit.unit_id}: its identity hashes to another id")
        if unit.unit_id in lg.units:
            raise ConfigiqError(f"unit {unit.unit_id} is listed twice")
        lg.units[unit.unit_id] = unit
        for m in unit.measurements:
            for rid, own in [(m["record"], unit.unit_id)] + [(x, unit.unit_id) for x in m["duplicates"]] + \
                    [(x["record"], x["unit_id"]) for x in m["merged"]]:
                if rid in lg.by_record:
                    raise ConfigiqError(f"record {rid} is in two units")
                lg.by_record[rid] = (unit, own)
    rep = _strict(yaml.safe_load(Path(report_path).read_text()), REPORT_KEYS, str(report_path))
    if rep["source"] != SOURCE:
        raise ConfigiqError(f"{report_path}: source {rep['source']!r}")
    lg.revision = str(rep["revision"])
    for reason, ids in sorted((rep["left_out"] or {}).items()):
        for rid in ids:
            lg.left_out[str(rid)] = reason
    sources = yaml.safe_load(Path(sources_path).read_text())
    src = [s for s in sources.get("sources", []) if s.get("id") == SOURCE]
    if len(src) != 1:
        raise ConfigiqError(f"sources.yaml names {len(src)} {SOURCE!r} sources, want 1")
    if src[0]["revision"]["ref"] != lg.revision:
        raise ConfigiqError(f"sources.yaml pins {src[0]['revision']['ref']}, the report was made from {lg.revision}")
    lg.assets = {a["name"]: a["sha256"] for a in src[0]["revision"].get("assets", [])}
    return lg


def check_files(lg: Ledger, data_dir: Path) -> None:
    """Refuse a download whose files are not the ones the ledger pins (D3)."""
    bad = []
    for name, want in sorted(lg.assets.items()):
        p = Path(data_dir) / name
        got = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
        if got != want:
            bad.append(f"{name}: {got or 'missing'}, pinned {want}")
    if bad:
        raise ConfigiqError("the dataset files differ from the ledger's pins: " + "; ".join(bad))


def read_rows(data_dir: Path, lg: Ledger) -> dict:
    """Every row of the pinned revision, by "path:row", read from its Parquet files after checking their hashes.
    Needs pyarrow."""
    import pyarrow.parquet as pq
    check_files(lg, data_dir)
    rows = {}
    for name in sorted(n for n in lg.assets if n.endswith(".parquet")):
        for i, rec in enumerate(pq.read_table(Path(data_dir) / name).to_pylist()):
            rows[f"{name}:{i}"] = rec
    return rows


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ConfigiqError(f"{v!r} is not a number")
    return None if math.isnan(f) else f


def _agrees(xs: list[float]) -> bool:
    m = sum(xs) / len(xs)
    return m == 0 or all(abs(x - m) / abs(m) <= AGREEMENT for x in xs)


@dataclass
class Point:
    unit_id: str
    identity: dict
    whole_runs: list            # [{"record", "values"}], values by measured column
    turn_slices: list           # [{"record", "ttft", "tpot", "itl", "successful_requests", "errored_requests"}]
    measured: dict | None       # the compared statistics, mean of agreeing whole runs, in ms; None on a conflict
    spread: dict                # per compared statistic over whole runs: {"n", "min", "max"}; reported, not credited
    g5: list                    # [{"code", "subject"}]
    provisional: bool = False   # scored in the provisional band, capped at PROVISIONAL_CAP, outside the headline
    preset: dict | None = None  # the forge preset a provisional point matched: its commit and period

    @property
    def g5_reason(self) -> dict | None:
        if not self.g5:
            return None
        return sorted(self.g5, key=lambda r: (G5_ORDER.index(r["code"]), r.get("subject", "")))[0]


def _compared(values: dict) -> dict:
    """The statistics a whole-run row recorded, in ms, by "<family>_<stat>". A null is left out, never filled."""
    out = {}
    for fam, stats in STATS.items():
        for s in stats:
            v = _num(values.get(f"{fam}_{s}"))
            if v is not None:
                out[f"{fam}_{s}"] = v * METRICS[fam]["unit_ms"]
    return out


def points(lg: Ledger, rows: dict, catalog: dict) -> list[Point]:
    """One point per ledger unit. rows is read_rows' output; catalog says what BLIS models, from the catalog the
    harness pins: {"models": {hf repo: {"moe": bool}}, "chips": set of accelerator names in upper case}."""
    by_unit: dict[str, list] = {}
    for rid, cols in rows.items():
        if rid in lg.left_out:
            continue
        placed = lg.by_record.get(rid)
        if placed is None:
            raise ConfigiqError(f"row {rid} is in neither the unit list nor the left-out rows of {lg.revision}")
        unit, own = placed
        got = unit_id(identity(cols))
        if got != own:
            raise ConfigiqError(f"row {rid}: its identity hashes to {got}, but the ledger gives {own}; "
                                f"the row differs from the pinned revision")
        by_unit.setdefault(unit.unit_id, []).append((rid, cols))
    missing = sorted(set(lg.units) - set(by_unit))
    if missing:
        raise ConfigiqError(f"{len(missing)} ledger units have no row, first {missing[0]}")
    out = []
    for uid in sorted(by_unit):
        unit = lg.units[uid]
        kept = {m["record"] for m in unit.measurements}
        whole, slices = [], []
        for rid, cols in sorted(by_unit[uid]):
            if rid not in kept:
                continue  # a duplicate repeats a kept row's values exactly
            values = {c: cols.get(c) for c in MEASURED_COLUMNS}
            if _num(values["measured concurrency"]) is not None:
                whole.append({"record": rid, "values": values})
            else:
                slices.append({"record": rid, "ttft": {s: _num(values.get(f"ttft_{s}")) for s in STATS["ttft"]},
                               "tpot": {s: _num(values.get(f"tpot_{s}")) for s in STATS["tpot"]},
                               "itl": {s: _num(values.get(f"itl_{s}")) for s in STATS["itl"]},
                               "successful_requests": _num(values["successful_requests"]),
                               "errored_requests": _num(values["errored_requests"])})
        if not whole:
            raise ConfigiqError(f"unit {uid}: no whole-run row (every row lacks measured concurrency)")
        g5 = gates(unit.identity, catalog)
        per = [_compared(w["values"]) for w in whole]
        spread = {}
        for k in sorted(set().union(*per)):
            xs = [p[k] for p in per if k in p]
            spread[k] = {"n": len(xs), "min": min(xs), "max": max(xs)}
        measured = None
        if len(whole) > 1:
            for c in AGREEMENT_COLUMNS:
                xs = [_num(w["values"].get(c)) for w in whole]
                if None in xs or not _agrees(xs):
                    g5.append({"code": "value_conflict", "subject": f"repeat runs disagree on {c}: "
                               + ", ".join(w["record"] for w in whole)})
                    break
        if not any(r["code"] == "value_conflict" for r in g5):
            keys = set.intersection(*(set(p) for p in per))
            measured = {k: sum(p[k] for p in per) / len(per) for k in sorted(keys)}
        provisional, preset = False, forge_preset(unit.identity)
        if g5 and preset is not None and all(
                r["code"] == "value_not_recorded" and r["subject"].startswith(PROVISIONAL_COVERS) for r in g5):
            g5, provisional = [], True
        out.append(Point(uid, unit.identity, whole, slices, measured, spread, g5, provisional,
                         {k: preset[k] for k in ("commit", "from", "to")} if provisional else None))
    return out


def forge_preset(ident: dict) -> dict | None:
    """The forge preset a row equals in every parsed column, current on or after the row's engine release was
    published (FORGE_PRESETS), or None. Of several, the one current longest is named, so a thin match shows only
    when no other exists."""
    released = VLLM_RELEASED.get(ident["backend_version"])
    if released is None or released < FORGE_HISTORY_START:
        return None
    row = {"model_id": ident["model_id"], "tp": ident["tp"],
           "kv_quantization": None if ident["kv_quantization"] in (None, "", "unknown") else ident["kv_quantization"],
           "max_seq_len": ident["max_seq_len"], "max_num_seqs": ident["max_num_seqs"], "precision": ident["precision"],
           "chunked_prefill_enabled": ident["chunked_prefill_enabled"],
           "gpu_memory_utilization": ident["gpu_memory_utilization"]}
    hits = [p for p in FORGE_PRESETS if all(p[k] == v for k, v in row.items()) and p["to"] >= released]
    if not hits:
        return None
    return max(hits, key=lambda p: (date.fromisoformat(p["to"]) - date.fromisoformat(p["from"]), p["commit"]))


def gates(ident: dict, catalog: dict) -> list[dict]:
    """The G5 reasons a unit has before any simulation, each {"code", "subject"} (design §11.4)."""
    out = []
    chip = ident["accelerator"]
    if chip in CHIPS_NOT_MODELLED:
        out.append({"code": CHIP_NOT_MODELLED, "subject": f"{chip} ({CHIPS_NOT_MODELLED[chip]})"})
    elif chip not in catalog["chips"]:
        out.append({"code": "not_in_catalog", "subject": f"chip {chip}"})
    model = catalog["models"].get(ident["model_id"])
    if model is None:
        out.append({"code": "not_in_catalog", "subject": f"model {ident['model_id']}"})
    elif model["moe"] and (ident["tp"] or 0) > 1:
        out.append({"code": "value_not_recorded", "subject": "parallelism (data and expert parallel)"})
    if not ident["isl"] or not ident["osl"]:
        out.append({"code": "value_not_recorded", "subject": "workload prompt and output lengths"})
    if ident["prefix_caching"] in (None, ""):
        out.append({"code": "value_not_recorded", "subject": "prefix caching (not a parsed engine column)"})
    for c in ENGINE_COLUMNS:
        if ident[c] in (None, "", "unknown"):
            out.append({"code": "value_not_recorded", "subject": f"engine {c}"})
    for f in FRAME_NOT_RECORDED:
        out.append({"code": "value_not_recorded", "subject": f})
    return out


def record(p: Point) -> dict:
    """The point's record for the summary and the event-level suite: its identity, what it compares, the repeats'
    spread, the turn slices, and its G5 reasons. The breakdown facets are the source, engine release, chip and
    model (COV-7)."""
    first = p.g5_reason
    return {"source": SOURCE, "point_id": p.unit_id, "identity": p.identity,
            "engine_release": p.identity["backend_version"], "chip": p.identity["accelerator"],
            "model": p.identity["model_id"],
            "metrics": {k: {"blis": METRICS[k]["blis"], "definition": METRICS[k]["definition"]} for k in METRICS},
            "measured": p.measured, "repeat_spread": p.spread, "whole_runs": [w["record"] for w in p.whole_runs],
            "turn_slices": p.turn_slices,
            "grade": "G5" if first else None, "g5_reason": first,
            "provisional": p.provisional, "grade_cap": PROVISIONAL_CAP if p.provisional else None,
            "substitutions": [dict(s) for s in PROVISIONAL_SUBSTITUTIONS] if p.provisional else [],
            "matched_preset": p.preset,
            "backlog": ([f"provisional on a preset current for one day ({p.preset['from']}, forge commit "
                         f"{p.preset['commit']}): the match is thin, and the raw launch arguments would settle it"]
                        if p.preset and p.preset["from"] == p.preset["to"] else []),
            "g5_reasons": sorted(p.g5, key=lambda r: (G5_ORDER.index(r["code"]), r.get("subject", "")))}
