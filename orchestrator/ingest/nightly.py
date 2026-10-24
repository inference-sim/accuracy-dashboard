"""The nightly decision: which of Discussion #15's two triggers fired, and what to do.

A pure function of four facts a night knows before it does any real work:

  * the point ids the current 180-day pull holds (window_ids),
  * the point ids last night's store held (last_ids),
  * the BLIS release resolved for tonight (blis_tag),
  * the BLIS release last night scored (last_blis_tag).

From those it reads #15's four-row trigger table and returns a Decision: what to score, whether
to freeze a snapshot, whether to republish the live view, and a one-line human reason. Nothing
here touches the network, BLIS or git -- the driver (cli.py nightly) does the work this plans,
so every branch of the table is a unit test with no infrastructure.

The triggers (#15, "Two triggers, two actions"):
  * An IX data release is any point id in the window that wasn't in the store last night.
  * A BLIS release is a new stable inference-sim tag (resolve_inputs.sh resolves it).
  * A night where points only age out of the window updates the live view and nothing else.

  IX   BLIS   Action
  no   no     no-op
  yes  no     score the new points only; update the live view; no snapshot, no diff
  no   yes    rescore the whole window; freeze a snapshot; diff allowed
  yes  yes    pull latest, rescore the whole window incl. new data; freeze a snapshot; diff on common

Age-out (points leaving the window with no new points and no BLIS release) is the no/no row's
one exception: the window changed, so the live view is rebuilt, but nothing is scored or frozen.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import contract


# The actions, named for #15's table rows. SEED is the day-one bootstrap (no prior store), which
# scores the whole window and freezes a snapshot like a BLIS release, but isn't a "change".
NOOP = "noop"
AGE_OUT = "age_out"
IX_ONLY = "ix_only"
BLIS_ONLY = "blis_only"
BOTH = "both"
SEED = "seed"


@dataclass
class Decision:
    """What tonight does. `score_ids` is the subset of the window to (re)score; the rest of the
    window is served from the score cache unchanged. `freeze_snapshot` adds a picker entry and a
    diffable frozen record; `update_live_view` republishes data/latest. A no-op does neither and
    keeps last night's published view."""
    action: str
    score_ids: set[str] = field(default_factory=set)
    freeze_snapshot: bool = False
    update_live_view: bool = False
    reason: str = ""

    @property
    def is_noop(self) -> bool:
        return self.action == NOOP


def plan_night(window_ids: set[str], last_ids: set[str], blis_tag: str,
               last_blis_tag: str | None) -> Decision:
    """Read #15's trigger table. `last_blis_tag` is None on the seed (no prior store)."""
    if not blis_tag:
        raise ValueError("a night must resolve a BLIS release before it can decide anything")
    new_points = window_ids - last_ids
    aged_out = last_ids - window_ids
    blis_changed = last_blis_tag is not None and blis_tag != last_blis_tag

    # The seed: no store yet. Score the whole window and freeze the first snapshot(s).
    if last_blis_tag is None:
        return Decision(SEED, score_ids=set(window_ids), freeze_snapshot=True, update_live_view=True,
                        reason=f"seed: score {len(window_ids)} points with {blis_tag} and freeze the first snapshot")

    # A BLIS release (with or without new data): rescore the whole window, freeze a snapshot,
    # allow a diff. New points are scored as part of "the whole window", so `both` differs from
    # `blis_only` only in its reason.
    if blis_changed:
        action = BOTH if new_points else BLIS_ONLY
        extra = f", incl. {len(new_points)} new" if new_points else ""
        return Decision(action, score_ids=set(window_ids), freeze_snapshot=True, update_live_view=True,
                        reason=f"BLIS {last_blis_tag} -> {blis_tag}: rescore {len(window_ids)} points{extra}, "
                               f"freeze a snapshot")

    # Same BLIS release from here on: no snapshot, no diff.
    if new_points:
        # An IX release: score only the new points (the cache covers the rest), merge into the
        # live view.
        return Decision(IX_ONLY, score_ids=set(new_points), freeze_snapshot=False, update_live_view=True,
                        reason=f"{len(new_points)} new point(s) under {blis_tag}: score them, update the live view")

    if aged_out:
        # Points only left the window: rebuild the live view from the pruned store, nothing scored.
        return Decision(AGE_OUT, score_ids=set(), freeze_snapshot=False, update_live_view=True,
                        reason=f"{len(aged_out)} point(s) aged out under {blis_tag}: update the live view")

    # Nothing changed.
    return Decision(NOOP, score_ids=set(), freeze_snapshot=False, update_live_view=False,
                    reason=f"no new points, none aged out, BLIS still {blis_tag}: nothing to do")


# A config is a measurement's identity with the date removed: one deployment (model, hardware,
# precision, framework, recipe) at one concurrency and benchmark type. Two measurements of the
# same config on different days are the same config, the newer superseding the older in the live
# view (Discussion #15, Decided: "the live view shows the latest result per config").
CONFIG_FIELDS = tuple(f for f in contract.IDENTITY_FIELDS if f != "measured_date")


def config_key(identity: dict) -> tuple:
    return tuple(identity[f] for f in CONFIG_FIELDS)


def latest_per_config(points: list[dict]) -> list[dict]:
    """The live view's points: for each config, only its newest measurement. `points` are dicts
    carrying an `identity` (with `measured_date`) and a `point_id`; the rest is passed through.
    Ties on date are broken by point_id, so the choice is deterministic. Snapshots and Compare
    keep every measurement -- this filter is the live view's alone."""
    newest: dict[tuple, dict] = {}
    for p in points:
        k = config_key(p["identity"])
        cur = newest.get(k)
        if cur is None or _supersedes(p, cur):
            newest[k] = p
    return sorted(newest.values(), key=lambda p: p["point_id"])


def _supersedes(a: dict, b: dict) -> bool:
    """`a` is a later (or tie-break-higher) measurement of the same config than `b`."""
    ad, bd = a["identity"]["measured_date"], b["identity"]["measured_date"]
    if ad != bd:
        return ad > bd
    return a["point_id"] > b["point_id"]


def zero_scored_is_noop(decision: Decision, scored_count: int) -> Decision:
    """#15: "A run that would score zero points should no-op and keep the last good view." A
    night that planned to score or freeze but ended with nothing scorable becomes a no-op, so the
    dashboard never blanks out. A planned no-op or a pure age-out (which scores nothing by design,
    yet still has a non-empty live view from the cache) is unaffected."""
    if scored_count == 0 and decision.action not in (NOOP, AGE_OUT):
        return Decision(NOOP, reason=f"{decision.action} scored zero points; keeping the last good view")
    return decision
