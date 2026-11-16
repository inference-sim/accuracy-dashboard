"""Tests of the held-out check (published_test.py): a published test figure needs the logged evaluation that made it."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import published_test as pt  # noqa: E402

ROW = "| 2026-11-16 | " + "a" * 40 + " | v0.17.0 | BLIS v0.17.0 | test | 155 | 71 |"
ROW2 = "| 2026-11-17 | " + "a" * 40 + " | v0.17.0 | BLIS v0.17.0 | test | 155 | 71 |"


def tree(tmp: Path, log_rows=(), report=None, notes=()) -> Path:
    (tmp / "m2").mkdir(parents=True)
    (tmp / "m2" / "evaluation-log.md").write_text("# Evaluation log\n\n" + "".join(n + "\n" for n in notes) + "\n"
                                                  + pt.HEADER + "\n|---|---|---|---|---|---|---|\n"
                                                  + "".join(r + "\n" for r in log_rows))
    if report is not None:
        (tmp / "m3").mkdir()
        (tmp / "m3" / "r.json").write_text(json.dumps(report))
    return tmp


def run(tmp):
    return pt.problems(tmp, tmp / "m2" / "evaluation-log.md")


def test_test_figures_with_their_logged_evaluation_pass(tmp_path):
    assert run(tree(tmp_path, [ROW], {"test_evaluated": True, "evaluation": [ROW]})) == []


def test_test_figures_whose_evaluation_the_log_does_not_hold_fail(tmp_path):
    found = run(tree(tmp_path, [], {"test_evaluated": True, "evaluation": [ROW]}))
    assert len(found) == 1 and "which the log does not hold" in found[0]


def test_test_figures_that_name_no_evaluation_fail(tmp_path):
    found = run(tree(tmp_path, [], {"development_split": {"test_evaluated": True}}))
    assert found == ["m3/r.json holds test figures and names no evaluation-log row"]


def test_a_malformed_log_row_fails(tmp_path):
    A = "a" * 40
    for bad in ("| 2026-11-16 | abc | v0.17.0 | e | test | 1 | 1 |", "| yesterday | " + A + " | v0.17.0 | e | test | 1 | 1 |",
                "| 2026-11-16 | " + A + " | v0.17.0 | e | train | 1 | 1 |", "a note",
                "| 2026-11-16 | " + A + " | v0.17.0 |  | test | 1 | 1 |",
                "| 2026-11-16 | " + A + " |  | e | test | 1 | 1 |", "| 2026-11-16 | " + A + " | latest | e | test | 1 | 1 |",
                "| 2026-11-16 | " + A + " | e | test | 1 | 1 |"):
        import hashlib
        found = run(tree(tmp_path / hashlib.sha256(bad.encode()).hexdigest()[:12], [bad]))
        assert any("not a row" in f for f in found), bad


def test_an_unlogged_report_that_shows_held_out_errors_fails(tmp_path):
    rep = {"test_evaluated": False, "splits": {"test": {"points": 4, "withheld": 3}, "unknown": {"points": 2, "withheld": 2}}}
    found = run(tree(tmp_path, [], rep))
    assert len(found) == 1 and "1 test points without a logged evaluation" in found[0]


def test_a_logged_evaluation_that_no_committed_report_names_fails(tmp_path):
    found = run(tree(tmp_path, [ROW]))
    assert found == [f"the log row {ROW!r} is named by no committed report"]


def test_a_second_test_evaluation_of_a_release_fails_unless_the_log_says_why():
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        found = run(tree(Path(t), [ROW, ROW2], {"test_evaluated": True, "evaluation": [ROW, ROW2]}))
        assert len(found) == 1 and "2 test evaluations of v0.17.0" in found[0]
    with tempfile.TemporaryDirectory() as t:
        note = "- Repeated: v0.17.0, 2 test evaluations: run twice while the tool was fixed"
        assert run(tree(Path(t), [ROW, ROW2], {"test_evaluated": True, "evaluation": [ROW, ROW2]}, [note])) == []
    with tempfile.TemporaryDirectory() as t:
        note = "- Repeated: v0.17.0, 3 test evaluations: wrong count"
        assert len(run(tree(Path(t), [ROW, ROW2], {"test_evaluated": True, "evaluation": [ROW, ROW2]}, [note]))) == 1
