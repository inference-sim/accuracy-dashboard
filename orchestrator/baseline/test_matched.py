"""Tests of the matched comparison (matched.py), on synthetic sweeps, dump rows and contracts written here."""
import json
import sys
import zipfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ingest"))
import headline as hl  # noqa: E402
import matched as mt  # noqa: E402

EST = "other"


@pytest.fixture(autouse=True)
def one_point_is_enough(monkeypatch, request):
    """These sweeps have three points; the minimum point count has a test of its own."""
    if "minimum" not in request.node.name:
        monkeypatch.setattr(hl, "MIN_POINTS", 1)


def sweep(tid="t1", gpu="h200", model="m", fw="vllm", tpot=(10.0, 12.0, 15.0), ttft=(100.0, 120.0, 200.0),
          est=((1.0, 1.0), (1.3, 1.1), (1.4, 2.4))):
    pts = []
    for i, c in enumerate((1, 2, 4)):
        p = {"concurrency": c, "status": "success",
             "measured_tpot_relative": tpot[i] / tpot[0], "measured_ttft_relative": ttft[i] / ttft[0]}
        if est[i] is not None:
            p[f"{EST}_tpot_relative"], p[f"{EST}_ttft_relative"] = est[i]
        pts.append(p)
    return {"topology_id": tid, "label": "1k1k", "model": model, "gpu": gpu, "framework": fw, "precision": "fp8",
            "serving": "aggregated", "workload": "1024:1024", "points": pts,
            "parallelism": {"tp_size": 8, "moe_ep_size": None, "attention_dp_size": 1, "pp_size": 1}}


def row(i, run, conc, tpot, ttft, slug="mslug", date="2026-09-01"):
    return {"id": i, "github_run_id": run, "model": slug, "hardware": "h200", "framework": "vllm", "precision": "fp8",
            "isl": 1024, "osl": 1024, "decode_tp": 8, "decode_ep": 1, "decode_dp_attention": False, "conc": conc,
            "benchmark_type": "single_turn", "disagg": False, "spec_method": "none", "error": None, "date": date,
            "metrics": {"mean_tpot": tpot, "mean_ttft": ttft}}


def test_a_sweep_is_matched_to_the_one_run_whose_curve_it_is():
    pts = {"sweeps": [sweep()]}
    rows = [row(1, 7, 1, 0.010, 0.100), row(2, 7, 2, 0.012, 0.120), row(3, 7, 4, 0.015, 0.200),
            # another run of the same deployment, another curve
            row(4, 8, 1, 0.010, 0.100), row(5, 8, 2, 0.011, 0.120), row(6, 8, 4, 0.015, 0.200),
            # a run measured after the artifact's last date
            row(7, 9, 1, 0.010, 0.100, date="2026-10-01")]
    got = mt.match(pts, rows, {"m": "mslug"}, "2026-09-27")
    assert [(e["concurrency"], e["records"]) for e in got] == [(1, ["1"]), (2, ["2"]), (4, ["3"])]


def test_two_runs_with_the_same_curve_are_not_guessed_between_and_no_run_is_no_record():
    rows = [row(i * 10 + k, run, c, t, f) for i, run in enumerate((7, 8))
            for k, (c, t, f) in enumerate(((1, 0.010, 0.100), (2, 0.012, 0.120), (4, 0.015, 0.200)))]
    assert {e.get("why") for e in mt.match({"sweeps": [sweep()]}, rows, {"m": "mslug"}, "2026-09-27")} == {"several_runs"}
    assert {e.get("why") for e in mt.match({"sweeps": [sweep()]}, [], {"m": "mslug"}, "2026-09-27")} == {"no_record"}


def entries(pred=None, kind="train", est_missing=False, sw=None, evaluate_test=False, splits_kind=None):
    """One sweep's entries, BLIS predicting `pred` (relatives) or nothing; `kind` the split the match found (None:
    no record, so no split); `splits_kind` what the harness's splits file says."""
    sw = sw or sweep(est=((1.0, 1.0), (1.3, 1.1), None) if est_missing else ((1.0, 1.0), (1.3, 1.1), (1.4, 2.4)))
    matched = [{"sweep": f"{sw['topology_id']}|1k1k", "concurrency": p["concurrency"], "unit": f"u{i}", "records": ["x"],
                **({"split": kind} if kind else {})} for i, p in enumerate(sw["points"])]
    contract = {}
    for i, p in enumerate(sw["points"]):
        if pred and pred[i] is not None:
            contract[f"u{i}"] = {"status": "scored", "grade": "G4", "meas_tpot_us": 1000 * p["measured_tpot_relative"],
                                 "pred_tpot_us": 1000 * pred[i][0], "meas_ttft_us": 1000 * p["measured_ttft_relative"],
                                 "pred_ttft_us": 1000 * pred[i][1]}
        else:
            contract[f"u{i}"] = {"status": "not_scored", "grade": "G5", "reason": "field_not_modelled"}
    splits = {f"u{i}": {"kind": splits_kind or kind} for i in range(3)} if (splits_kind or kind) else {}
    return mt.entries_for({"sweeps": [sw]}, matched, contract, splits, EST, evaluate_test=evaluate_test)


def test_the_metric_is_the_artifacts_mape_and_shape():
    es = entries(pred=[(1.0, 1.0), (1.2, 1.2), (1.5, 2.0)])
    b, x = mt.cell_figures(es, "blis"), mt.cell_figures(es, "est")
    # measured tpot relatives 1, 1.2, 1.5; the estimator's 1, 1.3, 1.4
    assert x["tpot_mape_pct"] == pytest.approx((0 + 0.1 / 1.2 + 0.1 / 1.5) / 3 * 100)
    # shape: own curve over its value at the lowest concurrency
    assert x["tpot_shape_pct"] == pytest.approx((0.1 / 1.2 + 0.1 / 1.5) / 2 * 100)
    assert b["tpot_mape_pct"] == pytest.approx(0) and b["tpot_shape_pct"] == pytest.approx(0)
    assert b["ttft_mape_pct"] == pytest.approx((0 + 0 + 0) / 3 * 100)


def test_a_point_blis_refuses_counts_against_its_coverage_and_its_cell():
    es = entries(pred=[(1.0, 1.0), (1.2, 1.2), None])
    b = mt.cell_figures(es, "blis")
    assert (b["covered"], b["points"]) == (2, 3)
    rep = mt.build_report(es, EST, {}, False)
    cell = rep["cells"][0]
    assert cell["blis_uncovered"] == {"field_not_modelled": 1}
    assert cell["won"] is False                       # better errors, but less coverage than the estimator
    assert rep["lanes"]["vllm"]["cells_won"] == 0


def test_a_cell_is_won_only_on_every_metric_with_at_least_the_coverage():
    rep = mt.build_report(entries(pred=[(1.0, 1.0), (1.2, 1.2), (1.5, 2.0)]), EST, {}, False)
    assert rep["cells"][0]["won"] is True
    worse_ttft = [(1.0, 1.0), (1.2, 1.5), (1.5, 3.0)]
    assert mt.build_report(entries(pred=worse_ttft), EST, {}, False)["cells"][0]["won"] is False


def test_test_points_are_withheld_from_errors_and_kept_in_coverage():
    es = entries(pred=[(1.0, 1.0), (1.2, 1.2), (1.5, 2.0)], kind="test")
    b = mt.cell_figures(es, "blis")
    assert (b["covered"], b["with_figures"], b["tpot_mape_pct"]) == (3, 0, None)


def test_a_point_of_no_known_split_is_withheld_even_in_a_logged_evaluation_and_refused_if_scored():
    for ev in (False, True):
        es = entries(pred=None, kind=None, evaluate_test=ev)
        x = mt.cell_figures(es, "est")
        assert (x["covered"], x["with_figures"], x["tpot_mape_pct"]) == (3, 0, None), ev
        assert mt.split_counts(es)["unknown"] == {"points": 3, "scored": 0, "withheld": 3}
        with pytest.raises(mt.MatchError, match="is scored and has no split"):
            entries(pred=[(1.0, 1.0), (1.2, 1.2), (1.5, 2.0)], kind=None, evaluate_test=ev)


def test_a_logged_evaluation_shows_the_test_points_and_names_its_log_rows():
    es = entries(pred=[(1.0, 1.0), (1.2, 1.2), (1.5, 2.0)], kind="test", evaluate_test=True)
    assert mt.cell_figures(es, "blis")["with_figures"] == 3
    with pytest.raises(mt.MatchError, match="evaluation-log rows"):
        mt.build_report(es, EST, {}, True)
    rep = mt.build_report(es, EST, {}, True, ["| row |"])
    assert rep["evaluation"] == ["| row |"] and rep["splits"]["test"]["withheld"] == 0


def test_a_split_the_record_and_the_splits_file_disagree_on_is_refused():
    with pytest.raises(mt.MatchError, match="the splits file says"):
        entries(pred=[(1.0, 1.0), (1.2, 1.2), (1.5, 2.0)], kind="train", splits_kind="test")


def test_a_matched_record_carries_its_development_split():
    import split as dsplit
    rows = [row(1, 7, 1, 0.010, 0.100), row(2, 7, 2, 0.012, 0.120), row(3, 7, 4, 0.015, 0.200)]
    got = mt.match({"sweeps": [sweep()]}, rows, {"m": "mslug"}, "2026-09-27")
    want = dsplit.kind_of(dsplit.series_id(dsplit.from_row(rows[0])), "2026-09-01")
    assert {e["split"] for e in got} == {want}


def test_a_zip_other_than_the_pinned_one_is_refused(tmp_path):
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("summary.json", "{}")
    pin = tmp_path / "pin.json"
    pin.write_text(json.dumps({"zip_sha256": "0" * 64, "summary_sha256": "0" * 64}))
    with pytest.raises(mt.MatchError, match="the pin records"):
        mt.extract_points(z, pin, tmp_path / "x.py", tmp_path / "out.json")


def test_a_logged_evaluation_appends_a_row_per_held_out_kind(tmp_path):
    log = tmp_path / "log.md"
    named = mt.log_evaluation(log, "c" * 40, "label", entries(pred=[(1.0, 1.0), (1.2, 1.2), None], kind="test"))
    rows = [x for x in log.read_text().splitlines() if x.startswith("| 2")]
    assert named == rows
    # a repeat of the same evaluation is logged again, and its report names every row of it
    again = mt.log_evaluation(log, "c" * 40, "label", entries(pred=[(1.0, 1.0), (1.2, 1.2), None], kind="test"))
    assert len(again) == 4 and again == [x for x in log.read_text().splitlines() if x.startswith("| 2")]
    assert [r.split(" | ")[2:] for r in rows] == [["label", "test", "3", "2 |"], ["label", "prospective", "0", "0 |"]]


def test_a_unit_the_pull_cannot_read_is_listed_and_left_out_of_the_pull(tmp_path, monkeypatch):
    calls = []

    def fake_pull(matched, rows, units, *, out, **kw):
        calls.append(list(units))
        out.mkdir(parents=True, exist_ok=True)
        pts = [{"point_id": u, "reasons": ["artifact_unmatched:pull_error"] if u == "bad" else [],
                "problems": ["<HTTPError 404: 'Not Found'>"] if u == "bad" else []} for u in units]
        (out / "manifest.json").write_text(json.dumps({"points": pts}))
        return 1 if "bad" in units else 0
    monkeypatch.setattr(mt, "_pull", fake_pull)
    matched = [{"unit": "bad", "records": ["1"]}, {"unit": "good", "records": ["2"]}, {"unit": None, "records": []}]
    errs = tmp_path / "errors.json"
    rc = mt.freeze(matched, [], ledger_dir=tmp_path, out=tmp_path / "pull", cache=tmp_path, workers=1, errors_out=errs)
    assert rc == 0 and calls == [["bad", "good"], ["good"]]
    assert json.loads(errs.read_text()) == {"bad": "<HTTPError 404: 'Not Found'>"}


def test_a_figure_under_the_minimum_point_count_is_too_few_points_and_wins_nothing_minimum():
    es = entries(pred=[(1.0, 1.0), (1.2, 1.2), (1.5, 2.0)])
    b = mt.cell_figures(es, "blis")
    assert (b["tpot_mape_pct"], b["tpot_mape_n"], b["tpot_shape_n"]) == (hl.TOO_FEW, 3, 2)
    assert mt.build_report(es, EST, {}, False)["cells"][0]["won"] is False


def test_the_like_for_like_shape_uses_each_sweeps_own_lowest_concurrency():
    # BLIS does not cover c0: neither side gets a shape from the sweep, though both cover c2 and c4
    es = entries(pred=[None, (1.2, 1.2), (1.5, 2.0)])
    x = mt.cell_figures(es, "est", only=lambda e: e.get("blis_tpot") is not None)
    assert (x["tpot_shape_n"], x["tpot_mape_n"]) == (0, 2)
    assert mt.cell_figures(es, "blis")["tpot_shape_n"] == 0


def test_only_the_records_that_reproduce_both_metrics_against_one_base_are_taken():
    rows = [row(1, 7, 1, 0.010, 0.100), row(2, 7, 2, 0.012, 0.120), row(3, 7, 4, 0.015, 0.200),
            row(4, 7, 2, 0.012, 0.300)]          # a second record at c2: its TPOT fits, its TTFT does not
    got = mt.match({"sweeps": [sweep()]}, rows, {"m": "mslug"}, "2026-09-27")
    assert [e["records"] for e in got] == [["1"], ["2"], ["3"]]
    # a curve whose TPOT and TTFT are each reproduced only by a different record is no match
    rows = [row(1, 7, 1, 0.010, 0.100), row(2, 7, 2, 0.012, 0.300), row(5, 7, 2, 0.050, 0.120), row(3, 7, 4, 0.015, 0.200)]
    assert {e.get("why") for e in mt.match({"sweeps": [sweep()]}, rows, {"m": "mslug"}, "2026-09-27")} == {"no_record"}


def test_a_one_point_sweep_is_not_matched_by_curve():
    sw = sweep()
    sw["points"] = sw["points"][:1]
    got = mt.match({"sweeps": [sw]}, [row(1, 7, 1, 0.010, 0.100)], {"m": "mslug"}, "2026-09-27")
    assert got[0]["why"] == "one_point_sweep" and got[0]["records"] == []


def test_every_point_has_its_series_split_whether_or_not_a_record_is_found():
    import split as dsplit
    want = dsplit.split_of(dsplit.series_id({"model": "mslug", "hardware": "h200", "precision": "fp8", "framework": "vllm",
                                             "spec_method": "none", "disagg": False}))
    assert {e["split"] for e in mt.match({"sweeps": [sweep()]}, [], {"m": "mslug"}, "2026-09-27")} == {want}


def test_a_pull_error_is_a_gone_record_only_for_404_or_410():
    assert mt.pull_error_reason("<HTTPError 404: 'Not Found'>") == "record_gone: HTTP 404"
    assert mt.pull_error_reason("<HTTPError 410: 'Gone'>") == "record_gone: HTTP 410"
    assert mt.pull_error_reason("<HTTPError 502: 'Bad Gateway'>").startswith("pull_error: <HTTPError 502")
    assert mt.pull_error_reason("TimeoutError()").startswith("pull_error: TimeoutError")


def test_an_estimator_point_with_one_of_its_two_figures_is_refused_by_name():
    sw = sweep()
    del sw["points"][1][f"{EST}_ttft_relative"]
    with pytest.raises(mt.MatchError, match="c2: the estimator states one of TPOT and TTFT"):
        entries(pred=[(1.0, 1.0), (1.2, 1.2), (1.5, 2.0)], sw=sw)


def test_a_contract_whose_files_hold_fewer_points_than_its_provenance_is_refused(tmp_path):
    d = tmp_path / "contract"
    d.mkdir()
    (d / "points.csv").write_text("scenario,model,gpu,label,concurrency,meas_tpot_us,pred_tpot_us,meas_ttft_us,"
                                  "pred_ttft_us,grade,point_id,measured_date\n")
    for f in ("fidelity.jsonl", "not_scored.jsonl", "failed.jsonl"):
        (d / f).write_text("")
    (d / "facets.json").write_text("{}")
    (d / "provenance.json").write_text(json.dumps({"points": 5}))
    with pytest.raises(mt.MatchError, match="5 in provenance"):
        mt.read_contract(d, tmp_path / "splits.json")


def test_a_freeze_with_nothing_to_freeze_is_an_error_not_a_crash(tmp_path):
    with pytest.raises(mt.MatchError, match="nothing to freeze"):
        mt.freeze([{"unit": None, "records": []}], [], ledger_dir=tmp_path, out=tmp_path / "p", cache=tmp_path,
                  workers=1, errors_out=tmp_path / "e.json")
