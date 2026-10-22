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

    server = ra.parse_server_log(SERVER_LOG)
    sweep = ra.sweep_from_row(ROW, server=server)
    ck("the row maps to the catalog model/chip",
       sweep["model"] == "kimi-k3" and sweep["gpu"] == "b300", str(sweep["scenario"]))
    ck("the scenario name marks it agentic",
       sweep["scenario"].endswith("-agentx.yaml"), sweep["scenario"])
    # Point 6: the scenario MUST draft (method + K) or blis refuses the acceptance flag.
    ck("the speculative method and K are written into the scenario config",
       sweep["stated_config"].get("speculative_method") == "dspark"
       and sweep["stated_config"].get("num_speculative_tokens") == 7,
       str(sweep["stated_config"]))

    mt, mp = ra.measured_us(ROW)  # seconds -> microseconds
    ck("measured TTFT is seconds scaled to microseconds",
       abs(mt - 1.69433e6) < 1, f"{mt}")
    ck("measured TPOT is seconds scaled to microseconds",
       abs(mp - 4540.0) < 1, f"{mp}")

    # Point 1: predicted TPOT is request_itl_mean_ms (per TOKEN), NOT itl_mean_ms (per step).
    # Under DSpark they differ by ~AL, so reading the wrong one inflates TPOT ~AL x.
    pt, pp = ra.predicted_us({"ttft_mean_ms": 1500.0,
                              "request_itl_mean_ms": 4.5, "itl_mean_ms": 17.0})
    ck("predicted TTFT is ms scaled to microseconds", abs(pt - 1.5e6) < 1, f"{pt}")
    ck("predicted TPOT comes from request_itl_mean_ms (per token), not itl_mean_ms",
       abs(pp - 4500.0) < 1, f"{pp}")
    # Missing request_itl_mean_ms fails loud rather than silently using the step interval.
    try:
        ra.predicted_us({"ttft_mean_ms": 1500.0, "itl_mean_ms": 17.0})
        ck("a metrics file without request_itl_mean_ms is rejected", False, "no error raised")
    except SystemExit:
        ck("a metrics file without request_itl_mean_ms is rejected", True)

    r = ra.csv_row(ROW, sweep, pt, pp)
    ck("the CSV row has exactly build_summary's columns",
       list(r.keys()) == ra.CSV_HEADER, str(list(r.keys())))
    ck("measured and predicted land in the right columns",
       r["meas_ttft_us"] == round(mt, 3) and r["pred_ttft_us"] == round(pt, 3)
       and r["meas_tpot_us"] == round(mp, 3) and r["pred_tpot_us"] == round(pp, 3))
    # Point 5: agentic points go in the "all" bucket, not the stricter measured_or_resolved.
    ck("the point is tagged the ALL tier (not measured_or_resolved)",
       r["tier_unbracketed"] == "ALL (approximate)", r["tier_unbracketed"])

    # agentic_replay_args: built from row + server log, NOT the CI job log.
    args, refusals = ra.agentic_replay_args(ROW, server)
    ck("no refusals for a supported, synthetic-acceptance row", refusals == [], str(refusals))
    ck("concurrency is taken from the row",
       "--concurrency" in args and args[args.index("--concurrency") + 1] == "2")
    # Point 3: duration 3600s is passed explicitly (the measured runs' window).
    ck("the AgentX duration 3600s is passed",
       "--benchmark-duration" in args
       and args[args.index("--benchmark-duration") + 1] == "3600s", str(args))
    ck("the synthetic acceptance length is passed from the server log",
       "--speculative-acceptance-length" in args
       and args[args.index("--speculative-acceptance-length") + 1] == "3.84")
    # Point 2: seed is NOT passed (left to blis's default of 42, which matches InferenceX).
    ck("seed is NOT passed (blis defaults to 42, matching InferenceX)",
       "--seed" not in args, str(args))
    # A speculative run whose acceptance is an outcome (not synthetic) is still refused.
    srv_nonsynth = {"speculative_method": "dspark", "rejection_sample_method": "rejection"}
    _, ref2 = ra.agentic_replay_args(ROW, srv_nonsynth)
    ck("a non-synthetic speculative run is refused (acceptance not a stated value)",
       any("synthetic acceptance" in x for x in ref2), str(ref2))
    # A row missing concurrency is refused rather than defaulted.
    _, ref3 = ra.agentic_replay_args({k: v for k, v in ROW.items() if k != "conc"}, {})
    ck("a row with no concurrency is refused", any("concurrency" in x for x in ref3), str(ref3))

    # The silent-speculation case (PR #21 re-review, #24c): the API row says spec_method=mtp
    # but the server log states no speculative_config (empty server dict -- most agentic logs
    # have no args line). Scoring it would price a drafting deployment as PLAIN decoding, so
    # it must be REFUSED, not scored. A wrong number is worse than a missing one.
    _, ref4 = ra.agentic_replay_args(dict(ROW, spec_method="mtp"), {})
    ck("a speculative row whose server log has no speculative_config is refused",
       any("priced as plain decoding" in x for x in ref4), str(ref4))
    ck("the refusal names the row's spec_method",
       any("mtp" in x for x in ref4), str(ref4))
    # A NON-speculative row with an empty server log is fine (no speculation to lose).
    _, ref5 = ra.agentic_replay_args(dict(ROW, spec_method="none"), {})
    ck("a non-speculative row with an empty server log is not refused for speculation",
       not any("plain decoding" in x for x in ref5), str(ref5))

    # Point 4: DP-attention width is derived from the row (num_decode_gpu / decode_tp),
    # not hard-coded to 2. A 32-GPU tp8 DP-attention row is dp4.
    dp_row = dict(ROW, decode_dp_attention=True, num_decode_gpu=32, decode_tp=8, decode_ep=32)
    ck("attention-DP width is derived from the row (32/8 = 4, not a hard-coded 2)",
       ra._attention_dp_size(dp_row) == 4, str(ra._attention_dp_size(dp_row)))
    ck("a non-DP row has attention_dp_size 1", ra._attention_dp_size(ROW) == 1)


def run_driver(td: Path, row: dict, blis_stub: str) -> subprocess.CompletedProcess:
    """Drive run_agentic.main() with a fake blis that writes a fixed metrics file.

    Deliberately passes NO --job-log: the external repo's Actions log is usually unreadable,
    and the driver must score without it (seed/duration default, concurrency from the row).
    """
    (td / "row.json").write_text(json.dumps(row))
    (td / "server.log").write_text(SERVER_LOG)
    blis = td / "blis_stub.sh"
    blis.write_text(blis_stub)
    blis.chmod(0o755)
    return subprocess.run(
        [sys.executable, str(HERE / "run_agentic.py"),
         "--row", str(td / "row.json"), "--server-log", str(td / "server.log"),
         "--corpus", str(td / "traces.jsonl"),
         "--corpus-sha256", "deadbeef", "--blis", str(blis),
         "--catalog", str(td), "--registry", str(td), "--out-dir", str(td / "out")],
        capture_output=True, text=True)


def test_driver_scores_a_supported_row():
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        (td / "traces.jsonl").write_text("{}\n")
        # A fake blis: record its argv, and on --metrics-path write a fixed MetricsOutput.
        # It writes BOTH itl_mean_ms (step interval) and request_itl_mean_ms (per token) so
        # the test confirms the driver reads the per-token one.
        stub = (
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' \"$@\" > \"$(dirname \"$0\")/argv.txt\"\n"
            "while [ $# -gt 0 ]; do [ \"$1\" = --metrics-path ] && echo "
            "'{\"ttft_mean_ms\": 1500.0, \"request_itl_mean_ms\": 4.5, \"itl_mean_ms\": 17.0}'"
            " > \"$2\"; shift; done\n"
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
            row_cells = dict(zip(ra.CSV_HEADER, lines[1].split(",")))
            # Predicted TPOT = request_itl_mean_ms (4.5ms = 4500us), NOT itl_mean_ms (17ms).
            ck("predicted TPOT in the CSV is the per-token metric (4500us, not 17000)",
               row_cells["pred_tpot_us"] == "4500.0", row_cells["pred_tpot_us"])
            ck("the CSV point is ALL tier", row_cells["tier_unbracketed"] == "ALL (approximate)")
        # Point 6: the scenario blis was given must carry a speculative: block (it drafts),
        # else blis would refuse --speculative-acceptance-length. And that flag is passed.
        argv = (td / "argv.txt").read_text() if (td / "argv.txt").exists() else ""
        ck("--speculative-acceptance-length is passed to blis",
           "--speculative-acceptance-length" in argv)
        ck("--benchmark-duration 3600s is passed to blis", "3600s" in argv)
        scen = list((td / "out" / "scenarios").glob("*.yaml"))
        ck("a scenario file is written", len(scen) == 1, str(scen))
        if scen:
            y = scen[0].read_text()
            ck("the scenario drafts (has a speculative: block so the accept flag applies)",
               "speculative:" in y and "num_spec_tokens:" in y, y[-200:])
        corpus = td / "out" / "agentic_corpus.json"
        ck("a facets corpus is written", corpus.exists())
        if corpus.exists():
            doc = json.loads(corpus.read_text())
            ck("the corpus records the fixed-workload fidelity",
               doc.get("fidelity") == "fixed-workload", str(doc.get("fidelity")))


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
