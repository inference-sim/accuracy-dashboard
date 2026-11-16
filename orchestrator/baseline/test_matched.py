"""Tests of the matched comparison (matched.py), on synthetic sweeps, dump rows and contracts written here."""
import json
import sys
import zipfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ingest"))
import matched as mt  # noqa: E402

EST = "other"


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


def entries(pred=None, kind="train", est_missing=False, sw=None):
    """One sweep's entries, BLIS predicting `pred` (relatives) or nothing."""
    sw = sw or sweep(est=((1.0, 1.0), (1.3, 1.1), None) if est_missing else ((1.0, 1.0), (1.3, 1.1), (1.4, 2.4)))
    matched = [{"sweep": f"{sw['topology_id']}|1k1k", "concurrency": p["concurrency"], "unit": f"u{i}", "records": ["x"]}
               for i, p in enumerate(sw["points"])]
    contract = {}
    for i, p in enumerate(sw["points"]):
        if pred and pred[i] is not None:
            contract[f"u{i}"] = {"status": "scored", "grade": "G4", "meas_tpot_us": 1000 * p["measured_tpot_relative"],
                                 "pred_tpot_us": 1000 * pred[i][0], "meas_ttft_us": 1000 * p["measured_ttft_relative"],
                                 "pred_ttft_us": 1000 * pred[i][1]}
        else:
            contract[f"u{i}"] = {"status": "not_scored", "grade": "G5", "reason": "field_not_modelled"}
    splits = {f"u{i}": {"kind": kind} for i in range(3)}
    return mt.entries_for({"sweeps": [sw]}, matched, contract, splits, EST, evaluate_test=False)


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
    mt.log_evaluation(log, "c" * 40, "label", entries(pred=[(1.0, 1.0), (1.2, 1.2), None], kind="test"))
    rows = [x for x in log.read_text().splitlines() if x.startswith("| 2")]
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
