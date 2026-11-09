"""Incremental pull planning (Discussion #15, "Store"): reuse frozen points, freeze only new
rows, drop aged-out ones. Pure set arithmetic over point ids -- no network."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pull as pl  # noqa: E402
import ledger as ldg  # noqa: E402
import ledger_fake  # noqa: E402


def _row(id_, model="m", conc=1, date_="2026-10-20"):
    return {"id": id_, "model": model, "hardware": "h100", "precision": "fp8", "framework": "vllm",
            "benchmark_type": "agentic_traces", "recipe_fingerprint": f"rf{id_}", "conc": conc, "date": date_,
            "run_url": f"https://github.com/o/r/actions/runs/{id_}/attempts/1"}


def _points(tmp_path, rows):
    return {p.row["id"]: p for p in pl.place(rows, ldg.load(ledger_fake.write(tmp_path / "ledger", rows))).points}


def _entry(p):
    return {"point_id": p.point_id, "identity": p.unit.identity, "row": p.row, "records": p.records, "files": {}}


def test_cold_pull_freezes_everything(tmp_path):
    pts = _points(tmp_path, [_row("1"), _row("2")])
    inc = pl.plan_incremental(list(pts.values()), prior_points=[])
    assert len(inc.fresh) == 2 and not inc.reuse and not inc.dropped


def test_incremental_reuses_frozen_and_freezes_only_new(tmp_path):
    pts = _points(tmp_path, [_row("1"), _row("2"), _row("3")])
    prior = [_entry(pts["1"]), _entry(pts["2"])]
    inc = pl.plan_incremental(list(pts.values()), prior_points=prior)
    assert set(inc.reuse) == {pts["1"].point_id, pts["2"].point_id}
    assert [p.row["id"] for p in inc.fresh] == ["3"]
    assert inc.dropped == set()


def test_a_point_whose_records_changed_is_frozen_again(tmp_path):
    # A unit that holds another record tonight (a new attempt the ledger joined) is not reused.
    pts = _points(tmp_path, [_row("1")])
    stale = {**_entry(pts["1"]), "records": []}
    inc = pl.plan_incremental(list(pts.values()), prior_points=[stale])
    assert [p.row["id"] for p in inc.fresh] == ["1"] and not inc.reuse


def test_aged_out_points_are_dropped(tmp_path):
    pts = _points(tmp_path, [_row("1", date_="2026-04-01"), _row("2", date_="2026-10-20")])
    prior = [_entry(pts["1"]), _entry(pts["2"])]
    # r1 has left the window (api.pull wouldn't return it); only r2 is in the window.
    inc = pl.plan_incremental([pts["2"]], prior_points=prior)
    assert inc.dropped == {pts["1"].point_id}
    assert set(inc.reuse) == {pts["2"].point_id}
    assert inc.fresh == []


def test_a_re_measurement_is_a_fresh_point_not_a_reuse(tmp_path):
    # Same deployment+conc, a new day and run -> a new point_id -> fresh, while the old one
    # stays (until it ages out). This is the goal's "re-measurement = new point".
    pts = _points(tmp_path, [_row("1", date_="2026-09-01"), _row("2", date_="2026-10-01")])
    inc = pl.plan_incremental(list(pts.values()), prior_points=[_entry(pts["1"])])
    assert [p.row["id"] for p in inc.fresh] == ["2"]
    assert set(inc.reuse) == {pts["1"].point_id}
    assert inc.dropped == set()


def test_prune_point_files_removes_the_point_dir(tmp_path):
    pid = "abc123"
    d = tmp_path / "points" / pid
    d.mkdir(parents=True)
    (d / "server_log.gz").write_bytes(b"x")
    pl.prune_point_files(tmp_path, pid)
    assert not d.exists()


def test_load_prior_manifest(tmp_path):
    assert pl.load_prior_manifest(tmp_path) is None
    import json
    (tmp_path / "manifest.json").write_text(json.dumps({"points": [{"point_id": "x"}]}))
    m = pl.load_prior_manifest(tmp_path)
    assert m["points"][0]["point_id"] == "x"
