"""Tests of the first-party corpus scorer (corpus.py). A first-party run is frozen into a pull and scored by the
scorer every InferenceX point goes through (score.score_points), with the fake `blis`, field list and catalog of the
scorer's own end-to-end test (test_score_e2e.py), so its scenario is built by the same §11.2 path."""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ingest"))
import corpus as cp  # noqa: E402
import settings as st  # noqa: E402
import score as sc  # noqa: E402
import test_score_e2e as e2e  # noqa: E402

N_RUNS = 12


def build(image, log):
    """What build.Resolver.resolve(...).record() gives an official release image (no network in a test)."""
    return {"image": image, "commit": e2e.ENGINE_COMMIT, "source": "image_label", "ref": "v0.31.0", "distance": 0, "match": "exact"}


def row(conc=4, metrics=None, **kw):
    return {"model": "m", "hardware": "mi355x", "precision": "fp8", "framework": "vllm", "benchmark_type": "single_turn",
            "conc": conc, "isl": 1024, "osl": 1024, "spec_method": "mtp", "disagg": False, "is_multinode": False,
            "decode_tp": 1, "decode_ep": 1, "num_decode_gpu": 1, "date": "2026-10-01", "image": "vllm/vllm-openai:v0.31.0",
            "metrics": metrics or {"mean_ttft": 0.2, "mean_tpot": 0.01, "median_tpot": 0.01, "p99_ttft": 0.3,
                                   "median_itl": 0.008, "output_tput_per_gpu": 400.0}, **kw}


def write_corpus(root: Path, runs=1, visibility="private", log=e2e.LOG, client=None, conc=(4,)):
    root.mkdir(parents=True)
    doc = {"format": cp.FORMAT, "visibility": visibility, "runs": []}
    for k in range(runs):
        rid = f"r{k}"
        c = conc[k % len(conc)]
        (root / rid).mkdir()
        # A real log records the requests its client sent: 10*conc measured and 2*conc warm-up (ingest/contamination.py).
        line = '"POST /v1/completions HTTP/1.1" 200\n'
        (root / rid / "vllm.log").write_text(log.replace(line * 48, line * (12 * c)))
        (root / rid / "client.log").write_text(e2e.job_log_text(1024, 1024, c))
        doc["runs"].append({"id": rid, "workload": "w", "row": row(conc=c),
                            "client": client or {"name": "inferencex", "repo": "SemiAnalysisAI/InferenceX", "commit": "f" * 40},
                            "files": {"server_log": f"{rid}/vllm.log", "job_log": f"{rid}/client.log"}})
    (root / "corpus.json").write_text(json.dumps(doc))
    return root


def _env(tmp, **fake):
    e = sc.Env(blis=e2e._fake_blis(tmp, **fake), blis_release="v0.12.0", blis_commit="b" * 40, harness_commit="c" * 40,
               catalog=tmp, catalog_release="0.3.0", registry=tmp, registry_release="v0.2.0", kernel="v0.3.0",
               corpora={}, field_list=e2e.FIELDS, vllm_defaults=st.load_vllm_defaults()[0], engine_release="0.31.0",
               sim_build="v0.12.0")
    e.catalog_obj = e2e._catalog(tmp, {"org/m": "m"}, {"mi355x": (None, None)}, {"m": "mtp"})
    e.parts = {"mi355x"}
    return e


def run(tmp, **kw):
    c = write_corpus(tmp / "c", **kw)
    rep, outcomes = cp.score(corpus=c, work=tmp / "w", env=_env(tmp), resolve_build=build)
    return rep, outcomes


def test_a_first_party_run_is_scored_by_the_scorer_an_inferencex_point_goes_through(tmp_path):
    rep, outcomes = run(tmp_path)
    r = rep["runs"][0]
    assert (r["status"], r["grade"]) == ("scored", "G2")
    # the scenario was built from the run's own server log by settings.decide: its recorded settings are named
    args = {a["arg"]: a for a in r["scenario_args"]}
    assert args["max_num_seqs"]["measured"] == 16 and args["max_num_seqs"]["match"] in ("exact", "mapped")
    # the client's requests were recomputed and the send gap named, as for every single-turn InferenceX point
    assert any(s["kind"] == "client_difference" and s["subject"] == "send_gap" for s in r["substitutions"])
    # the five figures: the fake's TTFT is 180 ms and TPOT 9 ms on every request; the client's own stats are measured
    assert r["simulated"]["ttft_p99_ms"] == pytest.approx(180) and r["measured"]["ttft_p99_ms"] == pytest.approx(300)
    assert r["simulated"]["interactivity_p50"] == pytest.approx(1000 / 9)
    assert r["simulated"]["itl_p50_ms"] is None and r["measured"]["itl_p50_ms"] == pytest.approx(8)


def test_a_field_the_engine_does_not_model_makes_the_run_g5_by_the_engines_field_list(tmp_path):
    rep, _ = run(tmp_path, log=e2e.LOG.replace("'block_size': 16", "'block_size': 16, 'not_a_known_field': 1"))
    r = rep["runs"][0]
    assert (r["status"], r["grade"]) == ("not_scored", "G5")
    assert any(g["code"] == "field_not_in_release" for g in r["reasons"]), r["reasons"]


def test_a_run_whose_client_the_harness_cannot_recompute_is_g5_by_the_scorers_reason(tmp_path):
    rep, _ = run(tmp_path, client={"name": "guidellm"})
    r = rep["runs"][0]
    assert (r["status"], r["grade"]) == ("not_scored", "G5")
    assert {"code": "value_not_recorded", "subject": "guidellm"} in r["reasons"]


def test_a_run_whose_client_commit_is_not_recorded_names_the_difference(tmp_path):
    rep, _ = run(tmp_path, client={"name": "inferencex"})
    subs = {(s["kind"], s["subject"]) for s in rep["runs"][0]["substitutions"]}
    assert ("client_difference", "client_release") in subs
    rep, _ = run(tmp_path / "with")
    assert ("client_difference", "client_release") not in {(s["kind"], s["subject"]) for s in rep["runs"][0]["substitutions"]}


def test_a_run_the_simulator_refuses_is_failed_not_scored(tmp_path):
    c = write_corpus(tmp_path / "c")
    rep, _ = cp.score(corpus=c, work=tmp_path / "w", env=_env(tmp_path, validate=1), resolve_build=build)
    assert rep["runs"][0]["status"] == "failed" and rep["grades"]["failed"] == 1 and rep["grades"]["G2"] == 0


def test_the_ranking_says_whether_blis_orders_the_configurations_as_the_runs_do(tmp_path):
    c = write_corpus(tmp_path / "c", runs=3, conc=(4, 8, 16))
    doc = json.loads((c / "corpus.json").read_text())
    for r, tput in zip(doc["runs"], (300.0, 200.0, 100.0)):       # measured: the lowest concurrency serves most
        r["row"]["metrics"]["output_tput_per_gpu"] = tput
    (c / "corpus.json").write_text(json.dumps(doc))
    rep, _ = cp.score(corpus=c, work=tmp_path / "w", env=_env(tmp_path), resolve_build=build)
    m = rep["ranking"]["w"]
    assert m["configs"] == 3 and m["top1"] == 0 and m["spearman"] == pytest.approx(-1.0)


def test_the_registry_must_define_each_figure_as_computed_here():
    good = {k: dict(v) for k, v in cp.FIGURES.items()}
    assert cp.check_registry(good) == []
    bad = {**good, "itl_p50_ms": {**good["itl_p50_ms"], "population": "requests"}}
    assert cp.check_registry(bad) == ["the simulator's itl_p50_ms has population 'requests'; this tool computes it with 'tokens'"]


def test_a_private_corpus_publishes_only_its_grade_counts_over_ten_runs_or_more(tmp_path):
    rep, _ = run(tmp_path, runs=N_RUNS)
    pub = cp.public_summary(rep, "corpus-one")
    assert set(pub) == {"format", "label", "engine_release", "runs", "min_units", "grades"}
    assert pub["grades"]["G2"] == N_RUNS and "max_num_seqs" not in json.dumps(pub)
    assert '"conc": 4' in cp.markdown(rep, "corpus-one")      # the full report shows each run's configuration


def test_a_private_corpus_of_fewer_than_ten_runs_publishes_nothing(tmp_path):
    rep, _ = run(tmp_path)
    with pytest.raises(cp.CorpusError, match="fewer than 10"):
        cp.public_summary(rep, "corpus-one")
    rep["grades"] = {**rep["grades"], "G2": 11, "failed": 3}
    rep["runs"] = rep["runs"] * 14
    assert cp.public_summary(rep, "corpus-one")["grades"]["failed"] == "fewer than 10"


def test_a_label_that_is_not_a_slug_shares_a_word_with_the_path_or_holds_a_private_name_is_refused(tmp_path):
    c = write_corpus(tmp_path / "secretlab" / "c")
    for label, why in (("Lab Corpus", "short slug"), ("ab", "short slug"), ("secretlab-runs", "shares a word"),
                       ("x-zeta-y", "private name")):
        with pytest.raises(cp.CorpusError, match=why):
            cp.check_label(label, c, ["zeta"])
    cp.check_label("corpus-one", c, ["zeta"])


def test_a_corpus_or_its_work_inside_a_work_tree_of_this_repository_is_refused(tmp_path):
    import subprocess
    with pytest.raises(cp.CorpusError, match="never in a work tree"):
        cp.load(cp.ROOT / "docs")
    c = write_corpus(tmp_path / "c")
    with pytest.raises(cp.CorpusError, match="never in a work tree"):
        cp.score(corpus=c, work=cp.ROOT / "docs" / "tmp-work", env=None, resolve_build=build)
    assert not (cp.ROOT / "docs" / "tmp-work").exists()
    wt = tmp_path / "wt"
    assert subprocess.run(["git", "-C", str(cp.ROOT), "worktree", "add", "--detach", "-q", str(wt), "HEAD"]).returncode == 0
    try:
        assert cp.inside_repo(wt / "anything") and not cp.inside_repo(tmp_path / "elsewhere")
    finally:
        subprocess.run(["git", "-C", str(cp.ROOT), "worktree", "remove", "--force", str(wt)], capture_output=True)


def test_the_cli_refuses_a_public_summary_without_a_label_and_an_engine_release_flag(tmp_path):
    c = write_corpus(tmp_path / "c")
    common = ["score", "--corpus", str(c), "--work", str(tmp_path / "w"), "--out", str(tmp_path / "o"), "--catalog", "x",
              "--registry", "y", "--fields", "f", "--corpus-dir", "d", "--blis", "b", "--catalog-release", "v1.0.0",
              "--registry-release", "v1.0.0", "--harness-commit", "c" * 40]
    assert cp.main(common + ["--public-out", str(tmp_path / "p.json")]) == 2 and not (tmp_path / "p.json").exists()
    with pytest.raises(SystemExit):
        cp.main(common + ["--engine-release", "0.32.0"])
