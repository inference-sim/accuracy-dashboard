"""The residual analysis reads train points only."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import compare as c  # noqa: E402
import residuals as rs  # noqa: E402


def pt(kind, model="m", conc=4, ratio=1.2, **kw):
    return {"status": "scored", "kind": kind, "series": f"s-{model}-{kind}", "model": model, "hardware": "b200", "precision": "fp8",
            "concurrency": conc, "serving": "aggregated", "spec": "none", "isl": 8192,
            "meas_ttft_us": 100.0, "pred_ttft_us": 100.0 * ratio, "meas_tpot_us": 10.0, "pred_tpot_us": 10.0 * ratio, **kw}


def test_the_signed_error_is_prediction_over_measurement_minus_one_in_percent():
    assert abs(rs.signed(130, 100) - 30.0) < 1e-9 and abs(rs.signed(70, 100) + 30.0) < 1e-9


def test_the_bands_and_regimes():
    assert [rs.band(x) for x in (1, 2, 3, 8, 9, 32, 33, 128, 129, 4096)] == ["1-2", "1-2", "3-8", "3-8", "9-32", "9-32", "33-128", "33-128", ">128", ">128"]
    assert rs.regime(pt("train", conc=4)) == "shallow queue, long prompt"
    assert rs.regime({**pt("train", conc=64), "isl": 1024}) == "deep queue, short prompt"


def test_only_train_points_are_read():
    train = [pt("train", ratio=1.3) for _ in range(6)]
    other = [pt(k, ratio=5.0) for k in ("validation", "test", "prospective") for _ in range(6)] + [pt(None, ratio=5.0) for _ in range(6)]
    groups = rs.analyse(train + other)
    assert groups and all(abs(g["median_signed_error_pct"] - 30.0) < 1e-9 for g in groups)
    assert all(g["n"] == 6 for g in groups)


def test_a_group_needs_five_points_and_the_top_is_by_size_of_the_median():
    pts = [pt("train", "big", ratio=1.5) for _ in range(5)] + [pt("train", "small", ratio=1.05) for _ in range(5)] \
        + [pt("train", "few", ratio=9.0) for _ in range(4)]
    g = rs.analyse(pts)
    assert "few" not in {x["value"] for x in g if x["facet"] == "model"}
    top = rs.top_biases(g, 2)
    assert top[0]["value"] != "small" and abs(top[0]["median_signed_error_pct"]) >= abs(top[1]["median_signed_error_pct"])
    assert rs.top_biases(g, 1)[0]["median_signed_error_pct"] > 40


def test_the_report_names_the_train_split_and_the_hypotheses():
    g = rs.analyse([pt("train", ratio=1.4) for _ in range(6)])
    md = rs.markdown(g, rs.top_biases(g, 30), 6, {("model", "m", "ttft"): "a hypothesis"})
    assert "train split" in md and "not an evaluation" in md and "a hypothesis" in md


def test_the_refusal_text_is_read_from_the_scorers_logs(tmp_path):
    logs = tmp_path / "w1" / "logs"
    logs.mkdir(parents=True)
    (logs / ("a" * 64 + ".err")).write_text('time="2026-11-11T00:00:00Z" level=fatal msg="scenario \\"p-0123456789abcdef.yaml\\": the kernel will not price \\"all\\""\n')
    (logs / ("b" * 64 + ".err")).write_text("")
    got = c.refusals_from_logs(tmp_path)
    assert got == {"a" * 64: 'the kernel will not price "all"'}
    assert c.refusal_classes(list(got.values()) * 2 + [None]) == [('the kernel will not price "all"', 2)]
