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


TARGETS = {"vllm": "0.32.0", "sglang": "0.5.23"}
ROUTERS = [{"router": "dynamo", "mode": "kv", "policy": "none"}, {"router": "dynamo", "mode": "random", "policy": "random-picker"}]


def test_target_and_near_releases():
    got = {(e, v): rr.nearness(e, v, TARGETS) for e, v in [
        ("vllm", "0.32.0"), ("vllm", "0.32.1"), ("vllm", "0.31.2"), ("vllm", "0.33.0"), ("vllm", "0.30.0"),
        ("vllm", None), ("sglang", "0.5.23"), ("sglang", "0.5.22"), ("sglang", "0.5.24.post1"), ("sglang", "0.5.21"),
        (None, "0.32.0")]}
    assert got == {("vllm", "0.32.0"): "target", ("vllm", "0.32.1"): "near", ("vllm", "0.31.2"): "near",
                   ("vllm", "0.33.0"): "near", ("vllm", "0.30.0"): None, ("vllm", None): None,
                   ("sglang", "0.5.23"): "target", ("sglang", "0.5.22"): "near", ("sglang", "0.5.24.post1"): "near",
                   ("sglang", "0.5.21"): None, (None, "0.32.0"): None}


def row(i, framework, image, date="2026-11-01", hardware="b200", disagg=False):
    return {"id": i, "framework": framework, "image": image, "model": "m", "hardware": hardware,
            "benchmark_type": "single_turn", "date": date, "disagg": disagg}


def test_an_inferencex_record_names_its_release_only_for_an_official_image():
    recs = rr.inferencex_records([
        row(1, "vllm", "vllm/vllm-openai:v0.32.0@sha256:" + "a" * 64), row(2, "vllm", "vllm/vllm-openai:nightly-abc"),
        row(3, "sglang", "lmsysorg/sglang:v0.5.23-cu130"), row(4, "trt", "nvcr.io/trt:1.3.0"),
        row(5, "dynamo-vllm", "vllm/vllm-openai:v0.32.0"), row(6, "vllm", "vllm/vllm-openai:0.32.0")])
    assert [(r["record"], r["engine"], r["release"], r["router"]) for r in recs] == [
        ("1", "vllm", "0.32.0", None), ("2", "vllm", None, None), ("3", "sglang", "0.5.23", None), ("4", None, None, None),
        ("5", "vllm", "0.32.0", "dynamo-router"), ("6", "vllm", "0.32.0", None)]   # the grader's own release rule


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
    assert rr.ledger_status(recs, {"1"}, "2026-09-27", {"3": "agentic_no_session"}) == {
        "1": "unit", "2": "newer_than_source_revision", "3": "left_out:agentic_no_session", "p:0": "source_not_in_ledger"}
    assert rr.source_revision_end("db-dump/2026-09-28") == "2026-09-27"


def test_a_dataset_file_whose_checksum_differs_from_the_manifest_is_refused(tmp_path):
    (tmp_path / "pairs").mkdir()
    (tmp_path / "pairs" / "p.parquet").write_bytes(b"not the file")
    (tmp_path / "manifest.json").write_text(json.dumps({"pairs": [{"id": "p", "file_sha256": "0" * 64, "records": 1}]}))
    with pytest.raises(rr.ReleaseError, match="the manifest says"):
        rr.read_configiq(tmp_path)


def test_the_report_counts_runs_on_target_and_near_releases_only():
    recs = rr.inferencex_records([row(1, "vllm", "vllm/vllm-openai:v0.32.0"), row(2, "vllm", "vllm/vllm-openai:v0.25.0"),
                                  row(3, "vllm", "vllm/vllm-openai:v0.33.0")])
    doc = rr.report(recs, {"1": "newer_than_source_revision", "2": "unit", "3": "unit"}, {}, TARGETS, ROUTERS)
    assert [(r["release"], r["nearness"], r["records"], r["record_ids"], r["conditions"]["engine_release"])
            for r in doc["runs"]] == [("0.32.0", "target", 1, ["1"], "true"), ("0.33.0", "near", 1, ["3"], "false: 0.33.0")]


def test_a_run_behind_a_router_blis_does_not_host_is_never_counted_as_able_to_reach_g1():
    recs = rr.inferencex_records([row(1, "dynamo-vllm", "vllm/vllm-openai:v0.32.0"), row(2, "vllm", "vllm/vllm-openai:v0.32.0"),
                                  row(3, "vllm-disagg", "vllm/vllm-openai:v0.32.0", disagg=True)])
    doc = rr.report(recs, {r["record"]: "unit" for r in recs}, {}, TARGETS, ROUTERS)
    by = {r["framework"]: r["conditions"] for r in doc["runs"]}
    assert (by["dynamo-vllm"]["can_reach_g1"], by["dynamo-vllm"]["best_grade"]) == (False, "G2?")
    assert by["dynamo-vllm"]["router"].startswith("false: behind dynamo-router")
    assert (by["vllm"]["can_reach_g1"], by["vllm"]["best_grade"]) == (True, "G1")
    assert by["vllm-disagg"]["can_reach_g1"] is False
    assert doc["records"]["on_target_in_scope"] == 3 and doc["records"]["on_target_in_scope_that_can_reach_g1"] == 1
    only_kv = [{"router": "dynamo", "mode": "kv", "policy": "none"}]
    doc = rr.report(recs[:1], {"1": "unit"}, {}, TARGETS, only_kv)
    assert doc["runs"][0]["conditions"]["best_grade"] == "G5"


def test_rows_of_one_group_are_split_by_ledger_status():
    recs = rr.inferencex_records([row(1, "vllm", "vllm/vllm-openai:v0.32.0"), row(2, "vllm", "vllm/vllm-openai:v0.32.0")])
    doc = rr.report(recs, {"1": "unit", "2": "newer_than_source_revision"}, {}, TARGETS, ROUTERS)
    assert sorted((r["ledger"], r["record_ids"], r["conditions"]["fields_modelled"]) for r in doc["runs"]) == [
        ("newer_than_source_revision", ["2"], "not scored: newer than source revision"),
        ("unit", ["1"], "decided when the point is scored")]


def test_a_tpu_row_is_out_of_scope_by_the_baselines_own_rule():
    doc = rr.report(rr.inferencex_records([row(1, "vllm", "vllm/vllm-openai:v0.32.0", hardware="tpuv7")]),
                    {"1": "unit"}, {}, TARGETS, ROUTERS)
    assert doc["runs"][0]["scope"] == "out_of_scope"


def test_the_targets_are_read_from_the_stack_and_blis_sglangs_provenance():
    assert rr.targets_of({"engines": [{"kind": "vllm", "version": "0.32.0"}]}, {"sglang": {"version": "0.5.23"}}) == TARGETS
    with pytest.raises(rr.ReleaseError, match="no vLLM engine"):
        rr.targets_of({"engines": []}, {"sglang": {"version": "0.5.23"}})


def test_a_configiq_commit_that_does_not_hold_the_manifest_read_is_refused():
    rr.check_configiq_commit("a" * 40, __import__("hashlib").sha256(b"m").hexdigest(), fetch=lambda url: b"m")
    with pytest.raises(rr.ReleaseError, match="has sha256"):
        rr.check_configiq_commit("a" * 40, "0" * 64, fetch=lambda url: b"m")
    with pytest.raises(rr.ReleaseError, match="40-hex"):
        rr.check_configiq_commit("main", "0" * 64, fetch=lambda url: b"m")


def test_an_empty_source_is_an_error_not_a_crash(tmp_path):
    (tmp_path / "rows.json").write_text("[]")
    (tmp_path / "a.json").write_text("{}")
    assert rr.main(["report", "--inferencex-rows", str(tmp_path / "rows.json"), "--inferencex-availability", str(tmp_path / "a.json"),
                    "--inferencex-read-at", "t", "--dump-tags", str(tmp_path / "a.json"), "--ledger", str(tmp_path),
                    "--stack", str(tmp_path / "a.json"), "--engines", str(tmp_path / "a.json"), "--out", str(tmp_path / "o")]) == 2
