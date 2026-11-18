"""A night is not published when more than 5 percent of its points are faults (a named G5 is a result, not a fault)."""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import night_health as nh  # noqa: E402


def summary(points, failed=0, g5=0):
    return {"coverage": {"points": points, "graded": points - failed - g5, "not_scored": g5, "failed": failed},
            "failed": [{"point_id": f"{i:064x}", "faults": ["blis_refused:scenario"]} for i in range(failed)],
            "not_scored": [{"point_id": "x", "g5_reason": {"code": "not_in_catalog"}}] * g5}


def test_a_night_of_mostly_named_g5_points_is_published():
    assert nh.check(summary(665, failed=0, g5=287)) is None


def test_a_night_with_up_to_five_percent_faults_is_published_and_over_five_percent_is_not():
    assert nh.check(summary(200, failed=10)) is None
    why = nh.check(summary(200, failed=11))
    assert why and "11 of 200" in why and "blis_refused:scenario" in why


def test_the_command_exits_nonzero_on_a_bad_night_and_names_why(tmp_path):
    f = tmp_path / "s.json"
    f.write_text(json.dumps(summary(100, failed=20)))
    r = subprocess.run([sys.executable, str(HERE / "night_health.py"), str(f)], capture_output=True, text=True)
    assert r.returncode == 1 and "20 of 100" in r.stderr
    f.write_text(json.dumps(summary(100, failed=1)))
    assert subprocess.run([sys.executable, str(HERE / "night_health.py"), str(f)]).returncode == 0
    assert subprocess.run([sys.executable, str(HERE / "night_health.py"), str(f), "--limit", "0.001"]).returncode == 1


def test_a_summary_with_no_point_count_is_refused_not_passed(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        nh.check({"coverage": {}, "failed": []})
