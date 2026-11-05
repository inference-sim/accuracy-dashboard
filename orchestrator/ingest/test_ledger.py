"""The point identity is the ledger's unit identity (design §10.2), checked against a unit list
that blis-substrate's own ingest tool generated (testdata/ledger, build_fixture.py).

Run: python3 -m pytest orchestrator/ingest/test_ledger.py
"""
import gzip
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import contract as c  # noqa: E402
import ledger as ldg  # noqa: E402
import pull as pl  # noqa: E402

FIX = HERE / "testdata" / "ledger"
ROWS = json.loads((FIX / "api_rows.json").read_text())
BY_ID = {r["id"]: r for r in ROWS}


def _units():
    return [json.loads(x) for x in gzip.decompress((FIX / "units" / "inferencex.jsonl.gz").read_bytes()).splitlines()]


def test_every_records_identity_hashes_to_the_unit_id_the_ledger_gives_it():
    dates = c.run_dates(ROWS)
    n = 0
    for u in _units():
        for m in u["measurements"]:
            for rid in [m["record"]] + m["duplicates"]:
                assert c.point_id(c.unit_identity(BY_ID[rid], dates)) == u["unit_id"]
                n += 1
            for x in m["merged"]:
                assert c.point_id(c.unit_identity(BY_ID[x["record"]], dates)) == x["unit_id"]
                n += 1
    assert n == 8   # every record but the one left out


def test_the_identity_is_the_eleven_fields_of_the_unit_list():
    u = _units()[0]
    assert tuple(sorted(u["identity"])) == tuple(sorted(c.IDENTITY_FIELDS))
    assert c.point_id(u["identity"]) == u["unit_id"]


def test_the_image_digest_is_not_part_of_the_configuration_hash():
    a, b = BY_ID["101"], BY_ID["102"]
    assert "@sha256:" in b["image"] and "@sha256:" not in a["image"]
    assert c.configuration_hash(a) == c.configuration_hash(b)


def test_the_configuration_hash_keeps_every_key_and_json_types():
    cfg = c.configuration({"image": None, "isl": 1024, "disagg": False})
    assert list(cfg) == list(c.CONFIGURATION_FIELDS) and len(cfg) == 17
    assert cfg["image"] is None and cfg["osl"] is None and cfg["disagg"] is False
    with pytest.raises(ValueError, match="float"):
        c.configuration({"isl": 1024.0})
    # 1 and True are different JSON values, so different configurations.
    assert c.configuration_hash({"decode_tp": 1}) != c.configuration_hash({"decode_tp": True})


def test_the_benchmark_run_drops_the_attempt_and_is_null_without_a_run_id():
    assert c.benchmark_run("https://github.com/o/r/actions/runs/123/attempts/4") == 123
    assert c.benchmark_run("https://github.com/o/r/actions/runs/123") == 123
    assert c.benchmark_run(None) is None
    assert c.benchmark_run("https://example.com/no-run") is None


def test_the_measured_date_is_the_earliest_date_of_the_benchmark_run():
    dates = c.run_dates(ROWS)
    late = BY_ID["104"]
    assert late["date"] == "2026-06-03"
    assert c.unit_identity(late, dates)["measured_date"] == "2026-06-02"
    no_run = c.unit_identity(BY_ID["107"], dates)
    assert no_run["benchmark_run"] is None and no_run["measured_date"] == "2026-06-06"
    # The earliest date wins whatever order the records come in.
    assert c.run_dates(list(reversed(ROWS)))[9002] == "2026-06-02"
    with pytest.raises(ValueError, match="no measured date"):
        c.unit_identity(late, {})


def test_records_the_ledger_joins_are_one_point():
    lg = ldg.load(FIX)
    placed = pl.place(ROWS, lg)
    by = {p.point_id: p for p in placed.points}
    assert len(by) == 5
    dup = next(p for p in placed.points if "102" in p.records)
    assert dup.records == ["101", "102"] and len(dup.measurements) == 1
    joined = next(p for p in placed.points if "103" in p.records)
    assert joined.records == ["103", "104"] and len(joined.measurements) == 2
    merged = next(p for p in placed.points if "106" in p.records)
    assert merged.records == ["105", "106"] and merged.row["id"] == "105"


def test_records_the_ledger_leaves_out_are_listed_with_the_reason():
    lg = ldg.load(FIX)
    newer = {**BY_ID["109"], "id": "999", "conc": 64}
    placed = pl.place(ROWS + [newer], lg)
    assert {(x["record"], x["reason"]) for x in placed.unlisted} == {
        ("108", "left_out:error_reported"), ("999", "not_in_source_revision")}


def test_a_row_that_differs_from_the_pinned_source_is_refused():
    lg = ldg.load(FIX)
    changed = [dict(r) for r in ROWS]
    next(r for r in changed if r["id"] == "109")["decode_tp"] = 2
    with pytest.raises(ldg.LedgerError, match="row 109"):
        pl.place(changed, lg)


def test_the_unit_loader_refuses_unknown_keys_and_a_wrong_unit_id(tmp_path):
    u = _units()[0]
    for bad in ({**u, "role": "fit"}, {**u, "unit_id": "0" * 64}):
        p = tmp_path / "u.jsonl.gz"
        p.write_bytes(gzip.compress((json.dumps(bad) + "\n").encode()))
        with pytest.raises(ldg.LedgerError):
            ldg.read_units(p)


def test_a_unit_set_is_a_published_list_or_a_list_of_ids(tmp_path):
    ids = sorted(u["unit_id"] for u in _units())[:2]
    pub = tmp_path / "anchor.yaml"
    pub.write_text("kind: PublishedUnits\nrole: anchor\npartition_version: 1\nseed_sha256: ''\nunits:\n"
                   + "".join(f"  - {i}\n" for i in ids))
    assert ldg.read_unit_set(pub) == set(ids)
    plain = tmp_path / "units.txt"
    plain.write_text("# a unit set\n" + "\n".join(ids) + "\n")
    assert ldg.read_unit_set(plain) == set(ids)
    plain.write_text("row:1\n")
    with pytest.raises(ldg.LedgerError, match="not a unit_id"):
        ldg.read_unit_set(plain)
