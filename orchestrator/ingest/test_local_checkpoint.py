"""A run that serves a staged copy of a checkpoint (/lustre/fsw/models/GLM-5-FP8) names no Hugging Face repo; the catalog
model is found by the directory's name, and a path that fits no single catalog repository is not guessed at."""
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import score as sc  # noqa: E402
import support as sp  # noqa: E402
import test_score_e2e as e2e  # noqa: E402

REPOS = {"deepseek-r1-0528": "deepseek-ai/DeepSeek-R1-0528", "glm-5-fp8": "zai-org/GLM-5-FP8", "glm-5-nvfp4": "nvidia/GLM-5-NVFP4",
         "qwen3.5-397b-a17b": "Qwen/Qwen3.5-397B-A17B", "qwen3.5-397b-a17b-nvfp4": "nvidia/Qwen3.5-397B-A17B-NVFP4",
         "twin-a": "org-a/Twin-70B", "twin-b": "org-b/Twin-70B"}


def catalog(tmp_path) -> sp.Catalog:
    cat = e2e._catalog(tmp_path, {r: n for n, r in REPOS.items()}, {"h200": (8, None)}, {})
    for name, repo in REPOS.items():
        (cat.root / "models" / name).mkdir(parents=True, exist_ok=True)
        (cat.root / "models" / name / "model.yaml").write_text(yaml.safe_dump({"name": name, "source": {"repo": repo}}))
    return cat


def decided(model, served=None):
    return SimpleNamespace(roles={"model": model, "served_model": served if served is not None else []})


def served_model(tmp_path, path):
    cat = catalog(tmp_path)
    cks = sc._checkpoints(decided(path, path), None, cat)
    return cks, sp.check(cat, {"h200"}, checkpoints=cks, base_models={}, hardware="h200", spec_method=None)


def test_a_staged_checkpoint_resolves_to_the_catalog_model_its_directory_is_named_for(tmp_path):
    cks, sup = served_model(tmp_path, "/lustre/fsw/models/GLM-5-FP8")
    assert cks == ["zai-org/glm-5-fp8"] and sup.model == "glm-5-fp8" and sup.reasons == []


def test_the_quantisation_in_the_directory_name_picks_its_own_entry(tmp_path):
    _, sup = served_model(tmp_path, "/data/models/Qwen3.5-397B-A17B-NVFP4")
    assert sup.model == "qwen3.5-397b-a17b-nvfp4"
    _, sup = served_model(tmp_path, "/data/models/Qwen3.5-397B-A17B")
    assert sup.model == "qwen3.5-397b-a17b"


def test_a_path_that_fits_no_single_catalog_repository_is_refused_not_guessed(tmp_path):
    for path in ("/lustre/fsw/models/unknown-dir-fp8", "/models/Twin-70B"):      # none; two repositories
        cks, sup = served_model(tmp_path, path)
        assert cks == [] and sup.model is None and "model_not_in_catalog" in sup.reasons


def test_a_named_repository_still_comes_first(tmp_path):
    cat = catalog(tmp_path)
    assert sc._checkpoints(decided("/lustre/fsw/models/GLM-5-FP8", ["nvidia/GLM-5-NVFP4"]), None, cat)[0] == "nvidia/GLM-5-NVFP4"


def test_a_point_found_from_a_staged_path_names_the_directory_and_the_repository_chosen(tmp_path):
    cat = catalog(tmp_path)
    path = "/lustre/fsw/models/GLM-5-FP8"
    c = decided(path, path)
    cks = sc._checkpoints(c, None, cat)
    sup = sp.check(cat, {"h200"}, checkpoints=cks, base_models={}, hardware="h200", spec_method=None)
    sub = sc.staged_substitution(c, cat, sup.checkpoint)
    assert sub["kind"] == "estimated" and sub["subject"] == "checkpoint_from_staged_path"
    assert path in sub["detail"] and "zai-org/glm-5-fp8" in sub["detail"]
    # A run that named its repository is not given the substitution, even when it also served a staged path.
    named = decided(path, ["zai-org/GLM-5-FP8"])
    cks = sc._checkpoints(named, None, cat)
    assert sc.staged_substitution(named, cat, cks[0]) is None


def test_a_staged_directory_bound_to_its_repository_by_the_runs_harness_resolves_and_cites_the_binding(tmp_path):
    cat = catalog(tmp_path)
    path = "/lustre/fsw/models/dsr1-0528-fp8"
    c = decided(path, path)
    cks = sc._checkpoints(c, None, cat)
    sup = sp.check(cat, {"h200"}, checkpoints=cks, base_models={}, hardware="h200", spec_method=None)
    assert sup.model == "deepseek-r1-0528"
    sub = sc.staged_substitution(c, cat, sup.checkpoint)
    assert "launch_b200-dgxc.sh:19-20" in sub["detail"] and "deepseek-ai/deepseek-r1-0528" in sub["detail"]
    # A catalog without that repository is not given the guess.
    bare = e2e._catalog(tmp_path / "x", {}, {"h200": (8, None)}, {})
    assert bare.repo_of_local_path(path) is None
