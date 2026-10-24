"""Fabricated IX and BLIS releases, driven through run_night, verifying the goal's done-criterion
3 end to end (orchestration only -- no network, no BLIS). A tiny in-memory "world" stands in for
the API and the scorer:

  * a FakePull writes a store from a list of (point_id, measured_date) rows, incrementally
    (reusing a prior store, dropping aged-out points), exactly as cli.py pull does;
  * a FakeScorer builds a minimal v2-shaped summary from the store and counts a cache hit for any
    point it scored before with the same BLIS tag, so "cache honored" and "byte-identical rescore"
    are observable.

Each test fabricates a sequence of nights and asserts what #15's table says should happen.
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nightly as nt  # noqa: E402
import nightly_run as nr  # noqa: E402
import pull as pl  # noqa: E402
import contract as c  # noqa: E402


# ---------------------------------------------------------------- fakes

def _ident(model, conc, measured_date):
    return {"model": model, "hardware": "h100", "precision": "fp8", "framework": "vllm",
            "benchmark_type": "agentic_traces", "recipe": f"r-{model}-{conc}", "conc": conc,
            "measured_date": measured_date}


def pid_of(model, conc, measured_date):
    return c.point_id(_ident(model, conc, measured_date))


class World:
    """The fabricated universe: the current window's rows, and a scorer that records what it
    scored so a rescore can be checked for a cache hit."""
    def __init__(self):
        self.rows = []                  # list of (model, conc, measured_date)
        self.scored_log = []            # (blis_tag, frozenset(point_ids)) per score call
        self.score_cache = {}           # (blis_tag, point_id) -> stable fake metric

    # -- pull_fn: rewrite the store to exactly self.rows (incremental vs the prior store)
    def pull(self, store_dir: Path, today: date) -> str:
        store_dir = Path(store_dir)
        want = {pid_of(*r): r for r in self.rows}
        prior = pl.load_prior_manifest(store_dir)
        prior_ids = {p["point_id"] for p in prior["points"]} if prior else set()
        # drop aged-out point dirs
        for pid in prior_ids - set(want):
            pl.prune_point_files(store_dir, pid)
        points = []
        for pid, (model, conc, md) in sorted(want.items()):
            ident = _ident(model, conc, md)
            (store_dir / "points" / pid).mkdir(parents=True, exist_ok=True)
            points.append({"point_id": pid, "identity": ident,
                           "row": {"model": model, "conc": conc, "date": md}, "files": {}})
        pull_date = today.isoformat()
        pl.write_manifest(store_dir, {"window": ["", pull_date], "pulled_at": pull_date + "T00:00:00Z"}, points)
        return pull_date

    # -- score_build_fn: build a minimal v2 summary; count cache hits
    def score(self, store_dir: Path, blis_tag: str, score_ids: set, pull_date: str):
        m = pl.load_prior_manifest(Path(store_dir))
        entries = m["points"]
        # Honour the cache: a point already scored under this BLIS tag isn't real work. score_ids
        # is the compute hint; everything else must already be cached or this is a bug.
        real_work = set()
        for e in entries:
            key = (blis_tag, e["point_id"])
            if key not in self.score_cache:
                self.score_cache[key] = {"ttft_ms": 1.0, "tpot_ms": 1.0}
                real_work.add(e["point_id"])
        self.scored_log.append((blis_tag, frozenset(real_work)))
        summary = _fake_summary(entries, blis_tag, pull_date)
        return summary, len(entries)


def _fake_summary(entries, blis_tag, pull_date):
    """A v2-shaped summary skeleton -- enough for run_night and update_index, not the full schema."""
    return {"schema_version": 2,
            "snapshot_id": nr.snapshot_id(pull_date, blis_tag, pull_date),
            "generated_at": pull_date + "T00:00:00Z",
            "provenance": {"ingest": "api", "blis": {"release": blis_tag},
                           "ground_truth": {"release_tag": f"api-{pull_date}"}},
            "coverage": {"scored": len(entries), "not_scored": 0},
            "totals": {}, "matrix": [], "not_scored": [],
            "point_ids": sorted(e["point_id"] for e in entries)}


def _run(world, tmp, today, blis_tag, keep_api=5):
    return nr.run_night(date.fromisoformat(today), blis_tag,
                        store_dir=tmp / "store", data_dir=tmp / "data",
                        state_path=tmp / "state.json",
                        pull_fn=world.pull, score_build_fn=world.score,
                        snapshot_date=today, keep_api=keep_api)


def _index(tmp):
    return json.loads((tmp / "data" / "index.json").read_text())


# ---------------------------------------------------------------- the four combinations

def test_seed_then_no_no_is_a_noop(tmp_path):
    w = World()
    w.rows = [("m", 1, "2026-10-01"), ("m", 2, "2026-10-01")]
    seed = _run(w, tmp_path, "2026-10-02", "v0.11.0")
    assert seed.action == nt.SEED and seed.snapshot_id and seed.published
    # Night 2: nothing changed -> no-op, no new snapshot, index unchanged.
    before = _index(tmp_path)
    r = _run(w, tmp_path, "2026-10-03", "v0.11.0")
    assert r.decision.is_noop
    assert _index(tmp_path)["runs"] == before["runs"]


def test_ix_only_scores_new_points_keeps_cache_no_snapshot(tmp_path):
    w = World()
    w.rows = [("m", 1, "2026-10-01")]
    _run(w, tmp_path, "2026-10-02", "v0.11.0")           # seed: scores p1
    snaps_before = sorted((tmp_path / "data" / "snapshots").iterdir())
    # Night 2: a new point arrives, same BLIS.
    w.rows = [("m", 1, "2026-10-01"), ("m", 2, "2026-10-02")]
    r = _run(w, tmp_path, "2026-10-03", "v0.11.0")
    assert r.action == nt.IX_ONLY
    assert r.decision.score_ids == {pid_of("m", 2, "2026-10-02")}   # only the new point
    assert r.published and r.snapshot_id is None                    # live view updated, no snapshot
    # The cache was honoured: the second score call did real work only for the new point.
    assert w.scored_log[-1][1] == {pid_of("m", 2, "2026-10-02")}
    assert sorted((tmp_path / "data" / "snapshots").iterdir()) == snaps_before   # no new snapshot


def test_blis_only_rescns_whole_window_freezes_snapshot(tmp_path):
    w = World()
    w.rows = [("m", 1, "2026-10-01"), ("m", 2, "2026-10-01")]
    _run(w, tmp_path, "2026-10-02", "v0.11.0")           # seed with v0.11.0
    # Night 2: a new BLIS release, same data.
    r = _run(w, tmp_path, "2026-10-03", "v0.12.0")
    assert r.action == nt.BLIS_ONLY
    assert r.decision.score_ids == {pid_of("m", 1, "2026-10-01"), pid_of("m", 2, "2026-10-01")}
    assert r.snapshot_id and "v0.12.0" in r.snapshot_id and r.published
    # Two snapshots now exist (v0.11.0 seed + v0.12.0), both diffable.
    ids = [e["snapshot_id"] for e in _index(tmp_path)["runs"]]
    assert any("v0.11.0" in i for i in ids) and any("v0.12.0" in i for i in ids)
    # The whole window did real work under the new tag (nothing cached under v0.12.0 yet).
    assert len(w.scored_log[-1][1]) == 2


def test_both_rescns_whole_window_including_new(tmp_path):
    w = World()
    w.rows = [("m", 1, "2026-10-01")]
    _run(w, tmp_path, "2026-10-02", "v0.11.0")           # seed
    # Night 2: new BLIS AND a new point.
    w.rows = [("m", 1, "2026-10-01"), ("m", 2, "2026-10-02")]
    r = _run(w, tmp_path, "2026-10-03", "v0.12.0")
    assert r.action == nt.BOTH
    assert r.decision.score_ids == {pid_of("m", 1, "2026-10-01"), pid_of("m", 2, "2026-10-02")}
    assert r.snapshot_id and "v0.12.0" in r.snapshot_id


# ---------------------------------------------------------------- the extra cases

def test_re_measurement_is_a_new_point_and_both_stay_in_the_window(tmp_path):
    w = World()
    w.rows = [("m", 1, "2026-09-01")]
    _run(w, tmp_path, "2026-09-02", "v0.11.0")
    # A re-measurement of the same config on a new day: a new point id, same BLIS -> IX release.
    w.rows = [("m", 1, "2026-09-01"), ("m", 1, "2026-10-01")]
    r = _run(w, tmp_path, "2026-10-02", "v0.11.0")
    assert r.action == nt.IX_ONLY
    assert r.decision.score_ids == {pid_of("m", 1, "2026-10-01")}
    # Both measurements are still in the store (a measurement is immutable).
    m = pl.load_prior_manifest(tmp_path / "store")
    assert {e["point_id"] for e in m["points"]} == {pid_of("m", 1, "2026-09-01"), pid_of("m", 1, "2026-10-01")}


def test_age_out_drops_today_minus_180_keeps_today_minus_179_updates_live_view(tmp_path):
    import api
    from datetime import timedelta
    today = date(2026, 10, 23)
    start, _ = api.window_bounds(today, 180)                 # today-179
    keep = start.isoformat()                                 # today-179, stays
    drop = (start - timedelta(days=1)).isoformat()           # today-180, ages out
    w = World()
    w.rows = [("m", 1, keep), ("m", 2, drop)]
    _run(w, tmp_path, "2026-10-22", "v0.11.0")               # both present the night before
    # Tonight the old one ages out of the 180-day window (the fake pull is told only the kept row).
    w.rows = [("m", 1, keep)]
    r = _run(w, tmp_path, today.isoformat(), "v0.11.0")
    assert r.action == nt.AGE_OUT
    assert r.published and r.snapshot_id is None             # live view rebuilt, no snapshot/diff
    # The aged-out point and its files are gone from the store.
    m = pl.load_prior_manifest(tmp_path / "store")
    assert {e["point_id"] for e in m["points"]} == {pid_of("m", 1, keep)}
    assert not (tmp_path / "store" / "points" / pid_of("m", 2, drop)).exists()


def test_zero_scored_run_is_a_noop_and_keeps_last_good_view(tmp_path):
    # A scorer that scores nothing (e.g. a model BLIS can't handle) must not blank the dashboard.
    w = World()
    w.rows = [("m", 1, "2026-10-01")]
    seed = _run(w, tmp_path, "2026-10-02", "v0.11.0")
    good = (tmp_path / "data" / "latest" / "summary.json").read_text()
    # Night 2: a BLIS release, but the scorer returns zero scored.
    w.score = lambda store_dir, blis_tag, score_ids, pull_date: (_fake_summary([], blis_tag, pull_date), 0)
    r = _run(w, tmp_path, "2026-10-03", "v0.12.0")
    assert r.decision.is_noop
    assert (tmp_path / "data" / "latest" / "summary.json").read_text() == good   # last good view stands
    assert seed.snapshot_id   # the seed snapshot is untouched


def test_sixth_api_release_prunes_oldest_api_never_a_dump(tmp_path):
    # Seed a legacy dump snapshot by hand (CI never creates these; the picker keeps them forever).
    dump_id = "2026-01-01_blis-v0.10.0_ix-2026-09-28"
    dd = tmp_path / "data" / "snapshots" / dump_id
    dd.mkdir(parents=True)
    (dd / "summary.json").write_text(json.dumps(
        {"snapshot_id": dump_id, "schema_version": 1,
         "provenance": {"blis": {"release": "v0.10.0"}, "ground_truth": {"release_tag": "db-dump/2026-09-28"}}}))
    w = World()
    w.rows = [("m", 1, "2026-10-01")]
    # Six BLIS releases -> six API snapshots; keep_api=5 prunes the oldest API one.
    tags = ["v0.11.0", "v0.12.0", "v0.13.0", "v0.14.0", "v0.15.0", "v0.16.0"]
    for i, tag in enumerate(tags):
        _run(w, tmp_path, f"2026-10-0{i+2}", tag)
    ids = [e["snapshot_id"] for e in _index(tmp_path)["runs"]]
    api_ids = [i for i in ids if "ix-api" in i]
    assert len(api_ids) == 5                               # last 5 API snapshots
    assert not any("v0.11.0" in i for i in api_ids)        # the oldest API snapshot was pruned
    assert dump_id in ids                                  # the dump snapshot survived
    assert (tmp_path / "data" / "snapshots" / dump_id).exists()


def test_seed_rescore_is_byte_identical(tmp_path):
    # The seed's summary, rebuilt from the same frozen store with the same BLIS, is byte-identical
    # (the cache does no new work and the inputs are unchanged).
    w = World()
    w.rows = [("m", 1, "2026-10-01"), ("m", 2, "2026-10-01")]
    _run(w, tmp_path, "2026-10-02", "v0.11.0")
    first = (tmp_path / "data" / "latest" / "summary.json").read_text()
    cache_calls_before = len(w.scored_log)
    # Re-run the very same night against the same store: no-op (nothing changed), view unchanged.
    r = _run(w, tmp_path, "2026-10-02", "v0.11.0")
    assert r.decision.is_noop
    assert (tmp_path / "data" / "latest" / "summary.json").read_text() == first
    # The score cache was fully warm: had it run, it would have done zero real work.
    assert len(w.scored_log) == cache_calls_before        # no-op didn't even call the scorer
