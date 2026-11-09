"""The warm-up tests that need a simulator (COV-12): run through a real `blis replay`.

BLIS_BIN names the blis binary. The scenario is BLIS_SCENARIO (default
gpt-oss-120b-h100-fp4-vllm-tp2.yaml, one replica with prefix caching on) in BLIS_SCENARIO_DIR
(default testdata/sim, which holds that file, so the default needs only BLIS_BIN). The binary
must read trace version 4 and write the Result document, schema version 2, with
request_rows, on standard output. Without BLIS_BIN every test here fails: a skipped test is not
a passing one (X16).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import inferencex_client as ix  # noqa: E402

SCENARIO = os.environ.get("BLIS_SCENARIO", "gpt-oss-120b-h100-fp4-vllm-tp2.yaml")
SCENARIO_DIR = HERE / "testdata" / "sim"


def _blis() -> tuple[str, Path]:
    blis = os.environ.get("BLIS_BIN")
    if not blis:
        pytest.fail(f"set BLIS_BIN to a blis binary (the scenario {SCENARIO} is in {SCENARIO_DIR}); "
                    "these tests simulate and are never skipped (X16)")
    return blis, Path(os.environ.get("BLIS_SCENARIO_DIR") or SCENARIO_DIR)


def _run(tmp: Path, replay: ix.Replay) -> list[dict]:
    blis, scen = _blis()
    tmp.mkdir(parents=True, exist_ok=True)
    shutil.copy(scen / SCENARIO, tmp / SCENARIO)
    (tmp / ix.ROUTER_CONFIG_NAME).write_bytes(ix.router_config_bytes())
    h, d = ix.write_trace(replay, tmp)
    argv = ix.replay_argv(blis, SCENARIO, tmp, h, d, replay.sessions, replay.pool, 42)
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=1800)
    assert proc.returncode == 0, proc.stderr[-4000:]
    doc = json.loads(proc.stdout)
    assert (doc.get("kind"), doc.get("schema_version")) == ("Result", 2)
    rows = doc.get("request_rows")
    assert rows, "the Result has no request_rows"
    return rows


def test_the_primed_main_phase_does_not_depend_on_how_many_copies_ran(tmp_path):
    """The primed main phase is the drained warm-up's state: one copy of request 0 and the
    benchmark's 2*CONC copies leave the same state, so the main phase is identical."""
    conc = 4
    ins, outs = ix.target_lengths(1024, 1024, conc)
    seen = []
    for copies in (1, ix.WARMUPS_PER_CONCURRENCY * conc):
        rows = _run(tmp_path / f"c{copies}", ix.primed_phase(ins, outs, conc, copies))
        ix.check_primed(rows, len(ins))
        seen.append(ix.summarize(rows, ins, outs, ignore=ix.main_phase_only(len(ins))))
    assert seen[0] == seen[1]


def test_a_drained_copy_leaves_only_request_zeros_prompt_readable(tmp_path):
    """After one drained copy, main request 0 reads its prompt from the prefix cache in full
    blocks, and no other main request reads anything."""
    conc = 4
    ins, outs = ix.target_lengths(1024, 1024, conc)
    rows = _run(tmp_path, ix.primed_phase(ins, outs, conc, 1))
    ix.check_primed(rows, len(ins))
    main = {ix.request_index(r["id"]): r for r in rows
            if not ix.main_phase_only(len(ins))(r["id"])}
    assert len(main) == len(ins)
    cached0 = main[0].get("cached_local_tokens", 0)
    # The scenario's block size is 16; a full prefix hit computes the prompt's last block
    # (vLLM's max_cache_hit_length = num_tokens - 1), so at most ins[0] - 1 tokens are cached.
    assert 0 < cached0 <= ins[0] - 1 and cached0 % 16 == 0
    assert cached0 >= (ins[0] - 1) // 16 * 16
    for i, r in main.items():
        if i:
            assert r.get("cached_local_tokens", 0) == 0, f"main request {i} read the cache"


def test_the_scenario_the_generator_writes_is_one_the_simulator_validates_and_runs(tmp_path):
    """gen_scenarios.emit is the scenario writer of run_agentic.py. Its output must be the
    current contract, engine: {kind, version}, at the release the scoring build runs: the real
    `blis schema validate scenario` accepts it and `blis run` loads it (the legacy engine_version
    at a release the build does not run is refused)."""
    blis, _ = _blis()
    sys.path.insert(0, str(HERE.parent))
    import gen_scenarios as g
    release = json.loads((Path(blis).parent / "stack.json").read_text())["engines"][0]["version"]
    # gpt-oss-120b on H100 at nvfp4 weights and fp8 KV is a combination the engine resolves (the
    # committed scenario runs it). A run states its block size when the engine cannot resolve it
    # (blis-vllm #68); the generator never writes one it was not given.
    dep = {"scenario": "gpt-oss-120b-h100-fp4-vllm-tp2-agentx.yaml", "model": "gpt-oss-120b", "gpu": "h100",
           "framework": "vllm", "precision": "fp4", "serving": "aggregated", "spec_method": "none",
           "parallelism": {"tp_size": 2, "pp_size": 1, "attention_dp_size": 1, "moe_ep_size": 1, "moe_tp_size": 2},
           "stated_config": {"max_model_len": 32768, "block_size": 16}, "workload": "0:0", "gpus_per_node": 8}
    text = g.emit(dep, {"0:0"}, {"agentx"}, {"gpus_per_node": None, "gpus_per_rack": None}, release)
    path = tmp_path / dep["scenario"]
    path.write_text(text)
    v = subprocess.run([blis, "schema", "validate", "scenario", str(path)], capture_output=True, text=True)
    assert v.returncode == 0, v.stderr[-2000:]
    run = subprocess.run([blis, "run", "--scenarios", str(tmp_path), "--scenario", dep["scenario"],
                          "--workload", "chatbot", "--num-requests", "8", "--seed", "1"],
                         capture_output=True, text=True, timeout=600)
    assert run.returncode == 0, run.stderr[-2000:]
    assert json.loads(run.stdout)["engine"] == {"kind": "vllm", "version": release}

