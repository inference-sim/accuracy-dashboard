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
    text = emit(dep, {"1024:1024"}, {"1k1k"}, OPEN)
    m = re.search(rf"^ +{field}: (\S+)$", text, re.M)
    return m.group(1) if m else None


def cluster_of(dep, packaging):
    text = emit(dep, {"1024:1024"}, {"1k1k"}, packaging)
    return dict(re.findall(r"^  (hardware|nodes|gpus_per_node|gpus_per_rack|fabric): (\S+)$", text, re.M))


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
    try:
        emit(sweep(gpu="h100", node=None), {"1024:1024"}, {"1k1k"}, OPEN)
        ck("no recorded node size on a chip that fixes none is refused", False)
    except PackagingError as e:
        ck("no recorded node size on a chip that fixes none is refused as value_not_recorded",
           "value_not_recorded" in str(e) and "fixes no node size" in str(e), str(e))
    ck("a stated gpu_memory_utilization is written as stated",
       engine(sweep(stated={"gpu_memory_utilization": 0.85}),
              "gpu_memory_utilization") == "0.85")
    ck("an unstated gpu_memory_utilization is vLLM v0.31.0's default, 0.92",
       engine(sweep(stated={}), "gpu_memory_utilization") == "0.92")
    ck("a corpus with no stated_config also takes 0.92",
       engine(sweep(), "gpu_memory_utilization") == "0.92")
    ck("a stated block_size is written as stated",
       engine(sweep(stated={"block_size": 128}), "block_size") == "128")
    ck("an unstated block_size follows the rule (16 for a plain model)",
       engine(sweep(stated={}), "block_size") == "16")
    ck("an unstated block_size follows the rule (256 for DeepSeek-V4)",
       engine(sweep("deepseek-v4-pro", stated={}), "block_size") == "256")
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
    ck("an unstated max_model_len is still sized from the workload (32768 for 1k/1k)",
       engine(sweep(stated={}), "max_model_len") == "32768")
    ck("an unstated speculative config is left out",
       engine(sweep("deepseek-v4-pro", stated={}), "method") is None)

    # The relocation reworded comments but must emit valid Scenario + Deployment docs.
    text = emit(sweep(stated={}), {"1024:1024"}, {"1k1k"}, OPEN)
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
