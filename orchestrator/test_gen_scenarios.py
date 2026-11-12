#!/usr/bin/env python3
"""Behavioural tests for the scenario generator's engine settings.

The defect these cover: every scenario was once written with a single fixed
gpu_memory_utilization, so deployments that differed only in it were given byte-identical
predictions. They also guard that the prose-scrub done when this was relocated from
blis-latency-kernel into gen_scenarios.py (issue #20) did not disturb any EMITTED YAML
field -- only comments changed.

Run: python3 orchestrator/test_gen_scenarios.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gen_scenarios import PackagingError, emit  # noqa: E402

# What a chip's catalog entry fixes (`blis catalog resolve --chip` packaging): an 8-GPU HGX part
# fixes nothing; GB200 NVL72 fixes 4 GPUs per node and 72 per rack.
OPEN = {"gpus_per_node": None, "gpus_per_rack": None}
GB200 = {"gpus_per_node": 4, "gpus_per_rack": 72}

FAILURES = []


def ck(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'} {label}{(': ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


def sweep(model="minimax-m2.5", stated=None, gpu="h200", node=8, tp=4):
    s = {
        "scenario": f"{model}-{gpu}-fp8-vllm-tp{tp}.yaml", "model": model, "gpu": gpu,
        "precision": "fp8", "framework": "vllm",
        "parallelism": {"tp_size": tp, "pp_size": 1, "attention_dp_size": 1,
                        "moe_ep_size": 1, "moe_tp_size": tp},
        "gpus_per_node": node,
    }
    if stated is not None:
        s["stated_config"] = stated
    return s


def engine(dep, field):
    text = emit(dep, {"1k1k"}, OPEN, "0.32.0")
    m = re.search(rf"^ +{field}: (\S+)$", text, re.M)
    return m.group(1) if m else None


def cluster_of(dep, packaging):
    text = emit(dep, {"1k1k"}, packaging, "0.32.0")
    return dict(re.findall(r"^  (hardware|nodes|gpus_per_node|gpus_per_rack|fabric): (\S+)$", text, re.M))


# Everything the generator may put in the engine block, with the stated_config key that supplies it.
STATED_KEYS = {"max_model_len": 4096, "block_size": 64, "gpu_memory_utilization": 0.88,
               "enable_prefix_caching": False}
# The engine settings a generator once wrote itself, and vLLM or the cost model defaults for each:
# none may appear unless the run stated it (X19). quantization is the deployment's own precision.
ONCE_WRITTEN = ("max_num_batched_tokens", "max_num_seqs", "cudagraph_mode", "cache_dtype")


def engine_block(text):
    """The key: value lines of the Deployment's engine block."""
    dep = text.split("\n---\n", 1)[1]
    block = dep.split("    engine:\n", 1)[1]
    return dict(re.findall(r"^      (\w+): (\S+)$", block, re.M))


def stated_values_only():
    """X19, COV-3: a generated scenario holds only values the run stated (or the deployment's own
    precision as quantization). Over every subset of the statable keys, the engine block's keys are
    exactly the stated ones; no setting that was once written by default appears."""
    import itertools
    keys = list(STATED_KEYS)
    bad = []
    for r in range(len(keys) + 1):
        for subset in itertools.combinations(keys, r):
            stated = {k: STATED_KEYS[k] for k in subset}
            for precision, quant in (("fp8", "fp8"), ("bf16", None)):
                dep = sweep(stated=stated)
                dep["precision"] = precision
                got = engine_block(emit(dep, {"1k1k"}, OPEN, "0.32.0"))
                want = set(subset) | ({"quantization"} if quant else set())
                if set(got) != want or any(k in got for k in ONCE_WRITTEN):
                    bad.append((subset, precision, sorted(got)))
    ck("over every subset of stated settings the engine block holds exactly the stated ones (X19)",
       not bad, str(bad[:2]))
    ck("the generator source writes no engine default: no default constant is left",
       not re.search(r"GPU_MEMORY_UTILIZATION_DEFAULT|CACHE_DTYPE|max_num_seqs: 256|PIECEWISE|max_num_batched_tokens: 8192",
                     Path(sys.modules["gen_scenarios"].__file__).read_text().split('"""', 2)[2]))


def main() -> int:
    ck("a GB200 NVL72 deployment writes neither gpus_per_node nor gpus_per_rack",
       cluster_of(sweep(gpu="gb200-nvl72", node=8), GB200) == {"hardware": "gb200-nvl72", "nodes": "1"},
       str(cluster_of(sweep(gpu="gb200-nvl72", node=8), GB200)))
    ck("a GB200 NVL72 deployment of 8 ranks spans two 4-GPU trays",
       cluster_of(sweep(gpu="gb200-nvl72", tp=8), GB200).get("nodes") == "2")
    ck("an H100 deployment writes the node size the run recorded",
       cluster_of(sweep(gpu="h100", node=8), OPEN) == {"hardware": "h100", "nodes": "1", "gpus_per_node": "8"})
    ck("a recorded node of 4 is written as 4, and 8 ranks span two of them",
       cluster_of(sweep(gpu="h100", node=4, tp=8), OPEN) == {"hardware": "h100", "nodes": "2", "gpus_per_node": "4",
                                                              "fabric": "ib-400g"})
    multi = emit(sweep(gpu="h100", node=4, tp=8), {"1k1k"}, OPEN, "0.32.0")
    text = next(iter(multi.values())) if isinstance(multi, dict) else str(multi)
    ck("a multi-node scenario lists cost-model-fabric (without it the handoff is priced 23% fast)",
       "cost-model-fabric" in text and "ASSUMED" in text)
    for chip, want in (("b300", "ib-800g"), ("gb300", "ib-800g"), ("h200", "ib-400g"), ("b200", "ib-400g")):
        ck(f"a multi-node {chip} scenario assumes {want}",
           cluster_of(sweep(gpu=chip, node=4, tp=8), OPEN).get("fabric") == want)
    one = emit(sweep(gpu="h100", node=8), {"1k1k"}, OPEN, "0.32.0")
    ck("a one-node scenario lists no fabric set", "cost-model-fabric" not in (next(iter(one.values())) if isinstance(one, dict) else str(one)))
    try:
        emit(sweep(gpu="h100", node=None), {"1k1k"}, OPEN, "0.32.0")
        ck("no recorded node size on a chip that fixes none is refused", False)
    except PackagingError as e:
        ck("no recorded node size on a chip that fixes none is refused as value_not_recorded",
           "value_not_recorded" in str(e) and "fixes no node size" in str(e), str(e))
    ck("a stated gpu_memory_utilization is written as stated",
       engine(sweep(stated={"gpu_memory_utilization": 0.85}),
              "gpu_memory_utilization") == "0.85")
    ck("an unstated gpu_memory_utilization is not written (X19)",
       engine(sweep(stated={}), "gpu_memory_utilization") is None)
    ck("a corpus with no stated_config writes none either",
       engine(sweep(), "gpu_memory_utilization") is None)
    for rel in ("0.32.0", "0.33.0"):
        t = emit(sweep(stated={}), {"1k1k"}, OPEN, rel)
        ck(f"the engine is stated as engine: {{kind, version}} at the release given ({rel}), never engine_version",
           "engine:\n  kind: vllm\n  version: \"%s\"" % rel in t and "engine_version" not in t.replace("never engine_version", ""))
    ck("a stated block_size is written as stated",
       engine(sweep(stated={"block_size": 128}), "block_size") == "128")
    # X19, VLM-1: the engine repository owns engine defaults; a generator never writes one.
    for model in ("qwen3-14b", "glm-5", "deepseek-v4-pro"):
        ck(f"an unstated block_size is not written ({model})",
           engine(sweep(model, stated={}), "block_size") is None)
    ck("a stated enable_prefix_caching is written as stated",
       engine(sweep(stated={"enable_prefix_caching": False}),
              "enable_prefix_caching") == "false")
    ck("an unstated enable_prefix_caching is left to the engine default",
       engine(sweep(stated={}), "enable_prefix_caching") is None)
    mtp = sweep("deepseek-v4-pro", stated={"speculative_method": "mtp",
                                           "num_speculative_tokens": 2})
    ck("a stated speculative config is written as stated",
       (engine(mtp, "method"), engine(mtp, "num_spec_tokens")) == ("mtp", "2"))
    ck("a stated max_model_len is written as stated, not sized from the workload",
       engine(sweep(stated={"max_model_len": 1048576}), "max_model_len") == "1048576")
    ck("a max_model_len stated as None is left unset, so the engine resolves it",
       engine(sweep(stated={"max_model_len": None}), "max_model_len") is None)
    ck("an unstated max_model_len is not sized from the workload and not written (X19)",
       engine(sweep(stated={}), "max_model_len") is None)
    ck("an unstated speculative config is left out",
       engine(sweep("deepseek-v4-pro", stated={}), "method") is None)

    stated_values_only()

    # The relocation reworded comments but must emit valid Scenario + Deployment docs.
    text = emit(sweep(stated={}), {"1k1k"}, OPEN, "0.32.0")
    ck("emits both a Scenario and a Deployment document",
       "kind: Scenario" in text and "kind: Deployment" in text)

    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} failure(s): {FAILURES}")
        return 1
    print("PASS: 0 failure(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
