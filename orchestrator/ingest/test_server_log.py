"""The API's /server-log: a 413 is a fact about the source's data (a G5 value_not_recorded the
backlog lists); any other HTTP error is a fault of the run.

Run: python3 -m pytest orchestrator/ingest/test_server_log.py
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

def _freeze_single_turn(tmp, fetch):
    import types
    import ledger as ldg
    import ledger_fake
    import pull as pl
    row = {"id": "433032", "model": "m", "hardware": "h200", "precision": "fp8", "framework": "vllm",
           "benchmark_type": "single_turn", "conc": 4, "isl": 1024, "osl": 1024, "disagg": False,
           "is_multinode": False, "date": "2026-10-01", "image": "vllm/vllm-openai:v0.31.0",
           "run_url": "https://github.com/other/repo/actions/runs/1", "metrics": {"mean_ttft": 0.2}}
    lg = ldg.load(ledger_fake.write(tmp / "ledger", [row]))
    (point,) = pl.place([row], lg).points
    resolver = types.SimpleNamespace(resolve=lambda image, log: types.SimpleNamespace(record=lambda: {"image": image}))
    gh = types.SimpleNamespace(repo="SemiAnalysisAI/InferenceX")
    return pl.freeze_point(point, resolver=resolver, gh=gh, fetch=fetch, out=tmp / "out")


def _http_error(code):
    import io
    import urllib.error
    return urllib.error.HTTPError("https://api/server-log?id=433032", code, "x", {}, io.BytesIO(b""))


def test_a_413_on_server_log_is_a_data_issue_listed_as_value_not_recorded(tmp_path):
    import assess as asx

    def fetch(url):
        raise _http_error(413)
    entry = _freeze_single_turn(tmp_path, fetch)
    assert entry["reasons"] == ["server_log_missing:api_413"]
    assert "server_log" not in entry["files"]
    assert asx.g5_of("server_log_missing:api_413") == {"code": "value_not_recorded", "subject": "api_413"}


def test_the_413_point_is_g5_value_not_recorded_with_one_reason(tmp_path):
    import score as sc
    entry = _freeze_single_turn(tmp_path, lambda url: (_ for _ in ()).throw(_http_error(413)))
    o = sc.score_point(entry, tmp_path / "pull", tmp_path / "w", sc.Env(
        blis="x", blis_release="v0.16.0", blis_commit="a" * 40, catalog=tmp_path, catalog_release="c",
        registry=tmp_path, registry_release="r", kernel="k", corpora={}))
    assert o.fidelity is None and o.reasons == ["server_log_missing:api_413"]


def test_any_other_http_error_on_server_log_stays_a_run_fault(tmp_path):
    import urllib.error

    def fetch(url):
        raise _http_error(500)
    with pytest.raises(urllib.error.HTTPError) as e:
        _freeze_single_turn(tmp_path, fetch)
    assert e.value.code == 500
