"""Which committed contracts must be current, and which are frozen historical records (design X8).

A committed contract (a scoring run's results) is current when nothing that scores changed between the harness commit
that scored it and HEAD; a scorer change then means the run is made again (test_contracts_current.py). A contract
scored from a pull that is no longer held can never be made again, so it is a historical record instead: it is
listed, path by path, in docs/m2/historical-contracts.json, with the harness commit and the pull manifest it was scored
with and the reason. The list is checked here:

  - every entry names an existing contract directory, by its exact path (no pattern, no glob);
  - its harness commit and pull manifest SHA-256 are the contract's own (provenance.json), so a contract scored again
    cannot keep its exemption by accident;
  - an entry gives a reason.

`current(root)` is every committed contract that is not historical: the ones the currency gate holds to HEAD.
Current contracts come from the score-contracts workflow, which freezes the pull in GitHub Actions and keeps it as an
artifact, so a later scorer change can always score them again.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
LIST = Path("docs/m2/historical-contracts.json")
_PATTERN = set("*?[]")


class CurrencyError(ValueError):
    pass


def contracts(root: Path = ROOT) -> list[str]:
    """Every committed contract directory, as a repository-relative path: a directory holding provenance.json under
    docs/."""
    return sorted(str(p.parent.relative_to(root)) for p in (root / "docs").rglob("provenance.json")
                  if p.parent.name == "contract")


def historical(root: Path = ROOT, list_path: Path = LIST) -> dict[str, dict]:
    """The listed historical contracts, by path, each checked against the contract it names."""
    p = root / list_path
    if not p.is_file():
        return {}
    doc = json.loads(p.read_text())
    out, problems = {}, []
    for e in doc.get("historical") or []:
        path = str(e.get("path") or "")
        if not path or _PATTERN & set(path):
            problems.append(f"{path!r}: an entry names one contract directory by its path, never a pattern")
            continue
        prov = root / path / "provenance.json"
        if not prov.is_file():
            problems.append(f"{path}: no contract directory is there")
            continue
        got = json.loads(prov.read_text())
        for k in ("harness_commit", "pull_manifest_sha256"):
            if e.get(k) != got.get(k):
                problems.append(f"{path}: the entry's {k} {e.get(k)!r} is not the contract's {got.get(k)!r}")
        if not str(e.get("reason") or "").strip():
            problems.append(f"{path}: the entry gives no reason")
        if path in out:
            problems.append(f"{path}: listed twice")
        out[path] = e
    if problems:
        raise CurrencyError("; ".join(problems))
    return out


def current(root: Path = ROOT, list_path: Path = LIST) -> list[str]:
    """The committed contracts the currency gate holds to HEAD: every one that is not historical."""
    hist = historical(root, list_path)
    return [c for c in contracts(root) if c not in hist]
