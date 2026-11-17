"""An SGLang point is scored by the engine its run used (dashboard#110): its server log's `server_args=ServerArgs(...)`
printout and its launch command are read in SGLang's own field names, each field is decided by blis-sglang's field
list, and the point is graded by the same rules (§11.3, §11.4) as a vLLM one. A fake `blis` stands in for the
simulator, as in test_score_e2e.py.

Run: python3 -m pytest orchestrator/ingest/test_sglang_scoring.py
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
import engines  # noqa: E402
import fields as fl  # noqa: E402
import grade as gr  # noqa: E402
import ledger as ldg  # noqa: E402
import ledger_fake  # noqa: E402
import pull as pl  # noqa: E402
import recipes as rcp  # noqa: E402
import score as sc  # noqa: E402
import sglang_settings as ss  # noqa: E402
import test_score_e2e as e2e  # noqa: E402

RELEASE = "0.5.23"
IMAGE = f"lmsysorg/sglang:v{RELEASE}-cu130"

# SGLang prints every ServerArgs field, resolved: page_size, kv_cache_dtype, attention_backend and the seed are what the
# engine chose, not what the run asked for.
LOG = ("[2026-05-19 19:04:35] Setting page size to 64 for DeepSeek DSA.\n"
       "[2026-05-19 19:04:37] server_args=ServerArgs(model_path='org/m', tokenizer_path='org/m', host='0.0.0.0', port=8888, "
       "served_model_name='m', trust_remote_code=True, kv_cache_dtype='bfloat16', mem_fraction_static=0.85, "
       "page_size=64, attention_backend='nsa', tp_size=8, pp_size=1, dp_size=1, random_seed=1026055836, "
       "stream_interval=1, cuda_graph_max_bs=512)\n")
COMMAND = ("python3 -m sglang.launch_server --model-path org/m --host 0.0.0.0 --port 8888 --tp-size 8 "
           "--mem-fraction-static 0.85 --served-model-name m --trust-remote-code")


def _field(name, status, source="config"):
    ev = {"modelled": {"traces": ["core/sched/testdata/golden/t.json"]}, "proven_inert": {"proof": "TestInert"},
          "not_modelled": {"issue": "inference-sim/blis-sglang#49"}}[status]
    return {"name": name, "source": source, "status": status, "evidence": ev, "estimation": {"rule": "none"}}


# blis-sglang's list as the scorer reads it: the fields the oracle covers are modelled, the ones that never reach a
# simulation are proven inert, and the rest of ServerArgs is not modelled.
FIELDS = fl.parse(json.dumps({"kind": "FieldList", "engine": {"kind": "sglang", "version": RELEASE}, "fields": sorted([
    _field("model_path", "modelled"), _field("tp_size", "modelled"), _field("mem_fraction_static", "modelled"),
    _field("page_size", "modelled"), _field("pp_size", "modelled"), _field("dp_size", "modelled"),
    *[_field(n, "proven_inert") for n in ("host", "port", "served_model_name", "trust_remote_code", "tokenizer_path")],
    *[_field(n, "not_modelled") for n in ("kv_cache_dtype", "attention_backend", "stream_interval", "random_seed",
                                          "enable_flashinfer_allreduce_fusion")],
], key=lambda f: (f["name"], f["source"]))}).encode())


def _kit():
    return sc.EngineKit("sglang", RELEASE, FIELDS, "f" * 64, ss.load_declarations())


def _setup(tmp: Path, *, log: str = LOG, command: str | None = COMMAND, framework: str = "sglang"):
    entry, env = e2e._setup(tmp, log=log, spec="none", node_size=8, repo="org/m")
    row = entry["row"]
    row.update(framework=framework, image=IMAGE, decode_tp=8, num_decode_gpu=8)
    entry["build"] = {"image": IMAGE, "commit": None, "source": "custom", "ref": None, "match": "estimated", "why": "custom_build"}
    pdir = tmp / "pull" / "points" / entry["point_id"]
    if command is not None:
        (pdir / "launch_command.gz").write_bytes(gzip.compress(command.encode(), mtime=0))
        entry["files"]["launch_command"] = {"path": "launch_command.gz", "sha256": "0" * 64, "from": "job_log"}
    env.sglang = _kit()
    return entry, env


def _score(tmp, entry, env, name="c1"):
    return e2e._score(tmp, entry, env, tmp / name)


def test_an_sglang_point_with_every_field_accepted_is_graded_by_its_own_engine():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        o, work = _score(tmp, entry, env)
        assert o.fidelity is not None, o.reasons
        assert o.fidelity["grade"] == "G2"          # the run's release is the engine's; every single-turn point names the send gap
        docs = list(yaml.safe_load_all(next((work / "single_turn" / entry["point_id"]).glob("p-*.yaml")).read_text()))
        scen, dep = docs[0], docs[1]
        assert scen["engine"] == {"kind": "sglang", "version": RELEASE} and "engine_version" not in scen
        pool = dep["pools"][0]
        assert pool["parallel"]["tp"] == 8
        # What the run asked for is stated under SGLang's own names, and so is a resolved value of a field the engine
        # models or proves inert (page_size, tokenizer_path); a resolved value of any other field is not.
        assert pool["engine"] == {"model_path": "org/m", "mem_fraction_static": 0.85, "host": "0.0.0.0", "port": 8888,
                                  "served_model_name": "m", "trust_remote_code": True, "page_size": 64,
                                  "tokenizer_path": "org/m"}
        assert o.fidelity["simulator"]["engine"] == {"kind": "sglang", "version": RELEASE}
        assert o.facets["framework"] == "sglang" and "-sglang-tp8-" in o.facets["scenario"]
    finally:
        shutil.rmtree(tmp)


def test_an_sglang_release_the_scorer_runs_is_g2_and_another_is_g4():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        o, _ = _score(tmp, entry, env)
        assert o.run_release == RELEASE and o.fidelity["grade"] == "G2"
        entry["build"]["image"] = entry["row"]["image"] = "lmsysorg/sglang:v0.5.12-cu130"
        o, _ = _score(tmp, entry, env, "c2")
        subs = {s["kind"]: s for s in o.fidelity["substitutions"]}
        assert o.fidelity["grade"] == "G4" and subs["other_release"]["detail"] == f"0.5.12, scored on {RELEASE}"
    finally:
        shutil.rmtree(tmp)


def test_a_field_the_run_set_that_the_list_does_not_model_is_g5_by_its_name():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp, command=COMMAND + " --kv-cache-dtype bfloat16")
        o, _ = _score(tmp, entry, env)
        assert o.g5 == {"code": "field_not_modelled", "subject": "kv_cache_dtype"}
    finally:
        shutil.rmtree(tmp)


def test_a_flag_the_release_does_not_declare_is_g5_field_not_in_release():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp, command=COMMAND + " --cuda-graph-max-bs-renamed 192")
        o, _ = _score(tmp, entry, env)
        assert o.g5 == {"code": "field_not_in_release", "subject": "cuda_graph_max_bs_renamed"}
    finally:
        shutil.rmtree(tmp)


def test_a_value_the_engine_resolved_is_not_taken_as_set_by_the_run():
    # kv_cache_dtype, attention_backend and the seed are printed away from their defaults, but the command names none.
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        o, _ = _score(tmp, entry, env)
        assert o.fidelity is not None and o.g5 is None
        by_arg = {a["arg"]: a for a in o.fidelity["args"]}
        assert by_arg["kv_cache_dtype"]["match"] == "resolved_not_stated"
    finally:
        shutil.rmtree(tmp)


def test_a_flag_at_the_fields_default_is_not_a_request():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp, command=COMMAND + " --stream-interval 1")
        o, _ = _score(tmp, entry, env)
        assert o.fidelity is not None, o.reasons
    finally:
        shutil.rmtree(tmp)


def test_a_point_with_no_launch_command_is_g5_value_not_recorded_not_guessed_from_the_printout():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp, command=None)
        o, _ = _score(tmp, entry, env)
        assert o.g5 == {"code": "value_not_recorded", "subject": "launch_command"}
    finally:
        shutil.rmtree(tmp)


def test_an_environment_variable_left_to_the_shell_is_refused_by_name():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp, command="export SGLANG_FOO=$BAR\n" + COMMAND)
        o, _ = _score(tmp, entry, env)
        assert o.g5 == {"code": "value_not_recorded", "subject": "env.SGLANG_FOO"}
    finally:
        shutil.rmtree(tmp)


def test_without_an_sglang_field_list_the_points_stay_g5_field_unclassified():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        env.sglang = None
        o, _ = _score(tmp, entry, env)
        assert o.g5 == {"code": "field_unclassified", "subject": "sglang: no field list published"}
    finally:
        shutil.rmtree(tmp)


def test_a_prefill_decode_sglang_point_is_not_scored_yet_and_says_so():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        entry["row"]["disagg"] = True
        o, _ = _score(tmp, entry, env)
        assert o.g5 == {"code": "topology_unsupported", "subject": "sglang_disaggregated"}
    finally:
        shutil.rmtree(tmp)


def test_a_vllm_point_is_unchanged_when_sglang_is_scored_too():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = e2e._setup(tmp)
        env.sglang = _kit()
        o, work = _score(tmp, entry, env)
        scen = next((work / "single_turn" / entry["point_id"]).glob("p-*.yaml")).read_text()
        assert o.fidelity["simulator"]["engine"] == {"kind": "vllm", "version": "0.31.0"} and "engine_version: 0.31.0" in scen
    finally:
        shutil.rmtree(tmp)


# ------------------------------------------------------------------ reading a launch command

def test_a_launch_script_that_launches_by_branch_or_by_expansion_is_refused_by_name():
    one = "python3 -m sglang.launch_server --tp-size 8\n"
    assert ss.launch_command_of(one) == (one.strip(), None)
    assert ss.launch_command_of(one + "if x; then\n  python3 -m sglang.launch_server --tp-size 4\nfi\n") == (None, ss.AMBIGUOUS_COMMAND)
    assert ss.launch_command_of('python3 -m sglang.launch_server ${EP:+--ep-size $EP}\n') == (None, ss.SHELL_EXPANSION)
    assert ss.launch_command_of("echo hi\n") == (None, ss.NO_COMMAND)


def test_a_command_is_read_through_blis_sglangs_declarations():
    decl = ss.load_declarations()
    cmd, _ = ss.launch_command_of("export SGLANG_X=1\npython3 -m sglang.launch_server \\\n  --model-path \"$MODEL\" \\\n"
                                  "  --tensor-parallel-size 8 --enable-dp-attention --no-enable-radix-cache-nope \\\n"
                                  "  --chunked-prefill-size=4096 > log 2>&1 &\n")
    r = ss.read_launch_command(cmd, decl)
    assert r.values["tp_size"] == [8]                    # the alias of --tp-size
    assert r.values["enable_dp_attention"] == [True]     # a flag SGLang keeps by hand
    assert r.values["chunked_prefill_size"] == [4096]
    assert r.values["model_path"] == [None]              # left to the shell: a request with the value the log resolved
    assert r.values["env.SGLANG_X"] == ["1"]


# ------------------------------------------------------------------ the pull

def _gh(download):
    """A GitHub whose run holds no artifact and whose job logs have expired."""
    return types.SimpleNamespace(repo="o/r", list_cached=lambda run: [], download=download,
                                 run=lambda rid: {"sha": "c" * 40, "date": "2026-10-01T00:00:00Z"},
                                 job_logs_cached=lambda rid, attempt: ({}, 1))


def _row(**kw):
    return {"id": "1", "model": "m", "hardware": "h200", "precision": "fp8", "framework": "sglang",
            "benchmark_type": "single_turn", "conc": 4, "isl": 1024, "osl": 1024, "disagg": False, "is_multinode": False,
            "spec_method": "none", "date": "2026-10-01", "image": IMAGE, "decode_tp": 8,
            "run_url": "https://github.com/o/r/actions/runs/1", "metrics": {}, **kw}


def test_the_pull_fetches_an_sglang_points_log_and_freezes_the_command_of_its_runs_script(tmp_path):
    row = _row()
    lg = ldg.load(ledger_fake.write(tmp_path / "ledger", [row]))
    (point,) = pl.place([row], lg).points
    script = ("#!/usr/bin/env bash\nSERVER_LOG=/workspace/server.log\nset -x\npython3 -m sglang.launch_server \\\n"
              "  --model-path \"$MODEL\" \\\n  --tp-size \"$TP\" \\\n  --mem-fraction-static 0.85 > \"$SERVER_LOG\" 2>&1 &\n")
    rc = rcp.Recipes(recipes=[{"model": "org/m", "framework": "sglang", "precision": "fp8", "image": IMAGE, "runner": "h200",
                               "model-prefix": "m"}],
                     scripts={"benchmarks/single_node/m_fp8_h200.sh": "s1", "benchmarks/single_node/m_fp8_h200_trt.sh": "s2"})
    recipes = types.SimpleNamespace(repo="o/r", run_commit=lambda run: "c" * 40, at=lambda sha: rc,
                                    script=lambda rc_, path: script)

    def boom(*a, **k):
        raise AssertionError("artifacts were listed")
    gh = _gh(download=boom)
    resolver = types.SimpleNamespace(resolve=lambda image, log: types.SimpleNamespace(record=lambda: {"image": image}))
    fetch = lambda url: json.dumps({"serverLog": LOG}).encode()
    entry = pl.freeze_point(point, resolver=resolver, gh=gh, fetch=fetch, out=tmp_path / "out", recipes=recipes,
                            scoring=engines.DEFAULT_SCORING | {engines.SGLANG})
    assert "server_log" in entry["files"] and "launch_command" in entry["files"]
    assert entry["launch_command"] == {"from": "script", "repo": "o/r", "commit": "c" * 40,
                                       "path": "benchmarks/single_node/m_fp8_h200.sh"}
    text = gzip.decompress((tmp_path / "out" / "points" / entry["point_id"] / "launch_command.gz").read_bytes()).decode()
    assert ss.read_launch_command(text, ss.load_declarations()).values["tp_size"] == [None]
    # Without the SGLang field list the pull fetches nothing and the label's reason stands (test_engines.py).
    entry = pl.freeze_point(point, resolver=resolver, gh=gh, fetch=boom, out=tmp_path / "out2", recipes=recipes)
    assert entry["reasons"] == [engines.SGLANG_FIELD_LIST_UNPUBLISHED] and entry["files"] == {}


def test_a_run_whose_script_names_no_single_launch_is_recorded_with_the_reason(tmp_path):
    row = _row()
    lg = ldg.load(ledger_fake.write(tmp_path / "ledger", [row]))
    (point,) = pl.place([row], lg).points
    rc = rcp.Recipes(recipes=[], scripts={})
    recipes = types.SimpleNamespace(repo="o/r", run_commit=lambda run: "c" * 40, at=lambda sha: rc, script=None)
    gh = _gh(download=None)
    resolver = types.SimpleNamespace(resolve=lambda image, log: types.SimpleNamespace(record=lambda: {"image": image}))
    entry = pl.freeze_point(point, resolver=resolver, gh=gh, fetch=lambda url: json.dumps({"serverLog": LOG}).encode(),
                            out=tmp_path / "out", recipes=recipes, scoring=engines.DEFAULT_SCORING | {engines.SGLANG})
    assert "launch_command" not in entry["files"] and entry["launch_command_reason"] == "script_not_found"


# ------------------------------------------------------------------ grading and the contract

def test_the_release_of_an_official_sglang_image_is_its_tag():
    assert gr.run_release({"image": IMAGE}, None).version == RELEASE
    assert gr.run_release({"image": "lmsysorg/sglang:v0.5.12"}, None).version == "0.5.12"
    assert gr.run_release({"image": "lmsysorg/sglang:dev-cu13"}, None).nightly_or_custom


def test_a_run_that_scores_two_engines_holds_each_point_to_its_own_release():
    sim = lambda kind, v: {"build": "v0.1.0", "engine": {"kind": kind, "version": v}, "harness_commit": "a" * 40}
    pts = [{"point_id": "a" * 12, "grade": "G2", "substitutions": [{"kind": "send_gap"}], "simulator": sim("vllm", "0.32.0"),
            "build": {"release": "0.32.0"}},
           {"point_id": "b" * 12, "grade": "G2", "substitutions": [{"kind": "send_gap"}], "simulator": sim("sglang", RELEASE),
            "build": {"release": RELEASE}}]
    assert gr.check(pts, "0.32.0") != []                                  # one release for the whole run: refused
    assert gr.check(pts, {"vllm": "0.32.0", "sglang": RELEASE}) == []
    pts[1]["build"]["release"] = "0.5.12"
    assert any("graded G2" in p for p in gr.check(pts, {"vllm": "0.32.0", "sglang": RELEASE}))


def test_a_field_list_or_declarations_of_another_release_than_the_stack_runs_is_refused(tmp_path):
    import stack as sk
    stack = types.SimpleNamespace(engine=lambda kind: "0.5.24")
    f = tmp_path / "fields.json"
    f.write_text(json.dumps({"kind": "FieldList", "engine": {"kind": "sglang", "version": RELEASE}, "fields": []}))
    with pytest.raises(fl.FieldsError, match="runs sglang 0.5.24"):
        sc.read_sglang_kit(f, stack)
    stack = types.SimpleNamespace(engine=lambda kind: RELEASE)
    assert sc.read_sglang_kit(f, stack).release == RELEASE
    d = tmp_path / "decl.json"
    d.write_text(json.dumps({"engine": {"kind": "sglang", "version": "0.5.12"}, "fields": {}}))
    with pytest.raises(fl.FieldsError, match="declarations are for"):
        sc.read_sglang_kit(f, stack, d)


def test_recipes_are_read_from_a_local_clone_and_a_missing_commit_is_fetched_by_its_sha(tmp_path):
    import subprocess
    ident = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]

    def git(*a, cwd=None):
        return subprocess.run(["git", *ident, *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()
    src = tmp_path / "src"
    src.mkdir()
    git("init", "-q", "-b", "main", cwd=src)
    git("config", "uploadpack.allowAnySHA1InWant", "true", cwd=src)
    (src / "benchmarks" / "single_node").mkdir(parents=True)
    (src / "benchmarks" / "single_node" / "m_fp8_h200.sh").write_text("python3 -m sglang.launch_server --tp-size 8\n")
    git("add", "-A", cwd=src)
    git("commit", "-q", "-m", "a", cwd=src)
    clone = tmp_path / "clone.git"
    git("clone", "-q", "--bare", str(src), str(clone))
    (src / "benchmarks" / "single_node" / "m_fp8_h200.sh").write_text("python3 -m sglang.launch_server --tp-size 4\n")
    git("commit", "-q", "-am", "b", cwd=src)
    later = git("rev-parse", "HEAD", cwd=src)
    rc_src = rcp.GitRecipes(None, "o/r", clone)
    rc = rc_src.at(later)               # not in the clone: fetched, then read
    assert rc_src.script(rc, "benchmarks/single_node/m_fp8_h200.sh").strip().endswith("--tp-size 4")
    with pytest.raises(rcp.RecipesUnavailable):
        rcp.GitRecipes(None, "o/r", clone).at("0" * 40)
