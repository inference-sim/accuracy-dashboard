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


# ttft_mean_ms and tpot_mean_ms as blis-substrate contracts/metrics (800ae263) defines them,
# under the JSON names of its Definition.
SCOPES = {"scopes": ["cluster", "pool", "instance"], "aggregates": ["max", "min"]}
REGISTRY = {
    "ttft_mean_ms": {"id": "ttft_mean_ms", "formula": "ttft", "statistic": "mean", "population": "requests",
                     "window": "measured", "unit": "ms", "unfinished": "excluded", **SCOPES,
                     "better": "lower_is_better",
                     "description": "Time to first token, mean, over the measured window.",
                     "follows": "vllm v0.32.0 vllm/benchmarks/serve.py:624-634"},
    "tpot_mean_ms": {"id": "tpot_mean_ms", "formula": "tpot", "statistic": "mean",
                     "population": "requests_min_2_output_tokens", "window": "measured", "unit": "ms",
                     "unfinished": "excluded", **SCOPES, "better": "lower_is_better",
                     "description": "Time per output token, excluding the first, computed per request, mean, "
                                    "over the measured window.",
                     "follows": "vllm v0.32.0 vllm/benchmarks/serve.py:624-634"},
}


def test_the_registrys_ttft_and_tpot_means_are_the_clients():
    assert result.check_definitions(REGISTRY) == []


@pytest.mark.parametrize("metric,key,value", [
    ("ttft_mean_ms", "statistic", "p50"),
    ("ttft_mean_ms", "window", "run"),
    ("tpot_mean_ms", "population", "tokens"),     # pooled over tokens: inter-token latency, not TPOT
    ("tpot_mean_ms", "formula", "itl"),
    ("tpot_mean_ms", "unit", "s"),
    ("tpot_mean_ms", "unfinished", "not_applicable"),
    ("ttft_mean_ms", "percentile_method", "numpy_linear"),
])
def test_a_definition_other_than_the_clients_is_refused_naming_the_field(metric, key, value):
    reg = {k: dict(v) for k, v in REGISTRY.items()}
    reg[metric][key] = value
    assert result.check_definitions(reg) == [
        f"the simulator's {metric} has {key} {value!r}; the InferenceX client's has "
        f"{result.CLIENT_DEFINITIONS[metric][key]!r}"]


def test_a_registry_without_a_metric_the_harness_reads_is_refused():
    assert result.check_definitions({"ttft_mean_ms": REGISTRY["ttft_mean_ms"]}) == [
        "the simulator's metric registry has no tpot_mean_ms"]


# ---- the other figures: a rate or an interactivity is compared only with the same scope and aggregate
# (readiness analysis of 2026-11-11, section 6; the ids and keys are those of blis-substrate#52, layer 7, 41ae65f)

def _registry_with(metric, **over):
    base = dict(result.CLIENT_RATE_DEFINITIONS[metric])
    base.update(SCOPES)
    base.update(over)
    return {metric: {"id": metric, **base}}


@pytest.mark.parametrize("metric", sorted(result.CLIENT_RATE_DEFINITIONS))
def test_a_rate_or_interactivity_with_the_clients_definition_is_comparable(metric):
    assert result.check_definitions(_registry_with(metric), compared=(metric,)) == []


@pytest.mark.parametrize("metric,key,value", [
    # output tokens against total tokens: the plotted axis differs by two orders of magnitude on AgentX
    ("total_tokens_per_second_per_gpu", "formula", "output_throughput"),
    # all the deployment's GPUs against the decode GPUs of a disaggregated run, and the reverse
    ("total_tokens_per_second_per_gpu", "denominator", "window_and_decode_gpus"),
    ("output_tokens_per_second_per_decode_gpu", "denominator", "window_and_gpus"),
    # a rate per window against a rate with no GPU denominator
    ("total_tokens_per_second_per_gpu", "denominator", "window"),
    # 1 / mean(ITL) against the mean of 1 / ITL (interactivity_mean's formula; 2% to 27% apart on TP8 H200)
    ("interactivity_of_mean_tpot", "formula", "user_tps"),
    ("interactivity_of_mean_tpot", "statistic", "p50"),
])
def test_a_known_bad_definition_is_refused_naming_the_field(metric, key, value):
    reg = _registry_with(metric, **{key: value})
    got = result.check_definitions(reg, compared=(metric,))
    assert got == [f"the simulator's {metric} has {key} {value!r}; the InferenceX client's has "
                   f"{result.CLIENT_RATE_DEFINITIONS[metric][key]!r}"]


def test_a_registry_that_names_a_figure_by_another_scope_is_refused_not_matched_by_name():
    # The registry today has output_tok_s_per_gpu (output tokens over every GPU) and interactivity_mean
    # (the mean of 1/ITL); neither is the client's figure, and no registry record is looked up by a
    # similar name.
    reg = {"output_tok_s_per_gpu": {"id": "output_tok_s_per_gpu", "formula": "output_throughput"},
           "interactivity_mean": {"id": "interactivity_mean", "formula": "user_tps", "statistic": "mean"}}
    for metric in ("total_tokens_per_second_per_gpu", "interactivity_of_mean_tpot"):
        assert result.check_definitions(reg, compared=(metric,)) == [f"the simulator's metric registry has no {metric}"]


def test_a_figure_with_no_client_definition_is_not_compared():
    assert result.check_definitions(REGISTRY, compared=("goodput",)) == [
        "the harness has no client definition for goodput: it is not compared"]
    assert result.COMPARED_FIGURES == ("ttft_mean_ms", "tpot_mean_ms")


# ---- score calls it

def _fake_blis(tmp_path, body: str) -> Path:
    p = tmp_path / "blis"
    p.write_text("#!/usr/bin/env python3\nimport sys, json\n" + body)
    p.chmod(0o755)
    return p


def test_score_refuses_a_simulator_whose_ttft_or_tpot_is_not_the_clients(tmp_path):
    import cli
    bad = {k: dict(v) for k, v in REGISTRY.items()}
    bad["tpot_mean_ms"]["population"] = "tokens"
    blis = _fake_blis(tmp_path, f"print(json.dumps({{'metrics': {json.dumps(list(bad.values()))}}}))\n")
    assert cli.check_metric_definitions(blis) == [
        "the simulator's tpot_mean_ms has population 'tokens'; the InferenceX client's has 'requests_min_2_output_tokens'"]
    good = _fake_blis(tmp_path, f"print(json.dumps({{'metrics': {json.dumps(list(REGISTRY.values()))}}}))\n")
    assert cli.check_metric_definitions(good) == []


def test_a_build_without_blis_metrics_is_not_refused_and_other_failures_are(tmp_path, capsys):
    import cli
    old = _fake_blis(tmp_path, "sys.stderr.write('Error: unknown command \"metrics\" for \"blis\"\\n'); sys.exit(1)\n")
    assert cli.check_metric_definitions(old) == []
    assert "not checked" in capsys.readouterr().err
    broken = _fake_blis(tmp_path, "sys.stderr.write('panic'); sys.exit(2)\n")
    assert cli.check_metric_definitions(broken) and "panic" in cli.check_metric_definitions(broken)[0]


def test_cmd_score_runs_the_definition_check():
    import ast
    tree = ast.parse((Path(__file__).parent / "cli.py").read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "cmd_score")
    calls = {getattr(c.func, "id", None) for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "check_metric_definitions" in calls


# ---- the exact comparison: every meaning field, and the scope the figure is defined at

def test_ttft_and_tpot_are_compared_in_every_meaning_field_including_the_empty_ones():
    assert set(result.MEANING_FIELDS) == {"formula", "statistic", "population", "window", "unit",
                                          "percentile_method", "unfinished", "denominator"}
    for metric in (result.TTFT_MEAN_MS, result.TPOT_MEAN_MS):
        assert set(result.CLIENT_DEFINITIONS[metric]) == set(result.MEANING_FIELDS)
    for metric in sorted(result.CLIENT_RATE_DEFINITIONS):
        assert set(result.CLIENT_RATE_DEFINITIONS[metric]) == set(result.MEANING_FIELDS)
    assert result.CLIENT_CONTEXT == {"scope": "cluster", "member": "", "aggregate": "", "over": ""}


@pytest.mark.parametrize("metric", ["ttft_mean_ms", "tpot_mean_ms"])
@pytest.mark.parametrize("key,value", [("denominator", "window"), ("denominator", "window_and_gpus"),
                                        ("percentile_method", "numpy_linear")])
def test_an_unexpected_denominator_or_percentile_method_is_refused_though_the_client_states_none(metric, key, value):
    reg = {k: dict(v) for k, v in REGISTRY.items()}
    reg[metric][key] = value
    assert result.check_definitions(reg) == [
        f"the simulator's {metric} has {key} {value!r}; the InferenceX client's has ''"]


@pytest.mark.parametrize("scopes", [["instance"], ["pool", "instance"], [], None])
def test_a_definition_not_defined_at_the_cluster_scope_is_refused(scopes):
    reg = {k: dict(v) for k, v in REGISTRY.items()}
    reg["ttft_mean_ms"]["scopes"] = scopes
    got = result.check_definitions(reg)
    assert len(got) == 1 and got[0].startswith("the simulator's ttft_mean_ms is not defined at the cluster scope")


def test_the_registrys_scopes_and_aggregates_are_in_the_records_the_tests_use():
    # The tests compare records shaped as `blis metrics --json` writes them, scopes and aggregates included.
    assert all(r["scopes"] and r["aggregates"] for r in REGISTRY.values())


def _doc_with(entry):
    return {"metrics": {"ttft_mean_ms": entry}}


def test_a_direct_cluster_figure_is_read_with_or_without_the_version_3_context():
    assert result.figure(_doc_with({"value": 12.5, "samples": 3}), "ttft_mean_ms") == 12.5          # version 2
    assert result.figure(_doc_with({"value": 12.5, "scope": "cluster"}), "ttft_mean_ms") == 12.5    # version 3


@pytest.mark.parametrize("extra,text", [
    ({"scope": "instance", "member": "instance_0"}, "ttft_mean_ms is at the 'instance' scope, not the cluster"),
    ({"scope": "pool", "member": "decode"}, "ttft_mean_ms is at the 'pool' scope, not the cluster"),
    # the largest p99 over the instances: cluster scope, but an aggregate of narrower figures
    ({"scope": "cluster", "aggregate": "max", "over": "instance"}, "ttft_mean_ms states aggregate 'max'"),
    ({"scope": "cluster", "member": "decode"}, "ttft_mean_ms states member 'decode'"),
])
def test_a_figure_that_is_not_the_direct_cluster_figure_is_refused(extra, text):
    with pytest.raises(result.ResultError) as e:
        result.figure(_doc_with({"value": 12.5, **extra}), "ttft_mean_ms")
    assert text in str(e.value) and e.value.slug == "figure_not_cluster_direct"
