"""Read every setting a run recorded, classify it, and build the deployment BLIS is handed
(Discussion #28, "Engine settings").

Sources, in order; for each setting the first that states it wins, and two that state
different values are a conflict:

  1. launch_config    the srt launch config's role args + env (artifact), when the run has one;
  2. args             the server log's `non-default args: {...}`;
  3. resolved_config  the server log's `Initializing a V1 LLM engine (v…) with config: …`;
  4. engine_line      lines vLLM prints even for a setting it wasn't passed (ENGINE_LINES);
  5. blis_default     BLIS's own resolver (orchestrator/blisdefaults), only for a setting
                      BLIS requires that nothing above recorded.

A policy entry may restrict where its value is read (`source_only`) or prefer one source
(`source_prefer`): the compile mode is what the engine resolved, not what was asked.

Every path the run recorded is classified by orchestrator/vllm_arg_policy.yaml; an unknown
path refuses the point (unclassified_arg). Engine outcomes (the KV pool) are compared after
the replay and never written here.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pyrepr

POLICY_PATH = Path(__file__).resolve().parent.parent / "vllm_arg_policy.yaml"
SOURCES = ("launch_config", "args", "resolved_config", "engine_line", "blis_default")

# Lines vLLM prints with what it resolved, whether or not the flag was passed. Each pattern's
# groups become (path, value). A line printed once per rank must agree across ranks.
ENGINE_LINES = (
    (re.compile(r"Setting kv cache block size to (\d+) for"), ("block_size", int)),
    (re.compile(r"Desired GPU memory utilization is \(([0-9.]+), [0-9.]+ GiB\)"), ("gpu_memory_utilization", pyrepr.Float)),
    (re.compile(r"Chunked prefill is enabled with max_num_batched_tokens=(\d+)"), ("max_num_batched_tokens", int)),
)
_RUST_FRONTEND = re.compile(r"Launching Rust frontend")
_SIMPLE_OFFLOAD = re.compile(r"SimpleCPUOffloadConnector: role=\w+, per_rank=([0-9.]+) GB, world_size=(\d+)")
_ARGS = "non-default args: {"
_RESOLVED = re.compile(r"Initializing a V1 LLM engine \(v[^)]*\) with config: (.*)")


def load_policy(path: Path = POLICY_PATH) -> tuple[dict, str]:
    import yaml
    raw = path.read_bytes()
    return yaml.safe_load(raw), hashlib.sha256(raw).hexdigest()


def lookup(policy: dict, path: str) -> tuple[str, dict] | None:
    """The most specific entry for a path: an exact key, else the longest `prefix.*` that
    covers it."""
    entries = policy["entries"]
    if path in entries:
        return path, entries[path]
    best = None
    for key in entries:
        if key.endswith(".*") and fnmatch.fnmatchcase(path, key):
            if best is None or len(key) > len(best):
                best = key
    return (best, entries[best]) if best else None


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
    depth, quote = 0, None
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            if ch == "\\":
                continue
            if ch == quote:
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
        r.add("env.VLLM_USE_RUST_FRONTEND", "1")
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
    """A value as compared across sources: Float/Opaque compare by number/text, lists whole."""
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


def merge(readings: dict[str, Reading], policy: dict) -> dict[str, Setting]:
    """One Setting per path, by the source order and each entry's source rules."""
    paths = set()
    for r in readings.values():
        paths |= set(r.values)
    out = {}
    for path in sorted(paths):
        hit = lookup(policy, path)
        entry = hit[1] if hit else {}
        order = list(SOURCES[:-1])
        if entry.get("source_only"):
            order = [entry["source_only"]]
        elif entry.get("source_prefer"):
            order = [entry["source_prefer"]] + [s for s in order if s != entry["source_prefer"]]
        found = [(s, readings[s].values[path]) for s in order if s in readings and path in readings[s].values]
        if not found:
            continue
        s, vals = found[0]
        value, occ, conflict = _one(vals)
        st = Setting(path=path, value=value, source=s, occurrences=occ, conflict=conflict,
                     requested=_requested(path, readings, entry))
        # Only what was ASKED can disagree: the launch config and the args line both state
        # the request, so a difference between them is a conflict. The resolved line and
        # engine lines are the engine's resolution of that request; where they differ from
        # it, that is vLLM resolving, not a disagreement (and an entry that wants the
        # resolved value says so with source_prefer / source_only).
        if conflict is None and s in REQUESTED:
            for s2, vals2 in found[1:]:
                if s2 not in REQUESTED:
                    continue
                v2, _, c2 = _one(vals2)
                if c2 is not None or not _same(v2, value):
                    st.conflict = sorted({_canon(value): value, **{_canon(x): x for x in (c2 or [v2])}}.values(), key=_canon)
                    break
        out[path] = st
    return out


REQUESTED = ("launch_config", "args")


def _requested(path: str, readings: dict, entry: dict) -> bool:
    """Whether the run asked for this setting, rather than the build resolving it.

    The launch config, when the run ships one, is exactly what was asked. Without one, the
    args line is: vLLM prints the arguments that differ from its defaults, but a config
    object passed as an argument is printed whole, defaults included, so a field inside one
    counts as asked only when it isn't at its default (`unset`). A resolved-line or
    engine-line value is the engine's resolution, never a request."""
    if entry.get("source_only") == "resolved_config":
        return True     # the entry is about what the engine ran, so its resolution is the setting
    lc = readings.get("launch_config")
    if lc is not None and lc.values:
        return path in lc.values
    a = readings.get("args")
    if a is None or path not in a.values:
        return False
    if "." not in path:
        return True
    return not _is_unset(entry, _one(a.values[path])[0])


def _same(a, b) -> bool:
    """Equal as settings. A CLI flag that takes several values (served_model_name) is a
    scalar in the launch config and a one-element list in the args line."""
    if isinstance(a, list) and len(a) == 1 and not isinstance(b, list):
        a = a[0]
    if isinstance(b, list) and len(b) == 1 and not isinstance(a, list):
        b = b[0]
    return _canon(a) == _canon(b)


def read_all(server_log: str, launch_config: dict | None) -> tuple[dict[str, Reading], list[str]]:
    readings = {
        "launch_config": read_launch_config(launch_config),
        "args": read_args(server_log),
        "resolved_config": read_resolved(server_log),
        "engine_line": read_engine_lines(server_log),
    }
    problems = [p for r in readings.values() for p in r.problems]
    return readings, problems


# ------------------------------------------------------------------ classifying + the deployment

def _is_unset(entry: dict, value) -> bool:
    unset = entry.get("unset", [])
    if "default" in entry:
        unset = list(unset) + [entry["default"]]
    return any(_canon(value) == _canon(u) for u in unset)


def _typed(entry: dict, value):
    t = entry.get("type")
    v = value[0] if isinstance(value, list) and len(value) == 1 and t != "list" else value
    try:
        if t == "int":
            if isinstance(v, bool):
                raise ValueError
            return int(str(v)) if not isinstance(v, int) else v
        if t == "float":
            return float(v)
        if t == "bool":
            if isinstance(v, bool):
                return v
            if str(v).lower() in ("true", "1"):
                return True
            if str(v).lower() in ("false", "0"):
                return False
            raise ValueError
        if t == "str":
            return None if v is None else str(v)
        if t == "list":
            return [int(x) for x in v] if isinstance(v, list) else None
    except (TypeError, ValueError):
        raise ValueError(f"{value!r} is not a {t}")
    return v


@dataclass
class Classified:
    """The per-point outcome of settings extraction."""
    settings: dict = field(default_factory=dict)       # path -> Setting
    args: list = field(default_factory=list)           # fidelity args entries (blis filled later)
    reasons: list = field(default_factory=list)
    mapped: dict = field(default_factory=dict)         # blis_field -> value
    approximated: bool = False
    roles: dict = field(default_factory=dict)          # role -> value (model, drafter, ...)


def classify(settings: dict[str, Setting], policy: dict) -> Classified:
    c = Classified(settings=settings)
    aliases = {}
    for path, st in settings.items():
        hit = lookup(policy, path)
        if hit is None:
            c.reasons.append(f"unclassified_arg:{path}")
            continue
        _, entry = hit
        if entry.get("alias_of"):
            aliases[path] = (entry["alias_of"], st)
            continue
        if entry.get("role"):
            c.roles[entry["role"]] = st.value
        if st.conflict is not None:
            c.reasons.append(f"conflict:{path}")
            c.args.append({"arg": path, "measured": None, "source": st.source, "blis": None,
                           "match": "conflict", "values": [_record_value(v) for v in st.conflict]})
            continue
        cls = entry["class"]
        rec = {"arg": path, "measured": _record_value(st.value), "source": st.source}
        if cls in ("refuse", "approximate") and not st.requested:
            # The build's own resolution of a setting the run didn't ask for. The commit
            # distance gate admitted this build; its defaults are part of it.
            continue
        if st.occurrences > 1:
            rec["occurrences"] = st.occurrences
        if cls == "inert":
            if entry.get("note") or path == "frontend.router":
                c.args.append({**rec, "blis": None, "match": "inert"})
            continue
        if cls == "refuse":
            if _is_unset(entry, st.value):
                continue
            c.reasons.append(f"setting_not_modelled:{path}")
            c.args.append({**rec, "blis": None, "match": "absent_in_blis"})
            continue
        if cls == "approximate":
            if _is_unset(entry, st.value):
                continue
            c.approximated = True
            rec.update(blis=_record_value(entry.get("approximate_as")), match="approximated",
                       note=entry["note"])
            if entry.get("upstream"):
                rec["upstream"] = entry["upstream"]
            c.args.append(rec)
            continue
        # mapped
        if st.value is None:
            continue    # None is "let the engine decide": not a setting
        try:
            value = _typed(entry, st.value)
        except ValueError:
            c.reasons.append(f"conflict:{path}")
            c.args.append({**rec, "blis": None, "match": "unreadable"})
            continue
        c.mapped[entry["blis_field"]] = (path, value, entry)
        c.args.append({**rec, "blis_field": entry["blis_field"], "_value": value})
    # An alias (max_cudagraph_capture_size beside compilation_config's) must agree with its
    # canonical path when both are recorded; alone, it stands in for it.
    for path, (canonical, st) in sorted(aliases.items()):
        entry = policy["entries"][canonical]
        try:
            value = _typed(entry, st.value)
        except ValueError:
            c.reasons.append(f"conflict:{path}")
            continue
        have = c.mapped.get(entry["blis_field"])
        if have is None and canonical not in settings:
            c.mapped[entry["blis_field"]] = (path, value, entry)
            rec = {"arg": path, "measured": _record_value(st.value), "source": st.source,
                   "blis_field": entry["blis_field"], "_value": value}
            c.args.append(rec)
        elif have is not None and _canon(have[1]) != _canon(value) and canonical in settings and \
                settings[canonical].source in REQUESTED and st.source in REQUESTED:
            c.reasons.append(f"conflict:{path}")
    c.args.sort(key=lambda a: a["arg"])
    c.reasons = sorted(set(c.reasons))
    return c


# ------------------------------------------------------------------ the scenario BLIS is handed

COEFFICIENTS = ["cost-model-primitives", "cost-model-collectives", "cost-model-host-overheads",
                "cost-model-attention", "cost-model-recurrent", "cost-model-memory"]


@dataclass
class Part:
    """A catalog hardware part (catalog/hardware/<name>.yaml)."""
    name: str
    memory_gib: float


def blis_defaults(helper: str, part: Part) -> dict:
    """BLIS's own batch defaults for a part, from orchestrator/blisdefaults."""
    import subprocess
    out = subprocess.run([helper, "-memory-gib", repr(part.memory_gib), "-device", part.name],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


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
    defaults_used: list = field(default_factory=list)  # fidelity args entries


GPUS_PER_NODE = 8


def build(c: Classified, *, name: str, model: str, part: Part, engine_version: str,
          defaults: dict | None) -> Built:
    """The Scenario + Deployment for one point, from the classified settings.

    Only what the run recorded is written, plus BLIS's default for a setting BLIS requires
    that nothing recorded. The cluster is sized to the run's own GPUs (one engine replica),
    so BLIS never multiplies the deployment beyond what was measured.
    """
    b = Built()
    pool = {"role": "colocated", "nodes": 1, "parallel": {}, "engine": {}}
    dep = {"kind": "Deployment", "name": name, "pools": [pool]}
    offload = {}
    for blis_field, (path, value, entry) in sorted(c.mapped.items()):
        top = blis_field.split(".")[0]
        if blis_field == "replay.acceptance_length":
            b.acceptance_length = str(c.settings[path].value)
            continue
        if top == "offload":
            offload[blis_field] = (path, value)
            continue
        if blis_field == "engine.frontend":
            value = "rust" if str(value) == "1" else "python"
        _set(pool, blis_field, value)
    par = pool["parallel"]
    par.setdefault("tp", 1)
    par.setdefault("pp", 1)
    par.setdefault("dp", 1)
    par.setdefault("enable_expert_parallel", False)
    eng = pool["engine"]
    # A speculative block needs both halves; one alone isn't a drafter BLIS can price.
    if "speculative" in eng and set(eng["speculative"]) != {"method", "num_spec_tokens"}:
        b.reasons.append("required_setting_missing:speculative_config.num_speculative_tokens")
    # Required settings no source recorded: BLIS's own default, else refuse.
    for path, field_ in (("max_num_seqs", "max_num_seqs"), ("max_num_batched_tokens", "max_num_batched_tokens"),
                         ("block_size", "block_size")):
        if field_ in eng:
            continue
        if defaults and field_ in defaults:
            eng[field_] = defaults[field_]
            b.defaults_used.append({
                "arg": path, "measured": None, "source": "blis_default", "blis": defaults[field_],
                "match": "blis_default",
                "rule": f"ResolveVLLMBatchDefaults({defaults['memory_gib']} GiB, {defaults['device']}) "
                        f"at the BLIS release (vLLM {engine_version}'s served-deployment tier)"})
        else:
            b.reasons.append(f"required_setting_missing:{path}")
    if offload:
        b.reasons += _write_offload(dep, offload, c, par)
    ranks = par["tp"] * par["pp"] * par["dp"] * par.get("pcp", 1)
    b.gpus = ranks
    nodes = max(1, -(-ranks // GPUS_PER_NODE))
    pool["nodes"] = nodes
    b.scenario = {"kind": "Scenario", "name": name, "engine_version": engine_version.lstrip("v"),
                  "model": model, "coefficients": COEFFICIENTS,
                  "cluster": {"hardware": part.name, "nodes": nodes,
                              "gpus_per_node": min(ranks, GPUS_PER_NODE) if nodes == 1 else GPUS_PER_NODE}}
    if nodes > 1:
        b.reasons.append("blis_refused:multi_node_fabric_unstated")
    b.deployment = dep
    return b


def _write_offload(dep: dict, offload: dict, c: Classified, par: dict) -> list[str]:
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
    if pr is not None:
        per_rank = int(pr.value)
    elif total is not None:
        per_rank = int(total.value) // world
    if per_rank is None:
        return ["required_setting_missing:kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use"]
    logged = c.settings.get("offload.per_rank_gib")
    if logged is not None and abs(float(logged.value) - per_rank / 1024 ** 3) > 0.005:
        return ["conflict:kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use"]
    # BLIS's tier is the engine's: the world-size ranks of one engine share it.
    block = {"connector": conn, "tiers": [{"tier": "cpu_dram", "bytes": per_rank * world}]}
    lazy = offload.get("offload.spec", (None, None))[1]
    if lazy is not None and conn == "SimpleCPUOffloadConnector":
        block["spec"] = "lazy" if lazy else "eager"
    dep["offload"] = block
    return []


def to_yaml(b: Built, header: list[str]) -> str:
    """The scenario file: header comments, then the Scenario and Deployment documents."""
    import yaml
    lines = [f"# {h}" if h else "#" for h in header]
    body = yaml.safe_dump(b.scenario, sort_keys=False, default_flow_style=None, width=1000)
    body += "---\n" + yaml.safe_dump(b.deployment, sort_keys=False, default_flow_style=None, width=1000)
    return "\n".join(lines) + ("\n" if lines else "") + body
