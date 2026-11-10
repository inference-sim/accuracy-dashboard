"""cli.py nightly's wiring (no-storage model): it lists the window, fetches+scores the delta, and
merges into the published summary. BLIS and the network aren't available here, so api.pull,
cmd_pull, run_harness and build_summary_v2 are monkeypatched to cheap fakes -- this checks the glue
(arg plumbing, work/data/state paths, the pull-failure-stops-the-run rule), not the scoring, which
test_score_e2e and test_nightly_run cover.
"""
import json
import sys
import types
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cli  # noqa: E402
import contract as c  # noqa: E402
import pull as pl  # noqa: E402
import api  # noqa: E402
import ledger_fake  # noqa: E402


def fake_blis(path: Path, commands: dict) -> Path:
    """A blis executable that answers each command in `commands` (its argv joined by spaces) with
    (exit status, standard output, standard error), records every argv it was given in
    path.saw, and exits 2 for any other command."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env python3\nimport json, sys\n"
                    f"answers = {json.dumps(commands)}\n"
                    f"open({str(path) + '.saw'!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
                    "code, out, err = answers.get(' '.join(sys.argv[1:]), [2, '', 'unknown command'])\n"
                    "sys.stdout.write(out); sys.stderr.write(err); sys.exit(code)\n")
    path.chmod(0o755)
    return path


def write_catalog(root: Path, models: dict) -> Path:
    """A catalog of the given entries (name -> source repository): models/<name>/model.yaml."""
    for name, repo in models.items():
        (root / "models" / name).mkdir(parents=True, exist_ok=True)
        (root / "models" / name / "model.yaml").write_text(f"name: {name}\nsource:\n  repo: {repo}\n")
    return root


def resolves(catalog: Path, models: dict) -> dict:
    """The answers of `blis catalog resolve --catalog <catalog> --model <q> --json` for every entry
    name and source repository of `models`, each resolving to its entry."""
    out = {}
    for name, repo in models.items():
        for q in (name, repo):
            out[f"catalog resolve --catalog {catalog} --model {q} --json"] = [
                0, json.dumps({"query": q, "identity": name, "reason": "fake"}), ""]
    return out




def _head(repo):
    import subprocess
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else "0" * 40


def _args(tmp, **over):
    a = dict(blis_tag="v0.12.0", work_dir=str(tmp / "work"), data_dir=str(tmp / "data"),
             state=str(tmp / "state.json"), scored=str(tmp / "scored-releases.json"), window_days=180, keep_api=5, today="2026-10-23",
             cache=None, work=str(tmp / "contract"), score_work=str(tmp / "sw"), evaluator_commit="abc",
             blis=str(tmp / "sim" / "blis"), catalog=str(tmp / "cat"), registry=str(tmp / "reg"),
             corpus_dir=str(tmp / "corpora"), corpus_cache=None,
             timeout=7200, workers=1, download_workers=1, agentic_workers=1, max_rss_mb=0, stack=None,
             ledger=str(tmp / "ledger"), substrate_dir=str(tmp / "substrate"), substrate_version="v1.0.0",
             substrate_commit=_head(tmp / "substrate"), fields=str(tmp / "fields.json"))
    a.update(over)
    if not Path(a["scored"]).exists():
        Path(a["scored"]).write_text(json.dumps({"kind": "ScoredReleases", "releases": []}))
    return types.SimpleNamespace(**a)


def _row(model, conc, md):
    return {"model": model, "hardware": "h100", "precision": "fp8", "framework": "vllm",
            "benchmark_type": "agentic_traces", "recipe_fingerprint": f"rf-{model}-{conc}-{md}",
            "conc": conc, "date": md, "id": str(conc * 100000 + int(md.replace("-", "")[2:])),
            "run_url": f"https://github.com/o/r/actions/runs/{conc}{md.replace('-', '')}/attempts/1"}


def write_anchor_list(substrate: Path, units, role="anchor"):
    """The substrate release's published anchor list, where the night reads it (M1: the file, not
    `blis ledger`, which the M1 simulator does not have)."""
    d = substrate / "catalog" / "ledger" / "published"
    d.mkdir(parents=True, exist_ok=True)
    (d / "anchor.yaml").write_text(published(role, units))


def published(role, units):
    return json.dumps({"kind": "PublishedUnits", "role": role, "partition_version": 1,
                       "seed_sha256": "0" * 64, "units": sorted(units)})


class Fakes:
    """Stand-ins for the network+BLIS steps, recording what cmd_nightly drove."""
    def __init__(self, rows):
        self.rows = rows
        self.pulled_only = None   # the --only list cmd_pull got
        self.anchors = None       # the anchor list blis prints; None = every row's unit

    def api_pull(self, fetch, *, today, window_days, framework="vllm"):
        return types.SimpleNamespace(rows=self.rows)

    def ledger(self, tmp):
        # The ledger the night reads: one unit per row, written before each night, and the blis
        # that prints the anchor list of the substrate release it pins.
        ledger_fake.write(tmp / "ledger", self.rows)
        anchors = [ledger_fake.point_id(r) for r in self.rows] if self.anchors is None else self.anchors
        if not (tmp / "substrate" / ".git").exists():
            _tagged_repo(tmp / "substrate", "v1.0.0")
        cat = write_catalog(tmp / "cat", {"m": "org/m"})
        write_anchor_list(tmp / "substrate", anchors)
        (tmp / "fields.json").write_text(json.dumps(FIELD_LIST))
        fake_blis(tmp / "sim" / "blis", {**resolves(cat, {"m": "org/m"})})

    def run_harness(self, cmd):
        # The harness script the night scores through: record its command, and write what the
        # script would write to its output directory.
        self.harness_cmd = cmd
        self.scored_units = Path(cmd[cmd.index("--units") + 1])
        out = Path(cmd[cmd.index("--out") + 1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "provenance.json").write_text(json.dumps({"pulled_at": "2026-10-23T00:00:00Z"}))
        return 0

    def cmd_pull(self, a):
        self.pulled_only = a.only
        want = self.rows if a.only is None else [r for r in self.rows
                                                 if ledger_fake.point_id(r) in set(a.only)]
        out = Path(a.out)
        points = []
        for r in want:
            pid = ledger_fake.point_id(r)
            ident = c.unit_identity(r, c.run_dates([r]))
            (out / "points" / pid).mkdir(parents=True, exist_ok=True)
            points.append({"point_id": pid, "identity": ident, "row": r, "files": {}, "reasons": []})
        pl.write_manifest(out, {"window": ["", a.today], "pulled_at": a.today + "T00:00:00Z"}, points)
        return 0



def _install(monkeypatch, fakes, scored_ids):
    monkeypatch.setattr(api, "pull", fakes.api_pull)
    monkeypatch.setattr(cli, "cmd_pull", fakes.cmd_pull)
    monkeypatch.setattr(cli, "run_harness", fakes.run_harness)
    import build_summary_v2
    def fake_build(contract_dir, *, generated_at, evaluator_commit):
        return {"schema_version": 3, "snapshot_id": "2026-10-23_blis-v0.12.0_ix-api-2026-10-23",
                "generated_at": generated_at,
                "provenance": {"ingest": "api", "blis": {"release": "v0.12.0"},
                               "simulator": {"build": "v0.12.0", "engine": {"kind": "vllm", "version": "0.32.0"}},
                               "ground_truth": {"release_tag": "api-2026-10-23"}},
                "coverage": {"graded": len(scored_ids), "not_scored": 0}, "matrix": [], "not_scored": []}
    monkeypatch.setattr(build_summary_v2, "build", fake_build)
    return build_summary_v2


def test_nightly_seed_lists_window_fetches_all_and_publishes(tmp_path, monkeypatch):
    rows = [_row("m", 1, "2026-10-01"), _row("m", 2, "2026-10-01")]
    fakes = Fakes(rows)
    _install(monkeypatch, fakes, [ledger_fake.point_id(r) for r in rows])

    fakes.ledger(tmp_path)
    rc = cli.cmd_nightly(_args(tmp_path))
    assert rc == 0
    # Seed (no prior summary) -> every anchor unit of the window fetched, snapshot frozen, live
    # view + state written.
    assert fakes.pulled_only == sorted(ledger_fake.point_id(r) for r in rows)
    idx = json.loads((tmp_path / "data" / "index.json").read_text())
    assert idx["latest"] == "2026-10-23_blis-v0.12.0_ix-api-2026-10-23"
    assert (tmp_path / "data" / "latest" / "summary.json").is_file()
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["ingest"] == "api" and state["blis_tag"] == "v0.12.0"
    assert set(state["point_ids"]) == {ledger_fake.point_id(r) for r in rows}


def test_nightly_ix_only_fetches_only_the_delta(tmp_path, monkeypatch):
    rows = [_row("m", 1, "2026-10-01")]
    fakes = Fakes(rows)
    _install(monkeypatch, fakes, [ledger_fake.point_id(r) for r in rows])
    fakes.ledger(tmp_path)
    cli.cmd_nightly(_args(tmp_path))                       # seed

    # Night 2: a new point, same BLIS -> only the new point is fetched (the delta).
    new = _row("m", 2, "2026-10-02")
    fakes.rows = rows + [new]
    fakes.ledger(tmp_path)
    # the merge path calls build_merged; stub it to a trivial summary so we only test the delta fetch
    import build_summary_v2
    monkeypatch.setattr(build_summary_v2, "build_merged",
                        lambda prior, delta, window_ids, **k: {**prior, "coverage": {"graded": 2, "not_scored": 0}})
    cli.cmd_nightly(_args(tmp_path, today="2026-10-24"))
    assert fakes.pulled_only == [ledger_fake.point_id(new)]   # delta only


def test_a_night_after_a_v2_summary_fetches_and_scores_the_whole_window(tmp_path, monkeypatch):
    # A published v2 summary holds no grades, so the delta cannot be merged into it: the night
    # rescores the whole window rather than publish a summary of the delta alone.
    rows = [_row("m", 1, "2026-10-01")]
    fakes = Fakes(rows)
    _install(monkeypatch, fakes, [ledger_fake.point_id(r) for r in rows])
    fakes.ledger(tmp_path)
    cli.cmd_nightly(_args(tmp_path))                       # seed
    latest = tmp_path / "data" / "latest" / "summary.json"
    latest.write_text(json.dumps({**json.loads(latest.read_text()), "schema_version": 2}))
    new = _row("m", 2, "2026-10-02")
    fakes.rows = rows + [new]
    fakes.ledger(tmp_path)
    import build_summary_v2
    monkeypatch.setattr(build_summary_v2, "build_merged", lambda *a, **k: (_ for _ in ()).throw(AssertionError("merged")))
    cli.cmd_nightly(_args(tmp_path, today="2026-10-24"))
    assert fakes.pulled_only == sorted(ledger_fake.point_id(r) for r in fakes.rows)   # the whole window


def test_nightly_noop_fetches_nothing_not_the_whole_window(tmp_path, monkeypatch):
    # Regression: on a night with no new points (a no-op or a pure age-out), pull_fn computes
    # `only = sorted(window - last) == []`. cmd_pull must read [] as "freeze nothing", NOT conflate
    # it with None ("freeze the whole window") -- else every quiet night re-downloads and re-scores
    # all ~2000 points (the full BLIS-release cost) for a result the merge then throws away.
    rows = [_row("m", 1, "2026-10-01"), _row("m", 2, "2026-10-01")]
    fakes = Fakes(rows)
    _install(monkeypatch, fakes, [ledger_fake.point_id(r) for r in rows])
    fakes.ledger(tmp_path)
    cli.cmd_nightly(_args(tmp_path))                       # seed: whole window
    assert fakes.pulled_only == sorted(ledger_fake.point_id(r) for r in rows)

    # Night 2: identical window, same BLIS -> no new points. The delta is empty.
    cli.cmd_nightly(_args(tmp_path, today="2026-10-24"))
    assert fakes.pulled_only == []                         # the empty delta, not the whole window
    # and cmd_pull froze zero rows for that empty delta
    assert json.loads((tmp_path / "work" / "manifest.json").read_text())["points"] == []


def test_the_night_scores_only_the_anchor_units_the_build_publishes(tmp_path, monkeypatch):
    # COV-2: a window row whose unit is not on the release's anchor list is neither fetched nor
    # scored, and the score step is given the anchor list as --units.
    rows = [_row("m", 1, "2026-10-01"), _row("m", 2, "2026-10-01")]
    fakes = Fakes(rows)
    anchor = ledger_fake.point_id(rows[0])
    fakes.anchors = [anchor]
    _install(monkeypatch, fakes, [anchor])
    fakes.ledger(tmp_path)
    assert cli.cmd_nightly(_args(tmp_path)) == 0
    assert fakes.pulled_only == [anchor]
    import ledger as ldg
    assert ldg.read_unit_set(Path(fakes.scored_units), role="anchor") == {anchor}
    assert json.loads((tmp_path / "state.json").read_text())["point_ids"] == [anchor]


def test_an_anchor_unit_of_a_framework_no_engine_models_stays_in_the_window(tmp_path, monkeypatch):
    # The nightly pulls every framework. An anchor unit that runs on TensorRT-LLM is a point of
    # the window (engines.py gives it its G5 reason without an artifact); the anchor filter must
    # not drop it.
    vllm_row, trt_row = _row("m", 1, "2026-10-01"), {**_row("m", 2, "2026-10-01"), "framework": "trt"}
    fakes = Fakes([vllm_row, trt_row])
    both = sorted(ledger_fake.point_id(r) for r in fakes.rows)
    _install(monkeypatch, fakes, both)
    fakes.ledger(tmp_path)
    assert cli.cmd_nightly(_args(tmp_path)) == 0
    assert fakes.pulled_only == both


def test_a_night_fails_naming_the_count_when_an_anchor_unit_is_not_in_the_window(tmp_path, monkeypatch):
    # An anchor unit with no row in the window is neither pulled nor listed with a reason, so
    # the counts would omit it without a word (COV-1). The night stops before any fetch.
    rows = [_row("m", 1, "2026-10-01")]
    fakes = Fakes(rows)
    fakes.anchors = [ledger_fake.point_id(rows[0]), "e" * 64, "f" * 64]
    _install(monkeypatch, fakes, [])
    fakes.ledger(tmp_path)
    monkeypatch.setattr(cli, "cmd_pull", lambda a: (_ for _ in ()).throw(AssertionError("pulled")))
    with pytest.raises(RuntimeError, match=r"2 of the 3 anchor units are neither a point of the window nor listed"):
        cli.cmd_nightly(_args(tmp_path))
    assert not (tmp_path / "data" / "latest").exists()


def test_a_night_whose_build_publishes_no_anchor_unit_fails_and_scores_nothing(tmp_path, monkeypatch):
    # Until the ledger seed exists the anchor list is empty. The night fails naming why; it does
    # not fall back to scoring the whole window (X16).
    fakes = Fakes([_row("m", 1, "2026-10-01")])
    fakes.anchors = []
    _install(monkeypatch, fakes, [])
    fakes.ledger(tmp_path)
    monkeypatch.setattr(cli, "cmd_pull", lambda a: (_ for _ in ()).throw(AssertionError("pulled")))
    msgs = []
    monkeypatch.setattr(cli, "_log", msgs.append)
    assert cli.cmd_nightly(_args(tmp_path)) == 2
    assert any("lists no unit" in m and "anchor.yaml" in m for m in msgs), msgs
    assert not (tmp_path / "data" / "latest").exists()


def test_a_night_whose_substrate_publishes_no_anchor_list_fails(tmp_path, monkeypatch):
    # The substrate release has no catalog/ledger/published/anchor.yaml until its seed job runs.
    fakes = Fakes([_row("m", 1, "2026-10-01")])
    _install(monkeypatch, fakes, [])
    fakes.ledger(tmp_path)
    (tmp_path / "substrate" / "catalog" / "ledger" / "published" / "anchor.yaml").unlink()
    msgs = []
    monkeypatch.setattr(cli, "_log", msgs.append)
    assert cli.cmd_nightly(_args(tmp_path)) == 2
    assert any("publishes no anchor list yet" in m for m in msgs), msgs


def test_a_list_of_another_role_is_not_the_anchor_list(tmp_path):
    import ledger as ldg
    write_anchor_list(tmp_path / "substrate", ["a" * 64], role="fit")
    with pytest.raises(ldg.LedgerError, match="role 'fit', want 'anchor'"):
        cli.read_anchor_units(tmp_path / "substrate", tmp_path / "anchor.json")


def test_nightly_stops_when_the_pull_fails(tmp_path, monkeypatch):
    fakes = Fakes([_row("m", 1, "2026-10-01")])
    _install(monkeypatch, fakes, [])
    fakes.ledger(tmp_path)
    monkeypatch.setattr(cli, "cmd_pull", lambda a: 4)      # a pull error
    with pytest.raises(RuntimeError, match="pull failed"):
        cli.cmd_nightly(_args(tmp_path))


def test_the_nightly_scores_by_running_the_harness_script_and_no_container(tmp_path, monkeypatch):
    # Design §11.7: the night runs harness/run.sh from this checkout, so every figure records the
    # checkout's commit. It does not call cmd_score in its own process, and starts no container.
    rows = [_row("m", 1, "2026-10-01")]
    fakes = Fakes(rows)
    _install(monkeypatch, fakes, [ledger_fake.point_id(r) for r in rows])
    monkeypatch.setattr(cli, "cmd_score", lambda a: (_ for _ in ()).throw(AssertionError("scored from source")))
    fakes.ledger(tmp_path)
    assert cli.cmd_nightly(_args(tmp_path)) == 0
    cmd = fakes.harness_cmd
    assert cmd[0] == "bash" and Path(cmd[1]) == cli.HARNESS_RUN and cmd[1].endswith("harness/run.sh")
    assert "docker" not in cmd and cmd[2:4] == ["--sim", "v0.12.0"]
    # The substrate checkout has no tag of its own, so the night passes the release stack.json
    # names for the one checkout the catalog and registry are directories of.
    assert cmd[cmd.index("--catalog-release") + 1] == "v1.0.0" and cmd[cmd.index("--registry-release") + 1] == "v1.0.0"
    assert cmd[cmd.index("--catalog") + 1] == str((tmp_path / "cat").resolve())


def _nightly_refused(tmp_path, monkeypatch, **over):
    rows = [_row("m", 1, "2026-10-01")]
    fakes = Fakes(rows)
    _install(monkeypatch, fakes, [ledger_fake.point_id(r) for r in rows])
    fakes.ledger(tmp_path)
    monkeypatch.setattr(cli, "run_harness", lambda cmd: (_ for _ in ()).throw(AssertionError("scored")))
    msgs = []
    monkeypatch.setattr(cli, "_log", msgs.append)
    assert cli.cmd_nightly(_args(tmp_path, **over)) == 2
    return msgs


def test_the_nightly_stops_before_scoring_on_a_substrate_that_is_a_pseudo_version(tmp_path, monkeypatch):
    # A draft build pins a Go pseudo-version; it is not a release and cannot be published (X8).
    msgs = _nightly_refused(tmp_path, monkeypatch, substrate_version="v0.0.0-20261105035832-817e83e0018b")
    assert ("FATAL: blis-substrate v0.0.0-20261105035832-817e83e0018b in stack.json is not a release tag; "
            "a release is scored on a tagged substrate") in msgs, msgs


def test_the_nightly_stops_before_scoring_when_the_checkout_is_not_the_tags_commit(tmp_path, monkeypatch):
    # stack.json pins a commit that is not the one the tag names: both are in the message.
    other = "1" * 40
    msgs = _nightly_refused(tmp_path, monkeypatch, substrate_commit=other)
    head = _head(tmp_path / "substrate")
    assert any("FATAL" in m and head in m and other in m and "v1.0.0" in m for m in msgs), msgs


def _git(*a):
    import subprocess
    subprocess.run(["git", *a], check=True, capture_output=True)


def _tagged_repo(path, tag):
    path.mkdir(parents=True)
    _git("-C", str(path), "init", "-q")
    _git("-C", str(path), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x")
    if tag:
        _git("-C", str(path), "tag", tag)


def test_check_blis_inputs_reads_the_release_from_the_binarys_checkout(tmp_path):
    sim = tmp_path / "sim"
    _tagged_repo(sim, "v0.16.0")
    (sim / "blis").write_text("")
    assert cli.check_blis_inputs(sim / "blis", "v1.0.0", "v1.0.0") == []
    bad = cli.check_blis_inputs(sim / "nope", "v1.0.0", "v1.0.0")
    assert len(bad) == 1 and bad[0].startswith(f"--blis {sim / 'nope'} is not a file")


def test_check_blis_inputs_refuses_a_checkout_not_at_a_tag(tmp_path):
    sim = tmp_path / "sim"
    _tagged_repo(sim, None)
    (sim / "blis").write_text("")
    bad = cli.check_blis_inputs(sim / "blis", "v1.0.0", "v1.0.0")
    assert any("is not at a release tag" in b for b in bad)


def test_the_data_releases_are_named_by_the_caller_and_need_no_git_history(tmp_path):
    # The harness image mounts the catalog and registry without .git (harness_pin.docker_command),
    # so check_blis_inputs takes the release names.
    sim = tmp_path / "sim"
    _tagged_repo(sim, "v0.16.0")
    (sim / "blis").write_text("")
    bare = tmp_path / "mount" / "catalog"
    (bare / "models").mkdir(parents=True)
    assert not (bare / ".git").exists()
    assert cli.check_blis_inputs(sim / "blis", "v1.0.0", "v2.3.4-rc1") == []
    assert cli.check_blis_inputs(sim / "blis", None, "v1.0.0") == ["--catalog-release is required: the release tag the data is at"]
    assert cli.check_blis_inputs(sim / "blis", "v1.0.0", "bad tag") == ["--registry-release 'bad tag' is not a release tag"]


FIELD_LIST = {"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.32.0"}, "fields": []}


def test_the_field_list_is_the_file_for_the_release_the_simulator_runs(tmp_path):
    text = json.dumps(FIELD_LIST)
    f = tmp_path / "fields.json"
    f.write_text(text)
    fl_, sha = cli.read_fields(f, "0.32.0")
    assert fl_.engine == {"kind": "vllm", "version": "0.32.0"}
    import hashlib
    assert sha == hashlib.sha256(text.encode()).hexdigest()
    import fields
    with pytest.raises(fields.FieldsError, match="the simulator runs vllm 0.31.0"):
        cli.read_fields(f, "0.31.0")


def test_a_missing_field_list_file_is_refused(tmp_path):
    with pytest.raises(OSError):
        cli.read_fields(tmp_path / "absent.json", "0.32.0")


def test_a_build_with_no_stack_json_is_refused_with_why(tmp_path):
    import stack
    (tmp_path / "sim").mkdir()
    with pytest.raises(stack.StackError, match="predates stack.json"):
        cli.read_stack(tmp_path / "sim" / "blis", None)
    s = tmp_path / "stack.json"
    s.write_text(json.dumps({"kind": "Stack", "engines": [{"kind": "vllm", "version": "0.32.0"}]}))
    assert cli.read_stack(tmp_path / "sim" / "blis", str(s)).engine("vllm") == "0.32.0"


def test_resolve_blis_names_every_unscored_release_oldest_first_else_the_newest(tmp_path):
    # COV-9: resolve_blis.sh lists every stable release from v0.16.0 on that
    # state/scored-releases.json does not list, in tag order; with none left, it scores the
    # newest release's delta.
    import subprocess
    root = Path(__file__).resolve().parent.parent
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    releases = [{"tagName": t, "createdAt": d} for t, d in
                (("v0.17.0", "2026-12-01"), ("v0.15.0", "2026-10-30"), ("v0.16.0", "2026-11-10"))]
    gh = bin_ / "gh"
    # The fake gh applies the jq query the script passes, as gh does.
    gh.write_text("#!/usr/bin/env python3\nimport json, sys\nrel = " + json.dumps(releases) + "\n"
                  "q = sys.argv[sys.argv.index('-q') + 1]\n"
                  "assert q == 'sort_by(.createdAt) | .[].tagName', q\n"
                  "print('\\n'.join(r['tagName'] for r in sorted(rel, key=lambda r: r['createdAt'])))\n")
    gh.chmod(0o755)

    def run():
        out = tmp_path / "out"
        out.unlink(missing_ok=True)
        env = {"PATH": f"{bin_}:/usr/bin:/bin", "GITHUB_OUTPUT": str(out)}
        work = tmp_path / "repo"
        r = subprocess.run(["bash", str(work / "orchestrator" / "resolve_blis.sh")], env=env,
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return dict(line.split("=", 1) for line in out.read_text().splitlines())
    import shutil
    shutil.copytree(root, tmp_path / "repo" / "orchestrator", ignore=shutil.ignore_patterns("testdata", "__pycache__"))
    state = tmp_path / "repo" / "state"
    state.mkdir()

    def listed(*tags):
        (state / "scored-releases.json").write_text(json.dumps({"kind": "ScoredReleases", "releases": list(tags)}))
    listed("v0.15.0")
    import sys as _sys
    (bin_ / "python3").symlink_to(_sys.executable)
    # One release per run, the oldest unscored, and `more` says the run must start another: each
    # release is published before the next begins (COV-9), so a later failure cannot lose it.
    assert run() == {"blis_tags": "v0.16.0", "blis_tag": "v0.17.0", "more": "true"}
    # v0.16.0 published and listed; the next run starts at v0.17.0, the last, so nothing follows it.
    listed("v0.15.0", "v0.16.0")
    assert run() == {"blis_tags": "v0.17.0", "blis_tag": "v0.17.0", "more": "false"}
    # v0.17.0 FAILED: nothing was listed for it, so the next run starts at it again, not at v0.16.0.
    assert run() == {"blis_tags": "v0.17.0", "blis_tag": "v0.17.0", "more": "false"}
    listed("v0.15.0", "v0.16.0", "v0.17.0")
    assert run() == {"blis_tags": "v0.17.0", "blis_tag": "v0.17.0", "more": "false"}


def test_the_workflow_scores_one_release_and_starts_the_next_only_after_publishing_it():
    import yaml
    wf = yaml.safe_load((Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "api-nightly.yml").read_text())
    jobs = wf["jobs"]
    assert "more" in jobs["resolve"]["outputs"]
    steps = jobs["publish"]["steps"]
    names = [s.get("name", "") for s in steps]
    nxt = steps[names.index("Score the next unscored release")]
    # Dispatched by the publish job, after its publish step, and only when that step pushed.
    assert names.index("Score the next unscored release") > names.index(
        "Publish data/ to main (index + latest + API snapshots; dump snapshots untouched)")
    assert "steps.pub.outputs.pushed == 'true'" in nxt["if"] and "outputs.more == 'true'" in nxt["if"]
    assert "gh workflow run api-nightly.yml" in nxt["run"]
    assert jobs["publish"]["permissions"]["actions"] == "write"
    # The scoring step builds one release: its loop runs over the one tag the resolver named.
    score = next(s for s in jobs["run-night"]["steps"] if s.get("name") == "Score the release")
    assert score["env"]["BLIS_TAGS"] == "${{ needs.resolve.outputs.blis_tags }}"


def test_sim_build_must_be_the_checkouts_tag_or_commit(tmp_path):
    import subprocess
    sim = tmp_path / "sim"
    _tagged_repo(sim, "v0.16.0")
    (sim / "blis").write_text("")
    head = subprocess.run(["git", "-C", str(sim), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    check = lambda b: cli.check_blis_inputs(sim / "blis", "v1.0.0", "v1.0.0", b)  # noqa: E731
    assert check("v0.16.0") == [] and check(head) == []
    assert check("v0.17.0") == [f"--sim-build v0.17.0: the checkout {sim} is at v0.16.0"]
    assert check("0" * 40) == [f"--sim-build {'0' * 40}: the checkout {sim} is at commit {head}"]
    assert check("main") == ["--sim-build 'main' is neither a tag vX.Y.Z[-suffix] nor a 40-hex commit"]


def test_the_harness_commit_is_a_full_40_hex_commit():
    assert cli.check_harness_commit("a" * 40) == []
    for bad in ("latest", "v0.4.0", "a" * 12, "A" * 40, "sha256:" + "a" * 64, "unreleased"):
        assert cli.check_harness_commit(bad) == [f"--harness-commit {bad!r} is not a full 40-hex commit"], bad
    assert cli.check_harness_commit(None)[0].startswith("--harness-commit is required")


def test_units_select_the_points_of_the_pull_and_name_those_it_does_not_hold(tmp_path):
    a, b, c_ = "a" * 64, "b" * 64, "c" * 64
    units = tmp_path / "units.txt"
    units.write_text(f"{a}\n{c_}\n")
    pts = [{"point_id": a}, {"point_id": b}]
    chosen, rec = cli.select_units(pts, str(units))
    assert chosen == [{"point_id": a}]
    assert rec["count"] == 2 and rec["not_in_pull"] == [c_] and len(rec["sha256"]) == 64
    assert cli.select_units(pts, None) == (pts, None)


def test_a_pre_release_tag_is_a_simulator_build_but_not_a_release_tag(tmp_path):
    # harness/run.sh accepts vMAJOR.MINOR.PATCH-suffix; check_blis_inputs must agree, and the
    # figures are experimental unless the build is a release tag with no suffix.
    sim = tmp_path / "sim"
    _tagged_repo(sim, "v0.16.0-rc1")
    (sim / "blis").write_text("")
    check = lambda b: cli.check_blis_inputs(sim / "blis", "v1.0.0", "v1.0.0", b)  # noqa: E731
    assert check("v0.16.0-rc1") == []
    assert check("v0.16.0-rc2") == [f"--sim-build v0.16.0-rc2: the checkout {sim} is at v0.16.0-rc1"]
    assert check("v0.16") == ["--sim-build 'v0.16' is neither a tag vX.Y.Z[-suffix] nor a 40-hex commit"]
    assert cli.check_blis_inputs(sim / "blis", "v1.0.0", "v1.0.0") == []
    assert cli._RELEASE_TAG.match("v0.16.0") and not cli._RELEASE_TAG.match("v0.16.0-rc1")


# ttft_mean_ms and tpot_mean_ms as blis-substrate contracts/metrics (800ae263) defines them.
from test_result import REGISTRY  # noqa: E402


AGENTX = {"semianalysis_cc_traces_weka_062126": ("agentx-mvp-uncapped", "semianalysisai/cc-traces-weka-062126",
                                                  "23f152f6f0f9399a85901b89a6458def0ef16729", b"uncapped\n"),
          "semianalysis_cc_traces_weka_062126_256k": ("agentx-mvp", "semianalysisai/cc-traces-weka-062126-256k",
                                                      "8fecd2fc56694469f758f0afbbb6335ad3043740", b"capped\n")}


def _agentx_corpora(catalog, corpus_dir):
    """The two AgentX replay workloads in the catalog, and their corpus files where
    resolve_agentic_corpus.py --all puts them, each with the sha256 its entry pins."""
    import hashlib
    (catalog / "workloads").mkdir(parents=True, exist_ok=True)
    for alias, (name, repo, rev, body) in AGENTX.items():
        (catalog / "workloads" / f"{name}.yaml").write_text(
            f"replay:\n  corpus:\n    loader: {alias}\n    source:\n      huggingface: {repo}\n"
            f"      revision: {rev}\n      file: traces.jsonl\n      split: train\n"
            f"    sha256: {hashlib.sha256(body).hexdigest()}\n")
        (corpus_dir / name).mkdir(parents=True, exist_ok=True)
        (corpus_dir / name / "traces.jsonl").write_bytes(body)


def _score_inputs(tmp_path, commands: dict):
    """What cmd_score needs, with a fake blis answering `commands` beside a stack.json for vLLM
    0.32.0, in a checkout at v0.16.0; the catalog and registry as the harness image mounts them,
    plain directories with no .git, named by --catalog-release and --registry-release; and a pull
    of no points."""
    sim = tmp_path / "sim"
    _tagged_repo(sim, "v0.16.0")
    (sim / "go.mod").write_text("module x\n")
    (sim / "stack.json").write_text(json.dumps({"kind": "Stack", "engines": [{"kind": "vllm", "version": "0.32.0"}]}))
    blis = fake_blis(sim / "blis", {**commands})
    (tmp_path / "fields.json").write_text(json.dumps(FIELD_LIST))
    (tmp_path / "cat").mkdir()
    (tmp_path / "reg").mkdir()
    assert not (tmp_path / "cat" / ".git").exists() and not (tmp_path / "reg" / ".git").exists()
    _agentx_corpora(tmp_path / "cat", tmp_path / "corpora")
    (tmp_path / "pull").mkdir()
    pl.write_manifest(tmp_path / "pull", {"window": ["", ""], "pulled_at": "2026-10-23T00:00:00Z",
                                          "vllm_ref": "v0.32.0", "vllm_max_distance": 0}, [])
    return types.SimpleNamespace(
        pull=str(tmp_path / "pull"), out=str(tmp_path / "contract"), blis=str(blis), catalog=str(tmp_path / "cat"),
        registry=str(tmp_path / "reg"), fields=str(tmp_path / "fields.json"), catalog_release="v1.0.0", registry_release="v1.0.0", stack=None, sim_build=None, harness_commit="c" * 40, units=None,
        corpus_dir=str(tmp_path / "corpora"),
        corpus_cache=None, work=str(tmp_path / "work"), timeout=60, only=None, workers=1, agentic_workers=1,
        max_rss_mb=0)


def test_a_failed_catalog_resolve_stops_the_score_run(tmp_path, monkeypatch):
    # The scorer reads catalog identities through `blis catalog resolve`, with the catalog it
    # was given. A build without the command, or a name it refuses, fails the run rather than
    # grade a point not_in_catalog.
    a = _score_inputs(tmp_path, {})
    import score
    monkeypatch.setattr(score, "score_points", lambda points, pull, work, env, **k: [env.catalog_obj.model("org/m")])
    msgs = []
    monkeypatch.setattr(cli, "_log", msgs.append)
    assert cli.cmd_score(a) == 2
    want = f"blis catalog resolve --catalog {Path(a.catalog).resolve()} --model org/m --json exited 2"
    assert any(want in m for m in msgs), msgs


def test_an_ambiguous_catalog_repository_stops_the_night_before_any_fetch(tmp_path, monkeypatch):
    # Two entries claim org/m. `blis catalog resolve` refuses it; the night checks the catalog
    # once, before the pull, and exits with the message naming both entries (audit finding 14),
    # instead of crashing mid-score.
    fakes = Fakes([_row("m", 1, "2026-10-01")])
    _install(monkeypatch, fakes, [])
    fakes.ledger(tmp_path)
    models = {"a": "org/m", "b": "org/m"}
    cat = write_catalog(tmp_path / "cat", models)
    refusal = "model 'org/m' is the source repository of 2 catalog entries: a, b"
    answers = {**resolves(cat, models),
               f"catalog resolve --catalog {cat} --model org/m --json": [1, "", refusal]}
    fake_blis(tmp_path / "sim" / "blis", answers)
    monkeypatch.setattr(cli, "cmd_pull", lambda a: (_ for _ in ()).throw(AssertionError("pulled")))
    msgs = []
    monkeypatch.setattr(cli, "_log", msgs.append)
    assert cli.cmd_nightly(_args(tmp_path)) == 2
    assert any("FATAL" in m and "a, b" in m and "--model org/m" in m for m in msgs), msgs
    assert not (tmp_path / "data" / "latest").exists()


def test_a_score_run_replays_every_agentx_corpus_by_its_catalog_entry(tmp_path, monkeypatch):
    # D3, COV-12: the scorer takes each date-pinned alias's revision and full sha256 from its
    # catalog replay workload, and records both corpora in provenance. No --corpus-dataset, no
    # --corpus-revision: nothing defaults the corpus, and nothing resolves a moving ref.
    a = _score_inputs(tmp_path, {})
    import score
    seen = {}
    monkeypatch.setattr(score, "score_points", lambda points, pull, work, env, **k: seen.setdefault("env", env) and [])
    monkeypatch.setattr(score, "write_contract", lambda out, outcomes, prov: seen.setdefault("prov", prov))
    import contract
    monkeypatch.setattr(contract, "validate_dir", lambda d: [])
    assert cli.cmd_score(a) == 0
    corpora = seen["env"].corpora
    assert sorted(corpora) == sorted(AGENTX)
    for alias, (name, repo, rev, body) in AGENTX.items():
        e = corpora[alias]
        assert (e["workload"], e["repo"], e["revision"]) == (name, repo, rev)
        assert e["path"] == str((tmp_path / "corpora" / name / "traces.jsonl").resolve())
    assert [c["alias"] for c in seen["prov"]["corpora"]] == sorted(AGENTX)
    assert all(len(c["revision"]) == 40 and len(c["sha256"]) == 64 for c in seen["prov"]["corpora"])
    for flag in ("--corpus-dataset", "--corpus-revision", "--corpus-sha256"):
        with pytest.raises(SystemExit):
            cli.main(["score", "--pull", "p", "--out", "o", "--blis", "b", "--catalog", "c", "--registry", "r",
                      "--catalog-release", "v1", "--registry-release", "v1", "--harness-commit", "c" * 40,
                      "--corpus-dir", "d", flag, "x"])


@pytest.mark.parametrize("damage,match", [
    (lambda cat, cd: (cd / "agentx-mvp" / "traces.jsonl").write_bytes(b"other\n"), "mismatch"),
    (lambda cat, cd: (cd / "agentx-mvp" / "traces.jsonl").unlink(), "does not exist"),
    (lambda cat, cd: (cat / "workloads" / "agentx-mvp-uncapped.yaml").unlink(), "no workload"),
    (lambda cat, cd: (cat / "workloads" / "agentx-mvp.yaml").write_text(
        (cat / "workloads" / "agentx-mvp.yaml").read_text().replace("8fecd2fc56694469f758f0afbbb6335ad3043740", "main")),
     "40-hex"),
])
def test_a_score_run_without_every_pinned_corpus_is_refused(tmp_path, monkeypatch, damage, match):
    a = _score_inputs(tmp_path, {})
    damage(Path(a.catalog), Path(a.corpus_dir))
    msgs = []
    monkeypatch.setattr(cli, "_log", msgs.append)
    assert cli.cmd_score(a) == 2
    assert any(match in m for m in msgs), msgs


def test_a_score_run_reads_the_field_list_file_and_scores(tmp_path, monkeypatch):
    a = _score_inputs(tmp_path, {})
    import score
    seen = []
    monkeypatch.setattr(score, "score_points", lambda points, *x, **k: seen.append(points) or [])
    monkeypatch.setattr(score, "write_contract", lambda *x: None)
    import contract
    monkeypatch.setattr(contract, "validate_dir", lambda d: [])
    assert cli.cmd_score(a) == 0 and seen == [[]]
