#!/usr/bin/env python3
"""Make a small REAL direct-corpus trio from the kernel's committed scenarios, for budget-mode
CI (RFC D3). signedprobe's predicted side is a genuine blis replay against these real
deployments; the measured anchors are plausible stand-ins (the real dump supplies them in a
non-budget run). This proves the pipeline end to end without the 34 GB dump.

Reads only clean scenario fields; emits the three JSON files harness.LoadCorpus/LoadAbsolutes/
LoadEngineSettings consume. The emitted corpus carries only the measured-relative point fields;
the harness's other prediction-source relatives are absent (they default to 0.0 "not published"),
so nothing downstream carries a third-party baseline's field names.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re

# A spread of single-node vLLM scenarios across models, GPUs, topologies (no mtp — those are
# not_scored in v0.1.0; no multi-node — filtered at extraction).
PREFERRED = [
    "deepseek-v4-pro-b200-fp4-vllm-tp8-cfg1",
    "deepseek-v4-pro-h200-fp8-vllm-tp8-cfg1",
    "gpt-oss-120b-h200-fp4-vllm-tp8-cfg1",
    "gpt-oss-120b-h100-fp4-vllm-tp4-cfg1",
    "kimi-k2.5-b200-fp4-vllm-tp8-cfg1",
    "minimax-m2.5-h200-fp8-vllm-tp8-cfg1",
]
CONCURRENCIES = [1, 4, 16, 64]
# plausible measured µs curves (per concurrency), grown mildly per sweep so sweeps differ
BASE = {"tpot": {1: 7180, 4: 8820, 16: 13100, 64: 13200},
        "ttft": {1: 160000, 4: 204000, 16: 368000, 64: 821000}}


def read_scenario(path: str) -> dict:
    txt = open(path).read()
    def grab(pat, default=None):
        m = re.search(pat, txt, re.M)
        return m.group(1) if m else default
    tp = int(grab(r"^\s*tp:\s*(\d+)", "1"))
    pp = int(grab(r"^\s*pp:\s*(\d+)", "1"))
    dp = int(grab(r"^\s*dp:\s*(\d+)", "1"))
    return {
        "model": grab(r"^model:\s*(\S+)"),
        "gpu": grab(r"hardware:\s*(\S+)"),
        "engine_version": grab(r'engine_version:\s*"?([0-9.]+)"?', "0.29.0"),
        "precision": grab(r"quantization:\s*(\S+)", "fp8"),
        "tp": tp, "pp": pp, "dp": dp,
        "ep": "enable_expert_parallel: true" in txt,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", required=True, help="dir of committed direct *.yaml scenarios")
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--absolutes", required=True)
    ap.add_argument("--settings", required=True)
    args = ap.parse_args()

    available = {os.path.basename(p)[:-5]: p for p in glob.glob(os.path.join(args.scenarios, "*.yaml"))}
    picks = [n for n in PREFERRED if n in available]
    if not picks:
        # fall back to the first few single-node vllm cfg1 scenarios present
        picks = sorted(n for n in available if "vllm" in n and "mtp" not in n and n.endswith("cfg1"))[:6]
    if not picks:
        raise SystemExit(f"no usable scenarios in {args.scenarios}")

    corpus = {"source": "budget-fixture-direct", "measurement_source": "SemiAnalysis InferenceX", "sweeps": []}
    absset = {"source": "SemiAnalysis InferenceX", "source_url": "budget-fixture",
              "release_tag": "db-dump/budget", "metrics": "mean_tpot,mean_ttft",
              "validation": "budget-fixture", "anchors": []}
    setset = {"source": "SemiAnalysis InferenceX", "source_url": "budget-fixture",
              "release_tag": "db-dump/budget", "run_selection": "budget-fixture", "settings": []}

    for i, name in enumerate(picks):
        meta = read_scenario(available[name])
        scen = name + ".yaml"
        label = "1k1k"
        corpus["sweeps"].append({
            "scenario": scen, "model": meta["model"], "gpu": meta["gpu"],
            "workload": "1024:1024", "label": label, "framework": "vllm",
            "precision": meta["precision"], "serving": "aggregated", "spec_method": "none",
            "parallelism": {"tp_size": meta["tp"], "pp_size": meta["pp"],
                            "attention_dp_size": meta["dp"],
                            "moe_ep_size": (meta["tp"] if meta["ep"] else 1),
                            "moe_tp_size": meta["tp"]},
            # Only the measured relatives are emitted; the harness's other prediction-source
            # relatives default to 0.0 ("not published") when absent, so no third-party
            # baseline's field names appear in anything this repo writes.
            "points": [{"concurrency": c,
                        "measured_tpot_relative": round(BASE["tpot"][c] / BASE["tpot"][1], 6),
                        "measured_ttft_relative": round(BASE["ttft"][c] / BASE["ttft"][1], 6),
                        "status": "success"} for c in CONCURRENCIES],
        })
        f = 1.0 + 0.05 * i
        absset["anchors"].append({
            "scenario": scen, "label": label, "framework": "vllm", "gpu": meta["gpu"],
            "absolute_tpot_us": {str(c): round(BASE["tpot"][c] * f, 1) for c in CONCURRENCIES},
            "absolute_ttft_us": {str(c): round(BASE["ttft"][c] * f, 1) for c in CONCURRENCIES},
            "source_run_date": "budget", "source_config_id": 1000 + i, "relative_agreement": 0.0,
        })
        bycon = {str(c): {"passed": {"max_num_seqs": 256, "max_num_batched_tokens": 8192,
                                     "max_model_len": 32768, "block_size": 256,
                                     "enable_prefix_caching": False, "gpu_memory_utilization": 0.9,
                                     "enable_expert_parallel": meta["ep"]},
                          "resolved": {"resolved_gpu_kv_tokens": 500000,
                                       "resolved_max_concurrency": 100.0,
                                       "engine_version": meta["engine_version"]}}
                 for c in CONCURRENCIES}
        setset["settings"].append({"scenario": scen, "label": label, "framework": "vllm",
                                   "gpu": meta["gpu"], "source_run_date": "budget",
                                   "source_config_id": 1000 + i, "by_concurrency": bycon})

    json.dump(corpus, open(args.corpus, "w"), indent=2)
    json.dump(absset, open(args.absolutes, "w"), indent=2)
    json.dump(setset, open(args.settings, "w"), indent=2)
    print(f"[make_budget_fixture] {len(picks)} sweeps x {len(CONCURRENCIES)} points: {picks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
