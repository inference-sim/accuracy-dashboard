"""The tools that reconstruct a launch from an InferenceX benchmark script (orchestrator/supplemental): the script is run
under a restricted PATH with `vllm` stubbed, its own shell arithmetic and heredocs give the launch, and the launch is written as
the CLI-spelled flags the scorer reads. A one-commit repository stands in for InferenceX.

Run: python3 -m pytest orchestrator/ingest/test_supplemental_tools.py
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent / "supplemental"

SCRIPT = r'''#!/usr/bin/env bash
if [ "$ISL" = "1024" ] && [ "$OSL" = "1024" ]; then
    CALCULATED_MAX_MODEL_LEN=$((ISL + OSL + 20))
else
    CALCULATED_MAX_MODEL_LEN=$((ISL + OSL + 200))
fi
cat > config.yaml << EOF
kv-cache-dtype: fp8
no-enable-prefix-caching: true
max-num-batched-tokens: 8192
max-model-len: $CALCULATED_MAX_MODEL_LEN
EOF
export TORCH_CUDA_ARCH_LIST="9.0"
SERVER_LOG=$(mktemp /tmp/server-XXXXXX.log)
PYTHONNOUSERSITE=1 vllm serve $MODEL --host 0.0.0.0 --port $PORT --config config.yaml \
 --gpu-memory-utilization 0.9 --tensor-parallel-size $TP --max-num-seqs $CONC --disable-log-requests > $SERVER_LOG 2>&1 &
while IFS= read -r line; do
    if [[ "$line" == *"Application startup complete"* ]]; then break; fi
done < <(tail -F -n0 "$SERVER_LOG")
'''


def _tools():
    repo = Path(tempfile.mkdtemp())
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    (repo / "benchmarks").mkdir()
    (repo / "benchmarks" / "70b_fp8_h100_docker.sh").write_text(SCRIPT)
    for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "x", "--no-gpg-sign"]):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True, env=env)
    commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    os.environ["INFERENCEX_GIT"] = str(repo / ".git")
    os.environ["MATCHED_PULL"] = str(repo)
    mods = {}
    for name in ("reconstruct", "supplement"):
        spec = importlib.util.spec_from_file_location(f"supp_{name}", TOOLS / f"{name}.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        mods[name] = m
    return mods, commit


def test_the_scripts_own_arithmetic_and_heredoc_give_the_launch():
    mods, commit = _tools()
    rc = mods["reconstruct"]
    env = {"MODEL": "org/m", "TP": 4, "CONC": 16, "ISL": 1024, "OSL": 1024, "PORT": 8888}
    got = rc.run_script(commit, "benchmarks/70b_fp8_h100_docker.sh", env)
    assert "error" not in got, got
    a = rc.normalise(rc.final_args(got))
    assert a["max_model_len"] == 2068            # ISL + OSL + 20, the script's own sum
    assert a["tensor_parallel_size"] == 4 and a["max_num_seqs"] == 16 and a["model"] == "org/m"
    assert a["kv_cache_dtype"] == "fp8" and a["enable_prefix_caching"] is False and a["max_num_batched_tokens"] == 8192
    assert got["env"]["TORCH_CUDA_ARCH_LIST"] == "9.0" and got["env"]["PYTHONNOUSERSITE"] == "1"
    env8k = dict(env, ISL=8192, OSL=1024)
    assert rc.final_args(rc.run_script(commit, "benchmarks/70b_fp8_h100_docker.sh", env8k))["max_model_len"] == 9416


def test_a_script_that_never_starts_vllm_is_an_error_not_an_empty_launch():
    mods, commit = _tools()
    repo = Path(os.environ["INFERENCEX_GIT"]).parent
    (repo / "benchmarks" / "70b_fp8_h100_slurm.sh").write_text("#!/usr/bin/env bash\necho nothing\n")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    for cmd in (["add", "-A"], ["commit", "-q", "-m", "y", "--no-gpg-sign"]):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True, env=env)
    c2 = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    got = mods["reconstruct"].run_script(c2, "benchmarks/70b_fp8_h100_slurm.sh", {"MODEL": "m", "TP": 1, "CONC": 1, "ISL": 1, "OSL": 1})
    assert "error" in got


def test_the_command_line_overrides_the_config_file_and_the_no_forms_are_read_as_false():
    rc = _tools()[0]["reconstruct"]
    rec = {"argv": ["serve", "org/m", "--max-model-len", "100", "--no-enable-prefix-caching"], "config_yaml": "max-model-len: 50\nkv-cache-dtype: fp8\n"}
    a = rc.normalise(rc.final_args(rec))
    assert a["max_model_len"] == 100 and a["kv_cache_dtype"] == "fp8" and a["enable_prefix_caching"] is False and a["model"] == "org/m"


def test_the_launch_is_written_as_the_flags_the_scorer_reads():
    sp = _tools()[0]["supplement"]
    flags = sp.launch_flags({"model": "org/m", "host": "0.0.0.0", "port": 8888, "tensor_parallel_size": 4, "enable_prefix_caching": False,
                             "max_model_len": 2068}, {})
    assert "model" not in flags and "host" not in flags and "port" not in flags
    assert flags["no-enable-prefix-caching"] is True and "enable-prefix-caching" not in flags
    assert flags["tensor-parallel-size"] == 4 and flags["max-model-len"] == 2068
    # --disable-log-requests is the run's own argument (translated by the scorer); the sizes the script leaves at 1 are stated
    assert flags["disable-log-requests"] is True and flags["pipeline-parallel-size"] == 1 and flags["data-parallel-size"] == 1
