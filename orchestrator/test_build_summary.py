"""Unit tests for the orchestrator's arithmetic -- the glue, not the science (RFC A4/A6).

Run: python3 -m pytest orchestrator/test_build_summary.py  (or: python3 orchestrator/test_build_summary.py)
"""
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import build_summary as bs  # noqa: E402


def test_point_mape_matches_metricscore_formula():
    # (pred/meas - 1)*100
    assert math.isclose(bs.point_mape(980.0, 821.0), (980 / 821 - 1) * 100)
    assert math.isclose(bs.point_mape(149.0, 160.0), (149 / 160 - 1) * 100)


def test_point_mape_guards_nonpositive():
    assert bs.point_mape(100.0, 0.0) is None
    assert bs.point_mape(0.0, 100.0) is None
    assert bs.point_mape(-1.0, 100.0) is None


def test_shape_reanchors_both_sides_and_excludes_anchor():
    pts = [
        {"concurrency": 1, "pred_tpot_us": 100.0, "meas_tpot_us": 100.0},
        {"concurrency": 4, "pred_tpot_us": 220.0, "meas_tpot_us": 200.0},
        {"concurrency": 16, "pred_tpot_us": 400.0, "meas_tpot_us": 400.0},
    ]
    sh = bs.sweep_shape(pts, "tpot")
    assert sh[1] is None  # anchor excluded
    # c=4: pred_rel=2.2, meas_rel=2.0 -> (2.2/2.0 - 1)*100 = 10
    assert math.isclose(sh[4], 10.0)
    # c=16: pred_rel=4.0, meas_rel=4.0 -> 0
    assert math.isclose(sh[16], 0.0, abs_tol=1e-9)


def test_shape_none_when_fewer_than_three_points():
    pts = [
        {"concurrency": 1, "pred_tpot_us": 100.0, "meas_tpot_us": 100.0},
        {"concurrency": 4, "pred_tpot_us": 220.0, "meas_tpot_us": 200.0},
    ]
    assert bs.sweep_shape(pts, "tpot") == {}


def test_mean_abs_uses_absolute_values():
    m, n = bs.mean_abs([-10.0, 10.0, None, -20.0])
    assert n == 3
    assert math.isclose(m, (10 + 10 + 20) / 3)


def test_mean_abs_all_none():
    assert bs.mean_abs([None, None]) == (None, 0)


def test_tier_map_covers_signedprobe_strings():
    assert bs.TIER_MAP["ALL (approximate)"] == "all"
    assert bs.TIER_MAP["MEASURED-OR-RESOLVED"] == "measured_or_resolved"
    assert bs.TIER_MAP["STRICT"] == "measured_or_resolved"


def test_header_contract_rejects_renamed_columns():
    bad = ",".join(["scenario", "model", "gpu", "label", "concurrency",
                    "meas_tpot_us", "pred_tpot_us", "meas_ttft_us", "pred_ttft_us", "tier"])  # renamed last col
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as fh:
        fh.write(bad + "\n")
        fh.write("s.yaml,m,g,l,1,1,1,1,1,ALL (approximate)\n")
        path = fh.name
    try:
        raised = False
        try:
            bs.read_signedprobe_csv(path)
        except bs.ColumnContractError as e:
            raised = True
            assert "columns changed" in str(e)
        assert raised, "expected ColumnContractError on renamed header"
    finally:
        os.unlink(path)


def test_header_contract_rejects_empty_csv():
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as fh:
        path = fh.name
    try:
        raised = False
        try:
            bs.read_signedprobe_csv(path)
        except bs.ColumnContractError:
            raised = True
        assert raised
    finally:
        os.unlink(path)


def test_unscorable_rows_are_held_out_of_scoring():
    # signedprobe emits mtp points with tier UNSCORABLE; they must be returned separately and
    # never scored into the metrics (RFC §4.4 — not_scored:no_acceptance_rate).
    header = ",".join(bs.EXPECTED_HEADER)
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as fh:
        fh.write(header + "\n")
        fh.write("ok.yaml,m,b200,1k1k,1,7000,8000,160000,150000,ALL (approximate)\n")
        fh.write("mtp.yaml,m,b200,1k1k,1,7000,8000,160000,150000,UNSCORABLE\n")
        path = fh.name
    try:
        rows, unscorable = bs.read_signedprobe_csv(path)
        assert len(rows) == 1 and rows[0]["scenario"] == "ok.yaml"
        assert len(unscorable) == 1 and unscorable[0]["scenario"] == "mtp.yaml"
        assert rows[0]["tier"] == "all"
    finally:
        os.unlink(path)


def test_self_consistency_catches_tampering():
    flat = [
        {"tier": "all", "mape_ttft": 10.0, "mape_tpot": 5.0, "shape_ttft": 2.0, "shape_tpot": 1.0},
        {"tier": "all", "mape_ttft": 20.0, "mape_tpot": 15.0, "shape_ttft": 4.0, "shape_tpot": 3.0},
    ]
    totals = bs.metric_block_pair(flat)
    bs.assert_self_consistent(flat, totals)  # should pass
    totals["all"]["mape"]["tpot"] = 999.0  # tamper
    raised = False
    try:
        bs.assert_self_consistent(flat, totals)
    except AssertionError:
        raised = True
    assert raised


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
