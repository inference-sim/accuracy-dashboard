"""The required check `gate-rule / rule` comes from trusted base code, never from the pull request it judges.

A `pull_request` workflow runs the pull request's own copy of the file, so a later pull request could replace it with
a job of the same name that exits 0 and the base checker would never run. A `pull_request_target` workflow is read from
the base branch; it is safe only while it never checks out or runs the pull request's code. This lint holds both.

Run: python3 -m pytest orchestrator/gate/test_gate_workflow.py
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "gate-rule.yml"
BASE_REF = re.compile(r"\$\{\{\s*github\.event\.pull_request\.base\.(ref|sha)\s*\}\}")


def code(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


def block(text: str, key: str, indent: int = 0) -> list[str]:
    """The lines indented deeper than `key:` at `indent`, up to the next line at that indent."""
    lines, out, on = text.splitlines(), [], False
    for l in lines:
        if on:
            if l.strip() and len(l) - len(l.lstrip()) <= indent:
                break
            out.append(l)
        elif re.fullmatch(r" " * indent + re.escape(key) + r":\s*", l):
            on = True
    return out


def violations(text: str) -> list[str]:
    """Every way the workflow could run the pull request's code or be replaced by it; empty when it cannot."""
    body, bad = code(text), []
    if not re.search(r"^name: gate-rule\s*$", body, re.M) or not re.search(r"^jobs:\n  rule:\n", body, re.M):
        bad.append("the check name must stay `gate-rule / rule`")
    triggers = [m.group(1) for l in block(body, "on") if (m := re.fullmatch(r"  ([\w_]+):.*", l))]
    if triggers != ["pull_request_target"]:
        bad.append(f"the only trigger must be pull_request_target, not {triggers}")
    perms = {m.group(1): m.group(2) for l in block(body, "permissions") if (m := re.fullmatch(r"  ([\w-]+): (\w+)\s*", l))}
    if perms != {"contents": "read", "pull-requests": "read"} or len(re.findall(r"^\s*permissions:", body, re.M)) != 1:
        bad.append(f"permissions must be exactly contents: read and pull-requests: read, once, at the top: {perms}")
    if re.search(r"secrets\.", body):
        bad.append("the job must hold no secret")
    checkouts = [s for s in re.split(r"\n      - ", body) if "actions/checkout" in s]
    if len(checkouts) != 1 or len(re.findall(r"actions/checkout", body)) != 1:
        bad.append("exactly one checkout, of the base branch")
    for s in checkouts:
        ref = re.search(r"^\s*ref: (.*)$", s, re.M)
        if not ref or not BASE_REF.fullmatch(ref.group(1).strip()):
            bad.append("the checkout's ref must be the base branch's ref or sha")
        if not re.search(r"^\s*persist-credentials: false\s*$", s, re.M):
            bad.append("the checkout must set persist-credentials: false")
        if re.search(r"^\s*(repository|token|submodules|fetch-depth):", s, re.M):
            bad.append("the checkout takes no repository, token, submodules or depth option")
    if re.search(r"^\s*ref:.*(head|merge|refs/pull|github\.sha|github\.ref)", body, re.M):
        bad.append("a checkout of the pull request's head, merge ref or sha")
    if re.search(r"\bgit\b[^\n]*\b(checkout|switch|fetch|pull|clone|worktree|merge|cherry-pick|apply|am)\b", body):
        bad.append("no git command may bring the pull request's code into the checkout")
    for l in body.splitlines():
        for m in re.finditer(r"\b(python3?|bash)\s+([^\s\"'$]+)", l):
            if m.group(2) not in {"-m", "--version", "-"} and not m.group(2).startswith("base/") and not m.group(2).startswith("-"):
                bad.append(f"runs {m.group(2)}, which is not under the base checkout (base/)")
    return bad


def test_the_committed_workflow_is_a_pull_request_target_workflow_that_never_runs_the_pull_request():
    assert violations(WORKFLOW.read_text()) == []


def test_the_workflow_reads_the_pull_request_through_the_api_as_data():
    body = code(WORKFLOW.read_text())
    for needle in ("gh api", "/pulls/${PR_NUMBER}", "/files", "/compare/", "/tarball/", "--root \"$data/head\"", "--base-root base"):
        assert needle in body, needle
    assert "--root head" not in body and "path: head" not in body


@pytest.mark.parametrize("name,edit", [
    ("pull_request trigger", lambda t: t.replace("pull_request_target:", "pull_request:")),
    ("both triggers", lambda t: t.replace("  pull_request_target:", "  pull_request:\n    types: [opened]\n  pull_request_target:")),
    ("push trigger", lambda t: t.replace("  pull_request_target:", "  push:\n  pull_request_target:")),
    ("head sha checkout", lambda t: t.replace("github.event.pull_request.base.ref", "github.event.pull_request.head.sha")),
    ("head ref checkout", lambda t: t.replace("github.event.pull_request.base.ref", "github.event.pull_request.head.ref")),
    ("merge ref checkout", lambda t: t.replace("${{ github.event.pull_request.base.ref }}", "refs/pull/${{ github.event.pull_request.number }}/merge")),
    ("no ref (default checkout)", lambda t: t.replace("          ref: ${{ github.event.pull_request.base.ref }}\n", "")),
    ("a second checkout of the head", lambda t: t.replace("      - uses: actions/setup-python", "      - uses: actions/checkout@abc\n        with:\n          ref: ${{ github.event.pull_request.head.sha }}\n          path: head\n          persist-credentials: false\n      - uses: actions/setup-python")),
    ("a fork repository checkout", lambda t: t.replace("          path: base\n", "          path: base\n          repository: ${{ github.event.pull_request.head.repo.full_name }}\n")),
    ("credentials persisted", lambda t: t.replace("persist-credentials: false", "persist-credentials: true")),
    ("write permission", lambda t: t.replace("contents: read", "contents: write")),
    ("extra permission", lambda t: t.replace("  pull-requests: read\n", "  pull-requests: read\n  id-token: write\n")),
    ("a secret", lambda t: t.replace("GH_TOKEN: ${{ github.token }}", "GH_TOKEN: ${{ secrets.LEDGER_SEED }}")),
    ("git checkout of the head", lambda t: t.replace("set -euo pipefail\n", "set -euo pipefail\n          git -C base fetch origin pull/1/head && git -C base checkout FETCH_HEAD\n", 1)),
    ("the head's checker", lambda t: t.replace("python3 base/orchestrator/gate/gate.py", "python3 head/orchestrator/gate/gate.py")),
    ("another job name", lambda t: t.replace("jobs:\n  rule:", "jobs:\n  rule2:")),
    ("another workflow name", lambda t: t.replace("name: gate-rule", "name: gate-rule-2")),
])
def test_a_workflow_that_the_pull_request_could_replace_or_that_runs_its_code_is_refused(name, edit):
    original = WORKFLOW.read_text()
    mutated = edit(original)
    assert mutated != original, name
    assert violations(mutated), name


def test_the_rule_runs_only_when_a_reviewer_labels_the_pull_request():
    body = code(WORKFLOW.read_text())
    assert "if: contains(github.event.pull_request.labels.*.name, 'gate-rule')" in body
    assert "labeled" in "".join(block(body, "on"))
    # an unrelated label must not cancel a rule run in progress
    assert "github.event.label.name != 'gate-rule' && github.run_id" in body
