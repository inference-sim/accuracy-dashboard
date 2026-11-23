"""An edit of a pull request's title or body costs no CI run and lists no check.

checks.yml does not listen for `edited`. A job skipped by its `if` shows its `name:` unevaluated, so any
edit-time skip would list raw `${{ }}` templates on the pull request; a workflow that never starts lists nothing,
and the required checks of the last push keep their names and results.

Run: python3 -m pytest orchestrator/test_ci_edit.py
"""
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "checks.yml"


def workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def test_the_workflow_does_not_run_for_an_edit_of_the_title_or_body():
    types = workflow()[True]["pull_request"]["types"]
    assert "edited" not in types and "synchronize" in types


def test_no_job_name_or_condition_reads_the_edit_event():
    for name, job in workflow()["jobs"].items():
        assert "${{" not in job["name"] or "matrix." in job["name"], name
        assert "edited" not in str(job.get("if", "")), name


def test_the_required_job_names_are_plain():
    jobs = workflow()["jobs"]
    assert [jobs[j]["name"] for j in ("orchestrator", "web", "grep-clean", "gate")] == [
        "orchestrator", "web", "grep-clean", "gate"]
