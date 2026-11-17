"""configiq points: read from the ledger's unit list, checked row by row, and graded by design §11.3-11.4 and COV-7/
COV-10 (blis-design#14). Every row here is synthetic; no dataset value is in the repository (X12).

Run: python3 -m pytest orchestrator/ingest/test_configiq.py
"""
import gzip
import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import configiq as cq  # noqa: E402

F = "pairs/openai_gpt_oss_120b__b200/ground_truth.parquet"
CATALOG = {"models": {"openai/gpt-oss-120b": {"moe": True}, "deepseek-ai/DeepSeek-V4-Pro": {"moe": True},
                      "dense/model": {"moe": False}},
           "chips": {"B200", "H200"}}


def row(**set_):
    cols = {"pair_id": "openai_gpt_oss_120b__b200", "model": "openai/gpt-oss-120b", "model_id": "openai/gpt-oss-120b",
            "accelerator": "B200", "backend": "vllm", "version": "vLLM-0.32.0", "backend_version": "vLLM-0.32.0",
            "tp": 1.0, "isl": 1000.0, "osl": 1000.0, "concurrency": 50.0, "turns": 1.0, "prefix_tokens": None,
            "prefix_count": None, "prefix_caching": "no", "request_type": "/v1/completions", "spec_decoding": "",
            "gpu_memory_utilization": "0.92", "max_num_seqs": None, "max_seq_len": None,
            "chunked_prefill_enabled": None, "precision": None, "weight_quantization": "unknown",
            "kv_quantization": "unknown"}
    for c in cq.MEASURED_COLUMNS:
        cols[c] = 10.0
    cols.update({"measured concurrency": 49.0, "successful_requests": 1000.0, "errored_requests": 0.0,
                 "request_latency_median": 2.0, "itl_p99": "11.5"})
    cols.update(set_)
    return cols


def ledger_files(tmp_path, rows: dict) -> tuple:
    """A ledger directory holding one unit per identity among rows ("path:row" -> columns), each measurement kept
    under its first row, as blis-substrate's ingest writes it."""
    units = {}
    for rid in sorted(rows):
        ident = cq.identity(rows[rid])
        uid = cq.unit_id(ident)
        u = units.setdefault(uid, {"unit_id": uid, "role_key": "0" * 64, "identity": ident, "measurements": []})
        u["measurements"].append({"record": rid, "measured": hashlib.sha256(rid.encode()).hexdigest(),
                                  "duplicates": [], "merged": [], "recorded": {}})
    d = tmp_path / "ledger"
    (d / "units").mkdir(parents=True)
    (d / "reports").mkdir()
    lines = "".join(json.dumps(u, sort_keys=True, separators=(",", ":")) + "\n" for _, u in sorted(units.items()))
    (d / "units" / "configiq.jsonl.gz").write_bytes(gzip.compress(lines.encode()))
    rev = "a" * 40
    (d / "reports" / "configiq.yaml").write_text(yaml.safe_dump({
        "kind": "IngestReport", "source": "configiq", "revision": rev, "input": "b" * 64, "records": len(rows),
        "units": len(units), "role_keys": 1, "duplicates": 0, "merged": 0, "joined_units": 0, "joined_records": 0,
        "left_out": {}, "units_by_framework": {"vllm": len(units)}}))
    (d / "sources.yaml").write_text(yaml.safe_dump({"kind": "LedgerSources", "sources": [
        {"id": "configiq", "revision": {"kind": "hf_dataset_revision", "ref": rev, "assets": []}}]}))
    return d / "units" / "configiq.jsonl.gz", d / "reports" / "configiq.yaml", d / "sources.yaml"


def one(tmp_path, rows: dict, catalog=CATALOG):
    lg = cq.load(*ledger_files(tmp_path, rows))
    pts = cq.points(lg, rows, catalog)
    return pts, [cq.record(p) for p in pts]


def test_identity_is_canonical_whatever_the_column_type():
    assert cq.unit_id(cq.identity(row(tp=1.0, isl=1000.0))) == cq.unit_id(cq.identity(row(tp=1, isl=1000)))
    assert cq.identity(row(turns=float("nan")))["turns"] is None
    with pytest.raises(cq.ConfigiqError, match="tp"):
        cq.identity(row(tp=1.5))


def test_a_row_that_differs_from_the_pinned_revision_is_refused(tmp_path):
    rows = {f"{F}:0": row()}
    lg = cq.load(*ledger_files(tmp_path, rows))
    with pytest.raises(cq.ConfigiqError, match="differs from the pinned revision"):
        cq.points(lg, {f"{F}:0": row(tp=2.0)}, CATALOG)


def test_agreeing_repeats_are_scored_on_their_mean_and_never_credited_as_noise(tmp_path):
    pts, recs = one(tmp_path, {f"{F}:0": row(ttft_median=100.0), f"{F}:1": row(ttft_median=110.0)})
    assert len(pts) == 1
    assert recs[0]["measured"]["ttft_median"] == pytest.approx(105.0)
    assert recs[0]["repeat_spread"]["ttft_median"] == {"n": 2, "min": 100.0, "max": 110.0}
    assert not any(r["code"] == "value_conflict" for r in recs[0]["g5_reasons"])


@pytest.mark.parametrize("column,values", [("successful_requests", (1000.0, 1600.0)), ("itl_p95", (10.0, 20.0))])
def test_repeats_that_disagree_by_more_than_20_percent_are_a_value_conflict(tmp_path, column, values):
    pts, recs = one(tmp_path, {f"{F}:0": row(**{column: values[0]}), f"{F}:1": row(**{column: values[1]})})
    assert recs[0]["measured"] is None
    assert any(r["code"] == "value_conflict" and column in r["subject"] for r in recs[0]["g5_reasons"])
    assert recs[0]["provisional"] is False


def test_repeats_exactly_20_percent_from_their_mean_agree(tmp_path):
    _, recs = one(tmp_path, {f"{F}:0": row(successful_requests=1000.0), f"{F}:1": row(successful_requests=1500.0)})
    assert recs[0]["measured"]["ttft_median"] == 10.0


def test_turn_slices_are_kept_for_the_event_suite_and_never_graded_or_averaged(tmp_path):
    rows = {f"{F}:0": row(turns=5.0, ttft_median=100.0),
            f"{F}:1": row(turns=5.0, **{"measured concurrency": None, "measured rps": None, "ttft_median": 900.0})}
    pts, recs = one(tmp_path, rows)
    assert recs[0]["measured"]["ttft_median"] == 100.0
    assert [s["record"] for s in recs[0]["turn_slices"]] == [f"{F}:1"]
    assert recs[0]["turn_slices"][0]["ttft"]["median"] == 900.0
    assert recs[0]["whole_runs"] == [f"{F}:0"]


def test_metrics_are_compared_by_definition_in_ms_and_nothing_unrecorded_is_derived(tmp_path):
    pts, recs = one(tmp_path, {f"{F}:0": row(ttft_p999=None, request_latency_median=2.5)})
    m = recs[0]["measured"]
    assert m["request_latency_median"] == 2500.0
    assert "ttft_p999" not in m
    assert "tpot_mean" not in m  # the dataset records no TPOT mean
    assert recs[0]["metrics"]["tpot"]["blis"] == "e2e_per_output_token"
    assert recs[0]["metrics"]["itl"]["blis"] == "itl_per_request"


def test_scope_reasons_come_first(tmp_path):
    amd = {f"{F}:0": row(accelerator="MI355X", tp=4.0)}
    _, recs = one(tmp_path, amd)
    assert recs[0]["g5_reason"]["code"] == "chip_not_modelled"
    assert "blis-substrate#210" in recs[0]["g5_reason"]["subject"]
    _, recs = one(tmp_path / "b", {f"{F}:0": row(model_id="x/not-onboarded", model="x/not-onboarded")})
    assert recs[0]["g5_reason"] == {"code": "not_in_catalog", "subject": "model x/not-onboarded"}
    assert any(r["code"] == "value_not_recorded" for r in recs[0]["g5_reasons"])


def test_a_forge_consistent_row_is_provisional_capped_at_g3_with_three_named_substitutions(tmp_path):
    pts, recs = one(tmp_path, {f"{F}:0": row()})
    r = recs[0]
    assert r["provisional"] is True and r["grade"] is None and r["grade_cap"] == "G3"
    assert [s["kind"] for s in r["substitutions"]] == [
        "provisional_parallelism", "provisional_blank_flags", "provisional_frame"]
    assert r["matched_preset"]["commit"] == "117e2386a31f14c6d00f7fc6da74a2426940216e"
    assert r["backlog"] == []


def test_a_thin_preset_match_names_its_commit_and_period(tmp_path):
    rows = {f"{F}:0": row(model_id="deepseek-ai/DeepSeek-V4-Pro", model="deepseek-ai/DeepSeek-V4-Pro",
                          accelerator="H200", tp=8.0, version="vLLM-0.28.0", backend_version="vLLM-0.28.0",
                          kv_quantization="fp8")}
    _, recs = one(tmp_path, rows)
    assert recs[0]["provisional"] is True
    assert recs[0]["matched_preset"] == {"commit": "8f0ede3f3780699156a10f0f620bf5b0cb467af1",
                                         "from": "2026-09-22", "to": "2026-09-22"}
    assert "one day" in recs[0]["backlog"][0]


@pytest.mark.parametrize("change", [
    {"gpu_memory_utilization": "0.9"},                          # no preset passes 0.9
    {"tp": 4.0},                                                # no preset gives gpt-oss TP4
    {"max_seq_len": "8192"},                                    # no preset sets max-model-len
    {"version": "vLLM-0.20.0", "backend_version": "vLLM-0.20.0"},  # released before forge began
    {"prefix_caching": ""},                                     # a raw column, not a parsed flag
])
def test_a_row_no_preset_explains_stays_g5(tmp_path, change):
    _, recs = one(tmp_path, {f"{F}:0": row(**change)})
    assert recs[0]["provisional"] is False
    assert recs[0]["grade"] == "G5"
    assert recs[0]["g5_reason"]["code"] == "value_not_recorded"


def test_a_downloaded_file_that_differs_from_its_pin_is_refused(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "manifest.json").write_text("{}")
    lg = cq.Ledger(assets={"manifest.json": hashlib.sha256(b"{}").hexdigest()})
    cq.check_files(lg, tmp_path / "d")
    (tmp_path / "d" / "manifest.json").write_text("{ }")
    with pytest.raises(cq.ConfigiqError, match="manifest.json"):
        cq.check_files(lg, tmp_path / "d")


def test_the_export_is_read_against_the_pins(tmp_path):
    d = tmp_path / "d"
    (d / "pairs" / "x").mkdir(parents=True)
    pq = "pairs/x/ground_truth.parquet"
    (d / pq).write_bytes(b"parquet")
    lg = cq.Ledger(assets={pq: hashlib.sha256(b"parquet").hexdigest()})
    exp = tmp_path / "rows.jsonl"
    exp.write_text("".join(json.dumps({"file": pq, "row": i, "columns": row(concurrency=float(i + 1))}) + "\n"
                           for i in range(2)))
    rows = cq.read_export(exp, d, lg)
    assert sorted(rows) == [f"{pq}:0", f"{pq}:1"] and rows[f"{pq}:1"]["concurrency"] == 2.0
    exp.write_text(json.dumps({"file": pq, "row": 1, "columns": row()}) + "\n")
    with pytest.raises(cq.ConfigiqError, match="out of order"):
        cq.read_export(exp, d, lg)
    exp.write_text(json.dumps({"file": "pairs/y/ground_truth.parquet", "row": 0, "columns": row()}) + "\n")
    with pytest.raises(cq.ConfigiqError, match="not a Parquet file the ledger pins"):
        cq.read_export(exp, d, lg)
