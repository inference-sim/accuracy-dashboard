"""An edit of a pull request's title or body starts no CI run.

checks.yml does not list `edited` among its pull_request types, so an edit starts no run and the checks of the last
push keep their names and results. No job name, condition or concurrency group reads the event action. A retarget (an
edited event that changes the base) is run through ci-retarget.yml, which dispatches checks.yml on the head branch.

Run: python3 -m pytest orchestrator/test_ci_edit.py
"""
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def load(name):
    return yaml.safe_load((WORKFLOWS / name).read_text())


def test_checks_does_not_run_on_an_edit_of_the_pull_request():
    types = load("checks.yml")[True]["pull_request"]["types"]
    assert "edited" not in types
    assert {"opened", "synchronize", "reopened"} <= set(types)


def test_no_job_name_condition_or_group_reads_the_event_action():
    doc = load("checks.yml")
    text = str(doc["concurrency"]) + "".join(
        f"{job.get('name', '')}{job.get('if', '')}" for job in doc["jobs"].values())
    assert "github.event.action" not in text and "changes.base" not in text


def test_the_required_job_names_are_the_same_for_every_event():
    jobs = load("checks.yml")["jobs"]
    assert [jobs[j]["name"] for j in ("orchestrator", "web", "grep-clean", "gate")] == [
        "orchestrator", "web", "grep-clean", "gate"]


def test_a_retarget_dispatches_checks_and_a_text_edit_does_nothing():
    doc = load("ci-retarget.yml")
    assert doc[True]["pull_request"]["types"] == ["edited"]
    job = doc["jobs"]["dispatch-checks"]
    assert "github.event.changes.base" in job["if"]
    assert "gh workflow run checks.yml" in job["steps"][0]["run"]
