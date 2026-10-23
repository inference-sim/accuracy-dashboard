"""End-to-end: one frozen single-turn point through score_point and write_contract, with fake
`blisdefaults` and `signedprobe` executables standing in for BLIS (CI has no catalog or BLIS
build). Checks the contract validates, a drafter's recorded acceptance reaches the scenario,
and a rescore is byte-identical.

Run: python3 orchestrator/ingest/test_score_e2e.py
"""
from __future__ import annotations

import gzip
import json
import shutil
import stat
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import contract as c  # noqa: E402
import score as sc  # noqa: E402
import settings as st  # noqa: E402
import support as sp  # noqa: E402

LOG = (
    "INFO [api_utils.py:286] non-default args: {'model': 'org/m', 'served_model_name': ['org/m'], "
    "'tensor_parallel_size': 1, 'max_num_seqs': 16, 'max_num_batched_tokens': 8192, 'block_size': 16, "
    "'gpu_memory_utilization': 0.9, 'max_model_len': 2304, 'enable_prefix_caching': False, "
    "'speculative_config': {'method': 'mtp', 'num_speculative_tokens': 2, "
    "'rejection_sample_method': 'synthetic', 'synthetic_acceptance_length': 2.4}}\n"
    "INFO [core.py:129] Initializing a V1 LLM engine (v0.31.0) with config: model='org/m', "
    "tensor_parallel_size=1, pipeline_parallel_size=1, data_parallel_size=1, quantization=fp8, "
    "kv_cache_dtype=auto, enable_prefix_caching=False, "
    "compilation_config={'mode': <CompilationMode.NONE: 0>, 'cudagraph_mode': <CUDAGraphMode.FULL_AND_PIECEWISE: (2, 1)>}\n"
    '"POST /v1/completions HTTP/1.1" 200\n')

FAKE_DEFAULTS = """#!/usr/bin/env python3
import json, sys
a = sys.argv[1:]
if "-resolve" in a:
    print(json.dumps({"assumptions": [], "cache_dtype": "auto", "caches": [], "dp": 1, "ep": 1, "overrides": [], "tp": 1}))
else:
    print(json.dumps({"device": "h200", "max_num_batched_tokens": 8192, "max_num_seqs": 1024, "memory_gib": 139.8}))
"""
# signedprobe: one CSV row with the measured means it was given and fixed predictions; it also
# records the scenario it ran, so the test can check what BLIS was handed.
FAKE_PROBE = """#!/usr/bin/env python3
import json, sys, pathlib
a = sys.argv[1:]
def arg(k): return a[a.index(k) + 1]
abs_ = json.loads(pathlib.Path(arg("-absolutes")).read_text())["anchors"][0]
conc = next(iter(abs_["absolute_tpot_us"]))
scen = pathlib.Path(arg("-scenarios"))
(scen.parent / "probe_saw.yaml").write_text(next(scen.glob("*.yaml")).read_text())
print("scenario,model,gpu,label,concurrency,meas_tpot_us,pred_tpot_us,meas_ttft_us,pred_ttft_us,tier_unbracketed")
print(f"x,m,h200,1k1k,{conc},{abs_['absolute_tpot_us'][conc]},9000.0,{abs_['absolute_ttft_us'][conc]},180000.0,MEASURED")
"""


def _exe(path: Path, body: str) -> str:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def _setup(tmp: Path):
    ident = {"benchmark_type": "single_turn", "conc": 4, "framework": "vllm", "hardware": "h200",
             "measured_date": "2026-10-01", "model": "m", "precision": "fp8", "recipe": "row:1"}
    pid = c.point_id(ident)
    pdir = tmp / "pull" / "points" / pid
    pdir.mkdir(parents=True)
    (pdir / "server_log.gz").write_bytes(gzip.compress(LOG.encode(), mtime=0))
    row = {"id": "1", "model": "m", "hardware": "h200", "precision": "fp8", "framework": "vllm",
           "benchmark_type": "single_turn", "conc": 4, "isl": 1024, "osl": 1024, "spec_method": "mtp",
           "disagg": False, "is_multinode": False, "decode_tp": 1, "decode_ep": 1, "num_decode_gpu": 1,
           "date": "2026-10-01", "run_url": "https://github.com/o/r/actions/runs/1", "curve_workflow_run_id": "7",
           "image": "vllm/vllm-openai:v0.31.0", "metrics": {"mean_ttft": 0.2, "mean_tpot": 0.01}}
    entry = {"point_id": pid, "identity": ident, "row": row, "reasons": [],
             "files": {"server_log": {"path": "server_log.gz", "sha256": "0" * 64, "from": "api:/server-log"}},
             "build": {"image": row["image"], "commit": "a" * 40, "source": "image_label", "ref": "v0.31.0",
                       "distance": 0, "match": "exact"}}
    env = sc.Env(blis="blis", blis_release="v0.12.0", blis_commit="b" * 40, catalog=tmp, catalog_release="0.3.0",
                 registry=tmp, registry_release="v0.2.0", kernel="v0.3.0",
                 defaults_helper=_exe(tmp / "blisdefaults", FAKE_DEFAULTS), corpus={"sha256": "c" * 64},
                 policy=st.load_policy()[0], vllm_defaults=st.load_vllm_defaults()[0])
    env.signedprobe = _exe(tmp / "signedprobe", FAKE_PROBE)
    env.single_turn_workloads = {(1024, 1024, 4)}
    env.catalog_obj = sp.Catalog(root=tmp, models={"m": "org/m"}, speculators={"m": "mtp"},
                                 hardware={"h200": 139.8}, capability={"h200": 9})
    env.parts = {"h200"}
    return entry, env


def _score(tmp: Path, entry, env, out: Path):
    work = tmp / ("work-" + out.name)
    o = sc.score_point(entry, tmp / "pull", work, env)
    prov = {"ingest": "api", "blis": {"release": "v0.12.0", "commit_sha": "b" * 40, "catalog": "0.3.0",
                                      "registry": "v0.2.0", "extractor_version": "blis-latency-kernel@v0.3.0"},
            "vllm_ref": "v0.31.0", "vllm_max_distance": 2000, "policy_sha256": "d" * 64,
            "pulled_at": "2026-10-23T00:00:00Z", "corpus": None, "pull_manifest_sha256": "e" * 64,
            "source": {"name": "test", "url": "https://example.invalid/"}, "_policy": env.policy}
    sc.write_contract(out, [o], prov)
    return o, work


def test_a_single_turn_drafter_point_scores_with_its_recorded_acceptance_and_rescores_identically():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        o, work = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        assert c.validate_dir(tmp / "c1") == []
        saw = (work / "probe_saw.yaml").read_text()
        assert "acceptance:" in saw and "acceptance_length: 2.4" in saw        # pinned for signedprobe
        assert o.fidelity["status"] == "exact"
        _score(tmp, entry, env, tmp / "c2")
        for f in ("points.csv", "fidelity.jsonl", "facets.json", "not_scored.jsonl", "provenance.json"):
            assert (tmp / "c1" / f).read_bytes() == (tmp / "c2" / f).read_bytes(), f
    finally:
        shutil.rmtree(tmp)


def test_a_point_refused_before_blis_never_calls_it():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        log = LOG.replace("'block_size': 16,", "'block_size': 16, 'prefill_schedule_interval': 4,")
        pdir = tmp / "pull" / "points" / entry["point_id"]
        (pdir / "server_log.gz").write_bytes(gzip.compress(log.encode(), mtime=0))
        env.signedprobe = _exe(tmp / "signedprobe", "#!/bin/sh\nexit 99\n")   # must not run
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is None and o.reasons == ["setting_not_modelled:prefill_schedule_interval"]
        assert c.validate_dir(tmp / "c1") == []
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
