"""Tests of the release finder (release_runs.py): which releases are targets or near, how each source's records read
their release, what the ledger holds, and the dataset's checksum guard."""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ingest"))
import release_runs as rr  # noqa: E402


def test_target_and_near_releases():
    got = {(e, v): rr.nearness(e, v) for e, v in [
        ("vllm", "0.32.0"), ("vllm", "0.32.1"), ("vllm", "0.31.2"), ("vllm", "0.33.0"), ("vllm", "0.30.0"),
        ("vllm", None), ("sglang", "0.5.23"), ("sglang", "0.5.22"), ("sglang", "0.5.24.post1"), ("sglang", "0.5.21"),
        (None, "0.32.0")]}
    assert got == {("vllm", "0.32.0"): "target", ("vllm", "0.32.1"): None, ("vllm", "0.31.2"): "near",
                   ("vllm", "0.33.0"): "near", ("vllm", "0.30.0"): None, ("vllm", None): None,
                   ("sglang", "0.5.23"): "target", ("sglang", "0.5.22"): "near", ("sglang", "0.5.24.post1"): "near",
                   ("sglang", "0.5.21"): None, (None, "0.32.0"): None}


def row(i, framework, image, date="2026-11-01"):
    return {"id": i, "framework": framework, "image": image, "model": "m", "hardware": "b200",
            "benchmark_type": "single_turn", "date": date}


def test_an_inferencex_record_names_its_release_only_for_an_official_image():
    recs = rr.inferencex_records([
        row(1, "vllm", "vllm/vllm-openai:v0.32.0@sha256:" + "a" * 64), row(2, "vllm", "vllm/vllm-openai:nightly-abc"),
        row(3, "sglang", "lmsysorg/sglang:v0.5.23-cu130"), row(4, "trt", "nvcr.io/trt:1.3.0"),
        row(5, "dynamo-vllm", "vllm/vllm-openai:v0.32.0")])
    assert [(r["record"], r["engine"], r["release"]) for r in recs] == [
        ("1", "vllm", "0.32.0"), ("2", "vllm", None), ("3", "sglang", "0.5.23"), ("4", None, None), ("5", "vllm", "0.32.0")]


def test_a_configiq_record_reads_its_upstream_version_and_refuses_another_backend():
    recs = rr.configiq_records({"p__b200": [{"backend": "vllm", "backend_version": "vLLM-0.32.0", "model_id": "o/m",
                                             "accelerator": "B200", "turns": 1.0},
                                            {"backend": "vllm", "backend_version": "vLLM-main", "model_id": "o/m",
                                             "accelerator": "B200", "turns": None}]})
    assert [(r["record"], r["release"], r["hardware"]) for r in recs] == [("p__b200:0", "0.32.0", "b200"),
                                                                         ("p__b200:1", None, "b200")]
    with pytest.raises(rr.ReleaseError, match="vLLM rows only"):
        rr.configiq_records({"p": [{"backend": "sglang", "backend_version": "x", "model_id": "o/m", "accelerator": "H200"}]})


def test_the_ledger_status_of_each_record():
    recs = rr.inferencex_records([row(1, "vllm", "x"), row(2, "vllm", "x", "2026-10-02"), row(3, "vllm", "x", "2026-09-01")])
    recs.append({"source": "configiq", "record": "p:0", "date": None})
    assert rr.ledger_status(recs, {"1"}, "2026-09-27") == {"1": "unit", "2": "newer_than_source_revision",
                                                           "3": "not_in_ledger", "p:0": "source_not_in_ledger"}


def test_a_dataset_file_whose_checksum_differs_from_the_manifest_is_refused(tmp_path):
    (tmp_path / "pairs").mkdir()
    (tmp_path / "pairs" / "p.parquet").write_bytes(b"not the file")
    (tmp_path / "manifest.json").write_text(json.dumps({"pairs": [{"id": "p", "file_sha256": "0" * 64, "records": 1}]}))
    with pytest.raises(rr.ReleaseError, match="the manifest says"):
        rr.read_configiq(tmp_path)


def test_the_report_counts_runs_on_target_and_near_releases_only():
    recs = rr.inferencex_records([row(1, "vllm", "vllm/vllm-openai:v0.32.0"), row(2, "vllm", "vllm/vllm-openai:v0.25.0"),
                                  row(3, "vllm", "vllm/vllm-openai:v0.33.0")])
    doc = rr.report(recs, {"1": "newer_than_source_revision", "2": "unit", "3": "unit"}, {})
    assert [(r["release"], r["nearness"], r["records"], r["conditions"]["engine_release"]) for r in doc["runs"]] == [
        ("0.32.0", "target", 1, "true"), ("0.33.0", "near", 1, "false: 0.33.0")]
