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
    assert s.reasons == [] and s.drafter is None and s.substitutions == []


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


def test_a_stated_token_count_that_differs_from_the_graphs_is_a_named_substitution():
    assert _mtp(tokens=7).substitutions == []
    s = _mtp(tokens=1)
    assert s.reasons == [] and s.substitutions == [{
        "kind": "value_class", "subject": "speculative_config.num_speculative_tokens",
        "detail": "the run states 1, the catalog graph of mm3 derives 7"}]
