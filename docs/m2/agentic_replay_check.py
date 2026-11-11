#!/usr/bin/env python3
"""Run one agentic replay end to end through a `blis` binary, with the inputs the dashboard derives
from a real aiperf export, and show that the idle cap and the per-lane warm-up reach the simulator
and change what it does.

    agentic_replay_check.py --blis BLIS --export client_export.gz --corpus traces.jsonl \
        --scenario SCENARIO.yaml --scenarios DIR [--catalog DIR --registry DIR] --out RESULT.json

The workload spec is built by `orchestrator/ingest/replay.py` (from_export, workload_spec), the code
the scorer uses. It is run four times: as the export states it, without the 300 s per-trajectory
idle cap, without the warm-up, and without both. Each run's Result is read back: the replay frame it
echoes (the cap and the warm-up are in it only if the simulator parsed them), the measured window
(the warm-up moves its start), the request count and the two means. The outputs are
agentic-replay-check-c1.json, -c4.json and -c16.json beside this file (the concurrency of the export,
then 4 and 16 by --concurrency); docs/m2/agentic-replay-check.md says what they show.
"""
import argparse
import gzip
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "orchestrator" / "ingest"))
import replay as rp  # noqa: E402
import yaml  # noqa: E402

VARIANTS = {"as_exported": (True, True), "no_cap": (False, True), "no_warmup": (True, False), "neither": (False, False)}


def run(args, spec: dict, tmp: Path, name: str) -> dict:
    path = tmp / f"{name}.yaml"
    path.write_text(yaml.safe_dump({"replay": spec}, sort_keys=False))
    argv = [args.blis, "replay", "--agentic-scenario", spec["scenario"], "--workload-spec", str(path),
            "--concurrency", str(spec["concurrency"]), "--seed", str(spec["random_seed"]),
            "--corpus", args.corpus, "--corpus-sha256", spec["corpus"]["sha256"],
            "--scenario", Path(args.scenario).name, "--scenarios", args.scenarios,
            "--speculative-acceptance-length", str(args.acceptance_length), "--format", "json"]
    for flag, val in (("--catalog", args.catalog), ("--registry", args.registry), ("--corpus-cache", args.corpus_cache)):
        if val:
            argv += [flag, val]
    out = subprocess.run(argv, capture_output=True, text=True, check=True).stdout
    doc = json.loads(out)
    echoed = doc["frame"]["generator"]["workload"]["replay"]
    return {"frame_replay": {k: echoed.get(k) for k in ("benchmark_duration_s", "concurrency", "system_idle_gap_cap_s",
                                                       "trace_idle_gap_cap_s", "warmup")},
            "window": doc["window"], "requests": doc["requests"],
            "ttft_mean_ms": doc["metrics"]["ttft_mean_ms"], "tpot_mean_ms": doc["metrics"]["tpot_mean_ms"]}


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--blis", required=True)
    ap.add_argument("--export", required=True, help="a client_export (gzip) of the pull, or an aiperf profile export (json)")
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--scenarios", required=True, help="the directory holding the scenario file")
    ap.add_argument("--catalog")
    ap.add_argument("--registry")
    ap.add_argument("--corpus-cache")
    ap.add_argument("--acceptance-length", type=float, default=3.0)
    ap.add_argument("--duration", type=float, help="override the export's duration (s) to shorten the run")
    ap.add_argument("--concurrency", type=int, help="override the export's concurrency (the cap acts only when several lanes run)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    raw = Path(args.export).read_bytes()
    export = json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
    r = rp.from_export(export)
    if r.reasons:
        print("the export is not replayable:", r.reasons, file=sys.stderr)
        return 2
    sha = hashlib.sha256(Path(args.corpus).read_bytes()).hexdigest()
    corpus = {"repo": r.corpus_repo, "revision": "23f152f6f0f9399a85901b89a6458def0ef16729", "file": "traces.jsonl", "sha256": sha}
    base = rp.workload_spec(r, corpus)
    if args.duration:
        base["benchmark_duration_s"] = args.duration
    if args.concurrency:
        base["concurrency"] = args.concurrency
    result = {"export_sha256": hashlib.sha256(raw).hexdigest(), "client_version": r.client_version,
              "inputs_read_from_the_export": r.record(sha), "spec_as_exported": base, "runs": {}}
    with tempfile.TemporaryDirectory() as t:
        for name, (cap, warm) in VARIANTS.items():
            spec = json.loads(json.dumps(base))
            if not cap:
                spec.pop("trace_idle_gap_cap_s", None)
            if not warm:
                spec.pop("warmup", None)
            result["runs"][name] = run(args, spec, Path(t), name)
    Path(args.out).write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
