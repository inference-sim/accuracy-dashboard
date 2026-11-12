"""freeze_rows.py makes the units of rows the ledger does not hold, and the sixteen pinned rows are
placed by them and split by the same rule as every other point."""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "orchestrator" / "ingest"))
import contract as c  # noqa: E402
import freeze_rows as fr  # noqa: E402
import ledger as ldg  # noqa: E402
import split  # noqa: E402

PINNED = ROOT / "docs" / "m2" / "h200-v033"


def rows():
    return json.loads((PINNED / "rows.json").read_text())


def test_each_row_is_placed_in_the_unit_the_ledger_ingest_would_make_for_it(tmp_path):
    rs = rows()
    ids = fr.write_ledger(tmp_path, rs, "test")
    lg = ldg.load(tmp_path)
    dates = c.run_dates(rs)
    assert len(ids) == len(rs) == len(lg.units)
    for r in rs:
        p = lg.place(r, dates)
        assert p is not None and p.unit.unit_id == c.point_id(c.unit_identity(r, dates))
        assert p.unit.kept_record == str(r["id"])


def test_a_row_the_unit_list_does_not_hold_is_not_placed(tmp_path):
    rs = rows()
    fr.write_ledger(tmp_path, rs[1:], "test")
    assert ldg.load(tmp_path).place(rs[0], c.run_dates(rs)) is None


def test_two_rows_with_one_identity_are_refused(tmp_path):
    r = rows()[0]
    with pytest.raises(ValueError, match="one identity"):
        fr.write_ledger(tmp_path, [r, dict(r)], "test")


def test_the_committed_supplementary_ledger_holds_exactly_the_pinned_rows():
    lg = ldg.load(PINNED / "ledger")
    rs = rows()
    assert set(lg.by_record) == {str(r["id"]) for r in rs}
    dates = c.run_dates(rs)
    assert all(lg.place(r, dates) is not None for r in rs)
    assert {u for u in (PINNED / "units.txt").read_text().split()} == set(lg.units)


def test_the_pinned_rows_are_development_points_by_the_rule_every_point_follows():
    kinds = {split.kind_of(split.from_row(r), r["date"]) for r in rows()}
    assert kinds == {"validation"}      # a test or prospective row would have to stay withheld
    listed = json.loads((ROOT / "docs" / "m2" / "series-split.json").read_text())["series"]
    for r in rows():
        assert str(r["id"]) in listed[split.series_id(split.from_row(r))]["rows"]
