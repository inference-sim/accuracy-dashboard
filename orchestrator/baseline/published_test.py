"""No published figure holds the accuracy of a held-out point unless a logged evaluation produced it (design D7;
docs/m2/evaluation-protocol.md, sections 4 and 6).

The development split's test and prospective points are evaluated only through the logged path: the evaluation is a
row of docs/m2/evaluation-log.md, and the report that carries the figures names the rows it was logged as. This module
checks the committed tree for that:

  - every row of the log is a well-formed row (date, full harness commit, the release evaluated, estimator, split,
    points, scored), and a release has one test evaluation, or the log's own note says why it has more;
  - every committed report that says it holds test figures (`test_evaluated` true, at its top or in its
    development split) names log rows (`evaluation`), and each of them is in the log;
  - every committed report that says it does not, and states its split counts, withholds every test, prospective and
    unknown point;
  - every row of the log is named by a committed report, so no evaluation is logged and then left unpublished, and no
    report is deleted to hide one.

    published_test.py [DOCS_DIR]      exit status 1 on any problem
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HEADER = "| Date | Commit | Release | Estimator | Split | Points | Scored |"
ROW = re.compile(r"^\| \d{4}-\d{2}-\d{2} \| [0-9a-f]{40} \| (v\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?|[0-9a-f]{40}) "
                 r"\| [^|]*\S[^|]* \| (test|prospective) \| \d+ \| \d+ \|$")
# A release the log holds more than one test evaluation of is a violation of the protocol unless the log says so,
# above its table, in one line per release: "- Repeated: <release>, <n> test evaluations: <why>". The count must be
# the log's own; a row is never deleted to hide a repeat.
REPEATED = re.compile(r"^- Repeated: (\S+), (\d+) test evaluations: \S")
HELD = ("test", "prospective", "unknown")


def log_rows(text: str) -> tuple[list[str], list[str]]:
    """(rows, problems) of the evaluation log."""
    lines = text.rstrip("\n").splitlines()
    try:
        h = lines.index(HEADER)
    except ValueError:
        return [], [f"the log has no table header {HEADER!r}"]
    if h + 1 >= len(lines) or not lines[h + 1].startswith("|---"):
        return [], ["the log's header has no separator line under it"]
    rows, problems = lines[h + 2:], []
    for r in rows:
        if not ROW.match(r):
            problems.append(f"the log row {r!r} is not a row of date, full commit, release, estimator, split, points, "
                            f"scored")
    tests = {}
    for r in rows:
        m = ROW.match(r)
        if m and m.group(2) == "test":
            tests[m.group(1)] = tests.get(m.group(1), 0) + 1
    noted = {m.group(1): int(m.group(2)) for m in map(REPEATED.match, lines[:h]) if m}
    for rel, n in sorted(tests.items()):
        if n > 1 and noted.get(rel) != n:
            problems.append(f"the log holds {n} test evaluations of {rel}; a release is evaluated once, and a repeat "
                            f"the log keeps needs its own line above the table ('- Repeated: {rel}, {n} test "
                            f"evaluations: why')")
    for rel in sorted(set(noted) - {r for r, n in tests.items() if n > 1}):
        problems.append(f"the log notes repeats of {rel} it does not hold")
    return rows, problems


def _reports(docs: Path):
    for p in sorted(docs.rglob("*.json")):
        try:
            doc = json.loads(p.read_text())
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(doc, dict):
            yield p, doc


def _evaluated(doc: dict) -> bool:
    return bool(doc.get("test_evaluated")) or any(
        bool((doc.get(side) or doc).get("development_split", {}).get("test_evaluated"))
        for side in ("before", "after", None) if side is None or isinstance(doc.get(side), dict))


def problems(docs: Path, log: Path) -> list[str]:
    rows, out = log_rows(log.read_text()) if log.is_file() else ([], [f"{log} does not exist"])
    logged = set(rows)
    named_all: set[str] = set()
    for p, doc in _reports(docs):
        rel = p.relative_to(docs)
        if _evaluated(doc):
            named = doc.get("evaluation") or []
            if not named:
                out.append(f"{rel} holds test figures and names no evaluation-log row")
            out += [f"{rel} names the evaluation {r!r}, which the log does not hold" for r in named if r not in logged]
            named_all.update(named)
        elif isinstance(doc.get("splits"), dict):
            for k in HELD:
                v = doc["splits"].get(k) or {}
                if v.get("withheld", 0) != v.get("points", 0):
                    out.append(f"{rel} shows the errors of {v.get('points', 0) - v.get('withheld', 0)} {k} points "
                               f"without a logged evaluation")
    out += [f"the log row {r!r} is named by no committed report" for r in rows if r not in named_all]
    return out


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    docs = Path(argv[0]) if argv else ROOT / "docs"
    found = problems(docs, docs / "m2" / "evaluation-log.md")
    for f in found:
        print(f, file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
