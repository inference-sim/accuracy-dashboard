"""A frozen point through the scorer's own entry points with a real `blis` (COV-12, DEV-8).

BLIS_BIN names the blis binary and BLIS_SUBSTRATE the blis-substrate checkout its stack.json
pins (the catalog and the registry are read from it). The point is scored by score._score_one and
written by score.write_contract, so the real Result passes `blis schema validate result`, its
request_rows give the TTFT and TPOT means, and the contract validates. Without the two
variables every test here fails: a skipped test is not a passing one (X16).
"""
from __future__ import annotations

import csv
import dataclasses
import os
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import contract as c  # noqa: E402
import score as sc  # noqa: E402
import support as sp  # noqa: E402
import test_score_e2e as e2e  # noqa: E402

LOG = (
    "INFO [api_utils.py:286] non-default args: {'model': 'openai/gpt-oss-120b', 'tensor_parallel_size': 1, "
    "'max_num_seqs': 16, 'max_num_batched_tokens': 8192, 'block_size': 16, 'gpu_memory_utilization': 0.9, "
    "'max_model_len': 4096, 'enable_prefix_caching': False}\n"
    "INFO [core.py:129] Initializing a V1 LLM engine (v0.32.0) with config: model='openai/gpt-oss-120b', "
    "tensor_parallel_size=1, pipeline_parallel_size=1, data_parallel_size=1, quantization=mxfp4, "
    "kv_cache_dtype=fp8, enable_prefix_caching=False\n"
    "INFO [kv_cache_utils.py:1] GPU KV cache size: 400,000 tokens\n"
    '"POST /v1/completions HTTP/1.1" 200\n')


def _real():
    blis, sub = os.environ.get("BLIS_BIN"), os.environ.get("BLIS_SUBSTRATE")
    if not blis or not sub:
        pytest.fail("set BLIS_BIN to a blis binary and BLIS_SUBSTRATE to the blis-substrate checkout its "
                    "stack.json pins; these tests simulate and are never skipped (X16)")
    return blis, Path(sub)


def test_a_single_turn_point_is_scored_through_the_real_simulator():
    blis, sub = _real()
    tmp = Path(tempfile.mkdtemp())
    entry, env = e2e._setup(tmp, log=LOG, repo="openai/gpt-oss-120b", hardware="h100", conc=4, isl=1024, osl=128,
                            spec="none", chips={"h100": (8, 8)})
    entry["row"]["image"] = entry["build"]["image"] = "vllm/vllm-openai:v0.32.0"
    entry["build"]["ref"] = "v0.32.0"
    env = dataclasses.replace(env, blis=blis, catalog=sub / "catalog", registry=sub / "registry",
                              engine_release="0.32.0")
    env.catalog_obj = sp.Catalog(blis=blis, root=sub / "catalog")
    env.parts = {"h100"}
    o = sc._score_one(entry, tmp / "pull", tmp / "work", env)
    prov = {"ingest": "api", "blis": {"release": "v0.12.0", "commit_sha": "b" * 40, "catalog": "0.3.0",
                                      "registry": "v0.2.0", "extractor_version": "blis-latency-kernel@v0.3.0"},
            "simulator": env.simulator(), "harness_digest": env.harness_digest, "experimental": False, "units": None,
            "engine": {"kind": "vllm", "version": "0.32.0"}, "left_out_records": 0,
            "vllm_ref": "v0.32.0", "vllm_max_distance": 2000, "fields_sha256": "d" * 64,
            "pulled_at": "2026-10-23T00:00:00Z", "corpora": [], "pull_manifest_sha256": "e" * 64,
            "source": {"name": "test", "url": "https://example.invalid/"}}
    sc.write_contract(tmp / "c1", [o], prov)
    assert o.fidelity is not None, o.reasons
    assert c.validate_dir(tmp / "c1") == []
    pts = list(csv.DictReader((tmp / "c1" / c.POINTS_CSV).open()))
    assert len(pts) == 1
    ttft, tpot = float(pts[0]["pred_ttft_us"]), float(pts[0]["pred_tpot_us"])
    assert 0 < ttft < 60e6 and 0 < tpot < 1e6, (ttft, tpot)
    # The figures are the simulator's own, not the fixture's measurement.
    assert (ttft, tpot) != (200000.0, 10000.0)
