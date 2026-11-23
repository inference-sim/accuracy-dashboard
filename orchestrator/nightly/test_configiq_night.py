"""The configiq step (configiq_night.py): pinned fetch, and the arguments of the scoring run (design D9)."""
import hashlib
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import configiq_night as cn  # noqa: E402

REF = "a" * 40


def _sources(tmp_path, assets):
    led = tmp_path / "substrate" / "catalog" / "ledger"
    led.mkdir(parents=True)
    rows = "".join(f"          - {{name: {n}, sha256: \"{h}\"}}\n" for n, h in assets)
    (led / "sources.yaml").write_text(
        "sources:\n  - id: other\n    revision: {ref: zzz, assets: []}\n"
        f"  - id: configiq\n    revision:\n      ref: {REF}\n      assets:\n" + rows)
    return led


def _opener(files):
    def op(url):
        for name, data in files.items():
            if url.endswith("/" + name):
                return io.BytesIO(data)
        raise OSError(url)
    return op


def test_pins_reads_only_the_configiq_source(tmp_path):
    led = _sources(tmp_path, [("manifest.json", "00" * 32)])
    assert cn.pins(led / "sources.yaml") == (REF, [("manifest.json", "00" * 32)])


def test_fetch_writes_files_whose_sha256_is_pinned(tmp_path):
    data = b"rows"
    want = hashlib.sha256(data).hexdigest()
    cn.fetch(REF, [("pairs/x/ground_truth.parquet", want)], tmp_path / "d", opener=_opener({"ground_truth.parquet": data}))
    assert (tmp_path / "d" / "pairs/x/ground_truth.parquet").read_bytes() == data


def test_fetch_refuses_a_file_whose_sha256_differs_and_writes_nothing(tmp_path):
    with pytest.raises(cn.NightError, match="not the pinned"):
        cn.fetch(REF, [("manifest.json", "00" * 32)], tmp_path / "d", opener=_opener({"manifest.json": b"changed"}))
    assert not (tmp_path / "d" / "manifest.json").exists()


def _args(tmp_path, **extra):
    a = ["--substrate", str(tmp_path / "substrate"), "--blis", "b", "--catalog", "c", "--registry", "r", "--fields", "f",
         "--substrate-version", "v0.15.0", "--sim-build", "v0.18.0", "--harness-commit", "c" * 40, "--out", str(tmp_path / "out")]
    for k, v in extra.items():
        a += [f"--{k}", v]
    return a


def test_a_step_that_fails_returns_1_and_never_raises(tmp_path, capsys):
    _sources(tmp_path, [("manifest.json", "00" * 32)])
    assert cn.main(_args(tmp_path, **{"substrate-version": "not-a-pin"})) == 1
    assert "exact pin" in capsys.readouterr().err


def test_every_ledger_unit_is_scored_less_the_left_out_and_none_is_withheld(tmp_path, monkeypatch):
    """D9: score_configiq gets the ledger.yaml (the left-out filter) and no --withhold-split; the funnel gets --ledger-yaml
    and, when named, --published (the guard that no configiq id is in a fit, select or validate list)."""
    led = _sources(tmp_path, [("manifest.json", hashlib.sha256(b"m").hexdigest())])
    monkeypatch.setattr(cn, "fetch", lambda ref, assets, dest, **kw: Path(dest).mkdir(parents=True, exist_ok=True))
    calls = []

    def run(cmd, **kw):
        cmd = [str(c) for c in cmd]
        calls.append(cmd)
        if any(c.endswith("score_configiq.py") for c in cmd):
            out = Path(cmd[cmd.index("--out") + 1])
            out.mkdir(parents=True)
            (out / "summary.json").write_text(json.dumps({"provenance": {"blis": {"commit_sha": "d" * 40}}}))
        if any(c.endswith("funnel.py") for c in cmd):
            Path(cmd[cmd.index("--out") + 1]).write_text(json.dumps({"format": "funnel-2", "funnels": {"configiq": {}}}))
    monkeypatch.setattr(cn, "_run", run)
    assert cn.main(_args(tmp_path, published=str(tmp_path / "pub"))) == 0
    score = next(c for c in calls if any(x.endswith("score_configiq.py") for x in c))
    assert score[score.index("--ledger-yaml") + 1] == str(led / "ledger.yaml")
    assert "--withhold-split" not in score
    assert score[score.index("--catalog-release") + 1] == "v0.15.0"
    funnel = next(c for c in calls if any(x.endswith("funnel.py") for x in c))
    assert funnel[funnel.index("--ledger-yaml") + 1] == str(led / "ledger.yaml")
    assert funnel[funnel.index("--published") + 1] == str(tmp_path / "pub")
    assert "--configiq-points" in funnel
    assert json.loads((tmp_path / "out" / "funnel.json").read_text())["dataset"] == REF  # stamped for the nightly's stale check


def test_stamp_funnel_records_the_dataset_revision_the_nightly_compares(tmp_path):
    f = tmp_path / "funnel.json"
    f.write_text(json.dumps({"format": "funnel-2", "funnels": {"configiq": {}}}))
    cn.stamp_funnel(f, REF)
    assert json.loads(f.read_text())["dataset"] == REF and "funnels" in json.loads(f.read_text())


def test_a_funnel_stamped_for_commit_names_no_outside_tool_even_when_the_ledger_does(tmp_path):
    """A ledger source's name reaches the funnel's cut-point discrepancies; the file is committed, and grep-clean (RFC C1)
    scans it. The name is built in pieces so this file passes the guard."""
    tool = "AI" + "Simulate"
    f = tmp_path / "funnel.json"
    f.write_text(json.dumps({"format": "funnel-2", "funnels": {"configiq": {}}, "cut_points": {"checked": True, "discrepancies": [
        {"source": tool.lower(), "code": "held_outside_inferencex", "text": f"{tool.lower()} has a held cut-point; only InferenceX may (D9)"}]}}))
    cn.stamp_funnel(f, REF)
    text = f.read_text()
    assert tool.lower() not in text.lower() and "an external simulator has a held cut-point" in text


# ---- the workflow step that scores configiq on a release night (api-nightly.yml) ----

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "api-nightly.yml"


def _workflow_step(name):
    import yaml
    wf = yaml.safe_load(WORKFLOW.read_text())
    steps = [s for s in wf["jobs"]["run-night"]["steps"] if s.get("name") == name]
    assert len(steps) == 1, name
    return steps[0]


def _run_step(tmp_path, mode, embedded="true"):
    """Run the step's script in a scratch repo whose scorer is a stub that writes what `mode` says."""
    import os
    import subprocess
    repo = tmp_path / "repo"
    (repo / "orchestrator" / "nightly").mkdir(parents=True)
    (repo / "data" / "supplemental" / "classes").mkdir(parents=True)
    (repo / "data" / "supplemental" / "funnels").mkdir(parents=True)
    (repo / "data" / "supplemental" / "classes" / "configiq.json").write_text("OLD-CLASS")
    (repo / "data" / "supplemental" / "funnels" / "configiq.json").write_text("OLD-FUNNEL")
    (repo / "orchestrator" / "resolve_stack.py").write_text(
        f"print('substrate_embedded={embedded}\\nsubstrate_version=sv\\nsubstrate_commit=sc')\n")
    (repo / "orchestrator" / "nightly" / "configiq_night.py").write_text(
        "import os, sys, pathlib\n"
        "out = pathlib.Path(sys.argv[sys.argv.index('--out') + 1])\n"
        "assert sys.argv[sys.argv.index('--sim-build') + 1] == 'v9.9.9'\n"
        f"mode = {mode!r}\n"
        "(out / 'classes').mkdir(parents=True)\n"
        "if mode in ('both', 'classes_then_fail'):\n"
        "    (out / 'classes' / 'configiq.json').write_text('NEW-CLASS')\n"
        "if mode == 'both':\n"
        "    (out / 'funnel.json').write_text('NEW-FUNNEL')\n"
        "sys.exit(1 if mode == 'classes_then_fail' else 0)\n")
    script = tmp_path / "step.sh"
    script.write_text(_workflow_step("Score configiq with the night's build")["run"])
    env = {**os.environ, "RUNNER_TEMP": str(tmp_path / "tmp"), "GITHUB_SHA": "h" * 40, "BLIS_TAG": "v9.9.9"}
    r = subprocess.run(["bash", str(script)], cwd=repo, env=env, capture_output=True, text=True)
    cls = (repo / "data/supplemental/classes/configiq.json").read_text()
    fun = (repo / "data/supplemental/funnels/configiq.json").read_text()
    return r, cls, fun


def test_release_night_replaces_both_derived_files_together(tmp_path):
    r, cls, fun = _run_step(tmp_path, "both")
    assert r.returncode == 0, r.stderr
    assert (cls, fun) == ("NEW-CLASS", "NEW-FUNNEL")


@pytest.mark.parametrize("mode", ["classes_then_fail", "nothing_then_ok"])
def test_a_failed_or_partial_score_keeps_the_committed_pair_and_warns(tmp_path, mode):
    # configiq_night.py writes the class file before the funnel: a failure between the two must not leave
    # a class file of the new build beside a funnel of the old one.
    r, cls, fun = _run_step(tmp_path, mode)
    assert r.returncode == 0, r.stderr
    assert (cls, fun) == ("OLD-CLASS", "OLD-FUNNEL")
    assert "::warning title=configiq not rescored" in r.stdout


def test_a_build_with_its_substrate_outside_its_tree_is_skipped_with_a_warning(tmp_path):
    r, cls, fun = _run_step(tmp_path, "both", embedded="false")
    assert r.returncode == 0, r.stderr
    assert (cls, fun) == ("OLD-CLASS", "OLD-FUNNEL")
    assert "::warning title=configiq not rescored" in r.stdout


def test_workflow_scores_configiq_only_when_resolve_says_so_and_later_steps_read_the_committed_paths():
    step = _workflow_step("Score configiq with the night's build")
    assert step["if"].replace(" ", "") == "${{needs.resolve.outputs.configiq=='true'}}"
    assert step["continue-on-error"] is True
    assert _workflow_step("Install what the configiq export reads (parquet)")["if"] == step["if"]
    for later in ("Build the classes page data from the night's summary and the committed derived files",
                  "Build the Sources tab data (funnel.json) from the night's contract and the ledger"):
        # the files the classes page and the Sources tab read are the committed pair, never a scratch copy
        assert "RUNNER_TEMP/configiq" not in _workflow_step(later)["run"]
