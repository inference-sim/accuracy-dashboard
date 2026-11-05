"""The headline over G1 to G4, each grade's share and accuracy, and a count beside every figure
(COV-11), and coverage by engine, release, chip and grade (COV-7).

Run: python3 -m pytest orchestrator/ingest/test_headline.py
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import headline as hl  # noqa: E402


def _pt(grade, err=10.0, **kw):
    p = {"grade": grade, "framework": "vllm", "hardware": "h200", "release": "0.32.0"}
    if grade != "G5":
        p.update(meas_ttft_us=100.0, pred_ttft_us=100.0 + err, meas_tpot_us=10.0, pred_tpot_us=10.0 + err / 10)
    p.update(kw)
    return p


def test_the_headline_covers_g1_to_g4_and_each_grade_has_its_share_and_accuracy():
    pts = [_pt("G1", 10)] * 10 + [_pt("G4", 30)] * 30 + [_pt("G5")] * 5
    h = hl.headline(pts)
    assert h["graded"] == 40 and h["not_scored"] == 5 and h["points"] == 45
    assert h["headline"]["ttft"] == {"mape": pytest.approx(25.0), "n": 40}
    assert h["grades"]["G1"]["share"] == 0.25 and h["grades"]["G4"]["share"] == 0.75
    assert h["grades"]["G1"]["ttft"]["mape"] == pytest.approx(10.0)


def test_a_figure_under_the_minimum_is_too_few_points_not_a_number():
    h = hl.headline([_pt("G1")] * 3 + [_pt("G2")] * 12)
    assert h["grades"]["G1"]["ttft"] == {"mape": hl.TOO_FEW, "n": 3}
    assert isinstance(h["grades"]["G2"]["ttft"]["mape"], float)
    assert hl.check(h) == []
    h["grades"]["G1"]["ttft"]["mape"] = 1.0
    assert hl.check(h) == ["grades.G1.ttft: a figure over 3 points, under the minimum 10"]


def test_coverage_splits_by_engine_release_chip_and_grade():
    pts = [_pt("G2")] * 3 + [_pt("G5", framework="sglang", release=None, hardware="b200")] * 2
    c = hl.coverage(pts, left_out_records=7)
    assert c["graded"] == 3 and c["points"] == 5 and c["left_out_records"] == 7
    assert c["by_engine"]["sglang"]["graded"] == 0 and c["by_engine"]["vllm"]["grades"]["G2"] == 3
    assert "sglang nightly or custom" in c["by_engine_release"]
    assert c["by_grade"] == {"G1": 0, "G2": 3, "G3": 0, "G4": 0, "G5": 2}


def test_an_unknown_grade_is_refused():
    with pytest.raises(ValueError):
        hl.headline([_pt("G6")])
