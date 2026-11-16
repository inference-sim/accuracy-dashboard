"""Tests of the first-party client adapters (clients_fp.py) and of a run of each scored through corpus.py: the run's
own records give the replay input, the scorer builds the scenario, and grade.grade grades it. Every run here is a
small synthetic one in its client's format; no real record is read."""
import csv
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ingest"))
import clients_fp as cf  # noqa: E402
import corpus as cp  # noqa: E402
import test_corpus as tc  # noqa: E402
import test_score_e2e as e2e  # noqa: E402

NS = 1_000_000_000


def aiperf_record(conv, turn, start_s, end_s, isl, osl, ttft_ms, phase="profiling", itls=(10.0, 12.0)):
    return {"metadata": {"conversation_id": conv, "turn_index": turn, "request_start_ns": int(start_s * NS),
                         "request_end_ns": int(end_s * NS), "benchmark_phase": phase, "was_cancelled": False,
                         "x_request_id": f"{conv}-{turn}"},
            "metrics": {"time_to_first_token": {"value": ttft_ms, "unit": "ms"},
                        "input_sequence_length": {"value": isl, "unit": "tokens"},
                        "output_sequence_length": {"value": osl, "unit": "tokens"},
                        "inter_chunk_latency": {"value": list(itls), "unit": "ms"}}}


AIPERF_EXPORT = {"input_config": {"phases": [{"name": "profiling", "kind": "profiling", "type": "concurrency",
                                              "concurrency": 2}]}}


def aiperf_records():
    return [aiperf_record("a", 0, 0.0, 1.0, 100, 10, 50.0, phase="warmup"), aiperf_record("a", 1, 3.0, 4.0, 220, 10, 60.0),
            aiperf_record("b", 0, 0.5, 1.5, 120, 20, 70.0), aiperf_record("b", 1, 2.0, 2.5, 260, 20, 80.0)]


def test_an_aiperf_export_becomes_a_closed_loop_session_replay(tmp_path):
    rp = cf.aiperf(aiperf_records(), AIPERF_EXPORT, tmp_path)
    rows = list(csv.DictReader(rp.data.open()))
    assert [(r["session_id"], r["round_index"], r["input_tokens"], r["output_tokens"]) for r in rows] == [
        ("a", "0", "100", "10"), ("a", "1", "220", "10"), ("b", "0", "120", "20"), ("b", "1", "260", "20")]
    # the think time is the gap the client left between a round's end and the next round's start
    assert [r["think_time_us"] for r in rows] == ["", "2000000", "", "500000"]
    assert rp.flags == ["--session-mode", "closed-loop", "--concurrent-sessions", "2", "--total-sessions", "2"]
    # the warm-up round is replayed and not measured
    assert rp.requests == 4 and [m["id"] for m in rp.measured] == ["a:1", "b:0", "b:1"]
    assert rp.measured[0]["ttft_us"] == pytest.approx(60_000) and rp.measured[0]["itl_us"] == [10_000.0, 12_000.0]


def test_an_aiperf_export_without_a_concurrency_or_with_an_incomplete_record_is_refused(tmp_path):
    with pytest.raises(cf.ClientError, match="profiling phase"):
        cf.aiperf(aiperf_records(), {"input_config": {"phases": []}}, tmp_path)
    bad = aiperf_records()
    del bad[1]["metadata"]["request_end_ns"]
    with pytest.raises(cf.ClientError, match="lacks"):
        cf.aiperf(bad, AIPERF_EXPORT, tmp_path)


FAKE_CONVERT = """#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
if a[:2] == ["convert", "otel"]:
    def arg(k): return a[a.index(k) + 1]
    assert arg("--context-growth") == "accumulate", a
    d, prefix = arg("--input"), arg("--trace-output")
    rows = []
    for f in sorted(os.listdir(d)):
        spans = json.load(open(os.path.join(d, f)))["spans"]
        for k, s in enumerate(spans):
            rows.append([len(rows), "", "", "", s["trace_id"], k, "", 0, "true", s["attributes"]["gen_ai.usage.input_tokens"],
                         s["attributes"]["gen_ai.usage.output_tokens"], 0, 0, 0, 0, 0, "", 0, 0, 0, 0, 0, 0, 0, "ok", "", "", ""])
    open(prefix + ".yaml", "w").write("trace_version: 3\\ntime_unit: microseconds\\nmode: generated\\nsession_context_growth: accumulate\\n")
    cols = "request_id,client_id,tenant_id,slo_class,session_id,round_index,prefix_group,prefix_length,streaming,input_tokens,output_tokens,text_tokens,image_tokens,audio_tokens,video_tokens,reason_ratio,model,deadline_us,server_input_tokens,arrival_time_us,send_time_us,first_chunk_time_us,last_chunk_time_us,num_chunks,status,error_message,finish_reason,input_tokens_reset"
    open(prefix + ".csv", "w").write(cols + "\\n" + "".join(",".join(map(str, r)) + "\\n" for r in rows))
    sys.exit(0)
sys.exit(2)
"""


def inference_perf_run(root: Path):
    (root / "otel").mkdir(parents=True)
    for sid, spans in (("s1", [(1000, 100), (1300, 120)]), ("s2", [(900, 80)])):
        (root / "otel" / f"{sid}.json").write_text(json.dumps({"spans": [
            {"trace_id": sid, "attributes": {"gen_ai.usage.input_tokens": i, "gen_ai.usage.output_tokens": o}} for i, o in spans]}))
    per = [{"start_time": 10.0, "end_time": 11.0, "error": None,
            "info": {"request_metrics": {"text": {"input_tokens": 1000}},
                     "response_metrics": {"output_tokens": 3, "output_token_times": [10.2, 10.6, 11.0]}}},
           {"start_time": 10.5, "end_time": 11.3, "error": None,
            "info": {"request_metrics": {"text": {"input_tokens": 900}},
                     "response_metrics": {"output_tokens": 2, "output_token_times": [10.6, 11.3]}}}]
    (root / "per_request_lifecycle_metrics.json").write_text(json.dumps(per))
    (root / "inference-perf.yaml").write_text("load:\n  type: trace_session_replay\n  stages:\n  - concurrent_sessions: 2\n    num_sessions: 2\n")
    return per


def test_inference_perf_traces_are_converted_by_blis_and_replayed_as_a_pooled_loop(tmp_path):
    per = inference_perf_run(tmp_path / "run")
    blis = e2e._exe(tmp_path / "blis", FAKE_CONVERT)
    import yaml
    rp = cf.inference_perf(tmp_path / "run" / "otel", per, yaml.safe_load((tmp_path / "run" / "inference-perf.yaml").read_text()),
                           tmp_path / "out", blis)
    assert rp.requests == 3 and rp.flags == ["--concurrent-sessions", "2", "--total-sessions", "2"]
    assert "session_context_growth: accumulate" in rp.header.read_text()
    m = rp.measured[0]
    assert m["ttft_us"] == pytest.approx(200_000) and m["itl_us"] == pytest.approx([400_000, 400_000])
    assert m["tpot_us"] == pytest.approx(400_000)
    assert any("inference-sim#2130" in d["detail"] for d in rp.differences)


def test_an_inference_perf_configuration_without_a_concurrency_is_refused(tmp_path):
    per = inference_perf_run(tmp_path / "run")
    with pytest.raises(cf.ClientError, match="concurrent_sessions"):
        cf.inference_perf(tmp_path / "run" / "otel", per, {"load": {"stages": []}}, tmp_path / "out", "/bin/false")


# ------------------------------------------------------------------- through the corpus scorer

def fake_replay_blis(tmp: Path) -> str:
    """A blis that validates any Result and replays a TraceV2 by completing every row: TTFT 180 ms, TPOT 9 ms."""
    body = '''#!/usr/bin/env python3
import csv, json, sys
a = sys.argv[1:]
if a[:3] == ["schema", "validate", "result"]:
    sys.exit(0)
if a[0] == "catalog":
    print(json.dumps({"query": a[5], "identity": "m" if a[4] == "--model" else a[5], "reason": "fake",
                      **({"packaging": {"gpus_per_node": None, "gpus_per_rack": None}} if a[4] == "--chip" else {})}))
    sys.exit(0)
assert a[0] == "replay", a
rows = list(csv.DictReader(open(a[a.index("--trace-data") + 1])))
out = [{"id": "r%d" % i, "fate": "completed", "arrival_us": i * 1000000, "ttft_us": 180000, "tpot_us": 9000.0,
        "e2e_us": 180000 + 9000 * (int(r["output_tokens"]) - 1), "prompt_tokens": int(r["input_tokens"]),
        "output_tokens": int(r["output_tokens"])} for i, r in enumerate(rows)]
print(json.dumps({"kind": "Result", "schema_version": 3, "request_rows": out,
                  "requests": {"generated": len(rows), "completed": len(rows), "length_capped": 0},
                  "selected_entries": {"coefficients": [{"set": "s", "name": "n", "method": "measured"}]}}))
'''
    (tmp / "sim").mkdir(exist_ok=True)
    return e2e._exe(tmp / "sim" / "blis", body)


def adapted_corpus(root: Path, client: str, log=e2e.LOG):
    root.mkdir(parents=True)
    (root / "r0").mkdir()
    (root / "r0" / "vllm.log").write_text(log)
    files = {"server_log": "r0/vllm.log"}
    if client == "aiperf":
        (root / "r0" / "profile_export.jsonl").write_text("".join(json.dumps(r) + "\n" for r in aiperf_records()))
        (root / "r0" / "profile_export_aiperf.json").write_text(json.dumps(AIPERF_EXPORT))
        files |= {"client_records": "r0/profile_export.jsonl", "client_config": "r0/profile_export_aiperf.json"}
    else:
        inference_perf_run(root / "r0")
        files |= {"client_records": "r0/per_request_lifecycle_metrics.json", "client_config": "r0/inference-perf.yaml",
                  "otel_traces": "r0/otel"}
    doc = {"format": cp.FORMAT, "visibility": "private", "runs": [{"id": "r0", "workload": "w",
           "row": tc.row(benchmark_type="agentic_traces"), "client": {"name": client}, "files": files}]}
    (root / "corpus.json").write_text(json.dumps(doc))
    return root


def adapted_env(tmp: Path, convert=False):
    env = tc._env(tmp)
    blis = fake_replay_blis(tmp)
    if convert:      # the same binary converts and replays
        body = Path(blis).read_text().replace('assert a[0] == "replay", a', FAKE_CONVERT.split('sys.exit(2)')[0]
                                               .replace("#!/usr/bin/env python3\nimport json, os, sys\na = sys.argv[1:]\n", "import os\n")
                                               + 'assert a[0] == "replay", a')
        Path(blis).write_text(body)
    env.blis = blis
    return env


@pytest.mark.parametrize("client", ["aiperf", "inference-perf"])
def test_a_run_of_each_adapted_client_is_scored_on_the_scorers_scenario(tmp_path, client):
    c = adapted_corpus(tmp_path / "c", client)
    rep, _ = cp.score(corpus=c, work=tmp_path / "w", env=adapted_env(tmp_path, convert=client == "inference-perf"),
                      resolve_build=tc.build)
    r = rep["runs"][0]
    assert (r["status"], r["grade"]) == ("scored", "G2"), r
    kinds = {(s["kind"], s["subject"]) for s in r["substitutions"]}
    assert ("client_difference", "session_inputs" if client == "aiperf" else "pooled_session_replay") in kinds
    assert ("unevaluated", "kernel_hash") in kinds
    assert r["simulated"]["ttft_p99_ms"] == pytest.approx(180)
    assert r["measured"]["ttft_p99_ms"] is not None and r["measured"]["itl_p50_ms"] is not None


def test_an_adapted_run_whose_server_log_sets_an_unknown_field_is_g5_by_the_scorer(tmp_path):
    c = adapted_corpus(tmp_path / "c", "aiperf", log=e2e.LOG.replace("'block_size': 16", "'block_size': 16, 'not_a_known_field': 1"))
    rep, _ = cp.score(corpus=c, work=tmp_path / "w", env=adapted_env(tmp_path), resolve_build=tc.build)
    r = rep["runs"][0]
    assert (r["status"], r["grade"]) == ("not_scored", "G5")
    assert any(g["code"] == "field_not_in_release" for g in r["reasons"])


def test_an_adapted_run_with_no_server_log_is_g5_value_not_recorded(tmp_path):
    c = adapted_corpus(tmp_path / "c", "aiperf")
    doc = json.loads((c / "corpus.json").read_text())
    del doc["runs"][0]["files"]["server_log"]
    (c / "corpus.json").write_text(json.dumps(doc))
    rep, _ = cp.score(corpus=c, work=tmp_path / "w", env=adapted_env(tmp_path), resolve_build=tc.build)
    r = rep["runs"][0]
    assert (r["status"], r["grade"]) == ("not_scored", "G5") and {"code": "value_not_recorded"} in r["reasons"]


def test_an_adapted_run_missing_its_client_records_is_g5_by_name(tmp_path):
    c = adapted_corpus(tmp_path / "c", "inference-perf")
    doc = json.loads((c / "corpus.json").read_text())
    del doc["runs"][0]["files"]["otel_traces"]
    (c / "corpus.json").write_text(json.dumps(doc))
    rep, _ = cp.score(corpus=c, work=tmp_path / "w", env=adapted_env(tmp_path), resolve_build=tc.build)
    r = rep["runs"][0]
    assert r["grade"] == "G5" and r["reasons"] == [{"code": "value_not_recorded",
                                                    "subject": "inference-perf_records_missing_otel_traces"}]
