"""The srt-slurm recipe a prefill/decode (P/D) run launched from, and what it states (design §11.2, §11.3).

A P/D run's server log is one worker's, and for most runs it is gone, so the engine arguments of the
two pools are read from the recipe InferenceX launched the run with, at the commit the run executed
(P/D recipe recovery). Three steps, each of which refuses rather than guesses:

  1. Which recipe. The InferenceX master configuration at the run's commit lists, for each
     (model, runner, precision, framework) and sequence length, the search-space items the sweep
     ran: the concurrencies, each pool's workers, tensor and expert parallel size and DP-attention
     flag, and the recipe (`CONFIG_FILE=recipes/...`). The row is that item: exactly one item must
     agree with the row on all of them, or the row is `ambiguous` or `no_master_entry`.
  2. Where the file is. `CONFIG_FILE` names a path in the srt-slurm checkout the runner builds, and
     the runner's launch script overlays InferenceX's own recipes onto it (`cp -rT SRC DST`). The
     file is the source of the overlay whose destination holds the path; failing that, the same path
     under InferenceX's `srt-slurm-recipes/`. A path in neither came from the unpinned srt-slurm
     repository itself: `not_in_tree`. Overlays that give different files are `ambiguous`.
  3. What it says. `parse` reads the recipe; `check_row` compares it with the row (workers, GPUs
     per worker, sequence lengths, concurrency, precision) and any disagreement is a conflict, not a
     recovery.

Nothing here reads the network: `Recipes` (recipes.py) holds the tree of the commit, and the caller
gives the text of the files. The freezer (pull.py) reads once and keeps the file in the pull, so
scoring needs no network.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import yaml

ROOT = "benchmarks/multi_node/srt-slurm-recipes/"
# Reasons a recipe cannot be recovered, each a slug of `recipe_unresolved:<slug>`.
NO_MASTER, AMBIGUOUS, NOT_IN_TREE, UNREADABLE, NO_CONFIG_FILE, NO_COMMIT = (
    "no_master_entry", "ambiguous", "not_in_tree", "unreadable", "no_config_file", "run_commit_unreadable")
SLUGS = (NO_MASTER, AMBIGUOUS, NOT_IN_TREE, UNREADABLE, NO_CONFIG_FILE, NO_COMMIT)


def _hw(runner) -> str:
    return str(runner or "").removeprefix("cluster:").split("-", 1)[0]


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def master_matches(entries: list, row: dict) -> list[tuple[str, str | None]]:
    """The (master key, CONFIG_FILE) of every search-space item of the master configuration that is
    this row: same framework, model prefix, runner hardware and precision, a concurrency list holding the
    row's, and the row's workers, tensor and expert parallel size and DP-attention flag, and speculative
    decoding. A prefill/decode item (`prefill` and `decode`) also agrees on the sequence lengths; a
    colocated item (`worker`, as the agentic multi-node items) is the row's `prefill_*` fields with no
    decode pool of its own (the row's decode fields zero or the same), and agrees on the benchmark type (an agentic item has no sequence lengths). `entries` are
    (key, dict) pairs."""
    hits = []
    for key, v in entries:
        if v.get("framework") != row.get("framework") or v.get("model-prefix") != row.get("model") \
                or _hw(v.get("runner")) != row.get("hardware") or v.get("precision") != row.get("precision"):
            continue
        for scen_name, scen in (v.get("scenarios") or {}).items():
            for s in scen or []:
                agentic_item = s.get("isl") is None
                if agentic_item != (row.get("benchmark_type") == "agentic_traces"):
                    continue
                if not agentic_item and (s.get("isl") != row.get("isl") or s.get("osl") != row.get("osl")):
                    continue
                for ss in s.get("search-space") or []:
                    if row.get("conc") not in (ss.get("conc-list") or []):
                        continue
                    if (row.get("spec_method") or "none") != (ss.get("spec-decoding") or "none"):
                        continue
                    if "worker" in ss:
                        w = ss.get("worker") or {}
                        # The API fills a colocated row's decode fields with zeros or with the prefill ones.
                        mirrored = all(row.get(f"decode_{k}") in (None, 0, row.get(f"prefill_{k}"))
                                       for k in ("num_workers", "tp", "ep"))
                        mine = (row.get("prefill_num_workers"), row.get("prefill_tp"), row.get("prefill_ep"),
                                bool(row.get("prefill_dp_attention")), mirrored)
                        theirs = (w.get("num-worker"), w.get("tp"), w.get("ep"), bool(w.get("dp-attn")), True)
                        settings = w.get("additional-settings") or []
                    else:
                        pf, dc = ss.get("prefill") or {}, ss.get("decode") or {}
                        mine = (row.get("prefill_num_workers"), row.get("prefill_tp"), row.get("prefill_ep"),
                                bool(row.get("prefill_dp_attention")), row.get("decode_num_workers"),
                                row.get("decode_tp"), row.get("decode_ep"), bool(row.get("decode_dp_attention")))
                        theirs = (pf.get("num-worker"), pf.get("tp"), pf.get("ep"), bool(pf.get("dp-attn")),
                                  dc.get("num-worker"), dc.get("tp"), dc.get("ep"), bool(dc.get("dp-attn")))
                        settings = (pf.get("additional-settings") or []) + (dc.get("additional-settings") or [])
                    if mine != theirs:
                        continue
                    cf = [x[len("CONFIG_FILE="):].strip("\"'") for x in settings if str(x).startswith("CONFIG_FILE=")]
                    hits.append((key, cf[0] if cf else None))
    return sorted(set(hits), key=lambda h: (h[0], h[1] or ""))


_CP = re.compile(r"""cp\s+-r[Tt]?\s+"?\$\{?GITHUB_WORKSPACE\}?/benchmarks/multi_node/srt-slurm-recipes/(\S+?)"?\s+\\?\s*"?(recipes/\S+?)"?(?:\s|$)""")
_SRC = re.compile(r"""SRT_RECIPE_SRC="\$GITHUB_WORKSPACE/benchmarks/multi_node/srt-slurm-recipes/([^"]+)"\s*\n\s*SRT_RECIPE_DST="(recipes/[^"]+)\"""")


def overlays(script: str) -> list[tuple[str, str]]:
    """The (source under srt-slurm-recipes/, destination under recipes/) pairs a runner's launch
    script copies: `cp -rT "$GITHUB_WORKSPACE/.../srt-slurm-recipes/SRC" DST`, and the
    SRT_RECIPE_SRC / SRT_RECIPE_DST pair some scripts assign."""
    out = [(m.group(1).rstrip("/"), m.group(2).rstrip("/")) for m in _CP.finditer(script)]
    out += [(m.group(1).rstrip("/"), m.group(2).rstrip("/")) for m in _SRC.finditer(script)]
    return sorted(set(out))


def source_paths(config_file: str, tree: dict, scripts: dict[str, str], hardware: str) -> list[str]:
    """The InferenceX paths the recipe `config_file` can be, of those in `tree`: through each
    overlay of the launch scripts of the row's hardware whose destination holds the path (the
    longest destination only), else the same path under srt-slurm-recipes/."""
    cands = []
    for name, text in sorted(scripts.items()):
        if not name.rsplit("/", 1)[-1].startswith(f"launch_{hardware}-"):
            continue
        for src, dst in overlays(text):
            if config_file.startswith(dst + "/"):
                cands.append((len(dst), ROOT + src + config_file[len(dst):]))
    if cands:
        best = max(n for n, _ in cands)
        found = sorted({p for n, p in cands if n == best and p in tree})
    else:
        direct = ROOT + config_file.removeprefix("recipes/")
        found = [direct] if direct in tree else []
    return found


# ------------------------------------------------------------------ the recipe

@dataclass
class PoolSpec:
    role: str                       # "prefill" | "decode"
    workers: int | None
    gpus: int | None                # per worker
    nodes: int | None
    flags: dict = field(default_factory=dict)      # vllm_config.<role>: CLI flag spelling -> value
    env: dict = field(default_factory=dict)        # <role>_environment


@dataclass
class Recipe:
    name: str | None
    image: str | None
    model_alias: str | None
    precision: str | None
    gpu_type: str | None
    gpus_per_node: int | None
    pools: dict                     # role -> PoolSpec
    connector: str | None           # backend.connector: null means vLLM's own kv-transfer-config
    colocation: bool | None         # backend.allow_prefill_decode_colocation
    frontend: dict
    benchmark: dict
    dynamo: dict
    fabric: str | None = None       # resources.fabric, the inter-node fabric class, when a recipe states one


def parse(text: str) -> Recipe:
    """Read a recipe. Only structure is read here; the values are decided later by the engine's field
    list. A prefill/decode recipe has the pools `prefill` and `decode` (`prefill_workers`,
    `gpus_per_prefill`, ...); an aggregated one, one pool `aggregated` over `agg_nodes` nodes
    (`agg_workers`, `gpus_per_agg`). A recipe that is not a mapping, or has no resources, is an error."""
    doc = yaml.safe_load(text)
    if not isinstance(doc, dict) or not isinstance(doc.get("resources"), dict):
        raise ValueError("recipe has no resources block")
    res, be = doc["resources"], doc.get("backend") or {}
    cfg = be.get("vllm_config") or {}
    pools = {}
    if "agg_workers" in res:
        pools["aggregated"] = PoolSpec(
            role="aggregated", workers=_int(res.get("agg_workers")), gpus=_int(res.get("gpus_per_agg")),
            nodes=_int(res.get("agg_nodes")), flags=dict(cfg.get("aggregated") or {}),
            env={str(k): str(v) for k, v in (be.get("aggregated_environment") or {}).items()})
    else:
        for role in ("prefill", "decode"):
            pools[role] = PoolSpec(
                role=role, workers=_int(res.get(f"{role}_workers")), gpus=_int(res.get(f"gpus_per_{role}")),
                nodes=_int(res.get(f"{role}_nodes")), flags=dict(cfg.get(role) or {}),
                env={str(k): str(v) for k, v in (be.get(f"{role}_environment") or {}).items()})
    model = doc.get("model") or {}
    return Recipe(name=doc.get("name"), image=model.get("container"), model_alias=model.get("path"),
                  precision=model.get("precision"), gpu_type=res.get("gpu_type"),
                  gpus_per_node=_int(res.get("gpus_per_node")), pools=pools, connector=be.get("connector"),
                  colocation=be.get("allow_prefill_decode_colocation"), frontend=dict(doc.get("frontend") or {}),
                  benchmark=dict(doc.get("benchmark") or {}), dynamo=dict(doc.get("dynamo") or {}),
                  fabric=res.get("fabric") if isinstance(res.get("fabric"), str) and res.get("fabric") else None)


def concurrencies(r: Recipe) -> list[int]:
    raw = r.benchmark.get("concurrencies")
    if isinstance(raw, list):
        return [int(x) for x in raw]
    return [int(x) for x in str(raw or "").split("x") if x.strip().isdigit()]


def check_row(r: Recipe, row: dict) -> list[str]:
    """The recipe against the row it is said to have run: every disagreement is a
    `conflict:recipe.<field>` (the recipe is then not this row's, and nothing is recovered)."""
    out = []
    if "aggregated" in r.pools:
        # One engine over several nodes: the recipe's workers are engines, the row's `num_workers` is the
        # data-parallel size (tp x dp = the GPUs), so the GPUs and the stated parallel sizes are compared.
        p = r.pools["aggregated"]
        if p.workers and p.gpus and row.get("num_prefill_gpu") is not None and p.workers * p.gpus != row["num_prefill_gpu"]:
            out.append("conflict:recipe.gpus_per_agg")
        for flag, field in (("tensor-parallel-size", "prefill_tp"), ("data-parallel-size", "prefill_num_workers")):
            v = p.flags.get(flag)
            if isinstance(v, int) and row.get(field) is not None and v != row[field]:
                out.append(f"conflict:recipe.{flag}")
        cs = concurrencies(r)
        if cs and row.get("conc") not in cs:
            out.append("conflict:recipe.concurrency")
        return sorted(set(out))
    for role in ("prefill", "decode"):
        p = r.pools[role]
        workers, gpus = row.get(f"{role}_num_workers"), row.get(f"num_{role}_gpu")
        if p.workers != workers:
            out.append(f"conflict:recipe.{role}_workers")
        if p.workers and p.gpus and gpus is not None and p.workers * p.gpus != gpus:
            out.append(f"conflict:recipe.gpus_per_{role}")
    b = r.benchmark
    if b.get("isl") is not None and b.get("isl") != row.get("isl"):
        out.append("conflict:recipe.isl")
    if b.get("osl") is not None and b.get("osl") != row.get("osl"):
        out.append("conflict:recipe.osl")
    cs = concurrencies(r)
    if cs and row.get("conc") not in cs:
        out.append("conflict:recipe.concurrency")
    if r.precision and row.get("precision") and r.precision != row.get("precision"):
        out.append("conflict:recipe.precision")
    return sorted(set(out))


def kv_transfer(flags: dict) -> dict | None:
    """The pool's kv-transfer-config as a mapping, or None when the pool states none."""
    v = flags.get("kv-transfer-config")
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return None
    return v if isinstance(v, dict) else None


def router_mode(r: Recipe) -> tuple[str, int | None, bool]:
    """(the Dynamo frontend's router mode, its session-affinity TTL in seconds or None, whether the
    recipe states the mode). A recipe that states no mode runs the frontend's default,
    round-robin (docs/m2/dynamo-router-evidence.md). The mode is read from the frontend block's
    `router-mode` argument or the DYN_ROUTER_MODE variable."""
    fe = r.frontend
    args = fe.get("args") if isinstance(fe.get("args"), dict) else {}
    env = fe.get("env") if isinstance(fe.get("env"), dict) else {}
    mode = args.get("router-mode") or args.get("router_mode") or env.get("DYN_ROUTER_MODE")
    ttl = args.get("router-session-affinity-ttl-secs") or args.get("router_session_affinity_ttl_secs")
    if mode is None:
        return "round-robin", None, False
    return str(mode), (int(ttl) if ttl is not None else None), True


_HEX40 = re.compile(r"^[0-9a-f]{40}$")


def router_revision(r: Recipe) -> str | None:
    """The full commit of the Dynamo build the recipe pins (`dynamo: {hash: ...}` and its spellings), or
    None. A recipe that names a wheel or a version (every one read) pins no commit: a wheel version maps
    to no commit in any source the dashboard reads, so the router build is then not recorded."""
    for k in ("hash", "commit", "revision", "sha"):
        v = r.dynamo.get(k)
        if isinstance(v, str) and _HEX40.match(v):
            return v
    return None
