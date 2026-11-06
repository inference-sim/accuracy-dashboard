"""Tests for the summary builder and validator (orchestrator/build_summary_v2.py, which writes
summary.json v3, and validate_summary_v2.py, which reads v2 and v3).

Expectations are worked by hand from the committed contract fixture
(orchestrator/ingest/testdata/contract/run-a), not read back from the builder.

Run: python3 orchestrator/test_build_summary_v2.py
"""
import json
import shutil
from collections import Counter
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


def _recount(d: Path) -> None:
    """Set provenance.json's point count to the points a test-built contract holds (COV-1)."""
    sys.path.insert(0, str(HERE / "ingest"))
    import contract as c
    n = sum(1 for _ in open(d / c.FIDELITY_JSONL)) + sum(1 for name in (c.NOT_SCORED_JSONL, c.FAILED_JSONL)
                                                       for x in open(d / name) if x.strip())
    _set_prov(d, points=n)


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


def test_only_a_g1_point_counts_in_the_strict_tier():
    doc = _build()
    grades = Counter(p["fidelity"]["grade"] for p in _points(doc))
    # The fixture holds no G1: every scored point names the four G1 conditions that are not
    # graded yet (grade.UNCHECKED_KINDS), so the strict tier is empty.
    assert grades == {"G2": 6, "G4": 3}
    assert all(p["tier"] == ("measured_or_resolved" if p["fidelity"]["grade"] == "G1" else "all") for p in _points(doc))
    assert doc["totals"]["all"]["mape"]["n"] == 9
    assert doc["totals"]["measured_or_resolved"]["mape"]["n"] == 0


def test_the_headline_covers_g1_to_g4_with_each_grades_share_and_count():
    # COV-11, by hand from run-a: 9 graded points (6 G2, 3 G4) and 5 G5. Every figure is
    # over fewer than 10 points, so each is "too few points", never a number.
    h = _build()["headline"]
    assert (h["points"], h["graded"], h["not_scored"]) == (14, 9, 5)
    assert h["headline"]["ttft"] == {"mape": "too few points", "n": 9}
    assert {g: (r["points"], r["share"]) for g, r in h["grades"].items()} == \
        {g: (n, "too few points") for g, n in (("G1", 0), ("G2", 6), ("G3", 0), ("G4", 3))}
    assert all(r["ttft"]["mape"] == "too few points" for r in h["grades"].values())


def test_the_headline_is_a_number_from_ten_points():
    import headline as hl
    pts = [{"grade": "G2", "framework": "vllm", "hardware": "h200", "release": "0.31.0", "meas_ttft_us": 100.0,
            "pred_ttft_us": 110.0, "meas_tpot_us": 10.0, "pred_tpot_us": 9.0}] * hl.MIN_POINTS
    h = hl.headline(pts)
    assert h["headline"]["ttft"]["n"] == 10 and abs(h["headline"]["ttft"]["mape"] - 10.0) < 1e-9


def test_coverage_splits_by_engine_release_chip_and_grade_and_balances():
    c = _build()["coverage"]
    assert (c["points"], c["graded"], c["not_scored"], c["failed"]) == (14, 9, 5, 0)
    assert c["by_grade"] == {"G1": 0, "G2": 6, "G3": 0, "G4": 3, "G5": 5}
    assert c["by_engine_release"]["vllm 0.31.0"]["grades"] == {"G1": 0, "G2": 6, "G3": 0, "G4": 0, "G5": 1}
    assert c["by_engine_release"]["vllm nightly or custom"]["graded"] == 2
    # h200: the TP4 curve (3, G2), TP8 (G4), MiniMax-M3 (G4), and the router point (G5).
    assert c["by_chip"]["h200"] == {"points": 6, "graded": 5, "grades": {"G1": 0, "G2": 3, "G3": 0, "G4": 2, "G5": 1}}
    assert c["left_out_records"] == 3
    assert c["g5_reasons"] == {"field_not_modelled": 2, "not_in_catalog": 2, "router_unsupported": 1}


def test_the_backlog_top_ranks_the_reasons_points_are_not_g1():
    top = _build()["backlog"]["top"]
    # All nine graded points name the four conditions that are not graded yet, so those rank first.
    assert top[:4] == [{"reason": f"{k}: not checked", "points": 9}
                       for k in ("coefficient_range", "kernel_hash", "resolved_differs", "value_class")]
    assert top[4] == {"reason": "client_difference: send_gap", "points": 3}
    assert {"reason": "G5 not_in_catalog: eagle3", "points": 2} in top and len(top) == 10


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


def test_run_b_lists_the_point_it_failed_on_and_grades_it_nowhere():
    a, b = _build("run-a"), _build("run-b")
    ids_a, ids_b = {p["point_id"] for p in _points(a)}, {p["point_id"] for p in _points(b)}
    assert len(ids_b) == 8 and ids_b < ids_a
    assert [f["faults"] for f in b["failed"]] == [["blis_refused:timeout"]]
    assert b["coverage"]["failed"] == 1 and b["coverage"]["points"] == 14 and b["headline"]["points"] == 13


def test_a_failed_point_that_is_not_a_runner_limit_stops_the_publish():
    # COV-8: a run that holds a run fault other than a runner limit publishes nothing.
    import contract as c
    d = Path(tempfile.mkdtemp()) / "run-b"
    shutil.copytree(FIXTURE / "run-b", d)
    rows = [json.loads(x) for x in (d / c.FAILED_JSONL).read_text().splitlines()]
    for fault in ("blis_refused:max_cudagraph_capture_size", "setting_differs:max_num_seqs"):
        (d / c.FAILED_JSONL).write_text(c.canonical_dumps({**rows[0], "faults": [fault]}) + "\n")
        try:
            b2.build(d, generated_at=STAMP, evaluator_commit="test")
        except b2.PublishRefused as e:
            assert "COV-8" in str(e) and fault in str(e)
            continue
        raise AssertionError(f"published a run holding {fault}")
    for limit in ("blis_refused:insufficient_memory", "blis_refused:timeout"):
        (d / c.FAILED_JSONL).write_text(c.canonical_dumps({**rows[0], "faults": [limit]}) + "\n")
        b2.build(d, generated_at=STAMP, evaluator_commit="test")


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
    assert any("not_scored/failed" in p for p in vs2.problems(doc))
    doc = _build()
    doc["coverage"]["points"] += 1
    assert any("COV-1" in p for p in vs2.problems(doc))
    doc = _build()
    doc["coverage"]["by_chip"]["h200"]["points"] += 1
    assert any("coverage.by_chip" in p for p in vs2.problems(doc))
    doc = _build()
    doc["coverage"]["g5_reasons"]["not_in_catalog"] = 9
    assert any("g5_reasons" in p for p in vs2.problems(doc))
    doc = _build()
    _points(doc)[0]["fidelity"]["build"]["distance"] = "near"
    assert vs2.problems(doc) != []
    doc = _build()
    doc["schema_version"] = 1
    assert vs2.problems(doc) != []


def test_the_validator_refuses_a_figure_under_the_minimum_or_one_that_does_not_recompute():
    # COV-11: every figure carries its count; under the minimum it is "too few points".
    doc = _build()
    doc["headline"]["grades"]["G1"]["ttft"]["mape"] = 4.2
    assert vs2.problems(doc) != []
    doc = _build()
    doc["headline"]["grades"]["G2"]["points"] = 4
    assert any("headline.grades.G2" in p for p in vs2.problems(doc))
    doc = _build()
    doc["backlog"]["top"].reverse()
    assert any("backlog.top" in p for p in vs2.problems(doc))
    doc = _build("run-b")
    doc["failed"][0]["faults"] = ["setting_differs:max_num_seqs"]
    assert any("COV-8" in p for p in vs2.problems(doc))


def test_the_backlog_published_beside_the_summary_ranks_every_blocker_per_engine():
    # COV-7, design §11.6: from run-a's points, by hand. Each entry counts the points it blocks
    # (G5) or demotes (graded below G1); "alone" counts the G5 points whose only reason it is.
    b = b2.backlog_of(_build())
    assert b["kind"] == "Backlog" and b["simulator"]["build"] == "v0.12.0"
    v = {e["entry"]: e for e in b["engines"]["vllm"]}
    assert v["client_difference:send_gap"] == {"entry": "client_difference:send_gap", "blocks": 0, "alone": 0,
                                               "demotes": 3}
    assert v["not_in_catalog:eagle3"] == {"entry": "not_in_catalog:eagle3", "blocks": 2, "alone": 1, "demotes": 0}
    assert v["router_unsupported:vllm-router"]["alone"] == 1
    assert b["engines"]["vllm"][0]["alone"] >= b["engines"]["vllm"][-1]["alone"]


def test_a_pull_date_earlier_than_its_newest_measurement_is_refused():
    # COV-9: each published pull date is no earlier than the newest measurement it covers.
    doc = _build()
    doc["provenance"]["pulled_at"] = "2026-09-01T00:00:00Z"
    assert any("COV-9" in p for p in vs2.problems(doc))


def test_the_validator_requires_one_simulator_for_every_point_of_a_summary():
    doc = _build()
    _points(doc)[0]["fidelity"]["simulator"] = {"build": "v0.99.0", "engine": {"kind": "vllm", "version": "0.31.0"},
                                                 "harness_digest": "unreleased"}
    assert any("COV-6" in p for p in vs2.problems(doc))
    # Every point names one build, but not the provenance's.
    doc = _build()
    doc["provenance"]["simulator"] = {**doc["provenance"]["simulator"], "build": "v0.99.0"}
    assert any("other than the provenance's" in p for p in vs2.problems(doc))


def _build_with_a_g1_point():
    """run-a with one G2 point made G1: its substitutions and client differences removed, its grade
    column set. The scorer writes no G1 while grade.UNCHECKED_KINDS are not graded, so the
    fixture holds none; the builder and the validator must still handle one."""
    sys.path.insert(0, str(HERE / "ingest"))
    import contract as c
    d = Path(tempfile.mkdtemp()) / "run-a"
    shutil.copytree(FIXTURE / "run-a", d)
    recs = [json.loads(x) for x in (d / c.FIDELITY_JSONL).read_text().splitlines()]
    pick = next(r for r in recs if r["grade"] == "G2")
    pick.update(grade="G1", substitutions=[])
    pick["requests"]["differences"] = []
    (d / c.FIDELITY_JSONL).write_text("".join(c.canonical_dumps(r) + "\n" for r in recs))
    text = (d / c.POINTS_CSV).read_text()
    lines = text.splitlines(keepends=True)
    col = lines[0].rstrip("\n").split(",").index("grade")
    for i, ln in enumerate(lines[1:], 1):
        cells = ln.rstrip("\n").split(",")
        if cells[col + 1] == pick["point_id"]:
            cells[col] = "G1"
            lines[i] = ",".join(cells) + "\n"
    (d / c.POINTS_CSV).write_text("".join(lines))
    return b2.build(d, generated_at=STAMP, evaluator_commit="test")


def test_the_validator_refuses_states_the_contract_forbids():
    import copy
    base = _build_with_a_g1_point()

    def bad(mutate):
        doc = copy.deepcopy(base)
        mutate(doc)
        return vs2.problems(doc) != []
    first = lambda d: _points(d)[0]
    g1 = lambda d: next(p for p in _points(d) if p["fidelity"]["grade"] == "G1")
    g2 = lambda d: next(p for p in _points(d) if p["fidelity"]["grade"] == "G2")
    assert bad(lambda d: first(d)["fidelity"].update(grade="G5"))
    for m in ("differs", "absent_in_blis", "unreadable", "conflict"):       # a refusal can't be scored
        assert bad(lambda d, m=m: g1(d)["fidelity"]["args"][0].update(match=m)), m
    assert bad(lambda d: g1(d).update(tier="all"))                          # a G1 point is in the strict tier
    assert bad(lambda d: g2(d).update(tier="measured_or_resolved"))
    assert bad(lambda d: g1(d)["fidelity"].update(run_release="0.25.0"))    # COV-6
    assert bad(lambda d: first(d)["fidelity"]["build"].update(ref="v0.99.0"))
    assert bad(lambda d: d["not_scored"][0]["identity"].update(conc=999))
    assert bad(lambda d: d["not_scored"][0].update(g5_reason={"code": "blis_refused"}))   # COV-5
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
        f["identity"]["configuration_hash"] = "9" + f["identity"]["configuration_hash"][1:]
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
    _recount(d)
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


def _pt(err, shape=None):
    return {"tier": "measured_or_resolved", "error_pct": {"ttft": err, "tpot": err}, "shape": {"ttft": shape, "tpot": shape}}


def test_every_metric_block_of_a_v3_summary_is_too_few_points_under_the_minimum():
    # COV-11 at every level: run-a has 9 points, so no block at any level holds a number, and its
    # smaller nodes (3 points) say "too few points" with their count.
    doc = _build()
    seen = []

    def walk(node):
        for tier in ("measured_or_resolved", "all"):
            for kind in ("mape", "shape"):
                b = node["metrics"][tier][kind]
                seen.append((node["level"], b["n"]))
                for m in ("ttft", "tpot"):
                    assert b[m] in (None, "too few points") or b["n"] >= 10, (node["level"], tier, kind, b)
        for r in node.get("rows", []):
            if r["level"] != "point":
                walk(r)
    assert doc["totals"]["all"]["mape"] == {"ttft": "too few points", "tpot": "too few points", "n": 9}
    for m in doc["matrix"]:
        walk(m)
    assert {lvl for lvl, _ in seen} == {"model", "workload", "gpu", "topology"}
    assert any(n == 3 for _, n in seen)
    assert vs2.problems(doc) == []


def test_the_validator_refuses_a_number_over_fewer_than_the_minimum_at_any_depth():
    import copy
    base = _build()
    topo = lambda d: d["matrix"][0]["rows"][0]["rows"][0]["rows"][0]
    for name, mutate in (
        ("totals", lambda d: d["totals"]["all"]["mape"].update(ttft=4.0)),
        ("model", lambda d: d["matrix"][0]["metrics"]["all"]["shape"].update(tpot=4.0)),
        ("workload", lambda d: d["matrix"][0]["rows"][0]["metrics"]["all"]["mape"].update(tpot=4.0)),
        ("topology", lambda d: topo(d)["metrics"]["all"]["mape"].update(ttft=4.0)),
        ("a grade share", lambda d: d["headline"]["grades"]["G1"].update(share=0.3)),
    ):
        doc = copy.deepcopy(base)
        mutate(doc)
        found = vs2.problems(doc)
        assert found, name
    import headline as hl
    doc = copy.deepcopy(base)
    topo(doc)["metrics"]["all"]["mape"].update(ttft=4.0)
    assert any("under the minimum" in x for x in hl.check_document(doc)), "the document walk names the figure"
    assert hl.check_document(base) == []
    # Enough points: a number is right and the block recomputes.
    pts = [_pt(5.0, 1.0)] * 10
    node = {"coverage": {"scored": 10}, "metrics": {t: {"mape": {"ttft": 5.0, "tpot": 5.0, "n": 10},
                                                      "shape": {"ttft": 1.0, "tpot": 1.0, "n": 10}}
                                                  for t in ("measured_or_resolved", "all")}}
    assert vs2._metric_problems("x", node, pts, 3) == []
    node["metrics"]["all"]["mape"]["ttft"] = "too few points"
    assert any("over enough points" in x for x in vs2._metric_problems("x", node, pts, 3))


def test_the_validator_checks_the_tree_against_its_points():
    import copy
    base = _build()

    def found(mutate, text):
        doc = copy.deepcopy(base)
        mutate(doc)
        return any(text in p for p in vs2.problems(doc))
    topo = lambda d: d["matrix"][0]["rows"][0]["rows"][0]["rows"][0]
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
    f["identity"]["recipe_fingerprint"] = "99" * 32
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
    _recount(d)
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
    # Both runs are graded anchor units; the matrix shows them as one point.
    assert doc["coverage"]["graded"] == 10 and len(_points(doc)) == 9 and doc["coverage"]["repeat_runs_folded"] == 1
    # one curve again, so the trend is the same three-point sweep as without the twin
    assert all(q["sweep_id"] == pts[1]["sweep_id"] for q in pts.values())
    assert pts[1]["shape"] == {"ttft": None, "tpot": None} and pts[4]["shape"]["ttft"] is not None


def test_runs_with_different_blis_inputs_are_not_folded():
    d, _, _ = _twin_contract(same_inputs=False)
    doc = b2.build(d, generated_at=STAMP, evaluator_commit="test")
    assert doc["coverage"]["graded"] == 10 and doc["coverage"]["repeat_runs_folded"] == 0
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


def test_v1_documents_are_not_v2_or_v3():
    v1 = json.loads((HERE.parent / "web" / "testdata" / "render-fixture.summary.json").read_text())
    assert vs2.problems(v1) != []


def test_every_published_v2_snapshot_still_validates():
    # COV-8: published snapshots never change, so the validator keeps reading v2 as it was.
    paths = sorted((HERE.parent / "data").glob("snapshots/*api*/summary.json")) + [HERE.parent / "data" / "latest" / "summary.json"]
    v2 = [p for p in paths if json.loads(p.read_text())["schema_version"] == 2]
    assert v2
    for p in v2:
        assert vs2.problems(json.loads(p.read_text())) == [], p


# ---------------------------------------------------------------- frozen v2 (COV-8)

FROZEN_V2 = {  # sha256 of the files as origin/main published them
    "schemas/summary.v2.json": "15959e9835ac62b9706a844fbf851a72c2727f42f3fe45b2e36612d8f5fc65e1",
    "web/testdata/render-fixture.v2.summary.json": "45bc0718088abfc4d44d061cd9aaf586bc4c71f9986dbd7728962e800b3e240e",
    "web/testdata/render-fixture.v2b.summary.json": "6dec2cb4d7f5e4adf35524726d01b72ee87d52a4216f20c8ee7c897756cf8aa5",
}


def _v2_fixture(name="render-fixture.v2.summary.json"):
    return json.loads((HERE.parent / "web" / "testdata" / name).read_text())


def test_the_v2_schema_and_its_fixtures_are_frozen_files():
    import hashlib
    for rel, want in FROZEN_V2.items():
        assert hashlib.sha256((HERE.parent / rel).read_bytes()).hexdigest() == want, rel


def test_the_frozen_v2_fixtures_validate_with_the_legacy_identity_and_ids_hash_from_it():
    import legacy_ids
    for name in ("render-fixture.v2.summary.json", "render-fixture.v2b.summary.json"):
        doc = _v2_fixture(name)
        assert vs2.problems(doc) == [], name
        pts = _points(doc)
        assert pts and all("recipe" in p["identity"] for p in pts)
        assert all(legacy_ids.legacy_point_id(p["identity"]) == p["point_id"] for p in pts)


def test_the_v2_schema_refuses_a_unit_identity_no_v2_publisher_wrote():
    # The unit identity belongs to summary v3 only; v2 stays what v2 publishers wrote.
    doc = _v2_fixture()
    unit = _build()
    uid = _points(unit)[0]["identity"]
    assert "source" in uid and "recipe" not in uid
    assert vs2.validator(2).is_valid(doc)
    _points(doc)[0]["identity"] = uid
    assert not vs2.validator(2).is_valid(doc)
    assert vs2.problems(unit) == []        # v3 takes it
    legacy_in_v3 = _build()
    _points(legacy_in_v3)[0]["identity"] = _points(_v2_fixture())[0]["identity"]
    assert vs2.problems(legacy_in_v3) != []


# ---------------------------------------------------------------- no-storage merge (#15, revised)

def test_summary_inverts_to_a_valid_contract_and_rebuilds():
    # summary.json IS the store: it must invert back to a valid contract that build() re-accepts.
    import contract as c
    summary = _build()
    tmp = Path(tempfile.mkdtemp())
    try:
        b2.summary_to_contract(summary, tmp)
        assert c.validate_dir(tmp) == []
        rebuilt = b2.build(tmp, generated_at=STAMP, evaluator_commit="test")
        # Same points, same coverage -- the inversion is lossless for identity/fidelity/counts.
        assert rebuilt["coverage"] == summary["coverage"] and rebuilt["headline"] == summary["headline"]
        assert {p["point_id"] for p in _points(rebuilt)} == {p["point_id"] for p in _points(summary)}
    finally:
        shutil.rmtree(tmp)


def test_ix_only_merge_of_delta_reproduces_the_full_summary():
    # The heart of the no-storage design: merge(prior without X, delta=X) == the full summary's
    # point set and totals, having scored only X.
    import csv
    import io
    import contract as c
    full = _build()
    all_ids = [p["point_id"] for p in _points(full)]
    delta_ids = set(all_ids[:2])
    tmp = Path(tempfile.mkdtemp())
    try:
        # prior = full minus the 2 delta points (invert, strip them, rebuild)
        prior_c = tmp / "prior"
        b2.summary_to_contract(full, prior_c)
        _strip_points(prior_c, delta_ids)
        prior = b2.build(prior_c, generated_at="2026-10-22T00:00:00Z", evaluator_commit="test")
        assert prior["coverage"]["graded"] == full["coverage"]["graded"] - 2

        # delta contract = only the 2 new points, taken from the full fixture contract
        delta_c = tmp / "delta"
        _subset_contract(FIXTURE / "run-a", delta_c, delta_ids)

        window = set(all_ids) | {n["point_id"] for n in full["not_scored"]}
        merged = b2.build_merged(prior, delta_c, window, generated_at=STAMP, evaluator_commit="test",
                                 work=tmp / "wk")
        assert merged["coverage"] == full["coverage"] and merged["headline"] == full["headline"]
        assert merged["totals"] == full["totals"]
        assert c.validate_dir(delta_c) == []
    finally:
        shutil.rmtree(tmp)


def test_merge_takes_the_pull_date_from_the_delta_not_the_prior():
    # Issue #35: an IX-only merge keeps the prior run's BLIS release, field list and corpus (nothing was re-scored)
    # but a NEW pull fetched the delta, so `pulled_at`/`pull_manifest_sha256` -- the "API pull date"
    # and "pull sha256" the UI shows, and what build() derives release_tag/snapshot_id from -- must
    # come from the delta. Otherwise the pull date freezes to the base and chains backwards while
    # the data range advances, showing a pull older than its own newest measurement.
    import contract as c
    full = _build()
    all_ids = [p["point_id"] for p in _points(full)]
    delta_ids = set(all_ids[:2])
    tmp = Path(tempfile.mkdtemp())
    try:
        prior_c = tmp / "prior"
        b2.summary_to_contract(full, prior_c)
        _strip_points(prior_c, delta_ids)
        # The prior was pulled on the 20th; the delta's fresh pull is the 24th, a distinct manifest.
        _set_prov(prior_c, pulled_at="2026-10-20T09:00:00Z", pull_manifest_sha256="a" * 64)
        prior = b2.build(prior_c, generated_at="2026-10-20T09:00:00Z", evaluator_commit="test")
        assert prior["provenance"]["pulled_at"] == "2026-10-20T09:00:00Z"

        delta_c = tmp / "delta"
        _subset_contract(FIXTURE / "run-a", delta_c, delta_ids)
        _set_prov(delta_c, pulled_at="2026-10-24T11:30:00Z", pull_manifest_sha256="b" * 64)

        window = set(all_ids) | {n["point_id"] for n in full["not_scored"]}
        merged = b2.build_merged(prior, delta_c, window, generated_at="2026-10-25T06:00:00Z",
                                 evaluator_commit="test", work=tmp / "wk")
        p = merged["provenance"]
        # The pull-event fields are the delta's...
        assert p["pulled_at"] == "2026-10-24T11:30:00Z"
        assert p["ground_truth"]["measurement_sha256"] == "b" * 64
        assert p["ground_truth"]["release_tag"] == "api-2026-10-24"  # derived from the delta pull date
        # ...and the release-identity fields stay the prior's (nothing was re-scored).
        assert p["blis"] == prior["provenance"]["blis"]
        assert p["fields_sha256"] == prior["provenance"]["fields_sha256"]
        assert p["corpora"] == prior["provenance"]["corpora"]
        assert c.validate_dir(delta_c) == []
    finally:
        shutil.rmtree(tmp)


def _set_prov(contract_dir: Path, **fields):
    """Overwrite named provenance.json fields in a contract directory (test helper)."""
    import contract as c
    p = json.loads((contract_dir / c.PROVENANCE_JSON).read_text())
    p.update(fields)
    (contract_dir / c.PROVENANCE_JSON).write_text(c.canonical_dumps(p) + "\n")


def _strip_points(contract_dir: Path, drop: set):
    """Remove `drop` point ids from a contract directory (points.csv, fidelity, facets)."""
    import csv
    import io
    import contract as c
    rows = [r for r in csv.DictReader(open(contract_dir / c.POINTS_CSV)) if r["point_id"] not in drop]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=c.POINTS_HEADER, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    (contract_dir / c.POINTS_CSV).write_text(buf.getvalue())
    fid = [json.loads(l) for l in open(contract_dir / c.FIDELITY_JSONL) if l.strip()
           and json.loads(l)["point_id"] not in drop]
    (contract_dir / c.FIDELITY_JSONL).write_text("".join(c.canonical_dumps(r) + "\n" for r in sorted(fid, key=lambda r: r["point_id"])))
    fac = {k: v for k, v in json.loads((contract_dir / c.FACETS_JSON).read_text()).items() if k not in drop}
    (contract_dir / c.FACETS_JSON).write_text(c.canonical_dumps(fac) + "\n")
    _recount(contract_dir)


def _subset_contract(src: Path, dst: Path, keep: set):
    """A new contract holding only `keep` scored point ids from `src`."""
    import csv
    import io
    import contract as c
    dst.mkdir(parents=True, exist_ok=True)
    rows = [r for r in csv.DictReader(open(src / c.POINTS_CSV)) if r["point_id"] in keep]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=c.POINTS_HEADER, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    (dst / c.POINTS_CSV).write_text(buf.getvalue())
    fid = [json.loads(l) for l in open(src / c.FIDELITY_JSONL) if l.strip() and json.loads(l)["point_id"] in keep]
    (dst / c.FIDELITY_JSONL).write_text("".join(c.canonical_dumps(r) + "\n" for r in sorted(fid, key=lambda r: r["point_id"])))
    fac = {k: v for k, v in json.loads((src / c.FACETS_JSON).read_text()).items() if k in keep}
    (dst / c.FACETS_JSON).write_text(c.canonical_dumps(fac) + "\n")
    (dst / c.NOT_SCORED_JSONL).write_text("")
    (dst / c.FAILED_JSONL).write_text("")
    shutil.copy(src / c.PROVENANCE_JSON, dst / c.PROVENANCE_JSON)
    _recount(dst)


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
