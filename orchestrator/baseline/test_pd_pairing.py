"""Tests of the P/D pairing (pd_pairing.py), on synthetic topologies and dump rows written here."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pd_pairing as pp  # noqa: E402


def topo(tid="t1", concs=(1, 4), gpus=6, checkpoint="MiniMaxAI/MiniMax-M2.5"):
    return {"topology_id": tid, "checkpoint": checkpoint, "model": "minimax-m2.5", "gpu": "b200", "workload": "1024:1024",
            "label": "1k1k", "framework": "dynamo-vllm", "precision": "fp8", "total_gpus": gpus,
            "points": [{"concurrency": c, "status": "success", "measured_tpot_ms": 10.0 * c, "measured_ttft_ms": 100.0 * c}
                       for c in concs]}


def row(i, run, conc, tpot_ms, ttft_ms, pw=1, dw=1, date="2026-06-01"):
    return {"id": i, "github_run_id": run, "model": "minimaxm2.5", "hardware": "b200", "framework": "dynamo-vllm",
            "precision": "fp8", "isl": 1024, "osl": 1024, "conc": conc, "disagg": True, "date": date,
            "prefill_num_workers": pw, "decode_num_workers": dw, "prefill_tp": 2, "decode_tp": 4, "prefill_ep": 1,
            "decode_ep": 4, "prefill_dp_attention": False, "decode_dp_attention": True,
            "num_prefill_gpu": 2, "num_decode_gpu": 4,
            "metrics": {"mean_tpot": tpot_ms / 1000, "median_tpot": 0.0001, "mean_ttft": ttft_ms / 1000, "median_ttft": 0.0001}}


def run_rows(run, base=1):
    return [row(base, run, 1, 10.0, 100.0), row(base + 1, run, 4, 40.0, 400.0)]


def test_a_topology_pairs_with_the_run_that_reproduces_its_measured_curve():
    rows = run_rows("r1") + [row(10, "r2", 1, 99.0, 100.0), row(11, "r2", 4, 40.0, 400.0)]
    got = pp.pair([topo()], rows)
    assert [p["records"] for p in got] == [["1"], ["2"]]
    assert got[0]["pools"]["decode"] == {"workers": 1, "tp": 4, "ep": 4, "dp_attention": True, "gpus": 4}
    assert got[0]["cell"] == "dynamo-vllm|b200|minimax-m2.5|disaggregated"
    assert got[0]["split"] in ("train", "validation", "test")


def test_two_runs_that_both_reproduce_the_curve_are_not_paired_by_a_guess():
    got = pp.pair([topo()], run_rows("r1") + run_rows("r2", base=20))
    assert all(p["records"] == [] and p["why"] == "several_runs" for p in got)


def test_no_run_with_the_topologys_gpu_total_is_no_record():
    got = pp.pair([topo(gpus=8)], run_rows("r1"))
    assert all(p["records"] == [] and p["why"] == "no_record" for p in got)


def test_a_checkpoint_with_no_slug_is_named_and_a_failed_point_stays_in_the_cell():
    t = topo(checkpoint="acme/Unknown-9")
    t["points"][1]["status"] = "failed"
    got = pp.pair([t], run_rows("r1"))
    assert [p["why"] for p in got] == ["no_slug", "no_slug"]
    assert [p["estimator_status"] for p in got] == ["success", "failed"]


def test_a_failed_estimator_point_is_paired_to_its_record_so_coverage_counts_it():
    t = topo()
    t["points"][1] = {"concurrency": 4, "status": "failed"}
    rows = run_rows("r1")
    got = pp.pair([t], rows)
    assert got[1]["records"] == ["2"] and got[1]["estimator_status"] == "failed"


def test_the_run_is_read_from_the_record_url_when_the_export_has_no_run_id():
    rows = run_rows("r1")
    for r in rows:
        r.pop("github_run_id")
        r["run_url"] = "https://github.com/x/y/actions/runs/777/attempts/2"
    got = pp.pair([topo()], rows)
    assert [p["records"] for p in got] == [["1"], ["2"]]
