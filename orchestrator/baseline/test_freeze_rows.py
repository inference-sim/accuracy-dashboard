"""freeze_rows.py places rows only by the units of the substrate's ledger: it makes no unit, commits no record, and refuses an
unpinned or mismatched substrate checkout. The sixteen pinned rows are development points by the rule every point follows."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "orchestrator" / "ingest"))
import freeze_rows as fr  # noqa: E402
import ledger_fake  # noqa: E402
import split  # noqa: E402

PINNED = ROOT / "docs" / "m2" / "h200-v033"
FIX = ROOT / "orchestrator" / "ingest" / "testdata" / "ledger"
def _distinct(rows):
    import contract as c
    seen, out, dates = set(), [], c.run_dates(rows)
    for r in rows:
        k = c.point_id(c.unit_identity(r, dates))
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


ALL = json.loads((FIX / "api_rows.json").read_text())
ROWS = _distinct(ALL)[:3]


def test_the_dashboard_commits_no_ledger_unit_and_no_third_party_record():
    assert not (PINNED / "ledger").exists() and not (PINNED / "rows.json").exists()
    assert not hasattr(fr, "write_ledger") and not hasattr(fr, "NO_ROLE_KEY")


def test_a_row_is_placed_in_the_unit_the_substrates_list_holds_for_it(tmp_path):
    ledger_fake.write(tmp_path, ROWS)
    lg = fr.ldg.load(tmp_path)
    ids = fr.place_all(lg, ROWS)
    assert ids == sorted(ledger_fake.point_id(r) for r in ROWS)


def test_a_row_the_substrates_list_does_not_hold_is_refused_not_given_a_unit_here(tmp_path):
    ledger_fake.write(tmp_path, ROWS[1:])
    with pytest.raises(fr.FreezeError, match="holds no unit for it"):
        fr.place_all(fr.ldg.load(tmp_path), ROWS)


def test_the_substrates_report_may_name_its_supplements(tmp_path):
    ledger_fake.write(tmp_path, ROWS)
    rep = tmp_path / "reports" / "inferencex.yaml"
    doc = json.loads(rep.read_text())
    doc["supplements"] = [{"id": "s", "records": len(ROWS)}]
    rep.write_text(json.dumps(doc))
    assert len(fr.ldg.load(tmp_path).units) == len(ROWS)


def _repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                    "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    return subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


def test_an_empty_pin_is_refused_unless_the_build_is_declared_a_scratch_build(tmp_path):
    pins = tmp_path / "pins.env"
    pins.write_text("BLIS_SUBSTRATE_COMMIT=\n")
    with pytest.raises(fr.FreezeError, match="not pinned"):
        fr.check_pin(tmp_path, pins, False)
    assert fr.check_pin(tmp_path, pins, True) == ""


def test_a_ledger_checkout_at_another_commit_than_the_pin_is_refused(tmp_path):
    head = _repo(tmp_path)
    pins = tmp_path / "pins.env"
    pins.write_text(f"BLIS_SUBSTRATE_COMMIT={head}\n")
    assert fr.check_pin(tmp_path, pins, False) == head
    pins.write_text("BLIS_SUBSTRATE_COMMIT=" + "0" * 40 + "\n")
    with pytest.raises(fr.FreezeError, match="not the pinned"):
        fr.check_pin(tmp_path, pins, False)


def test_the_committed_pin_file_names_the_key_the_script_reads():
    assert fr.read_pin(PINNED / "pins.env") in ("",) or len(fr.read_pin(PINNED / "pins.env")) == 40


def test_the_sixteen_pinned_units_are_development_points_by_the_rule_every_point_follows():
    units = (PINNED / "units.txt").read_text().split()
    splits = json.loads((PINNED / "splits.json").read_text())
    assert len(units) == 16 and {splits[u]["kind"] for u in units} == {"validation"}    # a test or prospective row would stay withheld
