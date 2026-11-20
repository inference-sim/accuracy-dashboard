"""Tests of the slice report (slices.py, design COV-13): the role key, the minimum of role keys (not points) under which a
slice shows no accuracy, the laws the cuts obey, and the section the baseline report publishes. Offline: records are canned."""
import copy
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ingest"))
import m3_baseline as mb  # noqa: E402
import slices as sl  # noqa: E402


def rec(i, key, gpu="b200", grade="G4", ttft=10.0, **facets):
    """One graded point of the deployment `key` (its configuration hash); `i` is its concurrency."""
    return {
        "point_id": f"pt{i:04d}", "grade": grade, "substitutions": [],
        "build": {"commit": "c", "version": "0.1"},
        "identity": {"source": "inferencex", "model": "m", "hardware": gpu, "precision": "fp4", "framework": "vllm",
                     "benchmark_type": "single_turn", "configuration_hash": f"h{key}", "conc": i},
        "facets": {"framework": "vllm", "gpu": gpu, "model": "m", "precision": "fp4", "serving": "aggregated",
                   "parallelism": {"tp": 2, "dp": 1}, "workload": "1k1k", **facets},
        "figures": [{"metric": "ttft_mean_ms", "measured": 100.0, "predicted": 100.0 + ttft},
                    {"metric": "tpot_mean_ms", "measured": 10.0, "predicted": 11.0}],
    }


def spread(points, keys, **kw):
    return [rec(i, i % keys, **kw) for i in range(points)]


def with_keys(recs):
    return [{**r, "role_key": sl.role_key(r)} for r in recs]


SHOWN = [
    # points, role keys, is the accuracy shown
    (10, 1, False),
    (10, 2, False),
    (40, 9, False),
    (9, 9, False),
    (10, 10, True),
    (25, 10, True),
]


@pytest.mark.parametrize("points, keys, shown", SHOWN, ids=[f"{p}pts_{k}keys" for p, k, _ in SHOWN])
def test_a_figure_needs_ten_role_keys_not_ten_points(points, keys, shown):
    f = sl.figure(with_keys(spread(points, keys)), "ttft_mean_ms", 10)
    assert (f["mape"] != sl.TOO_FEW) is shown
    assert f["n"] == points and f["role_keys"] == keys
    if shown:
        assert f["mape"] == pytest.approx(sum(10.0 for _ in range(points)) / points)


def test_ten_points_from_two_role_keys_render_no_aggregate_but_stay_listed():
    row = sl.slice_by(with_keys(spread(10, 2)), "chip", 10)[0]
    assert (row["points"], row["role_keys"], row["shown"]) == (10, 2, False)
    assert row["ttft"]["mape"] == sl.TOO_FEW and row["tpot"]["mape"] == sl.TOO_FEW
    assert len(row["units"]) == 10 and row["units"] == sorted(row["units"])


def test_the_role_key_is_one_deployment_whatever_the_concurrency_or_date():
    a = rec(1, 0)
    b = copy.deepcopy(a)
    b["identity"].update(conc=64, measured_date="2026-10-01", benchmark_run=9)
    assert sl.role_key(a) == sl.role_key(b)
    for field, value in (("model", "n"), ("hardware", "h200"), ("precision", "fp8"), ("framework", "sglang"),
                         ("benchmark_type", "agentic_traces"), ("configuration_hash", "x"), ("source", "other")):
        c = copy.deepcopy(a)
        c["identity"][field] = value
        assert sl.role_key(c) != sl.role_key(a), field


def test_a_legacy_identity_with_a_recipe_stands_for_the_same_deployment():
    a = rec(1, 0)
    legacy = copy.deepcopy(a)
    legacy["identity"].pop("configuration_hash")
    legacy["identity"]["recipe"] = "h0"
    assert sl.role_key(legacy) == sl.role_key(a)


def test_a_ledger_role_key_is_used_where_the_record_carries_one():
    assert sl.role_key({**rec(1, 0), "role_key": "ledger-key"}) == "ledger-key"


def test_slices_are_cut_by_the_attribute_and_each_states_its_own_counts():
    recs = with_keys(spread(10, 2, gpu="h200") + [rec(100 + i, 100 + i, gpu="b200") for i in range(12)])
    rows = {r["value"]: r for r in sl.slice_by(recs, "chip", 10, [{"hardware": "h200"}, {"hardware": "b200"}])}
    assert (rows["h200"]["points"], rows["h200"]["role_keys"], rows["h200"]["shown"]) == (10, 2, False)
    assert (rows["b200"]["points"], rows["b200"]["role_keys"], rows["b200"]["shown"]) == (12, 12, True)
    assert rows["h200"]["coverage"] == {"scored": 10, "total": 11} and rows["b200"]["coverage"] == {"scored": 12, "total": 13}
    assert [r["value"] for r in sl.slice_by(recs, "chip", 10)] == ["b200", "h200"]


def test_every_attribute_cuts_the_points_without_losing_one():
    recs = with_keys(spread(30, 3))
    for by in sl.ATTRS:
        rows = sl.slice_by(recs, by, 10)
        total = sum(r["points"] for r in rows)
        assert total >= len(recs), by
        if by != "substitution":
            assert total == len(recs), by
        for r in rows:
            assert r["shown"] == (r["role_keys"] >= 10)


def test_a_point_with_several_substitutions_is_in_each_slice_and_one_with_none_in_none():
    a = rec(1, 0)
    a["substitutions"] = [{"kind": "x"}, {"kind": "y"}, {"kind": "x"}]
    rows = sl.slice_by(with_keys([a, rec(2, 1)]), "substitution", 10)
    assert sorted((r["value"], r["points"]) for r in rows) == [("none", 1), ("x", 1), ("y", 1)]


def test_an_attribute_the_record_does_not_hold_is_refused_and_named():
    with pytest.raises(sl.SliceError, match="node_count is not recorded"):
        sl.slice_by([], "node_count", 10)
    with pytest.raises(sl.SliceError, match="cannot slice by 'nonsense'"):
        sl.slice_by([], "nonsense", 10)


def _contract(tmp_path, recs, not_scored=()):
    (tmp_path / "pointrecords.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
    (tmp_path / "not_scored.jsonl").write_text("".join(json.dumps(r) + "\n" for r in not_scored))
    return tmp_path


def test_the_document_counts_only_graded_points_and_validates(tmp_path):
    recs = spread(10, 2) + [rec(50, 5, grade="G5")]
    doc = sl.validate(sl.build(_contract(tmp_path, recs), by=("chip", "grade")))
    assert (doc["points"], doc["role_keys"], doc["min_role_keys"]) == (10, 2, 10)
    assert [r["value"] for r in doc["slices"]["grade"]] == ["G4"]
    assert doc["slices"]["chip"][0]["ttft"]["mape"] == sl.TOO_FEW


def test_validation_refuses_a_number_shown_under_the_minimum_and_a_figure_withheld_above_it(tmp_path):
    doc = sl.build(_contract(tmp_path, spread(10, 2)), by=("chip",))
    bad = copy.deepcopy(doc)
    bad["slices"]["chip"][0]["ttft"]["mape"] = 12.0
    with pytest.raises(sl.SliceError, match="ttft is 12.0"):
        sl.validate(bad)
    bad = copy.deepcopy(doc)
    bad["slices"]["chip"][0]["shown"] = True
    with pytest.raises(sl.SliceError, match="shown is True"):
        sl.validate(bad)
    ok = sl.build(_contract(tmp_path, spread(10, 10)), by=("chip",))
    bad = copy.deepcopy(ok)
    bad["slices"]["chip"][0]["tpot"]["mape"] = sl.TOO_FEW
    with pytest.raises(sl.SliceError, match="tpot is 'too few points'"):
        sl.validate(bad)
    bad = copy.deepcopy(doc)
    bad["slices"]["chip"][0]["units"].pop()
    with pytest.raises(sl.SliceError, match="units listed"):
        sl.validate(bad)
    with pytest.raises(sl.SliceError, match="format"):
        sl.validate({**doc, "format": "slices-0"})


def test_the_section_states_the_rule_gives_the_count_in_place_of_the_figure_and_lists_the_points(tmp_path):
    doc = sl.build(_contract(tmp_path, spread(10, 2) + [rec(100 + i, 100 + i, gpu="h200") for i in range(10)]),
                   by=("chip",))
    text = "\n".join(sl.markdown(doc))
    assert "fewer than 10 role keys shows no accuracy" in text
    assert "| `b200` | 10 | 2 | 10 of 10 | too few points (2 role keys) | too few points (2 role keys) |" in text
    assert "| `h200` | 10 | 10 | 10 of 10 | 10.0% | 10.0% |" in text
    assert "Slices under 10 role keys list their points:" in text and "`pt0000`" in text
    assert "node_count" in text


def _report(**extra):
    import os
    import test_m3_baseline as tb
    kw = tb._inputs()
    kw["contract"] = Path("docs/m2/preliminary-after/contract")
    cwd = os.getcwd()
    os.chdir(tb.ROOT)
    try:
        return mb.report(**kw, **extra)[0]
    finally:
        os.chdir(cwd)


def test_the_report_carries_the_slices_only_when_given_and_refuses_one_that_breaks_the_rule(tmp_path):
    doc = sl.build(_contract(tmp_path, spread(10, 2)), by=("chip",))
    plain = _report()
    assert "slices" not in plain and "Accuracy by slice" not in mb.markdown(plain)
    with_s = _report(slices=doc)
    assert with_s["slices"] == doc and {k: v for k, v in with_s.items() if k != "slices"} == plain
    assert mb.markdown(with_s).startswith(mb.markdown(plain).rstrip("\n"))
    assert "## Accuracy by slice" in mb.markdown(with_s)
    bad = copy.deepcopy(doc)
    bad["slices"]["chip"][0]["ttft"]["mape"] = 12.0
    with pytest.raises(mb.BaselineError, match="slices document is not valid"):
        _report(slices=bad)


def test_the_command_writes_a_valid_document_and_refuses_a_missing_contract(tmp_path):
    out = tmp_path / "s.json"
    assert sl.main(["--contract", str(_contract(tmp_path, spread(12, 12))), "--by", "chip", "--out", str(out)]) == 0
    assert sl.validate(json.loads(out.read_text()))["slices"].keys() == {"chip"}
    assert sl.main(["--contract", str(tmp_path / "none"), "--out", str(out)]) == 2
    assert sl.main(["--contract", str(tmp_path), "--by", "router", "--out", str(out)]) == 2
