"""Tests of the M3 baseline report (m3_baseline.py): the refusal list, the issue each reason cites, the guards, and
the committed report."""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ingest"))
import m3_baseline as mb  # noqa: E402

ROOT = HERE.parent.parent
BASE = ROOT / "docs" / "m3" / "baseline"
ISSUES = {"fields": {"sha256": "x", "issues": {"linear_backend": "o/r#1"}},
          "reasons": {"value_not_recorded:workload_category_not_stated": "o/r#2", "field_not_in_release": "o/r#3"},
          "refusals": [{"contains": "indexer_kv_dtype", "class": "indexer", "issue": "o/r#4"}]}


def pt(n, status, reasons, hardware="b200", error=None):
    return {"id": f"{n:064x}", "status": status, "grade": "G5" if status == "not_scored" else status,
            "hardware": hardware, "g5_reasons": reasons, "error": error}


def test_the_refusal_list_is_ordered_by_points_blocked_and_cites_issues():
    pts = [pt(1, "not_scored", [("field_not_modelled", "linear_backend")]),
           pt(2, "not_scored", [("value_not_recorded", "workload_category_not_stated"), ("field_not_modelled", "x")]),
           pt(3, "not_scored", [("value_not_recorded", "workload_category_not_stated"), ("field_not_in_release", "env.A")]),
           pt(4, "not_scored", [("value_not_recorded", "workload_category_not_stated")]),
           pt(5, "failed", [("blis_refused", "scenario")], error="indexer_kv_dtype='bf16' is refused"),
           pt(6, "not_scored", [("field_not_modelled", "linear_backend")], hardware="mi355x")]
    rows = mb.refused(pts, ISSUES)
    assert [(r["reason"], r["blocks"], r["alone"], r["issue"]) for r in rows] == [
        ("value_not_recorded:workload_category_not_stated", 3, 1, "o/r#2"),
        ("blis_refused:scenario: indexer", 1, 1, "o/r#4"),
        ("field_not_modelled:linear_backend", 1, 1, "o/r#1"),
        ("field_not_in_release:env.A", 1, 0, "o/r#3"),
        ("field_not_modelled:x", 1, 0, None)]


def test_an_sglang_release_is_read_from_an_official_image_only():
    assert [mb.sglang_release(i) for i in (
        "lmsysorg/sglang:v0.5.22-cu130", "lmsysorg/sglang-rocm:v0.5.12.post1-rocm720-mi35x-20260523",
        "lmsysorg/sglang:v0.5.12@sha256:" + "a" * 64, "lmsysorg/sglang:nightly-dev-cu13-20260605-7dc73766",
        "lmsysorg/sglang:dev-minimax-m31-flash", "rocm/sgl-dev:sglang-0.5.9-rocm720", None)] == \
        ["0.5.22", "0.5.12.post1", "0.5.12", None, None, None, None]


def _inputs():
    return dict(contract=ROOT / "docs" / "m2" / "preliminary-after" / "contract", splits=None,
                sglang=json.loads((BASE / "sglang-lane.json").read_text()),
                ported=json.loads((BASE / "ported-changes.json").read_text()),
                issues=json.loads((BASE / "issues.json").read_text()), sglang_release_="0.5.23")


def test_a_field_list_other_than_the_runs_is_refused():
    kw = _inputs()
    kw["issues"]["fields"]["sha256"] = "0" * 64
    with pytest.raises(mb.BaselineError, match="not the one the run was scored with"):
        mb.report(**kw)


def test_the_committed_report_is_what_the_tool_makes_of_the_committed_inputs():
    kw = _inputs()
    kw["contract"] = Path("docs/m2/preliminary-after/contract")
    import os
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        doc, per_point = mb.report(**kw)
    finally:
        os.chdir(cwd)
    assert json.loads((BASE / "baseline.json").read_text()) == json.loads(json.dumps(doc))
    assert (BASE / "baseline.md").read_text() == mb.markdown(doc)
    assert (BASE / "ceilings.jsonl").read_text() == mb.ceilings_jsonl(per_point)


def test_every_reason_in_the_committed_refusal_lists_cites_an_issue_or_says_it_is_data():
    doc = json.loads((BASE / "baseline.json").read_text())
    missing = [r["reason"] for lane in doc["lanes"].values() for r in lane["refused"] if not r["issue"]]
    assert missing == []


def test_each_substitution_kind_counts_the_scored_in_scope_points_that_carry_it():
    sub = lambda k, s: {"kind": k, "subject": s, "detail": "d"}  # noqa: E731
    pts = [{"status": "scored", "hardware": "b200", "substitutions": [sub("estimated", "a"), sub("estimated", "b")]},
           {"status": "scored", "hardware": "h200", "substitutions": [sub("estimated", "a"), sub("later_record", "x")]},
           {"status": "scored", "hardware": "mi355x", "substitutions": [sub("later_record", "x")]},
           {"status": "not_scored", "hardware": "b200", "substitutions": []}]
    assert mb.substitution_kinds(pts) == [{"kind": "estimated", "points": 2, "subjects": 2},
                                          {"kind": "later_record", "points": 1, "subjects": 1}]
