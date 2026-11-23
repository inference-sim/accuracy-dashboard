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
from pathlib import Path, PurePosixPath

import prereg as pr

STATEMENT = re.compile(
    r"^[ \t]*Gate:[ \t]*(?:pre-registration[ \t]+(?P<id>[a-z0-9][a-z0-9.-]{2,63})|"
    r"not an accuracy change[ \t]*[-:][ \t]*(?P<why>\S.{8,}\S))[ \t]*$", re.M | re.I)
PATHS = Path("state") / "gate" / "accuracy-paths.json"


def accuracy_paths(root: Path) -> list[str]:
    doc = json.loads((Path(root) / PATHS).read_text())
    if set(doc) != {"kind", "paths"} or doc["kind"] != "AccuracyPaths" or not all(isinstance(p, str) and p for p in doc["paths"]):
        raise ValueError(f"{PATHS} is not an AccuracyPaths document")
    return doc["paths"]


def parse_changes(text: str) -> list[tuple[str, str]]:
    """`git diff --name-status` output: a status letter and a path (a rename names both paths)."""
    out = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0]:
            for p in parts[1:]:
                out.append((parts[0][0], p))
    return out


def is_test(path: str) -> bool:
    name = PurePosixPath(path).name
    return name.startswith("test_") and name.endswith(".py")


def touches(path: str, prefixes: list[str]) -> bool:
    """A test module is never scoring code (no scoring module is one: test_gate_surface.py); a data file under a directory is."""
    return not is_test(path) and any(path.startswith(p) if p.endswith("/") else path == p for p in prefixes)


def check_pr(body: str, changes: list[tuple[str, str]], root, base_root=None) -> list[str]:
    """Every way the pull request breaks the rule; empty when it follows it. `root` is the checkout of the pull
    request's head; `base_root` the base branch's (the list of accuracy paths and the cited pre-registration are read
    from it, so a pull request cannot shorten the list it is judged by), and defaults to `root`."""
    root, errs = Path(root), []
    base_root = Path(base_root) if base_root is not None else root
    found = list(STATEMENT.finditer(body or ""))
    if len(found) != 1:
        errs.append("the body must hold exactly one line 'Gate: pre-registration <id>' or "
                    "'Gate: not an accuracy change - <reason>' (a reason of at least 10 characters)")
        stated = None
    else:
        stated = found[0]
    pre_dir = pr.DIR.as_posix() + "/"
    for status, path in changes:
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
                pr.load(base_root / path)
            except (pr.PreRegistrationError, OSError):
                errs.append(f"pre-registration {cited} is not on the base branch")
    return errs
