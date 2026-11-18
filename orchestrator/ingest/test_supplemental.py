"""Reconstructed launches for units whose own recipe is gone (supplemental.py): which units become points, what the scorer
does with one, and the release translations the launch needs.

Run: python3 -m pytest orchestrator/ingest/test_supplemental.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import contract as c  # noqa: E402
import fields as fl  # noqa: E402
import grade as gr  # noqa: E402
import score as sc  # noqa: E402
import settings as st  # noqa: E402
import stand_in_facts as sif  # noqa: E402
import supplemental as sup  # noqa: E402
import test_score_e2e as e2e  # noqa: E402

IMAGE = "vllm/vllm-openai:v0.10.2"


def _row(i, conc):
    return {"id": i, "model": "llama70b", "hardware": "h100", "precision": "fp8", "framework": "vllm", "benchmark_type": "single_turn",
            "conc": conc, "isl": 1024, "osl": 1024, "spec_method": "none", "disagg": False, "is_multinode": False, "decode_tp": 4,
            "decode_ep": 1, "num_decode_gpu": 4, "date": "2025-10-29", "run_url": "https://github.com/o/r/actions/runs/18924487526",
            "image": None, "recipe_fingerprint": None, "metrics": {"mean_ttft": 0.2, "mean_tpot": 0.01}}


def _unit(commit="c" * 40):
    return {"launch": {"roles": {"aggregated": {"args": {"tensor-parallel-size": 4, "no-enable-prefix-caching": True},
                                                "env": {}}}, "model": {"path": "org/m"},
                       "resources": {"gpus_per_node": 8}},
            "commit": commit, "script": "benchmarks/70b_fp8_h100_docker.sh", "image": IMAGE,
            "substitution": f"recipe reconstructed from InferenceX scripts at {commit}; the run's own recipe is gone; "
                            f"vLLM v0.10.2 modelled as 0.33.0",
            "defaults_stated": ["pipeline-parallel-size=1"], "runner_env_omitted": ["TORCH_CUDA_ARCH_LIST=9.0"]}


def _sources(tmp: Path, errors: dict):
    rows = [_row(1, 4), _row(2, 8), _row(3, 16)]
    dates = c.run_dates(rows)
    units = [c.point_id(c.unit_identity(r, dates)) for r in rows]
    (tmp / "dump-rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (tmp / "match.json").write_text(json.dumps({"points": [{"unit": u, "records": [str(r["id"])]} for u, r in zip(units, rows)]}))
    (tmp / "pull-errors.json").write_text(json.dumps({u: e for u, e in zip(units, errors.values())} if False else
                                                       {units[i]: e for i, e in enumerate(errors.values()) if e}))
    return units


def test_only_a_unit_whose_record_is_gone_becomes_a_point():
    tmp = Path(tempfile.mkdtemp())
    units = _sources(tmp, {"gone": "<HTTPError 404: 'Not Found'>", "flaky": "<HTTPError 502: 'Bad Gateway'>", "held": ""})
    pts, skipped = sup.points({u: _unit() for u in units}, tmp)
    assert [p["point_id"] for p in pts] == [units[0]]
    assert "not a gone record" in skipped[units[1]] and "holds the unit's own record" in skipped[units[2]]
    p = pts[0]
    assert p["files"] == {} and p["identity"]["model"] == "llama70b"
    assert p["supplemental_recipe"]["release"] == "0.10.2" and p["supplemental_recipe"]["launch"]["model"]["path"] == "org/m"


def test_a_410_is_gone_too_and_a_unit_whose_identity_differs_is_left_out():
    tmp = Path(tempfile.mkdtemp())
    units = _sources(tmp, {"a": "<HTTPError 410: 'Gone'>", "b": "", "c": ""})
    pts, _ = sup.points({units[0]: _unit()}, tmp)
    assert len(pts) == 1
    rows = [json.loads(l) for l in (tmp / "dump-rows.jsonl").read_text().splitlines()]
    rows[0]["precision"] = "fp4"          # the row no longer hashes to the unit id
    (tmp / "dump-rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    pts, skipped = sup.points({units[0]: _unit()}, tmp)
    assert pts == [] and "does not hash" in skipped[units[0]]


def _entry(tmp: Path):
    """The e2e fixture's single-turn point with its server log removed and a reconstructed launch attached."""
    entry, env = e2e._setup(tmp, log=e2e.LOG, spec="none", job_log=None)
    entry["files"] = {}
    entry["build"] = {"image": IMAGE, "ref": "v0.10.2", "source": "supplemental", "match": "reconstructed"}
    unit = _unit()
    unit["launch"]["roles"]["aggregated"]["args"] = {"tensor-parallel-size": 1, "max-num-seqs": 16, "max-model-len": 2304,
                                                       "no-enable-prefix-caching": True, "max-num-batched-tokens": 8192,
                                                       "pipeline-parallel-size": 1, "data-parallel-size": 1}
    entry["supplemental_recipe"] = sup.entry_for(unit)
    return entry, env


def test_a_reconstructed_point_is_read_as_the_launch_named_with_its_commit_and_graded_no_higher_than_g4():
    tmp = Path(tempfile.mkdtemp())
    entry, env = _entry(tmp)
    o = sc._score_one(entry, tmp / "pull", tmp / "w", env, simulate=False)
    assert not any(r.startswith("server_log_missing") for r in o.reasons), o.reasons
    texts = [s["detail"] for s in o.subs if s["subject"] == "engine.recipe"]
    assert len(texts) == 1 and texts[0].startswith("recipe reconstructed from InferenceX scripts at " + "c" * 40)
    assert "the run's own recipe is gone" in texts[0] and "vLLM v0.10.2 modelled as 0.33.0" in texts[0]
    assert "pipeline-parallel-size=1" in texts[0] and "TORCH_CUDA_ARCH_LIST=9.0" in texts[0]
    sc.grade_outcome(o, env.engine_release)
    assert o.run_release == "0.10.2" and o.fidelity["grade"] in (gr.G4,), o.fidelity and o.fidelity["grade"]


def test_a_point_without_a_log_and_without_a_reconstructed_launch_is_still_refused_for_its_log():
    tmp = Path(tempfile.mkdtemp())
    entry, env = _entry(tmp)
    del entry["supplemental_recipe"]
    o = sc._score_one(entry, tmp / "pull", tmp / "w", env, simulate=False)
    assert "server_log_missing" in o.reasons and o.fidelity is None


def test_a_point_that_has_its_own_log_ignores_a_reconstructed_launch():
    tmp = Path(tempfile.mkdtemp())
    entry, env = e2e._setup(tmp, log=e2e.LOG, spec="none")
    entry["supplemental_recipe"] = sup.entry_for(_unit())
    o = sc._score_one(entry, tmp / "pull", tmp / "w", env, simulate=False)
    assert all(s["subject"] != "engine.recipe" for s in o.subs)


# ------------------------------------------------------------------------------------- the release translations

def _list(*rows):
    return fl.parse(json.dumps({"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.33.0"}, "fields": list(rows)}))


def _decide_with(flist, **vals):
    r = st.Reading()
    for k, v in vals.items():
        r.add(k.replace("__", "."), v)
    return st.decide(st.merge({"launch_config": r}, {}), flist, "b200", sif.facts_of(8, "10.0"))


def _inert(name):
    return {"name": name, "source": "config", "status": "inert_unproven", "evidence": {"note": "inert; no proof yet"},
            "estimation": {"rule": "leave_unset"}}


def test_the_v0_10_2_pass_config_names_are_the_names_v0_33_0_gave_them_and_the_point_says_so():
    flist = _list(_inert("compilation_config.pass_config.eliminate_noops"), _inert("compilation_config.pass_config.fuse_allreduce_rms"),
                  _inert("compilation_config.pass_config.fuse_attn_quant"))
    d = _decide_with(flist, compilation_config__pass_config__enable_attn_fusion=True,
                     compilation_config__pass_config__enable_fi_allreduce_fusion=True, compilation_config__pass_config__enable_noop=True)
    assert d.reasons == []
    renamed = {x["subject"] for x in d.substitutions if x["kind"] == "resolved_differs"}
    assert renamed == {"compilation_config.pass_config.enable_attn_fusion", "compilation_config.pass_config.enable_fi_allreduce_fusion",
                       "compilation_config.pass_config.enable_noop"}


def test_a_variable_or_flag_v0_33_0_does_not_read_is_left_out_and_named_not_refused():
    d = _decide_with(_list(), env__TORCH_CUDA_ARCH_LIST="9.0", env__VLLM_FLASHINFER_ALLREDUCE_FUSION_THRESHOLDS_MB='{"2":32}',
                     disable_log_requests=True)
    assert d.reasons == []
    left = {x["subject"] for x in d.substitutions if x["kind"] == "estimated"}
    assert left == {"env.TORCH_CUDA_ARCH_LIST", "env.VLLM_FLASHINFER_ALLREDUCE_FUSION_THRESHOLDS_MB", "disable_log_requests"}
