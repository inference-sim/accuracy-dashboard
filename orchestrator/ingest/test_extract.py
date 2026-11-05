"""Tests for the extractor stages: repr parsing, settings and their decision by the field list,
replay inputs, support,
artifacts and the API pull (orchestrator/ingest/). Network clients are faked.

Run: python3 orchestrator/ingest/test_extract.py
"""
import gzip
import io
import json
import re
import sys
import tarfile
import tempfile
import zipfile
from datetime import date
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import api  # noqa: E402
import artifacts as art  # noqa: E402
import fields as fl  # noqa: E402
import inferencex_runners as ir  # noqa: E402
import pyrepr  # noqa: E402
import replay as rp  # noqa: E402
import settings as st  # noqa: E402
import support as sp  # noqa: E402

DEFAULTS, _ = st.load_vllm_defaults()
FIELDS = fl.parse((HERE / "testdata" / "fields" / "fields.json").read_bytes())

# A resolved engine-config line as vLLM v0.31.0 prints it (every engine log has one).
RESOLVED = ("model='m', tensor_parallel_size=1, pipeline_parallel_size=1, data_parallel_size=1, "
            "quantization=fp8, kv_cache_dtype=auto, enable_prefix_caching=True, "
            "compilation_config={'mode': <CompilationMode.NONE: 0>, 'cudagraph_mode': <CUDAGraphMode.FULL_AND_PIECEWISE: (2, 1)>}")


def _log(args: str, resolved: str = RESOLVED, extra: str = "") -> str:
    out = f"INFO [api_utils.py:286] non-default args: {{{args}}}\n"
    if resolved is RESOLVED:
        # The engine runs the parallelism the args asked for, as in every real log.
        for k in ("tensor_parallel_size", "pipeline_parallel_size", "data_parallel_size"):
            m = re.search(rf"'{k}': (\d+)", args)
            if m:
                resolved = re.sub(rf"{k}=\d+", f"{k}={m.group(1)}", resolved)
    if resolved is not None:
        out += f"INFO [core.py:129] Initializing a V1 LLM engine (v0.30.1rc1.dev493+gac9126e58) with config: {resolved}\n"
    return out + extra


def _classify(log: str, launch=None, extra_readings=None):
    readings, problems = st.read_all(log, launch)
    assert problems == [], problems
    readings.update(extra_readings or {})
    return st.decide(st.merge(readings, DEFAULTS), FIELDS)


NODE8 = ir.NodeSize(8, "cluster.gpus_per_node: launch_config")


def _build(c, **kw):
    kw.setdefault("catalog_node_size", None)
    kw.setdefault("node", NODE8)
    return st.build(c, name="p", model="m", part=PART_H200, engine_version="0.31.0", field_list=FIELDS, **kw)


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


# ------------------------------------------------------------------ settings sources

def test_a_resolved_value_that_differs_from_the_passed_one_is_not_a_conflict():
    # Design §11.2: the engine resolves its settings; the block holds the value the run passed.
    log = _log("'block_size': 16", extra="INFO Setting kv cache block size to 64 for FLASHMLA backend(s).\n")
    c = _classify(log)
    assert c.reasons == [] and c.mapped["engine.block_size"] == ("block_size", 16)


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


def test_two_spellings_of_compilation_mode_the_engine_parses_alike_are_one_value():
    # vLLM parses CompilationConfig.mode from 3 or "VLLM_COMPILE" alike (config/compilation.py:852-870).
    launch = {"roles": {"agg": {"args": {"compilation-config": '{"mode": 3}'}}}}
    c = _classify(_log("'compilation_config': {'mode': <CompilationMode.VLLM_COMPILE: 3>}"), launch)
    assert c.reasons == []
    launch = {"roles": {"agg": {"args": {"compilation-config": '{"mode": 0}'}}}}
    c = _classify(_log("'compilation_config': {'mode': <CompilationMode.VLLM_COMPILE: 3>}"), launch)
    assert c.reasons == ["conflict:compilation_config.mode"]


def test_a_not_modelled_field_the_run_set_with_no_rule_is_field_not_modelled():
    c = _classify(_log("'prefill_schedule_interval': 32"))
    assert c.reasons == ["field_not_modelled:prefill_schedule_interval"]


def test_a_field_the_release_lacks_is_field_not_in_release():
    c = _classify(_log("'brand_new_knob': 3"))
    assert c.reasons == ["field_not_in_release:brand_new_knob"]


def test_a_field_printed_at_its_default_is_not_set_by_the_run():
    # vLLM prints a config object whole: its defaults are not settings the run chose, so even a
    # not-modelled field there decides nothing.
    c = _classify(_log("'compilation_config': {'custom_ops': []}, 'attention_config': AttentionConfig("
                       "backend=None, indexer_kv_dtype='auto', indexer_sparse_logits=False)"))
    assert c.reasons == [] and c.substitutions == []


def test_a_not_modelled_field_with_a_leave_unset_rule_is_left_unset_and_named():
    c = _classify(_log("'attention_config': AttentionConfig(indexer_kv_dtype='mxfp4', indexer_sparse_logits=True)"))
    assert c.reasons == []
    assert [(x["kind"], x["subject"]) for x in c.substitutions] == [
        ("estimated", "attention_config.indexer_kv_dtype"), ("estimated", "attention_config.indexer_sparse_logits")]
    rec = {a["arg"]: a for a in c.args}
    assert rec["attention_config.indexer_kv_dtype"]["match"] == "approximated"
    assert "engine.indexer_kv_dtype" not in c.mapped                 # left to the engine (X19)


def test_an_inert_unproven_field_the_run_set_is_named_as_an_interim_status():
    c = _classify(_log("'attention_config': AttentionConfig(backend='FLASHINFER')"))
    assert c.reasons == [] and [(x["kind"], x["subject"]) for x in c.substitutions] == \
        [("interim_status", "attention_config.backend")]


def test_every_recorded_value_is_copied_verbatim_under_the_engines_own_names():
    # COV-3: no value is translated; only the names the engine block renames are renamed.
    c = _classify(_log("'max_num_seqs': 16, 'tensor_parallel_size': 1, 'kv_cache_dtype': 'fp8', "
                       "'compilation_config': {'max_cudagraph_capture_size': 512}, "
                       "'speculative_config': {'method': 'mtp', 'num_speculative_tokens': 2}"))
    assert {k: v[1] for k, v in c.mapped.items() if k.startswith("engine.")} == {
        "engine.max_num_seqs": 16, "engine.cache_dtype": "fp8", "engine.quantization": "fp8",
        "engine.enable_prefix_caching": True, "engine.cudagraph_mode": "FULL_AND_PIECEWISE",
        "engine.max_cudagraph_capture_size": 512,
        "engine.speculative.method": "mtp", "engine.speculative.num_spec_tokens": 2}


def test_every_location_is_a_field_blis_vllm_engine_block_or_the_deployment_names():
    # The names blis-vllm rules/engineconfig/fieldnames_test.go (origin/m1/vllm) pins, and the
    # Deployment's parallel and offload fields (blis-substrate contracts/spec/deployment).
    engine = {"all2all_backend", "disable_custom_all_reduce", "cudagraph_mode", "max_cudagraph_capture_size",
              "cudagraph_capture_sizes", "async_scheduling", "frontend", "disable_cascade_attn",
              "enable_prefix_caching", "swa_bounded_replay", "block_size", "max_num_batched_tokens", "max_num_seqs",
              "long_prefill_token_threshold", "max_model_len", "quantization", "cache_dtype", "mamba_cache_dtype",
              "mamba_ssm_cache_dtype", "mamba_cache_mode", "gpu_memory_utilization", "scheduling_policy", "dbo",
              "eplb", "speculative", "engram_config", "moe_backend", "dcp_comm_backend", "dcp_q_replicate",
              "cp_kv_cache_interleave_size", "long_prefill_token_threshold_adaptive", "max_num_scheduled_tokens",
              "max_num_active_seqs", "watermark", "prefill_schedule_interval", "stream_interval",
              "disable_hybrid_kv_cache_manager", "kv_cache_memory_bytes", "prefix_match_unit",
              "prefix_cache_retention_interval", "kv_events", "max_loras", "max_cpu_loras",
              "decoder_replay_cudagraph_capture_sizes", "custom_ops", "use_trtllm_attention", "mla_prefill_backend",
              "indexer_kv_dtype", "linear_backend", "env"}
    parallel = {"tp", "pp", "dp", "dp_local", "enable_expert_parallel", "pcp", "dcp"}
    for path, loc in st.LOCATIONS.items():
        top, _, rest = loc.partition(".")
        if top == "engine":
            assert rest.split(".")[0] in engine, (path, loc)
        elif top == "parallel":
            assert rest in parallel, (path, loc)
        elif rest.startswith("connector_options."):
            assert rest.split(".", 1)[1] in {"load_async", "lookup_async", "enable_offload",
                                             "enable_cross_layers_blocks", "lazy_offload", "blocks_per_chunk",
                                             "kv_load_failure_policy"}, (path, loc)
        else:
            assert top in ("offload", "replay") and rest in ("connector", "spec", "tiers.cpu_dram",
                                                             "acceptance_length"), (path, loc)
    assert st.location("env.VLLM_FLASHINFER_ALLREDUCE_BACKEND") == "engine.env.VLLM_FLASHINFER_ALLREDUCE_BACKEND"


def test_a_local_model_path_is_named_by_the_runs_own_recipe():
    import recipes as rc
    master = """
minimaxm3-fp8-b200-vllm:
  model: MiniMaxAI/MiniMax-M3-MXFP8
  model-prefix: minimaxm3
  image: vllm/vllm-openai:nightly-93d8f834
  framework: vllm
  precision: fp8
  runner: cluster:b200-dgxc
minimaxm3-fp4-b200-vllm:
  model: nvidia/MiniMax-M3-NVFP4
  model-prefix: minimaxm3
  image: vllm/vllm-openai:nightly-93d8f834
  framework: vllm
  precision: fp4
  runner: b200
gptoss-fp4-b200-vllm:
  model: openai/gpt-oss-120b
  model-prefix: gptoss
  image: vllm/vllm-openai:v0.22.0
  framework: vllm
  precision: fp4
  runner: b200
dsv4-fp4-b200-vllm:
  model: deepseek-ai/DeepSeek-V4-Pro
  model-prefix: dsv4
  image: vllm/vllm-openai:nightly-7c5dc571
  framework: vllm
  precision: fp4
  runner: b200-dsv4
"""
    runners = """
clusters:
  h200-dgxc:
    models:
      entries:
        DeepSeek-V4-Pro-0813: {root: hf-hub-cache, dir: DeepSeek-V4-Pro}
"""
    r = rc.parse([master], runners)
    row = lambda **kw: {"framework": "vllm", "hardware": "b200", "image": "vllm/vllm-openai:nightly-93d8f834", **kw}
    # precision tells the two MiniMax-M3 checkpoints apart; the path agrees with each
    assert rc.checkpoint(r, row(precision="fp8"), "/lustre/fsw/gharunners/models/MiniMax-M3-MXFP8") == "MiniMaxAI/MiniMax-M3-MXFP8"
    assert rc.checkpoint(r, row(precision="fp4"), "/scratch/fsw/models/MiniMax-M3-NVFP4") == "nvidia/MiniMax-M3-NVFP4"
    # the API slug (gptoss120b) and the recipe prefix (gptoss) differ: not used
    assert rc.checkpoint(r, row(precision="fp4", image="vllm/vllm-openai:v0.22.0", model="gptoss120b"),
                         "/lustre/fsw/models/gpt-oss-120b") == "openai/gpt-oss-120b"
    # a path that isn't the recipe's model (a re-quantized copy) is never given its name
    assert rc.checkpoint(r, row(precision="fp4", image="vllm/vllm-openai:nightly-7c5dc571"),
                         "/scratch/models/DeepSeek-V4-Pro-NVFP4") is None
    # the same image on another part, or a different image, matches nothing
    assert rc.checkpoint(r, row(precision="fp8", hardware="h200"), "/x/MiniMax-M3-MXFP8") is None
    assert rc.checkpoint(r, row(precision="fp8", image="vllm/vllm-openai:other"), "/x/MiniMax-M3-MXFP8") is None
    assert rc.checkpoint(r, row(precision="fp8"), None) is None
    # runners.yaml's staged directory names a recipe model by another name
    r2 = rc.parse(["""
dsv4-fp4-h200-vllm:
  model: deepseek-ai/DeepSeek-V4-Pro-0813
  image: vllm/vllm-openai:nightly-x
  framework: vllm
  precision: fp4
  runner: h200-dgxc
"""], runners)
    assert rc.checkpoint(r2, row(precision="fp4", hardware="h200", image="vllm/vllm-openai:nightly-x"),
                         "/models/gharunners/hf-hub-cache/DeepSeek-V4-Pro") == "deepseek-ai/DeepSeek-V4-Pro-0813"
    # two recipes that both fit the path: refused, not picked
    r3 = rc.parse([master, master.replace("MiniMaxAI/MiniMax-M3-MXFP8", "other/MiniMax-M3-MXFP8").replace("minimaxm3-fp8-b200-vllm", "dup")], None)
    assert rc.checkpoint(r3, row(precision="fp8"), "/x/MiniMax-M3-MXFP8") is None
    assert rc.runner_hardware("cluster:b200-dgxc") == rc.runner_hardware("b200-multinode") == "b200"


def test_gpu_memory_utilization_is_read_from_the_profiling_note_when_no_desired_line():
    # vLLM v0.25 prints no "Desired GPU memory utilization" line; its CUDA-graph note states it.
    log = ("(Worker_TP0 pid=1) INFO [gpu_worker.py:481] CUDA graph memory profiling is enabled (default since "
           "v0.21.0). The current --gpu-memory-utilization=0.9200 is equivalent to --gpu-memory-utilization=0.8794 "
           "without CUDA graph memory profiling.")
    r = st.read_engine_lines(log + "\n" + log.replace("TP0", "TP1"))
    assert [str(v) for v in r.values["gpu_memory_utilization"]] == ["0.9200"] * 2


def test_an_env_var_vllm_warns_is_deprecated_is_read_as_set():
    # gpt-oss-120b h200 v0.22.0 (point 0004425a4c559ee3): no launch config, but vLLM printed
    log = ("(EngineCore pid=1) /usr/lib/python3/vllm/envs.py:358: FutureWarning: VLLM_MXFP4_USE_MARLIN is "
           "deprecated and will be removed in v0.23. Use --moe-backend instead.\n")
    r = st.read_engine_lines(log + log)
    assert r.values["env.VLLM_MXFP4_USE_MARLIN"] == [True]           # once, however often it's printed
    # set by the run, and not modelled with no rule in the field list
    c = _classify(_log("'tensor_parallel_size': 1") + "\n" + log)
    assert c.reasons == ["field_not_modelled:env.VLLM_MXFP4_USE_MARLIN"]
    # a variable the release does not read is not in its field list
    c = _classify(_log("'tensor_parallel_size': 1") + "\n" + log.replace("VLLM_MXFP4_USE_MARLIN", "VLLM_SOMETHING_NEW"))
    assert c.reasons == ["field_not_in_release:env.VLLM_SOMETHING_NEW"]


def test_an_environment_variable_is_copied_into_the_engine_env_as_the_launch_gave_it():
    launch = {"roles": {"agg": {"args": {"max-num-seqs": 16}, "env": {"VLLM_FLASHINFER_ALLREDUCE_BACKEND": "trtllm"}}}}
    c = _classify(_log("'max_num_seqs': 16"), launch)
    b = _build(c)
    assert b.deployment["pools"][0]["engine"]["env"] == {"VLLM_FLASHINFER_ALLREDUCE_BACKEND": "trtllm"}
    # a variable whose value the run did not record (only a deprecation warning) is not copied
    log = "FutureWarning: VLLM_FLASHINFER_ALLREDUCE_BACKEND is deprecated and will be removed\n"
    c = _classify(_log("'max_num_seqs': 16") + log)
    assert c.reasons == ["required_setting_missing:env.VLLM_FLASHINFER_ALLREDUCE_BACKEND"]


def test_moe_backend_is_copied_to_the_engine_blocks_field():
    c = _classify(_log("'kernel_config': KernelConfig(moe_backend='deep_gemm_mega_moe')"))
    assert c.mapped["engine.moe_backend"][1] == "deep_gemm_mega_moe"


def test_the_rust_frontend_line_maps_to_engine_frontend():
    c = _classify(_log("'max_num_seqs': 1", extra="INFO Launching Rust frontend: /usr/bin/vllm\n"))
    assert c.mapped["engine.frontend"][1] is True
    launch = {"roles": {"agg": {"args": {"max-num-seqs": 1}, "env": {"VLLM_USE_RUST_FRONTEND": "1"}}}}
    assert _classify(_log("'max_num_seqs': 1"), launch).mapped["engine.frontend"][1] is True
    launch["roles"]["agg"]["env"]["VLLM_USE_RUST_FRONTEND"] = "maybe"
    assert "conflict:env.VLLM_USE_RUST_FRONTEND" in _classify(_log("'max_num_seqs': 1"), launch).reasons


def test_served_model_name_is_a_list_in_args_and_a_scalar_in_the_launch_config():
    launch = {"roles": {"agg": {"args": {"served-model-name": "org/m"}}}}
    c = _classify(_log("'served_model_name': ['org/m']"), launch)
    assert c.reasons == []


# ------------------------------------------------------------------ review findings: no silent passes

def test_a_router_from_the_api_row_does_not_hide_what_the_args_line_asked_for():
    router = st.Reading()
    router.add("frontend.router", "vllm-router/consistent_hash")
    c = _classify(_log("'prefill_schedule_interval': 32"), extra_readings={"api_row": router})
    assert c.reasons == ["field_not_modelled:prefill_schedule_interval"]


def test_with_a_launch_config_an_args_only_request_still_counts():
    launch = {"roles": {"agg": {"args": {"max-num-seqs": 8}}}}
    c = _classify(_log("'max_num_seqs': 8, 'prefill_schedule_interval': 4"), launch)
    assert "field_not_modelled:prefill_schedule_interval" in c.reasons


def test_a_log_missing_its_args_or_resolved_line_is_unreadable():
    _, problems = st.read_all(_log("'max_num_seqs': 8", resolved=None), None)
    assert problems == ["server log has no resolved engine-config line"]
    _, problems = st.read_all("INFO [core.py:129] Initializing a V1 LLM engine (v0.31.0) with config: " + RESOLVED + "\n", None)
    assert problems == ["server log has no `non-default args` line"]


def test_a_field_inside_a_config_object_is_decided_when_set_and_ignored_at_its_default():
    c = _classify(_log("'attention_config': AttentionConfig(backend=None, flex_attn_block_m=64)"))
    assert c.reasons == []                                       # proven inert in the fixture
    # A field the release's defaults have no entry for is unset unless the launch config states it.
    c = _classify(_log("'compilation_config': {'brand_new_knob': 7}"))
    assert c.reasons == []
    launch = {"roles": {"agg": {"args": {"compilation-config": '{"brand_new_knob": 7}'}}}}
    c = _classify(_log("'compilation_config': {'brand_new_knob': 7}"), launch)
    assert c.reasons == ["field_not_in_release:compilation_config.brand_new_knob"]
    c = _classify(_log("'attention_config': AttentionConfig(backend=None, flex_attn_block_m=None)"))
    assert c.reasons == []


def test_a_none_in_an_earlier_source_does_not_hide_a_later_value():
    c = _classify(_log("'max_num_batched_tokens': None",
                       extra="Chunked prefill is enabled with max_num_batched_tokens=8192.\n"))
    assert c.mapped["engine.max_num_batched_tokens"][1] == 8192


def test_a_drafter_without_a_recorded_acceptance_takes_its_estimation_rule():
    # leave_unset in the fixture: the acceptance is left to the simulator's own registry, named.
    c = _classify(_log("'tensor_parallel_size': 1, 'max_num_seqs': 8, 'max_num_batched_tokens': 4096, 'block_size': 128, "
                       "'gpu_memory_utilization': 0.9, 'speculative_config': {'method': 'dspark', 'num_speculative_tokens': 5}"))
    b = _build(c)
    assert b.reasons == [] and b.acceptance_length is None


def test_the_flat_and_nested_spellings_of_one_setting_agree_or_conflict():
    c = _classify(_log("'max_cudagraph_capture_size': 512, 'compilation_config': {'max_cudagraph_capture_size': 512}"))
    assert c.mapped["engine.max_cudagraph_capture_size"][1] == 512 and c.reasons == []
    c = _classify(_log("'max_cudagraph_capture_size': 256, 'compilation_config': {'max_cudagraph_capture_size': 512}"))
    assert len(c.reasons) == 1 and c.reasons[0].startswith("conflict:")


def test_offload_bytes_printed_as_floats_and_ranks_that_disagree():
    base = ("'tensor_parallel_size': 1, 'max_num_seqs': 8, 'max_num_batched_tokens': 4096, 'block_size': 128, "
            "'gpu_memory_utilization': 0.9, 'kv_transfer_config': KVTransferConfig(kv_connector='SimpleCPUOffloadConnector', "
            "kv_connector_extra_config={'cpu_bytes_to_use': 53687091200.0})")
    c = _classify(_log(base))
    b = _build(c)
    assert b.reasons == [] and b.deployment["offload"]["tiers"][0]["bytes"] == 53687091200
    lines = "SimpleCPUOffloadConnector: role=WORKER, per_rank=50.00 GB, world_size=1\n" \
            "SimpleCPUOffloadConnector: role=WORKER, per_rank=40.00 GB, world_size=1\n"
    b = _build(_classify(_log(base, extra=lines)))
    assert b.reasons == ["conflict:offload.per_rank_gib"]


def test_parallelism_must_come_from_the_run():
    c = _classify(_log("'max_num_seqs': 8", "model='m', quantization=fp8"))
    b = _build(c)
    assert {"required_setting_missing:parallel.tp", "required_setting_missing:parallel.dp"} <= set(b.reasons)


def test_an_unknown_client_input_refuses():
    r = rp.from_export(_export(phase={"brand_new_pacing": 2}))
    assert "client_scenario_not_replayable:phase.brand_new_pacing" in r.reasons
    r = rp.from_export(_export())
    rp.cross_check(r, "aiperf profile --benchmark-grace-period 30 'unterminated", 8)
    assert r.reasons == ["conflict:replay.command_unreadable"]


def test_the_dashboard_holds_no_settings_table():
    # COV-3, design §11.1: field status and estimation rules come only from the engine's
    # fields.json. No file in the orchestrator classifies a setting.
    root = HERE.parent
    assert not (root / "vllm_arg_policy.yaml").exists()
    for f in sorted(root.rglob("*.py")) + sorted(root.rglob("*.yaml")):
        text = f.read_text()
        for word in ("class: mapped", "class: inert", "class: refuse", "class: approximate", "load_policy"):
            assert word not in text or f.name == "test_extract.py", (f, word)


def test_the_vllm_defaults_table_is_read_from_vllm_and_covers_printed_configs():
    assert DEFAULTS["attention_config.indexer_kv_dtype"] == "auto"
    assert DEFAULTS["kernel_config.moe_backend"] == "auto"
    assert DEFAULTS["prefill_schedule_interval"] == 1 and DEFAULTS["enforce_eager"] is False
    assert DEFAULTS["compilation_config.dynamic_shapes_config.type"] == "BACKED"


# ------------------------------------------------------------------ the deployment written

PART_H200 = st.Part(name="h200")


def test_a_setting_nothing_recorded_is_left_unset_and_no_list_of_required_settings_exists():
    # X19, design 11.1: the dashboard holds no list of the settings an engine needs. The engine
    # resolves what is unset; if it refuses, score.value_refusal names the field.
    c = _classify(_log("'tensor_parallel_size': 1"))
    b = _build(c)
    eng = b.deployment["pools"][0]["engine"]
    assert "max_num_seqs" not in eng and "block_size" not in eng and "max_num_batched_tokens" not in eng
    assert b.reasons == [] and b.substitutions == []
    assert not hasattr(st, "REQUIRED")


def test_a_built_scenario_holds_only_recorded_values_and_states_engine_version_from_stack_json():
    # X19: nothing the run did not record is written; engine_version is the release passed in.
    c = _classify(_log("'tensor_parallel_size': 1, 'max_num_batched_tokens': 4096"))
    b = st.build(c, name="p", model="m", part=PART_H200, engine_version="0.32.0", field_list=FIELDS,
                 catalog_node_size=None, node=NODE8)
    assert b.scenario["engine_version"] == "0.32.0"
    recorded = {loc.split(".", 1)[1] for loc in c.mapped if loc.startswith("engine.")}
    assert set(b.deployment["pools"][0]["engine"]) == recorded


def test_the_cluster_states_the_node_size_and_holds_the_runs_own_gpus():
    c = _classify(_log("'tensor_parallel_size': 1, 'data_parallel_size': 2, 'enable_expert_parallel': True, "
                       "'max_num_seqs': 16, 'max_num_batched_tokens': 4096, 'block_size': 128, 'gpu_memory_utilization': 0.9",
                       RESOLVED.replace("data_parallel_size=1", "data_parallel_size=2")))
    b = _build(c)
    assert b.scenario["cluster"] == {"hardware": "h200", "nodes": 1, "gpus_per_node": 8}
    assert b.scenario["engine_version"] == "0.31.0"
    par = b.deployment["pools"][0]["parallel"]
    assert (par["tp"], par["dp"], par["enable_expert_parallel"]) == (1, 2, True)


RANKS = ("'tensor_parallel_size': 16, 'max_num_seqs': 16, 'max_num_batched_tokens': 4096, 'block_size': 128, "
         "'gpu_memory_utilization': 0.9")


def test_a_chip_whose_catalog_entry_fixes_the_node_size_states_none_and_nodes_follow_from_it():
    b = _build(_classify(_log(RANKS, RESOLVED.replace("tensor_parallel_size=1", "tensor_parallel_size=16"))),
               catalog_node_size=4, node=ir.NodeSize())
    assert b.scenario["cluster"] == {"hardware": "h200", "nodes": 4}
    assert b.reasons == [] and b.node_source is None


def test_a_node_size_the_table_supplied_is_written_and_its_later_record_is_named():
    sub = {"kind": "later_record", "subject": "cluster.gpus_per_node", "detail": "d"}
    node = ir.NodeSize(8, "cluster.gpus_per_node: InferenceX runners.yaml at 303669b0", sub)
    b = _build(_classify(_log(RANKS, RESOLVED.replace("tensor_parallel_size=1", "tensor_parallel_size=16"))), node=node)
    assert b.scenario["cluster"] == {"hardware": "h200", "nodes": 2, "gpus_per_node": 8}
    assert b.node_source == node.provenance and b.substitutions == [sub]


def test_a_node_size_nothing_records_or_two_sources_disagree_on_makes_the_point_g5():
    c = _classify(_log("'max_num_seqs': 16, 'block_size': 128", RESOLVED))
    for code in ("value_not_recorded", "value_conflict"):
        b = _build(c, node=ir.NodeSize(reason={"code": code, "subject": "cluster.gpus_per_node"}))
        assert b.reasons == [f"{code}:cluster.gpus_per_node"] and "gpus_per_node" not in b.scenario["cluster"]


def test_the_launch_configs_node_size_is_read_only_when_it_is_a_positive_integer():
    assert st.recorded_node_size({"resources": {"gpus_per_node": 8}}) == 8
    for bad in (None, {}, {"resources": None}, {"resources": {"gpus_per_node": 0}},
                {"resources": {"gpus_per_node": True}}, {"resources": {"gpus_per_node": "8"}}):
        assert st.recorded_node_size(bad) is None

def test_offload_bytes_are_the_engines_from_the_server_wide_total():
    # cpu_bytes_to_use is server-wide and vLLM divides it by the engine's world size (TP4 here);
    # BLIS's tier is the engine's, so the bytes are per_rank x world.
    args = ("'tensor_parallel_size': 4, 'max_num_seqs': 8, 'max_num_batched_tokens': 4096, 'block_size': 128, "
            "'gpu_memory_utilization': 0.9, "
            "'kv_transfer_config': KVTransferConfig(kv_connector='SimpleCPUOffloadConnector', kv_role='kv_both', "
            "kv_connector_extra_config={'cpu_bytes_to_use': 1000000000003, 'lazy_offload': True})")
    c = _classify(_log(args, RESOLVED.replace("tensor_parallel_size=1", "tensor_parallel_size=4"),
                       extra="SimpleCPUOffloadConnector: role=WORKER, per_rank=232.83 GB, world_size=4\n"))
    b = _build(c)
    assert b.reasons == [], b.reasons
    assert b.deployment["offload"] == {"connector": "SimpleCPUOffloadConnector", "spec": "lazy",
                                       "tiers": [{"tier": "cpu_dram", "bytes": (1000000000003 // 4) * 4}]}


def test_a_connectors_own_options_are_copied_to_the_offload_blocks_connector_options():
    args = ("'tensor_parallel_size': 1, 'max_num_seqs': 8, 'max_num_batched_tokens': 4096, 'block_size': 128, "
            "'kv_transfer_config': KVTransferConfig(kv_connector='MooncakeStoreConnector', kv_role='kv_both', "
            "kv_load_failure_policy='recompute', kv_connector_extra_config={'cpu_bytes_to_use': 1073741824, "
            "'load_async': False, 'enable_cross_layers_blocks': True})")
    b = _build(_classify(_log(args)))
    assert b.reasons == [], b.reasons
    assert b.deployment["offload"]["connector_options"] == {
        "enable_cross_layers_blocks": True, "kv_load_failure_policy": "recompute", "load_async": False}


def test_offload_bytes_that_disagree_with_the_logged_per_rank_figure_conflict():
    args = ("'tensor_parallel_size': 4, 'max_num_seqs': 8, 'max_num_batched_tokens': 4096, 'block_size': 128, "
            "'gpu_memory_utilization': 0.9, "
            "'kv_transfer_config': KVTransferConfig(kv_connector='SimpleCPUOffloadConnector', "
            "kv_connector_extra_config={'cpu_bytes_to_use': 1000000000000})")
    c = _classify(_log(args, RESOLVED.replace("tensor_parallel_size=1", "tensor_parallel_size=4"),
                       extra="SimpleCPUOffloadConnector: role=WORKER, per_rank=50.00 GB, world_size=4\n"))
    b = _build(c)
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
    assert "client_scenario_not_replayable:system_idle_gap_cap_seconds" in r.reasons


# ------------------------------------------------------------------ support checks

# The scorer reads catalog identities through `blis catalog resolve` (design §5). This fake
# answers it as inference-sim 2eff3576 does: a model by entry name or by the source repository
# its model.yaml names (without regard to case), a chip by hardware/<name>.yaml; null otherwise;
# a repository two entries claim exits 1. Every argv is recorded in <blis>.saw.
FAKE_RESOLVE = """#!/usr/bin/env python3
import json, sys
MODELS, CHIPS = {models!r}, {chips!r}
a = sys.argv[1:]
open(sys.argv[0] + ".saw", "a").write(json.dumps(a) + "\\n")
assert a[:3] == ["catalog", "resolve", "--catalog"] and a[-1] == "--json", a
kind, q = a[4], a[5]
if kind == "--model":
    hits = sorted({{n for n, r in MODELS.items() if n == q or r.lower() == q.lower()}})
    if len(hits) > 1:
        sys.stderr.write(f"model {{q!r}} is the source repository of {{len(hits)}} catalog entries\\n")
        sys.exit(1)
    ident = hits[0] if hits else None
else:
    ident = q if q in CHIPS else None
print(json.dumps({{"query": q, "identity": ident, "reason": "fake"}}))
"""


def _catalog(tmp: Path, models=None, chips=("h200", "tpuv7")) -> sp.Catalog:
    models = models or {"dsv41": "deepseek-ai/DeepSeek-V4.1-Flash", "mm3": "MiniMaxAI/MiniMax-M3"}
    for name, spec in (("dsv41", "dspark"), ("mm3", "minimax_m3_mtp")):
        (tmp / "models" / name).mkdir(parents=True)
        (tmp / "models" / name / "graph.yaml").write_text(f"global: {{}}\nspeculator:\n  method: {spec}\n")
    blis = tmp / "blis"
    blis.write_text(FAKE_RESOLVE.format(models=models, chips=list(chips)))
    blis.chmod(0o755)
    return sp.Catalog(blis=str(blis), root=tmp)


def _asked(cat: sp.Catalog) -> list[list[str]]:
    saw = Path(cat.blis + ".saw")
    return [json.loads(x) for x in saw.read_text().splitlines()] if saw.exists() else []


def test_support_matches_the_checkpoint_then_its_base_model():
    cat = _catalog(Path(tempfile.mkdtemp()))
    s = sp.check(cat, {"h200"}, checkpoints=["deepseek-ai/DeepSeek-V4.1-Flash"], base_models={}, hardware="h200",
                 spec_method="dspark")
    assert (s.model, s.matched_by, s.chip, s.reasons) == ("dsv41", "checkpoint", "h200", [])
    s = sp.check(cat, {"h200"}, checkpoints=["nvidia/MiniMax-M3-NVFP4"],
                 base_models={"nvidia/MiniMax-M3-NVFP4": "MiniMaxAI/MiniMax-M3"}, hardware="h200", spec_method=None)
    assert (s.model, s.matched_by) == ("mm3", "base_model")


def test_support_asks_blis_catalog_resolve_with_the_catalog_and_caches_each_answer():
    cat = _catalog(Path(tempfile.mkdtemp()))
    for _ in range(2):
        sp.check(cat, {"h200"}, checkpoints=["deepseek-ai/DeepSeek-V4.1-Flash"], base_models={}, hardware="h200",
                 spec_method=None)
    root = str(cat.root)
    assert _asked(cat) == [["catalog", "resolve", "--catalog", root, "--model", "deepseek-ai/DeepSeek-V4.1-Flash", "--json"],
                           ["catalog", "resolve", "--catalog", root, "--chip", "h200", "--json"]]


def test_support_refuses_an_unknown_model_part_or_drafter():
    cat = _catalog(Path(tempfile.mkdtemp()))
    s = sp.check(cat, {"h200"}, checkpoints=["org/unknown"], base_models={}, hardware="h200", spec_method=None)
    assert s.reasons == ["model_not_in_catalog"]
    s = sp.check(cat, {"h200"}, checkpoints=["deepseek-ai/DeepSeek-V4.1-Flash"], base_models={}, hardware="tpuv7",
                 spec_method="dspark")
    assert s.reasons == ["hardware_no_coefficients"]
    # A part the registry has coefficients for but the catalog has no entry of.
    s = sp.check(cat, {"h200", "mi355x"}, checkpoints=["deepseek-ai/DeepSeek-V4.1-Flash"], base_models={},
                 hardware="mi355x", spec_method="dspark")
    assert (s.chip, s.reasons) == (None, ["hardware_no_coefficients"])
    s = sp.check(cat, {"h200"}, checkpoints=["MiniMaxAI/MiniMax-M3"], base_models={}, hardware="h200",
                 spec_method="eagle3")
    assert s.reasons == ["drafter_not_in_catalog:eagle3"]


def test_a_repository_two_catalog_entries_claim_stops_the_run():
    import blis_commands as bc
    cat = _catalog(Path(tempfile.mkdtemp()), models={"dsv41": "org/m", "mm3": "org/m"})
    with pytest.raises(bc.CommandError, match="source repository of 2 catalog entries"):
        sp.check(cat, {"h200"}, checkpoints=["org/m"], base_models={}, hardware="h200", spec_method=None)


def test_catalog_resolve_output_of_another_shape_is_refused():
    import blis_commands as bc
    tmp = Path(tempfile.mkdtemp())
    blis = tmp / "blis"
    for out, match in (('{"query": "h200", "identity": "h200"}', "not an object of query, identity and reason"),
                       ('{"query": "b200", "identity": "h200", "reason": ""}', "want query 'h200'"),
                       ("h200", "printed no JSON")):
        blis.write_text(f"#!/bin/sh\necho '{out}'\n")
        blis.chmod(0o755)
        with pytest.raises(bc.CommandError, match=match):
            bc.catalog_resolve(str(blis), str(tmp), chip="h200")


def test_an_inferencex_hardware_label_names_one_catalog_part():
    cat = _catalog(Path(tempfile.mkdtemp()), chips=("b200", "gb200-nvl72", "a100-80", "a100-sxm"))
    parts = {"b200", "gb200-nvl72", "a100-80", "a100-sxm"}
    assert sp.catalog_part(cat, parts, "b200") == "b200"                 # the part of that name
    assert sp.catalog_part(cat, parts, "gb200") == "gb200-nvl72"         # its one <label>-variant
    assert sp.catalog_part(cat, parts, "a100") is None                   # two variants: not guessed
    assert sp.catalog_part(cat, parts, "mi355x") is None                 # none
    assert sp.catalog_part(cat, parts - {"gb200-nvl72"}, "gb200") is None   # no coefficients for it


def test_the_rows_gpu_count_is_read_in_inferencex_terms():
    import score as sc

    class C:
        def __init__(self, **par):
            self.mapped = {f"parallel.{k}": (None, v, None) for k, v in par.items()}
    row = lambda **kw: {"disagg": False, "decode_dp_attention": False, **kw}
    t = sc._row_topology_vs_run
    # the plain case: tp 8 on 8 GPUs
    assert t(row(decode_tp=8, decode_ep=1, num_decode_gpu=8), C(tp=8, dp=1)) == []
    # MiniMax-M2.5 h100 TP8/EP8 (row 419573): the row counts 64 (tp x ep); the log runs 8 GPUs
    assert t(row(decode_tp=8, decode_ep=8, num_decode_gpu=64), C(tp=8, dp=1)) == []
    # and the same layout counted correctly
    assert t(row(decode_tp=8, decode_ep=8, num_decode_gpu=8), C(tp=8, dp=1)) == []
    # DeepSeek-V4-Pro h200 "TP 8, DP attention" (row 435219): vLLM logs tp 1, dp 8
    assert t(row(decode_tp=8, decode_ep=8, decode_dp_attention=True, num_decode_gpu=64), C(tp=1, dp=8)) == []
    # a different run: the row says 8 GPUs, the log ran 4
    assert t(row(decode_tp=8, decode_ep=1, num_decode_gpu=8), C(tp=4, dp=1)) == ["conflict:num_gpus", "conflict:tp"]
    # a tp x ep count that doesn't match the log's GPUs either is still a conflict
    assert t(row(decode_tp=8, decode_ep=8, num_decode_gpu=64), C(tp=4, dp=1)) == ["conflict:num_gpus", "conflict:tp"]
    # without DP attention, a row tp equal to tp x dp isn't the same layout
    assert t(row(decode_tp=8, decode_ep=1, num_decode_gpu=8), C(tp=1, dp=8)) == ["conflict:tp"]


def _graded(*, image="vllm/vllm-openai:v0.32.0", banner="0.32.0", subs=(), requests=None, reasons=(),
            scored=True, build_match="exact"):
    import score as sc
    o = sc.Outcome(point_id="p" * 64, identity={}, row={"image": image}, reasons=list(reasons),
                   build={"image": image, "match": build_match}, banner=banner, subs=list(subs))
    if scored:
        o.fidelity = {"build": o.build, "args": [], "resolved": [],
                      **({"requests": requests} if requests else {})}
        o.csv_row = [None] * 12
    sc.grade_outcome(o, "0.32.0")
    return o


APPROX = {"kind": "estimated", "subject": "quantization", "detail": "left unset"}
DEFAULTED = {"kind": "estimated", "subject": "max_num_seqs", "detail": "not recorded; left unset"}


UNCHECKED = [{"kind": k, "subject": "not checked", "detail": f"{k} is not graded yet"}
             for k in ("coefficient_range", "kernel_hash", "resolved_differs", "value_class")]


def test_no_point_is_g1_while_four_of_the_g1_conditions_are_not_graded():
    # Design 11.3's G1 also requires a kernel hash per library, no extrapolated or unidentified
    # coefficient, a value class per modelled field, and no resolved value that differs. No source
    # carries these yet, so each scored point names them (grade.UNCHECKED_KINDS) and is G2 at best.
    o = _graded()
    assert o.fidelity["grade"] == "G2" and o.csv_row[9] == "G2"
    assert o.fidelity["substitutions"] == UNCHECKED
    assert o.fidelity["run_release"] == "0.32.0"
    # build.match is not a grade input: the build decides G2 or G4 through its release alone.
    assert _graded(build_match="estimated").fidelity["grade"] == "G2"


def test_every_estimate_and_client_difference_is_named_and_makes_the_point_g2():
    gap = {"kind": "client_difference", "subject": "send_gap", "detail": "x"}
    o = _graded(subs=[APPROX, DEFAULTED], requests={"differences": [gap]})
    assert o.fidelity["grade"] == "G2"
    assert [(s["kind"], s["subject"]) for s in o.fidelity["substitutions"]] == [
        ("client_difference", "send_gap"), ("coefficient_range", "not checked"), ("estimated", "max_num_seqs"),
        ("estimated", "quantization"), ("kernel_hash", "not checked"), ("resolved_differs", "not checked"),
        ("value_class", "not checked")]
    assert next(s for s in o.fidelity["substitutions"] if s["subject"] == "quantization")["detail"] == "left unset"


def test_another_release_or_a_nightly_build_is_g4_and_says_so():
    o = _graded(image="vllm/vllm-openai:v0.25.0", banner="0.25.0")
    assert o.fidelity["grade"] == "G4" and o.fidelity["run_release"] == "0.25.0"
    assert {s["kind"] for s in o.fidelity["substitutions"]} == {
        "other_release", "ported_functions_unpublished", *(u["kind"] for u in UNCHECKED)}
    o = _graded(image="vllm/vllm-openai:nightly-abc", banner="0.30.1rc1.dev493+gac9126e58")
    assert o.fidelity["grade"] == "G4" and o.fidelity["run_release"] is None
    assert [s["kind"] for s in o.fidelity["substitutions"]] == [
        "coefficient_range", "kernel_hash", "nightly_or_custom", "resolved_differs", "value_class"]


def test_a_point_not_scored_is_g5_with_every_reason_on_the_closed_list():
    import grade as gr
    o = _graded(scored=False, reasons=["drafter_not_in_catalog:eagle3", "router_unsupported:vllm-router"])
    assert o.g5 == {"code": "router_unsupported", "subject": "vllm-router"}
    assert o.g5_reasons == [{"code": "not_in_catalog", "subject": "eagle3"},
                            {"code": "router_unsupported", "subject": "vllm-router"}]
    with pytest.raises(gr.GradeError):
        _graded(scored=False, reasons=[])


def test_a_run_fault_is_never_graded():
    for fault in ("blis_refused:timeout", "setting_differs:max_num_seqs"):
        o = _graded(reasons=[fault, "model_not_in_catalog"], scored=False)
        assert o.faults == [fault] and o.g5 is None and o.fidelity is None


def test_a_build_never_refuses_a_point_at_pull_time():
    import pull as pl
    src = (HERE / "pull.py").read_text()
    assert "b.reasons" not in src and 'entry["build"] = b.record()' in src
    assert not hasattr(__import__("build").Build(image="x"), "reasons")


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


def test_several_uploads_for_one_point_are_ambiguous_not_guessed():
    arts = [_A(1, "bmk_" + RF, "2026-10-01T10:00:00Z"),
            _A(2, "server_logs_" + RF, "2026-10-01T10:00:05Z"), _A(3, "server_logs_" + RF, "2026-10-01T10:00:09Z")]
    j = art.join({"recipe_fingerprint": "f" * 64, "conc": 8}, arts,
                 lambda a: {"recipe_fingerprint": "f" * 64, "conc": 8} if a.id == 1 else None, agentic=False)
    assert j.reasons == ["artifact_unmatched:several_server_logs"]
    arts = [_A(1, "bmk_" + RF, "2026-10-01T10:00:00Z"),
            _A(2, "server_logs_" + RF, "2026-10-01T09:00:00Z"), _A(3, "server_logs_" + RF, "2026-10-01T09:30:00Z")]
    j = art.join({"recipe_fingerprint": "f" * 64, "conc": 8}, arts,
                 lambda a: {"recipe_fingerprint": "f" * 64, "conc": 8} if a.id == 1 else None, agentic=False)
    assert j.reasons == ["artifact_unmatched:several_server_logs"]


def test_unreadable_archive_members_raise_instead_of_being_skipped():
    try:
        list(art.iter_files(_zip({"bad.tar.gz": b"\x1f\x8b" + b"not gzip"})))
    except art.Unreadable:
        pass
    else:
        raise AssertionError("a corrupt member was skipped")
    try:
        art.find_launch_config([("c.yaml", f"benchmark: {{env: {{RESULT_FILENAME: {RF}}}\n  : [".encode())], RF)
    except ValueError:
        return
    raise AssertionError("an unparseable launch config was treated as absent")


def test_an_oversized_member_the_point_does_not_need_is_skipped_not_fatal():
    # PR #32 review: a 2.1 GB server_metrics_export.json beside the client export sank the whole
    # agentic upload. The cap is lowered here so the test needs no 2 GiB of memory.
    import pull as pl
    old = art._MAX_MEMBER
    art._MAX_MEMBER = 64
    try:
        export = b'{"records": []}'
        blob = _zip({"profile_export_aiperf.json": export, "server_metrics_export.json": b"{" + b" " * 200 + b"}"})
        entry: dict = {}
        files = pl.read_needed(blob, entry, lambda o: o.path.rsplit("/", 1)[-1] in pl.AGENTIC_FILES)
        assert [p for p, _ in files] == ["profile_export_aiperf.json"]
        assert entry["skipped_members"] == ["server_metrics_export.json (202 bytes)"]
        # the needed member oversized: the artifact is unreadable, as before
        big = _zip({"profile_export_aiperf.json": b"{" + b" " * 200 + b"}"})
        for blob, needed in ((big, lambda o: True), (_zip({"nested.zip": _zip({"a": b"x" * 200})}), lambda o: False)):
            try:
                pl.read_needed(blob, {}, needed)
            except art.Unreadable:
                continue
            raise AssertionError("an oversized member the point needs (or an archive) was skipped")
        # without an `oversized` list, iter_files still refuses
        try:
            list(art.iter_files(_zip({"x.json": b" " * 200})))
        except art.Unreadable:
            pass
        else:
            raise AssertionError("iter_files skipped silently")
        # a tar member too
        entry = {}
        files = pl.read_needed(_targz({"./log.txt": LOG, "./m.json": b" " * 200}), entry, lambda o: False)
        assert [p for p, _ in files] == ["log.txt"] and entry["skipped_members"] == ["m.json (200 bytes)"]
    finally:
        art._MAX_MEMBER = old


def test_an_escaped_quote_inside_a_string_does_not_end_it():
    # PR #32 review: `\\'` used to close the quote early, so a later brace was counted.
    text = "non-default args: {'a': 'it\\'s {not} a brace', 'b': 1} tail }"
    got = st._balanced(text, text.index("{"))
    assert got == "{'a': 'it\\'s {not} a brace', 'b': 1}", got


def test_a_sweep_is_one_curve_of_inferencex_rows():
    # PR #31 review: one InferenceX workflow ran DeepSeek-V4-Pro b200 tp8 with and without MTP,
    # and MiniMax-M2.5 b300 tp2 with and without DP attention; the sweep id joined each pair, so
    # two points sat at one concurrency. Rows of one curve differ only in per-point fields.
    import score as sc
    row = {"curve_workflow_run_id": "2151", "model": "dsv4pro", "hardware": "b200", "conc": 1, "id": "1",
           "spec_method": "none", "decode_dp_attention": False, "recipe_fingerprint": "a" * 64,
           "metrics": {"mean_ttft": 1.0}}
    same_curve = {**row, "conc": 2, "id": "2", "recipe_fingerprint": "b" * 64, "metrics": {"mean_ttft": 2.0}}
    sid = lambda r: sc.sweep_id(r, "scen", "1k1k")  # noqa: E731
    assert sid(row) == sid(same_curve) and sid(row).startswith("2151|scen|1k1k|")
    assert sid(row) != sid({**row, "spec_method": "mtp"})
    assert sid(row) != sid({**row, "decode_dp_attention": True})


def test_two_points_left_at_one_concurrency_in_a_sweep_get_a_sweep_each():
    import score as sc
    o = lambda pid, conc, recipe: sc.Outcome.__new__(sc.Outcome)  # noqa: E731
    outs = []
    for pid, conc, recipe in (("a", 1, "row:1"), ("b", 2, "row:2"), ("c", 2, "row:3")):
        x = o(pid, conc, recipe)
        x.identity = {"conc": conc}
        x.point_id = recipe
        x.facets = {"sweep_id": "s"}
        outs.append(x)
    sc.split_repeated_sweeps(outs)
    assert [x.facets["sweep_id"] for x in outs] == ["s|row:1", "s|row:2", "s|row:3"]   # the point ids' first 12
    clean = [outs[0]]
    clean[0].facets["sweep_id"] = "t"
    sc.split_repeated_sweeps(clean)
    assert clean[0].facets["sweep_id"] == "t"


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
                      # every other serving stack InferenceX reports is pulled too
                      *[{"id": str(10 + i), "model": "glm5", "framework": f, "date": "2026-10-21"}
                        for i, f in enumerate(("sglang", "trt", "dynamo-vllm"))]]}

    def fetch(url):
        path = url[len(api.BASE):]
        if path.startswith("/api/v1/benchmarks?model="):
            import urllib.parse
            return gzip.compress(json.dumps(rows[urllib.parse.unquote(path.split("=", 1)[1])]).encode())
        return site[path]

    p = api.pull(fetch, today=date(2026, 10, 23), window_days=7)
    assert [r["id"] for r in p.rows] == ["2", "3", "10", "11", "12"]   # by date, not curve_date; every framework
    assert p.unnamed_slugs == ["newmodel"]                  # reported, not guessed


def test_in_window_is_exactly_n_calendar_days_both_ends_included():
    # Discussion #15: today-179 <= date <= today is 180 calendar days. The window spans exactly
    # N days -- the old `start = today - N` bug spanned N+1.
    today = date(2026, 10, 23)
    start, end = api.window_bounds(today, 180)
    assert (start, end) == (date(2026, 4, 27), today)       # 2026-04-27 .. 2026-10-23 == 180 days
    assert (end - start).days == 179                        # inclusive span is N-1 days apart
    assert api.in_window("2026-04-27", today, 180)          # today-179: the oldest day kept
    assert not api.in_window("2026-04-26", today, 180)      # today-180: one day too old, dropped
    assert api.in_window("2026-10-23", today, 180)          # today: kept
    assert not api.in_window("2026-10-24", today, 180)      # after today: waits for a later run
    assert not api.in_window("not-a-date", today, 180)      # unparseable: never in the window


def test_pull_window_boundary_keeps_today_minus_179_drops_today_minus_180():
    # The pull uses the same in_window, so its window is exactly 180 days too.
    today = date(2026, 10, 23)
    site = {"/": b'<script src="/_next/static/c/a.js"></script>',
            "/_next/static/c/a.js": b'x={m:"M"}',
            "/api/v1/availability": json.dumps([{"model": "m", "framework": "vllm", "date": "2026-10-20"}]).encode()}
    rows = {"M": [{"id": "keep", "model": "m", "framework": "vllm", "date": "2026-04-27"},   # today-179
                  {"id": "drop", "model": "m", "framework": "vllm", "date": "2026-04-26"}]}  # today-180

    def fetch(url):
        path = url[len(api.BASE):]
        if path.startswith("/api/v1/benchmarks?model="):
            return gzip.compress(json.dumps(rows["M"]).encode())
        return site[path]

    p = api.pull(fetch, today=today, window_days=180)
    assert [r["id"] for r in p.rows] == ["keep"]
    assert p.window == ("2026-04-27", "2026-10-23")


def test_run_and_attempt_from_run_url():
    assert api.run_of({"run_url": "https://github.com/o/r/actions/runs/123/attempts/2"}) == ("123", 2)
    assert api.run_of({"run_url": "https://github.com/o/r/actions/runs/123"}) == ("123", 1)
    assert api.run_of({"run_url": None}) is None


# ------------------------------------------------------------------ real logs

LOGS = HERE / "testdata" / "logs"


def test_every_value_a_real_log_records_is_read_and_copied_verbatim():
    """One excerpt per InferenceX deployment shape seen in the 2026-09-20..10-23 window (the
    lines the extractor reads, verbatim). Each reads whole, and every value it records that the
    scenario has a place for is copied there unchanged, under the engine block's name (COV-3).
    The field list here is every recorded path, modelled, so nothing is estimated or refused."""
    names = sorted(p.name[:-len(".server-log.txt")] for p in LOGS.glob("*.server-log.txt"))
    assert len(names) >= 40
    for name in names:
        launch_path = LOGS / f"{name}.launch.json"
        launch = json.loads(launch_path.read_text()) if launch_path.exists() else None
        readings, problems = st.read_all((LOGS / f"{name}.server-log.txt").read_text(), launch)
        assert problems == [], (name, problems)
        merged = st.merge(readings, DEFAULTS)
        everything = fl.parse(json.dumps({"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.31.0"},
            "fields": sorted(({"name": p[4:] if p.startswith("env.") else p,
                               "source": "env" if p.startswith("env.") else "config", "status": "modelled",
                               "evidence": {"traces": ["t"]}, "estimation": {"rule": "none"}} for p in merged),
                             key=lambda f: (f["name"], f["source"]))}))
        d = st.decide(merged, everything)
        for loc, (path, value) in d.mapped.items():
            s_ = merged[path]
            assert st._canon(value) == st._canon(st._yaml_value(s_.value)) or loc == "engine.frontend", (name, path)
            # The passed value where the run passed one; the resolved one only where it passed none.
            passed = [v for x in st.PASSED for v in readings[x].values.get(path, []) if v is not None]
            assert s_.source in st.PASSED or not passed, (name, path)


def test_a_whole_printed_config_field_at_the_default_of_the_runs_release_is_not_set():
    """Real log excerpt (v0.32.0 banner): AttentionConfig prints use_prefill_decode_attention
    False and use_fp4_indexer_cache False, inductor_compile_config prints its entries. None is
    set by the run; none may yield field_not_in_release."""
    log = _LOG_V32
    readings, problems = st.read_all(log, None)
    assert problems == []
    assert "attention_config.use_prefill_decode_attention" in readings["args"].values
    defaults = st.defaults_for("0.32.0", DEFAULTS, st.vllm_defaults_release())
    merged = st.merge(readings, defaults)
    assert not merged["attention_config.use_prefill_decode_attention"].requested
    assert not merged["compilation_config.inductor_compile_config.combo_kernels"].requested
    assert [r for r in st.decide(merged, FIELDS).reasons if r.startswith("field_not_in_release")] == []


def test_defaults_of_another_release_judge_nothing_as_set():
    assert st.defaults_for("0.23.1rc1.dev1403+g4080263bb", DEFAULTS, "0.32.0") == {}
    assert st.defaults_for(None, DEFAULTS, "0.32.0") == {}
    assert st.defaults_for("0.32.0", DEFAULTS, "0.32.0") is DEFAULTS


def test_a_launch_config_stated_field_absent_from_the_release_is_field_not_in_release():
    launch = {"roles": {"agg": {"args": {"attention-config": '{"use_prefill_decode_attention": false}'}}}}
    readings, _ = st.read_all(_LOG_V32, launch)
    merged = st.merge(readings, st.defaults_for("0.32.0", DEFAULTS, "0.32.0"))
    assert merged["attention_config.use_prefill_decode_attention"].requested
    assert "field_not_in_release:attention_config.use_prefill_decode_attention" in st.decide(merged, FIELDS).reasons


_LOG_V32 = (
    "INFO [api_utils.py:273] non-default args: {'model': 'org/m', 'tensor_parallel_size': 1, "
    "'attention_config': AttentionConfig(backend=None, flash_attn_version=None, "
    "use_prefill_decode_attention=False, use_fp4_indexer_cache=False, indexer_kv_dtype='fp8'), "
    "'compilation_config': {'mode': <CompilationMode.NONE: 0>, 'inductor_compile_config': "
    "{'enable_auto_functionalized_v2': False, 'combo_kernels': True}}}\n"
    "INFO [core.py:116] Initializing a V1 LLM engine (v0.32.0) with config: model='m', "
    "tensor_parallel_size=1, pipeline_parallel_size=1, data_parallel_size=1, quantization=fp8, "
    "kv_cache_dtype=auto, enable_prefix_caching=True\n")



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
