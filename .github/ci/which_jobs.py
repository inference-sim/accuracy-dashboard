#!/usr/bin/env python3
"""Which checks a change needs, from the paths it changes.

    which_jobs.py FILE...        print `orchestrator=true|false`, `simulator=...`, `web=...` for the changed files
    which_jobs.py --all          every job (push to the default branch, manual runs, or an unreadable diff)

Each job runs when a changed path is one the job reads; the lists below say what each job reads. A path
that no list names runs no job (the README, the licence). A change to this directory or to checks.yml runs
every job, since it changes how they run. Data files under .github/ are not shared: stack-pins.env is read
by the simulator job only.
"""
from __future__ import annotations

import sys

# Every job reads these.
EVERYTHING = (".github/ci/", ".github/workflows/checks.yml")

# What each job reads. A prefix ending in "/" is a directory; anything else is one file.
READS = {
    # The Python suite: the code, the harness, the schemas, the committed data and state, the web fixtures the
    # builders rebuild, the generated documents (test_docs and the grade page read every docs/*.md), and every
    # workflow (test_run_sh pins their actions; the boundary lint scans them; test_stack reads api-nightly.yml).
    "orchestrator": ("orchestrator/", "harness/", "schemas/", "state/", "data/", "docs/", "web/testdata/",
                     "requirements-ci.txt", ".github/workflows/"),
    # The tests that simulate: the code they run, the harness, the schemas, the committed contracts they load, the
    # Python pins, and the upstream pins (.github/stack-pins.env, which no other job reads).
    "simulator": ("orchestrator/", "harness/", "schemas/", "requirements-ci.txt", ".github/stack-pins.env"),
    # The web app, its fixtures (web/testdata), and the committed snapshot the v1 smoke serves.
    "web": ("web/", "data/"),
}
# Under a read directory, these are not read.
IGNORED = ("docs/mockups/", "docs/screenshots/")

def reads(job: str, path: str) -> bool:
    if path.startswith(EVERYTHING):
        return True
    if path.startswith(IGNORED):
        return False
    if any(path.startswith(p) if p.endswith("/") else path == p for p in READS[job]):
        return True
    return job == "simulator" and path.startswith("docs/m2/") and "contract" in path.split("/")[3:4]


def select(files: list[str] | None) -> dict[str, bool]:
    """files None means everything; an empty list is treated as unreadable, so it also means everything."""
    if not files:
        return {job: True for job in READS}
    return {job: any(reads(job, f) for f in files) for job in READS}


def main(argv: list[str]) -> int:
    got = select(None if argv == ["--all"] else argv)
    for job, on in got.items():
        print(f"{job}={'true' if on else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
