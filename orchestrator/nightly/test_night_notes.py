"""The night's notes: warnings that never stop a publish (orchestrator/nightly/night_notes.py).

Run: python3 -m pytest orchestrator/nightly/test_night_notes.py
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ingest"))
import assess  # noqa: E402
import night_notes as nn  # noqa: E402


def _summary(points, refused, new=()):
    g5 = {"code": "blis_refused", "subject": "scenario"}
    other = {"code": "field_not_modelled", "subject": "x"}
    ns = [{"g5_reason": g5, "g5_reasons": [g5]} for _ in range(refused)]
    ns.append({"g5_reason": other, "g5_reasons": [other, g5]})     # classified by a more specific reason: not counted
    return {"coverage": {"points": points}, "not_scored": ns, "new_refusal_codes": list(new)}


def test_a_few_named_refusals_are_a_notice_not_a_warning():
    # the night of 2026-11-18: 14 of 20,364 points
    assert nn.notes(_summary(20364, 14)) == [("notice", "14 of 20364 points (0.07%) are named simulator refusals (G5 blis_refused).")]


def test_the_unclassified_share_warns_only_above_the_stated_limit():
    assert assess.UNCLASSIFIED_WARN_SHARE == 0.01
    below, above = _summary(1000, 10), _summary(1000, 11)
    assert [lv for lv, _ in nn.notes(below)] == ["notice"]            # 10 of 1000 is exactly 1 percent: not above
    assert [lv for lv, _ in nn.notes(above)] == ["warning"]


def test_a_new_refusal_code_is_a_warning_that_names_it():
    (level, text), = [n for n in nn.notes(_summary(20364, 0, new=["kv_cache_too_small"])) if "kv_cache_too_small" in n[1]]
    assert level == "warning" and "has not seen before" in text


def test_the_script_prints_annotations_writes_the_job_summary_and_never_fails(tmp_path):
    f = tmp_path / "s.json"
    f.write_text(json.dumps(_summary(1000, 50, new=["x_code"])))
    step = tmp_path / "step.md"
    run = lambda path: subprocess.run([sys.executable, str(HERE / "night_notes.py"), str(path)], capture_output=True, text=True,
                                      env={"GITHUB_STEP_SUMMARY": str(step), "PATH": "/usr/bin:/bin"})
    out = run(f)
    assert out.returncode == 0 and out.stdout.count("::warning::") == 2
    assert "Night notes" in step.read_text() and "x_code" in step.read_text()
    missing = run(tmp_path / "none.json")                               # an unreadable summary is a warning, not a stop
    assert missing.returncode == 0 and "::warning::night_notes could not read" in missing.stdout
