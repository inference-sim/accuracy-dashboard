"""Tests of the first-party corpus scorer (corpus.py), on a synthetic corpus written here and a fake simulator."""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ingest"))
import corpus as cp  # noqa: E402

COEF = {"kind": "Result", "schema_version": 3,
        "selected_entries": {"coefficients": [{"set": "s", "name": "n", "method": "measured"}]}}


def req(i, arrival_s, ttft_ms, tpot_ms, out=101, prompt=1000, cached=0, fate="completed", itl=True):
    r = {"id": f"request_{i}", "fate": fate, "arrival_us": int(arrival_s * 1e6), "ttft_us": int(ttft_ms * 1000),
         "tpot_us": tpot_ms * 1000, "e2e_us": int((ttft_ms + (out - 1) * tpot_ms) * 1000),
         "prompt_tokens": prompt, "output_tokens": out, "cached_local_tokens": cached}
    if itl:
        # a quarter of the gaps 2.5 times the TPOT and the rest half of it: their mean is the TPOT, their median half
        r["itl_us"] = [tpot_ms * 1000 * (2.5 if k < (out - 1) // 4 else 0.5) for k in range(out - 1)]
    return r


def rows(scale=1.0, n=11, itl=True):
    """n requests one second apart, 100 ms TTFT and 10 ms TPOT, times `scale`; half the prompt cached."""
    return [req(i, i, 100 * scale, 10 * scale, cached=500, itl=itl) for i in range(n)]


def test_the_figures_are_taken_over_the_steady_middle_window():
    rs = rows()
    rs[0] = req(0, 0, 5000, 50)          # the ramp: a slow first request
    rs[-1] = req(10, 10, 5000, 50)       # the drain
    f = cp.figures(rs, 0.1)
    assert f["requests"] == 9
    assert f["ttft_p99_ms"] == pytest.approx(100)
    assert f["itl_p50_ms"] == pytest.approx(5)      # the pooled per-token median, not the median TPOT of 10 ms
    assert f["interactivity_p50_tps"] == pytest.approx(100)
    assert f["cache_read_rate"] == pytest.approx(0.5)
    # 9 requests of 101 tokens between the first arrival (1 s) and the last completion (9 s + 1.1 s)
    assert f["output_throughput_tps"] == pytest.approx(9 * 101 / 9.1)


def test_a_request_that_did_not_complete_is_not_counted():
    rs = rows()
    rs[5] = {**rs[5], "fate": "dropped"}
    assert cp.figures(rs, 0.1)["requests"] == 8


def write_corpus(root: Path, visibility="private", image="vllm/vllm-openai:v0.32.0", runs=3, label="firstparty-a"):
    root.mkdir(parents=True)
    doc = {"format": cp.FORMAT, "label": label, "visibility": visibility, "runs": []}
    for k in range(runs):
        rid = f"r{k}"
        (root / rid).mkdir()
        (root / rid / "requests.jsonl").write_text("\n".join(json.dumps(r) for r in rows(1 + k)) + "\n")
        doc["runs"].append({"id": rid, "workload": "w", "concurrency": 8, "gpus": 8, "configuration": {"tp": 8, "k": k},
                            "build": {"image": image, "banner": image.rsplit(":v", 1)[-1]}, "measured_requests": f"{rid}/requests.jsonl",
                            "replay": ["replay", "--scenario", f"{rid}/scenario.yaml"], "differences": []})
    (root / "corpus.json").write_text(json.dumps(doc))
    return root


def fake_simulate(scales):
    def sim(run):
        s = scales[run["id"]]
        if s is None:
            raise cp.CorpusError("blis exited 1: refused")
        return {**COEF, "request_rows": rows(s, itl=False)}
    return sim


def test_a_run_on_the_engine_release_is_graded_g2_with_the_unevaluated_conditions_named(tmp_path):
    c = write_corpus(tmp_path / "c")
    rep = cp.score(corpus=c, simulate=fake_simulate({"r0": 1.0, "r1": 2.2, "r2": None}), engine_release="0.32.0")
    by = {r["id"]: r for r in rep["runs"]}
    assert by["r0"]["grade"] == "G2"
    assert {s["kind"] for s in by["r0"]["substitutions"]} == {"unevaluated"}
    assert by["r0"]["errors_pct"]["ttft_p99_ms"] == pytest.approx(0)
    assert by["r1"]["errors_pct"]["ttft_p99_ms"] == pytest.approx(10)      # 220 ms simulated against 200 measured
    assert by["r1"]["simulated"]["itl_p50_ms"] is None                     # the Result carries no per-token times
    assert by["r2"]["status"] == "failed"
    assert rep["grades"] == {"G1": 0, "G2": 2, "G3": 0, "G4": 0, "failed": 1}


def test_another_release_is_graded_as_an_inferencex_point_would_be(tmp_path):
    c = write_corpus(tmp_path / "c", image="vllm/vllm-openai:v0.31.0", runs=1)
    rep = cp.score(corpus=c, simulate=fake_simulate({"r0": 1.0}), engine_release="0.32.0")
    assert rep["runs"][0]["grade"] == "G4"


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
    pub = cp.public_summary(cp.score(corpus=c, simulate=sim, engine_release="0.32.0"))
    assert set(pub) == {"format", "label", "engine_release", "runs", "min_units", "grades"}
    assert "configuration" not in json.dumps(pub)
    # 11 G2 runs are shown; the one failed run is a count under 10, so it is not
    assert pub["grades"] == {"G1": 0, "G2": 11, "G3": 0, "G4": 0, "failed": "fewer than 10"}


def test_a_private_corpus_of_fewer_than_ten_runs_publishes_nothing(tmp_path):
    c = write_corpus(tmp_path / "c")
    rep = cp.score(corpus=c, simulate=fake_simulate({"r0": 1.0, "r1": 1.0, "r2": 1.0}), engine_release="0.32.0")
    with pytest.raises(cp.CorpusError, match="fewer than 10"):
        cp.public_summary(rep)
    full = cp.markdown(rep)
    assert '"k": 2' in full          # the full report shows each configuration beside its numbers


def test_a_corpus_or_a_private_report_inside_the_checkout_is_refused(tmp_path):
    with pytest.raises(cp.CorpusError, match="inside this checkout"):
        cp.load(cp.ROOT / "docs")
    c = write_corpus(tmp_path / "c")
    f = tmp_path / "fields.json"
    f.write_text(json.dumps({"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.32.0"}, "fields": []}))
    assert cp.main(["score", "--corpus", str(c), "--blis", "/bin/false", "--catalog", "x", "--registry", "y",
                    "--fields", str(f), "--out", str(cp.ROOT / "docs" / "tmp-report")]) == 2
    assert not (cp.ROOT / "docs" / "tmp-report").exists()


def test_a_run_states_exactly_one_kind_of_measurement(tmp_path):
    c = write_corpus(tmp_path / "c", runs=1)
    doc = json.loads((c / "corpus.json").read_text())
    doc["runs"][0]["measured_figures"] = {"ttft_p99_ms": 1}
    (c / "corpus.json").write_text(json.dumps(doc))
    with pytest.raises(cp.CorpusError, match="exactly one"):
        cp.load(c)


def test_aggregate_figures_are_compared_as_stated(tmp_path):
    c = write_corpus(tmp_path / "c", runs=1)
    doc = json.loads((c / "corpus.json").read_text())
    del doc["runs"][0]["measured_requests"]
    doc["runs"][0]["measured_figures"] = {"ttft_p99_ms": 50.0, "itl_p50_ms": 10.0, "window": "the client's"}
    (c / "corpus.json").write_text(json.dumps(doc))
    rep = cp.score(corpus=c, simulate=fake_simulate({"r0": 1.0}), engine_release="0.32.0")
    r = rep["runs"][0]
    assert r["errors_pct"]["ttft_p99_ms"] == pytest.approx(100)
    assert r["errors_pct"]["output_throughput_tps"] is None
    assert r["measured_window"] == "the source's own: the client's"


def test_the_replay_command_reads_the_runs_files_and_sets_the_data_itself(tmp_path):
    c = write_corpus(tmp_path / "c", runs=1)
    (c / "r0" / "scenario.yaml").write_text("x")
    run = cp.load(c)["runs"][0]
    argv = cp.replay_argv(run, c, blis="B", catalog=Path("C"), registry=Path("R"))
    assert argv == ["B", "replay", "--scenario", str(c / "r0" / "scenario.yaml"), "--catalog", "C", "--registry", "R",
                    "--format", "json"]
    with pytest.raises(cp.CorpusError, match="the harness sets it"):
        cp.replay_argv({**run, "replay": ["replay", "--catalog", "mine"]}, c, blis="B", catalog=Path("C"), registry=Path("R"))


def test_a_label_that_is_not_a_slug_shares_a_word_with_the_path_or_holds_a_private_name_is_refused(tmp_path):
    for i, (label, why) in enumerate((("Lab Corpus", "short slug"), ("ab", "short slug"), ("secretlab-runs", "shares"),
                                      ("x-zeta-y", "private name"))):
        c = write_corpus(tmp_path / "secretlab" / f"c{i}", label=label)
        with pytest.raises(cp.CorpusError, match=why):
            cp.load(c, private_names=["zeta"])
    assert cp.load(write_corpus(tmp_path / "secretlab" / "ok", label="corpus-one"), ["zeta"])["label"] == "corpus-one"


def test_a_run_without_a_valid_result_is_failed_not_scored(tmp_path):
    c = write_corpus(tmp_path / "c", runs=1)
    for res in ({"request_rows": rows()}, {**COEF, "schema_version": 1, "request_rows": rows()},
                {**COEF, "request_rows": []}, {**COEF, "request_rows": [{**rows()[0], "fate": "dropped"}]}):
        rep = cp.score(corpus=c, simulate=lambda run, res=res: res, engine_release="0.32.0")
        assert rep["runs"][0]["status"] == "failed", res
        assert rep["grades"]["failed"] == 1


def test_the_engine_release_is_read_from_the_field_list_not_given(tmp_path):
    f = tmp_path / "fields.json"
    f.write_text(json.dumps({"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.32.0"}, "fields": []}))
    assert cp.engine_from_fields(f) == "0.32.0"
    with pytest.raises(SystemExit):
        cp.main(["score", "--corpus", "x", "--blis", "b", "--catalog", "c", "--registry", "r",
                 "--engine-release", "0.32.0", "--out", "o"])
