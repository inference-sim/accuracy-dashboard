"""Commit distance (design §11.3): how far the commit a run measured is from the commit the simulator models.

Two things are asked of a pair of upstream commits (run, scored):

  changed(run, scored)  the ported functions, constants, surface items and kernel implementations that differ
                        between them, or None when no diff is published for that pair (the point is then G4). The
                        callable `grade.grade_by_commit` takes as `distance`.
  record(run, scored)   the pair of counts of commits from the merge base to each commit, and the tags between them,
                        read with git from a checkout of the engine's source; None without a checkout.

The diff comes from an upgrade report, the JSON that inference-sim's engines/upgrade/upgrade_report.py prints for one
engine upgrade (`from.commit` to `to.commit`). The dashboard reads that file; it imports nothing from the engine
repositories, so a report is the whole interface and the dashboard has no dependency link on them. A report names the
changes of one pair; a run on any other pair has no published diff.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

HEX40 = re.compile(r"^[0-9a-f]{40}$")


class DistanceError(ValueError):
    pass


# A scored point's commit distance in one word (design §11.3), so a slice or a funnel can cut by it. It is the reason
# of the point's grade, not a threshold: the plan sets no commit-count bound beyond which a point stops being graded.
SAME = "same"                              # the run measured the commit the simulator models (G1 or G2)
NO_PORTED_CHANGE = "no_ported_change"      # another commit, and nothing the engine ports differs (G3)
PORTED_CHANGE = "ported_change"            # another commit, and some ported function, field or kernel differs (G4)
UNPUBLISHED = "unpublished"                # another commit, and no diff is published for the pair (G4)
STATES = (SAME, NO_PORTED_CHANGE, PORTED_CHANGE, UNPUBLISHED, "custom_build", "commit_unresolvable", "commit_conflict")


def label(run: str | None, scored: str, changed: list[str] | None, why: str | None = None) -> dict:
    """What the fidelity record states of a point's commit distance, from the diff the provider returned for the pair
    (`changed`: None when none is published). `why` is a build the scorer could not place by commit (custom,
    unresolvable or conflicting), which is its own state; the ported changes are then not asked."""
    rec = {"run_commit": run, "scored_commit": scored}
    if why in STATES:
        return {**rec, "state": why}
    if run == scored:
        return {**rec, "state": SAME}
    if changed is None:
        return {**rec, "state": UNPUBLISHED}
    return {**rec, "state": PORTED_CHANGE if changed else NO_PORTED_CHANGE, "ported_changes": len(changed)}


def changes(report: dict) -> list[str] | None:
    """What one upgrade report says differs between its two commits, as sorted `kind:name` strings; [] when nothing
    §11.3 names differs. None when the report could not derive its code paths (the diff is then unpublished)."""
    paths = (report.get("source") or {}).get("code_paths")
    if isinstance(paths, dict):
        return None
    out = []
    for i in (report.get("surface") or {}).get("added") or []:
        out.append(f"surface:{i['id']}")
    for i in (report.get("surface") or {}).get("removed") or []:
        out.append(f"surface:{i['id']}")
    fields = report.get("fields") or {}
    for k in ("added", "removed", "status_changed"):
        out += [f"field:{f['name']}" for f in fields.get(k) or []]
    source = report.get("source") or {}
    out += [f"file:{f['upstream']}" for f in source.get("ported_files_changed") or []]
    for p in paths or []:
        out += [f"function:{p['path']}:{f}" for k in ("changed", "added", "removed") for f in p.get(k) or []]
    impls = source.get("kernel_impls") or {}
    for k in ("added", "removed", "changed"):
        out += [f"kernel_impl:{'/'.join(map(str, key))}" for key in impls.get(k) or []]
    return sorted(set(out))


def _commit(report: dict, side: str) -> str:
    c = (report.get(side) or {}).get("commit")
    if not isinstance(c, str) or not HEX40.match(c):
        raise DistanceError(f"an upgrade report's {side}.commit is {c!r}, not a 40-digit lowercase hex commit")
    return c


class Distance:
    """The commit-distance provider: upgrade reports for the diffs, an engine checkout for the counts."""

    def __init__(self, reports: list[dict] = (), checkout: Path | None = None):
        self.diffs: dict[frozenset, list[str] | None] = {}
        for r in reports:
            self.diffs[frozenset((_commit(r, "from"), _commit(r, "to")))] = changes(r)
        self.checkout = Path(checkout) if checkout else None

    @classmethod
    def load(cls, report_paths=(), checkout=None) -> "Distance":
        reports = []
        for p in report_paths or ():
            try:
                reports.append(json.loads(Path(p).read_text()))
            except (OSError, ValueError) as e:
                raise DistanceError(f"upgrade report {p}: {e}") from None
        return cls(reports, Path(checkout).resolve() if checkout else None)

    def __call__(self, run: str, scored: str) -> list[str] | None:
        return self.diffs.get(frozenset((run, scored)))

    def _git(self, *args: str) -> str | None:
        r = subprocess.run(["git", "-C", str(self.checkout), *args], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None

    def record(self, run: str, scored: str) -> dict | None:
        """{"run_commit", "scored_commit", "merge_base", "run_commits", "scored_commits", "tags"}: the counts of
        commits from the merge base to the run's and to the scored commit, and the tags in either range. None when no
        checkout was given or it lacks one of the commits."""
        if self.checkout is None:
            return None
        base = self._git("merge-base", run, scored)
        if not base:
            return None
        n = [self._git("rev-list", "--count", f"{base}..{c}") for c in (run, scored)]
        t = [self._git("tag", "--merged", a, "--no-merged", b) for a, b in ((run, scored), (scored, run))]
        if None in n or None in t:
            return None
        return {"run_commit": run, "scored_commit": scored, "merge_base": base,
                "run_commits": int(n[0]), "scored_commits": int(n[1]),
                "tags": sorted({x for s in t for x in s.split()})}
