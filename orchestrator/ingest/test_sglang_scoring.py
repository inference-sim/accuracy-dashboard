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
        assert scen["engine"] == {"kind": "sglang"} and "engine_version" not in scen
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


def test_a_malformed_environment_line_is_this_runs_problem_not_the_nights():
    # COV-1: an unbalanced quote in an export line must become a named problem on the run, not an exception that
    # aborts the scoring of every run after it.
    decl = ss.load_declarations()
    r = ss.read_launch_command("export FOO='\npython3 -m sglang.launch_server --tensor-parallel-size 8\n", decl)
    assert any(p.startswith("launch_config:") for p in r.problems), r.problems
    assert r.values["tp_size"] == [8]                    # the lines after it are still read


def test_a_run_with_a_malformed_environment_line_is_graded_g5_and_the_night_goes_on():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp, command="export FOO='\n" + COMMAND)
        o, _ = _score(tmp, entry, env)                  # raised ValueError before the fix
        assert o.g5 == {"code": "value_conflict", "subject": "server_log_unreadable"}, o.g5
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


def test_a_prefill_decode_sglang_point_with_no_recipe_is_refused_for_its_missing_recipe_not_for_being_sglang():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        entry["row"]["disagg"] = True
        o, _ = _score(tmp, entry, env)
        assert not any(r["subject"] == "sglang_disaggregated" for r in o.g5_reasons)
        assert {"code": "value_not_recorded", "subject": "not_frozen"} in o.g5_reasons, o.g5_reasons      # recipe_unresolved:not_frozen
    finally:
        shutil.rmtree(tmp)


def test_a_vllm_point_is_unchanged_when_sglang_is_scored_too():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = e2e._setup(tmp)
        env.sglang = _kit()
        o, work = _score(tmp, entry, env)
        scen = next((work / "single_turn" / entry["point_id"]).glob("p-*.yaml")).read_text()
        import yaml
        assert o.fidelity["simulator"]["engine"] == {"kind": "vllm", "version": "0.31.0"}
        # the scenario states the engine kind alone (SIM-1); the fidelity record names the release
        assert next(d for d in yaml.safe_load_all(scen) if d and d.get("kind") == "Scenario")["engine"] == {"kind": "vllm"} and "engine_version" not in scen
    finally:
        shutil.rmtree(tmp)


# ------------------------------------------------------------------ reading a launch command

def test_a_launch_script_that_launches_by_branch_or_by_expansion_is_refused_by_name():
    one = "python3 -m sglang.launch_server --tp-size 8\n"
    assert ss.launch_command_of(one) == (one.strip(), None)
    assert ss.launch_command_of(one + "if x; then\n  python3 -m sglang.launch_server --tp-size 4 --enable-dp-attention\nfi\n") == (None, ss.AMBIGUOUS_COMMAND)
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


def test_the_launch_script_is_the_single_turn_script_of_the_rows_model_framework_precision_and_runner():
    recipe = lambda **kw: {"model": "org/m", "model-prefix": "m", "framework": "sglang", "precision": "fp8",
                           "runner": "h200-dgxc", "image": "x/y:other-image", **kw}
    scripts = {"benchmarks/single_node/fixed_seq_len/m_fp8_h200.sh": "a", "benchmarks/single_node/agentic/m_fp8_h200.sh": "b",
               "benchmarks/single_node/other_fp8_h200.sh": "c", "benchmarks/single_node/m_fp8_h200_mtp.sh": "d"}
    rc = rcp.Recipes(recipes=[recipe(), recipe(**{"model-prefix": "other", "model": "org/o"})], scripts=scripts)
    row = _row(model="m")
    # The recipe pins another image than the run reports, the agentic copy is another script, and a neighbour model's
    # recipe does not lend its prefix.
    assert rcp.launch_script(rc, row) == "benchmarks/single_node/fixed_seq_len/m_fp8_h200.sh"
    assert rcp.launch_script(rc, _row(model="m", spec_method="mtp")) == "benchmarks/single_node/m_fp8_h200_mtp.sh"
    assert rcp.launch_script(rc, _row(model="unknown")) is None
    assert rcp.launch_script(rc, _row(model="m", framework="vllm")) is None


def test_a_parallel_size_the_list_does_not_model_is_refused_as_that_field_not_as_a_missing_value():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        fields = json.loads(json.dumps({"kind": "FieldList", "engine": {"kind": "sglang", "version": RELEASE},
                                        "fields": [{**_field(f.name, f.status, f.source)} for f in FIELDS.fields.values()]}))
        for f in fields["fields"]:
            if f["name"] == "dp_size":
                f.update(_field("dp_size", "not_modelled"))
        env.sglang = sc.EngineKit("sglang", RELEASE, fl.parse(json.dumps(fields).encode()), "f" * 64, ss.load_declarations())
        o, _ = _score(tmp, entry, env)
        assert o.g5 == {"code": "field_not_modelled", "subject": "dp_size"}
    finally:
        shutil.rmtree(tmp)


def test_an_unlisted_sglang_variable_is_refused_by_name():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp, command="export MODEL_PATH=/models/m\nexport SGLANG_NOT_IN_THIS_RELEASE=1\n" + COMMAND)
        o, _ = _score(tmp, entry, env)
        assert o.g5 == {"code": "field_not_in_release", "subject": "env.SGLANG_NOT_IN_THIS_RELEASE"}
    finally:
        shutil.rmtree(tmp)


def test_a_launch_scripts_own_helper_variables_are_not_the_engines():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp, command="export MODEL_PATH=$MODEL\nexport LOG_DIR=/workspace\n" + COMMAND)
        o, _ = _score(tmp, entry, env)
        assert o.fidelity is not None, o.reasons
    finally:
        shutil.rmtree(tmp)


def test_a_flag_an_earlier_release_had_is_read_as_the_field_that_replaced_it_and_named():
    # --cuda-graph-max-bs is v0.5.14's deprecated alias of --cuda-graph-max-bs-decode, which v0.5.23 removed. 92 of the 142
    # measured points pass it; without the translation each is field_not_in_release whatever the engine models.
    tmp = Path(tempfile.mkdtemp())
    try:
        fields = [{**_field(f.name, f.status, f.source)} for f in FIELDS.fields.values()] + [_field("cuda_graph_max_bs_decode", "modelled")]
        fields.sort(key=lambda f: (f["name"], f["source"]))
        entry, env = _setup(tmp, command=COMMAND + " --cuda-graph-max-bs 192")
        env.sglang = sc.EngineKit("sglang", RELEASE, fl.parse(json.dumps(
            {"kind": "FieldList", "engine": {"kind": "sglang", "version": RELEASE}, "fields": fields}).encode()), "f" * 64,
            ss.load_declarations())
        o, work = _score(tmp, entry, env)
        assert o.fidelity is not None, o.reasons
        sub = next(s for s in o.fidelity["substitutions"] if s["subject"] == "cuda_graph_max_bs")
        assert sub["kind"] == "resolved_differs" and "cuda_graph_max_bs_decode=192" in sub["detail"]
        dep = list(yaml.safe_load_all(next((work / "single_turn" / entry["point_id"]).glob("p-*.yaml")).read_text()))[1]
        assert dep["pools"][0]["engine"]["cuda_graph_max_bs_decode"] == 192
    finally:
        shutil.rmtree(tmp)


def test_the_nsa_backend_flags_of_an_earlier_release_are_read_as_the_dsa_fields_that_replaced_them_and_named():
    # SGLang PR #25821 (8131641bc66, v0.5.13) renamed --nsa-prefill-backend and --nsa-decode-backend to --dsa-*-backend with the
    # same choices and kept the old flags as deprecated aliases; PR #38375 removed them before v0.5.23. The GLM-5 recipes on
    # B200 and B300 still pass the old names: 30 development points were field_not_in_release whatever the engine models.
    tmp = Path(tempfile.mkdtemp())
    try:
        fields = [{**_field(f.name, f.status, f.source)} for f in FIELDS.fields.values()] + [
            _field("dsa_prefill_backend", "modelled"), _field("dsa_decode_backend", "modelled")]
        fields.sort(key=lambda f: (f["name"], f["source"]))
        entry, env = _setup(tmp, command=COMMAND + " --nsa-prefill-backend trtllm --nsa-decode-backend flashmla_kv")
        env.sglang = sc.EngineKit("sglang", RELEASE, fl.parse(json.dumps(
            {"kind": "FieldList", "engine": {"kind": "sglang", "version": RELEASE}, "fields": fields}).encode()), "f" * 64,
            ss.load_declarations())
        o, work = _score(tmp, entry, env)
        assert o.fidelity is not None, o.reasons
        subs = {s["subject"]: s for s in o.fidelity["substitutions"]}
        assert subs["nsa_prefill_backend"]["kind"] == "resolved_differs" and "dsa_prefill_backend=trtllm" in subs["nsa_prefill_backend"]["detail"]
        assert subs["nsa_decode_backend"]["kind"] == "resolved_differs" and "dsa_decode_backend=flashmla_kv" in subs["nsa_decode_backend"]["detail"]
        dep = list(yaml.safe_load_all(next((work / "single_turn" / entry["point_id"]).glob("p-*.yaml")).read_text()))[1]
        assert dep["pools"][0]["engine"]["dsa_prefill_backend"] == "trtllm"
        assert dep["pools"][0]["engine"]["dsa_decode_backend"] == "flashmla_kv"
    finally:
        shutil.rmtree(tmp)


def test_an_old_flag_is_still_read_as_its_successor_when_the_log_of_the_later_release_prints_the_successor_resolved():
    # A nightly image after the rename prints dsa_prefill_backend and dsa_decode_backend in its server_args while the recipe
    # still passes the nsa flags: the log's value is the engine's resolution, not a request, so it must not stop the
    # translation of what the run asked for (7 development points were refused field_not_in_release for it).
    log = LOG.replace("cuda_graph_max_bs=512)", "cuda_graph_max_bs=512, dsa_prefill_backend='flashmla_sparse', dsa_decode_backend='fa3')")
    tmp = Path(tempfile.mkdtemp())
    try:
        fields = [{**_field(f.name, f.status, f.source)} for f in FIELDS.fields.values()] + [
            _field("dsa_prefill_backend", "modelled"), _field("dsa_decode_backend", "modelled")]
        fields.sort(key=lambda f: (f["name"], f["source"]))
        entry, env = _setup(tmp, log=log, command=COMMAND + " --nsa-prefill-backend trtllm --nsa-decode-backend trtllm")
        env.sglang = sc.EngineKit("sglang", RELEASE, fl.parse(json.dumps(
            {"kind": "FieldList", "engine": {"kind": "sglang", "version": RELEASE}, "fields": fields}).encode()), "f" * 64,
            ss.load_declarations())
        o, work = _score(tmp, entry, env)
        assert o.fidelity is not None, o.reasons
        dep = list(yaml.safe_load_all(next((work / "single_turn" / entry["point_id"]).glob("p-*.yaml")).read_text()))[1]
        assert dep["pools"][0]["engine"]["dsa_prefill_backend"] == "trtllm"
        assert dep["pools"][0]["engine"]["dsa_decode_backend"] == "trtllm"
    finally:
        shutil.rmtree(tmp)


def test_the_mamba_strategy_flag_of_an_earlier_release_is_read_as_the_field_that_replaced_it_with_its_old_auto_resolved():
    # v0.5.13 resolved --mamba-scheduler-strategy auto to no_buffer; v0.5.14's auto can choose extra_buffer, so an old auto is
    # stated as the no_buffer the run got. A value that is already a strategy keeps its meaning.
    for given, stated in (("auto", "no_buffer"), ("extra_buffer", "extra_buffer")):
        tmp = Path(tempfile.mkdtemp())
        try:
            fields = [{**_field(f.name, f.status, f.source)} for f in FIELDS.fields.values()] + [
                _field("mamba_radix_cache_strategy", "modelled")]
            fields.sort(key=lambda f: (f["name"], f["source"]))
            entry, env = _setup(tmp, command=COMMAND + f" --mamba-scheduler-strategy {given}")
            env.sglang = sc.EngineKit("sglang", RELEASE, fl.parse(json.dumps(
                {"kind": "FieldList", "engine": {"kind": "sglang", "version": RELEASE}, "fields": fields}).encode()), "f" * 64,
                ss.load_declarations())
            o, work = _score(tmp, entry, env)
            assert o.fidelity is not None, o.reasons
            sub = next(s for s in o.fidelity["substitutions"] if s["subject"] == "mamba_scheduler_strategy")
            assert sub["kind"] == "resolved_differs" and f"mamba_radix_cache_strategy={stated}" in sub["detail"]
            dep = list(yaml.safe_load_all(next((work / "single_turn" / entry["point_id"]).glob("p-*.yaml")).read_text()))[1]
            assert dep["pools"][0]["engine"]["mamba_radix_cache_strategy"] == stated
        finally:
            shutil.rmtree(tmp)


def _score_with_field(extra_command, field_name, prefix=""):
    tmp = Path(tempfile.mkdtemp())
    try:
        fields = [{**_field(f.name, f.status, f.source)} for f in FIELDS.fields.values()] + [_field(field_name, "modelled")]
        fields.sort(key=lambda f: (f["name"], f["source"]))
        entry, env = _setup(tmp, command=prefix + COMMAND + extra_command)
        env.sglang = sc.EngineKit("sglang", RELEASE, fl.parse(json.dumps(
            {"kind": "FieldList", "engine": {"kind": "sglang", "version": RELEASE}, "fields": fields}).encode()), "f" * 64,
            ss.load_declarations())
        o, work = _score(tmp, entry, env)
        dep = list(yaml.safe_load_all(next((work / "single_turn" / entry["point_id"]).glob("p-*.yaml")).read_text()))[1] \
            if o.fidelity is not None else None
        return o, dep
    finally:
        shutil.rmtree(tmp)


def test_the_removed_piecewise_flag_is_the_prefill_graph_backend_disabled_and_named():
    o, dep = _score_with_field(" --disable-piecewise-cuda-graph", "cuda_graph_backend_prefill")
    assert o.fidelity is not None, o.reasons
    sub = next(s for s in o.fidelity["substitutions"] if s["subject"] == "disable_piecewise_cuda_graph")
    assert sub["kind"] == "resolved_differs" and "cuda_graph_backend_prefill=disabled" in sub["detail"]
    assert dep["pools"][0]["engine"]["cuda_graph_backend_prefill"] == "disabled"


def test_an_env_variable_no_sglang_release_reads_is_left_out_and_named():
    o, dep = _score_with_field("", "cuda_graph_backend_prefill", prefix="export SGLANG_ENABLE_FLASHINFER_GEMM=1\n")
    assert o.fidelity is not None, o.reasons
    sub = next(s for s in o.fidelity["substitutions"] if s["subject"] == "env.SGLANG_ENABLE_FLASHINFER_GEMM")
    assert sub["kind"] == "estimated" and "no SGLang release" in sub["detail"]
    assert "SGLANG_ENABLE_FLASHINFER_GEMM" not in json.dumps(dep["pools"][0]["engine"])


def test_a_json_text_stated_for_a_str_field_stays_the_text_the_engine_takes():
    # --model-loader-extra-config '{"enable_multithread_load": true}': SGLang's field is a str holding JSON (its log prints
    # model_loader_extra_config='{}'), so the scenario must carry the text; parsed into a map it is refused by the engine
    # ("is not a string"), which refused 20 development points.
    tmp = Path(tempfile.mkdtemp())
    try:
        fields = [{**_field(f.name, f.status, f.source)} for f in FIELDS.fields.values()] + [
            _field("model_loader_extra_config", "modelled")]
        fields.sort(key=lambda f: (f["name"], f["source"]))
        entry, env = _setup(tmp, command=COMMAND + " --model-loader-extra-config '{\"enable_multithread_load\": true}'")
        env.sglang = sc.EngineKit("sglang", RELEASE, fl.parse(json.dumps(
            {"kind": "FieldList", "engine": {"kind": "sglang", "version": RELEASE}, "fields": fields}).encode()), "f" * 64,
            ss.load_declarations())
        o, work = _score(tmp, entry, env)
        assert o.fidelity is not None, o.reasons
        dep = list(yaml.safe_load_all(next((work / "single_turn" / entry["point_id"]).glob("p-*.yaml")).read_text()))[1]
        assert dep["pools"][0]["engine"]["model_loader_extra_config"] == '{"enable_multithread_load": true}'
    finally:
        shutil.rmtree(tmp)


def _config(tmp, cfg):
    d = tmp / "catalog" / "models" / "m"
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text(json.dumps(cfg))


def test_sglangs_context_length_is_the_checkpoints_by_its_own_rule(tmp_path):
    # get_context_length: the first key, times the scaling factor unless the scaling names its original window or is llama3.
    _config(tmp_path, {"max_position_embeddings": 131072})
    assert ss.context_window(tmp_path / "catalog", "m") == 131072
    _config(tmp_path, {"max_position_embeddings": 163840, "rope_scaling": {"type": "yarn", "factor": 40.0,
                                                                          "original_max_position_embeddings": 4096}})
    assert ss.context_window(tmp_path / "catalog", "m") == 163840          # the original window is named: factor 1
    _config(tmp_path, {"text_config": {"max_position_embeddings": 32768, "rope_scaling": {"factor": 4.0}}})
    assert ss.context_window(tmp_path / "catalog", "m") == 131072          # a bare factor multiplies
    _config(tmp_path, {"seq_length": 4096, "max_position_embeddings": 99})
    assert ss.context_window(tmp_path / "catalog", "m") == 4096            # key order is SGLang's
    _config(tmp_path, {"hidden_size": 8})
    assert ss.context_window(tmp_path / "catalog", "m") is None            # SGLang's 2048 fallback is not stated
    assert ss.context_window(tmp_path / "nowhere", "m") is None


def test_a_scenario_states_the_checkpoints_context_length_when_the_run_set_none_and_the_run_s_when_it_did():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        _config(tmp, {"max_position_embeddings": 131072})
        o, work = _score(tmp, entry, env)
        assert o.fidelity is not None, o.reasons
        dep = list(yaml.safe_load_all(next((work / "single_turn" / entry["point_id"]).glob("p-*.yaml")).read_text()))[1]
        assert dep["pools"][0]["engine"]["context_length"] == 131072
        sub = next(s for s in o.fidelity["substitutions"] if s["subject"] == "context_length")
        assert sub["kind"] == "estimated" and "131072" in sub["detail"]
        # A context length the run set is the run's own; nothing is estimated.
        fields = [{**_field(f.name, f.status, f.source)} for f in FIELDS.fields.values()] + [_field("context_length", "modelled")]
        fields.sort(key=lambda f: (f["name"], f["source"]))
        env.sglang = sc.EngineKit("sglang", RELEASE, fl.parse(json.dumps(
            {"kind": "FieldList", "engine": {"kind": "sglang", "version": RELEASE}, "fields": fields}).encode()), "f" * 64,
            ss.load_declarations())
        (tmp / "pull" / "points" / entry["point_id"] / "launch_command.gz").write_bytes(
            gzip.compress((COMMAND + " --context-length 8192").encode(), mtime=0))
        o, work = _score(tmp, entry, env, "c2")
        dep = list(yaml.safe_load_all(next((work / "single_turn" / entry["point_id"]).glob("p-*.yaml")).read_text()))[1]
        assert dep["pools"][0]["engine"]["context_length"] == 8192
        assert not [s for s in o.fidelity["substitutions"] if s["subject"] == "context_length"]
    finally:
        shutil.rmtree(tmp)


BRANCHING = """if [[ $ISL -eq 1024 && $OSL -eq 1024 ]]; then
    python3 -m sglang.launch_server --model-path $MODEL --tensor-parallel-size=$TP \\
    --max-running-requests 512 --cuda-graph-max-bs 512 --stream-interval 10 $EVAL_CONTEXT_ARGS > $SERVER_LOG 2>&1 &
else
    python3 -m sglang.launch_server --model-path $MODEL --tensor-parallel-size=$TP \\
    --max-running-requests 256 --cuda-graph-max-bs 256 --stream-interval 10 $EVAL_CONTEXT_ARGS > $SERVER_LOG 2>&1 &
fi
"""
EXPANDING = """python3 -m sglang.launch_server --model-path=$MODEL --stream-interval 50 \\
  --scheduler-recv-interval $( [[ $CONC -gt 4 ]] && echo 30 || echo 10 ) \\
  --context-length $((ISL + OSL + 20)) > $SERVER_LOG 2>&1 &
"""


def test_a_script_whose_branches_name_the_same_flags_is_read_with_the_branched_values_left_to_the_log():
    cmd, why = ss.launch_command_of(BRANCHING)
    assert why is None
    r = ss.read_launch_command(cmd, ss.load_declarations())
    assert r.values["max_running_requests"] == [None] and r.values["cuda_graph_max_bs"] == [None]   # the log says which
    assert r.values["stream_interval"] == [10]                                                       # the same in both


def test_a_script_whose_branches_name_different_flags_is_still_refused():
    other = BRANCHING.replace("--stream-interval 10 $EVAL", "--disable-radix-cache $EVAL", 1)
    assert ss.launch_command_of(other) == (None, ss.AMBIGUOUS_COMMAND)


def test_a_flag_whose_value_the_shell_computes_is_named_with_its_value_left_to_the_log():
    cmd, why = ss.launch_command_of(EXPANDING)
    assert why is None
    r = ss.read_launch_command(cmd, ss.load_declarations())
    assert r.values["scheduler_recv_interval"] == [None] and r.values["context_length"] == [None]
    assert r.values["stream_interval"] == [50]


def test_an_expansion_that_decides_whether_a_flag_is_set_is_still_refused():
    assert ss.launch_command_of("python3 -m sglang.launch_server $( [[ $X ]] && echo --ep-size 4 ) --tp-size 2\n") == (None, ss.SHELL_EXPANSION)
