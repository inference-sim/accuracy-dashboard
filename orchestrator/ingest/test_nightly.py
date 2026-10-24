"""The nightly decision table (Discussion #15) and the latest-per-config live view, as pure
unit tests -- no network, no BLIS, no git. These are the local half of the goal's done-criterion
3 (the four IX x BLIS combinations, age-out, re-measurement, zero-scored no-op)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nightly as nt  # noqa: E402


# ---------------------------------------------------------------- the four-row trigger table

def test_no_ix_no_blis_is_a_noop():
    d = nt.plan_night(window_ids={"a", "b"}, last_ids={"a", "b"}, blis_tag="v0.12.0", last_blis_tag="v0.12.0")
    assert d.action == nt.NOOP and d.is_noop
    assert d.score_ids == set() and not d.freeze_snapshot and not d.update_live_view


def test_ix_only_scores_new_points_no_snapshot():
    # New point ids, same BLIS: score only the new ones, update the live view, no snapshot/diff.
    d = nt.plan_night(window_ids={"a", "b", "c"}, last_ids={"a", "b"}, blis_tag="v0.12.0", last_blis_tag="v0.12.0")
    assert d.action == nt.IX_ONLY
    assert d.score_ids == {"c"}           # only the new point, not the cached a/b
    assert d.update_live_view and not d.freeze_snapshot


def test_blis_only_rescored_whole_window_and_freezes():
    # New BLIS, same data: rescore everything, freeze a snapshot, diff allowed (100% common).
    d = nt.plan_night(window_ids={"a", "b"}, last_ids={"a", "b"}, blis_tag="v0.13.0", last_blis_tag="v0.12.0")
    assert d.action == nt.BLIS_ONLY
    assert d.score_ids == {"a", "b"}      # the whole window, not a subset
    assert d.freeze_snapshot and d.update_live_view


def test_both_rescores_whole_window_including_new():
    # New BLIS and new data: rescore the whole window incl. the new point; freeze; diff on common.
    d = nt.plan_night(window_ids={"a", "b", "c"}, last_ids={"a", "b"}, blis_tag="v0.13.0", last_blis_tag="v0.12.0")
    assert d.action == nt.BOTH
    assert d.score_ids == {"a", "b", "c"}
    assert d.freeze_snapshot and d.update_live_view
    assert "incl. 1 new" in d.reason


def test_age_out_only_updates_live_view_nothing_else():
    # Points only left the window: rebuild the live view, score nothing, freeze nothing.
    d = nt.plan_night(window_ids={"a"}, last_ids={"a", "b"}, blis_tag="v0.12.0", last_blis_tag="v0.12.0")
    assert d.action == nt.AGE_OUT
    assert d.score_ids == set()
    assert d.update_live_view and not d.freeze_snapshot


def test_age_out_with_new_points_is_an_ix_release_not_age_out():
    # A night that both gains and loses points is an IX release (the gain is the trigger).
    d = nt.plan_night(window_ids={"a", "c"}, last_ids={"a", "b"}, blis_tag="v0.12.0", last_blis_tag="v0.12.0")
    assert d.action == nt.IX_ONLY and d.score_ids == {"c"}


def test_seed_scores_whole_window_and_freezes():
    d = nt.plan_night(window_ids={"a", "b"}, last_ids=set(), blis_tag="v0.11.0", last_blis_tag=None)
    assert d.action == nt.SEED
    assert d.score_ids == {"a", "b"} and d.freeze_snapshot and d.update_live_view


def test_a_night_must_resolve_a_blis_release():
    import pytest
    with pytest.raises(ValueError):
        nt.plan_night(window_ids=set(), last_ids=set(), blis_tag="", last_blis_tag=None)


# ---------------------------------------------------------------- zero-scored no-op

def test_zero_scored_run_becomes_a_noop():
    planned = nt.plan_night(window_ids={"a"}, last_ids=set(), blis_tag="v0.11.0", last_blis_tag=None)
    assert planned.action == nt.SEED
    got = nt.zero_scored_is_noop(planned, scored_count=0)
    assert got.is_noop and "zero" in got.reason


def test_age_out_scoring_zero_is_still_age_out():
    # Age-out scores nothing by design, but its live view is non-empty (from the cache), so it is
    # not turned into a no-op.
    planned = nt.plan_night(window_ids={"a"}, last_ids={"a", "b"}, blis_tag="v0.12.0", last_blis_tag="v0.12.0")
    assert nt.zero_scored_is_noop(planned, scored_count=0).action == nt.AGE_OUT


def test_a_run_that_scores_keeps_its_action():
    planned = nt.plan_night(window_ids={"a", "b"}, last_ids={"a", "b"}, blis_tag="v0.13.0", last_blis_tag="v0.12.0")
    assert nt.zero_scored_is_noop(planned, scored_count=2).action == nt.BLIS_ONLY


# ---------------------------------------------------------------- latest-per-config live view

def _pt(pid, model, conc, date_):
    return {"point_id": pid,
            "identity": {"model": model, "hardware": "h100", "precision": "fp8", "framework": "vllm",
                         "benchmark_type": "agentic_traces", "recipe": "r1", "conc": conc, "measured_date": date_}}


def test_latest_per_config_keeps_only_the_newest_measurement():
    # One config (same model/hardware/.../conc) measured on two days: the live view shows the newer.
    pts = [_pt("old", "m", 1, "2026-09-01"), _pt("new", "m", 1, "2026-10-01")]
    live = nt.latest_per_config(pts)
    assert [p["point_id"] for p in live] == ["new"]


def test_latest_per_config_keeps_distinct_configs():
    # Different concurrency is a different config; both are kept.
    pts = [_pt("c1", "m", 1, "2026-10-01"), _pt("c2", "m", 2, "2026-10-01")]
    assert len(nt.latest_per_config(pts)) == 2


def test_a_re_measurement_is_a_new_point_and_wins_the_live_view():
    # A re-measurement is a new point_id (immutable identity incl. date); the older one stays in
    # the store/snapshot but the live view shows the newest.
    assert nt.config_key(_pt("old", "m", 1, "2026-09-01")["identity"]) == \
           nt.config_key(_pt("new", "m", 1, "2026-10-01")["identity"])
    live = nt.latest_per_config([_pt("old", "m", 1, "2026-09-01"), _pt("new", "m", 1, "2026-10-01")])
    assert [p["point_id"] for p in live] == ["new"]


def test_latest_per_config_tie_broken_by_point_id_deterministically():
    pts = [_pt("zzz", "m", 1, "2026-10-01"), _pt("aaa", "m", 1, "2026-10-01")]
    assert [p["point_id"] for p in nt.latest_per_config(pts)] == ["zzz"]
