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
DEFAULTS, _ = st.load_vllm_defaults()

# A resolved engine-config line as vLLM v0.31.0 prints it (every engine log has one).
RESOLVED = ("model='m', tensor_parallel_size=1, pipeline_parallel_size=1, data_parallel_size=1, "
            "quantization=fp8, kv_cache_dtype=auto, enable_prefix_caching=True, "
            "compilation_config={'mode': <CompilationMode.NONE: 0>, 'cudagraph_mode': <CUDAGraphMode.FULL_AND_PIECEWISE: (2, 1)>}")


def _log(args: str, resolved: str = RESOLVED, extra: str = "") -> str:
    out = f"INFO [api_utils.py:286] non-default args: {{{args}}}\n"
    if resolved is not None:
        out += f"INFO [core.py:129] Initializing a V1 LLM engine (v0.30.1rc1.dev493+gac9126e58) with config: {resolved}\n"
    return out + extra


def _classify(log: str, launch=None, extra_readings=None):
    readings, problems = st.read_all(log, launch)
    assert problems == [], problems
    readings.update(extra_readings or {})
    return st.classify(st.merge(readings, POLICY, DEFAULTS), POLICY, DEFAULTS)


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
            assert e.get("note") and "upstream" not in e, path
            # What BLIS used must come from BLIS (a source score.py reads) or be a fixed
            # switch value; never left for a placeholder.
            src = e.get("blis_from")
            assert (src is None) != ("approximate_as" not in e), path
            assert src is None or src == "priced.index_cache" or src.startswith("resolved."), path
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
    c = _classify(_log("'compilation_config': {'mode': <CompilationMode.VLLM_COMPILE: 3>}"))
    assert c.reasons == []
    # VLLM_COMPILE (vLLM's default) and NONE are both what BLIS prices; another mode isn't.
    c = _classify(_log("'max_num_seqs': 1", RESOLVED.replace("CompilationMode.NONE: 0", "CompilationMode.VLLM_COMPILE: 3")))
    assert c.reasons == []
    c = _classify(_log("'max_num_seqs': 1", RESOLVED.replace("CompilationMode.NONE: 0", "CompilationMode.STOCK_TORCH_COMPILE: 1")))
    assert c.reasons == ["setting_not_modelled:compilation_config.mode"]


def test_a_setting_the_run_asked_for_and_blis_cannot_state_is_not_modelled():
    c = _classify(_log("'prefill_schedule_interval': 32"))
    assert c.reasons == ["setting_not_modelled:prefill_schedule_interval"]
    assert next(a for a in c.args if a["arg"] == "prefill_schedule_interval")["match"] == "absent_in_blis"


def test_a_field_printed_at_its_default_is_not_a_request():
    # vLLM prints a config object whole: its defaults are not settings the run chose.
    c = _classify(_log("'attention_config': AttentionConfig(backend=None, use_trtllm_attention=None, "
                       "indexer_kv_dtype='auto', indexer_sparse_logits=False)"))
    assert c.reasons == [] and not c.approximated


def test_the_indexer_cache_dtype_is_approximated_with_its_note():
    c = _classify(_log("'attention_config': AttentionConfig(indexer_kv_dtype='mxfp4', indexer_sparse_logits=True)"))
    assert c.reasons == [] and c.approximated
    rec = {a["arg"]: a for a in c.args}
    assert rec["attention_config.indexer_kv_dtype"]["match"] == "approximated"
    assert rec["attention_config.indexer_kv_dtype"]["note"] and "upstream" not in rec["attention_config.indexer_kv_dtype"]
    assert rec["attention_config.indexer_sparse_logits"]["measured"] is True


def test_a_weight_format_blis_cannot_state_is_estimated_as_the_nearest_it_prices():
    import score as sc
    for run, blis in (("mxfp8", "fp8"), ("gpt_oss_mxfp4", "mxfp4"), ("modelopt_mixed", "modelopt_fp4")):
        c = _classify(_log("'max_num_seqs': 1", RESOLVED.replace("quantization=fp8", f"quantization={run}")))
        assert c.approximated and c.reasons == [], run
        assert c.mapped["engine.quantization"][1] == blis, run
        a = next(x for x in c.args if x["arg"] == "quantization")
        assert a["measured"] == run and a["note"], run
        # the diff reads the scenario back: written as the estimate, it's "approximated"
        args = [dict(a)]
        assert sc._diff_args(args, {"pools": [{"engine": {"quantization": blis}}]}, None) == []
        assert args[0]["match"] == "approximated" and args[0]["blis"] == blis and "_approximated" not in args[0]
        # a scenario that lost it is still a refusal
        assert sc._diff_args([dict(a)], {"pools": [{"engine": {}}]}, None) == ["setting_differs:quantization"]
    # a format BLIS prices is passed as it is
    c = _classify(_log("'max_num_seqs': 1", RESOLVED))
    assert not c.approximated and c.mapped["engine.quantization"][1] == "fp8"


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


def test_a_fusion_pass_at_vllms_own_default_for_the_part_is_inert():
    log = lambda tp, v: _log(f"'tensor_parallel_size': {tp}, 'compilation_config': {{'pass_config': {{'fuse_allreduce_rms': {v}}}}}")
    k = "compilation_config.pass_config.fuse_allreduce_rms"

    def cls(tp, v, family):
        c = st.classify(st.merge(st.read_all(log(tp, v), None)[0], POLICY, DEFAULTS), POLICY, DEFAULTS, family=family)
        return c.reasons, next(a["match"] for a in c.args if a["arg"] == k)
    # on at tp > 1 on Blackwell / Hopper: vLLM's own default, so nothing differs
    assert cls(4, True, 10) == ([], "inert") and cls(8, True, 9) == ([], "inert")
    # off where vLLM would turn it on, or on where it wouldn't (tp 1, an Ampere part): a choice
    assert cls(4, False, 10) == ([f"setting_not_modelled:{k}"], "absent_in_blis")
    # tp 1: the pass can't run (vLLM: "AllReduce fusion pass is disabled for tp_size <= 1"),
    # so any value is the engine vLLM ran (gpt-oss-120b b200 v0.22.0, point 033685898e93569f)
    assert cls(1, True, 10) == ([], "inert") and cls(1, False, 10) == ([], "inert")
    assert cls(4, True, 8) == ([f"setting_not_modelled:{k}"], "absent_in_blis")
    # the part's architecture unknown (an AMD part has no ComputeCapability): never assumed
    assert cls(4, True, None) == ([f"setting_not_modelled:{k}"], "absent_in_blis")


def test_chunked_prefill_off_is_refused_whatever_the_budget():
    # vLLM holds a prompt that doesn't fit the budget LEFT after decodes; BLIS splits it. A run
    # with chunking off always has max_num_batched_tokens >= max_model_len (vLLM refuses to start
    # otherwise), so that condition can't make it inert.
    for mbt, mml in ((16384, 9472), (9472, 9472)):
        c = _classify(_log(f"'enable_chunked_prefill': False, 'max_num_batched_tokens': {mbt}, 'max_model_len': {mml}"))
        assert c.reasons == ["setting_not_modelled:enable_chunked_prefill"], (mbt, mml)


def test_an_env_var_vllm_warns_is_deprecated_is_read_as_set():
    # gpt-oss-120b h200 v0.22.0 (point 0004425a4c559ee3): no launch config, but vLLM printed
    log = ("(EngineCore pid=1) /usr/lib/python3/vllm/envs.py:358: FutureWarning: VLLM_MXFP4_USE_MARLIN is "
           "deprecated and will be removed in v0.23. Use --moe-backend instead.\n")
    r = st.read_engine_lines(log + log)
    assert r.values["env.VLLM_MXFP4_USE_MARLIN"] == [True]           # once, however often it's printed
    # an MoE-kernel selector: estimated as BLIS's default MoE kernel, not refused (the user's call)
    c = _classify(_log("'tensor_parallel_size': 1") + "\n" + log)
    assert c.reasons == [] and c.approximated
    a = next(x for x in c.args if x["arg"] == "env.VLLM_MXFP4_USE_MARLIN")
    assert (a["measured"], a["blis"], a["match"]) == (True, False, "approximated") and a["note"]
    # an unknown deprecated variable is unclassified, never silently passed
    c = _classify(_log("'tensor_parallel_size': 1") + "\n" + log.replace("VLLM_MXFP4_USE_MARLIN", "VLLM_SOMETHING_NEW"))
    assert "setting_not_modelled:env.VLLM_SOMETHING_NEW" in c.reasons


def test_custom_ops_all_is_vllms_own_resolution_when_the_engine_runs_uncompiled():
    def cls(ops, mode):
        c = _classify(_log(f"'compilation_config': {{'custom_ops': {ops}}}", RESOLVED.replace(
            "CompilationMode.NONE: 0", mode)))
        return c.reasons
    k = "setting_not_modelled:compilation_config.custom_ops"
    # mode NONE: vLLM appends "all" itself (config/vllm.py:1788-1795), so ['all'] changes nothing
    # (DeepSeek-V4-Pro b200/b300 v0.25, e.g. point 00870be2cd0c6428)
    assert cls("['all']", "CompilationMode.NONE: 0") == []
    # compiled with inductor, vLLM appends "none": ['all'] is a choice
    assert k in cls("['all']", "CompilationMode.VLLM_COMPILE: 3")
    # any other list picks kernels at any mode
    assert k in cls("['+rotary_embedding']", "CompilationMode.NONE: 0")

def test_moe_backend_is_mapped_to_its_blis_field():
    c = _classify(_log("'kernel_config': KernelConfig(moe_backend='deep_gemm_mega_moe')"))
    assert c.mapped["engine.moe_backend"][1] == "deep_gemm_mega_moe"


def test_the_rust_frontend_line_maps_to_engine_frontend():
    c = _classify(_log("'max_num_seqs': 1", extra="INFO Launching Rust frontend: /usr/bin/vllm\n"))
    assert c.mapped["engine.frontend"][1] is True
    launch = {"roles": {"agg": {"args": {"max-num-seqs": 1}, "env": {"VLLM_USE_RUST_FRONTEND": "true"}}}}
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
    assert c.reasons == ["setting_not_modelled:prefill_schedule_interval"]


def test_with_a_launch_config_an_args_only_request_still_counts():
    launch = {"roles": {"agg": {"args": {"max-num-seqs": 8}}}}
    c = _classify(_log("'max_num_seqs': 8, 'enforce_eager': True"), launch)
    assert "setting_not_modelled:enforce_eager" in c.reasons


def test_a_log_missing_its_args_or_resolved_line_is_unreadable():
    _, problems = st.read_all(_log("'max_num_seqs': 8", resolved=None), None)
    assert problems == ["server log has no resolved engine-config line"]
    _, problems = st.read_all("INFO [core.py:129] Initializing a V1 LLM engine (v0.31.0) with config: " + RESOLVED + "\n", None)
    assert problems == ["server log has no `non-default args` line"]


def test_a_new_field_under_a_wildcard_entry_refuses_when_set():
    c = _classify(_log("'attention_config': AttentionConfig(backend=None, flex_attn_block_m=64)"))
    assert c.reasons == ["unclassified_arg:attention_config.flex_attn_block_m"]
    c = _classify(_log("'attention_config': AttentionConfig(backend=None, mla_prefill_backend='TRTLLM_RAGGED')"))
    assert c.reasons == ["setting_not_modelled:attention_config.mla_prefill_backend"]
    c = _classify(_log("'compilation_config': {'brand_new_knob': 7}"))
    assert c.reasons == ["unclassified_arg:compilation_config.brand_new_knob"]
    # The same fields at vLLM's default are not requests.
    c = _classify(_log("'attention_config': AttentionConfig(backend=None, flex_attn_block_m=None)"))
    assert c.reasons == []


def test_a_none_in_an_earlier_source_does_not_hide_a_later_value():
    c = _classify(_log("'max_num_batched_tokens': None",
                       extra="Chunked prefill is enabled with max_num_batched_tokens=8192.\n"))
    assert c.mapped["engine.max_num_batched_tokens"][1] == 8192


def test_a_drafter_without_a_recorded_acceptance_takes_blis_registry_default():
    import score as sc
    c = _classify(_log("'speculative_config': {'method': 'dspark', 'num_speculative_tokens': 5, "
                       "'rejection_sample_method': 'standard'}"))
    assert "setting_not_modelled:speculative_config.rejection_sample_method" in c.reasons
    c = _classify(_log("'tensor_parallel_size': 1, 'max_num_seqs': 8, 'max_num_batched_tokens': 4096, 'block_size': 128, "
                       "'gpu_memory_utilization': 0.9, 'speculative_config': {'method': 'dspark', 'num_speculative_tokens': 5}"))
    b = st.build(c, name="p", model="m", part=PART_H200, engine_version="v0.31.0", defaults=H200_DEFAULTS)
    assert b.reasons == [] and b.acceptance_needed == ("dspark", 5) and b.acceptance_length is None

    class Env:
        defaults_helper, registry = "blisdefaults", "reg"
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        return type("P", (), {"returncode": 0, "stdout": json.dumps(
            {"acceptance_length": 4.07, "fallback_from": "(none)", "measured_on": "b200",
             "profile": "m/dspark/k5/thinking-off/coding", "set": "s"})})()
    orig = sc.subprocess.run
    try:
        sc.subprocess.run = fake_run
        completions = '"POST /v1/completions HTTP/1.1" 200'
        args = []
        assert sc.acceptance_default(args, b, Env(), completions, "h200", "m") == []
        assert args[0]["blis"] == "4.07" and args[0]["match"] == "approximated" and args[0]["measured"] is None
        assert "registry default m/dspark/k5/thinking-off/coding (measured on b200)" in args[0]["note"]
        assert calls[0][calls[0].index("-thinking") + 1] == "off"
        # chat requests: the thinking mode depends on template arguments the log doesn't state
        assert sc.acceptance_default([], b, Env(), '"POST /v1/chat/completions HTTP/1.1"', "h200", "m") == \
            ["required_setting_missing:speculative_config.synthetic_acceptance_length"]
        # BLIS has no profile for the drafter: refused, never guessed
        sc.subprocess.run = lambda argv, **kw: type("P", (), {"returncode": 1, "stdout": ""})()
        assert sc.acceptance_default([], b, Env(), completions, "h200", "m") == \
            ["required_setting_missing:speculative_config.synthetic_acceptance_length"]
    finally:
        sc.subprocess.run = orig


def test_the_flat_and_nested_spellings_of_one_setting_agree_or_conflict():
    c = _classify(_log("'moe_backend': 'deep_gemm_mega_moe'"))
    assert c.mapped["engine.moe_backend"][1] == "deep_gemm_mega_moe" and c.reasons == []
    c = _classify(_log("'moe_backend': 'aiter', 'kernel_config': KernelConfig(moe_backend='deep_gemm_mega_moe')"))
    assert c.reasons == ["conflict:moe_backend"]


def test_offload_bytes_printed_as_floats_and_ranks_that_disagree():
    base = ("'tensor_parallel_size': 1, 'max_num_seqs': 8, 'max_num_batched_tokens': 4096, 'block_size': 128, "
            "'gpu_memory_utilization': 0.9, 'kv_transfer_config': KVTransferConfig(kv_connector='SimpleCPUOffloadConnector', "
            "kv_connector_extra_config={'cpu_bytes_to_use': 53687091200.0})")
    c = _classify(_log(base))
    b = st.build(c, name="p", model="m", part=PART_H200, engine_version="v0.31.0", defaults=H200_DEFAULTS)
    assert b.reasons == [] and b.deployment["offload"]["tiers"][0]["bytes"] == 53687091200
    lines = "SimpleCPUOffloadConnector: role=WORKER, per_rank=50.00 GB, world_size=1\n" \
            "SimpleCPUOffloadConnector: role=WORKER, per_rank=40.00 GB, world_size=1\n"
    b = st.build(_classify(_log(base, extra=lines)), name="p", model="m", part=PART_H200,
                 engine_version="v0.31.0", defaults=H200_DEFAULTS)
    assert b.reasons == ["conflict:offload.per_rank_gib"]


def test_parallelism_must_come_from_the_run():
    c = _classify(_log("'max_num_seqs': 8", "model='m', quantization=fp8"))
    b = st.build(c, name="p", model="m", part=PART_H200, engine_version="v0.31.0", defaults=H200_DEFAULTS)
    assert {"required_setting_missing:parallel.tp", "required_setting_missing:parallel.dp"} <= set(b.reasons)


def test_an_unknown_client_input_refuses():
    r = rp.from_export(_export(phase={"brand_new_pacing": 2}))
    assert "unclassified_arg:replay.phase.brand_new_pacing" in r.reasons
    r = rp.from_export(_export())
    rp.cross_check(r, "aiperf profile --benchmark-grace-period 30 'unterminated", 8)
    assert r.reasons == ["conflict:replay.command_unreadable"]


def test_the_vllm_defaults_table_is_read_from_vllm_and_covers_printed_configs():
    assert DEFAULTS["attention_config.indexer_kv_dtype"] == "auto"
    assert DEFAULTS["kernel_config.moe_backend"] == "auto"
    assert DEFAULTS["prefill_schedule_interval"] == 1 and DEFAULTS["enforce_eager"] is False
    assert DEFAULTS["compilation_config.dynamic_shapes_config.type"] == "BACKED"


# ------------------------------------------------------------------ the deployment written

PART_H200 = st.Part(name="h200", memory_gib=139.80072021)
H200_DEFAULTS = {"device": "h200", "max_num_batched_tokens": 8192, "max_num_seqs": 1024, "memory_gib": 139.80072021}


def test_a_required_setting_nothing_recorded_takes_the_blis_default():
    c = _classify(_log("'tensor_parallel_size': 8, 'max_num_batched_tokens': 8192",
                       RESOLVED.replace("tensor_parallel_size=1", "tensor_parallel_size=8"),
                       extra="Setting kv cache block size to 64 for X\nDesired GPU memory utilization is (0.92, 128 GiB).\n"))
    b = st.build(c, name="p", model="deepseek-v4.1-flash", part=PART_H200, engine_version="v0.31.0",
                 defaults=H200_DEFAULTS)
    eng = b.deployment["pools"][0]["engine"]
    assert eng["max_num_seqs"] == 1024 and eng["max_num_batched_tokens"] == 8192
    used = b.defaults_used
    assert [u["arg"] for u in used] == ["max_num_seqs"] and used[0]["source"] == "blis_default"
    assert b.reasons == []


def test_a_required_setting_with_no_source_and_no_default_refuses():
    c = _classify(_log("'tensor_parallel_size': 1"))
    b = st.build(c, name="p", model="m", part=PART_H200, engine_version="v0.31.0", defaults=None)
    assert sorted(b.reasons) == ["required_setting_missing:gpu_memory_utilization",
                                 "required_setting_missing:max_num_batched_tokens", "required_setting_missing:max_num_seqs"]
    # block_size is left to BLIS's kernel, which resolves it as vLLM would; score.py records it.
    assert b.kernel_resolves == ["block_size"] and "block_size" not in b.deployment["pools"][0]["engine"]


def test_the_cluster_is_sized_to_the_runs_own_gpus():
    c = _classify(_log("'tensor_parallel_size': 1, 'data_parallel_size': 2, 'enable_expert_parallel': True, "
                       "'max_num_seqs': 16, 'max_num_batched_tokens': 4096, 'block_size': 128, 'gpu_memory_utilization': 0.9",
                       RESOLVED.replace("data_parallel_size=1", "data_parallel_size=2")))
    b = st.build(c, name="p", model="m", part=PART_H200, engine_version="v0.31.0", defaults=H200_DEFAULTS)
    assert b.scenario["cluster"] == {"hardware": "h200", "nodes": 1, "gpus_per_node": 2}
    assert b.scenario["engine_version"] == "0.31.0"
    par = b.deployment["pools"][0]["parallel"]
    assert (par["tp"], par["dp"], par["enable_expert_parallel"]) == (1, 2, True)


def test_offload_bytes_are_the_engines_from_the_server_wide_total():
    # cpu_bytes_to_use is server-wide and vLLM divides it by the engine's world size (TP4 here);
    # BLIS's tier is the engine's, so the bytes are per_rank x world.
    args = ("'tensor_parallel_size': 4, 'max_num_seqs': 8, 'max_num_batched_tokens': 4096, 'block_size': 128, "
            "'gpu_memory_utilization': 0.9, "
            "'kv_transfer_config': KVTransferConfig(kv_connector='SimpleCPUOffloadConnector', kv_role='kv_both', "
            "kv_connector_extra_config={'cpu_bytes_to_use': 1000000000003, 'lazy_offload': True})")
    c = _classify(_log(args, RESOLVED.replace("tensor_parallel_size=1", "tensor_parallel_size=4"),
                       extra="SimpleCPUOffloadConnector: role=WORKER, per_rank=232.83 GB, world_size=4\n"))
    b = st.build(c, name="p", model="m", part=PART_H200, engine_version="v0.31.0", defaults=H200_DEFAULTS)
    assert b.reasons == [], b.reasons
    assert b.deployment["offload"] == {"connector": "SimpleCPUOffloadConnector", "spec": "lazy",
                                       "tiers": [{"tier": "cpu_dram", "bytes": (1000000000003 // 4) * 4}]}


def test_offload_bytes_that_disagree_with_the_logged_per_rank_figure_conflict():
    args = ("'tensor_parallel_size': 4, 'max_num_seqs': 8, 'max_num_batched_tokens': 4096, 'block_size': 128, "
            "'gpu_memory_utilization': 0.9, "
            "'kv_transfer_config': KVTransferConfig(kv_connector='SimpleCPUOffloadConnector', "
            "kv_connector_extra_config={'cpu_bytes_to_use': 1000000000000})")
    c = _classify(_log(args, RESOLVED.replace("tensor_parallel_size=1", "tensor_parallel_size=4"),
                       extra="SimpleCPUOffloadConnector: role=WORKER, per_rank=50.00 GB, world_size=4\n"))
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


def test_what_blis_used_for_an_estimated_setting_is_read_from_blis():
    import score as sc
    res = {"cache_dtype": "nvfp4_ds_mla", "assumptions": [],
           "overrides": [{"field": "cache_dtype", "requested": "fp8", "resolved": "nvfp4_ds_mla", "reason": "r"}],
           "caches": [{"name": "index", "kind": "index", "bytes_per_entry": 132, "head_dim": 128},
                      {"name": "swa", "kind": "window", "bytes_per_entry": 528, "head_dim": 512}]}

    def args():
        return [{"arg": "attention_config.backend", "measured": "FLASHINFER_MLA_SPARSE_DSV41", "blis": None,
                 "match": "approximated", "_blis_from": "resolved.cache_dtype"},
                {"arg": "attention_config.indexer_kv_dtype", "measured": "mxfp4", "blis": None,
                 "match": "approximated", "_blis_from": "priced.index_cache"}]
    orig = sc.blis_resolution
    try:
        sc.blis_resolution = lambda env, d, f: res
        a = args()
        assert sc.fill_blis_side(a, None, Path("."), "s.yaml", "m") == []
        assert [x["blis"] for x in a] == ["nvfp4_ds_mla", "fp8"]
        assert all("_blis_from" not in x for x in a)
        # No override (the run's cache dtype is what BLIS runs): still read, from cache_dtype.
        sc.blis_resolution = lambda env, d, f: {**res, "overrides": [], "cache_dtype": "fp8_ds_mla"}
        a = args()
        assert sc.fill_blis_side(a, None, Path("."), "s.yaml", "m") == [] and a[0]["blis"] == "fp8_ds_mla"
        # An indexer record no vLLM layout names, or two that differ: refused, never named.
        for caches in ([{"kind": "index", "bytes_per_entry": 100, "head_dim": 128}],
                       [{"kind": "index", "bytes_per_entry": 132, "head_dim": 128},
                        {"kind": "index", "bytes_per_entry": 68, "head_dim": 128}]):
            sc.blis_resolution = lambda env, d, f, c=caches: {**res, "caches": c}
            assert sc.fill_blis_side(args(), None, Path("."), "s.yaml", "m") == \
                ["setting_differs:attention_config.indexer_kv_dtype"], caches
        # A model with no sparse indexer (Kimi): the setting changes nothing; inert, not estimated.
        sc.blis_resolution = lambda env, d, f: {**res, "caches": [{"kind": "kv", "bytes_per_entry": 576, "head_dim": 576}]}
        a = args()[1:]
        assert sc.fill_blis_side(a, None, Path("."), "s.yaml", "m") == [] and a[0]["match"] == "inert"
        assert not sc._estimated(a)
        # BLIS refuses the scenario: its refusal is the reason, never a crash.
        sc.blis_resolution = lambda env, d, f: "blis_refused:quantization_mxfp8_is_not_one_this_kernel_prices"
        assert "blis_refused:quantization_mxfp8_is_not_one_this_kernel_prices" in sc.fill_blis_side(
            args(), None, Path("."), "s.yaml", "m")
    finally:
        sc.blis_resolution = orig


def test_an_inferencex_hardware_label_names_one_catalog_part():
    cat = sp.Catalog(root=Path("."), hardware={"b200": 178.0, "gb200-nvl72": 184.0, "a100-80": 79.2, "a100-sxm": 39.4})
    parts = {"b200", "gb200-nvl72", "a100-80", "a100-sxm"}
    assert sp.catalog_part(cat, parts, "b200") == "b200"                 # the part of that name
    assert sp.catalog_part(cat, parts, "gb200") == "gb200-nvl72"         # its one <label>-variant
    assert sp.catalog_part(cat, parts, "a100") is None                   # two variants: not guessed
    assert sp.catalog_part(cat, parts, "mi355x") is None                 # none
    assert sp.catalog_part(cat, parts - {"gb200-nvl72"}, "gb200") is None   # no coefficients for it


def test_an_indexer_record_is_named_by_vllms_layout_for_its_head_width():
    # vLLM v0.31.0: fp8 = d_h + 4-byte scale; mxfp4 = d_h/2 + d_h/32 ue8m0 scales; bf16 = 2*d_h.
    assert [sp.index_record_format(w, 128) for w in (132, 68, 256)] == ["fp8", "mxfp4", "bf16"]
    assert [sp.index_record_format(w, 64) for w in (68, 34, 128)] == ["fp8", "mxfp4", "bf16"]
    assert sp.index_record_format(100, 128) is None          # no layout gives 100 B
    assert sp.index_record_format(132, 0) is None            # no head width stated: not guessed


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


def test_a_point_is_exact_only_on_the_build_blis_models_with_nothing_approximated():
    import score as sc
    near = {"match": "exact", "distance": -738}
    assert sc.point_status(False, near) == "exact"
    assert sc.point_status(True, near) == "approximate"
    for why in ("custom_build", "outside_distance", "commit_unresolvable", "commit_conflict"):
        assert sc.point_status(False, {"match": "estimated", "why": why}) == "approximate", why
    assert sc.point_status(False, {}) == "approximate"          # no build record: never exact


def test_a_build_never_refuses_a_point_at_pull_time():
    import pull as pl
    src = (HERE / "pull.py").read_text()
    assert "b.reasons" not in src and 'entry["build"] = b.record()' in src
    assert not hasattr(__import__("build").Build(image="x"), "reasons")


def test_a_block_size_no_source_recorded_is_the_one_blis_resolves():
    import score as sc
    orig = sc.blis_resolution
    try:
        sc.blis_resolution = lambda env, d, f: {"overrides": [], "assumptions": [
            {"name": "block_size", "value": "16", "reason": "CacheConfig.DEFAULT_BLOCK_SIZE"}]}
        args = []
        assert sc.kernel_defaults(args, ["block_size"], None, Path("."), "s.yaml") == []
        assert args == [{"arg": "block_size", "measured": None, "source": "blis_default", "blis": 16,
                         "match": "blis_default", "rule": "BLIS kernel: CacheConfig.DEFAULT_BLOCK_SIZE"}]
        sc.blis_resolution = lambda env, d, f: {"overrides": [], "assumptions": []}
        assert sc.kernel_defaults([], ["block_size"], None, Path("."), "s.yaml") == ["required_setting_missing:block_size"]
        sc.blis_resolution = lambda env, d, f: "blis_refused:x"
        assert sc.kernel_defaults([], ["block_size"], None, Path("."), "s.yaml") == ["blis_refused:x"]
        assert sc.kernel_defaults([], [], None, Path("."), "s.yaml") == []       # nothing left to BLIS
    finally:
        sc.blis_resolution = orig


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
                      # every other serving stack InferenceX reports, including the ones that
                      # wrap vLLM: only plain vLLM rows are pulled
                      *[{"id": str(10 + i), "model": "glm5", "framework": f, "date": "2026-10-21"}
                        for i, f in enumerate(("sglang", "trt", "dynamo-vllm", "vllm-disagg", "llmd-vllm",
                                               "dynamo-sglang", "dynamo-trt", "atom", "VLLM", " vllm"))]]}

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


# ------------------------------------------------------------------ policy coverage on real logs

LOGS = HERE / "testdata" / "logs"


# The parts' CUDA compute-capability majors, as the pinned catalog states them (catalog
# hardware/*.yaml ComputeCapability); AMD and TPU parts state none.
CATALOG_FAMILY = {"h100": 9, "h200": 9, "b200": 10, "b300": 10, "gb200": 10, "gb300": 10}


def test_every_arg_in_the_committed_real_logs_classifies_as_recorded():
    """One excerpt per InferenceX deployment shape seen in the 2026-09-20..10-23 window (the
    lines the extractor reads, verbatim). Every path classifies (no unclassified_arg), the
    logs read whole, and each deployment's outcome is the one expected.json records. A policy
    edit that changes any of them shows up here and has to be re-recorded on purpose."""
    expected = json.loads((LOGS / "expected.json").read_text())
    assert len(expected) >= 40
    for name, want in sorted(expected.items()):
        launch_path = LOGS / f"{name}.launch.json"
        launch = json.loads(launch_path.read_text()) if launch_path.exists() else None
        readings, problems = st.read_all((LOGS / f"{name}.server-log.txt").read_text(), launch)
        part = name.split("-")[1]
        c = st.classify(st.merge(readings, POLICY, DEFAULTS), POLICY, DEFAULTS, family=CATALOG_FAMILY.get(part))
        got = {"problems": problems, "reasons": c.reasons, "approximate": c.approximated}
        assert got == want, (name, got, want)
        assert not [r for r in c.reasons if r.startswith("unclassified_arg")], name


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
