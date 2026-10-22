#!/usr/bin/env python3
"""Score BLIS against one agentic InferenceX row: mean TTFT + TPOT, apples-to-apples.

An `agentic_traces` row is one AgentX benchmark against one vLLM server. inference-sim
replays that benchmark exactly (`blis replay --agentic-scenario inferencex-agentx-mvp`),
emitting the same mean TTFT and mean inter-token latency the row measured. This driver
ties the pieces together and shapes the result into the dashboard's existing per-point
CSV, so `build_summary.py` scores it with no new scoring code:

  the row            fetch_agentic_rows.py (API) -> measured mean_ttft / mean_tpot (the
                     MEASURED side) + the deployment topology (model, gpu, precision,
                     parallelism, spec method).
  the replay args    agentic_replay_args(row, server) -> --concurrency (from the row),
                     --benchmark-duration 3600s (the documented AgentX window the measured
                     runs used) and --speculative-acceptance-length (from the server log,
                     with PR #19's no-guess rule). --seed is left to blis's default of 42,
                     which matches InferenceX's --random-seed 42 -- not READ per row, so
                     still a FIXED workload rather than a bit-exact per-row replay.
  the corpus         resolve_agentic_corpus.py -> --corpus traces.jsonl + --corpus-sha256.
  the scenario       gen_scenarios.emit() over the row's topology -> the Scenario +
                     Deployment YAML `blis replay` prices the server from (the SAME writer
                     the single-turn path uses, so the deployment is described identically).
  the prediction     `blis replay … --metrics-path out.json` -> ttft_mean_ms / itl_mean_ms
                     (the PREDICTED side).

A row with a refusal (unsupported model/hardware, or a speculative run with no stated
synthetic acceptance) is emitted as NOT scored, never run with a guessed value.

Fidelity: because the seed is not read per row (it is left at blis's default of 42, which
matches InferenceX's runs) this scores blis against a FIXED agentic workload -- seed 42 over
a 3600s window -- NOT a bit-exact reproduction of each measured run. The emitted corpus
records this (AGENTIC_FIDELITY) so a reader does not read it as the latter.

Mean TTFT + TPOT only: this reuses the existing summary.json shape and UI. An agentic row
is a single concurrency point, so it has no shape curve -- build_summary.py already treats
a <3-point sweep as shapeless (MAPE computed, shape null), so nothing downstream changes.

This is a LOCAL driver (run by hand against API data), NOT wired into the automated
nightly/ci-verify pipeline -- that still scores the db-dump. The blis binary, catalog and
registry it uses are the ones evaluate.sh already built into $WORK.

Usage:
    python orchestrator/run_agentic.py \
        --row .work/agentic/row-439932.json \
        --server-log .work/agentic/server-439932.log \
        --corpus .work/agentic/corpus/traces.jsonl --corpus-sha256 <hex> \
        --blis $WORK/inference-sim/blis --catalog $WORK/catalog --registry $WORK/registry \
        --out-dir .work/agentic/scored
        # --job-log is optional: only pins --max-context-length when readable.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from extract_agentic_replay_args import (AGENTX_SCENARIO, parse_job_log,  # noqa: E402
                                         parse_server_log)
from gen_scenarios import emit  # noqa: E402

# Agentic InferenceX model/GPU slug -> blis-catalog name. SEPARATE from the single-turn
# extractor's maps (direct_corpus_common.MODELS/CHIPS), which were curated for the models
# NVIDIA published on the db-dump: the agentic rows measure newer models the catalog has
# since gained graphs for. Keeping the two maps independent is the plan's "two sources,
# one pipeline" separation -- extending the single-turn map here would drift it from its
# documented provenance. A slug absent here is NOT scored (see sweep_from_row): the #15
# "unsupported model" rule -- carried as not-scored, never priced with a guess.
#
# Verified against blis-catalog 0.3.0's models/ directory (each name is a graph dir there).
AGENTIC_MODELS = {
    "kimik3": "kimi-k3",
    "kimik2.5": "kimi-k2.5",
    "kimik2.6": "kimi-k2.6",
    "dsv4": "deepseek-v4-pro",
    "dsv4flash": "deepseek-v4.1-flash",
    "minimaxm3": "minimax-m3",
    "glm5": "glm-5",
    "glm5.1": "glm-5",
    "qwen3.5": "qwen3.5-397b-a17b",
}

# Agentic GPU slug -> blis-catalog hardware. Only parts blis-registry prices are scoreable;
# a chip absent here (gb200/gb300/mi355x/tpuv7 appear in agentic rows) is NOT scored, the
# same rule as the model map -- the registry has no coefficients for a new hardware family.
AGENTIC_CHIPS = {"h100": "h100", "h200": "h200", "b200": "b200", "b300": "b300"}

# The CSV columns build_summary.py requires (its EXPECTED_HEADER). Latencies in MICROSECONDS.
CSV_HEADER = [
    "scenario", "model", "gpu", "label", "concurrency",
    "meas_tpot_us", "pred_tpot_us", "meas_ttft_us", "pred_ttft_us", "tier_unbracketed",
]

# The scored tier. build_summary.py maps "ALL (approximate)" to the "all" bucket ONLY --
# NOT the stricter "measured_or_resolved". Agentic points belong in "all": the deployment is
# rebuilt from API fields and seed/duration are defaulted (not read per row), so they are not
# the bit-exact, fully-stated configuration the measured_or_resolved tier is for. Putting them
# there would show them beside exactly-configured single-turn points as if equally pinned
# (PR #21 review, point 5).
AGENTIC_TIER = "ALL (approximate)"

# Whether the agentic replay reproduces the exact measured run (bit-exact) or a fixed
# workload. Surfaced in the emitted corpus so a reader never mistakes one for the other.
AGENTIC_FIDELITY = "fixed-workload"

# The AgentX sending window passed to every agentic replay. 3600s is the documented setting
# every InferenceX agentic job log checked actually ran (blis's scenario default is 1800s),
# so passing it matches the measured runs' request population without reading the job log.
AGENTIC_DURATION_S = 3600

# Agentic rows carry no isl/osl workload; label them by the scenario the harness replays.
AGENTIC_LABEL = "agentx"

# The context window the scenario's max_model_len must admit. The AgentX corpus is the
# cc-traces-weka 256k set, so the deployment must serve up to 256k-token sequences; a run
# that pinned --max-context-length lower is read from the job log and used instead. Passed
# to gen_scenarios.emit() as a parseable "<ctx>:0" workload so context_length() sizes
# max_model_len from it (emit expects an isl:osl pair; agentic has none, so osl is 0).
AGENTIC_CONTEXT_DEFAULT = 262144


def support_refusals(row: dict) -> list[str]:
    """Reasons the row's deployment cannot be priced: an unsupported model or chip.

    These are the #15 "unsupported model / new hardware" cases -- a row InferenceX measured
    that the pinned catalog/registry has no graph or coefficients for. They are reported as
    refusals (carried as not-scored), never priced with a guess, exactly as PR #19's
    log-derived refusals are.
    """
    out = []
    slug, gpu_raw = row.get("model"), row.get("hardware")
    if slug not in AGENTIC_MODELS:
        out.append(f"model {slug!r} is not in the pinned catalog (no graph to price it)")
    if gpu_raw not in AGENTIC_CHIPS:
        out.append(f"hardware {gpu_raw!r} has no registry coefficients")
    return out


def agentic_replay_args(row: dict, server: dict) -> tuple[list[str], list[str]]:
    """The `blis replay --agentic-scenario` args for one row, and any refusals.

    Unlike PR #19's `replay_args` (which reads every input from the CI job log and REFUSES a
    row whose seed/corpus it cannot read), this builds the args from what is reachable
    WITHOUT the job log, because the job log lives on an external GitHub repo
    (SemiAnalysisAI/InferenceX) whose Actions logs the dashboard's token cannot read:

      --concurrency                 from the row (the API states it)
      --benchmark-duration 3600s    the documented AgentX sending window: every InferenceX
                                    agentic job log checked ran --benchmark-duration 3600,
                                    so passing it (rather than blis's 1800s scenario default)
                                    matches the measured runs' request population without
                                    needing the job log (AGENTIC_DURATION_S).
      --speculative-acceptance-length  from the SERVER log (restored in the dump / API),
                                    with PR #19's rule: a speculative run is refused unless
                                    its acceptance is a stated synthetic value, never guessed
      --corpus / --corpus-sha256    supplied by the caller (the scenario pins the 256k corpus)

    What it does NOT pass, and why that is a documented tradeoff rather than a refusal:

      --seed              only the job log states the exact seed; omitted, blis uses its
                          default of 42 (cmd/root.go:853). That default HAPPENS to match
                          InferenceX, whose job logs all run --random-seed 42, so the fixed
                          workload likely matches the measured seed -- but we do not read it
                          to confirm per row, so this is still a fixed, not bit-exact, replay.
                          The seed selects WHICH traces populate the lanes.

    So the comparison is blis-vs-InferenceX on a FIXED agentic workload (seed 42, 3600s),
    not a bit-exact per-row reproduction (the seed/duration are not read from each row's job
    log). The emitted corpus records this (AGENTIC_FIDELITY). A speculative run with no stated
    synthetic acceptance is still refused -- that one IS a value we would otherwise invent.
    """
    refusals = []
    args = ["--agentic-scenario", AGENTX_SCENARIO,
            "--benchmark-duration", f"{AGENTIC_DURATION_S}s"]
    conc = row.get("conc")
    if conc is None:
        refusals.append("row does not state concurrency")
    else:
        args += ["--concurrency", str(int(conc))]
    if "speculative_method" in server:
        if server.get("rejection_sample_method") != "synthetic":
            refusals.append("speculative run without a synthetic acceptance setting: "
                            "its acceptance is an outcome, not a stated value")
        elif "synthetic_acceptance_length" not in server:
            refusals.append("synthetic speculative run with no synthetic_acceptance_length")
        else:
            # repr: the shortest text that reads back as the same float (3.84 stays "3.84").
            args += ["--speculative-acceptance-length",
                     repr(server["synthetic_acceptance_length"])]
    return args, refusals


def _attention_dp_size(row: dict) -> int:
    """The attention-DP width of a DP-attention decode deployment, from the row.

    A DP-attention run shards attention over num_decode_gpu / decode_tp replicas (e.g.
    32 GPUs / tp8 = dp4). Derived rather than guessed; falls back to 1 when the row does
    not mark DP attention, and to 2 only if the fields are missing on a DP-attention row
    (a conservative non-1 default rather than a silent 1)."""
    if not row.get("decode_dp_attention"):
        return 1
    gpus = int(row.get("num_decode_gpu") or 0)
    tp = int(row.get("decode_tp") or 0)
    if gpus and tp and gpus % tp == 0 and gpus // tp > 1:
        return gpus // tp
    return 2


def sweep_from_row(row: dict, server: dict | None = None,
                   max_context: int | None = None) -> dict:
    """A gen_scenarios.emit()-shaped deployment dict from an agentic API row.

    Maps the row's slugs to catalog names and its parallelism the same way the direct
    extractor does, so the scenario describes the measured deployment. The caller must
    first check support_refusals(row) is empty; this assumes the model and chip are known.

    `server` (parse_server_log output) supplies the speculative method and K. A speculative
    row's scenario MUST carry a `speculative:` block: `blis replay` refuses
    --speculative-acceptance-length when the scenario drafts no tokens
    (cmd/speculative_acceptance.go:87). So the method + num_speculative_tokens are written
    into stated_config, and gen_scenarios.emit() renders the block.

    `max_context` (from the job log's --max-context-length, if the run pinned one) sizes
    the scenario's max_model_len; absent, the 256k corpus default is used.
    """
    server = server or {}
    ctx = int(max_context) if max_context else AGENTIC_CONTEXT_DEFAULT
    slug, gpu_raw = row.get("model"), row.get("hardware")
    model = AGENTIC_MODELS[slug]
    chip = AGENTIC_CHIPS[gpu_raw]
    tp = int(row.get("decode_tp") or 1)
    ep = int(row.get("decode_ep") or 1)
    dp = _attention_dp_size(row)
    precision = row.get("precision") or "fp8"
    spec = row.get("spec_method") or "none"
    tag = f"tp{tp}"
    if ep > 1:
        tag += f"-ep{ep}"
    if dp > 1:
        tag += f"-dp{dp}"
    if spec != "none":
        tag += f"-{spec}"
    scenario = f"{model}-{chip}-{precision}-vllm-{tag}-agentx.yaml"
    # The scenario must draft for the acceptance-length flag to apply. method comes from the
    # server log's speculative_config (its vLLM name, e.g. dspark/mtp/eagle3 -- all priced by
    # blis, sim/config.go:317); K from num_speculative_tokens. gpu_memory_utilization etc.
    # are left to emit()'s defaults, as on the single-turn path.
    stated: dict = {}
    if spec != "none" and server.get("num_speculative_tokens"):
        stated["speculative_method"] = server.get("speculative_method") or spec
        stated["num_speculative_tokens"] = int(server["num_speculative_tokens"])
    return {
        "scenario": scenario,
        "model": model,
        "gpu": chip,
        "framework": "vllm",
        "precision": precision,
        "serving": "aggregated",
        "spec_method": spec,
        "parallelism": {"tp_size": tp, "pp_size": 1,
                        "attention_dp_size": dp,
                        "moe_ep_size": ep,
                        "moe_tp_size": 1 if ep > 1 else tp},
        "stated_config": stated,
        # A parseable "<ctx>:0" pair so gen_scenarios.emit() sizes max_model_len to the
        # agentic context window (emit expects isl:osl; agentic has no fixed osl).
        "workload": f"{ctx}:0",
    }


def measured_us(row: dict) -> tuple[float, float]:
    """(measured_ttft_us, measured_tpot_us) from the row. The API reports SECONDS; the CSV
    convention is microseconds, so both are scaled by 1e6."""
    m = row.get("metrics") or {}
    ttft_s = m.get("mean_ttft")
    tpot_s = m.get("mean_tpot")
    if ttft_s is None or tpot_s is None:
        raise SystemExit("row.metrics is missing mean_ttft/mean_tpot")
    return float(ttft_s) * 1e6, float(tpot_s) * 1e6


def predicted_us(metrics_json: dict) -> tuple[float, float]:
    """(pred_ttft_us, pred_tpot_us) from a blis --metrics-path MetricsOutput, in microseconds.

    TPOT comes from `request_itl_mean_ms`, NOT `itl_mean_ms`. The two differ under
    speculative decoding, which every agentic row here uses (DSpark):

      itl_mean_ms          the per-DECODE-STEP interval. A step accepts AL tokens (AL ~ 3.8
                           for DSpark), so this is ~AL times the per-token value.
      request_itl_mean_ms  aiperf's ITL, (latency - TTFT) / (OSL - 1), per TOKEN
                           (sim/metrics_measured.go:64-67, pinned by
                           TestMetricsPath_DSparkRequestITLIsTheStepIntervalOverTheAccepted-
                           Length). This is what InferenceX/aiperf reports as mean_tpot.

    Reading itl_mean_ms would make predicted TPOT ~AL times too high and read as a BLIS
    accuracy failure that is really a metric mismatch (PR #21 review, point 1). TTFT is
    ttft_mean_ms, which the file already restates over the measured window.
    """
    ttft_ms = metrics_json.get("ttft_mean_ms")
    # request_itl_mean_ms is the per-token metric; fall back to itl_mean_ms only if a
    # (non-speculative) build did not emit it, so a missing key fails loud rather than
    # silently reverting to the step interval.
    tpot_ms = metrics_json.get("request_itl_mean_ms")
    if ttft_ms is None or tpot_ms is None:
        raise SystemExit("blis metrics JSON missing ttft_mean_ms/request_itl_mean_ms "
                         "(need a --metrics-path file from a build that emits the "
                         "aiperf-defined measured metrics)")
    return float(ttft_ms) * 1e3, float(tpot_ms) * 1e3


def csv_row(row: dict, sweep: dict, pred_ttft_us: float, pred_tpot_us: float) -> dict:
    """One build_summary.py CSV row for a scored agentic point."""
    meas_ttft_us, meas_tpot_us = measured_us(row)
    return {
        "scenario": sweep["scenario"],
        "model": sweep["model"],
        "gpu": sweep["gpu"],
        "label": AGENTIC_LABEL,
        "concurrency": int(row.get("conc") or 1),
        "meas_tpot_us": round(meas_tpot_us, 3),
        "pred_tpot_us": round(pred_tpot_us, 3),
        "meas_ttft_us": round(meas_ttft_us, 3),
        "pred_ttft_us": round(pred_ttft_us, 3),
        "tier_unbracketed": AGENTIC_TIER,
    }


def facets_corpus(sweep: dict, row: dict) -> dict:
    """A minimal corpus JSON in the shape build_summary.py:read_corpus_facets joins on
    (scenario, label). Carries the deployment facets and marks the workload agentic."""
    return {
        "source": "SemiAnalysis InferenceX (agentic_traces, live API)",
        "benchmark_type": "agentic_traces",
        # Not a bit-exact per-row replay: seed and sending-window duration are left at blis's
        # defaults (the CI job log that states them is on an unreadable external repo), so the
        # replay is a FIXED agentic workload. Recorded so a reader never reads these numbers
        # as an exact reproduction of each measured run.
        "fidelity": AGENTIC_FIDELITY,
        "fidelity_note": ("seed and benchmark-duration are blis defaults, not the measured "
                          "run's values; concurrency and speculative acceptance are read"),
        "sweeps": [{
            "scenario": sweep["scenario"],
            "label": AGENTIC_LABEL,
            "model": sweep["model"],
            "gpu": sweep["gpu"],
            # The UI groups a workload by isl_osl; agentic has none, so surface the label
            # (the emit() sizing pair sweep["workload"] stays internal to the scenario).
            "workload": AGENTIC_LABEL,
            "framework": sweep["framework"],
            "precision": sweep["precision"],
            "serving": sweep["serving"],
            "spec_method": sweep["spec_method"],
            "parallelism": sweep["parallelism"],
            "source_row_id": str(row.get("id")),
            "source_run_url": row.get("run_url"),
            "image": row.get("image"),
        }],
    }


def build_blis_argv(blis: str, scenario_name: str, scenarios_dir: str, catalog: str,
                    registry: str, corpus: str, corpus_sha256: str,
                    replay: list[str], metrics_path: str) -> list[str]:
    """The full `blis replay --agentic-scenario` command. `replay` is PR #19's arg list,
    which already carries --agentic-scenario + --seed/--concurrency/--benchmark-duration
    and (for a synthetic-acceptance run) --speculative-acceptance-length."""
    return [
        blis, "replay",
        *replay,
        "--corpus", corpus,
        "--corpus-sha256", corpus_sha256,
        "--scenario", scenario_name,
        "--scenarios", scenarios_dir,
        "--catalog", catalog,
        "--registry", registry,
        "--metrics-path", metrics_path,
    ]


def write_csv(rows: list[dict], path: Path) -> None:
    import csv
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_HEADER)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--row", required=True, help="row-<id>.json from fetch_agentic_rows.py")
    ap.add_argument("--server-log", required=True)
    ap.add_argument("--job-log", default=None,
                    help="optional CI job log; only used to pin --max-context-length. "
                         "Omit when the external repo's Actions logs are unreadable; "
                         "seed/duration are left to blis's defaults regardless.")
    ap.add_argument("--corpus", required=True, help="traces.jsonl")
    ap.add_argument("--corpus-sha256", required=True)
    ap.add_argument("--blis", required=True, help="the blis binary evaluate.sh built")
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--registry", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    row = json.loads(Path(args.row).read_text())
    server = parse_server_log(Path(args.server_log).read_text())
    # The job log is OPTIONAL and used only as a hint for --max-context-length: the external
    # repo's Actions logs are usually unreadable, and seed/duration are deliberately left to
    # blis's defaults (see agentic_replay_args). When present, its --max-context-length pins
    # max_model_len to exactly what the run used.
    job = {}
    if args.job_log:
        jt = Path(args.job_log).read_text()
        job = parse_job_log(jt) if jt.strip() else {}

    replay, refusals = agentic_replay_args(row, server)
    # Unsupported model / new hardware (the #15 case) is a refusal too, read from the row
    # itself. Combine both so an unscoreable row is not run at all.
    refusals = support_refusals(row) + refusals

    if refusals:
        # Not scored: either the replay args are incomplete (running would require guessing
        # a value, which the no-tuning rule forbids) or the model/hardware is unsupported
        # (#15). Record why and stop (no CSV row, no blis run).
        (out / "refusals.json").write_text(json.dumps(
            {"row_id": str(row.get("id")), "refusals": refusals}, indent=2) + "\n")
        print(f"row {row.get('id')} NOT scored ({len(refusals)} refusal(s)):", file=sys.stderr)
        for r in refusals:
            print(f"  - {r}", file=sys.stderr)
        return 0

    # Supported and replayable: build the deployment sweep + its facets corpus. `server`
    # supplies the speculative method/K the scenario must draft with; if the run pinned
    # --max-context-length (job log), size max_model_len to it, else the 256k default.
    sweep = sweep_from_row(row, server=server,
                           max_context=job.get("max_context_length"))
    corpus_doc = facets_corpus(sweep, row)
    (out / "agentic_corpus.json").write_text(json.dumps(corpus_doc, indent=2) + "\n")

    # Write the scenario the row's deployment prices from, into a scenarios dir blis reads.
    scen_dir = out / "scenarios"
    scen_dir.mkdir(exist_ok=True)
    (scen_dir / sweep["scenario"]).write_text(
        emit(sweep, {sweep["workload"]}, {AGENTIC_LABEL}))

    metrics_path = out / f"blis-metrics-{row.get('id')}.json"
    argv = build_blis_argv(
        args.blis, sweep["scenario"], str(scen_dir), args.catalog, args.registry,
        args.corpus, args.corpus_sha256, replay, str(metrics_path))
    print("running:", " ".join(argv), file=sys.stderr)
    proc = subprocess.run(argv, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr[-4000:])
        raise SystemExit(f"blis replay failed (exit {proc.returncode}) for row {row.get('id')}")

    metrics = json.loads(metrics_path.read_text())
    pred_ttft_us, pred_tpot_us = predicted_us(metrics)
    r = csv_row(row, sweep, pred_ttft_us, pred_tpot_us)
    write_csv([r], out / "signedprobe.csv")  # same name/shape build_summary.py reads

    print(f"row {row.get('id')} scored -> {out/'signedprobe.csv'}")
    print(f"  measured ttft={r['meas_ttft_us']/1e3:.1f}ms tpot={r['meas_tpot_us']/1e3:.3f}ms "
          f"| predicted ttft={r['pred_ttft_us']/1e3:.1f}ms tpot={r['pred_tpot_us']/1e3:.3f}ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
