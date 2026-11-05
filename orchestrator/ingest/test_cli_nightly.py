"""cli.py nightly's wiring (no-storage model): it lists the window, fetches+scores the delta, and
merges into the published summary. BLIS and the network aren't available here, so api.pull,
cmd_pull, cmd_score and build_summary_v2 are monkeypatched to cheap fakes -- this checks the glue
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


def _args(tmp, **over):
    a = dict(blis_tag="v0.12.0", work_dir=str(tmp / "work"), data_dir=str(tmp / "data"),
             state=str(tmp / "state.json"), window_days=180, keep_api=5, today="2026-10-23",
             cache=None, work=str(tmp / "contract"), score_work=str(tmp / "sw"), evaluator_commit="abc",
             blis=str(tmp / "sim" / "blis"), catalog=str(tmp / "cat"), registry=str(tmp / "reg"),
             corpus_dir=str(tmp / "corpora"), corpus_cache=None,
             timeout=7200, workers=1, download_workers=1, agentic_workers=1, max_rss_mb=0, stack=None,
             ledger=str(tmp / "ledger"))
    a.update(over)
    return types.SimpleNamespace(**a)


def _row(model, conc, md):
    return {"model": model, "hardware": "h100", "precision": "fp8", "framework": "vllm",
            "benchmark_type": "agentic_traces", "recipe_fingerprint": f"rf-{model}-{conc}-{md}",
            "conc": conc, "date": md, "id": str(conc * 100000 + int(md.replace("-", "")[2:])),
            "run_url": f"https://github.com/o/r/actions/runs/{conc}{md.replace('-', '')}/attempts/1"}


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
        fake_blis(tmp / "sim" / "blis", {"ledger --list anchor --json": [0, published("anchor", anchors), ""]})

    def cmd_score(self, a):
        self.scored_units = a.units
        Path(a.out).mkdir(parents=True, exist_ok=True)
        (Path(a.out) / "provenance.json").write_text(json.dumps({"pulled_at": "2026-10-23T00:00:00Z"}))
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
    monkeypatch.setattr(cli, "cmd_score", fakes.cmd_score)
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
    fakes.anchors = [anchor, "f" * 64]                     # an anchor unit outside the window too
    _install(monkeypatch, fakes, [anchor])
    fakes.ledger(tmp_path)
    assert cli.cmd_nightly(_args(tmp_path)) == 0
    assert fakes.pulled_only == [anchor]
    import ledger as ldg
    assert ldg.read_unit_set(Path(fakes.scored_units), role="anchor") == {anchor, "f" * 64}
    assert json.loads((tmp_path / "state.json").read_text())["point_ids"] == [anchor]


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
    assert any("printed no unit" in m and "anchor list" in m for m in msgs), msgs
    assert not (tmp_path / "data" / "latest").exists()


def test_a_night_whose_blis_has_no_ledger_command_fails(tmp_path, monkeypatch):
    fakes = Fakes([_row("m", 1, "2026-10-01")])
    _install(monkeypatch, fakes, [])
    fakes.ledger(tmp_path)
    fake_blis(tmp_path / "sim" / "blis", {})
    msgs = []
    monkeypatch.setattr(cli, "_log", msgs.append)
    assert cli.cmd_nightly(_args(tmp_path)) == 2
    assert any("blis ledger --list anchor --json exited 2" in m for m in msgs), msgs


def test_a_list_of_another_role_is_not_the_anchor_list(tmp_path):
    import ledger as ldg
    blis = fake_blis(tmp_path / "sim" / "blis", {"ledger --list anchor --json": [0, published("fit", ["a" * 64]), ""]})
    with pytest.raises(ldg.LedgerError, match="role 'fit', want 'anchor'"):
        cli.read_anchor_units(blis, tmp_path / "anchor.json")


def test_nightly_stops_when_the_pull_fails(tmp_path, monkeypatch):
    fakes = Fakes([_row("m", 1, "2026-10-01")])
    _install(monkeypatch, fakes, [])
    fakes.ledger(tmp_path)
    monkeypatch.setattr(cli, "cmd_pull", lambda a: 4)      # a pull error
    with pytest.raises(RuntimeError, match="pull failed"):
        cli.cmd_nightly(_args(tmp_path))


def test_the_nightly_passes_the_blis_binary_to_score(tmp_path, monkeypatch):
    rows = [_row("m", 1, "2026-10-01")]
    fakes = Fakes(rows)
    _install(monkeypatch, fakes, [ledger_fake.point_id(r) for r in rows])
    seen = {}
    real = fakes.cmd_score
    monkeypatch.setattr(cli, "cmd_score", lambda a: (seen.setdefault("a", a), real(a))[1])
    fakes.ledger(tmp_path)
    cli.cmd_nightly(_args(tmp_path))
    assert seen["a"].blis == str(tmp_path / "sim" / "blis")
    assert not hasattr(seen["a"], "blis_dir") and not hasattr(seen["a"], "signedprobe")


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
    for r in ("cat", "reg"):
        _tagged_repo(tmp_path / r, "v1.0.0")
    assert cli.check_blis_inputs(sim / "blis", tmp_path / "cat", tmp_path / "reg") == []
    bad = cli.check_blis_inputs(sim / "nope", tmp_path / "cat", tmp_path / "reg")
    assert len(bad) == 1 and bad[0].startswith(f"--blis {sim / 'nope'} is not a file")


def test_check_blis_inputs_refuses_a_checkout_not_at_a_tag(tmp_path):
    sim = tmp_path / "sim"
    _tagged_repo(sim, None)
    (sim / "blis").write_text("")
    for r in ("cat", "reg"):
        _tagged_repo(tmp_path / r, "v1.0.0")
    bad = cli.check_blis_inputs(sim / "blis", tmp_path / "cat", tmp_path / "reg")
    assert any("is not at a release tag" in b for b in bad)


FIELD_LIST = {"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.32.0"}, "fields": []}


def test_the_field_list_is_what_blis_fields_prints_for_the_release_the_simulator_runs(tmp_path):
    text = json.dumps(FIELD_LIST)
    blis = fake_blis(tmp_path / "sim" / "blis", {"fields --engine vllm --json": [0, text, ""]})
    fl_, sha = cli.read_fields(blis, "0.32.0")
    assert fl_.engine == {"kind": "vllm", "version": "0.32.0"}
    import hashlib
    assert sha == hashlib.sha256(text.encode()).hexdigest()
    import fields
    with pytest.raises(fields.FieldsError, match="the simulator runs vllm 0.31.0"):
        cli.read_fields(blis, "0.31.0")


def test_a_blis_without_the_fields_command_is_refused_naming_the_command(tmp_path):
    import blis_commands
    blis = fake_blis(tmp_path / "sim" / "blis", {})
    with pytest.raises(blis_commands.CommandError, match="blis fields --engine vllm --json exited 2: unknown command"):
        cli.read_fields(blis, "0.32.0")


def test_a_build_with_no_stack_json_is_refused_with_why(tmp_path):
    import stack
    (tmp_path / "sim").mkdir()
    with pytest.raises(stack.StackError, match="predates stack.json"):
        cli.read_stack(tmp_path / "sim" / "blis", None)
    s = tmp_path / "stack.json"
    s.write_text(json.dumps({"kind": "Stack", "engines": [{"kind": "vllm", "version": "0.32.0"}]}))
    assert cli.read_stack(tmp_path / "sim" / "blis", str(s)).engine("vllm") == "0.32.0"


def test_resolve_blis_names_every_unscored_release_oldest_first_else_the_newest(tmp_path):
    # COV-9: resolve_blis.sh lists every stable release from v0.16.0 on with no published
    # snapshot, in tag order; with none left, it scores the newest release's delta.
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
    snaps = tmp_path / "repo" / "data" / "snapshots"
    (snaps / "2026-10-31_blis-v0.15.0_ix-api-2026-10-31").mkdir(parents=True)
    import sys as _sys
    (bin_ / "python3").symlink_to(_sys.executable)
    assert run() == {"blis_tags": "v0.16.0 v0.17.0", "blis_tag": "v0.17.0"}
    (snaps / "2026-11-11_blis-v0.16.0_ix-api-2026-11-11").mkdir()
    (snaps / "2026-12-02_blis-v0.17.0_ix-api-2026-12-02").mkdir()
    assert run() == {"blis_tags": "v0.17.0", "blis_tag": "v0.17.0"}


def test_sim_build_must_be_the_checkouts_tag_or_commit(tmp_path):
    import subprocess
    sim = tmp_path / "sim"
    _tagged_repo(sim, "v0.16.0")
    (sim / "blis").write_text("")
    for r in ("cat", "reg"):
        _tagged_repo(tmp_path / r, "v1.0.0")
    head = subprocess.run(["git", "-C", str(sim), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    check = lambda b: cli.check_blis_inputs(sim / "blis", tmp_path / "cat", tmp_path / "reg", b)  # noqa: E731
    assert check("v0.16.0") == [] and check(head) == []
    assert check("v0.17.0") == [f"--sim-build v0.17.0: the checkout {sim} is at v0.16.0"]
    assert check("0" * 40) == [f"--sim-build {'0' * 40}: the checkout {sim} is at commit {head}"]
    assert check("main") == ["--sim-build 'main' is neither a release tag vX.Y.Z nor a 40-hex commit"]


def test_harness_digest_is_a_sha256_or_unreleased():
    assert cli.check_harness_digest("sha256:" + "a" * 64) == [] and cli.check_harness_digest("unreleased") == []
    assert cli.check_harness_digest("latest") == ["--harness-digest 'latest' is neither sha256:<64 hex> nor unreleased"]
    assert cli.check_harness_digest(None)[0].startswith("--harness-digest is required")


def test_units_select_the_points_of_the_pull_and_name_those_it_does_not_hold(tmp_path):
    a, b, c_ = "a" * 64, "b" * 64, "c" * 64
    units = tmp_path / "units.txt"
    units.write_text(f"{a}\n{c_}\n")
    pts = [{"point_id": a}, {"point_id": b}]
    chosen, rec = cli.select_units(pts, str(units))
    assert chosen == [{"point_id": a}]
    assert rec["count"] == 2 and rec["not_in_pull"] == [c_] and len(rec["sha256"]) == 64
    assert cli.select_units(pts, None) == (pts, None)


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
    0.32.0, in a checkout at v0.16.0; the catalog and registry at release tags; and a pull of no
    points."""
    sim = tmp_path / "sim"
    _tagged_repo(sim, "v0.16.0")
    (sim / "go.mod").write_text("module x\n")
    (sim / "stack.json").write_text(json.dumps({"kind": "Stack", "engines": [{"kind": "vllm", "version": "0.32.0"}]}))
    blis = fake_blis(sim / "blis", {"fields --engine vllm --json": [0, json.dumps(FIELD_LIST), ""],
                                    "metrics --json": [0, json.dumps({"metrics": list(REGISTRY.values())}), ""],
                                    **commands})
    for r in ("cat", "reg"):
        _tagged_repo(tmp_path / r, "v1.0.0")
    _agentx_corpora(tmp_path / "cat", tmp_path / "corpora")
    (tmp_path / "pull").mkdir()
    pl.write_manifest(tmp_path / "pull", {"window": ["", ""], "pulled_at": "2026-10-23T00:00:00Z",
                                          "vllm_ref": "v0.32.0", "vllm_max_distance": 0}, [])
    return types.SimpleNamespace(
        pull=str(tmp_path / "pull"), out=str(tmp_path / "contract"), blis=str(blis), catalog=str(tmp_path / "cat"),
        registry=str(tmp_path / "reg"), stack=None, sim_build=None, harness_digest="unreleased", units=None,
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


def test_a_score_run_whose_blis_defines_tpot_otherwise_is_refused_before_scoring(tmp_path, monkeypatch):
    # DEV-8: the measured mean TPOT is over requests; a simulator whose tpot_mean_ms pools over
    # tokens is not compared with it.
    pooled = dict(REGISTRY["tpot_mean_ms"], population="tokens")
    a = _score_inputs(tmp_path, {"metrics --json": [0, json.dumps({"metrics": [REGISTRY["ttft_mean_ms"], pooled]}), ""]})
    import score
    monkeypatch.setattr(score, "score_points", lambda *x, **k: (_ for _ in ()).throw(AssertionError("scored")))
    msgs = []
    monkeypatch.setattr(cli, "_log", msgs.append)
    assert cli.cmd_score(a) == 2
    assert "FATAL: the simulator's tpot_mean_ms has population 'tokens'; the InferenceX client's has " \
           "'requests_min_2_output_tokens'" in msgs, msgs


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
                      "--harness-digest", "unreleased", "--corpus-dir", "d", flag, "x"])


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


def test_a_score_run_whose_blis_has_no_metrics_command_is_refused(tmp_path, monkeypatch):
    a = _score_inputs(tmp_path, {"metrics --json": [2, "", "unknown command \"metrics\""]})
    msgs = []
    monkeypatch.setattr(cli, "_log", msgs.append)
    assert cli.cmd_score(a) == 2
    assert any("blis metrics --json exited 2" in m for m in msgs), msgs


def test_a_score_run_with_the_clients_definitions_scores(tmp_path, monkeypatch):
    a = _score_inputs(tmp_path, {})
    import score
    seen = []
    monkeypatch.setattr(score, "score_points", lambda points, *x, **k: seen.append(points) or [])
    monkeypatch.setattr(score, "write_contract", lambda *x: None)
    import contract
    monkeypatch.setattr(contract, "validate_dir", lambda d: [])
    assert cli.cmd_score(a) == 0 and seen == [[]]


@pytest.mark.parametrize("printed,match", [
    ({"metrics": [{"id": "x"}]}, "not a definition"),
    ({"metrics": [dict(REGISTRY["ttft_mean_ms"], extra=1)]}, "not a definition"),
    ({"metrics": [REGISTRY["ttft_mean_ms"], REGISTRY["ttft_mean_ms"]]}, "defined twice"),
    ([REGISTRY["ttft_mean_ms"]], "not {\"metrics\""),
])
def test_the_metric_registry_client_refuses_another_shape(tmp_path, printed, match):
    import blis_commands
    blis = fake_blis(tmp_path / "blis", {"metrics --json": [0, json.dumps(printed), ""]})
    with pytest.raises(blis_commands.CommandError, match=match):
        blis_commands.metrics(str(blis))
