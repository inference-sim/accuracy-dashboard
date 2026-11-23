"""The rule that every accuracy change lands through the gate (Table DC "Gate as the path").

A pull request body states, on a line of its own, one of:

    Gate: pre-registration <id>
    Gate: not an accuracy change - <reason>

A change to a path in state/gate/accuracy-paths.json moves published accuracy and must cite a
pre-registration, which must already be on the base branch: it is committed first, before any held-out
datum is read, and a pre-registration is never edited or deleted after it is committed. Pre-registrations
are checked to be well formed wherever they are added.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import budget
import prereg as pr
import surface
from surface import is_test

STATEMENT = re.compile(
    r"^[ \t]*Gate:[ \t]*(?:pre-registration[ \t]+(?P<id>[a-z0-9][a-z0-9.-]{2,63})|"
    r"not an accuracy change[ \t]*[-:][ \t]*(?P<why>\S.{8,}\S))[ \t]*$", re.M | re.I)
PATHS = Path("state") / "gate" / "accuracy-paths.json"
EXCEPTIONS = Path("state") / "gate" / "exceptions.json"
HEX40 = re.compile(r"[0-9a-f]{40}")


def accuracy_paths(root: Path) -> list[str]:
    doc = json.loads((Path(root) / PATHS).read_text())
    if set(doc) != {"kind", "paths"} or doc["kind"] != "AccuracyPaths" or not all(isinstance(p, str) and p for p in doc["paths"]):
        raise ValueError(f"{PATHS} is not an AccuracyPaths document")
    return doc["paths"]


def exceptions(root) -> list[dict]:
    """The maintainer exceptions on the branch `root` checks out: a pull request and the one head it covers."""
    path = Path(root) / EXCEPTIONS
    if not path.exists():
        return []
    doc = json.loads(path.read_text())
    ok = isinstance(doc, dict) and set(doc) == {"kind", "exceptions"} and doc["kind"] == "GateExceptions" and isinstance(doc["exceptions"], list)
    ok = ok and all(isinstance(e, dict) and set(e) == {"pull_request", "head", "reason"} and type(e["pull_request"]) is int
                    and isinstance(e["head"], str) and HEX40.fullmatch(e["head"]) and isinstance(e["reason"], str) and len(e["reason"]) >= 10
                    for e in doc["exceptions"])
    if not ok:
        raise ValueError(f"{EXCEPTIONS} is not a GateExceptions document of {{pull_request, head, reason}} entries")
    return doc["exceptions"]


def excepted(root, pull_request: int, head: str) -> bool:
    return any(e["pull_request"] == pull_request and e["head"] == head for e in exceptions(root))


def parse_changes(text: str) -> list[tuple[str, str]]:
    """`git diff --name-status` output: a status letter and a path (a rename names both paths)."""
    out = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0]:
            for p in parts[1:]:
                out.append((parts[0][0], p))
    return out


def touches(path: str, prefixes: list[str]) -> bool:
    """A test module is never scoring code (no scoring module is one: test_gate_surface.py); a data file under a directory is."""
    return not is_test(path) and any(path.startswith(p) if p.endswith("/") else path == p for p in prefixes)


@dataclass(frozen=True)
class Landing:
    """The pull request as the trusted job derives it from git: its number, its head commit, the merge base with the
    base branch, and a checkout of that merge base (the tree the candidate's change is judged against)."""
    number: int
    head: str
    merge_base: str
    merge_base_root: Path


def evaluation_errors(base_root: Path, pre: dict, landing: Landing) -> list[str]:
    """A cited pre-registration must have been evaluated, and passed, on this head over this merge base: the base
    branch's ledger records the gate's evaluation (its verdict, never a claim in the pull request)."""
    try:
        doc = budget.load(base_root / budget.PATH)
    except (budget.Refused, OSError, ValueError) as e:
        return [f"{budget.PATH.as_posix()} on the base branch cannot be read ({e}); an evaluation of {pre['id']} cannot be checked"]
    digest = pr.digest(pre)
    for part in doc["partitions"].values():
        for e in part["evaluations"]:
            if (e["preregistration"], e["preregistration_sha256"], e["candidate"], e["base"]) == (pre["id"], digest, landing.head, landing.merge_base):
                if e["verdict"] == "pass":
                    return []
                return [f"the whole-run gate evaluated {pre['id']} on this head and returned {e['verdict']}; only a pass lands, "
                        f"or a maintainer exception in {EXCEPTIONS.as_posix()}"]
    return [f"no evaluation of {pre['id']} on head {landing.head[:12]} over merge base {landing.merge_base[:12]} is recorded in "
            f"{budget.PATH.as_posix()} on the base branch; run the whole-run gate and commit its ledger.json to main first"]


def check_pr(body: str, changes: list[tuple[str, str]], root, base_root, landing: Landing) -> list[str]:
    """Every way the pull request breaks the rule; empty when it follows it. `root` is the checkout of the pull
    request's head; `base_root` the base branch's (the list of accuracy paths, the cited pre-registration and the
    maintainer exceptions are read from it, so a pull request cannot shorten the list it is judged by or grant itself
    an exception), and defaults to `root`."""
    root, errs = Path(root), []
    base_root = Path(base_root) if base_root is not None else root
    found = list(STATEMENT.finditer(body or ""))
    if len(found) != 1:
        errs.append("the body must hold exactly one line 'Gate: pre-registration <id>' or "
                    "'Gate: not an accuracy change - <reason>' (a reason of at least 10 characters)")
        stated = None
    else:
        stated = found[0]
    waived = excepted(base_root, landing.number, landing.head)
    if not waived:
        diff = surface.differing(landing.merge_base_root, root, accuracy_paths(base_root))
        if diff:
            errs.append("the change alters the scoring surface (" + ", ".join(diff[:5]) + (" and more" if len(diff) > 5 else "")
                        + "): the candidate run would score with its own code, not main's; it needs a maintainer exception in "
                        + EXCEPTIONS.as_posix() + " on the base branch")
    pre_dir = pr.DIR.as_posix() + "/"
    for status, path in changes:
        if path == EXCEPTIONS.as_posix() and status != "D":
            try:
                exceptions(root)
            except (ValueError, OSError):
                errs.append(f"{path} is not a GateExceptions document of {{pull_request, head, reason}} entries")
        if path.startswith(pre_dir):
            if status != "A":
                errs.append(f"{path}: a pre-registration is never edited, renamed or deleted after it is committed")
            elif path.endswith(".json") and "/" not in path[len(pre_dir):]:
                try:
                    pr.load(root / path)
                except pr.PreRegistrationError as e:
                    errs.append(str(e))
            else:
                errs.append(f"{path}: only <id>.json files live in {pre_dir}")
    moves = sorted({p for s, p in changes if touches(p, accuracy_paths(base_root))})
    cited = stated.group("id") if stated is not None else None
    if moves and stated is not None and cited is None:
        errs.append("the change touches " + ", ".join(moves[:5]) + (" and more" if len(moves) > 5 else "")
                    + ", which moves accuracy; it must cite a pre-registration")
    if cited is not None:
        added = {p for s, p in changes if s in "AMDR"}
        path = pr.DIR / f"{cited}.json"
        if path.as_posix() in added:
            errs.append(f"pre-registration {cited} is added by this pull request; it must be on the base branch first")
        else:
            try:
                pre = pr.load(base_root / path)
            except (pr.PreRegistrationError, OSError):
                errs.append(f"pre-registration {cited} is not on the base branch")
            else:
                if not waived:
                    errs += evaluation_errors(base_root, pre, landing)
    return errs
