#!/usr/bin/env python3
"""Write the contract fixture: two runs (run-a, run-b) over the same frozen pull.

The values are illustrative, shaped like real InferenceX rows from Discussion #28's evidence
(builds, distances, settings sources, reasons). They're not real measurements. run-b is the same
pull scored by an older BLIS release, with different predictions, and one point that BLIS
refused, listed as failed, so Compare sees a shrunk intersection.

Each point is graded by grade.grade from its build and the substitutions its settings named
(design §11.3), with the engine release both runs score on, ENGINE: a nightly or custom build is
G4; an official image of ENGINE with a substitution is G2, with none G1; another release is G4,
since no engine publishes its ported-function list yet.

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
    FACETS_JSON, FAILED_JSONL, FIDELITY_JSONL, NOT_SCORED_JSONL, POINTS_CSV, POINTS_HEADER, PROVENANCE_JSON,
    canonical_dumps, point_id, points_sort_key, ratio_str, run_dates, unit_identity,
)
import grade as gr  # noqa: E402
import score as sc  # noqa: E402

ENGINE = "0.31.0"

VLLM_REF = "v0.31.0"
FIELDS_SHA = "1" * 64
CORPUS = {"dataset": "semianalysisai/cc-traces-weka-062126",
          "revision": "23f152f6f0f9399a85901b89a6458def0ef16729",
          "sha256": "29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276"}
# The two AgentX corpora, as the catalog replay workloads pin them (provenance.json's corpora).
CORPORA = [{"alias": "semianalysis_cc_traces_weka_062126", "workload": "agentx-mvp-uncapped", **CORPUS},
           {"alias": "semianalysis_cc_traces_weka_062126_256k", "workload": "agentx-mvp",
            "dataset": "semianalysisai/cc-traces-weka-062126-256k",
            "revision": "8fecd2fc56694469f758f0afbbb6335ad3043740",
            "sha256": "e39cd2ff3eba21d4a3664be51da743ac3d2149a1933898cafc7bfeac8147eeef"}]

# Builds, as #28's evidence resolved them: two nightly images.
B_AC91 = {"image": "vllm/vllm-openai:nightly-dev-x86_64-cu130-ac9126e58aa7",
          "commit": "ac9126e58aa7bbab1856ba6593ba4d5003fea516", "source": "label_by_tag",
          "ref": VLLM_REF, "distance": 207, "match": "exact"}
# Official release images: the release the simulator runs, and an older one.
B_REL = {"image": "vllm/vllm-openai:v0.31.0", "commit": "3c0a1b2d4e5f60718293a4b5c6d7e8f901234567",
         "source": "release_tag", "ref": VLLM_REF, "distance": 0, "match": "exact"}
B_OLD = {"image": "vllm/vllm-openai:v0.25.0", "commit": "799c3afa5d5b17b676d04e0b58a5628943bb4003",
         "source": "label_by_tag", "ref": VLLM_REF, "distance": -4121, "match": "estimated", "why": "outside_distance"}
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


# An estimate is the field list's estimation rule, named on the point (fields.decide).
LEFT_UNSET = "left unset; the engine resolves the upstream default"
APPROX = {
    "attention_config.indexer_kv_dtype": {"note": LEFT_UNSET},
    "attention_config.indexer_sparse_logits": {"note": LEFT_UNSET},
}
NOT_RECORDED = "not recorded; left unset, so the engine resolves the upstream default"
SEND_GAP = {"kind": "client_difference", "subject": "send_gap",
            "detail": "the simulator admits the next request at the step that emitted the previous request's last "
                      "token; the client sends it after the response stream closes, an interval not modelled"}
REQUESTS = {"client": "inferencex benchmark_serving.py", "start": "cold", "copies": 0, "count": 10,
            "differences": [SEND_GAP]}


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
                   "image": B_REL["image"], "vllm_version": "0.31.0"},
        "meas": (ttft, tpot), "pred": {"a": pa, "b": pb},
        "fidelity": {"build": B_REL,
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
    # DeepSeek-V4.1-Flash h200 TP8 c1 on an older release: max_num_seqs not recorded, so BLIS's
    # default is an estimate; the release is not the one the simulator runs, so the point is G4.
    {"row": {"model": "dsv41flash", "hardware": "h200", "precision": "fp4", "framework": "vllm",
             "benchmark_type": "agentic_traces", "recipe_fingerprint": "b1" * 32, "conc": 1,
             "date": "2026-09-21", "curve_workflow_run_id": "2410"},
     "facets": {"scenario": "deepseek-v4.1-flash-h200-fp4-vllm-tp8-dspark5-agentx.yaml",
                "label": "agentx", "workload": "agentx", "model": "deepseek-v4.1-flash", "gpu": "h200",
                "spec_method": "mtp", "parallelism": {"tp": 8, "pp": 1, "dp": 1, "ep": 1},
                "image": B_OLD["image"], "vllm_version": "0.25.0"},
     "meas": (760.0, 6.90), "pred": {"a": (720.0, 6.10), "b": (790.0, 5.95)},
     "fidelity": {"build": B_OLD,
                  "args": [arg("block_size", 64, 64, "exact", "engine_line"),
                           arg("gpu_memory_utilization", "0.92", "0.92", "exact", "engine_line")],
                  "_subs": [{"kind": "estimated", "subject": "max_num_seqs", "detail": NOT_RECORDED}],
                  "resolved": [{"quantity": "kv_cache_tokens_per_replica", "measured": 31006342,
                                "blis": None, "match": "unreadable"}],
                  "replay": {**REPLAY, "concurrency": 1}, "blis_kernel_provenance": None}},
    # DeepSeek-V4.1-Flash b200 DEP2 c8 on a nightly build: MegaMoE copied into the engine block's
    # moe_backend, and the MXFP4 indexer cache left unset by the field list's estimation rule.
    {"row": {"model": "dsv41flash", "hardware": "b200", "precision": "fp4", "framework": "vllm",
             "benchmark_type": "agentic_traces", "recipe_fingerprint": "c8" * 32, "conc": 8,
             "date": "2026-10-03", "curve_workflow_run_id": "2560"},
     "facets": {"scenario": "deepseek-v4.1-flash-b200-fp4-vllm-tp1-ep2-dp2-dspark5-agentx.yaml",
                "label": "agentx", "workload": "agentx", "model": "deepseek-v4.1-flash", "gpu": "b200",
                "spec_method": "mtp", "parallelism": {"tp": 1, "pp": 1, "dp": 2, "ep": 2},
                "image": B_AC91["image"], "vllm_version": "0.30.1rc1.dev493+gac9126e58"},
     "meas": (1180.0, 5.10), "pred": {"a": (1043.9, 4.447), "b": (1210.0, 4.30)},
     "fidelity": {"build": B_AC91,
                  "_subs": [{"kind": "estimated", "subject": k, "detail": v["note"]} for k, v in APPROX.items()],
                  "args": [arg("attention_config.indexer_kv_dtype", "mxfp4", None, "approximated", "args",
                               **APPROX["attention_config.indexer_kv_dtype"]),
                           arg("attention_config.indexer_sparse_logits", True, None, "approximated", "args",
                               **APPROX["attention_config.indexer_sparse_logits"]),
                           arg("block_size", 128, 128, "exact", "engine_line"),
                           arg("data_parallel_size", 2, 2, "exact", "args"),
                           arg("enable_expert_parallel", True, True, "exact", "args"),
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
     "fidelity": {"build": B_FORK,
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
                   "image": B_REL["image"], "vllm_version": "0.31.0"},
        "meas": (ttft, tpot), "pred": {"a": pa, "b": pb},
        "fidelity": {"build": B_REL, "requests": REQUESTS,
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

# Each G5 point, with every G5 reason found (design §11.4).
NOT_SCORED = [
    ({"model": "minimaxm3", "hardware": "b200", "precision": "fp4", "framework": "vllm",
      "benchmark_type": "agentic_traces", "recipe_fingerprint": "e1" * 32, "conc": 1, "date": "2026-09-30"},
     "vllm/vllm-openai:nightly-af7f9488c2210d67e1033ecdc845b087ee7fe92b", (2310.0, 9.8),
     [{"code": "not_in_catalog", "subject": "eagle3"}]),
    ({"model": "dsv41flash", "hardware": "b300", "precision": "fp4", "framework": "vllm",
      "benchmark_type": "agentic_traces", "recipe_fingerprint": "f8" * 32, "conc": 8, "date": "2026-10-20"},
     "vllm/vllm-openai:cu134-nightly-x86_64-dev-20261019-mk", (1490.0, 4.9),
     [{"code": "field_not_modelled", "subject": "prefill_schedule_interval"}]),
    ({"model": "dsv4", "hardware": "b200", "precision": "fp4", "framework": "vllm",
      "benchmark_type": "agentic_traces", "recipe_fingerprint": "", "row_id": "445802", "conc": 1,
      "date": "2026-10-21"},
     "vllm/vllm-openai:nightly-dev-x86_64-cu13.0.1-20ebb28", (880.0, 11.2),
     [{"code": "not_in_catalog"}]),
    ({"model": "minimaxm3", "hardware": "h100", "precision": "fp8", "framework": "vllm",
      "benchmark_type": "agentic_traces", "recipe_fingerprint": "e6" * 32, "conc": 6, "date": "2026-09-27"},
     "vllm/vllm-openai:nightly-ddd6fbca148a867aad1fcab7ec72f582b9977db4", (2050.0, 12.4),
     [{"code": "field_not_modelled", "subject": "kv_transfer_config.kv_connector"},
      {"code": "not_in_catalog", "subject": "eagle3"}]),
    ({"model": "dsv4", "hardware": "h200", "precision": "fp8", "framework": "vllm",
      "benchmark_type": "single_turn", "recipe_fingerprint": "a9" * 32, "conc": 16, "date": "2026-10-02"},
     "vllm/vllm-openai:v0.31.0", (520.0, 14.1),
     [{"code": "router_unsupported", "subject": "vllm-router"}]),
]

RUNS = {
    "a": {"blis": {"release": "v0.12.0", "commit_sha": "f199223d701d96dddeb1c314509bed003515b599",
                   "catalog": "0.3.0", "registry": "v0.2.0", "extractor_version": "blis-latency-kernel@v0.3.0"},
          "refused": {}},
    "b": {"blis": {"release": "v0.11.0", "commit_sha": "8e344596c35272e6f505df65c0935aeb5e0000ec",
                   "catalog": "0.3.0", "registry": "v0.2.0", "extractor_version": "blis-latency-kernel@v0.3.0"},
          # BLIS v0.11.0 times out on this one point: a runner limit, listed as failed and never
          # graded, so the point isn't shared with run-a and the run still publishes.
          "refused": {"a4" * 32: "blis_refused:timeout"}},
}


# The serving configuration every fixture row shares, in InferenceX's own names; a row's
# run_url is built from its curve run id, and a row with neither has no benchmark run.
CONFIG = {"isl": None, "osl": None, "offload_mode": "off", "spec_method": "none", "disagg": False,
          "is_multinode": False, "prefill_tp": 1, "prefill_ep": 1, "prefill_dp_attention": False,
          "prefill_num_workers": 0, "num_prefill_gpu": 1, "decode_tp": 1, "decode_ep": 1,
          "decode_dp_attention": False, "decode_num_workers": 0, "num_decode_gpu": 1}


def identity(row: dict) -> dict:
    """The row's ledger identity (design §10.2), from contract.unit_identity."""
    run = row.get("curve_workflow_run_id")
    full = {**CONFIG, "image": row.get("image"), **row, "id": row.get("row_id", "0"),
            "run_url": f"https://github.com/SemiAnalysisAI/InferenceX/actions/runs/{run}/attempts/1" if run else None}
    return unit_identity(full, run_dates([full]))


def _common(ident: dict, image: str, meas, run_release, sim: dict) -> dict:
    return {"simulator": sim, "point_id": point_id(ident), "identity": ident, "measured_date": ident["measured_date"],
            "model": ident["model"], "hardware": ident["hardware"], "precision": ident["precision"],
            "framework": ident["framework"], "benchmark_type": ident["benchmark_type"], "conc": ident["conc"],
            "image": image, "run_release": run_release, "measured": {"ttft_ms": meas[0], "tpot_ms": meas[1]}}


def write_run(name: str, run: dict, base: Path) -> Path:
    out = base / f"run-{name}"
    out.mkdir(parents=True, exist_ok=True)
    rows, fidelity, facets, not_scored, failed = [], [], {}, [], []
    sim = {"build": run["blis"]["release"], "engine": {"kind": "vllm", "version": ENGINE},
           "harness_commit": "0123456789abcdef0123456789abcdef01234567"}
    for p in POINTS:
        ident = identity(p["row"])
        pid = point_id(ident)
        f = p["facets"]
        rel = gr.run_release(p["fidelity"]["build"], f["vllm_version"])
        refused = run["refused"].get(p["row"]["recipe_fingerprint"])
        if refused:
            failed.append({**_common(ident, f["image"], p["meas"], rel.version, sim), "faults": [refused]})
            continue
        sweep = f"{p['row']['curve_workflow_run_id']}|{f['scenario']}|{f['label']}"
        facets[pid] = {"identity": ident, "sweep_id": sweep, "scenario": f["scenario"], "label": f["label"],
                       "workload": f["workload"], "model": f["model"], "gpu": f["gpu"],
                       "precision": ident["precision"], "framework": "vllm", "serving": "aggregated",
                       "spec_method": f["spec_method"], "parallelism": f["parallelism"],
                       "image": f["image"], "vllm_version": f["vllm_version"]}
        fid = {k: v for k, v in p["fidelity"].items()
               if (v is not None or k == "blis_kernel_provenance") and k != "_subs"}
        fid["args"] = sorted(fid["args"], key=lambda a: a["arg"])
        fid["resolved"] = sorted(fid["resolved"], key=lambda r: r["quantity"])
        g = gr.grade(engine_version=ENGINE, release=rel,
                     substitutions=sc.substitutions(p["fidelity"].get("_subs", []), fid))
        fid.update(grade=g.grade, substitutions=g.substitutions, run_release=rel.version, simulator=sim)
        pttft, ptpot = p["pred"][name]
        rows.append([f["scenario"], f["model"], f["gpu"], f["label"], ident["conc"],
                     round(p["meas"][1] * 1000, 3), round(ptpot * 1000, 3),
                     round(p["meas"][0] * 1000, 3), round(pttft * 1000, 3),
                     g.grade, pid, ident["measured_date"]])
        fidelity.append({"point_id": pid, **fid})
    for row, image, meas, reasons in NOT_SCORED:
        ident = identity(row)
        rel = gr.run_release({"image": image}, None)
        g = gr.grade(engine_version=ENGINE, release=rel, substitutions=[], g5=reasons)
        not_scored.append({**_common(ident, image, meas, rel.version, sim), "grade": g.grade, "g5_reason": g.g5,
                           "g5_reasons": sorted(reasons, key=lambda r: (r["code"], r.get("subject", "")))})

    rows.sort(key=lambda r: points_sort_key(dict(zip(POINTS_HEADER, map(str, r)))))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(POINTS_HEADER)
    w.writerows(rows)
    (out / POINTS_CSV).write_text(buf.getvalue())
    fidelity.sort(key=lambda r: r["point_id"])
    (out / FIDELITY_JSONL).write_text("".join(canonical_dumps(r) + "\n" for r in fidelity))
    (out / FACETS_JSON).write_text(canonical_dumps(facets) + "\n")
    (out / "pointrecords.jsonl").write_text("")      # the fixture's Results carry no data block
    for fname, recs in ((NOT_SCORED_JSONL, not_scored), (FAILED_JSONL, failed)):
        recs.sort(key=lambda r: r["point_id"])
        (out / fname).write_text("".join(canonical_dumps(r) + "\n" for r in recs))
    prov = {"ingest": "api", "blis": run["blis"], "simulator": sim, "harness_commit": "0123456789abcdef0123456789abcdef01234567",
            "experimental": False, "units": None, "engine": {"kind": "vllm", "version": ENGINE},
            "points": len(POINTS) + len(NOT_SCORED), "left_out_records": 3,
            "vllm_ref": VLLM_REF, "vllm_max_distance": 2000,
            "fields_sha256": FIELDS_SHA, "pulled_at": "2026-10-23T00:00:00Z", "corpora": CORPORA,
            "pull_manifest_sha256": "2" * 64,
            "source": {"name": "SemiAnalysis InferenceX API", "url": "https://inferencex.semianalysis.com/api/v1/"}}
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
