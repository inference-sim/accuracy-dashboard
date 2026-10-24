"""The nightly driver: one run of the API-ingest pipeline (Discussion #15).

run_night() composes the pieces the rest of this package builds -- the incremental pull, the
trigger decision (nightly.plan_night), the cumulative-but-cached score, the v2 summary, the
two-retention index and the ix-store -- into the sequence a CI night runs:

  1. Pull the current 180-day window into the store, incrementally (reuse frozen points, freeze
     new rows, drop aged-out ones). The store is rewritten to hold only the current window.
  2. Decide what the night does from #15's trigger table: compare the window's point ids and the
     resolved BLIS tag against last night's.
  3. If it's a no-op, stop -- the last good published view stands, nothing is written.
  4. Otherwise score the window (cached by exact inputs, so only changed points do real work) and
     build the v2 summary.
  5. A run that scored zero points becomes a no-op (the dashboard never blanks out).
  6. Publish: always refresh the live view; on a BLIS release also freeze a diffable snapshot.
     Rebuild the index (count-based last-5 API snapshots; dump snapshots untouched) and record
     tonight's state.

The expensive, infrastructure-bound steps (the pull's network, BLIS scoring) are injected as
`pull_fn` and `score_build_fn`, so this orchestration is tested with fakes -- no network, no BLIS,
no catalog. cli.py nightly wires the real implementations. Everything else here is real file I/O,
the same in a test and in CI.
"""
from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import nightly as nt  # noqa: E402
import pull as pl  # noqa: E402
import update_index as ui  # noqa: E402


@dataclass
class NightResult:
    """What a night did, for the log and for tests."""
    decision: nt.Decision
    snapshot_id: str | None = None
    scored: int = 0
    published: bool = False

    @property
    def action(self) -> str:
        return self.decision.action


def _read_state(state_path: Path) -> dict:
    if state_path.is_file():
        try:
            return json.loads(state_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _store_ids(store_dir: Path) -> set[str]:
    """The point ids last night's store holds (empty on the seed)."""
    m = pl.load_prior_manifest(store_dir)
    return {p["point_id"] for p in m["points"]} if m else set()


def snapshot_id(snapshot_date: str, blis_tag: str, pull_date: str) -> str:
    """The snapshot/live-view id: date_blis-<release>_ix-api-<pull-date>. Matches
    build_summary_v2's id so a frozen snapshot and the summary it holds agree."""
    return f"{snapshot_date}_blis-{blis_tag}_ix-api-{pull_date}"


def run_night(today: date, blis_tag: str, *, store_dir: Path, data_dir: Path, state_path: Path,
              pull_fn, score_build_fn, snapshot_date: str, keep_api: int = 5) -> NightResult:
    """One night. `pull_fn(store_dir, today) -> pull_date` rewrites the store to the current
    window and returns the pull's date. `score_build_fn(store_dir, blis_tag, score_ids, pull_date)
    -> (summary_dict, scored_count)` scores the window (honouring `score_ids` as the compute hint
    -- the rest is served from the cache) and returns the v2 summary and how many points scored."""
    store_dir, data_dir, state_path = Path(store_dir), Path(data_dir), Path(state_path)
    state = _read_state(state_path)
    last_ids = _store_ids(store_dir)
    last_blis = state.get("blis_tag")

    # 1. Pull the current window into the store (incremental; store holds only this window).
    pull_date = pull_fn(store_dir, today)
    window_ids = _store_ids(store_dir)

    # 2. Decide.
    decision = nt.plan_night(window_ids, last_ids, blis_tag, last_blis)

    # 3. No-op: keep the last good published view, write nothing.
    if decision.is_noop:
        return NightResult(decision)

    # 4. Score the window (cached) and build the summary.
    summary, scored = score_build_fn(store_dir, blis_tag, decision.score_ids, pull_date)

    # 5. A run that scored zero points becomes a no-op.
    decision = nt.zero_scored_is_noop(decision, scored)
    if decision.is_noop:
        return NightResult(decision, scored=scored)

    # 6. Publish. Ordered so a failure can't half-publish: the snapshot dir and the index are
    # written first (they don't touch the served latest), then the live view, then state last. If
    # the index rebuild throws, data/latest and state both still describe last night's good run.
    snap_id = summary.get("snapshot_id") or snapshot_id(snapshot_date, blis_tag, pull_date)
    if decision.freeze_snapshot:
        _write_summary(data_dir / "snapshots" / snap_id / "summary.json", summary)
    ui.main(["--data-dir", str(data_dir), "--keep-api", str(keep_api)])
    published = False
    if decision.update_live_view:
        _write_summary(data_dir / "latest" / "summary.json", summary)
        published = True
    _write_state(state_path, blis_tag, snap_id, sorted(window_ids))
    return NightResult(decision, snapshot_id=snap_id if decision.freeze_snapshot else None,
                       scored=scored, published=published)


def _write_summary(path: Path, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")


def _write_state(state_path: Path, blis_tag: str, snapshot_id: str, point_ids: list[str]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(
        {"ingest": "api", "blis_tag": blis_tag, "snapshot_id": snapshot_id,
         "point_count": len(point_ids)}, indent=2) + "\n")
