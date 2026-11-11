"""A run that names a draft checkpoint is matched to the catalog's drafter entries (layer 8), not to
the served model's own graph. The catalog here is a synthetic fixture of the schema as described:
a drafter lists `targets`, a target lists `drafters`, and the check is two-way."""
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import support as sp  # noqa: E402
import settings as st  # noqa: E402
from test_extract import _catalog  # noqa: E402

MM3 = "MiniMaxAI/MiniMax-M3"
EAGLE = "Inferact/MiniMax-M3-EAGLE3"
GQA = "Inferact/MiniMax-M3-EAGLE3-GQA"


def _entry(root, name, *, graph_method=None, tokens=None, **keys):
    d = Path(root) / "models" / name
    d.mkdir(parents=True, exist_ok=True)
    import yaml
    (d / "model.yaml").write_text(yaml.safe_dump({"name": name, **keys}))
    if graph_method:
        n = f"  num_spec_tokens: {tokens}\n" if tokens is not None else ""
        (d / "graph.yaml").write_text(f"global: {{}}\nspeculator:\n  method: {graph_method}\n{n}")


def _cat(**links):
    root = Path(tempfile.mkdtemp())
    models = {"dsv41": "deepseek-ai/DeepSeek-V4.1-Flash", "mm3": MM3, "mm3-mxfp8": "MiniMaxAI/MiniMax-M3-MXFP8", "mm3-eagle3": EAGLE, "mm3-eagle3-gqa": GQA}
    cat = _catalog(root, models=models)
    _entry(root, "mm3", drafters=links.get("mm3", ["mm3-eagle3"]))
    _entry(root, "mm3-mxfp8", drafters=["mm3-eagle3"])
    _entry(root, "mm3-eagle3", graph_method="eagle3", targets=links.get("eagle3", ["mm3", "mm3-mxfp8"]))
    _entry(root, "mm3-eagle3-gqa", graph_method="eagle3", targets=["mm3-mxfp8"])
    return cat


def _check(cat, draft=EAGLE, spec="eagle3", model=MM3):
    return sp.check(cat, {"h200"}, checkpoints=[model], base_models={}, hardware="h200", spec_method=spec,
                    draft_checkpoint=draft)


def test_a_drafter_that_names_the_model_and_is_named_by_it_is_found():
    s = _check(_cat())
    assert s.reasons == [] and s.drafter == "mm3-eagle3"
    s = _check(_cat(), model="MiniMaxAI/MiniMax-M3-MXFP8")
    assert s.reasons == [] and s.drafter == "mm3-eagle3"


def test_the_check_is_two_way():
    assert _check(_cat(mm3=[])).reasons == ["drafter_not_in_catalog:eagle3"]       # the model does not list it
    assert _check(_cat(eagle3=["mm3-mxfp8"])).reasons == ["drafter_not_in_catalog:eagle3"]   # it does not name the model


def test_a_drafter_for_another_target_is_not_this_models():
    s = _check(_cat(), draft=GQA)       # the GQA drafter names only the mxfp8 model
    assert s.reasons == ["drafter_not_in_catalog:eagle3"] and s.drafter is None


def test_a_draft_checkpoint_the_catalog_does_not_hold_or_a_method_that_differs_is_refused():
    assert _check(_cat(), draft="Inferact/Unknown").reasons == ["drafter_not_in_catalog:eagle3"]
    assert _check(_cat(), spec="dspark").reasons == ["drafter_not_in_catalog:dspark"]


def test_a_run_that_names_no_draft_checkpoint_is_decided_by_the_served_models_graph_as_before():
    cat = _cat()
    s = sp.check(cat, {"h200"}, checkpoints=[MM3], base_models={}, hardware="h200", spec_method="mtp")
    assert s.reasons == [] and s.drafter is None
    s = sp.check(cat, {"h200"}, checkpoints=[MM3], base_models={}, hardware="h200", spec_method="eagle3")
    assert s.reasons == ["drafter_not_in_catalog:eagle3"]


def test_the_catalog_schema_may_put_the_lists_under_identity():
    cat = _cat()
    root = Path(cat.root)
    _entry(root, "mm3", identity={"drafters": ["mm3-eagle3"]})
    _entry(root, "mm3-eagle3", graph_method="eagle3", identity={"targets": ["mm3"]})
    assert _check(cat).reasons == []


def test_the_scenario_names_the_drafter_by_its_catalog_entry_and_only_when_the_run_named_one():
    from test_extract import _build, _classify, _log
    args = ("'tensor_parallel_size': 1, 'speculative_config': {'method': 'eagle3', 'num_speculative_tokens': 3, "
            "'model': 'Inferact/MiniMax-M3-EAGLE3'}")
    c = _classify(_log(args))
    assert c.roles.get("drafter") == EAGLE and sp.hf_repo(c.roles["drafter"]) == EAGLE
    spec = lambda b: b.deployment["pools"][0]["engine"]["speculative"]  # noqa: E731
    assert spec(_build(c, draft_model="mm3-eagle3"))["draft_model"] == "mm3-eagle3"
    assert "draft_model" not in spec(_build(c))


# ---- MTP: vLLM states every model-specific MTP method as `mtp`

def _mtp(spec="mtp", model=MM3, draft=None, tokens=None, cat=None):
    cat = cat or _cat()
    _entry(Path(cat.root), "mm3", graph_method="minimax_m3_mtp", tokens=7, drafters=["mm3-eagle3"])
    return sp.check(cat, {"h200"}, checkpoints=[model], base_models={}, hardware="h200", spec_method=spec,
                    draft_checkpoint=draft, num_spec_tokens=tokens)


def test_the_engine_names_a_model_specific_mtp_method_mtp_and_keeps_the_others():
    assert [sp.engine_method(m) for m in ("minimax_m3_mtp", "mtp", "eagle3", "dflash", "dspark", None)] == \
        ["mtp", "mtp", "eagle3", "dflash", "dspark", None]


def test_an_mtp_point_resolves_against_the_catalogs_model_specific_method():
    s = _mtp()
    assert s.reasons == [] and s.drafter is None


def test_vllm_naming_the_served_model_as_its_own_drafter_is_the_served_models_graph():
    # vLLM's resolved config names the target as the MTP draft model
    s = _mtp(draft=MM3)
    assert s.reasons == [] and s.drafter is None


def test_a_model_with_no_mtp_speculator_or_another_method_is_still_refused():
    cat = _cat()
    s = sp.check(cat, {"h200"}, checkpoints=["deepseek-ai/DeepSeek-V4.1-Flash"], base_models={}, hardware="h200",
                 spec_method="mtp")                  # its graph speculates by dspark
    assert s.reasons == ["drafter_not_in_catalog:mtp"]
    assert _mtp(spec="eagle3").reasons == ["drafter_not_in_catalog:eagle3"]       # wrong method
    assert _mtp(spec="minimax_m3_mtp").reasons == ["drafter_not_in_catalog:minimax_m3_mtp"]   # the engine never states it


# ---- the stated draft length (vLLM v0.32.0 vllm/config/speculative.py, via the layer 8 reference)

import pytest  # noqa: E402


@pytest.mark.parametrize("method, k, n", [
    ("mtp", 3, 7), ("mtp", 7, 7), ("mtp", 1, 7), ("mtp", 14, 7), ("mtp", 21, 7),     # minimax-m3 (7 modules)
    ("mtp", 1, 1), ("mtp", 4, 1), ("mtp", 3, 1),                                      # mxfp8 and dsv4 (1 module): any multiple of 1
    ("eagle", 1, None), ("eagle3", 9, None), ("draft_model", 2, None), ("dflash", 5, None), ("dspark", 7, None),
])
def test_a_draft_length_vllm_accepts_is_not_a_conflict(method, k, n):
    assert sp.draft_length_conflict(method, k, n) is None


@pytest.mark.parametrize("method, k, n, text", [
    ("mtp", 8, 7, "8 exceeds the model's 7 MTP modules and is not a multiple of 7"),
    ("mtp", 13, 7, "13 exceeds"), ("mtp", 20, 7, "20 exceeds"),
    ("mtp", 0, 7, "0 is below 1"), ("eagle3", 0, None, "0 is below 1"), ("dspark", -2, None, "-2 is below 1"),
])
def test_a_draft_length_vllm_refuses_is_named_with_its_numbers(method, k, n, text):
    assert text in sp.draft_length_conflict(method, k, n)


def test_a_point_stating_a_length_vllm_refuses_is_value_conflict_and_a_valid_length_names_nothing():
    s = _mtp(tokens=3)                                   # 3 against 7 modules
    assert s.reasons == []
    s = _mtp(tokens=14)
    assert s.reasons == []
    s = _mtp(tokens=8)
    assert s.reasons == ["value_conflict:speculative_config.num_speculative_tokens: vLLM refuses "
                         "8 exceeds the model's 7 MTP modules and is not a multiple of 7"]
    assert _mtp(tokens=0).reasons[0].startswith("value_conflict:speculative_config.num_speculative_tokens")
    assert _mtp(tokens=None).reasons == []              # an unstated length is the builder's to require


def test_the_separate_drafter_path_requires_a_length_of_at_least_one():
    assert _check(_cat()).reasons == []
    s = sp.check(_cat(), {"h200"}, checkpoints=[MM3], base_models={}, hardware="h200", spec_method="eagle3",
                 draft_checkpoint=EAGLE, num_spec_tokens=0)
    assert s.reasons and s.reasons[0].startswith("value_conflict:speculative_config.num_speculative_tokens")


def test_mutation_comparing_the_length_for_equality_would_refuse_valid_runs(monkeypatch):
    # The rule is "K <= n_predict, or a multiple of it"; an equality check (the graph's default as an
    # expectation) would refuse 3 against 7. The test above passes only with the rule.
    monkeypatch.setattr(sp, "draft_length_conflict", lambda m, k, n: None if k == n else "differs")
    assert _mtp(tokens=3).reasons != []


# ---- a drafter that shares its target's repository (layer 8: told apart by source.path)

def _flash_catalog():
    root = Path(tempfile.mkdtemp())
    for name, extra in (("flash", {"drafters": ["flash-dspark"]}),
                        ("flash-dspark", {"targets": ["flash"]})):
        d = root / "models" / name
        d.mkdir(parents=True)
        src = {"provider": "huggingface", "repo": "MiniMaxAI/MiniMax-M3.1-Flash", "revision": "r"}
        if name.endswith("dspark"):
            src["path"] = "dspark/config.json"
        import yaml
        (d / "model.yaml").write_text(yaml.safe_dump({"name": name, "source": src, **extra}))
        (d / "graph.yaml").write_text("global: {}\n" + ("speculator:\n  method: dspark\n  num_spec_tokens: 7\n" if name.endswith("dspark") else ""))
    (root / "hardware").mkdir()
    (root / "hardware" / "h200.yaml").write_text("GPUsPerNode: 8\n")
    return sp.CheckoutCatalog(blis="", root=root)


def test_the_served_model_lookup_skips_a_drafter_that_shares_its_repository():
    cat = _flash_catalog()
    assert cat.model("MiniMaxAI/MiniMax-M3.1-Flash") == "flash"        # not ambiguous
    assert cat.drafters_of("minimaxai/minimax-m3.1-flash") == ["flash-dspark"]
    cat.check_unambiguous()


def test_a_dspark_run_naming_the_served_repo_as_its_draft_model_finds_the_drafter_entry():
    cat = _flash_catalog()
    s = sp.check(cat, {"h200"}, checkpoints=["MiniMaxAI/MiniMax-M3.1-Flash"], base_models={}, hardware="h200",
                 spec_method="dspark", draft_checkpoint="MiniMaxAI/MiniMax-M3.1-Flash", num_spec_tokens=5)
    assert s.reasons == [] and s.drafter == "flash-dspark"
    s = sp.check(cat, {"h200"}, checkpoints=["MiniMaxAI/MiniMax-M3.1-Flash"], base_models={}, hardware="h200",
                 spec_method="eagle3", draft_checkpoint="MiniMaxAI/MiniMax-M3.1-Flash")
    assert s.reasons == ["drafter_not_in_catalog:eagle3"]
