"""Tests of the first-party corpus scorer (corpus.py), on a synthetic corpus written here and a fake simulator."""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ingest"))
import corpus as cp  # noqa: E402
import fields as fl  # noqa: E402

N = 11
ENGINE = {"max_num_seqs": 64, "kv_cache_dtype": "auto"}


def result(rows_, n=N):
    return {"kind": "Result", "schema_version": 3, "request_rows": rows_,
            "requests": {"generated": n, "completed": n, "length_capped": 0},
            "selected_entries": {"coefficients": [{"set": "s", "name": "n", "method": "measured"}]}}


def req(i, arrival_s, ttft_ms, tpot_ms, out=101, prompt=1000, cached=0, fate="completed", itl=True):
    r = {"id": f"request_{i}", "fate": fate, "arrival_us": int(arrival_s * 1e6), "ttft_us": int(ttft_ms * 1000),
         "tpot_us": tpot_ms * 1000, "e2e_us": int((ttft_ms + (out - 1) * tpot_ms) * 1000),
         "prompt_tokens": prompt, "output_tokens": out, "cached_local_tokens": cached}
    if itl:
        # a quarter of the gaps 2.5 times the TPOT and the rest half of it: their mean is the TPOT, their median half
        r["itl_us"] = [tpot_ms * 1000 * (2.5 if k < (out - 1) // 4 else 0.5) for k in range(out - 1)]
    return r


def rows(scale=1.0, n=N, itl=True, shift_s=0.0):
    """n requests `scale` seconds apart, 100 ms TTFT and 10 ms TPOT, times `scale`; half the prompt cached: a closed
    loop that is `scale` times slower delivers 1/scale of the throughput."""
    return [req(i, i * scale + shift_s, 100 * scale, 10 * scale, cached=500, itl=itl) for i in range(n)]


def test_the_figures_are_the_registrys_over_the_steady_middle_window():
    rs = rows()
    rs[0] = req(0, 0, 5000, 50)          # the ramp: a slow first request
    rs[-1] = req(10, 10, 5000, 50)       # the drain
    ids = cp.window_ids(rs, 0.1)
    f = cp.figures(rs, ids)
    assert f["requests"] == 9
    assert f["ttft_p99_ms"] == pytest.approx(100)
    assert f["itl_p50_ms"] == pytest.approx(5)              # pooled per-token median, not the median TPOT of 10 ms
    assert f["interactivity_p50"] == pytest.approx(100)    # 1000 over the TPOT p50 in ms
    assert f["cache_hit_rate"] == pytest.approx(0.5)
    # 9 requests of 101 output tokens over the 8 s between the window's first and last arrival
    assert f["output_tok_s"] == pytest.approx(9 * 101 / 8)


def test_the_simulated_side_is_read_over_the_measured_windows_requests():
    meas = rows()
    ids = cp.window_ids(meas, 0.1)
    sim = rows(shift_s=0.3) + [req(99, 5, 100, 10)]        # an extra request the measured window does not hold
    assert cp.figures(sim, ids)["requests"] == len(ids)


def test_the_registry_must_define_each_figure_as_computed_here():
    good = {k: dict(v) for k, v in cp.FIGURES.items()}
    assert cp.check_registry(good) == []
    bad = {**good, "itl_p50_ms": {**good["itl_p50_ms"], "population": "requests"}}
    assert cp.check_registry(bad) == ["the simulator's itl_p50_ms has population 'requests'; this tool computes it with 'tokens'"]
    assert cp.check_registry({k: v for k, v in good.items() if k != "cache_hit_rate"}) == \
        ["the simulator's metric registry has no cache_hit_rate"]


def write_corpus(root: Path, visibility="private", image="vllm/vllm-openai:v0.32.0", runs=3, engine=None, scenario_engine=None):
    root.mkdir(parents=True)
    doc = {"format": cp.FORMAT, "visibility": visibility, "runs": []}
    for k in range(runs):
        rid = f"r{k}"
        (root / rid).mkdir()
        (root / rid / "requests.jsonl").write_text("\n".join(json.dumps(r) for r in rows(1 + k)) + "\n")
        eng = dict(engine or ENGINE)
        (root / rid / "scenario.yaml").write_text(
            "kind: Scenario\n---\nkind: Deployment\npools:\n- name: p\n  engine: "
            + json.dumps({**(scenario_engine or eng), "engine_version": "0.32.0"}) + "\n")
        doc["runs"].append({"id": rid, "workload": "w", "concurrency": 8, "gpus": 8, "configuration": {"engine": eng},
                            "build": {"image": image, "banner": image.rsplit(":v", 1)[-1]},
                            "scenario": f"{rid}/scenario.yaml", "measured_requests": f"{rid}/requests.jsonl",
                            "replay": ["replay", "--scenario", f"{rid}/scenario.yaml"], "differences": []})
    (root / "corpus.json").write_text(json.dumps(doc))
    return root


def fake_simulate(scales):
    def sim(run):
        s = scales[run["id"]]
        if s is None:
            raise cp.CorpusError("blis exited 1")
        return result(rows(s, itl=False))
    return sim


def field_list(status="modelled", rule="none"):
    return fl.parse(json.dumps({"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.32.0"}, "fields": [
        {"name": "kv_cache_dtype", "source": "config", "status": "modelled", "evidence": {"traces": ["t"]},
         "estimation": {"rule": "none"}},
        {"name": "max_num_seqs", "source": "config", "status": status,
         "evidence": {"issue": "o/r#1"} if status == "not_modelled" else {"traces": ["t"]},
         "estimation": {"rule": rule}}]}))


def test_a_run_on_the_engine_release_is_graded_g2_with_the_unevaluated_conditions_named(tmp_path):
    c = write_corpus(tmp_path / "c")
    rep = cp.score(corpus=c, simulate=fake_simulate({"r0": 1.0, "r1": 2.2, "r2": None}), engine_release="0.32.0",
                   field_list=field_list())
    by = {r["id"]: r for r in rep["runs"]}
    assert by["r0"]["grade"] == "G2"
    assert {s["kind"] for s in by["r0"]["substitutions"]} == {"unevaluated"}
    assert by["r0"]["errors_pct"]["ttft_p99_ms"] == pytest.approx(0)
    assert by["r1"]["errors_pct"]["ttft_p99_ms"] == pytest.approx(10)      # 220 ms simulated against 200 measured
    assert by["r1"]["simulated"]["itl_p50_ms"] is None                     # the Result carries no per-token times
    assert by["r2"]["status"] == "failed"
    assert rep["grades"]["G2"] == 2 and rep["grades"]["failed"] == 1


def test_another_release_is_graded_as_an_inferencex_point_would_be(tmp_path):
    c = write_corpus(tmp_path / "c", image="vllm/vllm-openai:v0.31.0", runs=1)
    rep = cp.score(corpus=c, simulate=fake_simulate({"r0": 1.0}), engine_release="0.32.0", field_list=field_list())
    assert rep["runs"][0]["grade"] == "G4"


def test_a_configuration_field_the_engine_does_not_model_and_has_no_rule_for_is_g5(tmp_path):
    c = write_corpus(tmp_path / "c", runs=1)
    rep = cp.score(corpus=c, simulate=fake_simulate({"r0": 1.0}), engine_release="0.32.0",
                   field_list=field_list(status="not_modelled"))
    r = rep["runs"][0]
    assert (r["status"], r["grade"], r["g5_reason"]) == ("not_scored", "G5", {"code": "field_not_modelled", "subject": "max_num_seqs"})
    assert "errors_pct" not in r and rep["grades"]["G5"] == 1
    rep = cp.score(corpus=c, simulate=fake_simulate({"r0": 1.0}), engine_release="0.32.0",
                   field_list=field_list(status="not_modelled", rule="leave_unset"))
    assert rep["runs"][0]["grade"] == "G2" and any(s["kind"] == "estimated" for s in rep["runs"][0]["substitutions"])


def test_a_scenario_that_is_not_the_runs_configuration_is_refused(tmp_path):
    c = write_corpus(tmp_path / "c", runs=1, scenario_engine={**ENGINE, "max_num_seqs": 256})
    rep = cp.score(corpus=c, simulate=fake_simulate({"r0": 1.0}), engine_release="0.32.0", field_list=field_list())
    assert rep["runs"][0]["status"] == "failed"
    assert "max_num_seqs: the configuration states 64, the scenario 256" in rep["runs"][0]["fault"]


def test_the_ranking_says_whether_blis_orders_the_configurations_as_the_runs_do(tmp_path):
    c = write_corpus(tmp_path / "c")
    # measured: r0 fastest, then r1, then r2; BLIS swaps r0 and r1
    rep = cp.score(corpus=c, simulate=fake_simulate({"r0": 2.5, "r1": 1.5, "r2": 3.5}), engine_release="0.32.0")
    m = rep["ranking"]["w"]
    assert (m["configs"], m["top1"]) == (3, 0)
    assert m["spearman"] == pytest.approx(0.5)
    assert 0 < m["regret"] < 1


def test_a_private_corpus_publishes_only_its_grade_counts_over_ten_runs_or_more(tmp_path):
    c = write_corpus(tmp_path / "c", runs=12)
    sim = fake_simulate({f"r{k}": (None if k == 0 else 1.0) for k in range(12)})
    pub = cp.public_summary(cp.score(corpus=c, simulate=sim, engine_release="0.32.0"), "corpus-one")
    assert set(pub) == {"format", "label", "engine_release", "runs", "min_units", "grades"}
    assert "configuration" not in json.dumps(pub)
    assert pub["grades"] == {"G1": 0, "G2": 11, "G3": 0, "G4": 0, "G5": 0, "failed": "fewer than 10"}
    assert '"max_num_seqs": 64' in cp.markdown(cp.score(corpus=c, simulate=sim, engine_release="0.32.0"), "corpus-one")


def test_a_private_corpus_of_fewer_than_ten_runs_publishes_nothing(tmp_path):
    c = write_corpus(tmp_path / "c")
    rep = cp.score(corpus=c, simulate=fake_simulate({"r0": 1.0, "r1": 1.0, "r2": 1.0}), engine_release="0.32.0")
    with pytest.raises(cp.CorpusError, match="fewer than 10"):
        cp.public_summary(rep, "corpus-one")


def test_a_label_that_is_not_a_slug_shares_a_word_with_the_path_or_holds_a_private_name_is_refused(tmp_path):
    c = write_corpus(tmp_path / "secretlab" / "c")
    for label, why in (("Lab Corpus", "short slug"), ("ab", "short slug"), ("secretlab-runs", "shares a word"),
                       ("x-zeta-y", "private name")):
        with pytest.raises(cp.CorpusError, match=why):
            cp.check_label(label, c, ["zeta"])
    cp.check_label("corpus-one", c, ["zeta"])


def test_a_public_summary_needs_a_label_given_on_the_command_line(tmp_path):
    c = write_corpus(tmp_path / "c")
    assert cp.main(["score", "--corpus", str(c), "--blis", "b", "--catalog", "c", "--registry", "r", "--fields", "f",
                    "--out", str(tmp_path / "o"), "--public-out", str(tmp_path / "p.json")]) == 2
    assert not (tmp_path / "p.json").exists()


def test_a_run_without_a_valid_result_is_failed_not_scored(tmp_path):
    c = write_corpus(tmp_path / "c", runs=1)
    good = result(rows())
    for res in ({"request_rows": rows()}, {**good, "schema_version": 1}, {**good, "request_rows": []},
                {**good, "request_rows": [{**r, "fate": "dropped"} for r in rows()]},
                {**good, "requests": {"generated": N, "completed": N - 1, "length_capped": 0}}):
        rep = cp.score(corpus=c, simulate=lambda run, res=res: res, engine_release="0.32.0")
        assert rep["runs"][0]["status"] == "failed", res
        assert rep["grades"]["failed"] == 1 and rep["grades"]["G2"] == 0


def test_a_fault_of_a_private_corpus_names_no_path(tmp_path):
    c = write_corpus(tmp_path / "c", runs=1)

    def sim(run):
        raise cp.CorpusError(f"cannot read {tmp_path}/secret/place/trace.jsonl")
    rep = cp.score(corpus=c, simulate=sim, engine_release="0.32.0")
    assert str(tmp_path) not in rep["runs"][0]["fault"] and "<path>" in rep["runs"][0]["fault"]


def test_the_engine_release_is_read_from_the_builds_stack_and_the_field_list_must_agree(tmp_path):
    (tmp_path / "blis").write_text("")
    (tmp_path / "stack.json").write_text(json.dumps({"kind": "Stack", "toolchain": "go1", "modules": [],
                                                     "engines": [{"kind": "vllm", "version": "0.32.0", "commit": "a" * 40}]}))
    f = tmp_path / "fields.json"
    f.write_text(json.dumps({"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.32.0"}, "fields": []}))
    assert cp.engine_release_of(str(tmp_path / "blis"), f)[0] == "0.32.0"
    f.write_text(json.dumps({"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.31.0"}, "fields": []}))
    with pytest.raises(cp.CorpusError, match="the field list is for"):
        cp.engine_release_of(str(tmp_path / "blis"), f)
    with pytest.raises(SystemExit):
        cp.main(["score", "--corpus", "x", "--blis", "b", "--catalog", "c", "--registry", "r", "--fields", "f",
                 "--engine-release", "0.32.0", "--out", "o"])


def test_a_corpus_or_a_report_inside_a_work_tree_of_this_repository_is_refused(tmp_path):
    with pytest.raises(cp.CorpusError, match="inside a work tree"):
        cp.load(cp.ROOT / "docs")
    c = write_corpus(tmp_path / "c")
    assert cp.main(["score", "--corpus", str(c), "--blis", "b", "--catalog", "x", "--registry", "y", "--fields", "f",
                    "--out", str(cp.ROOT / "docs" / "tmp-report")]) == 2
    assert not (cp.ROOT / "docs" / "tmp-report").exists()


def test_a_corpus_in_another_worktree_of_this_repository_is_refused(tmp_path):
    import subprocess
    wt = tmp_path / "wt"
    r = subprocess.run(["git", "-C", str(cp.ROOT), "worktree", "add", "--detach", "-q", str(wt), "HEAD"], capture_output=True)
    assert r.returncode == 0, r.stderr
    try:
        assert cp.inside_repo(wt / "anything")
        assert not cp.inside_repo(tmp_path / "elsewhere")
    finally:
        subprocess.run(["git", "-C", str(cp.ROOT), "worktree", "remove", "--force", str(wt)], capture_output=True)


def test_a_run_states_exactly_one_kind_of_measurement_and_a_trim_that_leaves_a_window(tmp_path):
    c = write_corpus(tmp_path / "c", runs=1)
    doc = json.loads((c / "corpus.json").read_text())
    doc["runs"][0]["measured_figures"] = {}
    (c / "corpus.json").write_text(json.dumps(doc))
    with pytest.raises(cp.CorpusError, match="exactly one"):
        cp.load(c)
    del doc["runs"][0]["measured_figures"]
    for trim in (0.5, -0.1, "x"):
        (c / "corpus.json").write_text(json.dumps({**doc, "window_trim_fraction": trim}))
        with pytest.raises(cp.CorpusError, match="window_trim_fraction"):
            cp.load(c)


def test_aggregate_figures_are_compared_only_under_the_same_definition_and_window(tmp_path):
    c = write_corpus(tmp_path / "c", runs=1)
    doc = json.loads((c / "corpus.json").read_text())
    del doc["runs"][0]["measured_requests"]
    doc["runs"][0]["measured_figures"] = {"ttft_p99_ms": {"value": 50.0, "scope": "cluster", "aggregate": "",
                                                          "window": "the client's"}}
    (c / "corpus.json").write_text(json.dumps(doc))
    with pytest.raises(cp.CorpusError, match="DEV-8"):
        cp.load(c)
    doc["runs"][0]["measured_figures"]["ttft_p99_ms"]["window"] = "arrival_middle:0.1"
    (c / "corpus.json").write_text(json.dumps(doc))
    rep = cp.score(corpus=c, simulate=fake_simulate({"r0": 1.0}), engine_release="0.32.0")
    assert rep["runs"][0]["errors_pct"]["ttft_p99_ms"] == pytest.approx(100)


def test_the_replay_command_runs_with_the_harnesss_data_flags_only(tmp_path):
    c = write_corpus(tmp_path / "c", runs=1)
    run = cp.load(c)["runs"][0]
    assert cp.replay_argv(run, blis="B", catalog=Path("C"), registry=Path("R")) == [
        "B", "replay", "--scenario", "r0/scenario.yaml", "--catalog", "C", "--registry", "R", "--format", "json"]
    for bad in (["replay", "--catalog", "mine"], ["replay", "--catalog=/mine"], ["replay", "--format=yaml"]):
        with pytest.raises(cp.CorpusError, match="the harness sets it"):
            cp.replay_argv({**run, "replay": bad}, blis="B", catalog=Path("C"), registry=Path("R"))
