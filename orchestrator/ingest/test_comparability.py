"""Checks that the dashboard compares like with like (docs/comparability.md; the comparability
audit's T1, T3, T4, T7, T9, T10): the simulated request pattern is the client's, the means
are the client's own definition, the DB writer's unit mapping is the one the dashboard assumes,
and no consumer reads a Result aggregate of a single-turn point.

T3 and T4 run source of the InferenceX client, pinned by commit and sha256 in
testdata/client/SOURCE.json: the excerpts are the client's functions verbatim.

Run: python orchestrator/ingest/test_comparability.py   (or pytest)"""
from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import math
import sys
import typing
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import inferencex_client as ix  # noqa: E402

CLIENT = HERE / "testdata" / "client"


# ------------------------------------------------------------------ pinned client source

def _source(name: str) -> tuple[str, dict]:
    meta = next(m for m in json.loads((CLIENT / "SOURCE.json").read_text()) if m["excerpt"] == name)
    text = (CLIENT / name).read_text()
    assert hashlib.sha256(text.encode()).hexdigest() == meta["excerpt_sha256"], f"{name} was edited"
    assert len(meta["commit"]) == 40 and len(meta["file_sha256"]) == 64
    return text, meta


@dataclasses.dataclass
class RequestFuncOutput:                     # backend_request_func.py at 08d7a9cd, the fields used
    generated_text: str = ""
    success: bool = False
    latency: float = 0.0
    output_tokens: int = 0
    ttft: float = 0.0
    itl: list = dataclasses.field(default_factory=list)
    tpot: float = 0.0
    prompt_len: int = 0
    error: str = ""


def _calculate_metrics(name: str):
    src, _ = _source(name)
    import numpy as np
    ns = {"np": np, "List": typing.List, "Dict": typing.Dict, "Tuple": typing.Tuple, "list": list,
          "dict": dict, "tuple": tuple, "warnings": warnings, "RequestFuncOutput": RequestFuncOutput,
          "PreTrainedTokenizerBase": object, "BenchmarkMetrics": lambda **kw: SimpleNamespace(**kw),
          "MILLISECONDS_TO_SECONDS_CONVERSION": 1000, "str": str, "int": int, "float": float,
          "annotations": None}
    exec("from __future__ import annotations\n" + src, ns)
    return ns["calculate_metrics"]


CLIENTS = ["calculate_metrics_08d7a9cd.py", "calculate_metrics_96d6fb58.py"]


def _row(i, ttft_us, tpot_us, out, inp=100):
    return {"id": f"request_{i}", "fate": "completed", "arrival_us": 0, "ttft_us": ttft_us,
            "e2e_us": ttft_us + (tpot_us or 0) * (out - 1) + 777, "prompt_tokens": inp, "output_tokens": out,
            **({"tpot_us": tpot_us} if out > 1 else {})}


def _as_client_outputs(rows):
    """A Result row as the client's RequestFuncOutput: latency runs to the last content chunk."""
    outs = []
    for r in rows:
        tpot = r.get("tpot_us") or 0
        outs.append(RequestFuncOutput(success=True, output_tokens=r["output_tokens"], ttft=r["ttft_us"] / 1e6,
                                      latency=(r["ttft_us"] + tpot * (r["output_tokens"] - 1)) / 1e6,
                                      itl=[tpot / 1e6] * max(r["output_tokens"] - 1, 0)))
    return outs


def _client_means(name, rows, failed=()):
    outs = _as_client_outputs(rows)
    for i in failed:
        outs[i].success = False
    reqs = [("p", r["prompt_tokens"], r["output_tokens"]) for r in rows]
    fn = _calculate_metrics(name)
    args = [reqs, outs, 100.0, None] + ([["ttft"]] if "selected_percentile_metrics" in fn.__code__.co_varnames[:fn.__code__.co_argcount] else []) + [[99.0], {}]
    m, _ = fn(*args)
    return m.mean_ttft_ms, m.mean_tpot_ms


@pytest.mark.parametrize("client", CLIENTS)
def test_t3_summarize_is_the_clients_mean_ttft_and_mean_tpot(client):
    rows = [_row(0, 180_000, 9_000, 1024), _row(1, 250_000, 11_500, 700), _row(2, 90_000, 8_200, 33),
            _row(3, 400_000, 15_000, 2048)]
    ins = [r["prompt_tokens"] for r in rows]
    outs = [r["output_tokens"] for r in rows]
    s = ix.summarize(rows, ins, outs)
    ttft_ms, tpot_ms = _client_means(client, rows)
    assert s["mean_ttft_us"] / 1000 == pytest.approx(ttft_ms, rel=1e-9)
    assert s["mean_tpot_us"] / 1000 == pytest.approx(tpot_ms, rel=1e-9)


@pytest.mark.parametrize("client", CLIENTS)
def test_t3_a_one_token_request_counts_in_ttft_and_not_in_tpot(client):
    rows = [_row(0, 180_000, 9_000, 512), _row(1, 300_000, None, 1), _row(2, 120_000, 7_000, 64)]
    s = ix.summarize(rows, [100] * 3, [512, 1, 64])
    ttft_ms, tpot_ms = _client_means(client, rows)
    assert s["tpot_requests"] == 2
    assert s["mean_ttft_us"] / 1000 == pytest.approx(ttft_ms, rel=1e-9)
    assert s["mean_tpot_us"] / 1000 == pytest.approx(tpot_ms, rel=1e-9)


@pytest.mark.parametrize("client", CLIENTS)
def test_t3_a_failed_request_is_averaged_away_by_the_client_and_refused_here(client):
    """The client averages the survivors, so a run that lost its slowest request reports an easier
    point. The dashboard's simulated run must complete every request; summarize refuses otherwise,
    so a simulated point is never averaged over survivors."""
    rows = [_row(0, 180_000, 9_000, 512), _row(1, 900_000, 30_000, 512), _row(2, 120_000, 7_000, 512)]
    survivors, _ = _client_means(client, rows, failed=[1])
    everyone, _ = _client_means(client, rows)
    assert survivors != pytest.approx(everyone)
    lost = [dict(rows[0]), dict(rows[1], fate="dropped"), dict(rows[2])]
    with pytest.raises(ValueError):
        ix.summarize(lost, [100] * 3, [512] * 3)


def test_t3_a_request_whose_output_length_differs_from_the_target_is_refused():
    rows = [_row(0, 180_000, 9_000, 511), _row(1, 250_000, 9_500, 512)]
    with pytest.raises(ValueError):
        ix.summarize(rows, [100, 100], [512, 512])


def test_t3_the_pinned_sources_are_the_commits_the_audit_read():
    for name, commit in (("calculate_metrics_08d7a9cd.py", "08d7a9cd"), ("calculate_metrics_96d6fb58.py", "96d6fb58")):
        _, meta = _source(name)
        assert meta["commit"].startswith(commit) and meta["repo"] == "SemiAnalysisAI/InferenceX"


# ------------------------------------------------------------------ T4: the DB writer's unit mapping

def test_t4_the_db_row_is_the_clients_millisecond_mean_in_seconds_and_the_dashboard_reads_microseconds():
    src, _ = _source("writer_unit_mapping_96d6fb58.py")
    ns: dict = {}
    exec(src, ns)
    data = ns["apply_unit_mapping"]({"mean_ttft_ms": 123.4, "mean_tpot_ms": 5.6, "mean_itl_ms": 5.6,
                                     "output_throughput": 99.0}, {})
    assert data["mean_ttft"] == pytest.approx(0.1234) and data["mean_tpot"] == pytest.approx(0.0056)
    assert data["mean_itl"] == pytest.approx(0.0056)          # the DB's itl is the registry's tpot
    assert data["mean_intvty"] == pytest.approx(1000 / 5.6)   # 1 / mean(TPOT), not mean(1 / TPOT)
    assert "output_throughput" not in data
    import score as sc
    entry = {"row": {"metrics": {"mean_ttft": data["mean_ttft"], "mean_tpot": data["mean_tpot"]}}}
    m = sc.measured(entry)
    assert m["mean_ttft"] * 1e6 == pytest.approx(123_400) and m["mean_tpot"] * 1e6 == pytest.approx(5_600)


# ------------------------------------------------------------------ T1: the request pattern

def _closed_loop(n, conc, e2e=lambda i: 1_000_000 + 37_000 * (i % 7), overhead=777):
    free = [0] * conc
    rows = []
    for i in range(n):
        free.sort()
        a = free.pop(0)
        d = e2e(i)
        free.append(a + d + overhead)
        rows.append({"id": f"request_{i}", "fate": "completed", "arrival_us": a, "e2e_us": d})
    return rows


def test_t1_a_closed_loop_run_passes_and_reports_its_concurrency():
    out = ix.check_request_pattern(_closed_loop(80, 8), 80, 8)
    assert 0.9 * 8 <= out["achieved_concurrency"] <= 8


def test_t1_every_violation_is_refused():
    base = _closed_loop(40, 4)
    def fails(rows, conc=4):
        with pytest.raises(ValueError):
            ix.check_request_pattern(rows, 40, conc)
    fails([r for r in base if r["id"] != "request_7"])                                   # a request missing
    late = [dict(r) for r in base]; late[1]["arrival_us"] += 5_000                      # first conc not together
    fails(late)
    swapped = [dict(r) for r in base]
    swapped[10]["arrival_us"], swapped[11]["arrival_us"] = swapped[11]["arrival_us"] + 50_000, swapped[10]["arrival_us"]
    fails(swapped)                                                                       # order
    fails(base, conc=3)                                                                  # more in flight than conc
    fails(_closed_loop(40, 4, overhead=2_000_000))                                       # slots idle: mean below conc
    burst = [dict(r, arrival_us=0) for r in base]
    fails(burst)                                                                         # not a closed loop


def _two_lanes_freeing_together(first_overhead_us, tokens):
    """Two lanes finish 1 us apart. The lane that finished first hands its request over after a longer
    overhead, so the next record in order arrives after the one after it."""
    rows = [(0, 1_000), (0, 1_001), (1_000 + first_overhead_us, 100_000), (1_001 + 777, 100_000)]
    rows += [(101_778 + 777, 100_000), (1_000 + first_overhead_us + 100_000 + 777, 100_000)]
    return [{"id": f"request_{i}", "fate": "completed", "arrival_us": a, "e2e_us": e, "output_tokens": tokens}
            for i, (a, e) in enumerate(rows)]


def test_t1_the_slack_for_the_releases_overhead_grows_with_the_output_tokens():
    # 8.2 ms out of order: allowed for requests of 1024 output tokens (1 ms + 12 us x 1024 = 13.3 ms),
    # refused for requests of 100 tokens (2.2 ms).
    ix.check_request_pattern(_two_lanes_freeing_together(9_000, 1024), 6, 2)
    with pytest.raises(ValueError):
        ix.check_request_pattern(_two_lanes_freeing_together(9_000, 100), 6, 2)
    ix.check_request_pattern(_two_lanes_freeing_together(900, 100), 6, 2)       # 0.1 ms: within 2.2 ms
    assert (ix.ORDER_SLACK_BASE_US, ix.ORDER_SLACK_PER_TOKEN_US) == (1000, 12)


# ------------------------------------------------------------------ T9: the send gap text

def test_t9_the_send_gap_text_states_the_simulators_release_rule():
    d = next(x for x in ix.client_differences(True, "") if x["subject"] == "send_gap")["detail"]
    assert f"{ix.COMPLETION_OVERHEAD_US} us" in d and ix.COMPLETION_OVERHEAD_US == 777
    assert "completion plus the assumed completion overhead" in d and "not measured" in d
    assert "step that emitted" not in d and "last token" not in d


# ------------------------------------------------------------------ T10: client-bound

def test_t10_a_run_near_the_clients_chunk_ceiling_is_flagged():
    assert ix.chunk_rate(512, 20_000) == pytest.approx(25_600)
    assert ix.client_bound(512, 20_000) and not ix.client_bound(64, 20_000)
    ds = ix.client_differences(True, "", client_bound=True)
    assert "client_saturation" in [d["subject"] for d in ds]
    assert "client_saturation" not in [d["subject"] for d in ix.client_differences(True, "")]


# ------------------------------------------------------------------ T7: no Result aggregate on single-turn

def test_t7_ttft_and_tpot_aggregates_are_read_only_on_the_agentic_path():
    names = ("TTFT_MEAN_MS", "TPOT_MEAN_MS", "ttft_mean_ms", "tpot_mean_ms")
    uses = {}
    for path in sorted(HERE.glob("*.py")):
        # pointrecord.py names the metric ids of the figures it writes; it reads no aggregate.
        if path.name.startswith("test_") or path.name in ("result.py", "pointrecord.py"):
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            hit = (isinstance(node, ast.Attribute) and node.attr in names) or \
                  (isinstance(node, ast.Name) and node.id in names) or \
                  (isinstance(node, ast.Constant) and node.value in names)
            if hit:
                uses.setdefault(path.name, []).append(node.lineno)
    assert set(uses) == {"score.py"}, uses
    tree = ast.parse((HERE / "score.py").read_text())
    dispatch = None
    # score_point's dispatch: the prefill/decode path (score_pd) calls the single-turn scorer too.
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "score_point"]:
        for node in ast.walk(fn):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Call) and \
                    getattr(node.value.func, "id", "") == "score_single_turn":
                dispatch = (fn.name, node.lineno, fn.end_lineno)
    assert dispatch, "the single-turn dispatch moved; update this test"
    _, after, end = dispatch
    assert all(after < ln <= end for ln in uses["score.py"]), (dispatch, uses)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
