"""Tests for the extractor-to-summary contract (orchestrator/ingest/CONTRACT.md).

Run: python3 orchestrator/ingest/test_contract.py
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import contract as c  # noqa: E402

FIXTURE = HERE / "testdata" / "contract"
REPO = HERE.parent.parent

IDENT = {"source": "inferencex", "model": "dsv41flash", "hardware": "h200", "precision": "fp4",
         "framework": "vllm", "benchmark_type": "agentic_traces", "configuration_hash": "cd" * 32,
         "recipe_fingerprint": "ab" * 32, "conc": 4, "measured_date": "2026-09-21",
         "benchmark_run": 123}


def _copy(run: str) -> Path:
    d = Path(tempfile.mkdtemp()) / run
    shutil.copytree(FIXTURE / run, d)
    return d


def _lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def _write_lines(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(c.canonical_dumps(r) + "\n" for r in rows))


# ------------------------------------------------------------------ identity + encoding

def test_point_id_is_sha256_of_the_canonical_identity():
    # Worked by hand: sorted keys, no spaces.
    text = ('{"benchmark_run":123,"benchmark_type":"agentic_traces","conc":4,"configuration_hash":"'
            + "cd" * 32 + '","framework":"vllm","hardware":"h200","measured_date":"2026-09-21",'
            '"model":"dsv41flash","precision":"fp4","recipe_fingerprint":"' + "ab" * 32
            + '","source":"inferencex"}')
    assert c.point_id(IDENT) == hashlib.sha256(text.encode()).hexdigest()


def test_point_id_changes_with_the_measurement_date_and_the_benchmark_run():
    # A re-measurement is a different point, and so is another run on the same day.
    assert c.point_id(IDENT) != c.point_id({**IDENT, "measured_date": "2026-09-22"})
    assert c.point_id(IDENT) != c.point_id({**IDENT, "benchmark_run": 124})


def test_point_id_takes_a_null_fingerprint_and_a_null_run():
    assert c.point_id({**IDENT, "recipe_fingerprint": None, "benchmark_run": None})
    for bad in ({**IDENT, "recipe_fingerprint": ""}, {**IDENT, "benchmark_run": "123"},
                {**IDENT, "source": "another-source"}):
        try:
            c.point_id(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")


def test_point_id_rejects_missing_or_extra_fields():
    for bad in ({k: v for k, v in IDENT.items() if k != "conc"}, {**IDENT, "blis_release": "v0.12.0"}):
        try:
            c.point_id(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {sorted(bad)}")


def test_point_id_rejects_a_string_concurrency():
    try:
        c.point_id({**IDENT, "conc": "4"})
    except ValueError:
        return
    raise AssertionError("accepted conc as a string")


def test_ratio_str_keeps_four_significant_figures_and_trailing_zeros():
    assert c.ratio_str(9787503, 9787503) == "1.000"
    assert c.ratio_str(21002240, 20039988) == "1.048"
    assert c.ratio_str(1, 3) == "0.3333"
    assert c.ratio_str(5, 0) is None and c.ratio_str(None, 3) is None


def test_canonical_dumps_sorts_keys_without_spaces_and_keeps_utf8():
    assert c.canonical_dumps({"b": 1, "a": [1, {"d": "→", "c": None}]}) == '{"a":[1,{"c":null,"d":"→"}],"b":1}'


# ------------------------------------------------------------------ the committed fixture

def test_committed_fixture_runs_are_valid():
    for run in ("run-a", "run-b"):
        assert c.validate_dir(FIXTURE / run) == [], run


def test_committed_fixture_matches_its_generator():
    # The fixture is generated; generate into a temp dir (never over the committed files) and compare.
    tmp = Path(tempfile.mkdtemp())
    subprocess.run([sys.executable, str(FIXTURE / "build_fixture.py"), str(tmp)], check=True,
                   capture_output=True)
    for run in ("run-a", "run-b"):
        for name in c.CONTRACT_FILES:
            assert (FIXTURE / run / name).read_bytes() == (tmp / run / name).read_bytes(), f"{run}/{name}"


def test_fixture_run_b_shares_all_but_one_scored_point_with_run_a():
    def ids(run, name):
        return {json.loads(x)["point_id"] for x in (FIXTURE / run / name).read_text().splitlines() if x}
    a, b = ids("run-a", c.FIDELITY_JSONL), ids("run-b", c.FIDELITY_JSONL)
    assert len(a) == 9 and len(b) == 8 and b < a
    dropped = (a - b).pop()
    assert dropped in ids("run-b", c.FAILED_JSONL)
    assert dropped not in ids("run-b", c.NOT_SCORED_JSONL)


def test_the_fixture_holds_every_graded_grade_but_g3_and_a_g5():
    grades = {r["grade"] for r in _lines(FIXTURE / "run-a" / c.FIDELITY_JSONL)}
    assert grades == {"G1", "G2", "G4"}
    assert {r["grade"] for r in _lines(FIXTURE / "run-a" / c.NOT_SCORED_JSONL)} == {"G5"}


# ------------------------------------------------------------------ the validator catches breakage

def test_validator_reports_a_missing_file():
    d = _copy("run-a")
    (d / c.FACETS_JSON).unlink()
    assert c.validate_dir(d) == ["missing facets.json"]


def test_validator_rejects_a_changed_csv_header():
    d = _copy("run-a")
    text = (d / c.POINTS_CSV).read_text().replace("measured_date", "date", 1)
    (d / c.POINTS_CSV).write_text(text)
    assert any("header" in p for p in c.validate_dir(d))


def test_validator_rejects_a_point_id_that_does_not_hash_from_its_identity():
    d = _copy("run-a")
    facets = json.loads((d / c.FACETS_JSON).read_text())
    pid = next(iter(facets))
    facets[pid]["identity"]["conc"] += 1
    (d / c.FACETS_JSON).write_text(c.canonical_dumps(facets) + "\n")
    assert any("hashes to a different id" in p for p in c.validate_dir(d))


def test_validator_rejects_an_unknown_match_value():
    d = _copy("run-a")
    rows = _lines(d / c.FIDELITY_JSONL)
    rows[0]["args"][0]["match"] = "close_enough"
    _write_lines(d / c.FIDELITY_JSONL, rows)
    assert any("close_enough" in p for p in c.validate_dir(d))


def test_validator_rejects_a_scored_point_graded_g5():
    d = _copy("run-a")
    rows = _lines(d / c.FIDELITY_JSONL)
    rows[0]["grade"] = "G5"
    _write_lines(d / c.FIDELITY_JSONL, rows)
    assert any("grade" in p and "G5" in p for p in c.validate_dir(d))


def test_validator_rejects_a_g5_reason_off_the_closed_list():
    # COV-5: G5 is only for design §11.4's reasons.
    for code in ("looked_wrong", "blis_refused", "setting_not_modelled"):
        d = _copy("run-a")
        rows = _lines(d / c.NOT_SCORED_JSONL)
        rows[0]["g5_reason"] = rows[0]["g5_reasons"][0] = {"code": code}
        _write_lines(d / c.NOT_SCORED_JSONL, rows)
        assert any(f"G5 reason {code!r}" in p for p in c.validate_dir(d)), code


def test_validator_rejects_unsorted_g5_reasons_and_a_reason_not_among_them():
    d = _copy("run-a")
    rows = _lines(d / c.NOT_SCORED_JSONL)
    two = next(r for r in rows if len(r["g5_reasons"]) == 2)
    two["g5_reasons"].reverse()
    _write_lines(d / c.NOT_SCORED_JSONL, rows)
    assert any("g5_reasons must be sorted" in p for p in c.validate_dir(d))
    d = _copy("run-a")
    rows = _lines(d / c.NOT_SCORED_JSONL)
    rows[0]["g5_reason"] = {"code": "value_conflict", "subject": "max_num_seqs"}
    _write_lines(d / c.NOT_SCORED_JSONL, rows)
    assert any("not one of its g5_reasons" in p for p in c.validate_dir(d))


def test_validator_rejects_a_fault_that_is_not_a_run_fault():
    d = _copy("run-b")
    rows = _lines(d / c.FAILED_JSONL)
    rows[0]["faults"] = ["model_not_in_catalog"]
    _write_lines(d / c.FAILED_JSONL, rows)
    assert any("failed.jsonl:1 at faults/0" in p for p in c.validate_dir(d))


def test_validator_rejects_a_point_that_is_both_not_scored_and_failed():
    d = _copy("run-b")
    ns = _lines(d / c.NOT_SCORED_JSONL)
    f = _lines(d / c.FAILED_JSONL)
    _write_lines(d / c.FAILED_JSONL, sorted(f + [{**{k: v for k, v in ns[0].items() if not k.startswith(("g5", "grade"))},
                                                  "faults": ["blis_refused"]}], key=lambda r: r["point_id"]))
    assert any("both not scored and failed" in p for p in c.validate_dir(d))


def test_validator_requires_the_counts_to_sum_to_the_points():
    # COV-1: every point is graded G1 to G4, listed as G5, or listed as failed, exactly once.
    d = _copy("run-b")
    prov = json.loads((d / c.PROVENANCE_JSON).read_text())
    prov["points"] += 1
    (d / c.PROVENANCE_JSON).write_text(c.canonical_dumps(prov) + "\n")
    assert any("(COV-1)" in p for p in c.validate_dir(d))


def test_validator_holds_each_grade_to_the_points_release():
    # COV-6: a point measured on another release is G3 or G4; one on the scored release is G1 or G2.
    d = _copy("run-a")
    rows = _lines(d / c.FIDELITY_JSONL)
    g1 = next(r for r in rows if r["grade"] == "G1")
    g1["run_release"] = "0.25.0"
    _write_lines(d / c.FIDELITY_JSONL, rows)
    assert any("COV-6" in p for p in c.validate_dir(d))
    d = _copy("run-a")
    prov = json.loads((d / c.PROVENANCE_JSON).read_text())
    prov["engine"]["version"] = "0.32.0"
    (d / c.PROVENANCE_JSON).write_text(c.canonical_dumps(prov) + "\n")
    assert any("COV-6" in p for p in c.validate_dir(d))


def test_validator_rejects_a_graded_point_that_names_no_substitution():
    # COV-4: every substitution is named; a G2 point with none is refused by the schema.
    d = _copy("run-a")
    rows = _lines(d / c.FIDELITY_JSONL)
    g2 = next(r for r in rows if r["grade"] == "G2")
    g2["substitutions"] = []
    _write_lines(d / c.FIDELITY_JSONL, rows)
    assert any("substitution" in p for p in c.validate_dir(d))


def test_validator_rejects_a_point_that_is_both_scored_and_not_scored():
    d = _copy("run-a")
    scored = _lines(d / c.FIDELITY_JSONL)[0]["point_id"]
    rows = _lines(d / c.NOT_SCORED_JSONL)
    rows[0]["point_id"] = scored
    _write_lines(d / c.NOT_SCORED_JSONL, rows)
    assert any("is also scored" in p for p in c.validate_dir(d))


def test_validator_rejects_non_canonical_json():
    d = _copy("run-a")
    prov = json.loads((d / c.PROVENANCE_JSON).read_text())
    (d / c.PROVENANCE_JSON).write_text(json.dumps(prov, indent=2) + "\n")
    assert "provenance.json is not canonical JSON" in c.validate_dir(d)


def test_validator_reports_malformed_files_instead_of_raising():
    cases = {
        c.FIDELITY_JSONL: lambda d: (d / c.FIDELITY_JSONL).write_text("{not json\n"),
        c.FACETS_JSON: lambda d: (d / c.FACETS_JSON).write_text("[1, 2]\n"),
        c.PROVENANCE_JSON: lambda d: (d / c.PROVENANCE_JSON).write_text("{oops\n"),
        c.POINTS_CSV: lambda d: (d / c.POINTS_CSV).write_text(",".join(c.POINTS_HEADER) + "\nshort,row\n"),
        "identity": lambda d: (d / c.FACETS_JSON).write_text(c.canonical_dumps(
            {k: {**v, "identity": "x"} for k, v in json.loads((d / c.FACETS_JSON).read_text()).items()}) + "\n"),
    }
    for name, breaker in cases.items():
        d = _copy("run-a")
        breaker(d)
        problems = c.validate_dir(d)          # must not raise
        assert problems, name


def test_validator_rejects_extra_facets():
    d = _copy("run-a")
    facets = json.loads((d / c.FACETS_JSON).read_text())
    facets["0" * 64] = next(iter(facets.values()))
    (d / c.FACETS_JSON).write_text(c.canonical_dumps(facets) + "\n")
    assert "facets.json ids != points.csv ids" in c.validate_dir(d)


def test_validator_rejects_unsorted_rows_args_and_lines():
    d = _copy("run-a")
    lines = (d / c.POINTS_CSV).read_text().splitlines()
    (d / c.POINTS_CSV).write_text("\n".join([lines[0], *reversed(lines[1:])]) + "\n")
    assert any("rows are not in" in p for p in c.validate_dir(d))
    d = _copy("run-a")
    rows = _lines(d / c.FIDELITY_JSONL)
    multi = next(r for r in rows if len(r["args"]) > 1)
    multi["args"].reverse()
    _write_lines(d / c.FIDELITY_JSONL, rows)
    assert any("args are not sorted" in p for p in c.validate_dir(d))
    d = _copy("run-a")
    _write_lines(d / c.NOT_SCORED_JSONL, list(reversed(_lines(d / c.NOT_SCORED_JSONL))))
    assert any("not_scored.jsonl: lines are not sorted" in p for p in c.validate_dir(d))


def test_validator_rejects_a_csv_concurrency_or_grade_that_disagrees():
    d = _copy("run-a")
    lines = (d / c.POINTS_CSV).read_text().splitlines()
    cols = lines[1].split(",")
    cols[4] = str(int(cols[4]) + 1)
    cols[9] = "G3" if cols[9] != "G3" else "G2"
    lines[1] = ",".join(cols)
    (d / c.POINTS_CSV).write_text("\n".join(lines) + "\n")
    problems = c.validate_dir(d)
    assert any("concurrency disagrees" in p for p in problems)
    assert any("its record" in p for p in problems)


def test_fidelity_schema_ties_the_grade_to_its_substitutions():
    import jsonschema
    v = jsonschema.Draft7Validator(json.loads(c.FIDELITY_SCHEMA.read_text()))
    recs = [{k: x for k, x in r.items() if k != "point_id"} for r in _lines(FIXTURE / "run-a" / c.FIDELITY_JSONL)]
    g1 = next(r for r in recs if r["grade"] == "G1")
    g2 = next(r for r in recs if r["grade"] == "G2")
    g4 = next(r for r in recs if r["grade"] == "G4")
    assert all(v.is_valid(r) for r in (g1, g2, g4))
    assert not v.is_valid({**g1, "substitutions": g2["substitutions"]})       # G1 names nothing
    assert not v.is_valid({**g2, "substitutions": []})                         # G2 names something
    assert not v.is_valid({**g2, "substitutions": g4["substitutions"]})        # another release is not G2
    assert not v.is_valid({**g4, "substitutions": g2["substitutions"]})        # G4 names the release or build
    assert not v.is_valid({**g2, "grade": "G1", "substitutions": []})          # a client difference is not G1
    assert not v.is_valid({**g1, "status": "exact"})                           # the old status field is gone
    assert not v.is_valid({**g1, "substitutions": [{"kind": "guess", "subject": "x", "detail": ""}]})


def test_an_estimated_build_is_scored_and_named():
    recs = [r for r in _lines(FIXTURE / "run-a" / c.FIDELITY_JSONL) if r["build"].get("why") == "custom_build"]
    assert len(recs) == 1 and recs[0]["grade"] == "G4" and recs[0]["run_release"] is None
    assert [s["kind"] for s in recs[0]["substitutions"]] == ["nightly_or_custom"]


def test_validator_requires_every_provenance_key():
    for key in c.PROVENANCE_KEYS:
        d = _copy("run-a")
        prov = json.loads((d / c.PROVENANCE_JSON).read_text())
        del prov[key]
        (d / c.PROVENANCE_JSON).write_text(c.canonical_dumps(prov) + "\n")
        assert f"provenance.json: missing {key}" in c.validate_dir(d), key


def test_fidelity_schema_ties_match_to_its_fields():
    import jsonschema
    v = jsonschema.Draft7Validator(json.loads(c.FIDELITY_SCHEMA.read_text()))
    rec = next({k: x for k, x in r.items() if k != "point_id"}
               for r in _lines(FIXTURE / "run-a" / c.FIDELITY_JSONL) if r["grade"] == "G1")
    assert v.is_valid(rec)
    assert not v.is_valid({**rec, "reasons": ["blis_refused"]})               # a graded point has no reasons
    mapped = {"arg": "kernel_config.moe_backend", "measured": "x", "blis": "x", "match": "mapped"}
    assert not v.is_valid({**rec, "args": [mapped]})                          # mapped needs blis_field
    assert v.is_valid({**rec, "args": [{**mapped, "blis_field": "engine.moe_backend"}]})
    # The scorer never writes a value of its own: no arg is a BLIS default (X19).
    dflt = {"arg": "max_num_seqs", "measured": None, "blis": 1024, "match": "blis_default", "rule": "r"}
    assert not v.is_valid({**rec, "args": [dflt]})


def test_validator_rejects_a_facets_record_missing_a_key_the_builder_reads():
    d = _copy("run-a")
    facets = json.loads((d / c.FACETS_JSON).read_text())
    del facets[next(iter(facets))]["sweep_id"]
    (d / c.FACETS_JSON).write_text(c.canonical_dumps(facets) + "\n")
    assert any("lacks sweep_id" in p for p in c.validate_dir(d))


def _sweep(points: list[tuple[str, int, str]]):
    """facets + points.csv rows for (point id, concurrency, spec_method), all in one sweep."""
    base = {"sweep_id": "2151|deepseek-v4-pro-b200-fp4-vllm-tp8|1k1k", "scenario": "deepseek-v4-pro-b200-fp4-vllm-tp8",
            "label": "1k1k", "workload": "1024:1024", "vllm_version": "0.25.0", "precision": "fp4",
            "parallelism": {"tp": 8, "pp": 1, "dp": 1, "ep": 1}}
    facets = {pid: {**base, "spec_method": spec} for pid, _, spec in points}
    rows = [{"point_id": pid, "concurrency": str(conc)} for pid, conc, _ in points]
    return facets, rows


def test_validator_rejects_a_sweep_with_two_points_at_one_concurrency():
    # The InferenceX shape behind PR #31's review: one workflow ran a layout with and without MTP,
    # and both shared a sweep, so two points sat at c=1 and the trend's anchor got a value.
    facets, rows = _sweep([("a", 1, "none"), ("b", 2, "none"), ("c", 1, "none")])
    assert any("two points at one concurrency" in p for p in c._sweep_problems(facets, rows))
    facets, rows = _sweep([("a", 1, "none"), ("b", 2, "none"), ("c", 4, "none")])
    assert c._sweep_problems(facets, rows) == []


def test_validator_rejects_a_sweep_that_mixes_drafters():
    facets, rows = _sweep([("a", 1, "mtp"), ("b", 2, "none")])
    assert any("mixes spec_method" in p for p in c._sweep_problems(facets, rows))


def test_the_fixture_sweeps_are_one_deployment_each():
    d = FIXTURE / "run-a"
    facets = json.loads((d / c.FACETS_JSON).read_text())
    rows = [{"point_id": pid, "concurrency": str(f["identity"]["conc"])} for pid, f in facets.items()]
    assert c._sweep_problems(facets, rows) == []


def test_cli_exit_codes():
    good = subprocess.run([sys.executable, str(HERE / "contract.py"), str(FIXTURE / "run-a")],
                          capture_output=True, text=True)
    assert good.returncode == 0 and "VALID" in good.stdout
    d = _copy("run-a")
    (d / c.POINTS_CSV).unlink()
    bad = subprocess.run([sys.executable, str(HERE / "contract.py"), str(d)], capture_output=True, text=True)
    assert bad.returncode == 1 and "missing points.csv" in bad.stderr


# ------------------------------------------------------------------ the summary schemas

def _summary_validator(version: int):
    sys.path.insert(0, str(REPO / "orchestrator"))
    import validate_summary_v2 as vs
    return vs.validator(version)


def _published_v2() -> dict:
    return json.loads((REPO / "data" / "latest" / "summary.json").read_text())


def _v3() -> dict:
    sys.path.insert(0, str(REPO / "orchestrator"))
    import build_summary_v2 as b2
    return b2.build(FIXTURE / "run-a", generated_at="2026-10-23T00:00:00Z", evaluator_commit="test")


def _first_point(doc: dict) -> dict:
    return doc["matrix"][0]["rows"][0]["rows"][0]["rows"][0]["rows"][0]


def test_the_v2_schema_still_reads_the_published_snapshot_and_its_frozen_fidelity_record():
    # COV-8: published v2 snapshots never change; their schema and fidelity record are frozen.
    v = _summary_validator(2)
    doc = _published_v2()
    assert list(v.iter_errors(doc)) == []
    _first_point(doc)["fidelity"]["build"]["distance"] = "near"
    assert not v.is_valid(doc)
    assert not _summary_validator(2).is_valid(_v3())


def test_the_v3_schema_requires_a_graded_fidelity_record_on_every_point():
    v = _summary_validator(3)
    assert list(v.iter_errors(_v3())) == []
    for field in ("fidelity", "point_id", "identity", "measured_date", "sweep_id"):
        doc = _v3()
        del _first_point(doc)[field]
        assert not v.is_valid(doc), field
    doc = _v3()
    del _first_point(doc)["fidelity"]["grade"]
    assert not v.is_valid(doc)
    assert not v.is_valid(_published_v2())


def test_the_v3_schema_accepts_not_scored_and_failed_records_exactly_as_the_contract_writes_them():
    v = _summary_validator(3)
    doc = _v3()
    doc["not_scored"] = _lines(FIXTURE / "run-a" / c.NOT_SCORED_JSONL)
    doc["failed"] = _lines(FIXTURE / "run-b" / c.FAILED_JSONL)
    assert list(v.iter_errors(doc)) == []
    doc["not_scored"] = [{**doc["not_scored"][0], "reasons": ["model_not_in_catalog"]}]
    assert not v.is_valid(doc)


def test_the_v3_schema_requires_a_count_with_every_figure_and_too_few_points_under_the_minimum():
    v = _summary_validator(3)
    doc = _v3()
    del doc["headline"]["headline"]["ttft"]["n"]
    assert not v.is_valid(doc)
    doc = _v3()
    doc["headline"]["grades"]["G1"]["ttft"] = {"mape": 3.5, "n": 3}           # a number under the minimum
    assert not v.is_valid(doc)
    doc["headline"]["grades"]["G1"]["ttft"] = {"mape": "too few points", "n": 12}
    assert not v.is_valid(doc)
    doc["headline"]["grades"]["G1"]["ttft"] = {"mape": 3.5, "n": 12}
    assert v.is_valid(doc)


def test_v1_documents_are_neither_v2_nor_v3():
    v1 = json.loads((REPO / "web" / "testdata" / "render-fixture.summary.json").read_text())
    assert not _summary_validator(2).is_valid(v1) and not _summary_validator(3).is_valid(v1)


if __name__ == "__main__":
    import traceback
    os.chdir(REPO)
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
