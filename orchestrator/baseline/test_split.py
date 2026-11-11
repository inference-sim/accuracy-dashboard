"""The development split, the ranking metrics and the citation check (docs/m2/evaluation-protocol.md)."""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ranking as rk  # noqa: E402
import split as sp  # noqa: E402

SERIES = {"model": "minimaxm3", "hardware": "b200", "framework": "vllm", "precision": "fp8", "spec_method": "none",
          "disagg": False, "benchmark_type": "single_turn", "isl": 8192, "osl": 1024, "image": "vllm/vllm-openai:v0.32.0"}


# ---- the constants and the rule are pinned

def test_the_constants_are_pinned():
    assert (sp.SALT, sp.TRAIN_PCT, sp.VALIDATION_PCT, sp.FREEZE_DATE) == ("blis-dev-split-1", 60, 20, "2026-11-09")
    assert sp.SERIES_FIELDS == ("model", "hardware", "framework", "precision", "spec_method", "disagg",
                                "benchmark_type", "isl", "osl", "image")


def test_the_assignment_of_known_series_is_pinned():
    sid = sp.series_id(SERIES)
    assert sid == '["minimaxm3","b200","vllm","fp8","none",false,"single_turn",8192,1024,"vllm/vllm-openai:v0.32.0"]'
    assert (sp.bucket(sid), sp.split_of(sid)) == (88, "test")
    assert (sp.bucket(sp.series_id({**SERIES, "hardware": "h200"})), sp.split_of({**SERIES, "hardware": "h200"})) == (28, "train")
    assert sp.split_of({**SERIES, "model": "dsv4"}) == "test"


def test_the_split_has_the_stated_proportions_over_many_series():
    counts = {"train": 0, "validation": 0, "test": 0}
    for i in range(20000):
        counts[sp.split_of(sp.series_id({**SERIES, "isl": i}))] += 1
    assert abs(counts["train"] / 20000 - 0.60) < 0.02 and abs(counts["validation"] / 20000 - 0.20) < 0.02
    assert abs(counts["test"] / 20000 - 0.20) < 0.02


def test_every_row_of_a_series_has_one_split_whatever_its_concurrency():
    rows = [{"id": str(i), "conc": c, **{k: v for k, v in SERIES.items()}, "date": "2026-10-01"} for i, c in enumerate((1, 2, 4, 8, 64))]
    assert len({sp.split_of(sp.from_row(r)) for r in rows}) == 1


def test_a_digest_in_the_image_does_not_make_a_new_series():
    a = sp.from_row({**SERIES, "image": "vllm/vllm-openai:v0.32.0@sha256:" + "a" * 64})
    assert a == sp.from_row(SERIES)


def test_the_series_of_a_row_and_of_a_contract_point_agree():
    facets = {"identity": {"model": "minimaxm3", "hardware": "b200", "framework": "vllm", "precision": "fp8",
                           "benchmark_type": "single_turn"}, "workload": "8192:1024", "serving": "aggregated",
              "spec_method": None, "image": "vllm/vllm-openai:v0.32.0"}
    assert sp.from_contract(facets) == sp.from_row({**SERIES, "disagg": False})
    assert sp.from_contract({**facets, "serving": "disaggregated"})["disagg"] is True
    assert sp.from_contract({**facets, "workload": "agentx"})["isl"] is None        # an agentic point has no ISL/OSL


# ---- prospective, fit and selection

def test_a_point_after_the_freeze_is_prospective_whatever_its_series_hashes_to():
    train = {**SERIES, "hardware": "h200"}
    assert sp.kind_of(train, "2026-11-09") == "train" and sp.kind_of(train, "2026-11-10") == "prospective"
    assert sp.kind_of(train, "2026-11-10T03:00:00Z") == "prospective"
    assert sp.kind_of(train, None) == "train"


def test_only_train_feeds_a_fit_and_train_with_validation_a_selection():
    tr, va, te = [s for s in (({**SERIES, "isl": i}) for i in range(60)) ][:0] or (None, None, None)
    by = {}
    for i in range(200):
        s = {**SERIES, "isl": i}
        by.setdefault(sp.split_of(s), s)
    assert sp.usable_for_fit(by["train"], "2026-10-01") and not sp.usable_for_fit(by["validation"], "2026-10-01")
    assert not sp.usable_for_fit(by["test"], "2026-10-01") and not sp.usable_for_fit(by["train"], "2026-11-10")
    assert sp.usable_for_selection(by["validation"], "2026-10-01") and not sp.usable_for_selection(by["test"], "2026-10-01")
    assert not sp.usable_for_selection(by["validation"], "2026-11-10")


def test_leave_one_group_out_holds_out_one_series_and_never_sees_test_or_prospective():
    pts = [{"series": s, "kind": k, "id": f"{s}{i}"} for s, k in (("a", "train"), ("b", "train"), ("c", "validation"),
                                                                     ("d", "test"), ("e", "prospective")) for i in range(2)]
    folds = list(sp.logo_folds(pts))
    assert [f[0] for f in folds] == ["a", "b", "c"]
    for held, fit, out in folds:
        assert {p["series"] for p in out} == {held} and held not in {p["series"] for p in fit}
        assert not {p["kind"] for p in fit + out} & {"test", "prospective"}


# ---- the published list and the citation check

def rows_of():
    out = []
    for i, hw in enumerate(("b200", "h200", "b300", "h100", "gb200", "mi300x")):
        for j in range(3):
            out.append({"id": f"{1000 + i * 10 + j}", **SERIES, "hardware": hw, "run_url": f"https://github.com/o/r/actions/runs/{500 + i}/attempts/1"})
    return out


def test_the_published_list_matches_the_rule_and_the_constants():
    doc = sp.series_list(rows_of())
    assert len(doc["series"]) == 6 and sp.check_list(doc) == []
    sid = next(iter(doc["series"]))
    doc["series"][sid]["split"] = "train" if doc["series"][sid]["split"] != "train" else "test"
    assert any("the rule gives" in p for p in sp.check_list(doc))
    doc["salt"] = "other"
    assert any(p.startswith("salt") for p in sp.check_list(doc))


def test_a_citation_of_a_validation_or_test_row_or_run_is_found_and_a_train_one_is_not():
    doc = sp.series_list(rows_of())
    by = {e["split"]: (sid, e) for sid, e in doc["series"].items()}
    withheld = next((sid, e) for sid, e in doc["series"].items() if e["split"] != "train")
    train = next((sid, e) for sid, e in doc["series"].items() if e["split"] == "train")
    row, run = withheld[1]["rows"][0], withheld[1]["runs"][0]
    assert sp.cited_withheld(f"InferenceX row {row}, fp8", doc) == [f"row {row} (series {withheld[0]})"]
    assert sp.cited_withheld(f"InferenceX rows {train[1]['rows'][0]}, {row}", doc)[0].startswith(f"row {row}")
    assert sp.cited_withheld(f"InferenceX run {run}", doc) == [f"run {run} (series {withheld[0]})"]
    assert sp.cited_withheld(f"InferenceX CollectiveX run {run}", doc) == []        # a kernel sweep, not a series
    assert sp.cited_withheld(f"InferenceX row {train[1]['rows'][0]}", doc) == []
    assert sp.cited_withheld("no row cited", doc) == []


def test_the_registry_check_fails_on_an_entry_that_cites_a_withheld_series(tmp_path):
    doc = sp.series_list(rows_of())
    wsid, w = next((s, e) for s, e in doc["series"].items() if e["split"] != "train")
    tsid, t = next((s, e) for s, e in doc["series"].items() if e["split"] == "train")
    reg = tmp_path / "coefficients"
    reg.mkdir()
    (reg / "set.yaml").write_text(
        "kind: CoefficientSet\nname: s\ncoefficients:\n"
        f"  - good:\n      sources:\n        - {{kind: model, cite: \"InferenceX row {t['rows'][0]}\", role: primary}}\n"
        f"  - bad:\n      sources:\n        - {{kind: model, cite: \"InferenceX row {w['rows'][0]}\", role: primary}}\n")
    problems = sp.check_registry(tmp_path, doc)
    assert problems == [f"set.yaml: bad cites row {w['rows'][0]} (series {wsid})"]


def test_the_splits_of_a_manifest():
    row = {**SERIES, "id": "1"}
    m = {"points": [{"point_id": "p1", "row": row, "identity": {"measured_date": "2026-10-01"}},
                    {"point_id": "p2", "row": row, "identity": {"measured_date": "2026-11-10"}}]}
    a = sp.assign_manifest(m)
    assert a["p1"]["kind"] == "test" and a["p2"]["kind"] == "prospective" and a["p1"]["series"] == a["p2"]["series"]


# ---- ranking

def items():
    cfg = [("c4", 4, 1, 8e3, 4e3, 9e3, 5e3), ("c16", 16, 1, 1e4, 5e3, 1.1e4, 5.5e3), ("c64", 64, 1, 3e4, 9e3, 2.5e4, 8e3),
           ("tp2c64", 64, 2, 2.5e4, 6e3, 2.8e4, 7e3), ("c256", 256, 1, 9e4, 3e4, 1.5e5, 5e4)]
    return [{"key": k, "pred": rk.throughput_per_gpu(pt, pp, c, 100, g), "meas": rk.throughput_per_gpu(mt, mp, c, 100, g)}
            for k, c, g, mt, mp, pt, pp in cfg]


def test_the_worked_example_of_the_protocol():
    it = items()
    assert [round(i["meas"], 1) for i in it] == [990.1, 3168.3, 6949.0, 5169.6, 8366.0]
    assert [round(i["pred"], 1) for i in it] == [793.7, 2880.3, 7833.5, 4438.3, 5019.6]
    m = rk.group_metrics(it)
    assert (m["spearman"], m["kendall"], m["top1"], m["top3"]) == (pytest.approx(0.9), pytest.approx(0.8), 0, 1)
    assert m["regret"] == pytest.approx((8366.0 - 6949.0) / 8366.0, abs=1e-3)


def test_a_perfect_order_scores_one_and_a_reversed_one_minus_one():
    xs = [1.0, 2.0, 3.0, 4.0]
    assert rk.spearman(xs, xs) == pytest.approx(1) and rk.kendall(xs, xs) == pytest.approx(1)
    assert rk.spearman(xs, xs[::-1]) == pytest.approx(-1) and rk.kendall(xs, xs[::-1]) == pytest.approx(-1)
    m = rk.group_metrics([{"key": str(i), "pred": x, "meas": x} for i, x in enumerate(xs)])
    assert (m["top1"], m["top3"], m["regret"]) == (1, 1, 0)


def test_ties_get_the_mean_rank_and_a_constant_side_has_no_correlation():
    assert rk._ranks([5, 1, 5, 3]) == [3.5, 1, 3.5, 2]
    assert rk.spearman([1, 1, 1], [1, 2, 3]) is None and rk.kendall([1, 1, 1], [1, 2, 3]) is None
    assert rk.kendall([1, 2, 2, 3], [1, 2, 3, 4]) == pytest.approx(5 / (5 * 6) ** 0.5)


def test_top3_is_the_measured_best_among_the_three_predicted_best():
    meas = [10, 9, 8, 7, 1]
    pred = [1, 9, 8, 7, 10]            # the measured best (index 0) is predicted worst of five
    it = [{"key": str(i), "pred": p, "meas": m} for i, (p, m) in enumerate(zip(pred, meas))]
    m = rk.group_metrics(it)
    assert (m["top1"], m["top3"]) == (0, 0)
    pred2 = [8, 9, 10, 7, 1]
    assert rk.group_metrics([{"key": str(i), "pred": p, "meas": mm} for i, (p, mm) in enumerate(zip(pred2, meas))])["top3"] == 1


def test_the_slo_goodput_is_zero_where_a_latency_bound_is_missed():
    assert rk.slo_goodput(1e4, 5e3, 8, 100, 1, slo_tpot_ms=10) > 0
    assert rk.slo_goodput(1e4, 5e3, 8, 100, 1, slo_tpot_ms=4) == 0
    assert rk.slo_goodput(1e4, 5e3, 8, 100, 1, slo_ttft_ms=5) == 0


def test_groups_under_three_configurations_are_left_out_and_few_groups_are_not_a_number():
    pts = []
    for g in range(12):
        for c in range(3 if g < 11 else 2):
            pts.append({"model": "m", "hardware": f"h{g}", "isl": 1, "osl": 100, "concurrency": 2 ** c, "gpus": 1, "key": f"k{c}",
                        "meas_ttft_us": 1e4, "meas_tpot_us": 1e3 * (c + 1), "pred_ttft_us": 1e4, "pred_tpot_us": 1e3 * (c + 1)})
    r = rk.evaluate(pts)
    assert r["groups"] == 11 and r["left_out"] == 1 and r["top1"] == 1 and r["spearman"] == pytest.approx(1)
    assert rk.evaluate(pts[:9])["spearman"] == "too few groups"


# ---- the report

def test_a_held_out_figure_refuses_a_train_point():
    import compare as c
    ok = [{"kind": "test", "status": "scored", "grade": "G4", "meas_ttft_us": 1, "pred_ttft_us": 1, "meas_tpot_us": 1, "pred_tpot_us": 1,
           "sweep": ("a", "b"), "concurrency": 1}]
    c.held_out_figure(ok)
    with pytest.raises(c.CompareError, match="may not include"):
        c.held_out_figure(ok + [{**ok[0], "kind": "train"}])
    with pytest.raises(c.CompareError):
        c.held_out_figure([{**ok[0], "kind": None}])


def test_the_committed_series_list_follows_the_rule():
    path = HERE.parent.parent / "docs" / "m2" / "series-split.json"
    doc = json.loads(path.read_text())
    assert sp.check_list(doc) == []
    assert {e["split"] for e in doc["series"].values()} == {"train", "validation", "test"}
