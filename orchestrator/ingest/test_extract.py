"""Tests for the extractor stages: repr parsing, settings, policy, replay inputs, support,
artifacts and the API pull (orchestrator/ingest/). Network clients are faked.

Run: python3 orchestrator/ingest/test_extract.py
"""
import gzip
import io
import json
import sys
import tarfile
import tempfile
import zipfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import api  # noqa: E402
import artifacts as art  # noqa: E402
import pyrepr  # noqa: E402
import replay as rp  # noqa: E402
import settings as st  # noqa: E402
import support as sp  # noqa: E402

POLICY, POLICY_SHA = st.load_policy()


def _log(args: str, resolved: str = "", extra: str = "") -> str:
    out = f"INFO [api_utils.py:286] non-default args: {{{args}}}\n"
    if resolved:
        out += f"INFO [core.py:129] Initializing a V1 LLM engine (v0.30.1rc1.dev493+gac9126e58) with config: {resolved}\n"
    return out + extra


def _classify(log: str, launch=None):
    readings, problems = st.read_all(log, launch)
    assert problems == [], problems
    return st.classify(st.merge(readings, POLICY), POLICY)


# ------------------------------------------------------------------ pyrepr

def test_repr_reads_dicts_objects_enums_and_keeps_float_text():
    v = pyrepr.parse("{'a': 0.90, 'b': KernelConfig(moe_backend='auto', x=None), "
                     "'c': {'mode': <CompilationMode.VLLM_COMPILE: 3>}, 'd': [1, 2], 'e': True}")
    assert v == {"a": "0.90", "b": {"moe_backend": "auto", "x": None}, "c": {"mode": "VLLM_COMPILE"},
                 "d": [1, 2], "e": True}
    assert isinstance(v["a"], pyrepr.Float) and float(v["a"]) == 0.9


def test_repr_refuses_what_it_cannot_read():
    for bad in ("{'a': }", "{'a': 1", "Obj(1, 2)"):
        try:
            pyrepr.parse(bad)
        except pyrepr.ReprError:
            continue
        raise AssertionError(bad)


def test_resolved_line_keeps_bare_words_as_text():
    got = pyrepr.parse_kwargs("model='m', dtype=torch.bfloat16, tensor_parallel_size=4, "
                              "device_config=cuda, speculative_config=SpeculativeConfig(method='dspark', num_spec_tokens=5)")
    assert got == {"model": "m", "dtype": "torch.bfloat16", "tensor_parallel_size": 4, "device_config": "cuda",
                   "speculative_config": {"method": "dspark", "num_spec_tokens": 5}}


# ------------------------------------------------------------------ the policy table

def test_most_specific_policy_entry_wins():
    assert st.lookup(POLICY, "attention_config.indexer_kv_dtype")[0] == "attention_config.indexer_kv_dtype"
    assert st.lookup(POLICY, "attention_config.flex_attn_block_m")[0] == "attention_config.*"
    assert st.lookup(POLICY, "some_new_flag") is None


def test_an_unknown_arg_refuses_the_point():
    c = _classify(_log("'max_num_seqs': 8, 'brand_new_knob': 3"))
    assert "unclassified_arg:brand_new_knob" in c.reasons


def test_every_policy_entry_is_well_formed():
    classes = {"mapped", "inert", "approximate", "refuse"}
    for path, e in POLICY["entries"].items():
        assert e["class"] in classes, path
        if e["class"] == "mapped":
            assert e.get("blis_field"), path
        if e["class"] == "approximate":
            assert e.get("note") and e.get("upstream"), path
        if e["class"] == "refuse":
            assert e.get("note"), path


# ------------------------------------------------------------------ settings sources

def test_args_win_and_engine_lines_fill_what_args_omit():
    log = _log("'max_num_seqs': 16, 'tensor_parallel_size': 4", extra=(
        "INFO Setting kv cache block size to 64 for FLASHMLA backend(s).\n" * 4
        + "INFO Desired GPU memory utilization is (0.92, 128.5 GiB).\n"
        + "INFO Chunked prefill is enabled with max_num_batched_tokens=8192.\n"))
    c = _classify(log)
    got = {f: v[1] for f, v in c.mapped.items()}
    assert got["engine.max_num_seqs"] == 16 and got["parallel.tp"] == 4
    assert got["engine.block_size"] == 64 and got["engine.max_num_batched_tokens"] == 8192
    assert got["engine.gpu_memory_utilization"] == 0.92
    block = next(a for a in c.args if a["arg"] == "block_size")
    assert block["source"] == "engine_line" and block["occurrences"] == 4


def test_engine_lines_that_disagree_across_ranks_conflict():
    log = _log("'max_num_seqs': 16", extra="Setting kv cache block size to 64 for X\nSetting kv cache block size to 128 for X\n")
    c = _classify(log)
    assert "conflict:block_size" in c.reasons
    rec = next(a for a in c.args if a["arg"] == "block_size")
    assert rec["match"] == "conflict" and rec["values"] == [128, 64]


def test_launch_config_and_args_that_disagree_conflict():
    launch = {"roles": {"agg": {"args": {"max-num-seqs": 32}}}}
    c = _classify(_log("'max_num_seqs': 16"), launch)
    assert "conflict:max_num_seqs" in c.reasons


def test_the_resolved_line_is_the_engines_resolution_not_a_conflict():
    # Asked VLLM_COMPILE; the engine ran NONE (vLLM runs DeepSeek-V4.1 uncompiled). Not a conflict,
    # and the compile mode is judged on what ran.
    c = _classify(_log("'compilation_config': {'mode': <CompilationMode.VLLM_COMPILE: 3>}",
                       "compilation_config={'mode': <CompilationMode.NONE: 0>}"))
    assert c.reasons == []


def test_a_setting_the_run_asked_for_and_blis_cannot_state_is_not_modelled():
    c = _classify(_log("'prefill_schedule_interval': 32"))
    assert c.reasons == ["setting_not_modelled:prefill_schedule_interval"]
    assert next(a for a in c.args if a["arg"] == "prefill_schedule_interval")["match"] == "absent_in_blis"


def test_a_field_printed_at_its_default_is_not_a_request():
    # vLLM prints a config object whole: its defaults are not settings the run chose.
    c = _classify(_log("'attention_config': AttentionConfig(backend=None, use_trtllm_attention=None, "
                       "indexer_kv_dtype='auto', indexer_sparse_logits=False)"))
    assert c.reasons == [] and not c.approximated


def test_the_indexer_cache_dtype_is_approximated_with_its_upstream_issue():
    c = _classify(_log("'attention_config': AttentionConfig(indexer_kv_dtype='mxfp4', indexer_sparse_logits=True)"))
    assert c.reasons == [] and c.approximated
    rec = {a["arg"]: a for a in c.args}
    assert rec["attention_config.indexer_kv_dtype"]["match"] == "approximated"
    assert rec["attention_config.indexer_kv_dtype"]["upstream"] == "inference-sim/blis-schemas#57"
    assert rec["attention_config.indexer_sparse_logits"]["measured"] is True


def test_moe_backend_is_mapped_to_its_blis_field():
    c = _classify(_log("'kernel_config': KernelConfig(moe_backend='deep_gemm_mega_moe')"))
    assert c.mapped["engine.moe_backend"][1] == "deep_gemm_mega_moe"


def test_the_rust_frontend_line_maps_to_engine_frontend():
    c = _classify(_log("'max_num_seqs': 1", extra="INFO Launching Rust frontend: /usr/bin/vllm\n"))
    assert c.mapped["engine.frontend"][1] == "1"


def test_served_model_name_is_a_list_in_args_and_a_scalar_in_the_launch_config():
    launch = {"roles": {"agg": {"args": {"served-model-name": "org/m"}}}}
    c = _classify(_log("'served_model_name': ['org/m']"), launch)
    assert c.reasons == []


# ------------------------------------------------------------------ the deployment written

PART_H200 = st.Part(name="h200", memory_gib=139.80072021)
H200_DEFAULTS = {"device": "h200", "max_num_batched_tokens": 8192, "max_num_seqs": 1024, "memory_gib": 139.80072021}


def test_a_required_setting_nothing_recorded_takes_the_blis_default():
    c = _classify(_log("'tensor_parallel_size': 8, 'max_num_batched_tokens': 8192",
                       extra="Setting kv cache block size to 64 for X\n"))
    b = st.build(c, name="p", model="deepseek-v4.1-flash", part=PART_H200, engine_version="v0.31.0",
                 defaults=H200_DEFAULTS)
    eng = b.deployment["pools"][0]["engine"]
    assert eng["max_num_seqs"] == 1024 and eng["max_num_batched_tokens"] == 8192
    used = b.defaults_used
    assert [u["arg"] for u in used] == ["max_num_seqs"] and used[0]["source"] == "blis_default"
    assert b.reasons == []


def test_a_required_setting_with_no_source_and_no_default_refuses():
    c = _classify(_log("'tensor_parallel_size': 8"))
    b = st.build(c, name="p", model="m", part=PART_H200, engine_version="v0.31.0", defaults=None)
    assert sorted(b.reasons) == ["required_setting_missing:block_size", "required_setting_missing:max_num_batched_tokens",
                                 "required_setting_missing:max_num_seqs"]


def test_the_cluster_is_sized_to_the_runs_own_gpus():
    c = _classify(_log("'tensor_parallel_size': 1, 'data_parallel_size': 2, 'enable_expert_parallel': True, "
                       "'max_num_seqs': 16, 'max_num_batched_tokens': 4096, 'block_size': 128"))
    b = st.build(c, name="p", model="m", part=PART_H200, engine_version="v0.31.0", defaults=H200_DEFAULTS)
    assert b.scenario["cluster"] == {"hardware": "h200", "nodes": 1, "gpus_per_node": 2}
    assert b.scenario["engine_version"] == "0.31.0"
    par = b.deployment["pools"][0]["parallel"]
    assert (par["tp"], par["dp"], par["enable_expert_parallel"]) == (1, 2, True)


def test_offload_bytes_are_the_engines_from_the_server_wide_total():
    # cpu_bytes_to_use is server-wide and vLLM divides it by the engine's world size (TP4 here);
    # BLIS's tier is the engine's, so the bytes are per_rank x world.
    args = ("'tensor_parallel_size': 4, 'max_num_seqs': 8, 'max_num_batched_tokens': 4096, 'block_size': 128, "
            "'kv_transfer_config': KVTransferConfig(kv_connector='SimpleCPUOffloadConnector', kv_role='kv_both', "
            "kv_connector_extra_config={'cpu_bytes_to_use': 1000000000003, 'lazy_offload': True})")
    c = _classify(_log(args, extra="SimpleCPUOffloadConnector: role=WORKER, per_rank=232.83 GB, world_size=4\n"))
    b = st.build(c, name="p", model="m", part=PART_H200, engine_version="v0.31.0", defaults=H200_DEFAULTS)
    assert b.reasons == [], b.reasons
    assert b.deployment["offload"] == {"connector": "SimpleCPUOffloadConnector", "spec": "lazy",
                                       "tiers": [{"tier": "cpu_dram", "bytes": (1000000000003 // 4) * 4}]}


def test_offload_bytes_that_disagree_with_the_logged_per_rank_figure_conflict():
    args = ("'tensor_parallel_size': 4, 'max_num_seqs': 8, 'max_num_batched_tokens': 4096, 'block_size': 128, "
            "'kv_transfer_config': KVTransferConfig(kv_connector='SimpleCPUOffloadConnector', "
            "kv_connector_extra_config={'cpu_bytes_to_use': 1000000000000})")
    c = _classify(_log(args, extra="SimpleCPUOffloadConnector: role=WORKER, per_rank=50.00 GB, world_size=4\n"))
    b = st.build(c, name="p", model="m", part=PART_H200, engine_version="v0.31.0", defaults=H200_DEFAULTS)
    assert b.reasons == ["conflict:kv_transfer_config.kv_connector_extra_config.cpu_bytes_to_use"]


# ------------------------------------------------------------------ replay inputs

def _export(**over):
    ph = {"name": "profiling", "kind": "profiling", "type": "concurrency", "duration": 3600.0, "concurrency": 8,
          "grace_period": 30.0, "timing_mode": "agentic_replay", "trajectory_start_min_ratio": 0.25,
          "trajectory_start_max_ratio": 0.75, "system_idle_gap_cap_seconds": 10.0, "warmup_requests_per_lane": 10}
    ds = {"name": "main", "type": "public", "dataset": "semianalysis_cc_traces_weka_062126", "entries": 393,
          "random_seed": 42, "trace_idle_gap_cap_seconds": 300.0}
    ph.update(over.pop("phase", {}))
    doc = {"aiperf_version": "1.0.11", "input_config": {"scenario": "agentx", "phases": [ph], "datasets": [ds],
                                                         "endpoint": {"streaming": True}},
           "metadata": {"dataset": {"loader": "semianalysis_cc_traces_weka_062126",
                                    "hf_dataset_name": "semianalysisai/cc-traces-weka-062126", "hf_split": "train"}}}
    doc["input_config"].update(over)
    return doc


def test_agentx_replays_as_the_mvp_scenario_with_the_runs_own_inputs():
    r = rp.from_export(_export())
    rp.cross_check(r, "agentx profile --concurrency 8 --benchmark-duration 3600", 8)
    assert r.reasons == [] and r.replayed_as == "inferencex-agentx-mvp"
    spec = rp.workload_spec(r, "a" * 64, "rev", "traces.jsonl")
    assert spec["concurrency"] == 8 and spec["random_seed"] == 42 and spec["benchmark_duration_s"] == 3600.0
    assert spec["trajectory_start"] == {"min_ratio": 0.25, "max_ratio": 0.75}
    assert "trace_idle_gap_cap_s" not in spec       # inference-sim#1971: not passed


def test_a_command_line_or_row_that_disagrees_with_the_export_conflicts():
    r = rp.from_export(_export())
    rp.cross_check(r, "aiperf profile --concurrency 16 --random-seed 7", 8)
    assert r.reasons == ["conflict:replay.concurrency", "conflict:replay.seed"]
    r = rp.from_export(_export())
    rp.cross_check(r, None, 4)
    assert r.reasons == ["conflict:replay.concurrency"]


def test_another_client_scenario_is_not_replayable():
    r = rp.from_export(_export(scenario="some-other-preset"))
    assert "client_scenario_not_replayable:some-other-preset" in r.reasons


def test_a_system_idle_cap_other_than_the_locked_one_is_not_modelled():
    r = rp.from_export(_export(phase={"system_idle_gap_cap_seconds": 30.0}))
    assert "setting_not_modelled:replay.system_idle_gap_cap_seconds" in r.reasons


# ------------------------------------------------------------------ support checks

def _catalog(tmp: Path) -> sp.Catalog:
    for name, repo, spec in (("dsv41", "deepseek-ai/DeepSeek-V4.1-Flash", "dspark"),
                             ("mm3", "MiniMaxAI/MiniMax-M3", "minimax_m3_mtp")):
        (tmp / "models" / name).mkdir(parents=True)
        (tmp / "models" / name / "model.yaml").write_text(f"name: {name}\nsource:\n  repo: {repo}\n")
        (tmp / "models" / name / "graph.yaml").write_text(f"global: {{}}\nspeculator:\n  method: {spec}\n")
    (tmp / "hardware").mkdir()
    (tmp / "hardware" / "h200.yaml").write_text("MemoryGiB: 139.8\n")
    (tmp / "hardware" / "tpuv7.yaml").write_text("MemoryGiB: 192\n")
    return sp.Catalog.load(tmp)


def test_support_matches_the_checkpoint_then_its_base_model():
    cat = _catalog(Path(tempfile.mkdtemp()))
    s = sp.check(cat, {"h200"}, checkpoints=["deepseek-ai/DeepSeek-V4.1-Flash"], base_models={}, hardware="h200",
                 spec_method="dspark")
    assert (s.model, s.matched_by, s.reasons) == ("dsv41", "checkpoint", [])
    s = sp.check(cat, {"h200"}, checkpoints=["nvidia/MiniMax-M3-NVFP4"],
                 base_models={"nvidia/MiniMax-M3-NVFP4": "MiniMaxAI/MiniMax-M3"}, hardware="h200", spec_method=None)
    assert (s.model, s.matched_by) == ("mm3", "base_model")


def test_support_refuses_an_unknown_model_part_or_drafter():
    cat = _catalog(Path(tempfile.mkdtemp()))
    s = sp.check(cat, {"h200"}, checkpoints=["org/unknown"], base_models={}, hardware="h200", spec_method=None)
    assert s.reasons == ["model_not_in_catalog"]
    s = sp.check(cat, {"h200"}, checkpoints=["deepseek-ai/DeepSeek-V4.1-Flash"], base_models={}, hardware="tpuv7",
                 spec_method="dspark")
    assert s.reasons == ["hardware_no_coefficients"]
    s = sp.check(cat, {"h200"}, checkpoints=["MiniMaxAI/MiniMax-M3"], base_models={}, hardware="h200",
                 spec_method="eagle3")
    assert s.reasons == ["drafter_not_in_catalog:eagle3"]


# ------------------------------------------------------------------ artifacts

def _A(i, name, t, expired=False):
    return art.Artifact(id=i, name=name, created_at=t, expired=expired, size=1)


RF = "dsv41flash_tp4_conc8_x"


def test_join_goes_through_the_result_json_and_ignores_attempt_only_uploads():
    arts = [_A(1, "bmk_agentic_" + RF, "2026-10-01T10:00:00Z"),
            _A(2, "server_logs_" + RF, "2026-10-01T09:00:00Z"),     # an earlier, failed attempt
            _A(3, "server_logs_" + RF, "2026-10-01T10:00:05Z"),
            _A(4, "agentic_" + RF, "2026-10-01T10:00:03Z"),
            _A(5, "server_logs_other", "2026-10-01T10:00:05Z")]     # no result JSON: not a point
    docs = {1: {"recipe_fingerprint": "f" * 64, "conc": 8}}
    j = art.join({"recipe_fingerprint": "f" * 64, "conc": 8}, arts, lambda a: docs.get(a.id), agentic=True)
    assert j.reasons == [] and j.result_filename == RF and j.server_logs.id == 3 and j.agentic.id == 4


def test_join_reports_no_match_and_several_matches():
    arts = [_A(1, "bmk_" + RF, "t1"), _A(2, "bmk_" + RF + "2", "t2")]
    same = {"recipe_fingerprint": "f" * 64, "conc": 8}
    j = art.join({"recipe_fingerprint": "f" * 64, "conc": 4}, arts, lambda a: same, agentic=False)
    assert j.reasons == ["artifact_unmatched:no_result"]
    j = art.join({"recipe_fingerprint": "f" * 64, "conc": 8}, arts, lambda a: same, agentic=False)
    assert j.reasons == ["artifact_unmatched:several_results"]
    j = art.join({"recipe_fingerprint": None, "conc": 8}, arts, lambda a: same, agentic=False)
    assert j.reasons == ["artifact_unmatched:no_recipe_fingerprint"]


def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in files.items():
            z.writestr(n, d)
    return buf.getvalue()


def _targz(files: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for n, d in files.items():
            info = tarfile.TarInfo(n)
            info.size = len(d)
            t.addfile(info, io.BytesIO(d))
    return buf.getvalue()


LOG = b"INFO non-default args: {'max_num_seqs': 8}\n"
CFG = f"roles:\n  agg:\n    args: {{max-num-seqs: 8}}\nbenchmark:\n  env:\n    RESULT_FILENAME: {RF}\n".encode()


def test_both_server_log_layouts_are_found_by_content():
    plain = _zip({"results/server.log": LOG, "results/benchmark.log": b"client noise\n"})
    nested = _zip({"srt-single-node-logs.tar.gz": _targz({"./logs/host-01_agg_w0.out": LOG,
                                                          "./config_tp4_c8.yaml": CFG,
                                                          "./logs/config_tp4_c8.yaml": CFG,
                                                          "./logs/benchmark.out": b"x"})})
    for blob, path in ((plain, "results/server.log"), (nested, "srt-single-node-logs.tar.gz/logs/host-01_agg_w0.out")):
        files = list(art.iter_files(blob))
        assert [p for p, _ in art.find_server_logs(files)] == [path]
    p, cfg = art.find_launch_config(list(art.iter_files(nested)), RF)
    assert cfg["roles"]["agg"]["args"]["max-num-seqs"] == 8


def test_two_different_launch_configs_for_one_point_are_refused():
    other = CFG.replace(b"8}", b"16}")
    files = list(art.iter_files(_targz({"./a.yaml": CFG, "./b.yaml": other})))
    try:
        art.find_launch_config(files, RF)
    except ValueError:
        return
    raise AssertionError("accepted two different launch configs")


def test_frozen_files_are_byte_stable():
    assert art.stable_gzip(b"same") == art.stable_gzip(b"same")


# ------------------------------------------------------------------ the API pull

def test_display_map_is_read_from_the_site_and_rows_windowed_on_date():
    site = {"/": b'<script src="/_next/static/c/a.js"></script>',
            "/_next/static/c/a.js": b'x={dsv41flash:"DeepSeek-V4.1-Flash","glm5.1":"GLM-5",glm5:"GLM-5"}',
            "/api/v1/availability": json.dumps([{"model": m, "framework": "vllm", "date": "2026-10-20"}
                                                for m in ("dsv41flash", "glm5", "glm5.1", "newmodel")]).encode()}
    rows = {"DeepSeek-V4.1-Flash": [{"id": "2", "model": "dsv41flash", "framework": "vllm", "date": "2026-10-20"},
                                    {"id": "1", "model": "dsv41flash", "framework": "vllm", "date": "2026-08-01",
                                     "curve_date": "2026-10-20"}],
            "GLM-5": [{"id": "3", "model": "glm5.1", "framework": "vllm", "date": "2026-10-21"},
                      {"id": "4", "model": "glm5", "framework": "sglang", "date": "2026-10-21"}]}

    def fetch(url):
        path = url[len(api.BASE):]
        if path.startswith("/api/v1/benchmarks?model="):
            import urllib.parse
            return gzip.compress(json.dumps(rows[urllib.parse.unquote(path.split("=", 1)[1])]).encode())
        return site[path]

    p = api.pull(fetch, today=date(2026, 10, 23), window_days=7)
    assert [r["id"] for r in p.rows] == ["2", "3"]          # by date, not curve_date; vllm only
    assert p.unnamed_slugs == ["newmodel"]                  # reported, not guessed


def test_run_and_attempt_from_run_url():
    assert api.run_of({"run_url": "https://github.com/o/r/actions/runs/123/attempts/2"}) == ("123", 2)
    assert api.run_of({"run_url": "https://github.com/o/r/actions/runs/123"}) == ("123", 1)
    assert api.run_of({"run_url": None}) is None


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
