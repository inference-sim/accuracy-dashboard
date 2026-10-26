"""Incremental pull planning (Discussion #15, "Store"): reuse frozen points, freeze only new
rows, drop aged-out ones. Pure set arithmetic over point ids -- no network."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pull as pl  # noqa: E402
import contract  # noqa: E402


def _row(id_, model="m", conc=1, date_="2026-10-20"):
    return {"id": id_, "model": model, "hardware": "h100", "precision": "fp8", "framework": "vllm",
            "benchmark_type": "agentic_traces", "recipe_fingerprint": f"rf{id_}", "conc": conc, "date": date_}


def _entry(row):
    ident = pl.identity(row)
    return {"point_id": contract.point_id(ident), "identity": ident, "row": row, "files": {}}


def test_cold_pull_freezes_everything():
    rows = [_row("1"), _row("2")]
    inc = pl.plan_incremental(rows, prior_points=[])
    assert len(inc.fresh) == 2 and not inc.reuse and not inc.dropped


def test_incremental_reuses_frozen_and_freezes_only_new():
    r1, r2, r3 = _row("1"), _row("2"), _row("3")
    prior = [_entry(r1), _entry(r2)]
    inc = pl.plan_incremental([r1, r2, r3], prior_points=prior)
    assert set(inc.reuse) == {contract.point_id(pl.identity(r1)), contract.point_id(pl.identity(r2))}
    assert [r["id"] for r in inc.fresh] == ["3"]
    assert inc.dropped == set()


def test_aged_out_points_are_dropped():
    r1, r2 = _row("1", date_="2026-04-01"), _row("2", date_="2026-10-20")
    prior = [_entry(r1), _entry(r2)]
    # r1 has left the window (api.pull wouldn't return it); only r2 is in `rows`.
    inc = pl.plan_incremental([r2], prior_points=prior)
    assert inc.dropped == {contract.point_id(pl.identity(r1))}
    assert set(inc.reuse) == {contract.point_id(pl.identity(r2))}
    assert inc.fresh == []


def test_a_re_measurement_is_a_fresh_point_not_a_reuse():
    # Same deployment+conc, a new day -> a new point_id -> fresh, while the old one stays (until
    # it ages out). This is the goal's "re-measurement = new point".
    old = _row("1", date_="2026-09-01")
    new = _row("2", date_="2026-10-01")   # same config, different day and id
    prior = [_entry(old)]
    inc = pl.plan_incremental([old, new], prior_points=prior)
    assert [r["id"] for r in inc.fresh] == ["2"]
    assert set(inc.reuse) == {contract.point_id(pl.identity(old))}
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
