"""Prefill/decode points (dashboard #61): the pools a row records, the named refusals,
the recipe a row ran and what it states, the router table, and a point scored through two pools.

Run: python3 -m pytest orchestrator/ingest/test_pd.py
"""
from __future__ import annotations

import gzip
import json
import shutil
import sys
import tempfile
import types
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import assess as asx  # noqa: E402
import contract as c  # noqa: E402
import grade as gr  # noqa: E402
import pd as pdm  # noqa: E402
import pd_recipe as pdr  # noqa: E402
import pull as pl  # noqa: E402
import recipes as rcp  # noqa: E402
import router_table as rt  # noqa: E402
import score as sc  # noqa: E402
import settings as st  # noqa: E402
import test_score_e2e as e2e  # noqa: E402

ROW = {"id": "9", "framework": "dynamo-vllm", "model": "m", "hardware": "mi355x", "precision": "fp8", "disagg": True,
       "is_multinode": True, "benchmark_type": "single_turn", "isl": 1024, "osl": 1024, "conc": 4, "spec_method": "none",
       "prefill_num_workers": 1, "num_prefill_gpu": 1, "prefill_tp": 1, "prefill_ep": 1, "prefill_dp_attention": False,
       "decode_num_workers": 2, "num_decode_gpu": 8, "decode_tp": 4, "decode_ep": 1, "decode_dp_attention": False,
       "date": "2026-10-01", "run_url": "https://github.com/SemiAnalysisAI/InferenceX/actions/runs/1/attempts/1",
       "curve_workflow_run_id": "7", "image": "vllm/vllm-openai:v0.31.0", "metrics": {"mean_ttft": 0.2, "mean_tpot": 0.01}}

RECIPE = """\
name: "t"
model: {path: "m", container: "vllm/vllm-openai:v0.31.0", precision: "fp8"}
resources: {gpu_type: "mi355x", gpus_per_node: 8, prefill_nodes: 1, decode_nodes: 1, prefill_workers: 1, decode_workers: 2,
            gpus_per_prefill: 1, gpus_per_decode: 4}
frontend: {type: dynamo, enable_multiple_frontends: false}
backend:
  type: vllm
  allow_prefill_decode_colocation: true
  prefill_environment: {VLLM_FLASHINFER_ALLREDUCE_BACKEND: "trtllm"}
  decode_environment: {VLLM_FLASHINFER_ALLREDUCE_BACKEND: "trtllm"}
  vllm_config:
    prefill:
      kv-transfer-config: '{"kv_connector": "NixlConnector", "kv_role": "kv_both"}'
      kv-cache-dtype: "fp8"
      no-enable-prefix-caching: true
      max-model-len: 2048
      max-num-batched-tokens: 2048
    decode:
      kv-transfer-config: '{"kv_connector": "NixlConnector", "kv_role": "kv_both"}'
      kv-cache-dtype: "fp8"
      tensor-parallel-size: 4
      enable-expert-parallel: true
      no-enable-prefix-caching: true
      max-model-len: 2048
      max-num-batched-tokens: 4096
benchmark: {type: "sa-bench", isl: 1024, osl: 1024, concurrencies: "4x8"}
"""

RECIPE_FABRIC = RECIPE.replace('gpu_type: "mi355x",', 'gpu_type: "mi355x", fabric: "ib-400g",')
REV = "1682167d3c97f0fc8cd405dee51f17288eeaeb55"
POOL_P = {"tp": 1, "pp": 1, "dp": 1, "expert_parallel": False}
POOL_D = {"tp": 4, "pp": 1, "dp": 1, "expert_parallel": True}
# The substrate's exact regime (layer 12): the sampled client counts, the engine release, the fabric, each pool's instance.
REGIME = {"workload": "balanced", "concurrencies": [1, 4, 16, 64], "model": "m", "hardware": "mi355x", "shapes": ["1P2D"],
          "engine_version": "0.31.0", "fabric": "ib-400g", "prefill": POOL_P, "decode": POOL_D}
TABLE_ENTRY = {"kind": "RouterMapping", "router": "dynamo", "mode": "round-robin", "revisions": [REV], "policy": "round-robin",
               "reason": "r", "difference": [{"aspect": "counter", "text": "counters differ", "evidence": [0]}],
               "bound": {"evidence": {"file": "runs.csv", "sha256": "0" * 64, "producer": "o/r", "commit": "a" * 40, "command": "c"},
                         "ratios": [{"metric": "ttft_p50_ms", "against": ["random-picker"], "regime": REGIME, "max_ratio": 1.07},
                                    {"metric": "ttft_p99_ms", "against": ["least-active-requests"], "regime": REGIME, "max_ratio": 1.7}],
                         "not_measured": ["other models"]},
               "evidence": [{"side": "router", "field": "mode", "repository": "ai-dynamo/dynamo", "commit": "a" * 40, "path": "p.rs",
                             "lines": "1-2", "claim": "c"}]}


def recipe():
    return pdr.parse(RECIPE)


# ---------------------------------------------------------------- the row's pools and their named refusals

def test_a_dp_free_row_has_two_pools_and_no_refusal():
    pools = pdm.pools_of(ROW, recipe())
    assert (pools["prefill"].workers, pools["prefill"].gpus, pools["prefill"].dp) == (1, 1, 1)
    assert (pools["decode"].workers, pools["decode"].gpus, pools["decode"].tp) == (2, 4, 4)
    assert pdm.topology_reasons(ROW, pools) == []


def test_a_pool_on_dp_attention_is_refused_by_name_with_the_other_pool_unequal():
    row = {**ROW, "prefill_dp_attention": True, "num_prefill_gpu": 8, "prefill_tp": 8}
    pools = pdm.pools_of(row)
    assert pools["prefill"].dp == 8 and pools["decode"].dp == 1
    assert pdm.topology_reasons(row, pools) == ["topology_unsupported:pd_pool_data_parallel",
                                                "topology_unsupported:pd_unequal_data_parallel"]


def test_equal_dp_above_one_is_a_pool_refusal_and_not_an_unequal_one():
    row = {**ROW, "prefill_dp_attention": True, "num_prefill_gpu": 4, "prefill_tp": 4, "decode_dp_attention": True}
    assert pdm.topology_reasons(row, pdm.pools_of(row)) == ["topology_unsupported:pd_pool_data_parallel"]


def test_the_recipes_data_parallel_size_decides_over_the_rows_reading():
    stated = RECIPE.replace("tensor-parallel-size: 4", "tensor-parallel-size: 1\n      data-parallel-size: 4")
    row = {**ROW, "decode_dp_attention": True}
    assert pdm.pools_of(row)["decode"].dp == 4                      # the row's reading: the pool's GPUs
    assert pdm.pools_of(row, pdr.parse(stated.replace("data-parallel-size: 4", "data-parallel-size: 2")))["decode"].dp == 2


def test_a_row_with_a_pool_of_no_workers_is_named_not_recorded():
    row = {**ROW, "decode_num_workers": 0, "num_decode_gpu": 0}
    assert pdm.pools_of(row) is None
    assert pdm.topology_reasons(row, None) == ["topology_unsupported:pd_pool_not_recorded"]


def test_the_named_refusals_are_topology_unsupported_with_the_slug_as_subject():
    for slug in pdm.TOPOLOGY_SLUGS:
        assert asx.g5_of(f"topology_unsupported:{slug}") == {"code": "topology_unsupported", "subject": slug}
    assert asx.g5_of("recipe_unresolved:not_in_tree") == {"code": "value_not_recorded", "subject": "not_in_tree"}


# ---------------------------------------------------------------- the endpoint picker configuration

POLICIES = ("round-robin", "random-picker", "least-active-requests", "default")      # names a fixture router publishes


def router_checkout(root: Path, policies=POLICIES, no_pd=("default",)) -> Path:
    """A fixture of the router checkout in the router's layout: reference-configs/policies.json and one file per form,
    each with its own bytes (the dashboard never reads their content; a trailing space and a CRLF make a rewrite visible).
    A policy in `no_pd` has no prefill/decode form, as `default` has none."""
    d = root / "router"
    (d / "reference-configs").mkdir(parents=True, exist_ok=True)
    entries = []
    for p in policies:
        files = {"colocated": f"{p}.yaml", "pd": None if p in no_pd else f"{p}-pd.yaml"}
        for form, name in files.items():
            if name:
                (d / "reference-configs" / name).write_bytes(f"# router file for {p} {form} \r\nkind: EndpointPickerConfig\n".encode())
        entries.append({"name": p, "files": files})
    (d / pdm.INDEX_PATH).write_text(json.dumps({"schema": 1, "policies": entries}))
    return d


@pytest.mark.parametrize("policy", [p for p in POLICIES if p != "default"])
def test_the_file_passed_for_a_policy_is_the_routers_pd_file_byte_for_byte(tmp_path, policy):
    d = router_checkout(tmp_path)
    assert pdm.epp_file(policy, d) == (d / "reference-configs" / f"{policy}-pd.yaml").read_bytes()
    assert pdm.epp_file(policy, d, "colocated") == (d / "reference-configs" / f"{policy}.yaml").read_bytes()


def test_a_policy_the_router_does_not_publish_is_refused_by_name(tmp_path):
    d = router_checkout(tmp_path, POLICIES[:3])
    with pytest.raises(pdm.PolicyConfigError) as e:
        pdm.epp_file("default", d)
    assert e.value.slug == "policy_config_not_published:default"
    with pytest.raises(pdm.PolicyConfigError) as e:
        pdm.epp_file("round-robin", tmp_path)                          # no index at all
    assert e.value.slug == "router_index_missing"


def test_a_policy_without_the_needed_form_is_refused_by_name(tmp_path):
    d = router_checkout(tmp_path)
    with pytest.raises(pdm.PolicyConfigError) as e:
        pdm.epp_file("default", d)                                     # default has no prefill/decode form
    assert e.value.slug == "policy_form_missing:default:pd"
    assert pdm.epp_file("default", d, "colocated")                     # but a colocated one
    d2 = router_checkout(tmp_path / "x", ("round-robin",), no_pd=("round-robin",))
    with pytest.raises(pdm.PolicyConfigError):
        pdm.epp_file("round-robin", d2)


def test_an_index_naming_a_file_outside_the_checkout_is_refused(tmp_path):
    d = router_checkout(tmp_path)
    (tmp_path / "outside.yaml").write_text("x")
    (d / pdm.INDEX_PATH).write_text(json.dumps({"policies": [{"name": "default", "files": {"colocated": "../../outside.yaml", "pd": None}}]}))
    with pytest.raises(pdm.PolicyConfigError):
        pdm.epp_file("default", d, "colocated")


# ---------------------------------------------------------------- the recipe

MASTER = {"k-fp8": {"framework": "dynamo-vllm", "model-prefix": "m", "runner": "mi355x-multinode", "precision": "fp8",
                    "model": "org/m", "image": "vllm/vllm-openai:v0.31.0",
                    "scenarios": {"fixed-seq-len": [{"isl": 1024, "osl": 1024, "search-space": [
                        {"conc-list": [4, 8], "prefill": {"num-worker": 1, "tp": 1, "ep": 1, "dp-attn": False,
                                                          "additional-settings": ["CONFIG_FILE=recipes/vllm/m/a.yaml"]},
                         "decode": {"num-worker": 2, "tp": 4, "ep": 1, "dp-attn": False}},
                        {"conc-list": [16], "prefill": {"num-worker": 1, "tp": 1, "ep": 1, "dp-attn": False,
                                                        "additional-settings": ["CONFIG_FILE=recipes/vllm/m/b.yaml"]},
                         "decode": {"num-worker": 2, "tp": 4, "ep": 1, "dp-attn": False}}]}]}}}


def test_a_row_is_the_one_search_space_item_it_agrees_with():
    assert pdr.master_matches(list(MASTER.items()), ROW) == [("k-fp8", "recipes/vllm/m/a.yaml")]
    assert pdr.master_matches(list(MASTER.items()), {**ROW, "conc": 16}) == [("k-fp8", "recipes/vllm/m/b.yaml")]
    assert pdr.master_matches(list(MASTER.items()), {**ROW, "conc": 32}) == []
    assert pdr.master_matches(list(MASTER.items()), {**ROW, "decode_num_workers": 3}) == []
    assert pdr.master_matches(list(MASTER.items()), {**ROW, "spec_method": "mtp"}) == []
    assert pdr.master_matches(list(MASTER.items()), {**ROW, "hardware": "b200"}) == []


def test_two_items_that_fit_the_row_are_both_returned_so_the_caller_can_refuse():
    twin = json.loads(json.dumps(MASTER))
    twin["k-fp8"]["scenarios"]["fixed-seq-len"][0]["search-space"][1]["conc-list"] = [4]
    got = pdr.master_matches(list(twin.items()), ROW)
    assert [cf for _, cf in got] == ["recipes/vllm/m/a.yaml", "recipes/vllm/m/b.yaml"]


LAUNCH = '''
mkdir -p recipes/vllm/minimax-m2.5
cp -rT "$GITHUB_WORKSPACE/benchmarks/multi_node/srt-slurm-recipes/vllm/minimax-m2.5-b300" recipes/vllm/minimax-m2.5
    mkdir -p recipes/vllm/deepseek-v4/agentic
    cp -rT "$GITHUB_WORKSPACE/benchmarks/multi_node/srt-slurm-recipes/vllm/deepseek-v4/agentic" \\
        recipes/vllm/deepseek-v4/agentic
SRT_RECIPE_SRC="$GITHUB_WORKSPACE/benchmarks/multi_node/srt-slurm-recipes/sglang/glm5"
SRT_RECIPE_DST="recipes/sglang/glm5"
'''


def test_the_launch_scripts_overlays_are_read_in_both_spellings():
    assert pdr.overlays(LAUNCH) == [("sglang/glm5", "recipes/sglang/glm5"),
                                    ("vllm/deepseek-v4/agentic", "recipes/vllm/deepseek-v4/agentic"),
                                    ("vllm/minimax-m2.5-b300", "recipes/vllm/minimax-m2.5")]


def test_the_file_is_the_source_of_the_overlay_that_holds_the_path_else_the_same_path_in_the_tree():
    root = pdr.ROOT
    tree = {root + "vllm/minimax-m2.5-b300/1k1k/x.yaml": "s1", root + "vllm/minimax-m2.5/1k1k/x.yaml": "s2"}
    scripts = {"runners/launch_b300-nv.sh": LAUNCH}
    # the overlay wins: the same name under the other directory is not the file that ran
    assert pdr.source_paths("recipes/vllm/minimax-m2.5/1k1k/x.yaml", tree, scripts, "b300") == \
        [root + "vllm/minimax-m2.5-b300/1k1k/x.yaml"]
    # a script of another hardware's launcher is not consulted
    assert pdr.source_paths("recipes/vllm/minimax-m2.5/1k1k/x.yaml", tree, scripts, "b200") == \
        [root + "vllm/minimax-m2.5/1k1k/x.yaml"]
    # no overlay and no such file in the tree: it came from the unpinned srt-slurm repository
    assert pdr.source_paths("recipes/vllm/other/y.yaml", tree, scripts, "b300") == []
    assert pdr.source_paths("recipes/vllm/minimax-m2.5/1k1k/absent.yaml", tree, scripts, "b300") == []


def test_the_recipe_is_parsed_per_pool_and_checked_against_the_row():
    r = recipe()
    assert (r.pools["prefill"].workers, r.pools["prefill"].gpus, r.pools["decode"].gpus) == (1, 1, 4)
    assert r.pools["decode"].flags["max-num-batched-tokens"] == 4096 and r.colocation is True
    assert pdr.concurrencies(r) == [4, 8] and pdr.check_row(r, ROW) == []
    assert pdr.check_row(r, {**ROW, "decode_num_workers": 3, "num_decode_gpu": 12}) == \
        ["conflict:recipe.decode_workers", "conflict:recipe.gpus_per_decode"]
    assert pdr.check_row(r, {**ROW, "num_decode_gpu": 4}) == ["conflict:recipe.gpus_per_decode"]
    assert pdr.check_row(r, {**ROW, "conc": 64}) == ["conflict:recipe.concurrency"]
    assert pdr.check_row(r, {**ROW, "isl": 8192}) == ["conflict:recipe.isl"]
    assert pdr.check_row(r, {**ROW, "precision": "fp4"}) == ["conflict:recipe.precision"]
    with pytest.raises(ValueError):
        pdr.parse("name: x\n")


def test_a_recipe_that_sets_no_router_mode_ran_the_frontends_default_and_says_so():
    assert pdr.router_mode(recipe()) == ("round-robin", None, False)
    kv = RECIPE.replace("frontend: {type: dynamo, enable_multiple_frontends: false}",
                        "frontend: {type: dynamo, args: {router-mode: kv, router-session-affinity-ttl-secs: 14400}}")
    assert pdr.router_mode(pdr.parse(kv)) == ("kv", 14400, True)


def test_the_pseudo_launch_states_a_size_the_recipe_leaves_at_default_only_when_the_gpus_equal_the_product():
    pools = pdm.pools_of(ROW, recipe())
    pre = pdm.pseudo_launch(recipe(), "prefill", ROW, pools["prefill"])["roles"]["prefill"]["args"]
    assert (pre["tensor-parallel-size"], pre["pipeline-parallel-size"], pre["data-parallel-size"]) == (1, 1, 1)
    odd = pools["decode"]
    odd.gpus = 8                                                      # 4 x 1 x 1 is not 8 GPUs: nothing is invented
    args = pdm.pseudo_launch(recipe(), "decode", ROW, odd)["roles"]["decode"]["args"]
    assert args["tensor-parallel-size"] == 4 and "pipeline-parallel-size" not in args
    assert pdm.pseudo_launch(recipe(), "decode", ROW, pools["decode"])["resources"] == {"gpus_per_node": 8}


def test_the_transfer_connector_and_role_are_not_engine_settings():
    pools = pdm.pools_of(ROW, recipe())
    rd, taken = pdm.read_pool(pdm.pseudo_launch(recipe(), "decode", ROW, pools["decode"]))
    assert taken == {"kv_transfer_config.kv_connector": "NixlConnector", "kv_transfer_config.kv_role": "kv_both"}
    assert not any(p.startswith("kv_transfer_config.kv_c") or p.endswith("kv_role") for p in rd.values)
    assert rd.values["enable_prefix_caching"] == [False]


def test_a_recipe_that_allows_colocation_names_the_pool_placement_difference():
    assert pdm.placement_substitution(recipe())["kind"] == "execution_mode"
    assert pdm.placement_substitution(pdr.parse(RECIPE.replace("allow_prefill_decode_colocation: true", "allow_prefill_decode_colocation: false"))) is None


# ---------------------------------------------------------------- the router table

def _table(tmp, **over):
    d = tmp / "routers"
    d.mkdir(exist_ok=True)
    (d / "dynamo-round-robin.yaml").write_text(yaml.safe_dump({**TABLE_ENTRY, **over}))
    return rt.load(tmp)


def test_the_table_is_resolved_as_the_substrate_does(tmp_path):
    t = _table(tmp_path)
    e, outcome = t.resolve("dynamo", "round-robin", None, REV)
    assert outcome == rt.MAPPED and e.policy == "round-robin" and e.revisions == [REV]
    assert t.resolve("dynamo", "round-robin", None, "b" * 40)[1] == rt.REVISION_NOT_COVERED      # a build the entry does not list
    assert t.resolve("dynamo", "round-robin", None, None)[1] == rt.REVISION_NOT_COVERED          # a build the run does not record
    assert t.resolve("dynamo", "kv", None, REV) == (None, rt.NO_ENTRY)
    assert t.resolve("dynamo", "round-robin", 1, REV) == (None, rt.NO_ENTRY)                     # affinity is part of the key
    assert t.resolve("dynamo", None, None, REV) == (None, rt.NO_ENTRY)
    assert _table(tmp_path, policy="none").resolve("dynamo", "round-robin", None, REV)[1] == rt.NO_POLICY
    assert rt.load(tmp_path / "nowhere").entries == []
    assert rt.router_key("dynamo-router") == "dynamo" and rt.router_key("llm-d-router") == "llm-d"


def test_a_bound_holds_a_point_only_in_its_regime(tmp_path):
    e = _table(tmp_path).entries[0]
    ok = dict(workload="balanced", conc=4, model="m", hardware="mi355x", shape="1P2D",
              engine_version="0.31.0", fabric="ib-400g", prefill=POOL_P, decode=POOL_D)
    assert sorted(m["metric"] for m in rt.matched_ratios(e, **ok)) == ["ttft_p50_ms", "ttft_p99_ms"]
    # The known-bad points: each differs from the sampled regime in one dimension and never gets a bound.
    bad = ({"workload": "prefill-bound"}, {"workload": None}, {"model": "n"}, {"hardware": "b200"}, {"shape": "2P2D"},
           {"conc": 8},                                   # between two sampled counts (4 and 16): not run, not covered
           {"conc": 100}, {"conc": 65}, {"conc": 0}, {"conc": None},
           {"engine_version": "0.32.0"}, {"engine_version": None},          # another engine release
           {"fabric": "roce-200g"}, {"fabric": None},                      # another or an unrecorded fabric
           {"prefill": {**POOL_P, "tp": 2}}, {"decode": {**POOL_D, "dp": 2}}, {"decode": {**POOL_D, "pp": 2}},
           {"decode": {**POOL_D, "expert_parallel": False}}, {"prefill": None}, {"decode": {"tp": 4}},
           {"decode": {**POOL_D, "extra": 1}})
    for change in bad:
        assert rt.matched_ratios(e, **{**ok, **change}) == [], change
    assert rt.workload_kind(1024, 1024) == "balanced" and rt.workload_kind(8192, 16) == "prefill-bound"
    assert rt.workload_kind(256, 2048) == "decode-bound" and rt.workload_kind(8192, 1024) is None


def test_the_old_range_form_of_a_regime_covers_no_point(tmp_path):
    """A regime that still states `concurrency_min` and `concurrency_max` (the form before the substrate made it
    exact) is not interpolated: it matches nothing."""
    old = {k: v for k, v in REGIME.items() if k != "concurrencies"} | {"concurrency_min": 1, "concurrency_max": 64}
    entry = {**TABLE_ENTRY, "bound": {**TABLE_ENTRY["bound"], "ratios": [
        {"metric": "ttft_p50_ms", "against": ["random-picker"], "regime": old, "max_ratio": 1.07}]}}
    e = _table(tmp_path, bound=entry["bound"]).entries[0]
    assert rt.matched_ratios(e, workload="balanced", conc=4, model="m", hardware="mi355x", shape="1P2D",
                             engine_version="0.31.0", fabric="ib-400g", prefill=POOL_P, decode=POOL_D) == []


POINT = {"workload": "balanced", "concurrency": 4, "model": "m", "hardware": "mi355x", "engine_version": "0.31.0",
         "fabric": "ib-400g", "shape": "1P2D", "prefill": POOL_P, "decode": POOL_D}


def _matched(e, **over):
    p = {**POINT, **over}
    return rt.matched_ratios(e, workload=p["workload"], conc=p["concurrency"], model=p["model"], hardware=p["hardware"],
                             shape=p["shape"], engine_version=p["engine_version"], fabric=p["fabric"],
                             prefill=p["prefill"], decode=p["decode"])


def test_the_substitution_carries_the_point_and_only_the_ratios_that_hold_it(tmp_path):
    other = {**REGIME, "concurrencies": [256]}              # a second cell of the sweep that does not hold a count of 4
    bound = {**TABLE_ENTRY["bound"], "ratios": TABLE_ENTRY["bound"]["ratios"] + [
        {"metric": "tpot_p50_ms", "against": ["random-picker"], "regime": other, "max_ratio": 1.4}]}
    e = _table(tmp_path, bound=bound).entries[0]
    m = _matched(e)
    sub = rt.substitution(e, "dynamo", REV, m, POINT)
    assert sub["kind"] == "router_differs" and sub["entry"] == "dynamo-round-robin" and sub["policy"] == "round-robin"
    assert sub["revision"] == REV and sub["difference"] == [{"aspect": "counter", "text": "counters differ"}]
    assert sub["regime"] == POINT
    assert sorted(r["metric"] for r in sub["bound"]["ratios"]) == ["ttft_p50_ms", "ttft_p99_ms"]      # not the tpot cell
    assert sub["bound"]["evidence"] == TABLE_ENTRY["bound"]["evidence"] and "ASSUMED" not in sub["detail"]
    assert rt.carried_bound_covers_point(sub) == []
    assert "ASSUMED" in rt.substitution(e, "dynamo", REV, m, POINT, assumed=True)["detail"]
    assert rt.bound_wide(m) is True                                            # 1.7 > 1.25
    assert rt.bound_wide(m[:1]) is False and rt.bound_wide([]) is False
    # Known bad: the whole bound carried is refused, and so is a record with no regime.
    whole = {**sub, "bound": bound}
    assert rt.carried_bound_covers_point(whole)
    with pytest.raises(gr.GradeError):
        gr.grade(engine_version="0.32.0", release=gr.Release("0.32.0", False), substitutions=[whole])
    assert rt.carried_bound_covers_point({k: v for k, v in sub.items() if k != "regime"})
    # An unsampled count has no bound for this regime.
    assert _matched(e, concurrency=8) == []


def test_the_grade_needs_the_build_the_difference_the_regime_and_the_bound_of_a_router_differs():
    base = {"kind": "router_differs", "subject": "dynamo", "entry": "dynamo-round-robin", "policy": "round-robin",
            "evidence": "e", "detail": "d", "revision": REV, "difference": [{"aspect": "a", "text": "t"}], "regime": POINT,
            "bound": {"ratios": [{"metric": "ttft_p50_ms", "against": ["random-picker"], "regime": REGIME, "max_ratio": 1.1}]}}
    release = gr.Release("0.32.0", False)
    assert gr.grade(engine_version="0.32.0", release=release, substitutions=[base]).grade == gr.G2
    for missing in ("revision", "difference", "bound", "regime"):
        with pytest.raises(gr.GradeError):
            gr.grade(engine_version="0.32.0", release=release, substitutions=[{k: v for k, v in base.items() if k != missing}])
    with pytest.raises(gr.GradeError):
        gr.grade(engine_version="0.32.0", release=release, substitutions=[{**base, "revision": "1.2.0.dev20260526"}])
    with pytest.raises(gr.GradeError):
        gr.grade(engine_version="0.32.0", release=release, substitutions=[{**base, "policy": "none"}])


# ---------------------------------------------------------------- the pull freezes the recipe

class FakeRecipes:
    repo = "SemiAnalysisAI/InferenceX"

    def __init__(self, tree=None, entries=None, launch=LAUNCH, texts=None, missing=False):
        self.rc = rcp.Recipes()
        self.rc.entries = entries if entries is not None else list(MASTER.items())
        self.rc.tree = tree if tree is not None else {pdr.ROOT + "vllm/m/a.yaml": "blob-a", "runners/launch_mi355x-amds.sh": "blob-l"}
        self.texts = {"blob-a": RECIPE, "blob-l": "", **(texts or {})}
        self.missing = missing

    def run_commit(self, run_id):
        return "a" * 40

    def at(self, sha):
        if self.missing:
            raise rcp.RecipesUnavailable(sha)
        return self.rc

    def blob_text(self, b):
        return self.texts[b]


def _frozen(tmp):
    return pl.Frozen(tmp / "points" / "x")


def test_the_pull_keeps_the_one_recipe_a_row_ran(tmp_path):
    f = _frozen(tmp_path)
    got = pl.freeze_pd_recipe(ROW, FakeRecipes(), f)
    assert got["recipe"]["path"] == pdr.ROOT + "vllm/m/a.yaml" and got["recipe"]["config_file"] == "recipes/vllm/m/a.yaml"
    assert got["recipe"]["commit"] == "a" * 40 and got["recipe"]["model"] == "org/m" and "recipe" in f.files
    assert gzip.decompress((f.dir / f.files["recipe"]["path"]).read_bytes()).decode() == RECIPE


@pytest.mark.parametrize("fake,slug", [
    (dict(missing=True), pdr.NO_COMMIT),
    (dict(entries=[]), pdr.NO_MASTER),
    (dict(tree={"runners/launch_mi355x-amds.sh": "blob-l"}), pdr.NOT_IN_TREE),
    (dict(texts={"blob-a": "name: x\n"}), pdr.UNREADABLE),
])
def test_the_pull_names_why_it_kept_no_recipe(tmp_path, fake, slug):
    f = _frozen(tmp_path)
    assert pl.freeze_pd_recipe(ROW, FakeRecipes(**fake), f) == {"recipe_reason": slug}
    assert "recipe" not in f.files


def test_the_pull_refuses_two_items_that_fit_and_two_files_that_differ(tmp_path):
    twin = json.loads(json.dumps(MASTER))
    twin["k-fp8"]["scenarios"]["fixed-seq-len"][0]["search-space"][1]["conc-list"] = [4]
    assert pl.freeze_pd_recipe(ROW, FakeRecipes(entries=list(twin.items())), _frozen(tmp_path)) == {"recipe_reason": pdr.AMBIGUOUS}
    two = FakeRecipes(launch="", tree={pdr.ROOT + "vllm/m/a.yaml": "blob-a", "runners/launch_mi355x-amds.sh": "blob-l",
                                       pdr.ROOT + "vllm/m2/a.yaml": "blob-z"},
                      texts={"blob-l": 'cp -rT "$GITHUB_WORKSPACE/benchmarks/multi_node/srt-slurm-recipes/vllm/m" recipes/vllm/m\n'
                                       'cp -rT "$GITHUB_WORKSPACE/benchmarks/multi_node/srt-slurm-recipes/vllm/m2" recipes/vllm/m\n',
                             "blob-z": RECIPE.replace("sa-bench", "other")})
    assert pl.freeze_pd_recipe(ROW, two, _frozen(tmp_path)) == {"recipe_reason": pdr.AMBIGUOUS}


def test_a_run_of_another_repository_has_no_commit_to_read(tmp_path):
    row = {**ROW, "run_url": "https://github.com/other/repo/actions/runs/1/attempts/1"}
    assert pl.freeze_pd_recipe(row, FakeRecipes(), _frozen(tmp_path)) == {"recipe_reason": pdr.NO_COMMIT}


# ---------------------------------------------------------------- a point scored through two pools

def _pd_point(tmp: Path, *, row=None, recipe_text=None, with_recipe=True, table=True, log=True):
    # table: the router table maps Dynamo's default mode (router_differs); False leaves the catalog's own, which has none here.
    recipe_text = RECIPE_FABRIC if recipe_text is None else recipe_text   # a stated fabric: the router bound's regime needs a recorded one
    entry, env = e2e._setup(tmp)
    env.router_checkout = router_checkout(tmp)
    pdir = tmp / "pull" / "points" / entry["point_id"]
    entry["row"].update({**ROW, **(row or {})})
    entry["measurements"] = [{"record": "1", "metrics": entry["row"]["metrics"]}]
    if not log:
        (pdir / "server_log.gz").unlink()
        entry["files"].pop("server_log")
        entry["reasons"] = ["server_log_missing"]
    if with_recipe:
        (pdir / "recipe.gz").write_bytes(gzip.compress(recipe_text.encode(), mtime=0))
        entry["files"]["recipe"] = {"path": "recipe.gz", "sha256": "0" * 64, "from": "t"}
        entry["recipe"] = {"repo": "SemiAnalysisAI/InferenceX", "commit": "a" * 40, "path": pdr.ROOT + "vllm/m/a.yaml",
                           "config_file": "recipes/vllm/m/a.yaml", "master_key": "k-fp8", "model": "org/m", "image": "x"}
    else:
        entry["recipe_reason"] = pdr.NOT_IN_TREE
    if table:
        d = tmp / "routers"
        d.mkdir(exist_ok=True)
        (d / "dynamo-round-robin.yaml").write_text(yaml.safe_dump(TABLE_ENTRY))
        env.routers_dir = d
        env.assumed_router_revision = REV
    env.catalog_obj = e2e._catalog(tmp, {"org/m": "m"}, {"mi355x": (8, None)}, {})
    env.parts = {"mi355x"}
    return entry, env


def _fields_with(*names_status):
    doc = json.loads((HERE / "testdata" / "fields" / "fields.json").read_bytes())
    for n, status in names_status:
        doc["fields"] = [f for f in doc["fields"] if f["name"] != n]
        f = {"name": n, "source": "env" if n.isupper() else "config", "status": status, "estimation": {"rule": "none"}}
        f["evidence"] = {"traces": ["t.json"]} if status == "modelled" else {"proof": "p.json"} if status == "proven_inert" else {"issue": "x/y#1"}
        doc["fields"].append(f)
    doc["fields"].sort(key=lambda f: (f["name"], f["source"]))
    import fields as fl
    return fl.parse(json.dumps(doc).encode())


def test_an_assumed_fabric_or_an_unsampled_concurrency_never_gets_router_differs():
    for kw, row in (({"recipe_text": RECIPE}, None),              # the recipe states no fabric: the class is assumed
                    ({"recipe_text": RECIPE_FABRIC}, {"conc": 100})):       # 100 is between the sampled 64 and nothing
        tmp = Path(tempfile.mkdtemp())
        try:
            entry, env = _pd_point(tmp, log=False, row=row, **kw)
            o, _ = e2e._score(tmp, entry, env, tmp / "c1")
            assert "router_unsupported:dynamo-router:no_bound_for_regime" in o.reasons, o.reasons
            assert o.fidelity is None
        finally:
            shutil.rmtree(tmp)


def test_a_dp_free_row_is_written_as_two_pools_and_scored_with_the_instance_counts_and_a_named_router():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _pd_point(tmp, log=False, recipe_text=RECIPE_FABRIC)
        o, work = e2e._score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        assert c.validate_dir(tmp / "c1") == []
        sdir = work / "single_turn" / entry["point_id"]
        dep = sc._parse_back(next(sdir.glob("p-*.yaml")).read_text())
        pre, dec = dep["pools"]
        assert (pre["role"], dec["role"]) == ("prefill", "decode")
        assert pre["parallel"]["tp"] == 1 and dec["parallel"]["tp"] == 4 and dec["parallel"]["enable_expert_parallel"] is True
        mnbt = lambda p: p["engine"].get("max_num_batched_tokens")
        assert (mnbt(pre), mnbt(dec)) == (2048, 4096)                   # each pool's own, from the recipe
        assert dep["pd_transfer"] == {"connector": "NixlConnector"}
        assert dep["router"] == {"endpoint_picker_config": "pd-round-robin.epp.yaml"}
        assert (sdir / "pd-round-robin.epp.yaml").read_bytes() == pdm.epp_file("round-robin", env.router_checkout, "pd")     # unchanged
        scen = next(d for d in yaml.safe_load_all(next(sdir.glob("p-*.yaml")).read_text()) if d["kind"] == "Scenario")
        assert scen["cluster"]["fabric"] == "ib-400g" and "cost-model-fabric" in scen["coefficients"]
        assert scen["cluster"]["nodes"] == 2
        argv = e2e._saw(env)[0]["argv"]
        got = lambda f: argv[argv.index(f) + 1]
        assert (got("--num-instances"), got("--prefill-instances"), got("--decode-instances")) == ("3", "1", "2")
        subs = {(s["kind"], s["subject"]): s for s in o.fidelity["substitutions"]}
        rd = subs[("router_differs", "dynamo")]
        assert rd["entry"] == "dynamo-round-robin" and rd["policy"] == "round-robin" and rd["difference"] and rd["bound"]
        assert rd["revision"] == REV and "ASSUMED" in rd["detail"] and "frontend's default" in rd["detail"]
        assert o.fidelity["router"]["bound_wide"] is True and o.fidelity["router"]["outcome"] == "mapped"
        assert sorted(m["metric"] for m in o.fidelity["router"]["matched_ratios"]) == ["ttft_p50_ms", "ttft_p99_ms"]
        for role in ("prefill", "decode"):
            rec = subs[("estimated", f"engine.{role}.recipe")]
            assert pdr.ROOT + "vllm/m/a.yaml" in rec["detail"] and "a" * 40 in rec["detail"] and "max_num_batched_tokens" in rec["detail"]
        assert ("estimated", "cluster.fabric") not in subs and ("execution_mode", "pool placement") in subs
        bc = subs[("client_difference", "benchmark_client")]["detail"]
        assert "sa-bench" in bc and "not InferenceX's" in bc and "chat template on (its default)" in bc
        assert o.fidelity["grade"] == "G2" or o.fidelity["grade"] in ("G3", "G4")
        f = json.loads((tmp / "c1" / "facets.json").read_text())[entry["point_id"]]
        assert f["serving"] == "disaggregated" and f["parallelism"]["decode_tp"] == 4 and f["parallelism"]["prefill_workers"] == 1
    finally:
        shutil.rmtree(tmp)


def test_a_row_on_dp_attention_is_refused_by_name_and_blis_is_never_asked():
    tmp = Path(tempfile.mkdtemp())
    try:
        row = {"prefill_dp_attention": True, "num_prefill_gpu": 8, "prefill_tp": 8}
        entry, env = _pd_point(tmp, row=row, recipe_text=RECIPE.replace("gpus_per_prefill: 1", "gpus_per_prefill: 8"))
        o, _ = e2e._score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is None      # the pools differ from the router bound's regime too, so that is named beside the topology
        assert {"topology_unsupported:pd_pool_data_parallel", "topology_unsupported:pd_unequal_data_parallel"} <= set(o.reasons)
        assert e2e._saw(env) == []
    finally:
        shutil.rmtree(tmp)


def test_a_row_with_no_recipe_and_no_log_keeps_both_reasons():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _pd_point(tmp, with_recipe=False, log=False)
        o, _ = e2e._score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is None and set(o.reasons) >= {"server_log_missing", "recipe_unresolved:not_in_tree"}
        # the router is also unsupported here (no table), which outranks value_not_recorded in the closed order
        assert o.g5["code"] == "router_unsupported" and {"code": "value_not_recorded", "subject": "not_in_tree"} in o.g5_reasons
        assert e2e._saw(env) == []
    finally:
        shutil.rmtree(tmp)


def _router_outcome(env_change=None, row=None, **over):
    """The G5 reason of a Dynamo point whose router table entry is the fixture's with `over` changed."""
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _pd_point(tmp, row=row)
        if env_change:
            env_change(env)
        if over:
            (tmp / "routers" / "dynamo-round-robin.yaml").write_text(yaml.safe_dump({**TABLE_ENTRY, **over}))
        o, _ = e2e._score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is None and e2e._saw(env) == []
        return o.g5
    finally:
        shutil.rmtree(tmp)


def test_a_dynamo_row_stays_router_unsupported_and_the_outcome_is_named():
    no = lambda s: {"code": "router_unsupported", "subject": f"dynamo-router:{s}"}
    assert _router_outcome(lambda e: setattr(e, "assumed_router_revision", None)) == no("revision_not_covered")   # a wheel, not a commit
    assert _router_outcome(lambda e: setattr(e, "assumed_router_revision", "b" * 40)) == no("revision_not_covered")
    assert _router_outcome(policy="none") == no("no_policy")
    assert _router_outcome(mode="kv") == no("no_entry")
    assert _router_outcome(row={"conc": 400}) == no("no_bound_for_regime")
    assert _router_outcome(row={"isl": 8192, "osl": 1024}) == no("no_bound_for_regime")      # a length no workload kind has


def test_a_dynamo_row_with_no_table_at_all_is_router_unsupported_by_name():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _pd_point(tmp, table=False)
        o, _ = e2e._score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is None and o.g5 == {"code": "router_unsupported", "subject": "dynamo-router:no_entry"}
        assert e2e._saw(env) == []
    finally:
        shutil.rmtree(tmp)


def test_a_recipe_that_is_not_the_rows_is_a_conflict_and_nothing_is_recovered():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _pd_point(tmp, recipe_text=RECIPE.replace("decode_workers: 2", "decode_workers: 3"))
        o, _ = e2e._score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is None and "conflict:recipe.decode_workers" in o.reasons and e2e._saw(env) == []
    finally:
        shutil.rmtree(tmp)


def test_an_environment_variable_the_engine_does_not_list_is_refused_not_dropped():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _pd_point(tmp, recipe_text=RECIPE.replace("VLLM_FLASHINFER_ALLREDUCE_BACKEND", "UCX_TLS"))
        o, _ = e2e._score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is None and "field_not_in_release:env.UCX_TLS" in o.reasons and e2e._saw(env) == []
    finally:
        shutil.rmtree(tmp)


def test_an_inert_environment_variable_is_recorded_and_not_stated_to_the_engine():
    # blis-vllm refuses an env key it does not read; a variable the field list calls inert is not stated.
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _pd_point(tmp, log=False)
        env.field_list = _fields_with(("VLLM_FLASHINFER_ALLREDUCE_BACKEND", "proven_inert"))
        o, work = e2e._score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        dep = sc._parse_back(next((work / "single_turn" / entry["point_id"]).glob("p-*.yaml")).read_text())
        assert all("env" not in p["engine"] for p in dep["pools"])
        arg = next(a for a in o.fidelity["args"] if a["arg"] == "decode.env.VLLM_FLASHINFER_ALLREDUCE_BACKEND")
        assert arg["match"] == "inert"
    finally:
        shutil.rmtree(tmp)


# ---------------------------------------------------------------- a colocated engine over several nodes

def test_a_colocated_engine_over_two_nodes_is_written_as_one_pool_with_a_fabric_and_scored():
    # row.is_multinode without disagg: one pool whose ranks need two nodes (it was refused for its topology).
    tmp = Path(tempfile.mkdtemp())
    try:
        log = e2e.LOG.replace("'tensor_parallel_size': 1,", "'tensor_parallel_size': 8, 'data_parallel_size': 2,") \
            .replace("tensor_parallel_size=1, pipeline_parallel_size=1, data_parallel_size=1",
                     "tensor_parallel_size=8, pipeline_parallel_size=1, data_parallel_size=2")
        entry, env = e2e._setup(tmp, log=log, node_size=8)
        entry["row"].update(is_multinode=True, decode_tp=8, decode_dp_attention=False, num_decode_gpu=16)
        o, work = e2e._score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        scen = list(yaml.safe_load_all(next((work / "single_turn" / entry["point_id"]).glob("p-*.yaml")).read_text()))
        cluster = next(d for d in scen if d["kind"] == "Scenario")["cluster"]
        assert cluster["nodes"] == 2 and cluster["fabric"] == "ib-400g"
        assert len(next(d for d in scen if d["kind"] == "Deployment")["pools"]) == 1
        assert ("estimated", "cluster.fabric") in {(s["kind"], s["subject"]) for s in o.fidelity["substitutions"]}
        assert c.validate_dir(tmp / "c1") == []
    finally:
        shutil.rmtree(tmp)


# ---------------------------------------------------------------- the one worker's log that survives

def _cfg(**kw):
    return {"tensor_parallel_size": 4, "data_parallel_size": 1, "kv_cache_dtype": "fp8", "enable_prefix_caching": False, **kw}


def test_a_log_that_agrees_with_one_pool_of_the_recipe_is_no_conflict():
    pools = pdm.pools_of(ROW, recipe())
    assert pdm.log_conflicts([_cfg()], recipe(), pools) == []                         # the decode worker
    assert pdm.log_conflicts([_cfg(tensor_parallel_size=1)], recipe(), pools) == []   # the prefill worker
    assert pdm.log_conflicts([_cfg(), _cfg(tensor_parallel_size=1)], recipe(), pools) == []


def test_a_log_the_recipe_contradicts_is_a_conflict_naming_the_field():
    pools = pdm.pools_of(ROW, recipe())
    assert pdm.log_conflicts([_cfg(tensor_parallel_size=8)], recipe(), pools) == ["conflict:server_log_vs_recipe.tensor_parallel_size"]
    assert pdm.log_conflicts([_cfg(data_parallel_size=2)], recipe(), pools) == ["conflict:server_log_vs_recipe.tensor_parallel_size"]
    assert pdm.log_conflicts([_cfg(kv_cache_dtype="auto")], recipe(), pools) == ["conflict:server_log_vs_recipe.kv_cache_dtype"]
    assert pdm.log_conflicts([_cfg(enable_prefix_caching=True)], recipe(), pools) == ["conflict:server_log_vs_recipe.enable_prefix_caching"]


def test_a_point_whose_log_contradicts_its_recipe_is_not_recovered_from_it():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _pd_point(tmp)          # the fixture's log is a TP1, KV-dtype-auto engine; the recipe says fp8
        o, _ = e2e._score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is None and "conflict:server_log_vs_recipe.kv_cache_dtype" in o.reasons and e2e._saw(env) == []
        assert o.g5_reasons and {"code": "value_conflict", "subject": "server_log_vs_recipe.kv_cache_dtype"} in o.g5_reasons
    finally:
        shutil.rmtree(tmp)


# ---------------------------------------------------------------- a multi-node colocated run whose log is gone

AGG_RECIPE = """\
name: "agg"
model: {path: "m", container: "vllm/vllm-openai:v0.31.0", precision: "fp8"}
resources: {gpu_type: "mi355x", gpus_per_node: 8, agg_nodes: 2, agg_workers: 1, gpus_per_agg: 16}
frontend: {type: vllm}
backend:
  type: vllm
  aggregated_environment: {VLLM_FLASHINFER_ALLREDUCE_BACKEND: "trtllm"}
  vllm_config:
    aggregated:
      tensor-parallel-size: 8
      data-parallel-size: 2
      max-num-seqs: 16
      max-model-len: 4096
benchmark: {type: custom, concurrencies: [8, 12]}
"""
AGG_MASTER = {"k": {"framework": "vllm", "model-prefix": "m", "runner": "cluster:mi355x-x", "precision": "fp8", "model": "org/m",
                    "scenarios": {"agentic-coding": [{"search-space": [
                        {"spec-decoding": "none", "conc-list": [8, 12],
                         "worker": {"num-worker": 2, "tp": 8, "ep": 1, "dp-attn": True,
                                    "additional-settings": ["CONFIG_FILE=recipes/vllm/m/agg.yaml"]}}]}]}}}
AGG_ROW = {"framework": "vllm", "benchmark_type": "agentic_traces", "isl": None, "osl": None, "conc": 8, "spec_method": "none",
           "disagg": False, "is_multinode": True, "prefill_num_workers": 2, "prefill_tp": 8, "prefill_ep": 1,
           "prefill_dp_attention": True, "num_prefill_gpu": 16, "decode_num_workers": 0, "decode_tp": 0, "decode_ep": 0,
           "decode_dp_attention": False, "num_decode_gpu": 0}


def test_an_agentic_item_with_one_worker_block_is_the_row_that_has_no_decode_pool():
    got = pdr.master_matches(list(AGG_MASTER.items()), {**ROW, **AGG_ROW})
    assert got == [("k", "recipes/vllm/m/agg.yaml")]
    assert pdr.master_matches(list(AGG_MASTER.items()), {**ROW, **AGG_ROW, "prefill_num_workers": 4}) == []
    assert pdr.master_matches(list(AGG_MASTER.items()), {**ROW, **AGG_ROW, "benchmark_type": "single_turn", "isl": 1024, "osl": 1024}) == []
    assert pdr.master_matches(list(AGG_MASTER.items()), {**ROW, **AGG_ROW, "decode_num_workers": 1}) == []


def test_an_aggregated_recipe_is_one_pool_checked_by_gpus_and_parallel_sizes():
    r = pdr.parse(AGG_RECIPE)
    assert list(r.pools) == ["aggregated"] and r.pools["aggregated"].gpus == 16
    row = {**ROW, **AGG_ROW}
    assert pdr.check_row(r, row) == []
    assert pdr.check_row(r, {**row, "num_prefill_gpu": 32}) == ["conflict:recipe.gpus_per_agg"]
    assert pdr.check_row(r, {**row, "prefill_tp": 16}) == ["conflict:recipe.tensor-parallel-size"]
    assert pdr.check_row(r, {**row, "conc": 99}) == ["conflict:recipe.concurrency"]


def test_a_multi_node_agentic_point_with_no_log_is_written_from_its_recipe_and_names_the_recovery():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = e2e._agentic(tmp)
        pdir = tmp / "pull" / "points" / entry["point_id"]
        (pdir / "server_log.gz").unlink()
        entry["files"].pop("server_log")
        entry["reasons"] = ["server_log_missing"]
        entry["row"].update({k: v for k, v in AGG_ROW.items() if k not in ("isl", "osl")})
        (pdir / "recipe.gz").write_bytes(gzip.compress(AGG_RECIPE.encode(), mtime=0))
        entry["files"]["recipe"] = {"path": "recipe.gz", "sha256": "0" * 64, "from": "t"}
        entry["recipe"] = {"repo": "SemiAnalysisAI/InferenceX", "commit": "a" * 40, "path": pdr.ROOT + "vllm/m/agg.yaml",
                           "config_file": "recipes/vllm/m/agg.yaml", "master_key": "k", "model": "org/m", "image": "x"}
        env.catalog_obj = e2e._catalog(tmp, {"org/m": "m"}, {"mi355x": (8, None)}, {})
        o, _ = e2e._score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        assert "server_log_missing" not in o.reasons
        scen = list(yaml.safe_load_all(next((tmp / "work-c1" / "scenarios").glob("p-*.yaml")).read_text()))
        cluster = next(d for d in scen if d["kind"] == "Scenario")["cluster"]
        dep = next(d for d in scen if d["kind"] == "Deployment")
        assert cluster["nodes"] == 2 and cluster["fabric"] == "ib-400g" and len(dep["pools"]) == 1
        assert dep["pools"][0]["parallel"]["tp"] == 8 and dep["pools"][0]["parallel"]["dp"] == 2
        subs = {(s["kind"], s["subject"]) for s in o.fidelity["substitutions"]}
        assert ("estimated", "engine.aggregated.recipe") in subs and ("estimated", "cluster.fabric") in subs
        # a recipe that is not the row's recovers nothing
        (pdir / "recipe.gz").write_bytes(gzip.compress(AGG_RECIPE.replace("gpus_per_agg: 16", "gpus_per_agg: 32").encode(), mtime=0))
        o, _ = e2e._score(tmp, entry, env, tmp / "c2")
        assert o.fidelity is None and "conflict:recipe.gpus_per_agg" in o.reasons
    finally:
        shutil.rmtree(tmp)


def test_a_fabric_class_the_recipe_states_is_used_and_not_named_as_assumed():
    # No recipe read states one today, so ib-400g is assumed and named; a stated class wins.
    for text, fabric, named in ((RECIPE, "ib-400g", True),
                                (RECIPE.replace("gpu_type: \"mi355x\",", "gpu_type: \"mi355x\", fabric: \"roce-200g\","), "roce-200g", False)):
        tmp = Path(tempfile.mkdtemp())
        try:
            entry, env = _pd_point(tmp, log=False, recipe_text=text)
            env.router_policy_experiment = "round-robin"     # the router bound's regime needs a recorded fabric; this test is about the fabric
            o, work = e2e._score(tmp, entry, env, tmp / "c1")
            assert o.fidelity is not None, o.reasons
            scen = next(d for d in yaml.safe_load_all(next((work / "single_turn" / entry["point_id"]).glob("p-*.yaml")).read_text())
                        if d["kind"] == "Scenario")
            assert scen["cluster"]["fabric"] == fabric and "cost-model-fabric" in scen["coefficients"]
            assert (("estimated", "cluster.fabric") in {(s["kind"], s["subject"]) for s in o.fidelity["substitutions"]}) is named
        finally:
            shutil.rmtree(tmp)


def test_a_router_policy_experiment_scores_the_writer_and_says_it_is_not_a_graded_router_result():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _pd_point(tmp, table=False, log=False)
        env.router_policy_experiment = "round-robin"
        o, work = e2e._score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        sub = next(s for s in o.fidelity["substitutions"] if s["subject"].startswith("router dynamo (experiment)"))
        assert sub["kind"] == "execution_mode" and "EXPERIMENT ONLY" in sub["detail"] and "no_entry" in sub["detail"]
        assert not [s for s in o.fidelity["substitutions"] if s["kind"] == "router_differs"]
        assert o.fidelity["router"]["outcome"] == "experiment"
        assert (next((work / "single_turn" / entry["point_id"]).glob("pd-round-robin.epp.yaml"))).is_file()
        # a router the experiment does not name policy for, and a point refused for another reason, stay refused
        entry2, env2 = _pd_point(Path(tempfile.mkdtemp()), table=False, row={"prefill_dp_attention": True, "num_prefill_gpu": 8, "prefill_tp": 8},
                                 recipe_text=RECIPE.replace("gpus_per_prefill: 1", "gpus_per_prefill: 8"), log=False)
        env2.router_policy_experiment = "round-robin"
        o2 = sc._score_one(entry2, Path(env2.catalog) / "pull", Path(env2.catalog) / "w", env2)
        assert o2.fidelity is None and "topology_unsupported:pd_pool_data_parallel" in o2.reasons
    finally:
        shutil.rmtree(tmp)


def test_a_size_the_aggregated_recipe_leaves_at_default_is_written_only_when_the_gpus_add_up():
    r = pdr.parse(AGG_RECIPE.replace("data-parallel-size: 2\n      ", ""))          # tp 8, no data-parallel size, 16 GPUs
    cfg, derived = pdm.aggregated_launch(r, {"model": "org/m"})
    args = cfg["roles"]["aggregated"]["args"]
    assert "data-parallel-size" not in args and "pipeline-parallel-size" not in args and derived == []   # 8 x 1 x 1 is not 16
    full = pdr.parse(AGG_RECIPE.replace("      data-parallel-size: 2\n", "").replace("tensor-parallel-size: 8", "tensor-parallel-size: 16"))
    cfg, derived = pdm.aggregated_launch(full, {"model": "org/m"})
    assert cfg["roles"]["aggregated"]["args"]["data-parallel-size"] == 1 and derived == ["pipeline_parallel_size", "data_parallel_size"]
    assert cfg["model"] == {"path": "org/m"} and cfg["resources"] == {"gpus_per_node": 8}


def test_the_router_experiment_does_not_replace_any_other_router_reason():
    # llm-d's own router has no recorded endpoint picker configuration: that is not a router the table could map.
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _pd_point(tmp, table=False, log=False)
        entry["row"]["metrics"] = {**entry["row"]["metrics"], "router_name": "llm-d-router"}   # ROW is shared: copy
        env.router_policy_experiment = "round-robin"
        o, _ = e2e._score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is None and "required_setting_missing:router.endpoint_picker_config" in o.reasons
        assert e2e._saw(env) == []
    finally:
        shutil.rmtree(tmp)


def test_a_prefill_decode_point_starts_cold_even_with_prefix_caching_on():
    """sa-bench's warm-up primes nothing the main phase reads, so a two-pool point is never primed with copies of
    request 0 (the InferenceX client's warm-up)."""
    on = RECIPE_FABRIC.replace("      no-enable-prefix-caching: true\n", "")
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _pd_point(tmp, log=False, recipe_text=on)
        env.router_policy_experiment = "round-robin"
        o, _ = e2e._score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        assert o.fidelity["requests"]["start"] == "cold"
    finally:
        shutil.rmtree(tmp)


def test_a_point_whose_policy_the_router_does_not_publish_is_g5_with_the_named_reason():
    for kw, want in (({"policies": POLICIES[1:]}, "router_unsupported:dynamo-router:policy_config_not_published:round-robin"),
                     ({"none": True}, "router_unsupported:dynamo-router:router_checkout_not_given")):
        tmp = Path(tempfile.mkdtemp())
        try:
            entry, env = _pd_point(tmp, log=False)
            env.router_checkout = None if kw.get("none") else router_checkout(tmp / "r2", kw["policies"])
            o, _ = e2e._score(tmp, entry, env, tmp / "c1")
            assert o.fidelity is None and want in o.reasons, o.reasons
            assert e2e._saw(env) == []                    # the simulator was never asked
        finally:
            shutil.rmtree(tmp)
