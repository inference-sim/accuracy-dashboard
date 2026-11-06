#!/usr/bin/env python3
"""Write the ledger fixture: InferenceX records shaped like export.sql's rows and the API's
rows, and the unit list and ingest report blis-substrate's own ingest tool generates from them.

TEMPORARY until inference-sim's `blis ledger` command exists (inference-sim m1/substrate, task
H): the unit list is generated here by running the ledger's ingest tool from a blis-substrate
checkout at the pinned commit. This script runs only by hand, to regenerate the fixture; no test
and no scorer runs or imports blis-substrate code (X7).

The records cover each rule of design §10.2 the harness depends on:
  r101, r102  two attempts of one benchmark run, the same measured values, the image digest on
              the second only: one unit, r102 a duplicate, the digest taken from r102;
  r103, r104  two attempts of one run, different measured values, the second a day later: one
              unit holding two measurements, measured date the earlier day;
  r105        the same measured values as r106 under another identity with the same role key
  r106        (no recipe fingerprint): merged into r105's unit;
  r107        no run_url: benchmark run null, its own date;
  r108        reports an error: left out, error_reported;
  r109        another concurrency of r101's deployment: its own unit.

Usage: build_fixture.py <blis-substrate checkout at 800ae263>
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUBSTRATE_COMMIT = "800ae26398590cb4f4f5c41fb4d89a33930ecff2"

BASE = {"model": "gptoss120b", "hardware": "h200", "precision": "fp4", "framework": "vllm",
        "benchmark_type": "single_turn", "isl": 1024, "osl": 1024, "offload_mode": "off",
        "spec_method": "none", "disagg": False, "is_multinode": False, "prefill_tp": 1,
        "prefill_ep": 1, "prefill_dp_attention": False, "prefill_num_workers": 0,
        "num_prefill_gpu": 1, "decode_tp": 1, "decode_ep": 1, "decode_dp_attention": False,
        "decode_num_workers": 0, "num_decode_gpu": 1, "image": "vllm/vllm-openai:v0.32.0",
        "recipe_fingerprint": "ab" * 32, "conc": 4}
RUN = "https://github.com/SemiAnalysisAI/InferenceX/actions/runs/{run}/attempts/{attempt}"


def rec(id_, run, attempt, date, metrics, **over):
    r = {**BASE, "id": id_, "date": date, "metrics": metrics,
         "run_url": RUN.format(run=run, attempt=attempt) if run else None,
         "run_attempt": attempt, "github_run_id": run, "run_conclusion": "success",
         "config_id": 7, "error": None}
    r.update(over)
    return r


M1 = {"mean_ttft": 0.050, "mean_tpot": 0.0100}
RECORDS = [
    rec(101, 9001, 1, "2026-06-01", M1),
    rec(102, 9001, 2, "2026-06-01", M1, image="vllm/vllm-openai:v0.32.0@sha256:" + "c" * 64),
    rec(103, 9002, 1, "2026-06-02", {"mean_ttft": 0.060, "mean_tpot": 0.0110}),
    rec(104, 9002, 2, "2026-06-03", {"mean_ttft": 0.064, "mean_tpot": 0.0114}),
    rec(105, 9003, 1, "2026-06-04", {"mean_ttft": 0.070, "mean_tpot": 0.0120}, conc=8),
    rec(106, 9004, 1, "2026-06-05", {"mean_ttft": 0.070, "mean_tpot": 0.0120}, conc=8, recipe_fingerprint=None),
    rec(107, None, 1, "2026-06-06", {"mean_ttft": 0.080, "mean_tpot": 0.0130}, conc=16),
    rec(108, 9005, 1, "2026-06-07", {}, error="OOM"),
    rec(109, 9001, 1, "2026-06-01", {"mean_ttft": 0.090, "mean_tpot": 0.0140}, conc=32),
]
EXPORT_KEYS = ("id", "github_run_id", "run_url", "run_attempt", "run_conclusion", "config_id", "model",
               "hardware", "precision", "framework", "benchmark_type", "conc", "error", "date",
               "recipe_fingerprint", "image", "isl", "osl", "offload_mode", "spec_method", "disagg",
               "is_multinode", "prefill_tp", "prefill_ep", "prefill_dp_attention", "prefill_num_workers",
               "num_prefill_gpu", "decode_tp", "decode_ep", "decode_dp_attention", "decode_num_workers",
               "num_decode_gpu", "metrics")
# What the API returns for a row: no export-only fields, the id as a string.
API_DROP = ("github_run_id", "run_attempt", "run_conclusion", "config_id", "error")


GO_MAIN = """package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"os"

	"gopkg.in/yaml.v3"

	"github.com/inference-sim/blis-substrate/ledger"
	"github.com/inference-sim/blis-substrate/ledger/inferencex"
)

func main() {
	raw, err := os.ReadFile(os.Args[1])
	if err != nil {
		panic(err)
	}
	rows, err := inferencex.ReadRows(bytes.NewReader(raw))
	if err != nil {
		panic(err)
	}
	sum := sha256.Sum256(raw)
	units, rep, err := inferencex.Ingest(rows, "fixture", hex.EncodeToString(sum[:]))
	if err != nil {
		panic(err)
	}
	var gz bytes.Buffer
	if err := ledger.EncodeUnits(&gz, units); err != nil {
		panic(err)
	}
	if err := os.WriteFile(os.Args[2], gz.Bytes(), 0o644); err != nil {
		panic(err)
	}
	y, err := yaml.Marshal(rep)
	if err != nil {
		panic(err)
	}
	if err := os.WriteFile(os.Args[3], y, 0o644); err != nil {
		panic(err)
	}
}
"""


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    sub = Path(argv[0]).resolve()
    head = subprocess.run(["git", "-C", str(sub), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    if head != SUBSTRATE_COMMIT:
        print(f"{sub} is at {head}, not {SUBSTRATE_COMMIT}", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        rows = t / "rows.jsonl"
        rows.write_text("".join(json.dumps({k: r[k] for k in EXPORT_KEYS}) + "\n" for r in RECORDS))
        # The ledger command pins the source's partition file, so the fixture calls the ingest
        # package itself, through a throwaway main inside the checkout's module.
        prog = sub / "ledger" / "cmd" / "fixtureingest"
        prog.mkdir()
        try:
            (prog / "main.go").write_text(GO_MAIN)
            (HERE / "units").mkdir(exist_ok=True)
            (HERE / "reports").mkdir(exist_ok=True)
            subprocess.run(["go", "run", "./ledger/cmd/fixtureingest", str(rows),
                            str(HERE / "units" / "inferencex.jsonl.gz"), str(HERE / "reports" / "inferencex.yaml")],
                           cwd=sub, check=True)
        finally:
            shutil.rmtree(prog)
    api = [{**{k: v for k, v in r.items() if k not in API_DROP}, "id": str(r["id"])} for r in RECORDS]
    (HERE / "api_rows.json").write_text(json.dumps(api, indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
