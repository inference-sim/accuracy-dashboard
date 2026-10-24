"""cli.py nightly's wiring: it builds the real pull/score/build closures and hands them to
run_night. BLIS and the network aren't available here, so cmd_pull/cmd_score/build_summary_v2 are
monkeypatched to cheap fakes -- this checks the glue (arg plumbing, store/data/state paths, the
pull-failure-stops-the-run rule), not the scoring, which test_score_e2e covers.
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


def _args(tmp, **over):
    a = dict(blis_tag="v0.12.0", store_dir=str(tmp / "store"), data_dir=str(tmp / "data"),
             state=str(tmp / "state.json"), window_days=180, keep_api=5, today="2026-10-23",
             cache=None, work=str(tmp / "contract"), score_work=None, evaluator_commit="abc",
             blis_dir=str(tmp / "sim"), catalog=str(tmp / "cat"), registry=str(tmp / "reg"),
             defaults_helper=str(tmp / "helper"), corpus=str(tmp / "corpus.json"),
             corpus_sha256=None, corpus_dataset="d", corpus_revision="main", corpus_cache=None,
             timeout=7200)
    a.update(over)
    return types.SimpleNamespace(**a)


def _seed_store(store: Path, rows):
    store.mkdir(parents=True, exist_ok=True)
    points = []
    for model, conc, md in rows:
        ident = {"model": model, "hardware": "h100", "precision": "fp8", "framework": "vllm",
                 "benchmark_type": "agentic_traces", "recipe": f"r-{model}-{conc}", "conc": conc,
                 "measured_date": md}
        pid = c.point_id(ident)
        (store / "points" / pid).mkdir(parents=True, exist_ok=True)
        points.append({"point_id": pid, "identity": ident, "row": {"model": model}, "files": {}})
    pl.write_manifest(store, {"window": ["", "2026-10-23"], "pulled_at": "2026-10-23T00:00:00Z"}, points)


def test_nightly_seeds_then_freezes_a_snapshot(tmp_path, monkeypatch):
    rows = [("m", 1, "2026-10-01"), ("m", 2, "2026-10-01")]

    def fake_pull(a):
        _seed_store(Path(a.out), rows)
        return 0

    def fake_score(a):
        # write a minimal contract the fake build reads back via build_summary_v2
        Path(a.out).mkdir(parents=True, exist_ok=True)
        return 0

    def fake_build(contract_dir, *, generated_at, evaluator_commit):
        m = pl.load_prior_manifest(tmp_path / "store")
        return {"schema_version": 2, "snapshot_id": "2026-10-23_blis-v0.12.0_ix-api-2026-10-23",
                "provenance": {"ingest": "api", "blis": {"release": "v0.12.0"},
                               "ground_truth": {"release_tag": "api-2026-10-23"}},
                "coverage": {"scored": len(m["points"]), "not_scored": 0}, "matrix": [], "not_scored": []}

    monkeypatch.setattr(cli, "cmd_pull", fake_pull)
    monkeypatch.setattr(cli, "cmd_score", fake_score)
    import build_summary_v2
    monkeypatch.setattr(build_summary_v2, "build", fake_build)

    rc = cli.cmd_nightly(_args(tmp_path))
    assert rc == 0
    # The seed froze a snapshot and wrote the live view + state.
    idx = json.loads((tmp_path / "data" / "index.json").read_text())
    assert idx["latest"] == "2026-10-23_blis-v0.12.0_ix-api-2026-10-23"
    assert (tmp_path / "data" / "latest" / "summary.json").is_file()
    assert (tmp_path / "data" / "snapshots" / idx["latest"] / "summary.json").is_file()
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["ingest"] == "api" and state["blis_tag"] == "v0.12.0"


def test_nightly_stops_when_the_pull_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "cmd_pull", lambda a: 4)   # a pull error
    with pytest.raises(RuntimeError, match="pull failed"):
        cli.cmd_nightly(_args(tmp_path))
