"""The coverage report: units and rows counted apart, every framework present, the grades summing
to the units, and a point graded without a simulator never G1 and never run (coverage.py,
score.score_point(simulate=False)).

Run: python3 -m pytest orchestrator/ingest/test_coverage.py
"""
from __future__ import annotations

import gzip
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cli  # noqa: E402
import coverage as cv  # noqa: E402
import grade as gr  # noqa: E402
import ledger_fake  # noqa: E402
import score as sc  # noqa: E402
import test_score_e2e as e2e  # noqa: E402

ROWS = {r["id"]: r for r in json.loads((HERE / "testdata" / "ledger" / "api_rows.json").read_text())}
# The log of a run with no drafter, so the fixture rows (spec_method none) agree with it.
LOG = e2e.LOG.replace(
    ", 'speculative_config': {'method': 'mtp', 'num_speculative_tokens': 2, "
    "'rejection_sample_method': 'synthetic', 'synthetic_acceptance_length': 2.4}", "")


def _single_turn(tmp: Path):
    entry, env = e2e._setup(tmp, log=LOG, spec="none")
    return entry, env


def test_a_point_graded_without_a_simulator_is_g2_never_g1_and_the_simulator_is_not_run():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _single_turn(tmp)
        o = sc._score_one(entry, tmp / "pull", tmp / "w", env, simulate=False)
        assert o.would_run_simulator and o.fidelity is not None and o.simulator is None
        assert o.fidelity["grade"] == gr.G2 and o.csv_row is None
        subjects = {(s["kind"], s["subject"]) for s in o.fidelity["substitutions"]}
        assert ("coefficient_method", "selected-entry report") in subjects      # only the Result can replace it
        assert ("client_difference", "send_gap") in subjects                    # known offline
        assert e2e._saw(env) == []                                              # blis was not run
    finally:
        shutil.rmtree(tmp)


def test_a_point_the_scorer_refuses_before_the_simulator_is_the_same_with_or_without_it():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = e2e._setup(tmp, log=LOG, spec="none", hardware="h100", chips={"h100": (None, None)}, node_size=None)
        a = sc._score_one(entry, tmp / "pull", tmp / "w1", env, simulate=False)
        b = sc._score_one(entry, tmp / "pull", tmp / "w2", env)
        assert not a.would_run_simulator and a.g5 == b.g5 == {"code": "value_not_recorded", "subject": "cluster.gpus_per_node"}
    finally:
        shutil.rmtree(tmp)


def test_an_agentic_point_graded_without_a_simulator_is_g2_and_the_simulator_is_not_run():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = e2e._agentic(tmp)
        o = sc._score_one(entry, tmp / "pull", tmp / "w", env, simulate=False)
        assert o.would_run_simulator and o.fidelity["grade"] == gr.G2
        assert ("coefficient_method", "selected-entry report") in {(s["kind"], s["subject"]) for s in o.fidelity["substitutions"]}
        assert e2e._saw(env) == []
    finally:
        shutil.rmtree(tmp)


def test_a_contract_is_never_written_from_points_graded_without_a_simulator():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _single_turn(tmp)
        o = sc._score_one(entry, tmp / "pull", tmp / "w", env, simulate=False)
        with pytest.raises(ValueError, match="without the simulator"):
            sc.write_contract(tmp / "out", [o], {})
    finally:
        shutil.rmtree(tmp)


# ---------------------------------------------------------------- the report on a tiny frozen pull

def _write_catalog(tmp: Path) -> tuple[Path, Path]:
    cat, reg = tmp / "checkout", tmp / "registry"
    (cat / "models" / "m").mkdir(parents=True)
    (cat / "models" / "m" / "model.yaml").write_text("name: m\nsource:\n  repo: org/m\n")
    (cat / "hardware").mkdir()
    (cat / "hardware" / "h200.yaml").write_text("GPUsPerNode: 8\n")
    (cat / "workloads").mkdir()
    for workload, repo, alias in (("agentx-mvp-uncapped", "semianalysisai/cc-traces-weka-062126",
                                   "semianalysis_cc_traces_weka_062126"),
                                  ("agentx-mvp", "semianalysisai/cc-traces-weka-062126-256k",
                                   "semianalysis_cc_traces_weka_062126_256k")):
        (cat / "workloads" / f"{workload}.yaml").write_text(json.dumps({"replay": {"corpus": {
            "loader": alias, "source": {"huggingface": repo, "revision": "a" * 40, "file": "traces.jsonl"},
            "sha256": "b" * 64}}}))
    (reg / "coefficients").mkdir(parents=True)
    (reg / "coefficients" / "c.yaml").write_text("scope:\n  hardware: [h200]\n")
    return cat, reg


def _pull(tmp: Path):
    """A pull of three vLLM units' worth of rows (101 and 102 are two attempts of one run, which the
    ledger joins; 109 is another concurrency), plus a TensorRT-LLM and an SGLang row the pull holds no
    artifacts of. The manifest's point ids are not the ledger's: they are of an older identity."""
    entry, env = _single_turn(tmp)
    trt = {**ROWS["109"], "id": "201", "framework": "trt", "run_url": None, "conc": 8}
    sgl = {**ROWS["109"], "id": "202", "framework": "sglang", "run_url": None, "conc": 16}
    kept = [ROWS["101"], trt, sgl, ROWS["109"]]
    ledger = ledger_fake.write(tmp / "ledger", kept)
    units = tmp / "ledger" / "units" / "inferencex.jsonl.gz"
    lines = [json.loads(x) for x in gzip.decompress(units.read_bytes()).decode().splitlines()]
    next(u for u in lines if u["measurements"][0]["record"] == "101")["measurements"][0]["duplicates"] = ["102"]
    units.write_bytes(gzip.compress("".join(json.dumps(u, sort_keys=True) + "\n" for u in lines).encode(), mtime=0))
    # Each entry's job log is of its own row's concurrency, as a real run's is.
    pts = []
    for n, rid in enumerate(("101", "109")):
        old = f"{n}" * 64
        shutil.copytree(tmp / "pull" / "points" / entry["point_id"], tmp / "pull" / "points" / old)
        r = ROWS[rid]
        (tmp / "pull" / "points" / old / "job_log.gz").write_bytes(
            gzip.compress(e2e.job_log_text(r["isl"], r["osl"], r["conc"]).encode(), mtime=0))
        pts.append({**entry, "point_id": old, "row": r, "records": [rid]})
    shutil.rmtree(tmp / "pull" / "points" / entry["point_id"])
    manifest = {"window": ["2026-06-01", "2026-06-30"], "base_models": {}, "points": pts}
    (tmp / "pull" / "manifest.json").write_text(json.dumps(manifest))
    rows = [ROWS["101"], ROWS["102"], trt, sgl, ROWS["109"], {**ROWS["109"], "id": "999", "conc": 64}]
    (tmp / "rows.json").write_text(json.dumps(rows))
    cat, reg = _write_catalog(tmp)
    stack = tmp / "stack.json"
    stack.write_text(json.dumps({"kind": "Stack", "toolchain": "go", "modules": [], "router": {},
                                 "engines": [{"kind": "vllm", "version": "0.31.0", "commit": "a" * 40}]}))
    return dict(pull_dir=tmp / "pull", ledger=ledger, fields_path=e2e.HERE / "testdata" / "fields" / "fields.json",
                stack_path=stack, catalog=cat, registry=reg, rows_path=tmp / "rows.json")


def test_rows_and_units_are_counted_apart_every_framework_appears_and_the_grades_sum_to_the_units():
    tmp = Path(tempfile.mkdtemp())
    try:
        doc = cv.run(**_pull(tmp))
        assert doc["rows"]["counted"] == "rows" and doc["units"]["counted"] == "units"
        # Six rows: the ledger joins 102 into 101's unit, and holds no unit for 999.
        assert doc["rows"]["in_window"] == 6 and doc["rows"]["no_unit"]["count"] == 1
        assert doc["rows"]["no_unit"]["by_reason"] == {"not_in_source_revision": 1}
        assert doc["rows"]["beyond_the_first_of_a_unit"] == 1
        assert doc["units"]["total"] == 4 and doc["units"]["total"] != doc["rows"]["in_window"]
        assert set(doc["rows"]["by_framework"]) == set(doc["units"]["by_framework"]) == {"vllm", "trt", "sglang"}
        assert doc["rows"]["by_framework"]["vllm"] == 4 and doc["units"]["by_framework"]["vllm"]["units"] == 2
        assert sum(doc["units"]["grades"].values()) == doc["units"]["total"]
        for fw in doc["units"]["by_framework"].values():
            assert sum(fw[g] for g in cv.GRADE_KEYS) == fw["units"]
        assert doc["units"]["by_framework"]["trt"]["G5"] == 1 and doc["units"]["by_framework"]["sglang"]["G5"] == 1
        # The two vLLM units took the artifacts of their rows by row id, under the pull's older ids.
        assert doc["units"]["by_framework"]["vllm"]["G2"] == 2 and doc["units"]["grades"]["G1"] == 0
        assert doc["units"]["would_run_simulator"]["total"] == 2
        assert doc["g5_reasons"]["first_reason"] == {"engine_unsupported:trt": 1,
                                                     "field_unclassified:sglang: no field list published": 1}
        assert {t["reason"] for t in doc["top_not_g1"]["top"]} >= {"coefficient_method: selected-entry report"}
        assert "anchor" not in doc
    finally:
        shutil.rmtree(tmp)


def test_the_anchor_section_counts_units_on_the_list():
    tmp = Path(tempfile.mkdtemp())
    try:
        kw = _pull(tmp)
        import contract as c
        uid = c.point_id(c.unit_identity(ROWS["109"], c.run_dates([ROWS["109"]])))
        anchor = tmp / "anchor.txt"
        anchor.write_text(f"{uid}\n{'f' * 64}\n")
        doc = cv.run(**kw, units_path=anchor)["anchor"]
        assert doc["counted"] == "units" and doc["listed"] == 2 and doc["in_window"] == 1 and doc["not_in_window"] == 1
        assert doc["grades"]["G2"] == 1
    finally:
        shutil.rmtree(tmp)


def test_the_command_prints_one_json_document_and_writes_it(capsys):
    tmp = Path(tempfile.mkdtemp())
    try:
        kw = _pull(tmp)
        out = tmp / "cov.json"
        rc = cli.main(["coverage", "--pull", str(kw["pull_dir"]), "--ledger", str(kw["ledger"]), "--fields", str(kw["fields_path"]),
                       "--stack", str(kw["stack_path"]), "--catalog", str(kw["catalog"]), "--registry", str(kw["registry"]),
                       "--rows", str(kw["rows_path"]), "--out", str(out)])
        assert rc == 0
        assert json.loads(capsys.readouterr().out) == json.loads(out.read_text())
    finally:
        shutil.rmtree(tmp)


def test_a_row_that_differs_from_the_ledger_is_listed_as_a_row_with_no_unit():
    tmp = Path(tempfile.mkdtemp())
    try:
        kw = _pull(tmp)
        rows = json.loads(kw["rows_path"].read_text())
        next(r for r in rows if r["id"] == "109")["decode_tp"] = 2
        kw["rows_path"].write_text(json.dumps(rows))
        doc = cv.run(**kw)
        assert doc["rows"]["no_unit"]["by_reason"] == {"differs_from_source_revision": 1, "not_in_source_revision": 1}
        assert doc["units"]["total"] == 3
    finally:
        shutil.rmtree(tmp)


def test_a_unit_of_a_scored_engine_with_no_artifacts_in_the_pull_is_counted_apart_not_graded():
    tmp = Path(tempfile.mkdtemp())
    try:
        kw = _pull(tmp)
        m = json.loads((kw["pull_dir"] / "manifest.json").read_text())
        m["points"] = m["points"][:1]
        (kw["pull_dir"] / "manifest.json").write_text(json.dumps(m))
        doc = cv.run(**kw)
        assert doc["units"]["grades"]["not_in_pull"] == 1 and doc["units"]["not_in_pull"] == {"no_entry": 1}
        assert sum(doc["units"]["grades"].values()) == doc["units"]["total"] == 4
    finally:
        shutil.rmtree(tmp)
