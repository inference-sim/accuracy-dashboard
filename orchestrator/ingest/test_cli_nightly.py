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


def _args(tmp, **over):
    a = dict(blis_tag="v0.12.0", work_dir=str(tmp / "work"), data_dir=str(tmp / "data"),
             state=str(tmp / "state.json"), window_days=180, keep_api=5, today="2026-10-23",
             cache=None, work=str(tmp / "contract"), score_work=str(tmp / "sw"), evaluator_commit="abc",
             blis=str(tmp / "sim" / "blis"), catalog=str(tmp / "cat"), registry=str(tmp / "reg"),
             fields=str(tmp / "fields.json"),
             corpus=str(tmp / "corpus.json"),
             corpus_sha256=None, corpus_dataset="d", corpus_revision="main", corpus_cache=None,
             timeout=7200, workers=1, download_workers=1, agentic_workers=1, max_rss_mb=0, stack=None,
             ledger=str(tmp / "ledger"))
    a.update(over)
    return types.SimpleNamespace(**a)


def _row(model, conc, md):
    return {"model": model, "hardware": "h100", "precision": "fp8", "framework": "vllm",
            "benchmark_type": "agentic_traces", "recipe_fingerprint": f"rf-{model}-{conc}-{md}",
            "conc": conc, "date": md, "id": str(conc * 100000 + int(md.replace("-", "")[2:])),
            "run_url": f"https://github.com/o/r/actions/runs/{conc}{md.replace('-', '')}/attempts/1"}


class Fakes:
    """Stand-ins for the network+BLIS steps, recording what cmd_nightly drove."""
    def __init__(self, rows):
        self.rows = rows
        self.pulled_only = None   # the --only list cmd_pull got (None = whole window)

    def api_pull(self, fetch, *, today, window_days, framework="vllm"):
        return types.SimpleNamespace(rows=self.rows)

    def ledger(self, tmp):
        # The ledger the night reads: one unit per row, written before each night.
        ledger_fake.write(tmp / "ledger", self.rows)

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

    def cmd_score(self, a):
        Path(a.out).mkdir(parents=True, exist_ok=True)
        (Path(a.out) / "provenance.json").write_text(json.dumps({"pulled_at": "2026-10-23T00:00:00Z"}))
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
    # Seed (no prior summary) -> whole window fetched, snapshot frozen, live view + state written.
    assert fakes.pulled_only is None                      # whole window, not a delta
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
    assert fakes.pulled_only is None                      # the whole window


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
    assert fakes.pulled_only is None

    # Night 2: identical window, same BLIS -> no new points. The delta is empty.
    cli.cmd_nightly(_args(tmp_path, today="2026-10-24"))
    assert fakes.pulled_only == []                         # the empty delta, NOT None (whole window)
    # and cmd_pull froze zero rows for that empty delta
    assert json.loads((tmp_path / "work" / "manifest.json").read_text())["points"] == []


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


def test_the_field_list_must_be_the_release_the_simulator_runs(tmp_path):
    p = tmp_path / "fields.json"
    p.write_text(json.dumps(FIELD_LIST))
    fl_, sha = cli.read_fields(str(p), "0.32.0")
    assert fl_.engine == {"kind": "vllm", "version": "0.32.0"} and len(sha) == 64
    import fields
    with pytest.raises(fields.FieldsError, match="the simulator runs vllm 0.31.0"):
        cli.read_fields(str(p), "0.31.0")
    with pytest.raises(fields.FieldsError, match="--fields is required"):
        cli.read_fields(None, "0.32.0")


def test_a_build_with_no_stack_json_is_refused_with_why(tmp_path):
    import stack
    (tmp_path / "sim").mkdir()
    with pytest.raises(stack.StackError, match="predates stack.json"):
        cli.read_stack(tmp_path / "sim" / "blis", None)
    s = tmp_path / "stack.json"
    s.write_text(json.dumps({"kind": "Stack", "engines": [{"kind": "vllm", "version": "0.32.0"}]}))
    assert cli.read_stack(tmp_path / "sim" / "blis", str(s)).engine("vllm") == "0.32.0"
