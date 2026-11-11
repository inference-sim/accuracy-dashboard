"""Prefill/decode (P/D) points: the two pools a row records, why a P/D shape is refused by name, and
the scenario that states its two pools (design §11.4 topology_unsupported, §11.2; dashboard #61).

What a row says. An InferenceX P/D row has, for each pool, the number of workers, the GPUs of the
pool, tensor and expert parallel size and a DP-attention flag (`prefill_*`, `decode_*`). A pool on
DP attention runs data-parallel size above one. The row spells that as `tp` equal to the pool's
GPUs per worker; the recipe states it (`data-parallel-size`), and where it does, the recipe's value
decides.

Named refusals (all are G5 `topology_unsupported`, design §11.4, with the part of the layout the stack
cannot express as the subject, so the reader sees a missing engine feature and not a missing writer):

  pd_pool_data_parallel      a pool runs data-parallel size above one: the engine refuses a KV
                             transfer with data parallelism (blis-vllm#47, M3);
  pd_unequal_data_parallel   the two pools differ in data-parallel size: the placement refuses it
                             (inference-sim#1952, M3);
  pd_pool_not_recorded       a pool has no workers or no GPUs in the row;
  pd_agentic                 an agentic replay of a P/D deployment is not written (dashboard#64).

A P/D shape that is not refused is written as two pools, the NIXL connector, the router the run's
recipe names, and counts of instances that `blis replay` takes as flags (`--prefill-instances`,
`--decode-instances`), by `build_pd`.
"""
from __future__ import annotations

from dataclasses import dataclass

import pd_recipe as pdr
import settings as st

NIXL = ("NixlConnector", "NixlPullConnector", "NixlPushConnector")
TRANSFER_PATHS = ("kv_transfer_config.kv_connector", "kv_transfer_config.kv_role")

POOL_DP = "pd_pool_data_parallel"
UNEQUAL_DP = "pd_unequal_data_parallel"
NOT_RECORDED = "pd_pool_not_recorded"
AGENTIC = "pd_agentic"
TOPOLOGY_SLUGS = (POOL_DP, UNEQUAL_DP, NOT_RECORDED, AGENTIC)


@dataclass
class Pool:
    role: str
    workers: int
    gpus: int                 # per worker
    tp: int                   # the row's
    ep: int
    dp_attention: bool
    dp: int                   # decided: the recipe's data-parallel-size, else the reading of the row's flag


def _flag_int(flags: dict, name: str):
    for k in (name, name.replace("-", "_")):
        v = flags.get(k)
        if isinstance(v, int) and not isinstance(v, bool):
            return v
    return None


def pools_of(row: dict, recipe: "pdr.Recipe | None" = None) -> dict | None:
    """The row's two pools, or None when it records a pool without workers or GPUs."""
    out = {}
    for role in ("prefill", "decode"):
        workers, total = row.get(f"{role}_num_workers"), row.get(f"num_{role}_gpu")
        tp = row.get(f"{role}_tp")
        if not (isinstance(workers, int) and workers > 0 and isinstance(total, int) and total > 0
                and total % workers == 0 and isinstance(tp, int) and tp > 0):
            return None
        gpus = total // workers
        attn = bool(row.get(f"{role}_dp_attention"))
        dp = 1
        if attn:
            # The row spells DP attention as tp equal to the pool's GPUs; the recipe states the size.
            dp = gpus
        if recipe is not None:
            stated = _flag_int(recipe.pools[role].flags, "data-parallel-size")
            if stated is not None:
                dp = stated
        out[role] = Pool(role, workers, gpus, tp, int(row.get(f"{role}_ep") or 1), attn, dp)
    return out


def topology_reasons(row: dict, pools: dict | None) -> list[str]:
    """The named refusals of a P/D row's shape (module docstring); every one that is true."""
    if pools is None:
        return [f"topology_unsupported:{NOT_RECORDED}"]
    out = []
    dps = {p.dp for p in pools.values()}
    if max(dps) > 1:
        out.append(f"topology_unsupported:{POOL_DP}")
    if len(dps) > 1:
        out.append(f"topology_unsupported:{UNEQUAL_DP}")
    if row.get("benchmark_type") == "agentic_traces":
        out.append(f"topology_unsupported:{AGENTIC}")
    return out


def pseudo_launch(recipe: "pdr.Recipe", role: str, row: dict, pool: Pool) -> dict:
    """A launch configuration of one pool in the form settings.read_launch_config reads: the recipe's
    flags of that pool (CLI spelling) and its environment, plus the tensor, pipeline and data
    parallel sizes the recipe leaves at vLLM's default where the pool's GPUs equal their product
    (otherwise the pool's size is left unstated and the build names it)."""
    spec = recipe.pools[role]
    args = dict(spec.flags)
    if not pool.dp_attention:
        tp = _flag_int(args, "tensor-parallel-size") or pool.tp
        pp = _flag_int(args, "pipeline-parallel-size") or 1
        dp = _flag_int(args, "data-parallel-size") or 1
        if tp * pp * dp == pool.gpus:
            args.setdefault("tensor-parallel-size", tp)
            args.setdefault("pipeline-parallel-size", pp)
            args.setdefault("data-parallel-size", dp)
    cfg = {"roles": {role: {"args": args, "env": dict(spec.env)}}}
    if recipe.gpus_per_node:
        cfg["resources"] = {"gpus_per_node": recipe.gpus_per_node}
    return cfg


def read_pool(launch: dict) -> "tuple[st.Reading, dict]":
    """The pool's settings reading, without its KV-transfer connector and role, which are the
    deployment's `pd_transfer` and the pool's role and not engine settings: (reading, {path: value})."""
    rd = st.read_launch_config(launch)
    taken = {}
    for p in TRANSFER_PATHS:
        vals = rd.values.pop(p, None)
        if vals:
            taken[p] = vals[0]
    return rd, taken


def epp_config(policy: str) -> str:
    """The endpoint picker configuration of a P/D deployment under one of the policies the router
    table may name (blis-substrate routertable.Policies): every request is split into a prefill and a
    decode leg, and each leg is placed by the policy's composition."""
    scorers = {"round-robin": [], "random-picker": [],
               "least-active-requests": [("active-request-scorer", 1)],
               "default": [("queue-scorer", 2), ("kv-cache-utilization-scorer", 2), ("prefix-cache-scorer", 3)]}
    producers = {"round-robin": [], "random-picker": [], "least-active-requests": ["inflight-load-producer"],
                 "default": ["approx-prefix-cache-producer"]}
    if policy not in scorers:
        raise ValueError(f"{policy!r} is not a policy llm-d's router offers")
    plugins = producers[policy] + sorted({s for s, _ in scorers[policy]}) + [
        "prefill-filter", "decode-filter", "random-picker" if policy == "random-picker" else "max-score-picker",
        "always-disagg-pd-decider"]
    lines = ["apiVersion: llm-d.ai/v1", "kind: EndpointPickerConfig", "plugins:"]
    for p in plugins:
        if p == "approx-prefix-cache-producer":
            lines += [f"- type: {p}", "  parameters:", "    maxPrefixTokensToMatch: 16384", "    lruCapacityPerServer: 31250"]
        else:
            lines.append(f"- type: {p}")
    lines += ["- type: disagg-profile-handler", "  parameters:", "    deciders:", "      prefill: always-disagg-pd-decider",
              "schedulingProfiles:"]
    for prof in ("prefill", "decode"):
        lines += [f"- name: {prof}", "  plugins:", f"  - pluginRef: {prof}-filter"]
        for s, w in scorers[policy]:
            lines += [f"  - pluginRef: {s}", f"    weight: {w}"]
        lines.append("  - pluginRef: " + ("random-picker" if policy == "random-picker" else "max-score-picker"))
    return "\n".join(lines) + "\n"


def epp_name(policy: str) -> str:
    return f"pd-{policy}.epp.yaml"


def recovery_substitution(role: str, recipe_meta: dict, fields: list[str], derived: list[str]) -> dict:
    """The G2 substitution naming that a pool's arguments are the recipe's, not the run's own record
    (design §11.2, "a recorded value was missing and replaced"): the fields the recipe states, by
    recipe and commit. The recipe states what the launcher was told, which is not proof of what ran."""
    d = (f"the {role} pool's engine arguments are those of InferenceX recipe {recipe_meta['path']} at the run's "
         f"commit {recipe_meta['commit']} (CONFIG_FILE {recipe_meta['config_file']}), not the run's server log, "
         f"which is one worker's or gone; fields the recipe states: {', '.join(sorted(fields)) or 'none'}")
    if derived:
        d += (f"; sizes the recipe leaves at vLLM's default, equal to the pool's GPUs: {', '.join(sorted(derived))}")
    return {"kind": "estimated", "subject": f"engine.{role}.recipe", "detail": d}


def placement_substitution(recipe: "pdr.Recipe") -> dict | None:
    """BLIS puts each pool on nodes of its own; a recipe that allows a prefill and a decode worker
    to share a node (allow_prefill_decode_colocation) ran with workers that might. The KV handoff is
    priced over the cluster fabric either way, which is what the recipe's UCX transport list
    (cuda_copy, rc) also selects when it sets one."""
    if not recipe.colocation:
        return None
    return {"kind": "execution_mode", "subject": "pool placement",
            "detail": "BLIS places the prefill and decode pools on nodes of their own; the recipe allows "
                      "prefill and decode workers to share a node (allow_prefill_decode_colocation)"}


def build_pd(pool_builts: dict, recipe: "pdr.Recipe", pools: dict, taken: dict, *, name: str, policy: str | None,
             per_node: int | None, launch: dict | None = None) -> "st.Built":
    """The Scenario + Deployment of the two pools. `pool_builts` are settings.build's results for
    each pool (one engine's ranks); the pools' node counts are the recipe's, but never fewer nodes
    than hold the pool's workers. The connector is the pools' kv-transfer-config, which must agree."""
    pre, dec = pool_builts["prefill"], pool_builts["decode"]
    dep_pools, nodes = [], 0
    for role, b in (("prefill", pre), ("decode", dec)):
        pool = dict(b.deployment["pools"][0])
        need = pools[role].workers * pools[role].gpus
        stated = recipe.pools[role].nodes or 1
        n = max(stated, -(-need // per_node)) if per_node else stated
        pool.update(role=role, nodes=n)
        dep_pools.append(pool)
        nodes += n
    connectors = {t.get("kv_transfer_config.kv_connector") for t in taken.values()} - {None}
    dep = {"kind": "Deployment", "name": name, "pools": dep_pools}
    if connectors:
        dep["pd_transfer"] = {"connector": sorted(connectors)[0]}
    if policy is not None:
        dep["router"] = {"endpoint_picker_config": epp_name(policy)}
    scenario = dict(pre.scenario)
    scenario["cluster"] = {**scenario["cluster"], "nodes": nodes}
    subs = pre.substitutions + dec.substitutions
    if nodes > 1 and "fabric" not in scenario["cluster"]:
        # Two pools never share a node, so a P/D deployment crosses the fabric: the handoff is priced
        # at its class and the registry's efficiency for it. No recipe or cluster record of
        # InferenceX names the class, so the assumed one is named on the point.
        recorded = recipe.fabric or st.recorded_fabric(launch)
        scenario["cluster"]["fabric"] = recorded or st.ASSUMED_FABRIC
        if st.FABRIC_COEFFICIENT not in scenario["coefficients"]:
            scenario["coefficients"] = [*scenario["coefficients"], st.FABRIC_COEFFICIENT]
        if recorded is None:
            subs = subs + [st.ASSUMED_FABRIC_SUBSTITUTION]
    out = st.Built(scenario=scenario, deployment=dep, acceptance_length=None,
                   gpus=sum(p.workers * p.gpus for p in pools.values()))
    out.reasons = sorted(set(pre.reasons + dec.reasons))
    out.substitutions = subs
    out.node_source = pre.node_source
    out.vllm_names = pre.vllm_names
    return out


def benchmark_client_note(recipe: "pdr.Recipe") -> str:
    """The text of the `benchmark_client` client difference of a prefill/decode point. The run's
    client is the benchmark its recipe names (srt-slurm's sa-bench for every recipe read), not the
    InferenceX client whose requests the replay rebuilds. The constants below are the benchmark's
    defaults at NVIDIA/srt-slurm main on 2026-11-11 (src/srtctl/benchmarks/scripts/sa-bench/bench.sh),
    the repository the runners cloned unpinned: a random range ratio of 0.8, 10 x concurrency prompts, 2 x
    concurrency warm-ups, and prompts sent through the chat template unless the recipe says otherwise."""
    b = recipe.benchmark
    chat = b.get("use_chat_template")
    return (f"the run's client is its recipe's `{b.get('type', 'unnamed')}` benchmark (srt-slurm), not InferenceX's "
            f"benchmark_serving.py; the replay sends the InferenceX client's seed-0 request lengths, and the recipe's "
            f"benchmark draws its own random prompts (range ratio {b.get('random_range_ratio', 0.8)} and the counts "
            f"are assumed equal), with the chat template {'on' if chat is None or chat else 'off'}"
            f"{' (its default)' if chat is None else ''}, which can shift the sent lengths")


def log_conflicts(configs: list[dict], recipe: "pdr.Recipe", pools: dict) -> list[str]:
    """A server log that survives for a P/D run is one worker's. Its resolved engine configuration must
    agree with a pool of the recipe: some pool has the logged tensor-parallel and data-parallel size, and
    of those pools one has the logged KV dtype and prefix caching where the recipe states them. Otherwise
    the recipe is not what ran, and the point is a conflict naming the field
    (`conflict:server_log_vs_recipe.<field>`); nothing is recovered from a recipe the log contradicts."""
    out = []
    for c in configs:
        near = []
        for role, pool in pools.items():
            flags = recipe.pools[role].flags
            tp = _flag_int(flags, "tensor-parallel-size") or (None if pool.dp_attention else pool.tp)
            if c.get("tensor_parallel_size") in (None, tp) or tp is None:
                if c.get("data_parallel_size") in (None, pool.dp):
                    near.append(flags)
        if not near:
            out.append("conflict:server_log_vs_recipe.tensor_parallel_size")
            continue
        kv_ok = [f for f in near if f.get("kv-cache-dtype") is None or c.get("kv_cache_dtype") in (None, f["kv-cache-dtype"])]
        if not kv_ok:
            out.append("conflict:server_log_vs_recipe.kv_cache_dtype")
        elif not any(f.get("no-enable-prefix-caching") is None or c.get("enable_prefix_caching") in (None, not f["no-enable-prefix-caching"])
                     for f in kv_ok):
            out.append("conflict:server_log_vs_recipe.enable_prefix_caching")
    return sorted(set(out))


def aggregated_launch(recipe: "pdr.Recipe", meta: dict) -> tuple[dict, list[str]]:
    """(a launch configuration in settings.read_launch_config's form, the sizes left at default) of a
    colocated multi-node run, from its aggregated recipe: the one pool's flags and environment, the
    recipe's GPUs per node, and the model the sweep served (the master configuration's). A tensor,
    pipeline or data-parallel size the recipe does not state is vLLM's default 1, written only where the
    stated sizes times the defaults equal the engine's GPUs (otherwise it is left unstated and the build
    names it)."""
    pool = recipe.pools["aggregated"]
    args = dict(pool.flags)
    names = ("tensor-parallel-size", "pipeline-parallel-size", "data-parallel-size")
    prod = 1
    for n in names:
        prod *= _flag_int(args, n) or 1
    derived = []
    if pool.workers and pool.gpus and prod == pool.workers * pool.gpus:
        for n in names:
            if _flag_int(args, n) is None:
                args[n] = 1
                derived.append(n.replace("-", "_"))
    cfg = {"roles": {"aggregated": {"args": args, "env": dict(pool.env)}}}
    if meta.get("model"):
        cfg["model"] = {"path": meta["model"]}
    if recipe.gpus_per_node:
        cfg["resources"] = {"gpus_per_node": recipe.gpus_per_node}
    return cfg, derived
