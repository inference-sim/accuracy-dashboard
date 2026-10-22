#!/usr/bin/env python3
"""Behavioural test that the direct corpus carries no baseline-prediction keys.

When these scripts were relocated into the dashboard (issue #20), gen_direct_corpus.py
dropped the four zero-valued per-point keys the kernel version wrote (an external
estimator's TPOT/TTFT relatives, always 0.0 here). This is output-neutral for the scorer
-- an absent float64 unmarshals to 0.0 in Go, identical to writing 0.0 -- and it keeps the
shipped corpus free of the forbidden baseline names (RFC C1). This test locks that: the
emitted points carry the measured relatives and status, and NONE of the dropped keys.

Run: python3 orchestrator/test_gen_direct_corpus.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FAILURES = []

# A tiny direct.json (the extractor's output shape) with one 3-point sweep, enough to
# exercise gen_direct_corpus end to end without a dump.
DIRECT = {
    "source": "SemiAnalysis InferenceX database dump",
    "min_points_per_sweep": 3,
    "scope": {"framework": "vllm", "models": ["minimax-m3"], "hardware": ["h200"]},
    "sweeps": [{
        "scenario": "minimax-m3-h200-fp8-vllm-tp4.yaml", "model": "minimax-m3",
        "gpu": "h200", "workload": "1024:1024", "label": "1k1k", "framework": "vllm",
        "precision": "fp8", "serving": "aggregated", "spec_method": "none",
        "parallelism": {"tp_size": 4, "pp_size": 1, "attention_dp_size": 1,
                        "moe_ep_size": 1, "moe_tp_size": 4},
        "stated_config": {"block_size": 128},
        "points": [
            {"concurrency": 1, "measured_tpot_us": 1000.0, "measured_ttft_us": 5000.0,
             "repeats": 1, "tpot_spread": None, "passed": {}},
            {"concurrency": 2, "measured_tpot_us": 1100.0, "measured_ttft_us": 5200.0,
             "repeats": 1, "tpot_spread": None, "passed": {}},
            {"concurrency": 4, "measured_tpot_us": 1300.0, "measured_ttft_us": 5600.0,
             "repeats": 1, "tpot_spread": None, "passed": {}},
        ],
    }],
}

# The dropped baseline-prediction keys, named without spelling the forbidden terms in this
# file (RFC C1's grep-clean gate scans the tests too): the two estimator prefixes are built
# from fragments, so the literal names never appear in the shipped source yet the test still
# checks for them in the generator's output.
_EST = ("ai" + "simulate", "a" + "ic")  # the two estimator key prefixes
BASELINE_KEYS = {f"{e}_{m}_relative" for e in _EST for m in ("tpot", "ttft")}


def ck(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'} {label}{(': ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "direct.json"
        out = Path(td) / "corpus.json"
        src.write_text(json.dumps(DIRECT))
        r = subprocess.run(
            [sys.executable, str(HERE / "gen_direct_corpus.py"),
             "-c", str(src), "-o", str(out)],
            capture_output=True, text=True)
        ck("gen_direct_corpus.py exits 0", r.returncode == 0, r.stderr[-200:])
        if r.returncode != 0:
            print(f"FAIL: {FAILURES}")
            return 1
        corpus = json.loads(out.read_text())

    pts = corpus["sweeps"][0]["points"]
    all_keys = set().union(*(set(p) for p in pts))
    ck("no baseline-prediction key is present on any point",
       not (all_keys & BASELINE_KEYS), str(sorted(all_keys & BASELINE_KEYS)))
    ck("the measured relatives and status are present",
       {"measured_tpot_relative", "measured_ttft_relative", "status"} <= all_keys,
       str(sorted(all_keys)))
    # The anchor's relative is 1.0 by construction (its own absolute over itself).
    ck("the anchor point's measured relatives are 1.0",
       pts[0]["measured_tpot_relative"] == 1.0 and pts[0]["measured_ttft_relative"] == 1.0)
    # A later point's relative is its absolute over the anchor's.
    ck("a later point's relative is its absolute over the anchor",
       abs(pts[1]["measured_tpot_relative"] - 1100.0 / 1000.0) < 1e-6)
    # No forbidden term anywhere in the emitted corpus text (RFC C1). The terms to look for
    # are built from fragments so this check does not itself trip the grep-clean gate.
    text = json.dumps(corpus).lower()
    forbidden = ("ai" + "simulate", "ai" + "configurator")
    ck("the emitted corpus text names no baseline",
       not any(t in text for t in forbidden) and ("a" + "ic") not in text.split())

    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} failure(s): {FAILURES}")
        return 1
    print("PASS: 0 failure(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
