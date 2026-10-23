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

IDENT = {"model": "dsv41flash", "hardware": "h200", "precision": "fp4", "framework": "vllm",
         "benchmark_type": "agentic_traces", "recipe": "ab" * 32, "conc": 4,
         "measured_date": "2026-09-21"}


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
    text = ('{"benchmark_type":"agentic_traces","conc":4,"framework":"vllm","hardware":"h200",'
            '"measured_date":"2026-09-21","model":"dsv41flash","precision":"fp4","recipe":"'
            + "ab" * 32 + '"}')
    assert c.point_id(IDENT) == hashlib.sha256(text.encode()).hexdigest()


def test_point_id_changes_with_the_measurement_date():
    # A re-measurement is a different point.
    assert c.point_id(IDENT) != c.point_id({**IDENT, "measured_date": "2026-09-22"})


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


def test_recipe_key_falls_back_to_the_row_id():
    assert c.recipe_key("cd" * 32, "445802") == "cd" * 32
    assert c.recipe_key("", "445802") == "row:445802"
    assert c.recipe_key(None, 445802) == "row:445802"
    try:
        c.recipe_key(None, None)
    except ValueError:
        return
    raise AssertionError("accepted a point with neither fingerprint nor row id")


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
    assert len(a) == 8 and len(b) == 7 and b < a
    dropped = (a - b).pop()
    assert dropped in ids("run-b", c.NOT_SCORED_JSONL)


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


def test_validator_rejects_a_scored_point_that_is_not_exact():
    d = _copy("run-a")
    rows = _lines(d / c.FIDELITY_JSONL)
    rows[0]["status"] = "not_scored"
    rows[0]["reasons"] = ["blis_refused"]
    _write_lines(d / c.FIDELITY_JSONL, rows)
    assert any("must be status exact" in p for p in c.validate_dir(d))


def test_validator_rejects_an_unknown_reason_code():
    d = _copy("run-a")
    rows = _lines(d / c.NOT_SCORED_JSONL)
    rows[0]["reasons"] = ["looked_wrong"]
    _write_lines(d / c.NOT_SCORED_JSONL, rows)
    assert any("unknown reason 'looked_wrong'" in p for p in c.validate_dir(d))


def test_validator_accepts_a_qualified_reason_and_rejects_unsorted_reasons():
    d = _copy("run-a")
    rows = _lines(d / c.NOT_SCORED_JSONL)
    rows[0]["reasons"] = ["setting_not_modelled:prefill_schedule_interval", "conflict:max_num_seqs"]
    _write_lines(d / c.NOT_SCORED_JSONL, rows)
    problems = c.validate_dir(d)
    assert any("sorted and unique" in p for p in problems)
    assert not any("unknown reason" in p for p in problems)


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


def test_validator_rejects_a_csv_concurrency_or_tier_that_disagrees():
    d = _copy("run-a")
    lines = (d / c.POINTS_CSV).read_text().splitlines()
    cols = lines[1].split(",")
    cols[4] = str(int(cols[4]) + 1)
    cols[9] = "ALL (approximate)"
    lines[1] = ",".join(cols)
    (d / c.POINTS_CSV).write_text("\n".join(lines) + "\n")
    problems = c.validate_dir(d)
    assert any("concurrency disagrees" in p for p in problems)
    assert any("scored points are MEASURED-OR-RESOLVED" in p for p in problems)


def test_validator_requires_every_provenance_key():
    for key in c.PROVENANCE_KEYS:
        d = _copy("run-a")
        prov = json.loads((d / c.PROVENANCE_JSON).read_text())
        del prov[key]
        (d / c.PROVENANCE_JSON).write_text(c.canonical_dumps(prov) + "\n")
        assert f"provenance.json: missing {key}" in c.validate_dir(d), key


def test_fidelity_schema_ties_status_to_reasons_and_match_to_its_fields():
    import jsonschema
    v = jsonschema.Draft7Validator(json.loads(c.FIDELITY_SCHEMA.read_text()))
    rec = {k: x for k, x in _lines(FIXTURE / "run-a" / c.FIDELITY_JSONL)[0].items() if k != "point_id"}
    assert v.is_valid(rec)
    assert not v.is_valid({**rec, "reasons": ["blis_refused"]})               # exact with reasons
    assert not v.is_valid({**rec, "status": "not_scored"})                    # not_scored without reasons
    assert v.is_valid({**rec, "status": "not_scored", "reasons": ["blis_refused"]})
    mapped = {"arg": "kernel_config.moe_backend", "measured": "x", "blis": "x", "match": "mapped"}
    assert not v.is_valid({**rec, "args": [mapped]})                          # mapped needs blis_field
    assert v.is_valid({**rec, "args": [{**mapped, "blis_field": "engine.moe_backend"}]})
    dflt = {"arg": "max_num_seqs", "measured": None, "blis": 1024, "match": "blis_default", "source": "blis_default"}
    assert not v.is_valid({**rec, "args": [dflt]})                            # blis_default needs rule
    assert v.is_valid({**rec, "args": [{**dflt, "rule": "r"}]})


def test_cli_exit_codes():
    good = subprocess.run([sys.executable, str(HERE / "contract.py"), str(FIXTURE / "run-a")],
                          capture_output=True, text=True)
    assert good.returncode == 0 and "VALID" in good.stdout
    d = _copy("run-a")
    (d / c.POINTS_CSV).unlink()
    bad = subprocess.run([sys.executable, str(HERE / "contract.py"), str(d)], capture_output=True, text=True)
    assert bad.returncode == 1 and "missing points.csv" in bad.stderr


# ------------------------------------------------------------------ summary.v2 schema

def _v2_validator():
    import jsonschema
    from referencing import Registry, Resource
    v2 = json.loads((REPO / "schemas" / "summary.v2.json").read_text())
    fid = json.loads(c.FIDELITY_SCHEMA.read_text())
    registry = Registry().with_resource(fid["$id"], Resource.from_contents(fid))
    return jsonschema.Draft7Validator(v2, registry=registry)


def _minimal_v2(point: dict) -> dict:
    block = {"mape": {"ttft": 1.0, "tpot": 1.0, "n": 1}, "shape": {"ttft": None, "tpot": None, "n": 0}}
    pair = {"measured_or_resolved": block, "all": block}
    cov = {"scored": 1, "total": 1}
    topo = {"level": "topology", "framework": "vllm", "engine_version": "0.30.1rc1", "precision": "fp4",
            "is_multinode": False, "parallelism": {"tp": 4}, "serving": "aggregated", "spec_method": "mtp",
            "label": "tp4 · fp4", "coverage": cov, "metrics": pair, "rows": [point]}
    gpu = {"level": "gpu", "label": "h200", "precision": "fp4", "coverage": cov, "metrics": pair, "rows": [topo]}
    wl = {"level": "workload", "label": "agentx", "isl": None, "osl": None, "coverage": cov, "metrics": pair, "rows": [gpu]}
    model = {"level": "model", "model": "deepseek-v4.1-flash", "vllm_version": "0.30.1rc1", "coverage": cov,
             "metrics": pair, "rows": [wl]}
    return {
        "schema_version": 2, "snapshot_id": "2026-10-23_blis-v0.12.0_ix-api-2026-10-23",
        "generated_at": "2026-10-23T00:00:00Z",
        "provenance": {
            "blis": {"release": "v0.12.0", "commit_sha": "f" * 40, "catalog": "0.3.0", "registry": "v0.2.0",
                     "extractor_version": "blis-latency-kernel@v0.3.0"},
            "ground_truth": {"source": "SemiAnalysis InferenceX API", "release_tag": "api-2026-10-23",
                             "measurement_sha256": "2" * 64},
            "evaluator_commit": "local", "scorer": "signedprobe", "ingest": "api", "vllm_ref": "v0.31.0",
            "vllm_max_distance": 2000, "policy_sha256": "1" * 64, "pulled_at": "2026-10-23T00:00:00Z"},
        "coverage": {"scored": 1, "not_scored": 0, "multinode_hidden": 0, "failed": 0, "not_scored_reasons": {}},
        "metrics": ["ttft", "tpot"], "totals": pair, "matrix": [model], "scope": {}, "not_scored": [],
    }


def _fixture_point() -> dict:
    rec = _lines(FIXTURE / "run-a" / c.FIDELITY_JSONL)[0]
    fid = {k: v for k, v in rec.items() if k != "point_id"}
    return {"level": "point", "concurrency": 4, "tier": "measured_or_resolved", "point_id": rec["point_id"],
            "measured_date": "2026-09-21", "fidelity": fid,
            "measured": {"ttft_ms": 1650.0, "tpot_ms": 9.4}, "predicted": {"ttft_ms": 1590.0, "tpot_ms": 8.55},
            "error_pct": {"ttft": -3.6, "tpot": -9.0}, "shape": None, "shape_reason": "< 3 concurrencies"}


def test_v2_schema_accepts_a_point_carrying_a_fixture_fidelity_record():
    errors = list(_v2_validator().iter_errors(_minimal_v2(_fixture_point())))
    assert errors == [], [e.message for e in errors]


def test_v2_schema_requires_fidelity_point_id_and_measured_date_on_every_point():
    for field in ("fidelity", "point_id", "measured_date"):
        point = _fixture_point()
        del point[field]
        assert not _v2_validator().is_valid(_minimal_v2(point)), field


def test_v2_schema_rejects_a_malformed_fidelity_record():
    point = _fixture_point()
    point["fidelity"]["build"]["distance"] = "near"
    assert not _v2_validator().is_valid(_minimal_v2(point))


def test_v2_schema_rejects_v1_documents():
    v1 = json.loads((REPO / "web" / "testdata" / "render-fixture.summary.json").read_text())
    assert not _v2_validator().is_valid(v1)


def test_v2_schema_accepts_a_not_scored_record_exactly_as_the_contract_writes_it():
    doc = _minimal_v2(_fixture_point())
    for ns in _lines(FIXTURE / "run-a" / c.NOT_SCORED_JSONL):
        doc["not_scored"] = [ns]
        errors = list(_v2_validator().iter_errors(doc))
        assert errors == [], [e.message for e in errors]
    doc["not_scored"] = [{**ns, "reasons": ["looked_wrong"]}]
    assert not _v2_validator().is_valid(doc)


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
