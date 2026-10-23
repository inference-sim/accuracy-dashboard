"""Tests for the v2 summary builder and validator (orchestrator/build_summary_v2.py, issue #30).

Expectations are worked by hand from the committed contract fixture
(orchestrator/ingest/testdata/contract/run-a), not read back from the builder.

Run: python3 orchestrator/test_build_summary_v2.py
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_summary_v2 as b2  # noqa: E402
import validate_summary_v2 as vs2  # noqa: E402

FIXTURE = HERE / "ingest" / "testdata" / "contract"
STAMP = "2026-10-23T00:00:00Z"


def _build(run="run-a", **kw):
    return b2.build(FIXTURE / run, generated_at=STAMP, evaluator_commit="test", **kw)


def _points(doc):
    return vs2.points(doc)


def _by_conc(doc, model, gpu, label_prefix):
    for m in doc["matrix"]:
        if m["model"] != model:
            continue
        for w in m["rows"]:
            for g in w["rows"]:
                if g["label"] != gpu:
                    continue
                for t in g["rows"]:
                    if t["label"].startswith(label_prefix):
                        return {p["concurrency"]: p for p in t["rows"]}
    raise KeyError((model, gpu, label_prefix))


def test_point_error_and_shape_are_v1s_arithmetic_worked_by_hand():
    # DeepSeek-V4.1-Flash h200 TP4 sweep, run-a: (conc, meas ttft, meas tpot, pred ttft, pred tpot) in ms
    # c1 (980, 8.10, 1050, 7.20)  c2 (1210, 8.65, 1260, 7.70)  c4 (1650, 9.40, 1590, 8.55)
    pts = _by_conc(_build(), "deepseek-v4.1-flash", "h200", "dp1 · ep1 · pp1 · tp4")
    assert pts[1]["error_pct"] == {"ttft": 7.1429, "tpot": -11.1111}          # 1050/980-1, 7.20/8.10-1
    assert pts[4]["error_pct"] == {"ttft": -3.6364, "tpot": -9.0426}
    assert pts[1]["shape"] == {"ttft": None, "tpot": None}                      # the anchor
    # c4: (1590/1050) / (1650/980) - 1 = -10.0606%;  (8.55/7.20) / (9.40/8.10) - 1 = +2.3271%
    assert pts[4]["shape"] == {"ttft": -10.0606, "tpot": 2.3271}
    assert pts[2]["shape"] == {"ttft": -2.8099, "tpot": 0.1445}


def test_a_sweep_with_fewer_than_three_points_has_no_shape():
    pts = _by_conc(_build(), "deepseek-v4.1-flash", "h200", "dp1 · ep1 · pp1 · tp8")
    assert pts[1]["shape"] is None and pts[1]["shape_reason"] == "< 3 concurrencies"


def test_each_point_carries_its_identity_date_and_fidelity_record():
    doc = _build()
    fid = {json.loads(l)["point_id"]: json.loads(l) for l in (FIXTURE / "run-a" / "fidelity.jsonl").read_text().splitlines()}
    for p in _points(doc):
        want = {k: v for k, v in fid[p["point_id"]].items() if k != "point_id"}
        assert p["fidelity"] == want and len(p["measured_date"]) == 10


def test_an_approximate_point_counts_in_the_all_tier_only():
    doc = _build()
    approx = [p for p in _points(doc) if p["fidelity"]["status"] == "approximate"]
    assert len(approx) == 1 and approx[0]["tier"] == "all"
    # 8 scored points, 7 exact: the strict tier's TPOT error averages 7 points, "all" averages 8.
    assert doc["totals"]["all"]["mape"]["n"] == 8
    assert doc["totals"]["measured_or_resolved"]["mape"]["n"] == 7


def test_the_tier_comes_from_the_fidelity_status_not_the_harness_tier_string():
    # Flip one exact point's points.csv tier string: the built tier still follows its fidelity record.
    import build_summary as v1
    orig = dict(v1.TIER_MAP)
    try:
        # If the builder read the harness string, every exact point would land in "all".
        v1.TIER_MAP["MEASURED-OR-RESOLVED"] = "all"
        doc = _build()
    finally:
        v1.TIER_MAP.clear()
        v1.TIER_MAP.update(orig)
    tiers = {p["fidelity"]["status"]: p["tier"] for p in _points(doc)}
    assert tiers == {"exact": "measured_or_resolved", "approximate": "all"}


def test_coverage_balances_and_counts_reasons_by_code():
    doc = _build()
    assert doc["coverage"]["scored"] == 8 and doc["coverage"]["not_scored"] == 4
    # run-a's not-scored records: drafter_not_in_catalog:eagle3 (x2, one also setting_not_modelled),
    # setting_not_modelled:prefill_schedule_interval, and build_commit_unresolvable + custom_build.
    assert doc["coverage"]["not_scored_reasons"] == {"build_commit_unresolvable": 1, "custom_build": 1,
                                                     "drafter_not_in_catalog": 2, "setting_not_modelled": 2}
    assert len(doc["not_scored"]) == 4


def test_the_built_summary_is_schema_valid_and_byte_identical_on_rebuild():
    a, b = b2.dumps(_build()), b2.dumps(_build())
    assert a == b
    assert vs2.problems(json.loads(a)) == []


def test_provenance_names_the_api_ingest_and_the_frozen_pull():
    doc = _build()
    p = doc["provenance"]
    prov_in = json.loads((FIXTURE / "run-a" / "provenance.json").read_text())
    assert p["ingest"] == "api" and p["vllm_ref"] == "v0.31.0" and p["vllm_max_distance"] == 2000
    assert p["ground_truth"]["release_tag"] == "api-2026-10-23"
    assert p["ground_truth"]["measurement_sha256"] == prov_in["pull_manifest_sha256"]
    assert doc["snapshot_id"] == "2026-10-23_blis-v0.12.0_ix-api-2026-10-23"


def test_run_b_scored_by_an_older_blis_drops_the_refused_point():
    a, b = _build("run-a"), _build("run-b")
    ids_a, ids_b = {p["point_id"] for p in _points(a)}, {p["point_id"] for p in _points(b)}
    assert len(ids_b) == 7 and ids_b < ids_a
    assert b["coverage"]["not_scored_reasons"].get("blis_refused") == 1


def test_an_invalid_contract_is_refused_not_built():
    d = Path(tempfile.mkdtemp()) / "run-a"
    shutil.copytree(FIXTURE / "run-a", d)
    lines = (d / "fidelity.jsonl").read_text().splitlines()
    rec = json.loads(lines[0])
    rec["args"][0]["match"] = "close_enough"
    lines[0] = json.dumps(rec, sort_keys=True, separators=(",", ":"))
    (d / "fidelity.jsonl").write_text("\n".join(lines) + "\n")
    try:
        b2.build(d, generated_at=STAMP, evaluator_commit="test")
    except b2.ContractError as e:
        assert "close_enough" in str(e)
        return
    raise AssertionError("built a summary from an invalid contract")


def test_the_validator_catches_coverage_that_doesnt_balance_and_malformed_fidelity():
    doc = _build()
    doc["coverage"]["not_scored"] += 1
    assert any("coverage.not_scored" in p for p in vs2.problems(doc))
    doc = _build()
    doc["coverage"]["not_scored_reasons"]["custom_build"] = 9
    assert any("not_scored_reasons" in p for p in vs2.problems(doc))
    doc = _build()
    _points(doc)[0]["fidelity"]["build"]["distance"] = "near"
    assert vs2.problems(doc) != []
    doc = _build()
    doc["schema_version"] = 1
    assert vs2.problems(doc) != []


def test_v1_documents_are_not_v2():
    v1 = json.loads((HERE.parent / "web" / "testdata" / "render-fixture.summary.json").read_text())
    assert vs2.problems(v1) != []


if __name__ == "__main__":
    import traceback
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
