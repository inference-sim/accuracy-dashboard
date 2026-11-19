"""cli.py nightly's wiring (no-storage model): it lists the window, fetches+scores the delta, and
merges into the published summary. BLIS and the network aren't available here, so api.pull,
cmd_pull, run_harness and build_summary_v2 are monkeypatched to cheap fakes -- this checks the glue
(arg plumbing, work/data/state paths, the pull-failure-stops-the-run rule), not the scoring, which
test_score_e2e and test_nightly_run cover.
"""
import json
import shutil
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
                               "harness_commit": cli.harness_commit_now(),
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


def test_a_night_scored_by_another_harness_commit_rescores_the_whole_window_and_does_not_merge(tmp_path, monkeypatch):
    # A summary names one harness commit (X8) and validation refuses a point from another, so a
    # delta scored by a newer checkout cannot be merged into it: the whole window is rescored.
    rows = [_row("m", 1, "2026-10-01")]
    fakes = Fakes(rows)
    _install(monkeypatch, fakes, [ledger_fake.point_id(r) for r in rows])
    fakes.ledger(tmp_path)
    cli.cmd_nightly(_args(tmp_path))                       # seed, at the checkout's commit
    latest = tmp_path / "data" / "latest" / "summary.json"
    doc = json.loads(latest.read_text())
    doc["provenance"]["harness_commit"] = "f" * 40          # last night was scored by another commit
    latest.write_text(json.dumps(doc))
    new = _row("m", 2, "2026-10-02")
    fakes.rows = rows + [new]
    fakes.ledger(tmp_path)
    import build_summary_v2
    monkeypatch.setattr(build_summary_v2, "build_merged", lambda *a, **k: (_ for _ in ()).throw(AssertionError("merged")))
    cli.cmd_nightly(_args(tmp_path, today="2026-10-24"))
    assert sorted(fakes.pulled_only) == sorted(ledger_fake.point_id(r) for r in fakes.rows)   # the whole window


def test_same_harness_commit_is_the_only_one_a_summary_can_be_merged_with():
    here = cli.harness_commit_now()
    assert len(here) == 40
    assert cli.same_harness({"provenance": {"harness_commit": here}}, here)
    assert not cli.same_harness({"provenance": {"harness_commit": "e" * 40}}, here)
    assert not cli.same_harness({"provenance": {}}, here)
    assert not cli.same_harness(None, here)


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


def test_an_anchor_unit_the_window_holds_no_usable_row_of_is_g5_by_name_and_the_night_goes_on(tmp_path, monkeypatch):
    # COV-1: every anchor unit is graded or G5 with a reason. One the window's pull holds no row of is G5
    # not_in_pull_window; one whose row now differs from the ledger's record is G5 row_differs_from_ledger. Neither is
    # fetched, and the rest are scored and published.
    import pull as pl
    kept, gone, changed = _row("m", 1, "2026-10-01"), _row("m", 2, "2026-10-01"), _row("m", 4, "2026-10-01")
    fakes = Fakes([kept, gone, changed])
    _install(monkeypatch, fakes, [ledger_fake.point_id(kept)])
    fakes.ledger(tmp_path)
    fakes.rows = [kept, {**changed, "precision": "fp4"}]          # the window: one row gone, one changed
    real = fakes.cmd_pull

    def pull(a):
        fakes.rows = [kept]
        return real(a)
    monkeypatch.setattr(cli, "cmd_pull", pull)
    assert cli.cmd_nightly(_args(tmp_path)) == 0
    assert fakes.pulled_only == [ledger_fake.point_id(kept)]
    entries = {e["point_id"]: e["reasons"] for e in json.loads((tmp_path / "work" / "manifest.json").read_text())["points"]}
    assert entries == {ledger_fake.point_id(kept): [], ledger_fake.point_id(gone): [pl.NOT_IN_WINDOW],
                       ledger_fake.point_id(changed): [pl.ROW_DIFFERS]}


def test_an_anchor_unit_the_ledger_does_not_hold_stops_the_night_before_any_fetch(tmp_path, monkeypatch):
    # The anchor list names units the ledger lacks: the list and the ledger are not one release's, so the ledger is
    # unreadable for this night. It stops, naming the count, before any fetch.
    rows = [_row("m", 1, "2026-10-01")]
    fakes = Fakes(rows)
    fakes.anchors = [ledger_fake.point_id(rows[0]), "e" * 64, "f" * 64]
    _install(monkeypatch, fakes, [])
    fakes.ledger(tmp_path)
    monkeypatch.setattr(cli, "cmd_pull", lambda a: (_ for _ in ()).throw(AssertionError("pulled")))
    import ledger as ldg
    with pytest.raises(ldg.LedgerError, match=r"2 anchor units are not units of the ledger"):
        cli.cmd_nightly(_args(tmp_path))
    assert not (tmp_path / "data" / "latest").exists()


def test_an_unpulled_anchor_is_g5_in_the_contract_without_a_simulation(tmp_path):
    import pull as pl
    import score as sc
    entry = {"point_id": "u", "identity": {}, "row": {"framework": "vllm", "benchmark_type": "single_turn"},
             "reasons": [pl.NOT_IN_WINDOW], "files": {}}
    o = sc.score_point(entry, tmp_path, tmp_path / "w", sc.Env(
        blis="x", blis_release="v0.17.1", blis_commit="a" * 40, catalog=tmp_path, catalog_release="c",
        registry=tmp_path, registry_release="r", kernel="k", corpora={}))
    import assess as asx
    assert o.fidelity is None and o.reasons == [pl.NOT_IN_WINDOW]
    assert asx.g5_of(o.reasons[0]) == {"code": "value_not_recorded", "subject": "not_in_pull_window"}


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


def _pseudo(commit):
    return f"v0.15.1-0.20261118162118-{commit[:12]}"


def test_the_nightly_scores_a_stack_pinned_by_commit_as_it_scores_a_tag(tmp_path, monkeypatch):
    # The M3.1 release v0.18.1 pins blis-substrate by a Go pseudo-version. It is an exact pin (design X8: the number records what
    # it came from), so the night scores it, with the catalog and registry named by the pinned commit.
    rows = [_row("m", 1, "2026-10-01")]
    fakes = Fakes(rows)
    _install(monkeypatch, fakes, [ledger_fake.point_id(r) for r in rows])
    fakes.ledger(tmp_path)
    head = _head(tmp_path / "substrate")
    assert cli.cmd_nightly(_args(tmp_path, substrate_version=_pseudo(head), substrate_commit=head)) == 0
    cmd = fakes.harness_cmd
    assert cmd[cmd.index("--catalog-release") + 1] == head and cmd[cmd.index("--registry-release") + 1] == head


def test_the_nightly_still_stops_before_scoring_on_a_checkout_that_is_not_the_pinned_commit(tmp_path, monkeypatch):
    other = "1" * 40
    msgs = _nightly_refused(tmp_path, monkeypatch, substrate_version=_pseudo(other), substrate_commit=other)
    head = _head(tmp_path / "substrate")
    assert any("FATAL" in m and head in m and other in m and "pin is commit" in m for m in msgs), msgs


@pytest.mark.parametrize("version,commit,fragment", [
    ("v0.0.0-20261105035832-817e83e0018b", "", "pins no full 40-hex commit"),      # a pseudo-version with no commit
    ("v0.0.0-20261105035832-817e83e0018b", "1" * 40, "names the commit 817e83e0018b"),   # one that names another commit
    ("main", "1" * 40, "neither a release tag, a pseudo-version nor the pinned commit"),   # a branch
])
def test_the_nightly_stops_before_scoring_on_a_substrate_that_is_no_exact_pin(tmp_path, monkeypatch, version, commit, fragment):
    msgs = _nightly_refused(tmp_path, monkeypatch, substrate_version=version, substrate_commit=commit)
    assert any(m.startswith(f"FATAL: blis-substrate {version} in stack.json is not an exact pin") and fragment in m for m in msgs), msgs


def test_a_figure_is_experimental_when_it_used_an_overlay_or_is_not_exactly_pinned_and_not_when_pinned_by_commit():
    env = lambda **k: types.SimpleNamespace(**{"routers_dir": None, "assumed_router_revision": None,   # noqa: E731
                                               "router_policy_experiment": None, "speculative_fallback_category": None,
                                               "sim_build": "v0.18.1", "catalog_release": "a" * 40, "registry_release": "a" * 40, **k})
    assert cli.experimental_run(env()) is False                                   # a tag and commits: exact pins
    assert cli.experimental_run(env(sim_build="b" * 40, catalog_release="v0.15.0-rc1")) is False
    for overlay in ({"routers_dir": "/r"}, {"assumed_router_revision": "x"}, {"router_policy_experiment": "p"},
                    {"speculative_fallback_category": "c"}, {"catalog_release": "main"}, {"registry_release": "a" * 12}):
        assert cli.experimental_run(env(**overlay)) is True, overlay


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
    # A copy of the catalog and registry may carry no .git,
    # so check_blis_inputs takes the release names.
    sim = tmp_path / "sim"
    _tagged_repo(sim, "v0.16.0")
    (sim / "blis").write_text("")
    bare = tmp_path / "mount" / "catalog"
    (bare / "models").mkdir(parents=True)
    assert not (bare / ".git").exists()
    assert cli.check_blis_inputs(sim / "blis", "v1.0.0", "v2.3.4-rc1") == []
    assert cli.check_blis_inputs(sim / "blis", "a" * 40, "b" * 40) == []
    assert cli.check_blis_inputs(sim / "blis", None, "v1.0.0") == ["--catalog-release is required: the release tag or full 40-hex commit the data is at"]
    for bad in ("bad tag", "main", "m2/10-x", "e1a1d97", "A" * 40, "v1"):
        assert cli.check_blis_inputs(sim / "blis", "v1.0.0", bad) == [
            f"--registry-release {bad!r} is neither a release tag nor a full 40-hex commit"], bad


def test_a_release_build_over_mutable_data_names_is_refused_and_cannot_be_a_released_figure(tmp_path):
    """A branch name or `latest` names data that moves; with a tagged build it used to make a figure that
    looked released."""
    sim = tmp_path / "sim"
    _tagged_repo(sim, "v0.16.0")
    (sim / "blis").write_text("")
    bad = cli.check_blis_inputs(sim / "blis", "main", "latest", "v0.16.0")
    assert bad == ["--catalog-release 'main' is neither a release tag nor a full 40-hex commit",
                   "--registry-release 'latest' is neither a release tag nor a full 40-hex commit"]
    assert cli.check_blis_inputs(sim / "blis", "v0.13.0", "v0.13.0", "v0.16.0") == []


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


def test_resolve_blis_skips_a_superseded_release_once_its_patch_release_is_tagged(tmp_path):
    # COV-9 with stack.SUPERSEDED, through resolve_blis.sh and the real table: v0.16.0 and v0.17.0 can never be
    # scored (their substrates publish no anchor list). Until v0.17.1 is tagged the night keeps naming v0.16.0, so the
    # gap stays visible; once it is tagged, the night scores v0.17.1 and never lists the two it replaces.
    import shutil
    import subprocess
    import sys as _sys
    root = Path(__file__).resolve().parent.parent
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "python3").symlink_to(_sys.executable)
    shutil.copytree(root, tmp_path / "repo" / "orchestrator", ignore=shutil.ignore_patterns("testdata", "__pycache__"))
    state = tmp_path / "repo" / "state"
    state.mkdir()

    def run(tags, scored):
        rel = [{"tagName": t, "createdAt": f"2026-11-{10 + k:02d}"} for k, t in enumerate(tags)]
        (bin_ / "gh").write_text("#!/usr/bin/env python3\nimport json, sys\nrel = " + json.dumps(rel) + "\n"
                                 "print('\\n'.join(r['tagName'] for r in sorted(rel, key=lambda r: r['createdAt'])))\n")
        (bin_ / "gh").chmod(0o755)
        (state / "scored-releases.json").write_text(json.dumps({"kind": "ScoredReleases", "releases": scored}))
        out = tmp_path / "out"
        out.unlink(missing_ok=True)
        r = subprocess.run(["bash", str(tmp_path / "repo" / "orchestrator" / "resolve_blis.sh")],
                           env={"PATH": f"{bin_}:/usr/bin:/bin", "GITHUB_OUTPUT": str(out)}, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return dict(line.split("=", 1) for line in out.read_text().splitlines())

    before = ["v0.15.0", "v0.16.0", "v0.17.0"]
    assert run(before, ["v0.15.0"]) == {"blis_tags": "v0.16.0", "blis_tag": "v0.17.0", "more": "true"}
    after = before + ["v0.17.1"]
    assert run(after, ["v0.15.0"]) == {"blis_tags": "v0.17.1", "blis_tag": "v0.17.1", "more": "false"}
    # v0.17.1 published and listed: nothing is left, so the night scores the newest release's delta; the two it
    # replaced are still not listed as scored.
    assert run(after, ["v0.15.0", "v0.17.1"]) == {"blis_tags": "v0.17.1", "blis_tag": "v0.17.1", "more": "false"}
    assert json.loads((state / "scored-releases.json").read_text())["releases"] == ["v0.15.0", "v0.17.1"]


PUBLISH = Path(__file__).resolve().parent.parent / "nightly" / "publish.sh"


def _publish_repo(tmp_path):
    """A repository holding a committed data/ and state/, then a night's change to both, uncommitted."""
    import subprocess
    repo = tmp_path / "repo"
    (repo / "data").mkdir(parents=True)
    (repo / "state").mkdir()
    (repo / "data" / "index.json").write_text("{}")
    (repo / "state" / "last-run-api.json").write_text("{}")
    (repo / "state" / "scored-releases.json").write_text("{}")
    for cmd in (["init", "-q"], ["add", "-A"], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "base"]):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True)
    (repo / "data" / "index.json").write_text('{"night": 1}')
    return repo


def _commits(repo) -> int:
    import subprocess
    return int(subprocess.run(["git", "-C", str(repo), "rev-list", "--count", "HEAD"], capture_output=True, text=True, check=True).stdout)


def _publish(repo, checks_body: str, *args):
    import os
    import subprocess
    checks = repo.parent / "checks.sh"
    checks.write_text("#!/usr/bin/env bash\n" + checks_body)
    env = {**os.environ, "PUBLISH_CHECKS": str(checks), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["bash", str(PUBLISH), *args], cwd=repo, env=env, capture_output=True, text=True)


def test_a_night_whose_check_fails_commits_nothing(tmp_path):
    repo = _publish_repo(tmp_path)
    before = _commits(repo)
    r = _publish(repo, "echo 'boundary: 157 ids in the map, not published' >&2; exit 7", "api-nightly: v0.18.0 [skip ci]")
    assert r.returncode == 7 and "boundary" in r.stderr
    assert _commits(repo) == before
    # The night's data is still in the working tree, unstaged: nothing landed and nothing was lost.
    assert (repo / "data" / "index.json").read_text() == '{"night": 1}'


def test_a_night_whose_checks_all_pass_commits_once_with_its_message(tmp_path):
    import subprocess
    repo = _publish_repo(tmp_path)
    before = _commits(repo)
    r = _publish(repo, "exit 0", "api-nightly: v0.18.0 2026-11-17 [skip ci]")
    assert r.returncode == 0, r.stderr
    assert _commits(repo) == before + 1
    log = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%s"], capture_output=True, text=True).stdout.strip()
    assert log == "api-nightly: v0.18.0 2026-11-17 [skip ci]"


def test_a_night_that_changes_nothing_reports_it_and_commits_nothing(tmp_path):
    import subprocess
    repo = _publish_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--", "data"], check=True)
    before = _commits(repo)
    r = _publish(repo, "exit 0", "msg")
    assert r.returncode == 10 and _commits(repo) == before


def test_a_dry_run_runs_the_checks_and_commits_nothing(tmp_path):
    repo = _publish_repo(tmp_path)
    before = _commits(repo)
    assert _publish(repo, "exit 0", "--dry-run", "unused").returncode == 0 and _commits(repo) == before
    assert _publish(repo, "exit 3", "--dry-run", "unused").returncode == 3


def test_the_workflow_publishes_through_the_script(tmp_path):
    import yaml
    wf = yaml.safe_load((Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "api-nightly.yml").read_text())
    run = next(s for s in wf["jobs"]["publish"]["steps"] if s.get("id") == "pub")["run"]
    assert "orchestrator/nightly/publish.sh" in run and "git commit" not in run


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


def _publish_step(tmp_path, dry_run):
    """Run the publish job's publish step as the runner would, in a scratch checkout holding a night's incoming data,
    with a fake git that records its calls. Returns (exit status, output, git calls, GITHUB_OUTPUT)."""
    import re
    import subprocess
    import yaml
    wf = yaml.safe_load((Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "api-nightly.yml").read_text())
    step = next(s for s in wf["jobs"]["publish"]["steps"] if s.get("id") == "pub")
    env_expr = step["env"]["DRY_RUN"]
    assert env_expr == "${{ inputs.dry_run && 'true' || 'false' }}", env_expr
    script = re.sub(r"\$\{\{[^}]*\}\}", "v0.17.1", step["run"])
    work = tmp_path / "checkout"
    (work / "newdata" / "latest").mkdir(parents=True)
    (work / "newdata" / "index.json").write_text("{}")
    (work / "newdata" / "latest" / "summary.json").write_text(json.dumps(
        {"snapshot_id": "2026-11-17_blis-v0.17.1_ix-api-2026-11-17", "coverage": {"points": 3, "graded": 2, "by_grade": {"G4": 2, "G5": 1}}}))
    (work / "incoming" / "state").mkdir(parents=True)
    (work / "incoming" / "state" / "last-run-api.json").write_text("{}")
    (work / "incoming" / "state" / "scored-releases.json").write_text(json.dumps({"kind": "ScoredReleases", "releases": ["v0.17.1"]}))
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    # `git diff --cached --quiet` exits 1: the night staged a change, so publish.sh commits it.
    (bin_ / "git").write_text(f"#!/bin/sh\necho \"$@\" >> {tmp_path / 'git.calls'}\ncase \"$1\" in diff) exit 1;; esac\n")
    (bin_ / "git").chmod(0o755)
    import sys as _sys
    (bin_ / "python3").symlink_to(_sys.executable)
    out = tmp_path / "gh_output"
    # The real publish.sh, with its checks stubbed to pass (the script's own behaviour is tested above).
    (work / "orchestrator" / "nightly").mkdir(parents=True)
    shutil.copy(PUBLISH, work / "orchestrator" / "nightly" / "publish.sh")
    (tmp_path / "pass.sh").write_text("exit 0\n")
    r = subprocess.run(["bash", "-c", script], cwd=work, capture_output=True, text=True,
                       env={"PATH": f"{bin_}:/usr/bin:/bin", "GITHUB_OUTPUT": str(out), "GITHUB_REF_NAME": "main",
                            "PUBLISH_CHECKS": str(tmp_path / "pass.sh"),
                            "DRY_RUN": "true" if dry_run else "false", "RELEASE": "v0.17.1"})
    calls = (tmp_path / "git.calls").read_text().splitlines() if (tmp_path / "git.calls").exists() else []
    return r.returncode, r.stdout + r.stderr, calls, out.read_text() if out.exists() else ""


def test_a_dry_run_validates_prints_what_it_would_publish_and_pushes_nothing(tmp_path):
    rc, text, calls, output = _publish_step(tmp_path, dry_run=True)
    assert rc == 0, text
    assert calls == [] and "pushed=false" in output
    for want in ("DRY RUN: would publish", "snapshot_id: 2026-11-17_blis-v0.17.1_ix-api-2026-11-17", "release: v0.17.1",
                 "points: 3, graded: 2", '"G4": 2', '"G5": 1'):
        assert want in text, (want, text)


def test_a_run_that_is_not_a_dry_run_commits_and_pushes_as_before(tmp_path):
    rc, text, calls, output = _publish_step(tmp_path, dry_run=False)
    assert rc == 0, text
    assert any(c.startswith("commit ") for c in calls) and "push" in calls and "pushed=true" in output
    assert "DRY RUN" not in text


def test_the_pages_deploy_and_the_next_run_follow_only_a_push():
    import yaml
    wf = yaml.safe_load((Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "api-nightly.yml").read_text())
    steps = {s.get("name"): s for s in wf["jobs"]["publish"]["steps"]}
    for name in ("Deploy the published data to Pages", "Score the next unscored release"):
        assert "steps.pub.outputs.pushed == 'true'" in steps[name]["if"], name
    assert wf[True]["workflow_dispatch"]["inputs"]["dry_run"] == {
        "description": "Validate and print what would be published, and publish nothing", "type": "boolean", "default": False}


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
    # harness/run.sh accepts vMAJOR.MINOR.PATCH-suffix; check_blis_inputs must agree. A suffixed tag is an exact pin like any
    # other, so a figure at one is not experimental on that account.
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
    0.32.0, in a checkout at v0.16.0; the catalog and registry as a copy without .git has them,
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


def test_a_repository_two_catalog_entries_claim_does_not_stop_the_night(tmp_path, monkeypatch):
    # Two entries claim org/m, and `blis catalog resolve --model org/m` refuses it. The night's catalog check asks
    # each entry by name and does not ask that repository: each run is matched to the entry its deployment is, and a
    # run that matches none is G5 catalog_entry_ambiguous (test_drafter.py). So the night goes on to the pull.
    fakes = Fakes([_row("m", 1, "2026-10-01")])
    _install(monkeypatch, fakes, [])
    fakes.ledger(tmp_path)
    models = {"a": "org/m", "b": "org/m"}
    cat = write_catalog(tmp_path / "cat", models)
    refusal = 'Error: model "org/m" is the source repository of 2 catalog entries (a, b); name the entry instead'
    present = {d.name: d.name for d in (cat / "models").iterdir() if d.name not in models}   # the fixture's own entries
    answers = {**resolves(cat, present), **resolves(cat, models),
               f"catalog resolve --catalog {cat} --model org/m --json": [1, "", refusal]}
    fake_blis(tmp_path / "sim" / "blis", answers)
    pulled = []
    monkeypatch.setattr(cli, "cmd_pull", lambda a: pulled.append(a) or 1)
    msgs = []
    monkeypatch.setattr(cli, "_log", msgs.append)
    import pytest
    with pytest.raises(RuntimeError, match="pull failed"):     # the fake pull fails: the night got past the check
        cli.cmd_nightly(_args(tmp_path))
    assert pulled, msgs
    assert not any("catalog" in m and "FATAL" in m for m in msgs), msgs
    saw = [json.loads(x) for x in (tmp_path / "sim" / "blis.saw").read_text().splitlines()]
    assert ["catalog", "resolve", "--catalog", str(cat), "--model", "org/m", "--json"] not in saw


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
                      "--catalog-release", "v1.0.0", "--registry-release", "v1.0.0", "--harness-commit", "c" * 40,
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
