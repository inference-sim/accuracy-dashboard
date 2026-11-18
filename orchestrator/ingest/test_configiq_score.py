"""configiq points scored by simulation (configiq_score.py; design §10.1-10.3, §11, COV-7, COV-10, COV-11, D7).

Every dataset row here is synthetic (X12). The simulator is a fake `blis` that answers `replay` with one Result of
per-request rows (test_score_e2e.FAKE_BLIS): what is asserted is what the scorer asked of it and what it made of the
answer, never the text of the code. Before this module a configiq point had no consumer: no scenario was built from
one and `blis replay` was never called for one.

Run: python3 -m pytest orchestrator/ingest/test_configiq_score.py
"""
import csv
import json
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import by_source as bs  # noqa: E402
import configiq as cq  # noqa: E402
import configiq_score as cs  # noqa: E402
import support as sp  # noqa: E402
import test_configiq as tc  # noqa: E402
import test_score_e2e as e2e  # noqa: E402

F = tc.F
CATALOG = tc.CATALOG
MODEL = "openai/gpt-oss-120b"
# The fake simulator gives every request a 180000 us TTFT and a 9000 us per-token decode (test_score_e2e.FAKE_BLIS).
FAKE_TTFT_MS, FAKE_TPOT_MS = 180.0, 9.0


def prow(**set_):
    """A row the launcher's preset explains (tc.row's defaults: gpt-oss-120b, TP1, 0.92, vLLM-0.32.0) with the figures a
    scored point needs: GuideLLM's mean TTFT 200 ms and mean ITL 10 ms, constant 1004/1000 token requests."""
    cols = tc.row(**{"prefix_caching": "yes", "successful_requests": 12.0, "concurrency": 4.0,
                     "measured concurrency": 3.9, "ttft_mean": 200.0, "itl_mean": 10.0,
                     "prompt_token_count_mean": 1004.0, "prompt_token_count_p99": 1004.0,
                     "output_token_count_mean": 1000.0, "output_token_count_p99": 1000.0, **set_})
    return cols


def setup(tmp_path, rows: dict, *, fake=None, models=None, chips=None, engine_release="0.33.0", config=True):
    """Points from a synthetic ledger and an Env whose simulator is the fake blis."""
    lg = cq.load(*tc.ledger_files(tmp_path, rows))
    pts = cq.points(lg, rows, CATALOG)
    cat_root = tmp_path / "catalog"
    (cat_root / "models" / "gpt-oss-120b").mkdir(parents=True, exist_ok=True)
    (cat_root / "models" / "gpt-oss-120b" / "graph.yaml").write_text("layers: []\n")
    if config:
        (cat_root / "models" / "gpt-oss-120b" / "config.json").write_text(json.dumps(
            {"max_position_embeddings": 131072,
             "rope_scaling": {"factor": 32.0, "original_max_position_embeddings": 4096, "rope_type": "yarn"}}))
    blis = fake or e2e._fake_blis(tmp_path)
    env = cs.Env(blis=blis, catalog=cat_root, registry=tmp_path / "registry", catalog_release="v0.15.0",
                 registry_release="v0.15.0", engine_release=engine_release, sim_build="v0.18.0",
                 harness_commit="c" * 40)
    env.catalog_obj = e2e._catalog(tmp_path, models or {MODEL: "gpt-oss-120b"}, chips or {"b200": (None, None)}, {})
    env.parts = set(chips or {"b200"})
    return pts, env


def run(tmp_path, rows, **kw):
    pts, env = setup(tmp_path, rows, **kw)
    outs = cs.score_all(pts, env, tmp_path / "work")
    return pts, outs, env


def replays(env) -> list[dict]:
    return e2e._saw(env)


def test_a_launcher_consistent_row_is_replayed_as_the_dataset_records_it_and_scored(tmp_path):
    rows = {f"{F}:0": prow()}
    pts, outs, env = run(tmp_path, rows)
    assert pts[0].provisional is True          # the gate alone leaves it "awaiting simulation"; nothing ever ran it
    (o,) = outs
    assert o.status == "scored", (o.g5, o.faults)
    # The simulator was asked once, for the run's own requests: 12 successful requests of the recorded 1004 in and
    # 1000 out, a closed loop of the recorded concurrency 4.
    (saw,) = replays(env)
    argv = saw["argv"]
    assert argv[argv.index("--concurrent-sessions") + 1] == "4"
    trace = list(csv.DictReader(open(argv[argv.index("--trace-data") + 1])))
    assert len(trace) == 12
    assert {(r["input_tokens"], r["output_tokens"]) for r in trace} == {("1004", "1000")}
    # The scenario states the row's model, chip, engine release (the simulator's), TP and parsed engine settings.
    text = (Path(argv[argv.index("--scenarios") + 1]) / argv[argv.index("--scenario") + 1]).read_text()
    scen, dep = list(yaml.safe_load_all(text))
    assert scen["model"] == "gpt-oss-120b" and scen["cluster"]["hardware"] == "b200"
    assert scen["engine"] == {"kind": "vllm", "version": "0.33.0"}
    pool = dep["pools"][0]
    assert pool["parallel"] == {"dp": 1, "pp": 1, "tp": 1}
    assert pool["engine"]["gpu_memory_utilization"] == 0.92 and pool["engine"]["enable_prefix_caching"] is True
    # The figures are the fake's, and the error is predicted over measured.
    assert o.predicted["ttft_mean"] == pytest.approx(FAKE_TTFT_MS)
    assert o.errors["ttft_mean"] == pytest.approx((FAKE_TTFT_MS - 200.0) / 200.0 * 100)
    assert o.errors["itl_mean"] == pytest.approx((FAKE_TPOT_MS - 10.0) / 10.0 * 100)


def test_a_scored_point_is_provisional_never_better_than_g3_and_names_its_substitutions(tmp_path):
    rows = {f"{F}:0": prow(version="vLLM-0.33.0", backend_version="vLLM-0.33.0")}
    _, outs, _ = run(tmp_path, rows)
    (o,) = outs
    r = cs.record(o)
    # The run's release is the simulator's, so the substitutions alone would give G2; the cap makes it G3.
    assert o.computed_grade == "G2" and r["grade"] == "G3" and r["grade_cap"] == "G3" and r["provisional"] is True
    kinds = {(s["kind"], s["subject"]) for s in r["substitutions"]}
    assert {("provisional_parallelism", "parallelism"), ("provisional_blank_flags", "engine flags the row leaves blank"),
            ("provisional_frame", "frame"), ("client_difference", "frame"), ("estimated", "cluster.gpus_per_node"),
            ("estimated", "engine.max_model_len")} <= kinds


def test_a_run_on_another_release_than_the_simulators_is_g4_with_the_release_named(tmp_path):
    _, outs, _ = run(tmp_path, {f"{F}:0": prow()})            # vLLM-0.32.0 against a simulator running 0.33.0
    r = cs.record(outs[0])
    assert r["grade"] == "G4" and r["provisional"] is True and r["grade_before_cap"] == "G4"
    other = [s for s in r["substitutions"] if s["kind"] == "other_release"]
    assert len(other) == 1 and "0.32.0" in other[0]["detail"] and "0.33.0" in other[0]["detail"]


def test_a_gap_between_the_run_and_the_scenario_is_a_named_substitution(tmp_path):
    rows = {f"{F}:0": prow(prompt_token_count_mean=900.0, prompt_token_count_p99=1500.0, errored_requests=3.0)}
    _, outs, _ = run(tmp_path, rows)
    (o,) = outs
    by = {s["subject"]: s for s in o.substitutions}
    assert "900" in by["request lengths"]["detail"] and "1500" in by["request lengths"]["detail"]
    assert "3 requests errored" in by["errored requests"]["detail"]
    blank = next(s["detail"] for s in o.substitutions if s["kind"] == "estimated" and s["subject"] == "engine flags the row leaves blank")
    assert "max_num_seqs" in blank and "gpu_memory_utilization" not in blank.split(" not recorded")[0]
    assert "131072" in by["engine.max_model_len"]["detail"]
    assert by["cluster.gpus_per_node"]["kind"] == "estimated"
    assert {(s["kind"], s["subject"]) for s in o.substitutions} >= {("client_difference", "frame"),
                                                                    ("provisional_frame", "frame")}


@pytest.mark.parametrize("backend,fragment", [("trtllm", "inference-sim hosts vLLM and SGLang only"),
                                              ("sglang", "SGLang rows have no launcher presets")])
def test_a_row_of_an_engine_that_is_neither_vllm_nor_a_reconstructible_sglang_is_refused_by_name(tmp_path, backend, fragment):
    rows = {f"{F}:0": prow(backend=backend)}
    _, outs, env = run(tmp_path, rows)
    (o,) = outs
    assert o.status == "refused" and replays(env) == []
    assert o.g5[0]["code"] == "engine_unsupported" and backend in o.g5[0]["subject"] and fragment in o.g5[0]["subject"]
    r = cs.record(o)
    assert r["grade"] == "G5" and r["provisional"] is False and r["g5_reason"]["code"] == "engine_unsupported"


@pytest.mark.parametrize("change,fragment", [
    ({"tp": 4.0}, "tensor parallel size 4"),
    ({"gpu_memory_utilization": "0.9"}, "gpu_memory_utilization"),
    ({"version": "vLLM-0.20.0", "backend_version": "vLLM-0.20.0"}, "predates the launcher's history"),
])
def test_a_launch_that_cannot_be_reconstructed_is_refused_with_the_reason_that_decides_it(tmp_path, change, fragment):
    _, outs, env = run(tmp_path, {f"{F}:0": prow(**change)})
    (o,) = outs
    assert o.status == "refused" and replays(env) == []
    assert o.g5[0]["code"] == "value_not_recorded" and o.g5[0]["subject"].startswith("launch: ")
    assert fragment in o.g5[0]["subject"]


def test_a_chip_the_catalog_does_not_model_is_refused_by_the_chip_not_by_the_launch(tmp_path):
    rows = {f"{F}:0": prow(accelerator="MI355X")}
    _, outs, env = run(tmp_path, rows)
    assert outs[0].status == "refused" and replays(env) == []
    assert [r["code"] for r in outs[0].g5] == [cq.CHIP_NOT_MODELLED]


def test_a_multi_turn_row_is_refused_with_what_the_dataset_does_not_record(tmp_path):
    rows = {f"{F}:0": prow(turns=5.0, prefix_tokens=512.0, prefix_count=10000.0)}
    _, outs, env = run(tmp_path, rows)
    (o,) = outs
    assert o.status == "refused" and replays(env) == []
    assert o.g5[0]["code"] == "value_not_recorded" and "multi-turn" in o.g5[0]["subject"] and "think time" in o.g5[0]["subject"]


def test_an_entry_with_a_committed_graph_and_no_config_file_is_scored_and_names_the_window_it_left_to_the_simulator(tmp_path):
    # The catalog keeps a licensed model's config.json out and commits its hash and the derived graph, which is all the
    # simulator reads. The scorer states no max_model_len and says so.
    _, outs, env = run(tmp_path, {f"{F}:0": prow()}, config=False)
    (o,) = outs
    assert o.status == "scored", (o.g5, o.faults)
    assert len(replays(env)) == 1
    sub = next(s for s in o.substitutions if s["subject"] == "engine.max_model_len")
    assert sub["kind"] == "estimated" and "commits no config.json" in sub["detail"]
    text = (Path(replays(env)[0]["argv"][replays(env)[0]["argv"].index("--scenarios") + 1]) / f"cq-{o.point.unit_id[:16]}.yaml").read_text()
    assert "max_model_len" not in text


def test_an_entry_with_no_derived_graph_is_refused_by_name(tmp_path):
    pts, env = setup(tmp_path, {f"{F}:0": prow()}, config=False)
    (env.catalog / "models" / "gpt-oss-120b" / "graph.yaml").unlink()
    o = cs.score_point(pts[0], env, tmp_path / "work")
    assert o.status == "refused" and replays(env) == []
    assert o.g5[0]["code"] == "not_in_catalog" and "no derived graph" in o.g5[0]["subject"]


def test_a_simulator_that_cannot_resolve_the_window_makes_the_point_a_named_g5_not_a_failure(tmp_path):
    fake = tmp_path / "refuse"
    fake.write_text("#!/usr/bin/env python3\nimport sys\nsys.stderr.write('level=fatal msg=\"scenario x.yaml: the first pool states no engine.max_model_len and its model graph no context window\"\\n')\nsys.exit(1)\n")
    fake.chmod(0o755)
    _, outs, _ = run(tmp_path, {f"{F}:0": prow()}, config=False, fake=str(fake))
    (o,) = outs
    assert o.status == "refused" and o.g5[0]["code"] == "value_not_recorded" and "max_model_len" in o.g5[0]["subject"]


def test_a_row_that_states_its_max_seq_len_needs_no_config_and_names_no_estimate(tmp_path):
    # The preset passes none, so a stated length makes the launch inconsistent; the scenario writer still honours it.
    pts, env = setup(tmp_path, {f"{F}:0": prow(max_seq_len="8192")}, config=False)
    sc = cs.build(pts[0], model="gpt-oss-120b", chip="b200", engine_release="0.33.0",
                  packaging={"gpus_per_node": 8, "gpus_per_rack": None})
    dep = list(yaml.safe_load_all(sc.text))[1]
    assert dep["pools"][0]["engine"]["max_model_len"] == 8192
    assert "engine.max_model_len" not in {s["subject"] for s in sc.substitutions}


def test_a_chip_whose_catalog_entry_fixes_the_node_size_is_not_given_an_assumed_one(tmp_path):
    pts, _ = setup(tmp_path, {f"{F}:0": prow()})
    sc = cs.build(pts[0], model="gpt-oss-120b", chip="gb200-nvl72", engine_release="0.33.0",
                  packaging={"gpus_per_node": 4, "gpus_per_rack": 72}, context=131072)
    scen = list(yaml.safe_load_all(sc.text))[0]
    assert "gpus_per_node" not in scen["cluster"] and "cluster.gpus_per_node" not in {s["subject"] for s in sc.substitutions}


def _test_split_rows():
    """Rows of one model whose series fall on the test split, and rows whose series do not."""
    out = {"test": None, "train": None}
    for isl in range(100, 400):
        ident = cq.identity(prow(isl=float(isl)))
        sp_ = cs.split_of(ident)
        if sp_ in out and out[sp_] is None:
            out[sp_] = isl
    return out


def test_a_point_on_the_test_split_is_withheld_not_simulated_and_its_figures_are_not_in_its_record(tmp_path):
    isl = _test_split_rows()["test"]
    _, outs, env = run(tmp_path, {f"{F}:0": prow(isl=float(isl))})
    (o,) = outs
    assert o.split == "test" and o.status == "withheld" and replays(env) == []
    r = cs.record(o)
    assert r["measured"] is None and r["whole_runs"] == [] and r["turn_slices"] == []
    assert r["grade"] is None and r["provisional"] is True      # awaiting evaluation, in the provisional band


def test_one_sweep_and_its_remeasurements_are_on_one_split():
    a, b = cq.identity(prow(concurrency=1.0)), cq.identity(prow(concurrency=512.0))
    assert cs.split_of(a) == cs.split_of(b)
    assert cs.series(a) == cs.series(b)
    assert cs.series(a) != cs.series(cq.identity(prow(isl=999.0)))


def test_a_simulator_that_drops_a_request_gives_a_failed_point_not_a_figure(tmp_path):
    fake = e2e._fake_blis(tmp_path, drop=True)
    _, outs, _ = run(tmp_path, {f"{F}:0": prow()}, fake=fake)
    (o,) = outs
    assert o.status == "failed" and o.predicted is None and o.errors is None
    r = cs.record(o)
    assert r["failed"] is True and r["grade"] is None


def test_a_simulator_that_ignores_the_closed_loop_is_a_failed_point(tmp_path):
    fake = e2e._fake_blis(tmp_path, burst=True)           # every request arrives at once: not 4 in flight
    _, outs, _ = run(tmp_path, {f"{F}:0": prow()}, fake=fake)
    assert outs[0].status == "failed"


def test_guidellms_percentile_is_the_first_value_whose_cumulative_weight_reaches_the_quantile():
    rows = [{"fate": "completed", "ttft_us": t * 1000, "e2e_us": t * 2000, "output_tokens": 10, "tpot_us": 1000.0}
            for t in (1, 2, 3, 4)]
    p = cs.predicted(rows)
    assert p["ttft_median"] == 2 and p["ttft_p95"] == 4 and p["ttft_p1"] == 1 and p["ttft_mean"] == 2.5
    assert p["request_latency_min"] == 2 and p["request_latency_max"] == 8
    # ITL is weighted by output tokens - 1: the long request carries nine tenths of the weight.
    w = [{"fate": "completed", "ttft_us": 1000, "e2e_us": 1, "output_tokens": 2, "tpot_us": 1000.0},
         {"fate": "completed", "ttft_us": 1000, "e2e_us": 1, "output_tokens": 10, "tpot_us": 9000.0}]
    q = cs.predicted(w)
    assert q["itl_median"] == 9.0 and q["itl_mean"] == pytest.approx((1.0 * 1 + 9.0 * 9) / 10)
    assert "tpot_mean" not in q            # GuideLLM records no TPOT mean; none is derived


def test_vllms_default_context_is_the_checkpoints_with_the_rope_factor_of_a_type_that_does_not_include_it():
    assert cs.vllm_max_model_len({"max_position_embeddings": 131072,
                                  "rope_scaling": {"factor": 32.0, "rope_type": "yarn"}}) == 131072
    assert cs.vllm_max_model_len({"max_position_embeddings": 8192,
                                  "rope_scaling": {"factor": 4.0, "rope_type": "linear"}}) == 32768
    nested = {"text_config": {"max_position_embeddings": 262144, "rope_parameters": {
        "full_attention": {"rope_type": "proportional"}, "sliding_attention": {"rope_type": "default"}}}}
    assert cs.vllm_max_model_len(nested) == 262144
    assert cs.vllm_max_model_len({"max_position_embeddings": 4096, "n_positions": 2048}) == 2048
    assert cs.vllm_max_model_len({"hidden_size": 8}) is None


def test_coverage_counts_what_ran_what_was_refused_by_reason_and_what_was_withheld(tmp_path):
    t = _test_split_rows()
    rows = {f"{F}:0": prow(isl=float(t["train"])),                       # scored
            f"{F}:1": prow(isl=float(t["train"]), concurrency=8.0),      # scored (same sweep)
            f"{F}:2": prow(backend="trtllm", isl=float(t["train"])),     # refused: engine
            f"{F}:3": prow(isl=float(t["test"]))}                        # withheld
    _, outs, _ = run(tmp_path, rows)
    c = cs.coverage(outs)
    assert (c["points"], c["scored"], c["refused"], c["withheld"], c["failed"]) == (4, 2, 1, 1, 0)
    assert c["runnable"] == 3 and c["runnable_share"] == 0.75
    assert list(c["refusals_by_reason"].values()) == [1] and "engine_unsupported" in next(iter(c["refusals_by_reason"]))
    assert c["dev_points"] == 3 and c["dev_scored"] == 2


def test_the_summary_keeps_provisional_points_out_of_the_graded_headline_and_its_breakdown_sums(tmp_path):
    t = _test_split_rows()
    rows = {f"{F}:{i}": prow(isl=float(t["train"]), concurrency=float(c)) for i, c in enumerate((2, 4, 8))}
    rows[f"{F}:9"] = prow(accelerator="MI300X", isl=float(t["train"]))
    _, outs, _ = run(tmp_path, rows)
    doc = cs.summary(outs, {})
    br = doc["by_source"]
    assert doc["problems"] == []
    assert br["points"] == 4 and br["graded"] == 0 and br["provisional"] == 3 and br["not_scored"] == 1
    assert sum(br["provisional_grades"].values()) == 3 and br["provisional_grades"]["G3"] + br["provisional_grades"]["G4"] == 3
    assert br["g5_reasons"] == {cq.CHIP_NOT_MODELLED: 1}


def test_error_figures_are_withheld_under_ten_points_and_reported_with_their_count_from_ten(tmp_path):
    t = _test_split_rows()
    rows = {f"{F}:{i}": prow(isl=float(t["train"]), concurrency=float(i + 1)) for i in range(10)}
    _, outs, _ = run(tmp_path, rows)
    f = cs.figures(outs)
    assert f["points"] == 10 and f["by_stat"]["ttft_mean"]["n"] == 10
    assert f["by_stat"]["ttft_mean"]["mape"] == pytest.approx(10.0)       # 180 against 200 on every point
    assert f["by_stat"]["itl_mean"]["signed_median"] == pytest.approx(-10.0)
    few = cs.figures(outs[:3])
    assert few["by_stat"]["ttft_mean"]["mape"] == cs.TOO_FEW and few["by_stat"]["ttft_mean"]["n"] == 3


def test_the_score_directory_is_written_deterministically_with_the_contract_columns(tmp_path):
    t = _test_split_rows()
    rows = {f"{F}:{i}": prow(isl=float(t["train"]), concurrency=float(c)) for i, c in enumerate((2, 4))}
    _, outs, _ = run(tmp_path, rows)
    a, b = tmp_path / "a", tmp_path / "b"
    cs.write_outputs(a, outs, {"x": 1})
    cs.write_outputs(b, list(reversed(outs)), {"x": 1})
    for name in ("configiq-points.jsonl", "points.csv", "summary.json"):
        assert (a / name).read_text() == (b / name).read_text()
    import contract
    pts = list(csv.DictReader((a / "points.csv").open()))
    assert list(pts[0]) == contract.POINTS_HEADER and len(pts) == 2
    assert {p["grade"] for p in pts} <= {"G3", "G4"}
    recs = [json.loads(x) for x in (a / "configiq-points.jsonl").read_text().splitlines()]
    assert all(r["source"] == "configiq" and r["provisional"] for r in recs)


# ---------------------------------------------------------------------------------------------- the command

def _tagged_repo(path: Path, tag: str):
    import subprocess
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(path), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                    "--allow-empty", "-m", "x"], check=True)
    subprocess.run(["git", "-C", str(path), "tag", tag], check=True)


def _command_fixture(tmp_path, rows: dict):
    """Everything score_configiq.main reads: a tagged simulator checkout holding stack.json and a fake blis that answers
    `replay`, `catalog resolve` and the schema check (and has no `metrics`), a catalog and a registry, a ledger and the
    dataset export, and the engine's field list."""
    sim = tmp_path / "checkout"
    _tagged_repo(sim, "v0.18.0")
    stack = json.loads((HERE / "testdata" / "stack.json").read_text())
    stack["engines"][0]["version"] = "0.31.0"          # the release the fixture field list is for
    (sim / "stack.json").write_text(json.dumps(stack))
    replay = Path(e2e._fake_blis(tmp_path))
    catalog_blis = Path(e2e._exe(tmp_path / "catalog-blis", e2e.CATALOG_BLIS.format(
        models={MODEL.lower(): "gpt-oss-120b"}, chips={"b200": (None, None)})))
    body = (f"#!/usr/bin/env python3\nimport os, sys\na = sys.argv[1:]\n"
            f"if a[:2] == ['catalog', 'resolve']:\n    os.execv({str(catalog_blis)!r}, [{str(catalog_blis)!r}] + a)\n"
            f"if a[:1] == ['metrics']:\n    sys.stderr.write('unknown command'); sys.exit(2)\n"
            f"os.execv({str(replay)!r}, [{str(replay)!r}] + a)\n")
    blis = Path(e2e._exe(sim / "blis", body))
    cat = tmp_path / "catalog"
    (cat / "models" / "gpt-oss-120b").mkdir(parents=True)
    (cat / "models" / "gpt-oss-120b" / "model.yaml").write_text(yaml.safe_dump({"name": "gpt-oss-120b", "source": {"repo": MODEL}}))
    (cat / "models" / "gpt-oss-120b" / "graph.yaml").write_text("layers: []\n")
    (cat / "models" / "gpt-oss-120b" / "config.json").write_text(json.dumps({"max_position_embeddings": 131072}))
    (cat / "hardware").mkdir()
    (cat / "hardware" / "b200.yaml").write_text("TFlopsPeak: 1\n")
    reg = tmp_path / "registry"
    (reg / "coefficients").mkdir(parents=True)
    (reg / "coefficients" / "c.yaml").write_text(yaml.safe_dump({"scope": {"hardware": ["b200"]}}))
    units, report, sources = tc.ledger_files(tmp_path, rows)
    export = tmp_path / "rows.jsonl"
    export.write_text("".join(json.dumps({"file": rid.rsplit(":", 1)[0], "row": int(rid.rsplit(":", 1)[1]), "columns": c}) + "\n"
                              for rid, c in sorted(rows.items())))
    data = tmp_path / "data"
    (data / F).parent.mkdir(parents=True)
    (data / F).write_bytes(b"parquet")
    import hashlib
    src = yaml.safe_load(sources.read_text())
    src["sources"][0]["revision"]["assets"] = [{"name": F, "sha256": hashlib.sha256(b"parquet").hexdigest()}]
    sources.write_text(yaml.safe_dump(src))
    return ["--ledger", str(units.parent.parent), "--rows", str(export), "--data-dir", str(data), "--blis", str(blis),
            "--catalog", str(cat), "--registry", str(reg), "--catalog-release", "v0.15.0", "--registry-release", "v0.15.0",
            "--fields", str(HERE / "testdata" / "fields" / "fields.json"), "--harness-commit", "d" * 40,
            "--out", str(tmp_path / "out")]


def test_the_command_turns_a_configiq_dataset_row_into_a_scored_point_and_refuses_the_rest_by_name(tmp_path):
    import score_configiq as cmd
    t = _test_split_rows()
    rows = {f"{F}:0": prow(isl=float(t["train"])),
            f"{F}:1": prow(isl=float(t["train"]), backend="trtllm", concurrency=8.0),
            f"{F}:2": prow(isl=float(t["train"]), tp=4.0, concurrency=16.0),
            f"{F}:3": prow(isl=float(t["test"]))}
    args = _command_fixture(tmp_path, rows)
    assert cmd.main(args) == 0
    out = tmp_path / "out"
    recs = {r["identity"]["concurrency"] + (1000 if r["identity"]["isl"] == t["test"] else 0): r
            for r in map(json.loads, (out / "configiq-points.jsonl").read_text().splitlines())}
    scored, engine, launch, withheld = recs[4], recs[8], recs[16], recs[1004]
    assert scored["status"] == "scored" and scored["grade"] in ("G3", "G4") and scored["provisional"] is True
    assert scored["errors_pct"]["ttft_mean"] == pytest.approx((FAKE_TTFT_MS - 200.0) / 200.0 * 100)
    assert engine["g5_reason"]["code"] == "engine_unsupported" and "trtllm" in engine["g5_reason"]["subject"]
    assert launch["g5_reason"]["code"] == "value_not_recorded" and "tensor parallel size 4" in launch["g5_reason"]["subject"]
    assert withheld["status"] == "withheld" and withheld["measured"] is None
    doc = json.loads((out / "summary.json").read_text())
    c = doc["coverage"]
    assert (c["points"], c["scored"], c["refused"], c["withheld"]) == (4, 1, 2, 1) and doc["problems"] == []
    assert doc["provenance"]["simulator"]["build"] == "v0.18.0" and doc["provenance"]["split"]["withheld"] == ["test"]
    assert len(list(csv.DictReader((out / "points.csv").open()))) == 1


def test_the_command_refuses_a_simulator_checkout_that_is_not_at_the_named_build(tmp_path):
    import score_configiq as cmd
    args = _command_fixture(tmp_path, {f"{F}:0": prow()})
    assert cmd.main(args + ["--sim-build", "v0.17.0"]) == 2
    assert not (tmp_path / "out").exists()
