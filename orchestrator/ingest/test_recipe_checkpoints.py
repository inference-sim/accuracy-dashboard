"""The served checkpoint and the draft checkpoint a run's own InferenceX recipe names, when its log
names only local paths (design: the recipe at the run's commit is part of the run's record)."""
import gzip
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pull as pl  # noqa: E402
import recipes as rcp  # noqa: E402
import support as sp  # noqa: E402

SCRIPT = '''#!/usr/bin/env bash
# MiniMax-M3 NVFP4 B300 single-node vLLM recipe with EAGLE3 speculative decoding.
DRAFT_MODEL="Inferact/MiniMax-M3-EAGLE3"
hf download "$DRAFT_MODEL"
'''
ROW = {"framework": "vllm", "precision": "fp4", "image": "vllm/vllm-openai:nightly-1", "hardware": "b300",
       "spec_method": "mtp", "model": "minimaxm3", "run_url": "https://github.com/SemiAnalysisAI/InferenceX/actions/runs/7/attempts/1"}


def recipes_of(models=("nvidia/MiniMax-M3-NVFP4",), scripts=None):
    rc = rcp.Recipes()
    rc.recipes = [{"model": m, "model-prefix": "minimaxm3", "framework": "vllm", "precision": "fp4",
                   "image": "vllm/vllm-openai:nightly-1", "runner": "b300"} for m in models]
    rc.scripts = scripts if scripts is not None else {"benchmarks/single_node/fixed_seq_len/minimaxm3_fp4_b300_mtp.sh": "blob"}
    return rc


class FakeRecipes:
    repo = "SemiAnalysisAI/InferenceX"

    def __init__(self, rc, text=SCRIPT):
        self.rc, self.text = rc, text

    def run_commit(self, run_id):
        return "a" * 40

    def at(self, sha):
        return self.rc

    def script(self, rc, path):
        return self.text


def log(model, draft):
    spec = f", 'speculative_config': {{'method': 'eagle3', 'model': '{draft}', 'num_speculative_tokens': 3}}" if draft else ""
    return f"INFO [api_utils.py:286] non-default args: {{'model': '{model}'{spec}}}\n"


# ---- the script

def test_the_draft_model_is_read_with_its_line_and_only_when_exactly_one_is_set():
    assert rcp.draft_model(SCRIPT) == ("Inferact/MiniMax-M3-EAGLE3", 3)
    assert rcp.draft_model("DRAFT_MODEL=a/b\nDRAFT_MODEL=c/d\n") is None
    assert rcp.draft_model("DRAFT_MODEL=a/b\nDRAFT_MODEL=a/b\n") == ("a/b", 1)
    assert rcp.draft_model("# DRAFT_MODEL=a/b\n") is None


def test_the_script_is_found_by_the_recipes_prefix_precision_hardware_and_spec():
    assert rcp.draft_script(recipes_of(), ROW).endswith("minimaxm3_fp4_b300_mtp.sh")
    assert rcp.draft_script(recipes_of(), {**ROW, "spec_method": "none"}) is None       # no draft model
    assert rcp.draft_script(recipes_of(scripts={}), ROW) is None
    two = {"a/minimaxm3_fp4_b300_mtp.sh": "x", "b/minimaxm3_fp4_b300_mtp.sh": "y"}
    assert rcp.draft_script(recipes_of(scripts=two), ROW) is None                        # ambiguous: none


# ---- the pull records the recipe's draft model whatever the path is called

def test_the_pull_records_the_recipes_draft_model_for_a_local_path_draft():
    d = pl.recipe_draft_checkpoint(ROW, log("/scratch/models/MiniMax-M3-NVFP4", "/data/models/MiniMax-M3-EAGLE3"), FakeRecipes(recipes_of()))
    assert d == {"repo": "Inferact/MiniMax-M3-EAGLE3", "source": "inferencex_recipe", "commit": "a" * 40,
                 "script": "benchmarks/single_node/fixed_seq_len/minimaxm3_fp4_b300_mtp.sh", "line": 3,
                 "logged_path": "/data/models/MiniMax-M3-EAGLE3"}


def test_the_pull_records_nothing_for_a_repo_a_self_draft_or_no_draft():
    f = FakeRecipes(recipes_of())
    assert pl.recipe_draft_checkpoint(ROW, log("/s/M", "Inferact/MiniMax-M3-EAGLE3"), f) is None     # the log names a repo
    assert pl.recipe_draft_checkpoint(ROW, log("/s/M", None), f) is None
    assert pl.recipe_draft_checkpoint(ROW, log("/s/M", "/s/M"), f) is None                          # MTP names the target
    assert pl.recipe_draft_checkpoint(ROW, log("/s/M", "/d/M-EAGLE3"), FakeRecipes(recipes_of(), "no draft here\n")) is None


# ---- the scorer's rule

ENTRY = {"draft_checkpoint": {"repo": "Inferact/MiniMax-M3-EAGLE3"}}


def test_a_path_whose_last_component_equals_the_recipes_repo_name_resolves():
    assert sp.resolve_draft("/data/models/MiniMax-M3-EAGLE3", ["/s/M"], ENTRY) == ("Inferact/MiniMax-M3-EAGLE3", None)
    assert sp.resolve_draft("/data/models/MiniMax-M3-EAGLE3/", ["/s/M"], ENTRY)[0] == "Inferact/MiniMax-M3-EAGLE3"


def test_a_mismatch_between_the_path_and_the_recipe_is_a_value_conflict_naming_both():
    repo, why = sp.resolve_draft("/data/models/MiniMax-M3-EAGLE3-GQA", ["/s/M"], ENTRY)
    assert repo is None and why == ("value_conflict:speculative_config.model: the log names "
                                    "/data/models/MiniMax-M3-EAGLE3-GQA, the recipe Inferact/MiniMax-M3-EAGLE3")


def test_a_local_path_with_no_recipe_draft_is_value_not_recorded_not_drafter_not_in_catalog():
    assert sp.resolve_draft("/data/models/X-EAGLE3", ["/s/M"], {}) == (None, "value_not_recorded:speculative_config.model")


def test_a_repo_a_self_draft_and_no_draft_need_no_recipe():
    assert sp.resolve_draft("Inferact/MiniMax-M3-EAGLE3", [], {}) == ("Inferact/MiniMax-M3-EAGLE3", None)
    assert sp.resolve_draft("/s/M", ["/s/M"], {}) == (None, None)
    assert sp.resolve_draft(None, ["/s/M"], {}) == (None, None)


# ---- the served checkpoint that the recipe and the path disagree on

def test_the_recipe_and_a_served_path_that_name_different_checkpoints_are_a_conflict_not_a_missing_model():
    rc = recipes_of(models=("deepseek-ai/DeepSeek-V4-Pro",))
    row = {**ROW, "model": "dsv4", "spec_method": "none"}
    assert rcp.checkpoint(rc, row, "/scratch/models/DeepSeek-V4-Pro-NVFP4") is None
    assert rcp.conflicting_checkpoint(rc, row, "/scratch/models/DeepSeek-V4-Pro-NVFP4") == "deepseek-ai/DeepSeek-V4-Pro"
    assert rcp.conflicting_checkpoint(rc, row, "/scratch/models/DeepSeek-V4-Pro") is None            # they agree: resolved elsewhere
    two = recipes_of(models=("deepseek-ai/DeepSeek-V4-Pro", "nvidia/DeepSeek-V4-Pro-NVFP4"))
    assert rcp.conflicting_checkpoint(two, row, "/scratch/models/other") is None                      # two recipes: no one to name
    got = pl.recipe_checkpoint_conflict(row, log("/scratch/models/DeepSeek-V4-Pro-NVFP4", None), FakeRecipes(rc))
    assert got == {"repo": "deepseek-ai/DeepSeek-V4-Pro", "source": "inferencex_recipe", "commit": "a" * 40,
                   "served_path": "/scratch/models/DeepSeek-V4-Pro-NVFP4"}
    assert sp.served_conflict({"checkpoint_conflict": got}) == (
        "value_conflict:model: the log serves /scratch/models/DeepSeek-V4-Pro-NVFP4, the recipe deepseek-ai/DeepSeek-V4-Pro")
    assert sp.served_conflict({}) is None
