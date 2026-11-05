"""Tests for result.py: reading and validating the Result document blis writes on standard
output (SUB-19, DEV-8, DEV-9). No simulator: a fake `blis schema validate` stands in.

Run: python3 -m pytest orchestrator/ingest/test_result.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import result  # noqa: E402

COUNTS = {"generated": 10, "completed": 10, "timed_out": 0, "in_flight_at_horizon": 0, "queued_at_horizon": 0,
          "not_started": 0, "length_capped": 0}


def _doc(**over) -> dict:
    d = {"kind": "Result", "schema_version": 2, "name": "x", "requests": dict(COUNTS),
         "metrics": {"ttft_mean_ms": {"value": 12.5, "samples": 10}, "tpot_mean_ms": {"value": 3, "samples": 9}}}
    d.update(over)
    return d


def _validator(tmp: Path, code: int) -> str:
    p = tmp / "blis"
    p.write_text(f"#!/bin/sh\n[ \"$1 $2 $3\" = 'schema validate result' ] || exit 2\n"
                 f"[ -f \"$4\" ] || exit 2\necho 'requests.generated: bad' >&2\nexit {code}\n")
    p.chmod(0o755)
    return str(p)


def _runner(rc: int, stdout: str, stderr: str = ""):
    def run(argv, *, timeout, cwd):
        return subprocess.CompletedProcess(argv, rc, stdout, stderr)
    return run


# ------------------------------------------------------------------ parse

def test_parse_reads_a_schema_version_2_result():
    assert result.parse(json.dumps(_doc()).encode())["name"] == "x"


@pytest.mark.parametrize("doc", [{"kind": "Scenario", "schema_version": 2}, [1, 2], "x"])
def test_parse_refuses_another_kind(doc):
    with pytest.raises(result.ResultError) as e:
        result.parse(json.dumps(doc).encode())
    assert e.value.slug == "result_unreadable"


@pytest.mark.parametrize("version", [1, 3, None, "2"])
def test_parse_refuses_another_schema_version(version):
    with pytest.raises(result.ResultError) as e:
        result.parse(json.dumps(_doc(schema_version=version)).encode())
    assert e.value.slug == "result_schema_version"


def test_parse_refuses_text_that_is_not_json():
    with pytest.raises(result.ResultError) as e:
        result.parse(b"time=... level=info msg=done")
    assert e.value.slug == "result_unreadable"


# ------------------------------------------------------------------ figure

def test_figure_reads_a_metric_by_its_registry_id():
    assert result.figure(_doc(), result.TTFT_MEAN_MS) == 12.5
    assert result.figure(_doc(), result.TPOT_MEAN_MS) == 3.0


def test_figure_refuses_a_missing_metric():
    with pytest.raises(result.ResultError) as e:
        result.figure(_doc(metrics={"ttft_mean_ms": {"value": 1.0, "samples": 1}}), result.TPOT_MEAN_MS)
    assert e.value.slug == "metrics_incomplete" and "tpot_mean_ms" in str(e.value)


def test_figure_refuses_a_run_with_no_metrics_and_names_the_failed_acceptance():
    doc = _doc(frame={"acceptance": [{"condition": "achieved_concurrency_within", "threshold": 0.05,
                                      "observed": 0.2, "met": False}]})
    del doc["metrics"]
    with pytest.raises(result.ResultError) as e:
        result.figure(doc, result.TTFT_MEAN_MS)
    assert "achieved_concurrency_within" in str(e.value)


@pytest.mark.parametrize("value", [None, "12.5", True])
def test_figure_refuses_a_value_that_is_not_a_number(value):
    with pytest.raises(result.ResultError):
        result.figure(_doc(metrics={"ttft_mean_ms": {"value": value, "samples": 1}}), result.TTFT_MEAN_MS)


# ------------------------------------------------------------------ requests_complete

def test_requests_complete_accepts_every_request_completed():
    result.requests_complete(_doc(), 10)


@pytest.mark.parametrize("counts", [
    {"completed": 9, "dropped": {"unservable": 1}},
    {"completed": 9, "dropped": {"routing_rejected": 1}},
    {"completed": 9, "timed_out": 1},
    {"completed": 9, "in_flight_at_horizon": 1},
    {"completed": 9, "queued_at_horizon": 1},
    {"completed": 9, "not_started": 1},
    {"length_capped": 1},
    {"generated": 11, "completed": 11},
    {"generated": 9, "completed": 9},
    {"generated": 11, "not_started": 1},
], ids=["dropped-unservable", "dropped-routing", "timed_out", "in_flight", "queued", "not_started",
        "length_capped", "more_generated", "fewer_generated", "generated_beyond_sent"])
def test_requests_complete_refuses_each_fate_but_completed(counts):
    with pytest.raises(result.ResultError) as e:
        result.requests_complete(_doc(requests={**COUNTS, **counts}), 10)
    assert e.value.slug == "requests_incomplete"


def test_rows_refuses_a_result_without_request_rows():
    with pytest.raises(result.ResultError) as e:
        result.rows(_doc())
    assert e.value.slug == "request_rows_missing"
    assert result.rows(_doc(request_rows=[])) == []


# ------------------------------------------------------------------ reports

def test_engine_report_and_kernel_report():
    doc = _doc(reports={"engine": {"cluster": {"kv_capacity_tokens_per_replica": 512}}, "kernel": {"a": 1}})
    assert result.engine_report(doc, "kv_capacity_tokens_per_replica") == 512
    assert result.engine_report(_doc(), "kv_capacity_tokens_per_replica") is None
    assert result.kernel_report(doc) == {"a": 1}
    assert result.kernel_report(_doc()) is None


# ------------------------------------------------------------------ run and validate

def test_run_validates_and_returns_the_document(tmp_path):
    raw = json.dumps(_doc())
    doc, got, stderr = result.run(["blis", "replay"], blis=_validator(tmp_path, 0), runner=_runner(0, raw, "warn"))
    assert doc["name"] == "x" and got == raw.encode() and stderr == "warn"


def test_run_refuses_a_result_that_does_not_validate(tmp_path):
    with pytest.raises(result.ResultError) as e:
        result.run(["blis", "replay"], blis=_validator(tmp_path, 1), runner=_runner(0, json.dumps(_doc())))
    assert e.value.slug == "result_invalid" and "requests.generated" in str(e.value)


def test_run_refuses_when_the_validator_cannot_run(tmp_path):
    with pytest.raises(result.ResultError) as e:
        result.run(["blis", "replay"], blis=_validator(tmp_path, 2), runner=_runner(0, json.dumps(_doc())))
    assert e.value.slug == "result_validate_failed"


def test_run_raises_run_failed_with_the_simulators_stderr(tmp_path):
    with pytest.raises(result.RunFailed) as e:
        result.run(["blis", "replay"], blis=_validator(tmp_path, 0), runner=_runner(1, "", 'level=fatal msg="no"'))
    assert e.value.stderr == 'level=fatal msg="no"'


def _report(*methods):
    return {"selected_entries": {"coefficients": [
        {"set": "cost-model-attention", "name": f"c{i}", "method": m, "scope": {}, "file": "f.yaml"}
        for i, m in enumerate(methods)]}}


def test_measured_and_calibrated_coefficients_name_no_substitution():
    assert result.coefficient_substitutions(_report("measured", "calibrated", "not_charged")) == []
    assert result.coefficient_substitutions({"selected_entries": {}}) == []


@pytest.mark.parametrize("method", ["transferred", "literature", "vendor_spec", "roofline", "assumed"])
def test_each_weaker_coefficient_method_is_a_named_g2_substitution(method):
    assert result.coefficient_substitutions(_report("measured", method)) == [
        {"kind": "coefficient_method", "subject": "cost-model-attention/c1", "detail": method}]


def test_a_result_without_the_selected_entry_report_is_never_g1():
    assert result.coefficient_substitutions({}) == [
        {"kind": "coefficient_method", "subject": "selected-entry report", "detail": "not read"}]


def test_an_unknown_coefficient_method_is_refused():
    with pytest.raises(result.ResultError) as e:
        result.coefficient_substitutions(_report("divined"))
    assert e.value.slug == "coefficient_method_unknown"
