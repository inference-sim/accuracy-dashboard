#!/usr/bin/env python3
"""Write the contract fixture: two runs (run-a, run-b) over the same frozen pull.

The values are illustrative, shaped like real InferenceX rows from Discussion #28's evidence
(builds, distances, settings sources, reason codes). They're not real measurements. run-b is
the same pull scored by an older BLIS release, with different predictions, and one point that
BLIS refused, so Compare sees a shrunk intersection.

Usage: build_fixture.py [OUT_DIR]   (default: this directory, i.e. regenerate the committed fixture)
test_contract.py generates into a temporary directory and checks the committed files match it.
"""
from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
from contract import (  # noqa: E402
    FACETS_JSON, FIDELITY_JSONL, NOT_SCORED_JSONL, POINTS_CSV, POINTS_HEADER, PROVENANCE_JSON,
    canonical_dumps, point_id, points_sort_key, ratio_str, recipe_key,
)

VLLM_REF = "v0.31.0"
POLICY_SHA = "1" * 64
CORPUS = {"dataset": "semianalysisai/cc-traces-weka-062126",
          "revision": "23f152f6f0f9399a85901b89a6458def0ef16729",
          "sha256": "29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276"}

# Builds, as #28's evidence resolved them.
B_CD10 = {"image": "vllm/vllm-openai:nightly-cd10ed6f9f6b37a8ace9cf380007e66fe12ec0c3",
          "commit": "cd10ed6f9f6b37a8ace9cf380007e66fe12ec0c3", "source": "server_log_banner",
          "ref": VLLM_REF, "distance": -738, "match": "exact"}
B_AC91 = {"image": "vllm/vllm-openai:nightly-dev-x86_64-cu130-ac9126e58aa7",
          "commit": "ac9126e58aa7bbab1856ba6593ba4d5003fea516", "source": "label_by_tag",
          "ref": VLLM_REF, "distance": 207, "match": "exact"}
B_7C5D = {"image": "vllm/vllm-openai:nightly-7c5dc571cbd1064ecc8a9b1045637ff647aa22cb",
          "commit": "7c5dc571cbd1064ecc8a9b1045637ff647aa22cb", "source": "image_label",
          "ref": VLLM_REF, "distance": -1435, "match": "exact"}
# A build BLIS doesn't model is still scored, as estimated: here a model-specific image built
# from a vLLM fork (its commit is off vLLM's mainline).
B_FORK = {"image": "vllm/vllm-openai:vllm-minimax-m3-perf-x86_64-13.0.1-8b00f41", "commit": None,
          "source": None, "ref": VLLM_REF, "distance": None, "match": "estimated", "why": "custom_build"}

REPLAY = {"client": "aiperf", "client_version": "0.12.0", "scenario": "inferencex-agentx-mvp",
          "replayed_as": "inferencex-agentx-mvp", "duration_s": 3600,
          "trajectory_start": {"min_ratio": 0.25, "max_ratio": 0.75},
          "corpus": "semianalysis_cc_traces_weka_062126", "corpus_sha256": CORPUS["sha256"], "seed": 42}


def arg(name, measured, blis, match, source=None, **extra):
    a = {"arg": name, "measured": measured, "blis": blis, "match": match}
    if source:
        a["source"] = source
    a.update(extra)
    return a


def common_args(seqs, seqs_src, block, gmu, gmu_src):
    return [
        arg("block_size", block, block, "exact", "engine_line"),
        arg("gpu_memory_utilization", gmu, gmu, "exact", gmu_src),
        arg("max_num_seqs", seqs, seqs, "exact", seqs_src),
    ]


# Approximations are fixed text per arg (the policy table's).
APPROX = {
    "attention_config.indexer_kv_dtype": {
        "note": "No Deployment key states the indexer cache dtype, so BLIS prices the default FP8 "
                "indexer record (132 B/entry) where the run used MXFP4 (68 B)."},
    "attention_config.indexer_sparse_logits": {
        "note": "vLLM's sparse-logits indexer needs the MXFP4 indexer cache; with the FP8 record BLIS "
                "prices, it's the dense-logits indexer."},
}
TIER_BY_STATUS = {"exact": "MEASURED-OR-RESOLVED", "approximate": "ALL (approximate)"}


# Each scored point: identity, facets, CSV measurements (ms), predictions per run (ms), fidelity.
POINTS = [
    # DeepSeek-V4.1-Flash h200 TP4, agentic, one curve: conc 1/2/4 (shape needs >= 3).
    *[{
        "row": {"model": "dsv41flash", "hardware": "h200", "precision": "fp4", "framework": "vllm",
                "benchmark_type": "agentic_traces", "recipe_fingerprint": fp, "conc": c,
                "date": "2026-09-21", "curve_workflow_run_id": "2410"},
        "facets": {"scenario": "deepseek-v4.1-flash-h200-fp4-vllm-tp4-dspark5-agentx.yaml",
                   "label": "agentx", "workload": "agentx", "model": "deepseek-v4.1-flash", "gpu": "h200",
                   "spec_method": "mtp", "parallelism": {"tp": 4, "pp": 1, "dp": 1, "ep": 1},
                   "image": B_CD10["image"], "vllm_version": "0.29.1rc1.dev128+gcd10ed6f9"},
        "meas": (ttft, tpot), "pred": {"a": pa, "b": pb},
        "fidelity": {"status": "exact", "build": B_CD10,
                     "args": common_args(seqs, "args", 64, "0.92", "engine_line"),
                     "resolved": [{"quantity": "kv_cache_tokens_per_replica", "measured": kv,
                                   "blis": kvb, "delta": kvb - kv,
                                   "ratio": ratio_str(kvb, kv),
                                   "match": "differs"}],
                     "replay": {**REPLAY, "concurrency": c}, "blis_kernel_provenance": None},
    } for fp, c, ttft, tpot, pa, pb, seqs, kv, kvb in [
        ("a1" * 32, 1, 980.0, 8.10, (1050.0, 7.20), (1120.0, 7.05), 16, 20039988, 21002240),
        ("a2" * 32, 2, 1210.0, 8.65, (1260.0, 7.70), (1380.0, 7.55), 16, 20039988, 21002240),
        ("a4" * 32, 4, 1650.0, 9.40, (1590.0, 8.55), (1830.0, 8.30), 16, 20039988, 21002240),
    ]],
    # DeepSeek-V4.1-Flash h200 TP8 c1: max_num_seqs not recorded -> BLIS default.
    {"row": {"model": "dsv41flash", "hardware": "h200", "precision": "fp4", "framework": "vllm",
             "benchmark_type": "agentic_traces", "recipe_fingerprint": "b1" * 32, "conc": 1,
             "date": "2026-09-21", "curve_workflow_run_id": "2410"},
     "facets": {"scenario": "deepseek-v4.1-flash-h200-fp4-vllm-tp8-dspark5-agentx.yaml",
                "label": "agentx", "workload": "agentx", "model": "deepseek-v4.1-flash", "gpu": "h200",
                "spec_method": "mtp", "parallelism": {"tp": 8, "pp": 1, "dp": 1, "ep": 1},
                "image": B_CD10["image"], "vllm_version": "0.29.1rc1.dev128+gcd10ed6f9"},
     "meas": (760.0, 6.90), "pred": {"a": (720.0, 6.10), "b": (790.0, 5.95)},
     "fidelity": {"status": "exact", "build": B_CD10,
                  "args": [arg("block_size", 64, 64, "exact", "engine_line"),
                           arg("gpu_memory_utilization", "0.92", "0.92", "exact", "engine_line"),
                           arg("max_num_seqs", None, 1024, "blis_default", "blis_default",
                               rule="ResolveVLLMBatchDefaults: >=70 GiB, not A100 (vLLM v0.31.0 OpenAI-server tier)")],
                  "resolved": [{"quantity": "kv_cache_tokens_per_replica", "measured": 31006342,
                                "blis": None, "match": "unreadable"}],
                  "replay": {**REPLAY, "concurrency": 1}, "blis_kernel_provenance": None}},
    # DeepSeek-V4.1-Flash b200 DEP2 c8: MegaMoE mapped, router inert, and the MXFP4 indexer
    # cache approximated (BLIS prices the default FP8 record), so the point is approximate.
    {"row": {"model": "dsv41flash", "hardware": "b200", "precision": "fp4", "framework": "vllm",
             "benchmark_type": "agentic_traces", "recipe_fingerprint": "c8" * 32, "conc": 8,
             "date": "2026-10-03", "curve_workflow_run_id": "2560"},
     "facets": {"scenario": "deepseek-v4.1-flash-b200-fp4-vllm-tp1-ep2-dp2-dspark5-agentx.yaml",
                "label": "agentx", "workload": "agentx", "model": "deepseek-v4.1-flash", "gpu": "b200",
                "spec_method": "mtp", "parallelism": {"tp": 1, "pp": 1, "dp": 2, "ep": 2},
                "image": B_AC91["image"], "vllm_version": "0.30.1rc1.dev493+gac9126e58"},
     "meas": (1180.0, 5.10), "pred": {"a": (1043.9, 4.447), "b": (1210.0, 4.30)},
     "fidelity": {"status": "approximate", "build": B_AC91,
                  "args": [arg("attention_config.indexer_kv_dtype", "mxfp4", "fp8", "approximated", "args",
                               **APPROX["attention_config.indexer_kv_dtype"]),
                           arg("attention_config.indexer_sparse_logits", True, False, "approximated", "args",
                               **APPROX["attention_config.indexer_sparse_logits"]),
                           arg("block_size", 128, 128, "exact", "engine_line"),
                           arg("data_parallel_size", 2, 2, "exact", "args"),
                           arg("enable_expert_parallel", True, True, "exact", "args"),
                           arg("frontend.router", "vllm-router/consistent_hash", None, "inert", "api_row"),
                           arg("gpu_memory_utilization", "0.97", "0.97", "exact", "args"),
                           arg("kernel_config.moe_backend", "deep_gemm_mega_moe", "deep_gemm_mega_moe",
                               "mapped", "args", blis_field="engine.moe_backend"),
                           arg("max_num_seqs", 16, 16, "exact", "args")],
                  "resolved": [{"quantity": "kv_cache_tokens_per_replica", "measured": 9787503,
                                "occurrences": 2, "blis": 9787503, "delta": 0, "ratio": ratio_str(9787503, 9787503),
                                "match": "exact"}],
                  "replay": {**REPLAY, "concurrency": 8, "client_version": "1.0.11", "scenario": "agentx"},
                  "blis_kernel_provenance": {"method_counts": {"assumed": 50, "measured": 99}}}},
    # MiniMax-M3 h200 TP8 c4 on a custom image: every setting matched, but the build isn't the
    # one BLIS models, so the point is estimated.
    {"row": {"model": "minimaxm3", "hardware": "h200", "precision": "fp8", "framework": "vllm",
             "benchmark_type": "agentic_traces", "recipe_fingerprint": "e4" * 32, "conc": 4,
             "date": "2026-10-11", "curve_workflow_run_id": "2610"},
     "facets": {"scenario": "minimax-m3-h200-fp8-vllm-tp8-agentx.yaml", "label": "agentx", "workload": "agentx",
                "model": "minimax-m3", "gpu": "h200", "spec_method": "none",
                "parallelism": {"tp": 8, "pp": 1, "dp": 1, "ep": 1},
                "image": B_FORK["image"], "vllm_version": "0.30.0rc2.dev44+g8b00f4123"},
     "meas": (1630.0, 11.80), "pred": {"a": (1490.0, 10.90), "b": (1720.0, 10.40)},
     "fidelity": {"status": "approximate", "build": B_FORK,
                  "args": [arg("block_size", 16, 16, "exact", "engine_line"),
                           arg("gpu_memory_utilization", "0.9", "0.9", "exact", "engine_line"),
                           arg("max_num_seqs", 64, 64, "exact", "args")],
                  "resolved": [], "replay": {**REPLAY, "concurrency": 4}, "blis_kernel_provenance": None}},
    # DeepSeek-V4-Pro b200 single-turn 8k1k TP8: one curve, conc 1/4/16.
    *[{
        "row": {"model": "dsv4", "hardware": "b200", "precision": "fp4", "framework": "vllm",
                "benchmark_type": "single_turn", "recipe_fingerprint": fp, "conc": c,
                "date": "2026-09-03", "curve_workflow_run_id": "2301"},
        "facets": {"scenario": "deepseek-v4-pro-b200-fp4-vllm-tp8.yaml", "label": "8k1k",
                   "workload": "8192:1024", "model": "deepseek-v4-pro", "gpu": "b200", "spec_method": "none",
                   "parallelism": {"tp": 8, "pp": 1, "dp": 1, "ep": 1},
                   "image": B_7C5D["image"], "vllm_version": "0.28.1rc1.dev199+g7c5dc571c"},
        "meas": (ttft, tpot), "pred": {"a": pa, "b": pb},
        "fidelity": {"status": "exact", "build": B_7C5D,
                     "args": [arg("block_size", 256, 256, "exact", "args"),
                              arg("enable_prefix_caching", False, False, "exact", "args"),
                              arg("max_model_len", 9472, 9472, "exact", "args"),
                              arg("max_num_batched_tokens", 8192, 8192, "exact", "args")],
                     "resolved": [], "blis_kernel_provenance": None},
    } for fp, c, ttft, tpot, pa, pb in [
        ("d1" * 32, 1, 410.0, 21.5, (380.0, 20.1), (430.0, 19.4)),
        ("d4" * 32, 4, 620.0, 23.8, (590.0, 22.9), (700.0, 21.7)),
        ("df" * 32, 16, 1340.0, 29.6, (1450.0, 30.8), (1610.0, 28.9)),
    ]],
]

NOT_SCORED = [
    ({"model": "minimaxm3", "hardware": "b200", "precision": "fp4", "framework": "vllm",
      "benchmark_type": "agentic_traces", "recipe_fingerprint": "e1" * 32, "conc": 1, "date": "2026-09-30"},
     "vllm/vllm-openai:nightly-af7f9488c2210d67e1033ecdc845b087ee7fe92b", (2310.0, 9.8),
     ["drafter_not_in_catalog:eagle3"]),
    ({"model": "dsv41flash", "hardware": "b300", "precision": "fp4", "framework": "vllm",
      "benchmark_type": "agentic_traces", "recipe_fingerprint": "f8" * 32, "conc": 8, "date": "2026-10-20"},
     "vllm/vllm-openai:cu134-nightly-x86_64-dev-20261019-mk", (1490.0, 4.9),
     ["setting_not_modelled:prefill_schedule_interval"]),
    ({"model": "dsv4", "hardware": "b200", "precision": "fp4", "framework": "vllm",
      "benchmark_type": "agentic_traces", "recipe_fingerprint": "", "row_id": "445802", "conc": 1,
      "date": "2026-10-21"},
     "vllm/vllm-openai:nightly-dev-x86_64-cu13.0.1-20ebb28", (880.0, 11.2),
     ["model_not_in_catalog"]),
    ({"model": "minimaxm3", "hardware": "h100", "precision": "fp8", "framework": "vllm",
      "benchmark_type": "agentic_traces", "recipe_fingerprint": "e6" * 32, "conc": 6, "date": "2026-09-27"},
     "vllm/vllm-openai:nightly-ddd6fbca148a867aad1fcab7ec72f582b9977db4", (2050.0, 12.4),
     ["drafter_not_in_catalog:eagle3", "setting_not_modelled:kv_transfer_config.kv_connector"]),
]

# Notes are fixed text per reason (the policy table's), keyed by the full reason.
NOTES = {
    "setting_not_modelled:prefill_schedule_interval": {
        "text": "No Deployment key states vLLM's prefill_schedule_interval, which holds prefills back "
                "for decode-only steps; BLIS schedules a prefill every step."},
}

RUNS = {
    "a": {"blis": {"release": "v0.12.0", "commit_sha": "f199223d701d96dddeb1c314509bed003515b599",
                   "catalog": "0.3.0", "registry": "v0.2.0", "extractor_version": "blis-latency-kernel@v0.3.0"},
          "refused": {}},
    "b": {"blis": {"release": "v0.11.0", "commit_sha": "8e344596c35272e6f505df65c0935aeb5e0000ec",
                   "catalog": "0.3.0", "registry": "v0.2.0", "extractor_version": "blis-latency-kernel@v0.3.0"},
          # BLIS v0.11.0 refuses this one point, so it isn't shared with run-a.
          "refused": {"a4" * 32: "blis_refused:max_cudagraph_capture_size"}},
}


def identity(row: dict) -> dict:
    return {"model": row["model"], "hardware": row["hardware"], "precision": row["precision"],
            "framework": row["framework"], "benchmark_type": row["benchmark_type"],
            "recipe": recipe_key(row.get("recipe_fingerprint"), row.get("row_id")),
            "conc": row["conc"], "measured_date": row["date"]}


def write_run(name: str, run: dict, base: Path) -> Path:
    out = base / f"run-{name}"
    out.mkdir(parents=True, exist_ok=True)
    rows, fidelity, facets, not_scored = [], [], {}, []
    for p in POINTS:
        ident = identity(p["row"])
        pid = point_id(ident)
        refused = run["refused"].get(p["row"]["recipe_fingerprint"])
        if refused:
            not_scored.append({"point_id": pid, "identity": ident, "measured_date": ident["measured_date"],
                               "model": ident["model"], "hardware": ident["hardware"],
                               "precision": ident["precision"], "framework": ident["framework"],
                               "benchmark_type": ident["benchmark_type"], "conc": ident["conc"],
                               "image": p["facets"]["image"],
                               "measured": {"ttft_ms": p["meas"][0], "tpot_ms": p["meas"][1]},
                               "reasons": [refused]})
            continue
        f = p["facets"]
        sweep = f"{p['row']['curve_workflow_run_id']}|{f['scenario']}|{f['label']}"
        facets[pid] = {"identity": ident, "sweep_id": sweep, "scenario": f["scenario"], "label": f["label"],
                       "workload": f["workload"], "model": f["model"], "gpu": f["gpu"],
                       "precision": ident["precision"], "framework": "vllm", "serving": "aggregated",
                       "spec_method": f["spec_method"], "parallelism": f["parallelism"],
                       "image": f["image"], "vllm_version": f["vllm_version"]}
        pttft, ptpot = p["pred"][name]
        rows.append([f["scenario"], f["model"], f["gpu"], f["label"], ident["conc"],
                     round(p["meas"][1] * 1000, 3), round(ptpot * 1000, 3),
                     round(p["meas"][0] * 1000, 3), round(pttft * 1000, 3),
                     TIER_BY_STATUS[p["fidelity"]["status"]], pid, ident["measured_date"]])
        fid = {k: v for k, v in p["fidelity"].items() if v is not None or k == "blis_kernel_provenance"}
        fid["args"] = sorted(fid["args"], key=lambda a: a["arg"])
        fid["resolved"] = sorted(fid["resolved"], key=lambda r: r["quantity"])
        fidelity.append({"point_id": pid, **fid})
    for row, image, meas, reasons in NOT_SCORED:
        ident = identity(row)
        rec = {"point_id": point_id(ident), "identity": ident,
               "measured_date": ident["measured_date"], "model": ident["model"],
               "hardware": ident["hardware"], "precision": ident["precision"],
               "framework": ident["framework"], "benchmark_type": ident["benchmark_type"],
               "conc": ident["conc"], "image": image,
               "measured": {"ttft_ms": meas[0], "tpot_ms": meas[1]},
               "reasons": sorted(set(reasons))}
        notes = [{"reason": r, **NOTES[r]} for r in rec["reasons"] if r in NOTES]
        if notes:
            rec["notes"] = notes
        not_scored.append(rec)

    rows.sort(key=lambda r: points_sort_key(dict(zip(POINTS_HEADER, map(str, r)))))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(POINTS_HEADER)
    w.writerows(rows)
    (out / POINTS_CSV).write_text(buf.getvalue())
    fidelity.sort(key=lambda r: r["point_id"])
    (out / FIDELITY_JSONL).write_text("".join(canonical_dumps(r) + "\n" for r in fidelity))
    (out / FACETS_JSON).write_text(canonical_dumps(facets) + "\n")
    not_scored.sort(key=lambda r: r["point_id"])
    (out / NOT_SCORED_JSONL).write_text("".join(canonical_dumps(r) + "\n" for r in not_scored))
    prov = {"ingest": "api", "blis": run["blis"], "vllm_ref": VLLM_REF, "vllm_max_distance": 2000,
            "policy_sha256": POLICY_SHA, "pulled_at": "2026-10-23T00:00:00Z", "corpus": CORPUS,
            "pull_manifest_sha256": "2" * 64}
    (out / PROVENANCE_JSON).write_text(canonical_dumps(prov) + "\n")
    return out


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    base = Path(args[0]) if args else HERE
    for name, run in RUNS.items():
        print(f"wrote {write_run(name, run, base)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
