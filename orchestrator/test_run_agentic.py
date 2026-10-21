#!/usr/bin/env python3
"""Behavioural tests for the agentic scoring driver.

No network and no real blis build: these feed a fixed agentic row and a fixed blis metrics
JSON and check that the driver (1) maps the row to a scoreable deployment, (2) places
measured and predicted mean TTFT/TPOT in the right CSV columns and units, (3) refuses an
unsupported model/hardware or an unreplayable row rather than scoring it with a guess.

Run: python3 orchestrator/test_run_agentic.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_agentic as ra  # noqa: E402

HERE = Path(__file__).resolve().parent
FAILURES = []

# A fixed agentic row (the shape fetch_agentic_rows.py writes), trimmed to what the driver
# reads. mean_ttft / mean_tpot are in SECONDS, as the API reports them.
ROW = {
    "id": "439932", "model": "kimik3", "hardware": "b300", "precision": "fp4",
    "spec_method": "mtp", "decode_tp": 8, "decode_ep": 1, "decode_dp_attention": False,
    "conc": 2, "image": "vllm/vllm-openai:nightly-dev-x86_64-cu13.0.1-5894fdf",
    "run_url": "https://github.com/SemiAnalysisAI/InferenceX/actions/runs/31893747354",
    "benchmark_type": "agentic_traces",
    "metrics": {"mean_ttft": 1.69433, "mean_tpot": 0.00454},
}

# A Kimi-K3 server + job log pair that replay_args resolves with zero refusals.
SERVER_LOG = (
    "(APIServer pid=1) INFO  version 0.17.2rc1.dev4996+g5894fdf98\n"
    "non-default args: {'model': '/scratch/models/Kimi-K3', 'tensor_parallel_size': 8, "
    "'speculative_config': {'method': 'dspark', 'num_speculative_tokens': 7, "
    "'rejection_sample_method': 'synthetic', 'synthetic_acceptance_length': 3.84}}\n"
)
JOB_LOG = (
    "+ aiperf profile --scenario inferencex-agentx-mvp --model moonshotai/Kimi-K3 "
    "--concurrency 2 --benchmark-duration 3600 --random-seed 42 --num-dataset-entries 393 "
    "--public-dataset semianalysis_cc_traces_weka_062126\n"
)


def ck(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'} {label}{(': ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


def test_pure_functions():
    ck("a supported row has no support refusals", ra.support_refusals(ROW) == [])
    ck("an unsupported model is refused",
       any("not in the pinned catalog" in r
           for r in ra.support_refusals(dict(ROW, model="brand-new-model"))))
    ck("an unsupported chip is refused",
       any("no registry coefficients" in r
           for r in ra.support_refusals(dict(ROW, hardware="mi355x"))))

    sweep = ra.sweep_from_row(ROW)
    ck("the row maps to the catalog model/chip",
       sweep["model"] == "kimi-k3" and sweep["gpu"] == "b300", str(sweep["scenario"]))
    ck("the scenario name marks it agentic",
       sweep["scenario"].endswith("-agentx.yaml"), sweep["scenario"])

    mt, mp = ra.measured_us(ROW)  # seconds -> microseconds
    ck("measured TTFT is seconds scaled to microseconds",
       abs(mt - 1.69433e6) < 1, f"{mt}")
    ck("measured TPOT is seconds scaled to microseconds",
       abs(mp - 4540.0) < 1, f"{mp}")

    pt, pp = ra.predicted_us({"ttft_mean_ms": 1500.0, "itl_mean_ms": 4.5})  # ms -> us
    ck("predicted TTFT is ms scaled to microseconds", abs(pt - 1.5e6) < 1, f"{pt}")
    ck("predicted TPOT comes from itl_mean_ms", abs(pp - 4500.0) < 1, f"{pp}")

    r = ra.csv_row(ROW, sweep, pt, pp)
    ck("the CSV row has exactly build_summary's columns",
       list(r.keys()) == ra.CSV_HEADER, str(list(r.keys())))
    ck("measured and predicted land in the right columns",
       r["meas_ttft_us"] == round(mt, 3) and r["pred_ttft_us"] == round(pt, 3)
       and r["meas_tpot_us"] == round(mp, 3) and r["pred_tpot_us"] == round(pp, 3))
    ck("the point is tagged the apples-to-apples tier",
       r["tier_unbracketed"] == "MEASURED-OR-RESOLVED", r["tier_unbracketed"])


def run_driver(td: Path, row: dict, blis_stub: str) -> subprocess.CompletedProcess:
    """Drive run_agentic.main() with a fake blis that writes a fixed metrics file."""
    (td / "row.json").write_text(json.dumps(row))
    (td / "server.log").write_text(SERVER_LOG)
    (td / "job.log").write_text(JOB_LOG)
    blis = td / "blis_stub.sh"
    blis.write_text(blis_stub)
    blis.chmod(0o755)
    return subprocess.run(
        [sys.executable, str(HERE / "run_agentic.py"),
         "--row", str(td / "row.json"), "--server-log", str(td / "server.log"),
         "--job-log", str(td / "job.log"), "--corpus", str(td / "traces.jsonl"),
         "--corpus-sha256", "deadbeef", "--blis", str(blis),
         "--catalog", str(td), "--registry", str(td), "--out-dir", str(td / "out")],
        capture_output=True, text=True)


def test_driver_scores_a_supported_row():
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        (td / "traces.jsonl").write_text("{}\n")
        # A fake blis: ignore args, find --metrics-path and write a fixed MetricsOutput.
        stub = (
            "#!/usr/bin/env bash\n"
            "while [ $# -gt 0 ]; do [ \"$1\" = --metrics-path ] && echo "
            "'{\"ttft_mean_ms\": 1500.0, \"itl_mean_ms\": 4.5}' > \"$2\"; shift; done\n"
        )
        r = run_driver(td, ROW, stub)
        ck("driver exits 0 on a supported, replayable row", r.returncode == 0,
           r.stderr[-300:])
        csv = td / "out" / "signedprobe.csv"
        ck("a signedprobe.csv is written", csv.exists())
        if csv.exists():
            lines = csv.read_text().strip().splitlines()
            ck("the CSV has a header + one data row", len(lines) == 2, str(lines))
            ck("the header is build_summary's EXPECTED_HEADER",
               lines[0] == ",".join(ra.CSV_HEADER))
        ck("a facets corpus is written",
           (td / "out" / "agentic_corpus.json").exists())


def test_driver_refuses_unsupported():
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        (td / "traces.jsonl").write_text("{}\n")
        stub = "#!/usr/bin/env bash\necho 'blis should not run' >&2\nexit 7\n"
        r = run_driver(td, dict(ROW, model="brand-new-model"), stub)
        ck("driver exits 0 (not scored, not an error) on an unsupported model",
           r.returncode == 0, r.stderr[-200:])
        ck("no CSV is written for an unsupported row",
           not (td / "out" / "signedprobe.csv").exists())
        refusals = td / "out" / "refusals.json"
        ck("a refusals.json records why", refusals.exists())
        if refusals.exists():
            doc = json.loads(refusals.read_text())
            ck("the refusal names the unsupported model",
               any("brand-new-model" in x for x in doc["refusals"]), str(doc["refusals"]))


def main() -> int:
    test_pure_functions()
    test_driver_scores_a_supported_row()
    test_driver_refuses_unsupported()
    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} failure(s): {FAILURES}")
        return 1
    print("PASS: 0 failure(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
