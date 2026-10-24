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


def test_a_drafter_is_part_of_the_deployment_row_label():
    doc = _build()
    labels = [t["label"] for m in doc["matrix"] for w in m["rows"] for g in w["rows"] for t in g["rows"]]
    assert any(l.endswith(" · mtp") for l in labels)                  # DSv4.1-Flash with MTP
    assert not any(l.endswith(" · none") for l in labels)             # no drafter: nothing added


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
    # one with approximated settings, one on a build BLIS doesn't model (a custom image)
    assert len(approx) == 2 and all(p["tier"] == "all" for p in approx)
    assert sorted(p["fidelity"]["build"]["match"] for p in approx) == ["estimated", "exact"]
    # 9 scored points, 7 exact: the strict tier's TPOT error averages 7 points, "all" averages 9.
    assert doc["totals"]["all"]["mape"]["n"] == 9
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
    assert doc["coverage"]["scored"] == 9 and doc["coverage"]["not_scored"] == 4
    # run-a's not-scored records: drafter_not_in_catalog:eagle3 (x2, one also setting_not_modelled),
    # setting_not_modelled:prefill_schedule_interval, and model_not_in_catalog. A build is never one.
    assert doc["coverage"]["not_scored_reasons"] == {"drafter_not_in_catalog": 2, "model_not_in_catalog": 1,
                                                     "setting_not_modelled": 2}
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
    assert len(ids_b) == 8 and ids_b < ids_a
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
    doc["coverage"]["not_scored_reasons"]["model_not_in_catalog"] = 9
    assert any("not_scored_reasons" in p for p in vs2.problems(doc))
    doc = _build()
    _points(doc)[0]["fidelity"]["build"]["distance"] = "near"
    assert vs2.problems(doc) != []
    doc = _build()
    doc["schema_version"] = 1
    assert vs2.problems(doc) != []


def test_the_validator_refuses_states_the_contract_forbids():
    import copy
    base = _build()

    def bad(mutate):
        doc = copy.deepcopy(base)
        mutate(doc)
        return vs2.problems(doc) != []
    first = lambda d: _points(d)[0]
    exact = lambda d: next(p for p in _points(d) if p["fidelity"]["status"] == "exact")
    assert bad(lambda d: first(d)["fidelity"].update(status="not_scored", reasons=["blis_refused"]))
    for m in ("differs", "absent_in_blis", "unreadable", "conflict"):       # a refusal can't be scored
        assert bad(lambda d, m=m: exact(d)["fidelity"]["args"][0].update(match=m)), m
    assert bad(lambda d: first(d)["fidelity"]["build"].update(ref="v0.99.0"))
    assert bad(lambda d: exact(d)["fidelity"]["build"].update(distance=5000))
    assert bad(lambda d: first(d)["fidelity"]["build"].update(match="estimated", why="outside_distance", distance=None))
    assert bad(lambda d: d["not_scored"][0]["identity"].update(conc=999))
    assert vs2.problems(copy.deepcopy(base)) == []


def _spec_and_nospec_contract():
    """run-a with the DSv4-Pro b200 sweep copied as a no-spec twin of one deployment, sharing its
    InferenceX workflow, concurrencies and date: PR #31 review's 12 mixed rows, in miniature."""
    import csv
    sys.path.insert(0, str(HERE / "ingest"))
    import contract
    d = Path(tempfile.mkdtemp()) / "run-a"
    shutil.copytree(FIXTURE / "run-a", d)
    facets = json.loads((d / "facets.json").read_text())
    fid = {r["point_id"]: r for r in map(json.loads, (d / "fidelity.jsonl").read_text().splitlines())}
    with open(d / "points.csv", newline="") as fh:
        rows = list(csv.DictReader(fh))
    src = [r for r in rows if facets[r["point_id"]]["model"] == "deepseek-v4-pro"]
    assert len(src) == 3
    for r in src:
        f = json.loads(json.dumps(facets[r["point_id"]]))
        f["identity"]["recipe"] = "row:9" + f["identity"]["recipe"][-6:] if f["identity"]["recipe"].startswith("row:") \
            else "9" + f["identity"]["recipe"][1:]
        f["spec_method"] = "mtp"
        f["sweep_id"] += "|mtp"
        pid = contract.point_id(f["identity"])
        facets[pid] = f
        rows.append({**r, "point_id": pid, "pred_ttft_us": str(float(r["pred_ttft_us"]) * 1.1)})
        fid[pid] = {**fid[r["point_id"]], "point_id": pid}
    rows.sort(key=contract.points_sort_key)
    with open(d / "points.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=contract.POINTS_HEADER, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    (d / "facets.json").write_text(contract.canonical_dumps(facets) + "\n")
    (d / "fidelity.jsonl").write_text("".join(contract.canonical_dumps(fid[k]) + "\n" for k in sorted(fid)))
    return d, facets


def test_a_spec_and_a_no_spec_sweep_of_one_layout_are_two_rows_each_with_its_own_trend():
    d, _ = _spec_and_nospec_contract()
    doc = b2.build(d, generated_at=STAMP, evaluator_commit="test")
    assert vs2.problems(doc) == []
    rows = {t["label"]: t for m in doc["matrix"] if m["model"] == "deepseek-v4-pro"
            for w in m["rows"] for g in w["rows"] for t in g["rows"]}
    assert sorted(rows) == ["dp1 · ep1 · pp1 · tp8 · fp4", "dp1 · ep1 · pp1 · tp8 · fp4 · mtp"]
    for t in rows.values():
        concs = [p["concurrency"] for p in t["rows"]]
        assert concs == sorted(set(concs))                      # one point per concurrency
        assert t["rows"][0]["shape"] == {"ttft": None, "tpot": None}  # each row's anchor


def test_a_sweep_with_two_points_at_one_concurrency_is_refused_not_built():
    d, facets = _spec_and_nospec_contract()
    # Undo the split: both runs back in one sweep, as the extractor wrote them before the fix.
    for f in facets.values():
        f["sweep_id"] = f["sweep_id"].removesuffix("|mtp")
        f["spec_method"] = "none"
    import contract
    (d / "facets.json").write_text(contract.canonical_dumps(facets) + "\n")
    try:
        b2.build(d, generated_at=STAMP, evaluator_commit="test")
    except b2.ContractError as e:
        assert "two points at one concurrency" in str(e)
        return
    raise AssertionError("built a summary whose sweep repeats a concurrency")


def test_the_validator_checks_the_tree_against_its_points():
    import copy
    base = _build()

    def found(mutate, text):
        doc = copy.deepcopy(base)
        mutate(doc)
        return any(text in p for p in vs2.problems(doc))
    topo = lambda d: d["matrix"][0]["rows"][0]["rows"][0]["rows"][0]
    assert found(lambda d: d["totals"]["all"]["mape"].update(ttft=99.0), "totals: all mape.ttft")
    assert found(lambda d: topo(d)["metrics"]["all"]["shape"].update(n=99), "shape n 99")
    assert found(lambda d: topo(d).update(spec_method="eagle3"), "label doesn't state")
    assert found(lambda d: topo(d).update(precision="int4"), "label doesn't state")
    assert found(lambda d: topo(d)["rows"][0].update(shape={"ttft": 1.0, "tpot": 1.0}), "anchor")
    assert found(lambda d: topo(d)["rows"].append(copy.deepcopy(topo(d)["rows"][0])), "two points at one concurrency")


def test_a_gpu_whose_rows_differ_in_precision_states_none():
    d, facets = _spec_and_nospec_contract()
    import contract
    for f in facets.values():
        if f["spec_method"] == "mtp" and f["model"] == "deepseek-v4-pro":
            f["precision"] = "fp8"
    (d / "facets.json").write_text(contract.canonical_dumps(facets) + "\n")
    doc = b2.build(d, generated_at=STAMP, evaluator_commit="test")
    g = next(g for m in doc["matrix"] if m["model"] == "deepseek-v4-pro" for w in m["rows"] for g in w["rows"])
    assert g["precision"] is None and sorted(t["precision"] for t in g["rows"]) == ["fp4", "fp8"]
    assert vs2.problems(doc) == []


def test_one_deployment_on_two_vllm_builds_is_two_rows_named_by_build():
    d, facets = _spec_and_nospec_contract()
    import contract
    for f in facets.values():
        if f["spec_method"] == "mtp" and f["model"] == "deepseek-v4-pro":
            f["spec_method"] = "none"
            f["vllm_version"] = "0.32.0"
    (d / "facets.json").write_text(contract.canonical_dumps(facets) + "\n")
    doc = b2.build(d, generated_at=STAMP, evaluator_commit="test")
    labels = sorted(t["label"] for m in doc["matrix"] if m["model"] == "deepseek-v4-pro"
                    for w in m["rows"] for g in w["rows"] for t in g["rows"])
    assert len(labels) == 2 and len(set(labels)) == 2 and all(" · vLLM " in l for l in labels), labels
    assert vs2.problems(doc) == []


def _twin_contract(same_inputs: bool):
    """run-a with the DSv4-Pro b200 c=4 point run twice by InferenceX: another recipe row, its own
    sweep, the same day, a slightly different measured TTFT, and (if same_inputs) the same BLIS
    inputs and prediction. PR #31's minimax-m2.5 b300 c=1024 pair, in miniature."""
    import csv
    sys.path.insert(0, str(HERE / "ingest"))
    import contract
    d = Path(tempfile.mkdtemp()) / "run-a"
    shutil.copytree(FIXTURE / "run-a", d)
    facets = json.loads((d / "facets.json").read_text())
    fid = {r["point_id"]: r for r in map(json.loads, (d / "fidelity.jsonl").read_text().splitlines())}
    with open(d / "points.csv", newline="") as fh:
        rows = list(csv.DictReader(fh))
    src = next(r for r in rows if facets[r["point_id"]]["model"] == "deepseek-v4-pro" and r["concurrency"] == "4")
    f = json.loads(json.dumps(facets[src["point_id"]]))
    f["identity"]["recipe"] = "row:999"
    f["sweep_id"] += "|twin"
    pid = contract.point_id(f["identity"])
    facets[pid] = f
    twin = {**src, "point_id": pid, "meas_ttft_us": str(float(src["meas_ttft_us"]) + 2000.0)}
    if not same_inputs:
        twin["pred_ttft_us"] = str(float(src["pred_ttft_us"]) * 1.2)
    rows.append(twin)
    fid[pid] = {**fid[src["point_id"]], "point_id": pid}
    rows.sort(key=contract.points_sort_key)
    with open(d / "points.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=contract.POINTS_HEADER, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    (d / "facets.json").write_text(contract.canonical_dumps(facets) + "\n")
    (d / "fidelity.jsonl").write_text("".join(contract.canonical_dumps(fid[k]) + "\n" for k in sorted(fid)))
    return d, src, pid


def test_two_inferencex_runs_of_one_measurement_are_shown_once_as_their_mean():
    d, src, pid = _twin_contract(same_inputs=True)
    doc = b2.build(d, generated_at=STAMP, evaluator_commit="test")
    assert vs2.problems(doc) == []
    pts = _by_conc(doc, "deepseek-v4-pro", "b200", "dp1")
    p = pts[4]
    assert sorted(r["point_id"] for r in p["repeats"]) == sorted([src["point_id"], pid])
    assert p["point_id"] == min(src["point_id"], pid)
    assert p["measured"]["ttft_ms"] == round((float(src["meas_ttft_us"]) * 2 + 2000.0) / 2 / 1000, 4)
    assert doc["coverage"]["scored"] == 9 and doc["coverage"]["repeat_runs_folded"] == 1
    # one curve again, so the trend is the same three-point sweep as without the twin
    assert all(q["sweep_id"] == pts[1]["sweep_id"] for q in pts.values())
    assert pts[1]["shape"] == {"ttft": None, "tpot": None} and pts[4]["shape"]["ttft"] is not None


def test_runs_with_different_blis_inputs_are_not_folded():
    d, _, _ = _twin_contract(same_inputs=False)
    doc = b2.build(d, generated_at=STAMP, evaluator_commit="test")
    assert doc["coverage"]["scored"] == 10 and doc["coverage"].get("repeat_runs_folded") == 0
    assert not any(p.get("repeats") for p in _points(doc))
    assert vs2.problems(doc) == []


def test_the_validator_checks_folded_runs():
    import copy
    d, _, _ = _twin_contract(same_inputs=True)
    base = b2.build(d, generated_at=STAMP, evaluator_commit="test")
    folded = lambda doc: next(p for p in _points(doc) if p.get("repeats"))  # noqa: E731
    doc = copy.deepcopy(base)
    folded(doc)["measured"]["ttft_ms"] += 50
    assert any("mean of its runs" in p for p in vs2.problems(doc))
    doc = copy.deepcopy(base)
    doc["coverage"]["repeat_runs_folded"] = 0
    assert any("repeat_runs_folded" in p for p in vs2.problems(doc))


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
