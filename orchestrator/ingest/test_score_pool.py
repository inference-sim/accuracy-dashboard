"""score_points' type-split concurrency (single-turn parallel, agentic serial) is a pure speed
knob: the result is in input order and identical whatever the worker counts. No BLIS needed --
_score_one is stubbed to a deterministic outcome keyed by point_id."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import score as sc  # noqa: E402


def _pt(pid, agentic):
    return {"point_id": pid, "identity": {}, "reasons": [],
            "row": {"benchmark_type": "agentic_traces" if agentic else "single_turn",
                    "model": "m", "hardware": "h100", "conc": 1}}


def _stub(monkeypatch):
    # deterministic outcome per point, independent of worker/process (so results must match
    # regardless of concurrency). Runs in-process, so no pickling/pool spin-up needed.
    def fake(entry, pull_dir, work, env):
        return sc.Outcome(point_id=entry["point_id"], identity={}, row=entry["row"],
                          reasons=[f"r-{entry['point_id']}"])
    monkeypatch.setattr(sc, "_score_one", fake)
    monkeypatch.setattr(sc, "_worker_score", lambda e: fake(e, None, None, None))


def test_split_scores_every_point_in_input_order(tmp_path, monkeypatch):
    _stub(monkeypatch)
    pts = [_pt("s0", False), _pt("a0", True), _pt("s1", False), _pt("a1", True), _pt("s2", False)]
    out = sc.score_points(pts, tmp_path, tmp_path, env=None, workers=1, agentic_workers=1)
    assert [o.point_id for o in out] == ["s0", "a0", "s1", "a1", "s2"]  # input order preserved


def test_split_interleaves_types_but_keeps_input_order(tmp_path, monkeypatch):
    # single-turn and agentic are scored in separate phases, yet the returned list is in the
    # ORIGINAL input order (write_contract re-sorts anyway, but order-stability is the contract).
    # workers=1 keeps it in-process; the real pool's byte-identical output is proven in test_score_e2e.
    _stub(monkeypatch)
    pts = [_pt(f"s{i}", False) for i in range(6)] + [_pt(f"a{i}", True) for i in range(3)]
    out = sc.score_points(pts, tmp_path, tmp_path, env=None, workers=1, agentic_workers=1)
    assert [o.point_id for o in out] == [p["point_id"] for p in pts]
    assert [o.reasons for o in out] == [[f"r-{p['point_id']}"] for p in pts]


def test_all_agentic_window_still_scores_everything(tmp_path, monkeypatch):
    # the realistic case today: the delta is ~all agentic -> all go through the serial path.
    _stub(monkeypatch)
    pts = [_pt(f"a{i}", True) for i in range(10)]
    out = sc.score_points(pts, tmp_path, tmp_path, env=None, workers=1, agentic_workers=1)
    assert len(out) == 10 and [o.point_id for o in out] == [f"a{i}" for i in range(10)]


def test_is_agentic_classifies_by_benchmark_type():
    assert sc._is_agentic(_pt("x", True))
    assert not sc._is_agentic(_pt("y", False))


# ---------------------------------------------------------------- run_capped (per-replay RSS cap)

def test_run_capped_kills_a_process_over_the_rss_ceiling():
    import pytest
    prog = "a=[]\nimport time\nfor i in range(60): a.append(bytearray(10*1024*1024)); time.sleep(0.05)\ntime.sleep(5)"
    with pytest.raises(sc.MemoryExceeded):
        sc.run_capped(["python3", "-c", prog], timeout=30, max_rss_mb=100, poll_s=0.3)


def test_run_capped_lets_a_small_process_finish():
    r = sc.run_capped(["python3", "-c", "print('ok')"], timeout=30, max_rss_mb=4000, poll_s=0.3)
    assert r.returncode == 0 and r.stdout.strip() == "ok"


def test_run_capped_zero_is_a_plain_run():
    r = sc.run_capped(["python3", "-c", "print('nocap')"], timeout=30, max_rss_mb=0)
    assert r.returncode == 0 and r.stdout.strip() == "nocap"
