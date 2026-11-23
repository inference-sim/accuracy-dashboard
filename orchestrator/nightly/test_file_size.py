"""A file near GitHub's 100 MB limit stops a publish; the summary is written compact; the committed data is under the limit."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import build_summary_v2 as b2  # noqa: E402
import file_size as fs  # noqa: E402

REPO = HERE.parent.parent


def test_a_file_over_the_limit_is_named_and_one_under_it_is_not(tmp_path):
    (tmp_path / "ok.json").write_bytes(b"x" * 1024)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "big.json").write_bytes(b"x" * (3 * fs.MB))
    assert fs.oversize([tmp_path], limit_mb=4) == []
    assert [(Path(p).name, round(mb)) for p, mb in fs.oversize([tmp_path], limit_mb=2)] == [("big.json", 3)]
    assert fs.main([str(tmp_path), "--limit-mb", "2"]) == 1 and fs.main([str(tmp_path), "--limit-mb", "4"]) == 0
    assert fs.main([str(tmp_path / "missing")]) == 0


def test_the_published_summary_is_compact_and_the_same_document():
    doc = {"schema_version": 3, "matrix": [{"rows": [{"a": 1, "b": [1, 2], "c": "·"}]}]}
    text = b2.dumps(doc)
    assert text.endswith("\n") and "\n" not in text[:-1] and ": " not in text and ", " not in text
    assert json.loads(text) == doc


def test_nothing_committed_is_near_the_limit():
    assert fs.oversize([REPO / "data", REPO / "state"]) == []
