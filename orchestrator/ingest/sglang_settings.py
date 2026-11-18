"""What an SGLang run set, read from its server log and its launch command (design §11.2).

vLLM prints only the arguments a run passed away from their defaults, so its log says what the
run set. SGLang prints `server_args=ServerArgs(...)` with EVERY field, each resolved: a value the
model or the chip chose (page_size, kv_cache_dtype, the CUDA graph sizes) and a random seed are
printed as the values they took. The printout therefore gives the resolved value of a field but
cannot say whether the run asked for it. The launch command can: a flag it names is a request.

    resolved_config   the first `server_args=ServerArgs(...)` the log prints, in SGLang's own field
                      names. The first is the launching process's; later ones are per-rank copies
                      that differ in ports and ranks.
    launch_config     the flags (and environment variables) of the `sglang.launch_server` command,
                      mapped to ServerArgs fields through blis-sglang's declarations
                      (sglang_declarations.json). A flag whose value the command left to the shell
                      ($TP) is a request with the value the printout resolved.

A run without a recorded launch command has no source for what it asked, so it is refused by name
(required_setting_missing is the code; the subject is launch_command). Nothing is guessed from the
printout: a field printed away from its default may be the engine's resolution.

The classification of every field comes only from blis-sglang's fields.json, through fields.decide.
"""
from __future__ import annotations

import json
import re
import shlex
from functools import lru_cache
from pathlib import Path

import pyrepr
import settings as st

DECLARATIONS_PATH = Path(__file__).resolve().parent.parent / "sglang_declarations.json"
LAUNCH_COMMAND_SUBJECT = "launch_command"

_SERVER_ARGS = re.compile(r"server_args=ServerArgs\((.*)\)\s*$", re.M)
_LAUNCH = re.compile(r"(?:python3?\s+-m\s+sglang\.launch_server|sglang\s+serve)(?=\s|$)")
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_XTRACE = re.compile(r"^(?:\S+\s+)?\++\s+")      # an optional timestamp, then the shell's "+ " prefix


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    return json.loads(Path(path).read_bytes())


def load_declarations(path: Path = DECLARATIONS_PATH) -> dict:
    """The declarations table: {"engine", "source", "fields": {name: {"flags", "type", "default"?}}}."""
    return _load(str(path))


def _flag_map(decl: dict) -> dict:
    return {flag: name for name, f in decl["fields"].items() for flag in f["flags"]}


# ------------------------------------------------------------------ reading each source

def read_server_args(log: str) -> st.Reading:
    """The first `server_args=ServerArgs(...)` of the log, field by field."""
    r = st.Reading()
    m = _SERVER_ARGS.search(log)
    if m is None:
        return r
    try:
        for k, v in pyrepr.parse_kwargs(m.group(1)).items():
            r.add(k, v)
    except pyrepr.ReprError as e:
        r.problems.append(f"resolved_config: {e}")
    return r


NO_COMMAND, AMBIGUOUS_COMMAND, SHELL_EXPANSION = "no_launch_command", "several_launch_commands", "shell_expansion"
_EXPANSION = re.compile(r"\$\(|`|\$\{[^}]*:[-+=?]")


LEFT_TO_THE_LOG = "$LEFT_TO_THE_LOG"
_FLAG_BEFORE_VALUE = re.compile(r"--[A-Za-z0-9][A-Za-z0-9-]*(?:=|\s+)$")


def _hide_computed_values(cmd: str) -> str:
    """The command with each `$(...)` or `$((...))` that is a flag's whole value replaced by a variable the reader
    leaves to the log. The flag is still named, and the printout of the resolved arguments holds its value; an
    expansion anywhere else (it may decide whether a flag is set at all) is left, and the command is refused."""
    out, i = [], 0
    while i < len(cmd):
        j = cmd.find("$(", i)
        if j < 0:
            break
        depth, k = 0, j + 1
        while k < len(cmd):
            depth += {"(": 1, ")": -1}.get(cmd[k], 0)
            k += 1
            if depth == 0:
                break
        if depth != 0 or not _FLAG_BEFORE_VALUE.search(cmd[:j]) or (k < len(cmd) and not cmd[k].isspace()):
            break
        out.append(cmd[i:j] + LEFT_TO_THE_LOG)
        i = k
    return "".join(out) + cmd[i:]


def _merge_branches(cmds: list[str]) -> str | None:
    """One command for the several a script launches by branch, when they differ only in the values of the flags they
    all name: each differing value becomes a variable left to the log. Commands that name different flags, or are
    laid out differently, are not merged (None): which flags the run set is then unknown."""
    split = [shlex.split(c, comments=True) for c in cmds]
    if len({len(t) for t in split}) != 1:
        return None
    merged = []
    for col in zip(*split):
        if len(set(col)) == 1:
            merged.append(col[0])
            continue
        heads = {t.partition("=")[0] for t in col}
        if any(t.startswith("--") and "=" not in t for t in col) or len(heads) != 1 and any("=" in t for t in col):
            return None
        merged.append(f"{heads.pop()}={LEFT_TO_THE_LOG}" if all("=" in t for t in col) and next(iter(heads)).startswith("--")
                      else LEFT_TO_THE_LOG)
    return " ".join(shlex.quote(t) if t != LEFT_TO_THE_LOG and not t.startswith("--") else t for t in merged)


def launch_command_of(text: str) -> tuple[str | None, str | None]:
    """(the launch command with the environment it ran with, None) from a CI job log or a script, or (None, why).

    The text holds the `sglang.launch_server` (or `sglang serve`) command, its continuation lines joined, and
    the `export` lines before it. A job log run under `set -x` shows the command with its variables expanded.
    Nothing is guessed: no command, several different ones (a script that launches by branch), or a command that
    uses a shell expansion this reader cannot evaluate (${X:+--flag $X}, $(...)) is refused with its reason."""
    lines = text.splitlines()
    env, cmds, i = [], [], 0
    while i < len(lines):
        line = _XTRACE.sub("", lines[i]).strip()
        if line.startswith("export "):
            env.append(line)
        m = _LAUNCH.search(line)
        if m and not line.startswith("#"):
            cmd = line
            while cmd.endswith("\\") and i + 1 < len(lines):
                i += 1
                cmd = cmd[:-1].rstrip() + " " + lines[i].strip()
            cmds.append(cmd)
        i += 1
    distinct = sorted({_hide_computed_values(c) for c in cmds})
    if not distinct:
        return None, NO_COMMAND
    if len(distinct) > 1:
        merged = None if any(_EXPANSION.search(c) for c in distinct) else _merge_branches(distinct)
        if merged is None:
            return None, AMBIGUOUS_COMMAND
        distinct = [merged]
    if _EXPANSION.search(distinct[0]):
        return None, SHELL_EXPANSION
    return "\n".join(env + distinct), None


def _coerce(value: str, kind: str):
    """A flag's text as SGLang's parser takes it, by the field's declared type."""
    k = (kind or "").replace("Optional[", "").rstrip("]")
    if k == "int":
        return int(value)
    if k == "float":
        return pyrepr.Float(value)
    if k == "bool":
        return value.strip().lower() in ("1", "true", "yes")
    if value[:1] in "{[":
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def read_launch_command(text: str | None, decl: dict) -> st.Reading:
    """The flags and environment variables of a launch command (launch_command_of's output)."""
    r = st.Reading()
    if not text:
        return r
    flags = _flag_map(decl)
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if not _LAUNCH.search(line):
            try:
                toks = shlex.split(line.removeprefix("export "), comments=True)
            except ValueError as e:
                # A malformed environment line is this run's problem, named as a G5 (COV-1), not the night's.
                r.problems.append(f"launch_config: {e}")
                continue
            for tok in toks:
                if _ASSIGN.match(tok):
                    k, _, v = tok.partition("=")
                    r.add(f"env.{k}", None if "$" in v else v)
            continue
        try:
            toks = shlex.split(line, comments=True)
        except ValueError as e:
            r.problems.append(f"launch_config: {e}")
            continue
        # Leading VAR=value words are the command's own environment.
        while toks and _ASSIGN.match(toks[0]):
            k, _, v = toks.pop(0).partition("=")
            r.add(f"env.{k}", None if "$" in v else v)
        start = next((j for j, t in enumerate(toks) if t.startswith("--")), len(toks))
        toks = toks[start:]
        j = 0
        while j < len(toks):
            t = toks[j]
            j += 1
            if t in (">", ">>", "&", "2>&1") or t.startswith((">", "2>")):
                break
            if not t.startswith("--"):
                continue
            flag, eq, val = t.partition("=")
            negated = False
            name = flags.get(flag)
            if name is None and flag.startswith("--no-") and flags.get("--" + flag[5:]) is not None:
                name, negated = flags["--" + flag[5:]], True
            if name is None:
                # A flag this release's ServerArgs does not declare: the run set a field the release lacks
                # (§11.4 field_not_in_release). It is read under the name the flag spells, so decide refuses it by name.
                name = flag[2:].replace("-", "_")
            kind = (decl["fields"].get(name) or {}).get("type")
            if negated:
                r.add(name, False)
            elif eq:
                r.add(name, _value(val, kind))
            elif j < len(toks) and not toks[j].startswith("--") and kind != "bool":
                vals = [toks[j]]
                j += 1
                # A list-valued flag takes every word up to the next flag.
                while (kind or "").startswith(("List", "list")) and j < len(toks) and not toks[j].startswith(("--", ">", "&", "2>")):
                    vals.append(toks[j])
                    j += 1
                r.add(name, _value(vals[0], kind) if len(vals) == 1 and not (kind or "").startswith(("List", "list"))
                      else [_value(v, "str") for v in vals])
            else:
                r.add(name, True if kind in ("bool", None) else None)
    return r


def _value(text: str, kind: str):
    """A flag's value, or None when the command left it to the shell (an unexpanded $VAR). A flag the release does not
    declare has no type; a whole number is read as one, so a renamed field takes the value as the earlier release read it."""
    if "$" in text:
        return None
    if kind is None and re.fullmatch(r"-?\d+", text):
        return int(text)
    try:
        return _coerce(text, kind)
    except ValueError:
        return text


# The flags of a prefill/decode pool that are the deployment's (its role and its KV transfer), not engine settings.
TRANSFER_FIELDS = ("disaggregation_mode", "disaggregation_transfer_backend")
CONNECTOR_PATH = "kv_transfer_config.kv_connector"      # where pd.build_pd looks for the pools' connector


def pool_launch_text(launch: dict) -> str:
    """A launch command, in the form `read_launch_command` reads, of the one pool a pseudo launch
    configuration (pd.pseudo_launch) holds: the recipe's flags and environment. A flag set to false is not on the command."""
    (role, spec), = launch["roles"].items()
    lines = [f"export {k}={shlex.quote(str(v))}" for k, v in (spec.get("env") or {}).items()]
    words = ["python3", "-m", "sglang.launch_server"]
    for k, v in (spec.get("args") or {}).items():
        if v is None or v is False:
            continue
        words.append(f"--{k}")
        if v is not True:
            words += [shlex.quote(str(x)) for x in (v if isinstance(v, list) else [v])]
    return "\n".join(lines + [" ".join(words)])


def read_pool(launch: dict, decl: dict, field_list=None) -> tuple[st.Reading, dict]:
    """(the pool's settings reading without its role and transfer backend, {field: value}) from a pseudo launch
    configuration. The transfer backend is also given as the connector pd.build_pd reads; one the recipe leaves
    unstated is the engine's declared default."""
    rd = read_launch_command(pool_launch_text(launch), decl)
    if field_list is not None:
        drop_foreign_env(rd, field_list)
    taken = {}
    for f in TRANSFER_FIELDS:
        vals = rd.values.pop(f, None)
        if vals:
            taken[f] = vals[0]
    backend = taken.get("disaggregation_transfer_backend")
    if backend is None and "disaggregation_mode" in taken:
        backend = (decl["fields"].get("disaggregation_transfer_backend") or {}).get("default")
    if backend is not None:
        taken[CONNECTOR_PATH] = backend
    return rd, taken


def unresolved_env(readings: dict) -> list[str]:
    """The environment variables the launch command sets to a value left to the shell ($X): the value is not
    recorded, and the point is refused naming the variable rather than run without it."""
    lc = readings["launch_config"]
    return sorted(f"required_setting_missing:{p}" for p, vs in lc.values.items()
                  if p.startswith("env.") and all(v is None for v in vs))


ENGINE_ENV_PREFIX = "SGLANG_"


def drop_foreign_env(reading: st.Reading, field_list) -> None:
    """Remove the environment variables of a launch script that SGLang does not read: a script exports its own helper
    variables (MODEL_PATH, a log directory) beside the engine's. A variable is the engine's when its field list names it
    (every variable the release reads, with its libraries') or it is spelled as SGLang's own (SGLANG_*): an unlisted
    SGLANG_* variable is one this release lacks, and the run is refused for it by name."""
    for path in [p for p in reading.values if p.startswith("env.")]:
        if field_list.lookup(path) is None and not path[len("env."):].startswith(ENGINE_ENV_PREFIX):
            del reading.values[path]


def read_all(server_log: str, launch_text: str | None, decl: dict, field_list=None) -> tuple[dict, list]:
    readings = {"launch_config": read_launch_command(launch_text, decl),
                "resolved_config": read_server_args(server_log)}
    if field_list is not None:
        drop_foreign_env(readings["launch_config"], field_list)
    problems = [p for r in readings.values() for p in r.problems]
    if not readings["resolved_config"].values:
        problems.append("server log has no `server_args=ServerArgs(...)` line")
    return readings, problems


# ------------------------------------------------------------------ what the run asked for

def requested(path: str, readings: dict, decl: dict) -> bool:
    """Whether the run set this field: its launch command names the flag, and the value the run
    resolved to is not the field's declared default (a field at its default is not set, §11.4).
    A field the command does not name is the engine's own resolution, whatever it printed.
    An environment variable the command sets is set."""
    if path.startswith("env."):
        return True
    lc = readings.get("launch_config")
    if lc is None or path not in lc.values:
        return False
    given = st._one([v for v in lc.values[path] if v is not None] or lc.values[path])[0]
    shown = given
    if shown is None:
        res = readings.get("resolved_config")
        shown = st._one(res.values[path])[0] if res is not None and path in res.values else None
    f = decl["fields"].get(path)
    if f is not None and "default" in f and shown is not None:
        return st._canon(shown) != st._canon(f["default"])
    return True


def make_requested(decl: dict):
    return lambda path, readings, _unused: requested(path, readings, decl)


# ------------------------------------------------------------------ where each field goes

PARALLEL = {"tp_size": "parallel.tp", "pp_size": "parallel.pp", "dp_size": "parallel.dp"}
ROLES = {"model_path": "model", "served_model_name": "served_model", "speculative_draft_model_path": "drafter"}


# A flag or field of an earlier SGLang release that the modelled release removed, read as the field that replaced it
# (settings.translate_removed). TEMPORARY until the engine's field list states the earlier names.
TRANSLATIONS = {
    "cuda_graph_max_bs": (
        "cuda_graph_max_bs_decode", st.SAME_VALUE, lambda v: v is not None,
        "SGLang's --cuda-graph-max-bs capped the decode CUDA graph's batch size; v0.5.14 split the cap by phase and kept the "
        "old flag as a deprecated alias of --cuda-graph-max-bs-decode (server_args.py at v0.5.14: new_flag="
        "\"--cuda-graph-max-bs-decode\"), and v0.5.23 removed the alias; the prefill cap is its own field"),
}


def make_names(decl: dict) -> st.Names:
    def location(path: str):
        if path in PARALLEL:
            return PARALLEL[path]
        if path.startswith("env."):
            return f"engine.env.{path[4:]}"
        return f"engine.{path}" if path in decl["fields"] else None
    return st.Names(roles=ROLES, pool_role={}, derived=("frontend.router",), frontend_env=None, location=location,
                    translations=TRANSLATIONS)


def parallel_reasons(reasons: list[str], c: st.Decided, field_list) -> list[str]:
    """A parallel size the scenario lacks because its field is not modelled is that field's refusal, not a missing value:
    SGLang prints tp_size, pp_size and dp_size on every run, but the scenario states only what the engine models or the run
    set. The reason then names the field (field_not_modelled:dp_size)."""
    by_loc = {loc: name for name, loc in PARALLEL.items()}
    out = []
    for r in reasons:
        name = by_loc.get(r.removeprefix("required_setting_missing:")) if r.startswith("required_setting_missing:parallel.") else None
        f = field_list.lookup(name) if name else None
        if name and name in c.settings and c.settings[name].value is not None and f is not None and f.status == "not_modelled":
            out.append(f"field_not_modelled:{name}")
        else:
            out.append(r)
    return out


# ------------------------------------------------------------------ the context length

CONTEXT_LENGTH_KEYS = ("max_sequence_length", "seq_length", "max_seq_len", "model_max_length", "max_position_embeddings")
CONTEXT_LENGTH_FIELD = "context_length"


def context_window(catalog_root, model: str) -> int | None:
    """The context length SGLang serves a model at when the run states no --context-length: get_context_length
    (python/sglang/srt/utils/hf_transformers/common.py:677-694 at 297e54fd) over the catalog model's config.json. The
    first of CONTEXT_LENGTH_KEYS the config sets, times the rope-scaling factor, which counts only when the scaling
    names no original_max_position_embeddings and is not llama3. None when the entry has no config or none of the keys:
    SGLang's own fallback (2048) is not a value the checkpoint states, so it is not supplied."""
    f = Path(catalog_root) / "models" / model / "config.json"
    if not f.is_file():
        return None
    cfg = json.loads(f.read_text())
    cfg = cfg.get("text_config", cfg) if isinstance(cfg, dict) else {}
    factor = 1
    scaling = cfg.get("rope_scaling")
    if scaling:
        factor = scaling.get("factor", 1)
        if "original_max_position_embeddings" in scaling or scaling.get("rope_type") == "llama3":
            factor = 1
    for key in CONTEXT_LENGTH_KEYS:
        v = cfg.get(key)
        if v is not None:
            return int(factor * v)
    return None
