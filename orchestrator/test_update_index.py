"""The run index's two independent retentions (Discussion #15): count-based last-N for API
snapshots, dump snapshots never pruned, each entry tagged with its ingest for the picker."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import update_index as ui  # noqa: E402


def _snap(tmp, snap_id, *, ingest, blis="v0.12.0", ix="api-2026-10-23"):
    """Write a minimal summary.json under data/snapshots/<snap_id>/."""
    d = tmp / "snapshots" / snap_id
    d.mkdir(parents=True, exist_ok=True)
    prov = {"blis": {"release": blis}, "ground_truth": {"release_tag": ix}}
    if ingest == "api":
        prov["ingest"] = "api"
    doc = {"snapshot_id": snap_id, "generated_at": f"{snap_id[:10]}T00:00:00Z",
           "schema_version": 2 if ingest == "api" else 1, "provenance": prov}
    (d / "summary.json").write_text(json.dumps(doc))
    return d


def test_dump_snapshots_are_never_pruned(tmp_path):
    # Three dump snapshots + six API ones, keep_api=5: all 3 dumps stay, only 5 newest API kept.
    for i in range(3):
        _snap(tmp_path, f"2026-10-0{i+1}_blis-v0.1{i}.0_ix-2026-09-28", ingest="dump", ix="db-dump/2026-09-28")
    for i in range(6):
        _snap(tmp_path, f"2026-10-1{i}_blis-v0.12.0_ix-api-2026-10-23", ingest="api")
    entries = ui.build_index(str(tmp_path), keep_api=5, today=None)
    by_ingest = {"api": 0, "db-dump": 0}
    for e in entries:
        by_ingest[e["ingest"]] += 1
    assert by_ingest == {"api": 5, "db-dump": 3}
    # The pruned one is the OLDEST api snapshot (2026-10-10), never a dump.
    ids = {e["snapshot_id"] for e in entries}
    assert "2026-10-10_blis-v0.12.0_ix-api-2026-10-23" not in ids
    assert "2026-10-15_blis-v0.12.0_ix-api-2026-10-23" in ids
    for i in range(3):      # every dump snapshot survives
        assert f"2026-10-0{i+1}_blis-v0.1{i}.0_ix-2026-09-28" in ids
    # And its directory is gone from disk, not just the index.
    assert not (tmp_path / "snapshots" / "2026-10-10_blis-v0.12.0_ix-api-2026-10-23").exists()
    assert (tmp_path / "snapshots" / "2026-10-01_blis-v0.10.0_ix-2026-09-28").exists()


def test_a_sixth_api_release_prunes_the_oldest_api_not_a_dump(tmp_path):
    # The goal's "a 6th release prunes the oldest API snapshot, never a dump one".
    _snap(tmp_path, "2026-01-01_blis-v0.10.0_ix-2026-09-28", ingest="dump", ix="db-dump/2026-09-28")
    for day in range(1, 7):     # five, then a sixth API release
        _snap(tmp_path, f"2026-10-0{day}_blis-v0.12.0_ix-api-2026-10-23", ingest="api")
    entries = ui.build_index(str(tmp_path), keep_api=5, today=None)
    ids = [e["snapshot_id"] for e in entries]
    assert "2026-10-01_blis-v0.12.0_ix-api-2026-10-23" not in ids       # oldest API pruned
    assert "2026-01-01_blis-v0.10.0_ix-2026-09-28" in ids               # the old dump survives
    assert sum(1 for e in entries if e["ingest"] == "api") == 5


def test_entries_are_newest_first_and_tagged_with_ingest(tmp_path):
    _snap(tmp_path, "2026-10-01_blis-v0.11.0_ix-api-2026-10-23", ingest="api")
    _snap(tmp_path, "2026-10-03_blis-v0.12.0_ix-api-2026-10-23", ingest="api")
    _snap(tmp_path, "2026-09-28_blis-v0.12.0_ix-2026-09-28", ingest="dump", ix="db-dump/2026-09-28")
    entries = ui.build_index(str(tmp_path), keep_api=5, today=None)
    assert [e["snapshot_id"][:10] for e in entries] == ["2026-10-03", "2026-10-01", "2026-09-28"]
    assert {e["snapshot_id"][:10]: e["ingest"] for e in entries} == {
        "2026-10-03": "api", "2026-10-01": "api", "2026-09-28": "db-dump"}


def test_main_writes_index_json(tmp_path):
    _snap(tmp_path, "2026-10-03_blis-v0.12.0_ix-api-2026-10-23", ingest="api")
    rc = ui.main(["--data-dir", str(tmp_path), "--keep-api", "5", "--today", "2026-10-23"])
    assert rc == 0
    idx = json.loads((tmp_path / "index.json").read_text())
    assert idx["keep_api"] == 5
    assert idx["latest"] == "2026-10-03_blis-v0.12.0_ix-api-2026-10-23"
    assert idx["runs"][0]["ingest"] == "api"


def test_legacy_retention_days_flag_is_accepted_and_ignored(tmp_path):
    # The old dump pipeline called update_index with --retention-days; it must not error.
    _snap(tmp_path, "2026-10-03_blis-v0.12.0_ix-api-2026-10-23", ingest="api")
    assert ui.main(["--data-dir", str(tmp_path), "--retention-days", "30", "--today", "2026-10-23"]) == 0
