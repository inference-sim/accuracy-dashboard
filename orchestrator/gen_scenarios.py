#!/usr/bin/env python3
"""Generate one scenario+deployment file per deployment in the direct corpus.

# Why generated rather than committed by hand

There are 46 of them, and every field that matters is already stated by the corpus's own
topology record: model, gpu, precision, framework and the parallelism block. Transcribing
those by hand is how a scenario comes to describe a deployment other than the one it scores --
the previous corpus had two sweeps pointing at a single scenario file, so one of them was
scored against the wrong parallelism. Generating from the corpus makes that class of error
impossible: the file and the points it is scored against come from one record.

# Two documents, one file

blis-schemas v0.2.0 splits the immutable problem (Scenario: model, cluster inventory,
coefficient and engine-version references) from the tunable configuration applied to it
(Deployment: pools, each a parallelism layout with its own engine settings). Each file
written here holds both, `---` separated, rather than a scenario and a sibling
deployment file.

One file because a measurement row addresses a deployment by a single filename --
`{"scenario": "deepseek-v3-b200-fp4-sglang-tp4.yaml", ...}` -- and there are over three
thousand such rows across testdata/measurements. Splitting the pair would rewrite every
one of them to say nothing it does not already say. harness.LoadBundle reads the pair.

# What the corpus states, and what it does not

STATED, and written here: tp_size, pp_size, attention_dp_size, moe_ep_size, moe_tp_size,
framework, precision, serving, gpu, model.

NOT stated by the artifact corpus, and therefore set here: max_num_seqs, max_model_len,
gpu_memory_utilization, cudagraph_mode. block_size is never set here: the engine repository owns
engine defaults and a generator never writes one (X19, VLM-1), so it is written only when the run
stated it, and otherwise left out for the engine to resolve or refuse (blis-vllm #68). A sweep carrying `stated_config` (the
InferenceX direct corpus: what the run's own args line passed) supplies
gpu_memory_utilization, block_size, enable_prefix_caching and the speculative config, which
are then written as stated. gpu_memory_utilization not stated is vLLM v0.31.0's default,
0.92 (vllm/config/cache.py:103); prefix caching and speculation not stated are left out, so
v0.31.0's defaults apply (caching on, no drafting). A stated drafter the catalog graph does
not describe is not written (see UNPRICED_SPECULATORS), and the file's header says so.
The rest are NOT vLLM's defaults, and the written header says how each differs:
max_num_seqs 256 is the default only below 70 GiB or on an A100
(EngineArgs.get_batch_defaults, vllm/engine/arg_utils.py); cudagraph_mode's default is
FULL_AND_PIECEWISE (vllm/config/compilation.py). They are held fixed so committed scores stay comparable,
and the comparison scores the RATIO of step times across concurrency at a fixed deployment,
which is what a setting held constant affects least. Where a value could NOT be held it is
derived from the workload instead -- max_model_len must admit the longest sequence the
workload runs, or the scenario would describe a deployment that cannot serve its own points.

# Expert parallelism

The rule this asserts: with EP on, each rank holds whole experts and moe_tp_size is 1; with
EP off, experts are sliced tensor-parallel and moe_tp_size equals tp_size. That is vLLM's
rule only at attention_dp_size 1 -- with EP off and dp above one vLLM slices experts over
dp x tp ranks (flatten_tp_across_dp_and_pcp, vllm/model_executor/layers/fused_moe/config.py at
v0.31.0) -- and it is the corpus's own convention, which states both fields; this asserts
the corpus is consistent with it rather than assuming it.

Usage:

    python orchestrator/gen_scenarios.py inferencex_direct_corpus.json \
        -o scenarios/
"""

import argparse
import collections
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "ingest"))
import blis_commands as bc  # noqa: E402
import stack as sk  # noqa: E402
import support as sp  # noqa: E402

COEFFICIENTS = (
    "[cost-model-primitives, cost-model-collectives, cost-model-host-overheads, "
    "cost-model-attention, cost-model-recurrent, cost-model-memory]"
)

# Artifact precision -> the engine's quantization name. bf16 means the checkpoint is served
# unquantised, which the schema spells as an absent quantization rather than a name.
# int4 is a weight-only integer format the checkpoint declares in its own
# quantization_config, which the graph already read: servedDType returns the CHECKPOINT
# width for compressed-tensors rather than a flag width, so stating a flag here would add
# nothing and risk disagreeing with the graph. Kimi-K2.5 is the case in hand --
# compressed-tensors at group_size 32, which the catalog derives as weight_dtype int4.
QUANT = {"fp4": "nvfp4", "fp8": "fp8", "bf16": None, "int4": None}

# vLLM v0.31.0's CacheConfig.gpu_memory_utilization default (vllm/config/cache.py:103).
GPU_MEMORY_UTILIZATION_DEFAULT = 0.92

# Stated drafters the catalog graph does not describe: the kernel refuses a deployment that
# drafts with a method other than its graph's speculator (liftDraft, draft.go). MiniMax-M3's
# graph states its own MTP head; EAGLE3 runs a separate draft checkpoint.
UNPRICED_SPECULATORS = {("minimax-m3", "eagle3")}

# A KV cache dtype is not stated by the corpus. fp8 KV is the default for the fp8 and fp4
# arms in these frameworks; bf16 serving keeps an unquantised cache.
CACHE_DTYPE = {"fp4": "fp8", "fp8": "fp8", "bf16": "auto", "int4": "auto"}



class PackagingError(ValueError):
    """A deployment's node size is neither fixed by its chip's catalog entry nor recorded by the
    run (G5 value_not_recorded, design §11.4)."""


def node_size(dep: dict, packaging: dict) -> int:
    """The GPUs in one node of the deployment's cluster (design §2.2, SUB-3). A chip whose catalog
    entry fixes it (`packaging["gpus_per_node"]`, as `blis catalog resolve --chip` reports it)
    gives that value; any other chip takes the size the run recorded, `dep["gpus_per_node"]`.
    Neither is an error: no size is assumed."""
    fixed = packaging["gpus_per_node"]
    if fixed is not None:
        return fixed
    recorded = dep.get("gpus_per_node")
    if not isinstance(recorded, int) or isinstance(recorded, bool) or recorded < 1:
        raise PackagingError(f"{dep['scenario']}: the catalog entry of {dep['gpu']} fixes no node size and the run "
                             f"recorded none (gpus_per_node {recorded!r}); value_not_recorded")
    return recorded


def context_length(workloads: set[str]) -> int:
    """The smallest power-of-two window that admits every workload in this deployment.

    A workload identity is "<isl>:<osl>"; a request occupies isl+osl tokens at its longest.
    Rounded up to a power of two because that is how these engines are configured, and kept
    at least 32768 so a short workload does not produce an implausibly tight window.
    """
    longest = max(sum(int(p) for p in w.split(":")) for w in workloads)
    window = 32768
    while window < longest:
        window *= 2
    return window


def emit(dep: dict, workloads: set[str], labels: set[str], packaging: dict, engine_release: str) -> str:
    """The scenario+deployment file. `packaging` is what the chip's catalog entry fixes:
    {"gpus_per_node", "gpus_per_rack"}, each the entry's value or None (Catalog.packaging).
    The cluster states gpus_per_node only for a chip whose entry fixes none, and never states
    gpus_per_rack (the scenario takes both from the entry, and a restated value must equal it)."""
    par = dep["parallelism"]
    tp, ep, dp = par["tp_size"], par["moe_ep_size"], par["attention_dp_size"]
    # A dense model records moe_ep_size as null: it has no expert group, which is a different
    # thing from one unsharded group (ep=1). Expert parallelism is off either way.
    expert_parallel = ep is not None and ep > 1
    ranks = tp * dp
    per_node = node_size(dep, packaging)
    nodes = max(1, -(-ranks // per_node))
    quant = QUANT[dep["precision"]]
    stated = dep.get("stated_config", {})
    # A stated max_model_len is the run's own (None: left unset, so the engine resolves it, X19);
    # otherwise it is sized to the longest isl+osl the deployment's workloads run.
    max_len = stated["max_model_len"] if "max_model_len" in stated else context_length(workloads)
    name = dep["scenario"][: -len(".yaml")]
    block_size = stated.get("block_size")        # None: not stated, so left to the engine (X19)
    gmu = stated.get("gpu_memory_utilization", GPU_MEMORY_UTILIZATION_DEFAULT)
    spec = stated.get("speculative_method")
    unpriced_spec = (dep["model"], spec) in UNPRICED_SPECULATORS

    lines = [
        f"# {dep['model']} on {dep['gpu']}, {dep['precision']} under {dep['framework']},",
        f"# as the direct InferenceX corpus records this deployment.",
        "#",
        "# GENERATED by orchestrator/gen_scenarios.py from the corpus's own topology",
        "# record. Re-run after a corpus update rather than editing here.",
        "#",
        f"# Topology states: tp_size {tp}, pp_size {par['pp_size']}, attention_dp_size {dp},",
        f"# moe_ep_size {ep}, moe_tp_size {par['moe_tp_size']}. Workloads scored at this",
        f"# deployment: {', '.join(sorted(labels))}.",
        "#",
        f"# gpu_memory_utilization {gmu}: "
        + ("stated by the run." if "gpu_memory_utilization" in stated else
           "not stated, so vLLM v0.31.0's default (vllm/config/cache.py:103)."),
        "# block_size: " + (f"{block_size}, stated by the run." if block_size is not None else
                           "not stated by the run, so not written; the engine resolves it or refuses the file."),
    ]
    if "enable_prefix_caching" in stated:
        lines.append("# enable_prefix_caching: stated by the run.")
    if "max_model_len" in stated:
        lines.append("# max_model_len: " + ("recorded by the run." if max_len is not None else
                                            "not recorded; left unset, so the engine resolves it."))
    if spec and unpriced_spec:
        lines += [f"# speculative: the run drafts with {spec} x"
                  f"{stated['num_speculative_tokens']}, NOT written: the catalog graph",
                  "# describes no such drafter, so the kernel would refuse the file."]
    elif spec:
        lines.append("# speculative: stated by the run.")
    lines += [
        "#",
        "# max_num_seqs and cudagraph_mode are not in the corpus, so they are set here -- and not",
        "# to vLLM's defaults. max_num_seqs 256 is its default only below 70 GiB or on an A100;",
        "# and its cudagraph_mode",
        "# default is FULL_AND_PIECEWISE, not PIECEWISE. They are held",
        "# fixed so committed scores stay comparable; moving them to the engine's defaults is a",
        "# re-scoring decision. The comparison scores a ratio across concurrency at a fixed",
        "# deployment, which is what a setting held constant affects least. max_model_len is",
        "# derived from the workload instead, since a window shorter than isl+osl would describe a",
        "# deployment that cannot serve its own points.",
    ]
    lines += [
        "kind: Scenario",
        f"name: {name}",
        # The engine the scenario runs, in the form the simulator reads: engine: {kind, version}. The
        # release is the one the scoring simulator's stack.json names (LIF-6), never a constant here.
        "engine:",
        "  kind: vllm",
        f'  version: "{engine_release}"',
        "",
        f"model: {dep['model']}",
        f"coefficients: {COEFFICIENTS}",
        "",
        # The hardware inventory lives inside the cluster: it is what the problem is
        # handed and a deployment cannot change it.
        "cluster:",
        f"  hardware: {dep['gpu']}",
    ]
    if nodes > 1:
        lines.append("  fabric: ib-400g")
    lines.append(f"  nodes: {nodes}")
    if packaging["gpus_per_node"] is None:
        lines.append(f"  gpus_per_node: {per_node}")
    lines += [
        # The tunable half, as its own document. Same file because a measurement row
        # addresses a deployment by one filename; same name because there is exactly one
        # deployment per scenario here.
        "---",
        "kind: Deployment",
        f"name: {name}",
        "",
        "pools:",
        "  - role: colocated",
        f"    nodes: {nodes}",
        "    parallel:",
        f"      tp: {tp}",
        f"      pp: {par['pp_size']}",
        f"      dp: {dp}",
        f"      enable_expert_parallel: {str(expert_parallel).lower()}",
        "    engine:",
    ]
    if quant is not None:
        lines.append(f"      quantization: {quant}")
    lines += [
        f"      cache_dtype: {CACHE_DTYPE[dep['precision']]}",
        "      max_num_batched_tokens: 8192",
        "      max_num_seqs: 256",
    ]
    if max_len is not None:
        lines.append(f"      max_model_len: {max_len}")
    if block_size is not None:
        lines.append(f"      block_size: {block_size}")
    lines += [
        "      cudagraph_mode: PIECEWISE",
        f"      gpu_memory_utilization: {gmu}",
    ]
    if "enable_prefix_caching" in stated:
        pc = str(stated["enable_prefix_caching"]).lower()
        lines.append(f"      enable_prefix_caching: {pc}")
    if spec and not unpriced_spec:
        lines += [
            "      speculative:",
            f"        method: {stated['speculative_method']}",
            f"        num_spec_tokens: {stated['num_speculative_tokens']}",
        ]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("corpus")
    ap.add_argument("-o", "--out", required=True, help="scenario directory")
    ap.add_argument("--blis", required=True, help="the blis binary; it reports each chip's packaging")
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--stack", required=True, help="the scoring build's stack.json: the engine release the scenarios run")
    ap.add_argument("--check", action="store_true",
                    help="verify the files on disk match what would be generated")
    args = ap.parse_args()

    with open(args.corpus) as fh:
        corpus = json.load(fh)

    deps: dict[str, dict] = {}
    workloads = collections.defaultdict(set)
    labels = collections.defaultdict(set)
    for s in corpus["sweeps"]:
        name = s["scenario"]
        par = s["parallelism"]
        ep, moe_tp = par["moe_ep_size"], par["moe_tp_size"]
        # vLLM's expert-sharding rule, asserted rather than assumed. It governs how experts
        # are sharded, so it says nothing about a DENSE model, which has none: the snapshot
        # records both fields as null there and the rule is skipped rather than given a
        # default that would make it pass for the wrong reason.
        if ep is None and moe_tp is None:
            pass
        elif ep is None or moe_tp is None:
            return fail(f"{name}: moe_ep_size {ep!r} with moe_tp_size {moe_tp!r}; a "
                        f"deployment states both for an MoE model and neither for a dense "
                        f"one, so one present and one absent is a corpus error")
        elif ep > 1 and moe_tp != 1:
            return fail(f"{name}: moe_ep_size {ep} with moe_tp_size {moe_tp}; "
                        f"EP holds whole experts so moe_tp_size must be 1")
        elif ep == 1 and moe_tp != par["tp_size"]:
            return fail(f"{name}: EP off but moe_tp_size {moe_tp} != tp_size "
                        f"{par['tp_size']}; sliced experts span the TP group")
        prior = deps.get(name)
        if prior is not None and prior["parallelism"] != par:
            return fail(f"{name}: two deployments share one scenario name")
        deps[name] = s
        workloads[name].add(s["workload"])
        labels[name].add(s["label"])

    os.makedirs(args.out, exist_ok=True)
    engine_release = sk.load(args.stack).engine("vllm")
    stale = []
    cat = sp.Catalog(blis=str(Path(args.blis).resolve()), root=Path(args.catalog))
    for name, dep in sorted(deps.items()):
        try:
            text = emit(dep, workloads[name], labels[name], cat.packaging(dep["gpu"]), engine_release)
        except (PackagingError, bc.CommandError) as e:
            return fail(str(e))
        path = os.path.join(args.out, name)
        if args.check:
            try:
                with open(path) as fh:
                    current = fh.read()
            except FileNotFoundError:
                stale.append(f"{name} (missing)")
                continue
            if current != text:
                stale.append(name)
        else:
            with open(path, "w") as fh:
                fh.write(text)

    if args.check:
        if stale:
            print(f"{len(stale)} scenario(s) stale or missing:", file=sys.stderr)
            for n in stale:
                print(f"  {n}", file=sys.stderr)
            return 1
        print(f"checked {len(deps)} scenario(s): all current")
        return 0
    print(f"wrote {len(deps)} scenario(s) to {args.out}")
    return 0


def fail(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
