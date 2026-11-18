"""An edit of a pull request's title or body costs no CI run (the pattern of blis-substrate's ci-light.yml).

The workflow's own expressions are evaluated here for the three kinds of event that reach checks.yml: a push to the
branch (action synchronize), an edit of the title or body (action edited, no base change), and an edit that moves the
base (action edited, changes.base set). An edit of the body must have its own concurrency group, so it cannot cancel the
run of the last push, and every job must be skipped with " (edit)" in its name, so the required checks of the last push
keep their names and results. A base change re-runs everything.

Run: python3 -m pytest orchestrator/test_ci_edit.py
"""
import re
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "checks.yml"


class Ctx:
    """The pieces of the github context the workflow's expressions read."""
    def __init__(self, action, base_changed=False):
        self.action = action
        self.base = {"ref": {"from": "main"}} if base_changed else None


def evaluate(expr: str, ctx: Ctx, needs_true: bool = True):
    """The workflow expression `${{ ... }}` (or a string holding several) evaluated for ctx: only the operators and
    names checks.yml uses (&&, ||, !, ==, !=, string literals, always(), needs.*.outputs.*, the github.event fields)."""
    def one(m):
        e = m.group(1)
        e = e.replace("&&", " and ").replace("||", " or ")
        e = re.sub(r"!(?!=)", " not ", e)
        e = e.replace("github.event.action", "ctx.action").replace("github.event.changes.base", "ctx.base")
        e = e.replace("always()", "True")
        e = re.sub(r"needs\.[\w-]+\.outputs\.[\w-]+ == 'true'", "NEEDS", e)
        e = re.sub(r"\bmatrix\.shard\b", "'shard'", e)
        e = re.sub(r"github\.(workflow|ref)", "'x'", e)
        return str(eval(e, {"ctx": ctx, "NEEDS": needs_true, "True": True}))
    out = re.sub(r"\$\{\{(.*?)\}\}", one, expr)
    return out


def workflow():
    doc = yaml.safe_load(WORKFLOW.read_text())
    return doc


PUSH, EDIT, BASE = Ctx("synchronize"), Ctx("edited"), Ctx("edited", base_changed=True)


def test_an_edit_of_the_body_runs_in_its_own_group_so_it_cannot_cancel_the_run_of_the_last_push():
    group = workflow()["concurrency"]["group"]
    push, edit, base = evaluate(group, PUSH), evaluate(group, EDIT), evaluate(group, BASE)
    assert edit == push + "-edit" and base == push


def test_every_job_is_skipped_on_an_edit_and_runs_otherwise():
    for name, job in workflow()["jobs"].items():
        cond = job["if"]
        cond = cond if isinstance(cond, str) else str(cond)
        truthy = lambda c: evaluate(c, ctx) not in ("False", "None", "")  # noqa: E731
        for ctx, runs, why in ((EDIT, False, "runs on an edit of the body"), (PUSH, True, "is skipped on a push"),
                               (BASE, True, "is skipped when the base moves")):
            assert truthy(cond) == runs, f"{name} {why}"


def test_a_job_skipped_for_an_edit_says_so_in_its_name_and_keeps_its_name_for_a_push():
    for name, job in workflow()["jobs"].items():
        n = job["name"]
        assert evaluate(n, EDIT).endswith(" (edit)"), name
        assert " (edit)" not in evaluate(n, PUSH), name
        assert evaluate(n, EDIT).removesuffix(" (edit)") == evaluate(n, PUSH), name


def test_the_workflow_listens_for_edits_and_its_required_job_names_are_unchanged_for_a_push():
    types = workflow()[True]["pull_request"]["types"]
    assert "edited" in types and "synchronize" in types
    jobs = workflow()["jobs"]
    assert [evaluate(jobs[j]["name"], PUSH) for j in ("orchestrator", "web", "grep-clean", "gate")] == [
        "orchestrator", "web", "grep-clean", "gate"]
