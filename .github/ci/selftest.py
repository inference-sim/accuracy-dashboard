#!/usr/bin/env python3
"""Pins which jobs run for sample change lists; prints the table. Run: python3 .github/ci/selftest.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from which_jobs import select  # noqa: E402

O, S, W = "orchestrator", "simulator", "web"
CASES = [
    ("README only", ["README.md"], set()),
    ("licence and gitignore", ["LICENSE", ".gitignore"], set()),
    ("docs page", ["docs/grades.md"], {O}),
    ("docs mockup image", ["docs/mockups/overview-v0.1.0.png"], set()),
    ("committed run contract", ["docs/m2/preliminary-after/contract/provenance.json"], {O, S}),
    ("harness file", ["harness/run.sh"], {O, S}),
    ("ingest file", ["orchestrator/ingest/score.py"], {O, S}),
    ("orchestrator test only", ["orchestrator/test_update_index.py"], {O, S}),
    ("web source", ["web/src/App.tsx"], {W}),
    ("web fixture", ["web/testdata/render-fixture.v3.summary.json"], {O, W}),
    ("schema", ["schemas/summary.v3.json"], {O, S}),
    ("committed snapshot", ["data/latest/summary.json"], {O, W}),
    ("state", ["state/last-run.json"], {O}),
    ("simulator pin", [".github/stack-pins.env"], {S}),
    ("python requirements", ["requirements-ci.txt"], {O, S}),
    ("another workflow", [".github/workflows/pages.yml"], {O}),
    ("this workflow", [".github/workflows/checks.yml"], {O, S, W}),
    ("the CI tools", [".github/ci/shards.py"], {O, S, W}),
    ("two areas", ["web/src/App.tsx", "harness/run.sh"], {O, S, W}),
    ("empty or unreadable list", [], {O, S, W}),
]


def main() -> int:
    bad = 0
    print(f"{'change':32} {'orchestrator':13} {'simulator':10} web")
    for name, files, want in CASES:
        got = {j for j, on in select(files).items() if on}
        mark = "" if got == want else f"   <-- expected {sorted(want)}"
        bad += got != want
        print(f"{name:32} {'run' if O in got else '-':13} {'run' if S in got else '-':10} {'run' if W in got else '-'}{mark}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
