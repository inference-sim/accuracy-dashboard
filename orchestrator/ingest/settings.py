"""Read every setting a run recorded, decide each by the engine's field list, and build the
deployment BLIS is handed (design §11.2; COV-3).

Sources, in order; for each setting the first that states it wins:

  1. launch_config    the srt launch config's role args + env (artifact), when the run has one;
  2. args             the server log's `non-default args: {...}`;
  3. resolved_config  the server log's `Initializing a V1 LLM engine (v…) with config: …`;
  4. engine_line      lines vLLM prints even for a setting it wasn't passed (ENGINE_LINES);
  5. api_row          the InferenceX row (the router a run was measured behind).

The first two record the values passed, the next two the values resolved. Two sources of the
same stage that disagree are a conflict (G5 value_conflict). A resolved value that differs from
a passed one is not a conflict: the engine resolves its settings, and blis-vllm reproduces that.

Which fields are modelled, and each field's estimation rule, come only from the engine's field
list (fields.py, VLM-3). The dashboard holds no settings table of its own (§11.1). Engine
outcomes (the KV pool) are compared after the replay and never written here.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import inferencex_runners as ir
import pyrepr

VLLM_DEFAULTS_PATH = Path(__file__).resolve().parent.parent / "vllm_defaults.json"


def load_vllm_defaults(path: Path = VLLM_DEFAULTS_PATH) -> tuple[dict, str]:
    raw = path.read_bytes()
    return json.loads(raw)["defaults"], hashlib.sha256(raw).hexdigest()


def vllm_defaults_release(path: Path = VLLM_DEFAULTS_PATH) -> str:
    """The vLLM release the defaults table was read at, e.g. "0.32.0"."""
    return json.loads(path.read_bytes())["vllm_ref"].lstrip("v")


def defaults_for(run_release: str | None, table: dict, table_release: str) -> dict:
    """The defaults of the run's OWN release: the table when the run's banner names exactly the
    release the table was read at, else none. A table of another release says nothing about what
    the run's vLLM printed."""
    return table if run_release is not None and run_release.lstrip("v") == table_release else {}
SOURCES = ("launch_config", "args", "resolved_config", "engine_line", "api_row")

# Lines vLLM prints with what it resolved, whether or not the flag was passed. Each pattern's
# groups become (path, value). A line printed once per rank must agree across ranks.
ENGINE_LINES = (
    (re.compile(r"Setting kv cache block size to (\d+) for"), ("block_size", int)),
    (re.compile(r"Desired GPU memory utilization is \(([0-9.]+), [0-9.]+ GiB\)"), ("gpu_memory_utilization", pyrepr.Float)),
    # Builds that print no "Desired …" line (e.g. v0.25) state it in the CUDA-graph profiling
    # note: "The current --gpu-memory-utilization=0.9200 is equivalent to …".
    (re.compile(r"The current --gpu-memory-utilization=([0-9.]+) is equivalent to"), ("gpu_memory_utilization", pyrepr.Float)),
    (re.compile(r"Chunked prefill is enabled with max_num_batched_tokens=(\d+)"), ("max_num_batched_tokens", int)),
)
_RUST_FRONTEND = re.compile(r"Launching Rust frontend")
# vLLM warns about a deprecated environment variable only when it is set (envs.py deprecated_env:
# "FutureWarning: <NAME> is deprecated and will be removed ..."), so the warning is the run
# saying it set the variable, even with no launch config to show it.
_DEPRECATED_ENV = re.compile(r"FutureWarning: ([A-Z][A-Z0-9_]+) is deprecated")
_SIMPLE_OFFLOAD = re.compile(r"SimpleCPUOffloadConnector: role=\w+, per_rank=([0-9.]+) GB, world_size=(\d+)")
_ARGS = "non-default args: {"
_RESOLVED = re.compile(r"Initializing a V1 LLM engine \(v[^)]*\) with config: (.*)")


# ------------------------------------------------------------------ reading each source

def flatten(value, prefix: str = "") -> dict:
    """{'a': {'b': 1}} -> {'a.b': 1}. Lists stay whole; an empty dict is no setting."""
    out = {}
    if isinstance(value, dict):
        for k, v in value.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    else:
        out[prefix] = value
    return out


def _balanced(text: str, start: int) -> str | None:
    depth, quote, escaped = 0, None, False
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            # Inside a string literal, a backslash escapes the next character (\' doesn't close).
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


@dataclass
class Reading:
    """One source's settings: path -> list of values found (several when lines repeat)."""
    values: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)

    def add(self, path, value):
        self.values.setdefault(path, []).append(value)


def read_args(log: str) -> Reading:
    r = Reading()
    i = log.find(_ARGS)
    seen = set()
    while i >= 0:
        body = _balanced(log, i + len(_ARGS) - 1)
        if body is None:
            r.problems.append("args: unterminated non-default args")
            break
        if body not in seen:
            seen.add(body)
            try:
                for k, v in flatten(pyrepr.parse(body)).items():
                    r.add(k, v)
            except pyrepr.ReprError as e:
                r.problems.append(f"args: {e}")
        i = log.find(_ARGS, i + 1)
    return r


def read_resolved(log: str) -> Reading:
    r = Reading()
    for line in sorted(set(_RESOLVED.findall(log))):
        try:
            parsed = pyrepr.parse_kwargs(line)
        except pyrepr.ReprError as e:
            r.problems.append(f"resolved_config: {e}")
            continue
        for k, v in flatten(parsed).items():
            r.add(k, v)
    # Paths whose name differs between args and the resolved line.
    if "max_seq_len" in r.values:
        r.values.setdefault("max_model_len", r.values["max_seq_len"])
    if "speculative_config.num_spec_tokens" in r.values:
        r.values.setdefault("speculative_config.num_speculative_tokens", r.values["speculative_config.num_spec_tokens"])
    return r


def read_engine_lines(log: str) -> Reading:
    r = Reading()
    for pattern, (path, cast) in ENGINE_LINES:
        for m in pattern.finditer(log):
            r.add(path, cast(m.group(1)))
    if _RUST_FRONTEND.search(log):
        r.add("env.VLLM_USE_RUST_FRONTEND", True)
    for name in sorted(set(_DEPRECATED_ENV.findall(log))):
        # The value isn't printed, only that it was set (decide refuses to copy it).
        r.add(f"env.{name}", True)
    for m in _SIMPLE_OFFLOAD.finditer(log):
        # vLLM prints GiB under the "GB" label (bytes / 1024**3); kept as the per-rank figure.
        r.add("offload.per_rank_gib", pyrepr.Float(m.group(1)))
        r.add("offload.world_size", int(m.group(2)))
    return r


def _arg_value(v):
    """A launch-config arg value as vLLM would parse it: JSON strings become objects."""
    if isinstance(v, str) and v[:1] in "{[":
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return v
    if isinstance(v, float):
        return pyrepr.Float(repr(v))
    return v


def read_launch_config(cfg: dict | None) -> Reading:
    """The srt launch config's role args (CLI flag spelling) and env, for a single-role
    (aggregated) run. A multi-role config is recorded as a problem: this extractor scores
    colocated engines only."""
    r = Reading()
    if not cfg:
        return r
    roles = (cfg.get("roles") or {}) if isinstance(cfg, dict) else {}
    if len(roles) != 1:
        r.problems.append(f"launch_config: {len(roles)} roles ({sorted(roles)}); only one colocated role is read")
        return r
    role = next(iter(roles.values())) or {}
    for flag, v in (role.get("args") or {}).items():
        key = str(flag).replace("-", "_")
        if key.startswith("no_") and v is True:
            key, v = key[3:], False
        for k, x in flatten(_arg_value(v), key).items():
            r.add(k, _arg_value(x) if not isinstance(x, (dict, list)) else x)
    for k, v in (role.get("env") or {}).items():
        r.add(f"env.{k}", str(v))
    fe = cfg.get("frontend") or {}
    if isinstance(fe, dict) and fe.get("type") and fe.get("type") != "vllm":
        policy = (fe.get("args") or {}).get("policy")
        r.add("frontend.router", f"{fe['type']}/{policy}" if policy else str(fe["type"]))
    return r


# ------------------------------------------------------------------ merging

def _norm(v):
    """A value as compared across sources: numbers by value (26 == 26.0 == '26.0' as printed),
    Opaque by text, lists and dicts whole."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, pyrepr.Float):
        try:
            return float(v)
        except ValueError:
            return str(v)
    if isinstance(v, list):
        return [_norm(x) for x in v]
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in sorted(v.items())}
    return v


def _canon(v) -> str:
    return json.dumps(_norm(v), sort_keys=True, default=str)


def _record_value(v):
    """The value as written into the fidelity record: floats as the printed decimal string."""
    if isinstance(v, (pyrepr.Float, pyrepr.Opaque)):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, list):
        return json.dumps(_norm(v))
    if isinstance(v, dict):
        return json.dumps(_norm(v), sort_keys=True)
    return v


@dataclass
class Setting:
    path: str
    value: object = None
    source: str | None = None
    occurrences: int = 1
    conflict: list | None = None    # every distinct value, when sources or repeats disagree
    requested: bool = False         # the run asked for it (vs. the build's own resolution)


def _one(values: list):
    """(value, occurrences, conflict) from one source's repeats."""
    distinct = {}
    for v in values:
        distinct.setdefault(_canon(v), v)
    if len(distinct) > 1:
        return None, len(values), [distinct[k] for k in sorted(distinct)]
    return values[0], len(values), None


def merge(readings: dict[str, Reading], vllm_defaults: dict) -> dict[str, Setting]:
    """One Setting per path: the first source in SOURCES order that states a value.

    A source that states a path as None ("let the engine decide") doesn't hide a later
    source's value for it: the first non-None value wins. Repeats within one source that
    disagree, and the two passed sources (launch_config, args) disagreeing, are conflicts
    (design §11.2, value_conflict). A resolved value that differs from a passed one is the
    engine's resolution, never a conflict."""
    paths = set()
    for r in readings.values():
        paths |= set(r.values)
    out = {}
    for path in sorted(paths):
        found = [(s, readings[s].values[path]) for s in SOURCES if s in readings and path in readings[s].values]
        stated = [(s, v) for s, v in found if any(x is not None for x in v)]
        s, vals = (stated or found)[0]
        value, occ, conflict = _one([x for x in vals if x is not None] or vals)
        st = Setting(path=path, value=value, source=s, occurrences=occ, conflict=conflict,
                     requested=_requested(path, readings, vllm_defaults))
        if conflict is None and s in PASSED:
            for s2, vals2 in stated[1:]:
                if s2 not in PASSED:
                    continue
                v2, _, c2 = _one([x for x in vals2 if x is not None])
                if c2 is not None or not _same(v2, value, path):
                    st.conflict = sorted({_canon(value): value, **{_canon(x): x for x in (c2 or [v2])}}.values(), key=_canon)
                    break
        out[path] = st
    return out


# The sources that record the values passed, and those that record the values resolved.
PASSED = ("launch_config", "args")
RESOLVED_SOURCES = ("resolved_config", "engine_line")


def _at_default(path: str, value, vllm_defaults: dict) -> bool:
    """Whether a value inside a config object is vLLM's own default for that field."""
    d = vllm_defaults.get(path)
    return path in vllm_defaults and not (isinstance(d, dict) and "unliteral" in d) and _canon(value) == _canon(d)


# The config objects vLLM prints WHOLE in `non-default args`, each field with its default
# (vllm/engine/arg_utils.py: an EngineArgs field typed as the config class). speculative_config
# and additional_config are plain dicts there and are printed as the run passed them.
WHOLE_PRINTED = ("aux_output_config", "attention_config", "compilation_config", "engram_config",
                 "eplb_config", "kernel_config", "kv_transfer_config", "observability_config",
                 "structured_outputs_config")


def _requested(path: str, readings: dict, vllm_defaults: dict) -> bool:
    """Whether the run set this setting, rather than the build resolving it (design §11.4: "the
    run sets a field the release does not have"; a field at its default is not set).

    vLLM prints only the top-level arguments that differ from their defaults, so a top-level
    field in the args line is set. A config object passed as an argument is printed whole, every
    field with its default (WHOLE_PRINTED), so a field inside one is judged by:

      1. the launch config, where the run has one: it states exactly the fields the run passed,
         so a field it states is set, and one it does not state is not, whatever the args line
         prints;
      2. otherwise the defaults of the run's own release (vllm_defaults, chosen by
         defaults_for): a field at the table's value is not set, one elsewhere is set;
      3. a field the release's defaults have no entry for, or any field when no table exists
         for the run's release, is judged unset: nothing says the run set it.

    An environment variable the engine prints as set is set. A resolved-line or engine-line value
    alone is the engine's resolution, never a request."""
    if path.startswith("env."):
        return True
    lc = readings.get("launch_config")
    has_lc = lc is not None and bool(lc.values)
    if has_lc and path in lc.values:
        return True
    a = readings.get("args")
    if a is None or path not in a.values:
        return False
    value = _one(a.values[path])[0]
    if value is None:
        return False
    if path.split(".")[0] not in WHOLE_PRINTED:
        return True
    if has_lc:
        return False
    return path in vllm_defaults and not _at_default(path, value, vllm_defaults)


# vLLM v0.32.0 parses CompilationConfig.mode from the IntEnum's value or its member name
# (vllm/config/compilation.py:37-50 CompilationMode, :852-870 validate_mode_before), and the
# server log prints the member name. The two passed sources may each use either spelling.
COMPILATION_MODES = {0: "NONE", 1: "STOCK_TORCH_COMPILE", 2: "DYNAMO_TRACE_ONCE", 3: "VLLM_COMPILE"}


def _parsed(path: str, v):
    """A passed value as the engine's argument parser reads it, for comparing two sources."""
    if path == "compilation_config.mode" and isinstance(v, int) and not isinstance(v, bool):
        return COMPILATION_MODES.get(v, v)
    if path == "compilation_config.mode" and isinstance(v, str):
        return v.upper()
    return v


def _same(a, b, path: str = "") -> bool:
    """Equal as settings, each read as the engine's parser reads it. A CLI flag that takes
    several values (served_model_name) is a scalar in the launch config and a one-element list
    in the args line."""
    if isinstance(a, list) and len(a) == 1 and not isinstance(b, list):
        a = a[0]
    if isinstance(b, list) and len(b) == 1 and not isinstance(a, list):
        b = b[0]
    return _canon(_parsed(path, a)) == _canon(_parsed(path, b))


def read_all(server_log: str, launch_config: dict | None) -> tuple[dict[str, Reading], list[str]]:
    readings = {
        "launch_config": read_launch_config(launch_config),
        "args": read_args(server_log),
        "resolved_config": read_resolved(server_log),
        "engine_line": read_engine_lines(server_log),
    }
    problems = [p for r in readings.values() for p in r.problems]
    # A vLLM engine log always prints both lines. A log missing either has changed shape (or
    # isn't a whole log), and its settings can't be trusted to be complete.
    if not readings["args"].values and _ARGS not in server_log:
        problems.append("server log has no `non-default args` line")
    if not readings["resolved_config"].values:
        problems.append("server log has no resolved engine-config line")
    return readings, problems


# ------------------------------------------------------------------ the engine's argument mapping

# Where each recorded field goes in the scenario, by its upstream name. This is the engine's own
# argument mapping, not a classification: every name is the upstream's, as blis-vllm's engine
# block takes it (blis-vllm rules/engineconfig/fieldnames_test.go at origin/m1/vllm), except the
# renames that file and blis-substrate's Deployment (contracts/spec/deployment/deployment.go)
# require: kv_cache_dtype is the block's cache_dtype; the compilation, attention and kernel
# config fields are the block's top-level ones; speculative_config is its speculative block
# (num_speculative_tokens is num_spec_tokens); VLLM_USE_RUST_FRONTEND is its frontend; the
# parallel sizes are the Deployment's parallel layout. kv_transfer_config's connector and CPU
# bytes are the Deployment's offload block (_write_offload). Every other environment variable is
# copied into the block's env as the launch gave it. The connector's own options go under the
# Deployment's offload.connector_options, as blis-vllm rules/engineconfig/connector.go names them.
_SAME_NAME = (
    "all2all_backend", "async_scheduling", "block_size", "cp_kv_cache_interleave_size", "dcp_comm_backend",
    "dcp_q_replicate", "disable_cascade_attn", "disable_custom_all_reduce", "disable_hybrid_kv_cache_manager",
    "enable_chunked_prefill", "enable_prefix_caching", "language_model_only", "gpu_memory_utilization", "kv_cache_memory_bytes", "long_prefill_token_threshold",
    "long_prefill_token_threshold_adaptive", "mamba_cache_dtype", "mamba_cache_mode", "mamba_ssm_cache_dtype",
    "max_cpu_loras", "max_cudagraph_capture_size", "max_loras", "max_model_len", "max_num_active_seqs",
    "max_num_batched_tokens", "max_num_scheduled_tokens", "max_num_seqs", "moe_backend",
    "prefill_schedule_interval", "prefix_cache_retention_interval", "prefix_match_unit", "quantization",
    "scheduling_policy", "stream_interval", "swa_bounded_replay", "watermark",
)
# Block keys that only a blis-vllm release which models the field has (M2 added them). The value is
# written only when the engine's field list calls the field modelled; an older engine's block
# refuses the key, and its field list does not model the field.
MODELLED_ONLY = ("engine.enable_chunked_prefill", "engine.language_model_only")
# blis-vllm's engine block takes vLLM's own setting names from the M2 classification on (rules/
# engineconfig/names.go "moves"): a nested config object under its class's name, the rest flat. The
# scorer builds the block in the earlier names and translates it once, when the field list is the
# M2 one (it carries value_classes, which arrive with the rename). TEMPORARY copy of the table.
VLLM_BLOCK_MOVES = (
    ("cudagraph_mode", "compilation_config.cudagraph_mode"),
    ("decoder_replay_cudagraph_capture_sizes", "compilation_config.decoder_replay_cudagraph_capture_sizes"),
    ("custom_ops", "compilation_config.custom_ops"),
    ("use_trtllm_attention", "attention_config.use_trtllm_attention"),
    ("mla_prefill_backend", "attention_config.mla_prefill_backend"),
    ("indexer_kv_dtype", "attention_config.indexer_kv_dtype"),
    ("cache_dtype", "kv_cache_dtype"),
    ("dbo.enable_dbo", "enable_dbo"),
    ("dbo.dbo_decode_token_threshold", "dbo_decode_token_threshold"),
    ("dbo.dbo_prefill_token_threshold", "dbo_prefill_token_threshold"),
    ("eplb.enable_eplb", "enable_eplb"),
    ("eplb.num_redundant_experts", "eplb_config.num_redundant_experts"),
    ("eplb.window_size", "eplb_config.window_size"),
    ("eplb.step_interval", "eplb_config.step_interval"),
    ("kv_events.enable_kv_cache_events", "kv_events_config.enable_kv_cache_events"),
    ("kv_events.publisher", "kv_events_config.publisher"),
    ("kv_events.topic", "kv_events_config.topic"),
    ("speculative.method", "speculative_config.method"),
    ("speculative.num_spec_tokens", "speculative_config.num_speculative_tokens"),
    ("speculative.draft_model", "speculative_config.model"),
    ("speculative.kv_cache_dtype", "speculative_config.kv_cache_dtype"),
    ("speculative.draft_sample_method", "speculative_config.draft_sample_method"),
    ("speculative.rejection_sample_method", "speculative_config.rejection_sample_method"),
    ("speculative.enable_adaptive_verification", "speculative_config.enable_adaptive_verification"),
)


def names_are_vllms(field_list) -> bool:
    """Whether the engine block takes vLLM's own names: the field list is the M2 one."""
    return any(f.value_classes is not None for f in field_list.fields.values())


def vllm_location(loc: str) -> str:
    """A scenario location in the earlier engine-block names, in vLLM's (engine.cache_dtype is
    engine.kv_cache_dtype); any other location unchanged."""
    if loc.startswith("engine."):
        for internal, external in VLLM_BLOCK_MOVES:
            if loc[len("engine."):] == internal:
                return "engine." + external
    return loc


def to_vllm_block(eng: dict) -> dict:
    """The engine block with its keys in vLLM's names (VLLM_BLOCK_MOVES); a copy."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in eng.items()}
    for internal, external in VLLM_BLOCK_MOVES:
        grp, _, leaf = internal.partition(".")
        src = out.get(grp) if leaf else out
        key = leaf or grp
        if not isinstance(src, dict) or key not in src:
            continue
        value = src.pop(key)
        if leaf and not src:
            out.pop(grp, None)
        dgrp, _, dleaf = external.partition(".")
        if dleaf:
            out.setdefault(dgrp, {})[dleaf] = value
        else:
            out[dgrp] = value
    return out
LOCATIONS = {
    **{f: f"engine.{f}" for f in _SAME_NAME},
    "kv_cache_dtype": "engine.cache_dtype",
    "compilation_config.cudagraph_mode": "engine.cudagraph_mode",
    "compilation_config.max_cudagraph_capture_size": "engine.max_cudagraph_capture_size",
    "compilation_config.cudagraph_capture_sizes": "engine.cudagraph_capture_sizes",
    "compilation_config.decoder_replay_cudagraph_capture_sizes": "engine.decoder_replay_cudagraph_capture_sizes",
    "compilation_config.custom_ops": "engine.custom_ops",
    "attention_config.use_trtllm_attention": "engine.use_trtllm_attention",
    "attention_config.mla_prefill_backend": "engine.mla_prefill_backend",
    "attention_config.indexer_kv_dtype": "engine.indexer_kv_dtype",
    "kernel_config.linear_backend": "engine.linear_backend",
    "kernel_config.moe_backend": "engine.moe_backend",
    "enable_dbo": "engine.dbo.enable_dbo",
    "dbo_decode_token_threshold": "engine.dbo.dbo_decode_token_threshold",
    "dbo_prefill_token_threshold": "engine.dbo.dbo_prefill_token_threshold",
    "enable_eplb": "engine.eplb.enable_eplb",
    "eplb_config.num_redundant_experts": "engine.eplb.num_redundant_experts",
    "eplb_config.window_size": "engine.eplb.window_size",
    "eplb_config.step_interval": "engine.eplb.step_interval",
    "kv_events_config.enable_kv_cache_events": "engine.kv_events.enable_kv_cache_events",
    "kv_events_config.publisher": "engine.kv_events.publisher",
    "kv_events_config.topic": "engine.kv_events.topic",
    "speculative_config.method": "engine.speculative.method",
    "speculative_config.num_speculative_tokens": "engine.speculative.num_spec_tokens",
    "speculative_config.kv_cache_dtype": "engine.speculative.kv_cache_dtype",
    "speculative_config.draft_sample_method": "engine.speculative.draft_sample_method",
    "speculative_config.rejection_sample_method": "engine.speculative.rejection_sample_method",
    "speculative_config.enable_adaptive_verification": "engine.speculative.enable_adaptive_verification",
    "engram_config.cpu_offload": "engine.engram_config.cpu_offload",
    "engram_config.dp_shared_memory": "engine.engram_config.dp_shared_memory",
    "engram_config.use_thp": "engine.engram_config.use_thp",
    "env.VLLM_USE_RUST_FRONTEND": "engine.frontend",
    "tensor_parallel_size": "parallel.tp",
    "pipeline_parallel_size": "parallel.pp",
    "data_parallel_size": "parallel.dp",
    "data_parallel_size_local": "parallel.dp_local",
    "enable_expert_parallel": "parallel.enable_expert_parallel",
    "prefill_context_parallel_size": "parallel.pcp",
    "decode_context_parallel_size": "parallel.dcp",
    "kv_transfer_config.kv_connector": "offload.connector",
    "kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use": "offload.tiers.cpu_dram",
    "kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use_per_rank": "offload.tiers.cpu_dram",
    "kv_transfer_config.kv_connector_extra_config.lazy_offload": "offload.spec",
    # The connector's own options, as blis-vllm reads them (rules/engineconfig/connector.go
    # ConnectorOptions), under the Deployment's offload.connector_options.
    "kv_transfer_config.kv_connector_extra_config.load_async": "offload.connector_options.load_async",
    "kv_transfer_config.kv_connector_extra_config.lookup_async": "offload.connector_options.lookup_async",
    "kv_transfer_config.kv_connector_extra_config.enable_offload": "offload.connector_options.enable_offload",
    "kv_transfer_config.kv_connector_extra_config.enable_cross_layers_blocks":
        "offload.connector_options.enable_cross_layers_blocks",
    "kv_transfer_config.kv_connector_extra_config.blocks_per_chunk": "offload.connector_options.blocks_per_chunk",
    "kv_transfer_config.kv_load_failure_policy": "offload.connector_options.kv_load_failure_policy",
    "speculative_config.synthetic_acceptance_length": "replay.acceptance_length",
}


def location(path: str) -> str | None:
    """Where a recorded field goes in the scenario; None when the scenario has no place for it."""
    if path in LOCATIONS:
        return LOCATIONS[path]
    if path.startswith("env."):
        return f"engine.env.{path[4:]}"
    return None


# Readings the harness derives that are not engine fields: the router a run was measured behind
# (assess.router_reason grades it) and the per-rank offload figure vLLM prints (_write_offload
# checks the written bytes against it).
DERIVED = ("frontend.router", "offload.per_rank_gib", "offload.world_size")

# The settings the support checks read to find the served checkpoint (support.check), by role.
ROLES = {"model": "model", "model_tag": "model", "served_model_name": "served_model",
         "speculative_config.model": "drafter"}

# A recorded field the Deployment states by the pool's shape rather than by a field: a
# colocated pool both stores and loads KV, which is kv_role kv_both (vllm/config/kv_transfer.py).
POOL_ROLE = {"kv_transfer_config.kv_role": {"kv_both": "colocated"}}

def _yaml_value(v):
    """A recorded value as the scenario states it: a printed float as a float, a bare token as
    its text, everything else as recorded."""
    if isinstance(v, pyrepr.Float):
        return float(v)
    if isinstance(v, pyrepr.Opaque):
        return str(v)
    if isinstance(v, list):
        return [_yaml_value(x) for x in v]
    if isinstance(v, dict):
        return {k: _yaml_value(x) for k, x in v.items()}
    return v


def _flag(v) -> bool:
    """An environment variable's value as vLLM's envs.py reads a boolean one."""
    if isinstance(v, bool):
        return v
    t = str(v).strip().lower()
    if t in ("1", "true"):
        return True
    if t in ("0", "false"):
        return False
    raise ValueError(f"{v!r} is not a boolean")


@dataclass
class Decided:
    """One point's recorded settings, decided by the engine's field list."""
    settings: dict = field(default_factory=dict)       # path -> Setting
    args: list = field(default_factory=list)           # fidelity args entries (blis filled later)
    reasons: list = field(default_factory=list)
    substitutions: list = field(default_factory=list)  # G2 substitutions named on the point
    mapped: dict = field(default_factory=dict)         # location -> (path, value)
    roles: dict = field(default_factory=dict)          # role -> value (model, served_model)


def decide(settings: dict[str, Setting], field_list) -> Decided:
    """Decide every recorded setting by the engine's fields.json (design §11.2, State and Decide).

    A setting two same-stage sources disagree on is a conflict (value_conflict). Every recorded
    value the scenario has a place for is copied there unchanged: the passed value where the run
    passed one, else the resolved one. Each field the run set is decided by fields.decide: a field
    the release lacks is field_not_in_release, a not-modelled field with no estimation rule is
    field_not_modelled, one with a rule takes it (left unset, or the stated substitute) and is
    named on the point, and an inert-unproven one is named as an interim status. A field the run
    set that the field list calls modelled, but the scenario has no place for, is a setting the
    written scenario lost (setting_differs): the harness cannot state what the run did."""
    import fields as fl
    d = Decided(settings=settings)
    for path, st in sorted(settings.items()):
        if path in DERIVED:
            continue
        if path in ROLES:
            d.roles[ROLES[path]] = st.value
        if path in POOL_ROLE:
            if st.value is not None and POOL_ROLE[path].get(st.value) != "colocated":
                d.reasons.append(f"setting_differs:{path}")
            continue
        rec = {"arg": path, "measured": _record_value(st.value), "source": st.source}
        if st.occurrences > 1:
            rec["occurrences"] = st.occurrences
        if st.conflict is not None:
            d.reasons.append(f"conflict:{path}")
            d.args.append({"arg": path, "measured": None, "source": st.source, "blis": None, "match": "conflict",
                           "values": [_record_value(v) for v in st.conflict]})
            continue
        estimated = None
        if st.requested:
            dec = fl.decide(field_list, path, set_by_run=True)
            if dec.g5:
                d.reasons.append(f"{dec.g5['code']}:{path}")
                continue
            if dec.substitution:
                d.substitutions.append(dec.substitution)
                if dec.substitution["kind"] == "estimated":
                    estimated = field_list.lookup(path).estimation
        loc = location(path)
        if loc in MODELLED_ONLY and not ((field_list.lookup(path) or fl.Field("", "", "", {}, {})).status == fl.MODELLED):
            loc = None      # the engine block of an older release has no such key
        if estimated is not None:
            # The field's estimation rule decides what the scenario states for it, not the run.
            d.args.append({**rec, "blis": None, "match": "approximated",
                           "note": d.substitutions[-1]["detail"]})
            if estimated["rule"] == fl.SUBSTITUTE:
                for f, v in sorted(estimated["setting"].items()):
                    sub = location(f)
                    if sub is None:
                        d.reasons.append(f"setting_differs:{f}")
                    else:
                        d.mapped[sub] = (f, v)
            continue
        if st.value is None:
            continue    # None is "let the engine decide": nothing to copy
        if loc is None:
            f = field_list.lookup(path)
            if st.requested and f is not None and f.status == fl.MODELLED and path not in ROLES:
                d.reasons.append(f"setting_differs:{path}")
            elif st.requested:
                d.args.append({**rec, "blis": None, "match": "inert"})
            continue
        if loc.startswith("engine.env.") and isinstance(st.value, bool):
            # vLLM's deprecation warning shows the variable was set, not its value.
            d.reasons.append(f"required_setting_missing:{path}")
            continue
        value = _yaml_value(st.value)
        if loc == "engine.frontend":
            try:
                value = _flag(value)
            except ValueError:
                d.reasons.append(f"conflict:{path}")
                continue
        prior = d.mapped.get(loc)
        if prior is not None and _canon(prior[1]) != _canon(value):
            # Two spellings of one setting (max_cudagraph_capture_size and compilation_config's)
            # that record different values.
            d.reasons.append(f"conflict:{path}")
            continue
        d.mapped[loc] = (path, value)
        d.args.append({**rec, "blis_field": loc, "_value": value})
    d.args.sort(key=lambda a: a["arg"])
    d.reasons = sorted(set(d.reasons))
    return d


# ------------------------------------------------------------------ the scenario BLIS is handed

COEFFICIENTS = ["cost-model-primitives", "cost-model-collectives", "cost-model-host-overheads",
                "cost-model-attention", "cost-model-recurrent", "cost-model-memory"]


@dataclass
class Part:
    """A catalog hardware part (catalog/hardware/<name>.yaml)."""
    name: str


def _set(d: dict, dotted: str, value):
    keys = dotted.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


@dataclass
class Built:
    scenario: dict = field(default_factory=dict)      # the Scenario document
    deployment: dict = field(default_factory=dict)    # the Deployment document
    acceptance_length: str | None = None              # --speculative-acceptance-length
    gpus: int = 0
    reasons: list = field(default_factory=list)
    substitutions: list = field(default_factory=list)  # estimates of values the run did not record
    node_source: str | None = None                    # where the scenario's gpus_per_node came from
    vllm_names: bool = False                          # the engine block is written in vLLM's own names


FRONTEND = {True: "rust", False: "python"}   # VLLM_USE_RUST_FRONTEND, parsed as a bool


def recorded_node_size(launch: dict | None) -> int | None:
    """The GPUs in one node as the run's launch configuration recorded them
    (resources.gpus_per_node), or None. Never a rank count: the GPUs a run used are not the GPUs
    of its node (tp=2 on an 8-GPU server)."""
    gpn = ((launch or {}).get("resources") or {}).get("gpus_per_node") if isinstance(launch, dict) else None
    return gpn if isinstance(gpn, int) and not isinstance(gpn, bool) and gpn > 0 else None


def build(d: Decided, *, name: str, model: str, part: Part, engine_version: str, field_list,
          catalog_node_size: int | None, node: ir.NodeSize, draft_model: str | None = None) -> Built:
    """The Scenario + Deployment for one point, from the decided settings.

    Only what the run recorded is written, under the engine's own names (LOCATIONS), and the
    substitute an estimation rule states. engine_version is the release the scoring simulator
    runs (stack.json), not the run's own (design §11.2). A setting no source recorded is left
    unset, so the engine resolves it (X19); the dashboard holds no list of the settings an
    engine needs (design §11.1). If the engine refuses the scenario for want of one, score.py
    maps its refusal to value_not_recorded, naming the field. The cluster holds the run's own
    GPUs (one engine replica).

    Node size (design §2.2, SUB-3). A chip whose catalog entry fixes GPUs per node
    (`catalog_node_size`) has it taken from the entry, so the scenario states none. For another
    chip the scenario states `node.gpus_per_node`, decided by inferencex_runners.resolve: the
    launch configuration's, else InferenceX's runner table. If it is unknown the point is G5
    value_not_recorded, or value_conflict where the two sources differ, and no size is invented.
    A later record the table supplied is named as a G2 substitution."""
    import fields as fl
    b = Built()
    acc = d.mapped.get("replay.acceptance_length")
    if acc is not None:
        b.acceptance_length = str(d.settings[acc[0]].value)
    pool = {"role": "colocated", "nodes": 1, "parallel": {}, "engine": {}}
    dep = {"kind": "Deployment", "name": name, "pools": [pool]}
    offload = {}
    for loc, (path, value) in sorted(d.mapped.items()):
        top = loc.split(".")[0]
        if loc == "replay.acceptance_length":
            continue
        if top == "offload":
            offload[loc] = (path, value)
            continue
        if loc == "engine.frontend":
            value = FRONTEND[value]
        if loc.startswith("engine.env."):
            pool["engine"].setdefault("env", {})[loc[len("engine.env."):]] = str(value)
            continue
        _set(pool, loc, value)
    par = pool["parallel"]
    # Parallelism from the run: the resolved engine config always states tp/pp/dp, so a
    # missing one means the log couldn't be read, not a default.
    for k in ("tp", "pp", "dp"):
        if k not in par:
            b.reasons.append(f"required_setting_missing:parallel.{k}")
            par[k] = 1
    # enable_expert_parallel is written only when the run recorded it (X19): vLLM prints it only
    # when it differs from the default, so an unrecorded one is left to the engine.
    eng = pool["engine"]
    spec = eng.get("speculative")
    if spec is not None and draft_model is not None:
        # The run named a draft checkpoint (speculative_config.model); the engine block names it by
        # its catalog entry (blis-vllm testdata/scenarios/muse-h100-pp2tp8-dspark.yaml: draft_model).
        spec["draft_model"] = draft_model
    if spec is not None and set(spec) >= {"method"} and "num_spec_tokens" not in spec:
        b.reasons.append("required_setting_missing:speculative_config.num_speculative_tokens")
    if offload:
        b.reasons += _write_offload(dep, offload, d, par)
    ranks = par["tp"] * par["pp"] * par["dp"] * par.get("pcp", 1)
    b.gpus = ranks
    cluster = {"hardware": part.name}
    per_node = catalog_node_size
    if per_node is None:
        per_node = node.gpus_per_node
        if node.reason is not None:
            b.reasons.append(f"{node.reason['code']}:{node.reason['subject']}")
            per_node = ranks      # only to size the placeholder; the point is already not scored
        else:
            cluster["gpus_per_node"] = per_node
            b.node_source = node.provenance
            if node.substitution is not None:
                b.substitutions.append(node.substitution)
    cluster["nodes"] = max(1, -(-ranks // per_node))
    pool["nodes"] = cluster["nodes"]
    b.scenario = {"kind": "Scenario", "name": name, "engine_version": engine_version.lstrip("v"),
                  "model": model, "coefficients": COEFFICIENTS, "cluster": cluster}
    if names_are_vllms(field_list):
        pool["engine"] = to_vllm_block(pool["engine"])
        b.vllm_names = True
    b.deployment = dep
    return b


def _write_offload(dep: dict, offload: dict, c: Decided, par: dict) -> list[str]:
    """The Deployment offload block from the run's kv_transfer_config. BLIS's tier bytes are
    per engine (one data-parallel rank's engine); vLLM's cpu_bytes_to_use is server-wide and
    divided by the engine's world size, unless cpu_bytes_to_use_per_rank states it per rank.
    The engine line vLLM prints (per_rank=…, world_size=…) is the resolved figure, so it is
    preferred when present."""
    conn = offload.get("offload.connector", (None, None))[1]
    if conn is None:
        return ["required_setting_missing:kv_transfer_config.kv_connector"]
    world = par["tp"] * par["pp"] * par.get("pcp", 1)
    per_rank = None
    pr = c.settings.get("kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use_per_rank")
    total = c.settings.get("kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use")
    try:
        if pr is not None and pr.conflict is None:
            per_rank = _bytes(pr.value)
        elif total is not None and total.conflict is None:
            per_rank = _bytes(total.value) // world
    except ValueError:
        return ["conflict:kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use"]
    if per_rank is None:
        return ["required_setting_missing:kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use"]
    logged = c.settings.get("offload.per_rank_gib")
    if logged is not None:
        if logged.conflict is not None:
            return ["conflict:offload.per_rank_gib"]
        # vLLM prints the per-rank figure to two decimals of GiB.
        if abs(float(logged.value) - per_rank / 1024 ** 3) > 0.005:
            return ["conflict:kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use"]
    # BLIS's tier is the engine's: the world-size ranks of one engine share it.
    block = {"connector": conn, "tiers": [{"tier": "cpu_dram", "bytes": per_rank * world}]}
    lazy = offload.get("offload.spec", (None, None))[1]
    if lazy is not None and conn == "SimpleCPUOffloadConnector":
        block["spec"] = "lazy" if lazy else "eager"
    opts = {loc.rsplit(".", 1)[1]: v for loc, (_, v) in sorted(offload.items())
            if loc.startswith("offload.connector_options.")}
    if opts:
        block["connector_options"] = opts
    dep["offload"] = block
    return []


def _bytes(v) -> int:
    """A byte count as printed: an int, or a float with no fractional part."""
    f = float(v)
    if f != int(f) or f <= 0:
        raise ValueError(f"{v!r} is not a whole number of bytes")
    return int(f)


def to_yaml(b: Built, header: list[str]) -> str:
    """The scenario file: header comments, then the Scenario and Deployment documents."""
    import yaml
    lines = [f"# {h}" if h else "#" for h in header]
    body = yaml.safe_dump(b.scenario, sort_keys=False, default_flow_style=None, width=1000)
    body += "---\n" + yaml.safe_dump(b.deployment, sort_keys=False, default_flow_style=None, width=1000)
    return "\n".join(lines) + ("\n" if lines else "") + body


# The fields a disaggregated or multi-node run's recorded settings state its topology by (design
# §11.4): the KV transfer config (role, connector) and the parallel sizes. They go through the
# same Decide step as every other field; the dashboard does not classify them.
TOPOLOGY_PREFIXES = ("kv_transfer_config.",)
TOPOLOGY_FIELDS = tuple(f for f, loc in LOCATIONS.items() if loc.startswith("parallel."))
KV_ROLE = "kv_transfer_config.kv_role"


def topology_paths(launch_config: dict | None, args: "Reading") -> list[str]:
    """The topology fields the run records, in any role of the launch config or in the logged
    arguments."""
    paths = set()
    for role in ((launch_config or {}).get("roles") or {}).values():
        for flag, v in ((role or {}).get("args") or {}).items():
            key = str(flag).replace("-", "_")
            for k in flatten(_arg_value(v), key):
                paths.add(k)
    paths |= set(args.values)
    return sorted(p for p in paths if p.startswith(TOPOLOGY_PREFIXES) or p in TOPOLOGY_FIELDS)


def topology_reasons(launch_config: dict | None, args: "Reading", field_list) -> list[str]:
    """Why a disaggregated or multi-node run is not scored as one colocated engine.

    Its recorded topology fields are decided by the engine's fields.json: a field the engine
    classifies not_modelled (with no rule) is `field_not_modelled:<field>`, one the release lacks
    `field_not_in_release`. A run that records no kv_transfer_config field is
    `value_not_recorded` for kv_transfer_config.kv_role. A run whose topology fields are all modelled cannot be written as
    the colocated pool this harness builds: the list is returned empty and the caller names
    `topology_unsupported` (score.py)."""
    import fields as fl
    paths = topology_paths(launch_config, args)
    out = []
    if not any(p.startswith(TOPOLOGY_PREFIXES) for p in paths):
        # Parallel sizes alone do not say how the engines are split: the role is still needed.
        out.append(f"required_setting_missing:{KV_ROLE}")
    for p in paths:
        dec = fl.decide(field_list, p, set_by_run=True)
        if dec.g5:
            out.append(f"{dec.g5['code']}:{p}")
    return sorted(out)


# ------------------------------------------------------------------ the acceptance a run realised

_SPEC_LINE = re.compile(r"SpecDecoding metrics: Mean acceptance length: ([0-9.]+).*?Drafted: ([0-9]+) tokens")


def realised_acceptance(log: str) -> dict | None:
    """The mean acceptance length the vLLM server logged while it served (its periodic
    "SpecDecoding metrics: Mean acceptance length: X, ... Drafted: D tokens" lines), or None when
    the log has none. The figure is the mean of the lines' lengths weighted by the tokens each
    interval drafted, which is the length over all drafts when the draft length is fixed. The log
    covers the server's whole life, warm-up and any other client included, so it is the run's
    realised acceptance only to that extent; `lines` and `drafted_tokens` say how much it rests on.
    Idle intervals (nothing drafted) are skipped."""
    total = weighted = 0.0
    lines = 0
    for m in _SPEC_LINE.finditer(log):
        drafted = int(m.group(2))
        if drafted <= 0:
            continue
        lines += 1
        total += drafted
        weighted += float(m.group(1)) * drafted
    if not lines:
        return None
    return {"mean_acceptance_length": round(weighted / total, 3), "log_lines": lines, "drafted_tokens": int(total)}
