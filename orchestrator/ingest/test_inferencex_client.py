"""Tests for inferencex_client.py: the client's draws, the sent-length evidence, the traces, and
reading the simulator's request rows back (COV-12). No network and no simulator; one test
compares the generator with numpy itself."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import inferencex_client as ix  # noqa: E402


# ------------------------------------------------------------------ the generator

# Values printed by numpy 2.5.4 (np.random.seed then np.random.randint, in the order listed),
# from inference-sim tools/harness/fixture_test.go. Several ranges, so the mask and the
# rejection run at different widths, and three seeds, including the largest 32-bit one.
NUMPY_VECTORS = [
    ("seed 0, 1k inputs", 0, [(819, 1025, 5)], [[991, 866, 936, 1011, 886]]),
    ("seed 0, 8k then 1k", 0, [(6553, 8193, 3), (819, 1025, 3)], [[7237, 7112, 7769], [886, 1014, 922]]),
    ("seed 0, size-0 draw first", 0, [(0, 200000, 0), (819, 1025, 5)], [[], [991, 866, 936, 1011, 886]]),
    ("seed 0, two values", 0, [(0, 2, 8)], [[0, 1, 1, 0, 1, 1, 1, 1]]),
    ("seed 0, vocab-sized", 0, [(0, 200000, 4)], [[199340, 43567, 173685, 117952]]),
    ("seed 0, a one-value range draws nothing", 0, [(5, 6, 3), (819, 1025, 2)], [[5, 5, 5], [991, 866]]),
    ("seed 3", 3, [(819, 1025, 4), (6553, 8193, 4)], [[925, 971, 950, 1003], [7521, 6809, 7342, 7574]]),
    ("seed 2^32-1", 4294967295, [(819, 1025, 3)], [[982, 853, 831]]),
]


@pytest.mark.parametrize("name,seed,calls,want", NUMPY_VECTORS, ids=[v[0] for v in NUMPY_VECTORS])
def test_the_generator_reproduces_numpys_legacy_randint(name, seed, calls, want):
    g = ix.MT19937(seed)
    for (low, high, n), w in zip(calls, want):
        assert g.randint(low, high, n) == w


def test_the_generator_agrees_with_numpy():
    import numpy as np  # CI installs it: a skipped test is not a passing one (X16)
    for seed in (0, 1, 7, 20261016):
        for isl, osl, conc in ((1024, 1024, 4), (8192, 1024, 64), (1000, 1, 3)):
            np.random.seed(seed)
            n = 10 * conc
            want = (np.random.randint(int(isl * 0.8), isl + 1, size=n).tolist(),
                    np.random.randint(int(osl * 0.8), osl + 1, size=n).tolist())
            assert ix.target_lengths(isl, osl, conc, seed=seed) == want


def test_the_committed_fixture_is_the_clients_draws():
    # Literals restated from the client and its launcher: --num-prompts $((CONC*10)) and
    # RANDOM_RANGE_RATIO 0.8.
    doc = json.loads(ix.WORKLOADS_SEED0.read_text())
    assert (doc["seed"], doc["range_ratio"], doc["requests_per_concurrency"], doc["prefix_len"]) == (0, 0.8, 10, 0)
    assert len(doc["points"]) == 29
    for p in doc["points"]:
        got = ix.target_lengths(p["isl"], p["osl"], p["concurrency"])
        assert got == (p["input_lens"], p["output_lens"]), (p["isl"], p["osl"], p["concurrency"])


def test_target_lengths_has_the_protocols_shape_at_any_point():
    ins, outs = ix.target_lengths(2048, 512, 3)
    assert len(ins) == len(outs) == 30
    assert all(int(2048 * 0.8) <= v <= 2048 for v in ins)
    assert all(int(512 * 0.8) <= v <= 512 for v in outs)
    with pytest.raises(ValueError):
        ix.target_lengths(1024, 1024, 0)


# ------------------------------------------------------------------ the sent-length evidence

def test_the_committed_evidence_loads_and_verifies_a_known_point():
    e = ix.PromptLengthEvidence.load(ix.PROMPT_LENGTHS)
    assert len(e.doc["points"]) == 360
    ok, why = e.verified("deepseek-ai/DeepSeek-V4-Pro", "2026-07-12", 1024, 1024, 1)
    assert ok and why == ""
    ok, why = e.verified("deepseek-ai/DeepSeek-V4-Pro", "2026-07-13", 1024, 1024, 1)
    assert not ok and "holds no evidence" in why
    ok, why = e.verified(None, "2026-07-12", 1024, 1024, 1)
    assert not ok


def _evidence(tmp_path, mutate):
    doc = json.loads(ix.PROMPT_LENGTHS.read_text())
    mutate(doc)
    p = tmp_path / "e.json"
    p.write_text(json.dumps(doc))
    return p


@pytest.mark.parametrize("name,mutate", [
    ("an unknown top-level key", lambda d: d.update(extra=1)),
    ("an unknown point key", lambda d: d["points"][0].update(extra=1)),
    ("an unknown revision key", lambda d: d["revisions"][0].update(extra=1)),
    ("an unknown per-revision evidence key", lambda d: d["points"][0]["evidence"][0].update(extra=1)),
    ("an unpinned revision", lambda d: d["revisions"][0].update(revision="main")),
    ("a file with no sha256", lambda d: d["revisions"][0]["files"].update({"tokenizer.json": "x"})),
    ("a point citing a revision the header does not pin",
     lambda d: d["points"][0]["evidence"][0].update(revision="f" * 40)),
    ("no generator", lambda d: d.update(generator="")),
])
def test_the_evidence_loader_refuses(tmp_path, name, mutate):
    with pytest.raises(ValueError):
        ix.PromptLengthEvidence.load(_evidence(tmp_path, mutate))


def test_a_mismatch_or_a_server_added_token_is_unverified(tmp_path):
    first = json.loads(ix.PROMPT_LENGTHS.read_text())["points"][0]
    key = (first["repo"], first["run_date"], first["isl"], first["osl"], first["concurrency"])

    def bump(d, field, value):
        for p in d["points"]:
            if (p["repo"], p["run_date"], p["isl"], p["osl"], p["concurrency"]) == key:
                p["evidence"][0][field] = value
    e = ix.PromptLengthEvidence.load(_evidence(tmp_path, lambda d: bump(d, "max_abs_mismatch", 3)))
    ok, why = e.verified(*key)
    assert not ok and "up to 3 tokens" in why
    e = ix.PromptLengthEvidence.load(_evidence(tmp_path, lambda d: bump(d, "server_added_tokens", [1])))
    ok, why = e.verified(*key)
    assert not ok and "adds 1 special token" in why


# ------------------------------------------------------------------ the traces

def _lengths(n=7):
    return [51 + i for i in range(n)], [60 + i for i in range(n)]


def test_the_main_phase_is_one_session_per_request_in_order():
    ins, outs = _lengths(8)
    run = ix.main_phase(ins, outs, 3)
    assert (run.sessions, run.pool) == (8, 3)
    for i, r in enumerate(run.records):
        assert (r["request_id"], r["session_id"], r["round_index"]) == (i, f"main-{i}", 0)
        assert (r["input_tokens"], r["output_tokens"]) == (ins[i], outs[i])
        assert (r["prefix_group"], r["prefix_length"], r["arrival_time_us"], r["deadline_us"]) == ("", 0, 0, 0)
        assert r["think_time_us"] is None and r["streaming"] is True


def test_the_primed_trace_caches_request_zeros_prompt_and_nothing_else():
    conc, n, copies = 3, 7, 2
    ins, outs = _lengths(n)
    run = ix.primed_phase(ins, outs, conc, copies)
    assert (run.pool, run.sessions) == (conc + copies, n + copies)
    warm, main = run.records[:2 * copies], run.records[2 * copies:]
    for j in range(copies):
        copy, holder = warm[2 * j], warm[2 * j + 1]
        # The copy is request 0's prompt (its prefix group, no further tokens) and output, at t=0.
        assert copy["session_id"] == holder["session_id"] == f"warmup-{j}"
        assert (copy["round_index"], copy["prefix_group"], copy["prefix_length"], copy["input_tokens"],
                copy["output_tokens"], copy["arrival_time_us"]) == (0, ix.PRIME_PREFIX_GROUP, ins[0], 0, outs[0], 0)
        # The holder keeps the slot until long after any main phase.
        assert (holder["round_index"], holder["input_tokens"], holder["output_tokens"],
                holder["think_time_us"]) == (1, 1, 1, ix.PRIME_HOLD_US)
        assert (copy["request_id"], holder["request_id"]) == (n + 2 * j, n + 2 * j + 1)
    # Main request 0 is the copies' prompt token for token; no other main request shares it.
    assert (main[0]["prefix_group"], main[0]["prefix_length"], main[0]["input_tokens"]) == \
        (ix.PRIME_PREFIX_GROUP, ins[0], 0)
    for i, r in enumerate(main):
        assert (r["request_id"], r["session_id"], r["arrival_time_us"]) == (i, f"main-{i}", ix.PRIME_MAIN_START_US)
        if i:
            assert (r["prefix_group"], r["prefix_length"], r["input_tokens"]) == ("", 0, ins[i])
    assert ix.PRIME_MAIN_START_US < ix.PRIME_HOLD_US


def test_write_trace_writes_the_substrate_trace_format(tmp_path):
    ins, outs = _lengths(3)
    h, d = ix.write_trace(ix.main_phase(ins, outs, 2), tmp_path / "a")
    assert h.read_text() == "trace_version: 4\ntime_unit: microseconds\nmode: generated\n"
    rows = list(csv.reader(d.open()))
    assert rows[0] == ix.TRACE_COLUMNS            # no optional column when no record uses one
    assert rows[1][:11] == ["0", ix.CLIENT_ID, "", "", "main-0", "0", "", "0", "true", "51", "60"]
    assert rows[1][15] == "0" and rows[1][-1] == "ok"
    h, d = ix.write_trace(ix.primed_phase(ins, outs, 2, 1), tmp_path / "b")
    rows = list(csv.reader(d.open()))
    assert rows[0] == ix.TRACE_COLUMNS + ["think_time_us"]
    assert rows[1][-1] == "" and rows[2][-1] == str(ix.PRIME_HOLD_US)


def test_the_replay_command_is_a_users_blis_replay():
    argv = ix.replay_argv("/b/blis", "s.yaml", "/d", "/d/trace.yaml", "/d/trace.csv", 12, 5, 42)
    assert argv == ["/b/blis", "replay", "--scenario", "s.yaml", "--scenarios", "/d",
                    "--trace-header", "/d/trace.yaml", "--trace-data", "/d/trace.csv",
                    "--session-mode", "closed-loop", "--concurrent-sessions", "5", "--total-sessions", "12",
                    "--seed", "42", "--format", "json", "--log", "error"]
    assert not any("metrics-path" in a or "results-path" in a for a in argv)


def test_the_router_config_places_by_requests_in_flight():
    text = ix.router_config_bytes().decode()
    assert "active-request-scorer" in text and "kind: EndpointPickerConfig" in text


# ------------------------------------------------------------------ reading the rows back

T = ix.PRIME_MAIN_START_US


def _primed_rows():
    return [
        {"id": "request_2", "fate": "completed", "arrival_us": 0, "e2e_us": 5_000_000},             # the copy
        {"id": "request_0", "fate": "completed", "arrival_us": T, "e2e_us": 3_000_000},             # main 0
        {"id": "request_1", "fate": "completed", "arrival_us": T, "e2e_us": 4_000_000},             # main 1
        {"id": "session_warmup-0_round_1_1", "fate": "completed", "arrival_us": T + 3_600_000_000, "e2e_us": 1},
    ]


def test_check_primed_accepts_a_drained_warmup():
    ix.check_primed(_primed_rows(), 2)


@pytest.mark.parametrize("name,mutate", [
    ("a copy still running at the main-phase start", lambda r: r[0].update(e2e_us=T + 1)),
    ("main request 0 starting late", lambda r: r[1].update(arrival_us=T + 1_000_000)),
    ("a holder round inside the main phase", lambda r: r[3].update(arrival_us=T + 2_000_000)),
])
def test_check_primed_refuses_an_undrained_warmup(name, mutate):
    rows = [dict(r) for r in _primed_rows()]
    mutate(rows)
    with pytest.raises(ValueError):
        ix.check_primed(rows, 2)


def _rows(ins, outs):
    return [{"id": f"request_{i}", "fate": "completed", "arrival_us": 0, "ttft_us": 1000 * (i + 1),
             "tpot_us": 10.0 * (i + 1), "e2e_us": 5000, "prompt_tokens": ins[i], "output_tokens": outs[i],
             "completion_index": i + 1} for i in range(len(ins))]


def test_summarize_is_the_clients_metric_over_the_main_phase():
    ins, outs = [5, 6, 7], [4, 1, 3]
    s = ix.summarize(_rows(ins, outs), ins, outs)
    assert s["completed"] == 3 and s["tpot_requests"] == 2      # the one-token request has no TPOT
    assert s["mean_ttft_us"] == 2000 and s["mean_tpot_us"] == 20.0 and s["first_ttft_us"] == 1000


def test_summarize_ignores_the_warmup_rows_of_a_primed_run():
    ins, outs = [5, 6], [4, 4]
    rows = _rows(ins, outs) + [{"id": "request_2", "fate": "completed", "arrival_us": 0, "ttft_us": 9,
                                "tpot_us": 9.0, "prompt_tokens": 5, "output_tokens": 4},
                               {"id": "session_warmup-0_round_1_3", "fate": "in_flight_at_horizon", "arrival_us": 1}]
    with pytest.raises(ValueError):
        ix.summarize(rows, ins, outs)
    assert ix.summarize(rows, ins, outs, ignore=ix.main_phase_only(2))["completed"] == 2


@pytest.mark.parametrize("name,mutate", [
    ("a request at another prompt length", lambda r: r[0].update(prompt_tokens=99)),
    ("a request at another output length", lambda r: r[1].update(output_tokens=99)),
    ("a missing completion", lambda r: r[2].update(fate="in_flight_at_horizon")),
    ("a duplicate completion", lambda r: r.append(dict(r[0]))),
    ("a request that is not the point's", lambda r: r[2].update(id="request_9")),
])
def test_summarize_refuses_a_run_that_is_not_the_points_requests(name, mutate):
    ins, outs = [5, 6, 7], [4, 4, 4]
    rows = _rows(ins, outs)
    mutate(rows)
    with pytest.raises(ValueError):
        ix.summarize(rows, ins, outs)


# ------------------------------------------------------------------ differences

def test_every_point_names_the_send_gap_and_an_unverified_length():
    assert [d["subject"] for d in ix.client_differences(True, "")] == ["send_gap"]
    d = ix.client_differences(False, "no evidence")
    assert [x["subject"] for x in d] == ["send_gap", "sent_prompt_lengths"]
    assert "no evidence" in d[1]["detail"]
