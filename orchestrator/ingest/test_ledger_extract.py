"""Tests of the ledger extract (ledger_extract.py): the dump's rows and logs the ledger's units need, in a compact file
whose bytes depend only on its content, checked against its pin and against the ledger before the night reads it."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger as ldg  # noqa: E402
import ledger_extract as lx  # noqa: E402
import ledger_fake  # noqa: E402


def _row(i, conc):
    return {"id": i, "model": "m", "hardware": "h200", "precision": "fp8", "framework": "vllm", "benchmark_type": "single_turn",
            "conc": conc, "date": "2026-09-01", "run_url": f"https://github.com/o/r/actions/runs/{100 + i}"}


ROWS = [_row(1, 4), _row(2, 8), _row(3, 16)]


def _text(rows):
    return "".join(json.dumps(r) + "\n" for r in rows)


def _ledger(tmp, rows=ROWS):
    return ldg.load(ledger_fake.write(tmp / "ledger", rows))


def test_the_extract_bytes_depend_only_on_its_content(tmp_path):
    a = lx.write_extract(_text(ROWS).splitlines(), [(2, "log two")], tmp_path / "a.gz")
    b = lx.write_extract(_text(list(reversed(ROWS))).splitlines(), [(2, "log two")], tmp_path / "b.gz")
    assert a == b and (tmp_path / "a.gz").read_bytes() == (tmp_path / "b.gz").read_bytes()
    assert a["rows"] == 3 and a["logs"] == 1
    rows, logs = lx.read(tmp_path / "a.gz")
    assert [r["id"] for r in rows] == [1, 2, 3] and logs == {"2": "log two"}
    assert all("server_log" not in r for r in rows)


def test_supplements_join_the_dump_rows_and_a_row_twice_is_refused(tmp_path):
    info = lx.write_extract(_text(ROWS[:2]).splitlines(), [], tmp_path / "x.gz", supplements=[ROWS[2]])
    assert info["rows"] == 3
    with pytest.raises(lx.ExtractError, match="row 2"):
        lx.write_extract(_text(ROWS).splitlines(), [], tmp_path / "y.gz", supplements=[ROWS[1]])


def test_the_build_check_wants_exactly_the_ledgers_units(tmp_path):
    lg = _ledger(tmp_path)
    assert lx.check_units(ROWS, lg) == 3
    with pytest.raises(lx.ExtractError, match="1 missing"):
        lx.check_units(ROWS[:2], lg)
    assert lx.check_units(ROWS[:2], lg, exact=False) == 2


def test_a_row_whose_content_is_not_the_ledgers_record_is_refused(tmp_path):
    lg = _ledger(tmp_path)
    with pytest.raises(ldg.RowDiffers):
        lx.check_units([{**ROWS[0], "precision": "fp4"}, *ROWS[1:]], lg)


def test_the_nights_check_holds_the_extract_to_its_pin(tmp_path):
    lg = _ledger(tmp_path)
    info = lx.write_extract(_text(ROWS).splitlines(), [], tmp_path / "x.gz")
    pin = {**info, "ledger_revision": lg.revision}
    rows, _ = lx.check(tmp_path / "x.gz", pin, lg)
    assert len(rows) == 3
    with pytest.raises(lx.ExtractError, match="sha256"):
        lx.check(tmp_path / "x.gz", {**pin, "sha256": "0" * 64}, lg)
    with pytest.raises(lx.ExtractError, match="ledger revision"):
        lx.check(tmp_path / "x.gz", {**pin, "ledger_revision": "db-dump/1999-01-01"}, lg)


def test_the_restore_reads_the_parts_sources_yaml_pins_and_refuses_one_whose_hash_differs(tmp_path):
    import hashlib
    good = b"part zero"
    sources = {"sources": [{"id": "inferencex", "revision": {
        "kind": "release_assets", "url": "https://github.com/o/app/releases/tag/db-dump/2026-09-28",
        "assets": [{"name": "d.part00", "sha256": hashlib.sha256(good).hexdigest()},
                   {"name": "d.part01", "sha256": "0" * 64}]}}]}
    base, parts = lx.dump_parts(sources)
    assert base == "https://github.com/o/app/releases/download/db-dump/2026-09-28" and len(parts) == 2
    seen = []

    def fetch(url, path):
        seen.append(url)
        Path(path).write_bytes(good)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for t in ("createdb", "pg_restore"):
        (bindir / t).write_text("#!/bin/sh\ncat >/dev/null\n")
        (bindir / t).chmod(0o755)
    with pytest.raises(lx.ExtractError, match="d.part01 has sha256"):
        lx.restore(sources, "db", str(bindir), fetch=fetch)
    assert seen == [f"{base}/d.part00", f"{base}/d.part01"]


def test_a_dump_row_keeps_its_text_and_only_the_logs_the_night_wants_are_read(tmp_path):
    # The dump's numbers are kept as the dump prints them (the ledger hashes that text); the log joins by row id.
    line = '{"id" : 7, "metrics" : {"mean_ttft": 0.10000000000000000555}}'
    lx.write_extract([line], [(7, "the log")], tmp_path / "x.gz")
    import gzip
    assert gzip.open(tmp_path / "x.gz", "rt").read() == line[:-1] + ',"server_log":"the log"}\n'
    assert lx.read(tmp_path / "x.gz", keep_log=lambda rid: False)[1] == {}
    assert lx.read(tmp_path / "x.gz", keep_log=lambda rid: rid == "7")[1] == {"7": "the log"}


def test_the_source_digest_changes_with_the_dump_the_supplements_or_the_anchor_list():
    src = {"sources": [{"id": "inferencex", "revision": {"ref": "db-dump/2026-09-28"}, "supplements": []}]}
    d = lx.source_digest(src, b"anchors")
    assert d != lx.source_digest(src, b"other anchors")
    assert d != lx.source_digest({"sources": [{**src["sources"][0], "supplements": [{"id": "s"}]}]}, b"anchors")
    with pytest.raises(lx.ExtractError, match="run the ledger-extract workflow"):
        lx.check_source(src, b"other anchors", {"source_sha256": d})
    lx.check_source(src, b"anchors", {"source_sha256": d})
