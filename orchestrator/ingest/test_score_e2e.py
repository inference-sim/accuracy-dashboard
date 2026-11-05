"""End-to-end: frozen points through score_point and write_contract, with fake `blisdefaults`
and `blis` executables standing in for BLIS (CI has no catalog or BLIS build). The fake blis
reads the trace it is given and prints a schema-version-2 Result on standard output, as
`blis replay --format json` does; `blis schema validate result` accepts it, or refuses it in
the invalid variant.

Checks: a single-turn point is scored with the client's means over the Result's request rows;
prefix caching off replays the main phase cold and on replays it primed; a Result with a
dropped request, or one that does not validate, is refused; an unverified point names the
sent-prompt-length difference; every single-turn point names the send gap and so is
approximate; the agentic path reads ttft_mean_ms and tpot_mean_ms and caches the Result; the
contract validates and a rescore is byte-identical.

Run: python3 orchestrator/ingest/test_score_e2e.py
"""
from __future__ import annotations

import csv
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
import inferencex_client as ix  # noqa: E402
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
    "INFO [kv_cache_utils.py:1] GPU KV cache size: 100,000 tokens\n"
    '"POST /v1/completions HTTP/1.1" 200\n')

FAKE_DEFAULTS = """#!/usr/bin/env python3
import json, sys
a = sys.argv[1:]
if "-resolve" in a:
    print(json.dumps({"assumptions": [], "cache_dtype": "auto", "caches": [], "dp": 1, "ep": 1, "overrides": [], "tp": 1}))
else:
    print(json.dumps({"device": "h200", "max_num_batched_tokens": 8192, "max_num_seqs": 1024, "memory_gib": 139.8}))
"""

# The fake blis. `schema validate result FILE` exits VALIDATE. `replay` records its argv and
# working directory beside itself, then prints a Result. For a single-turn trace (--trace-data)
# it writes one request row per trace record: a round-0 record is "request_<request_id>", a
# holder round "session_<session>_round_1_0"; each runs its prompt (prefix plus input tokens)
# and output tokens, with TTFT TTFT_US and TPOT TPOT_US, and arrives at its trace arrival
# time. With DROP set, the last main-phase request is dropped; with EARLY_HOLDER set, a holder
# round arrives at 0, inside the main phase; with SHORT set, main request 0 emits one token
# fewer than its target. An agentic replay gets the
# fixed metrics and reports below.
FAKE_BLIS = """#!/usr/bin/env python3
import csv, json, os, sys
VALIDATE, DROP, EARLY_HOLDER, SHORT, TTFT_US, TPOT_US = {validate}, {drop}, {early_holder}, {short}, 180000, 9000.0
a = sys.argv[1:]
here = os.path.dirname(os.path.abspath(__file__))
if a[:3] == ["schema", "validate", "result"]:
    json.load(open(a[3]))
    sys.exit(VALIDATE)
assert a[0] == "replay", a
with open(os.path.join(here, "blis_saw.json"), "a") as fh:
    fh.write(json.dumps({{"argv": a, "cwd": os.getcwd()}}) + "\\n")
def arg(k): return a[a.index(k) + 1]
counts = {{"generated": 0, "completed": 0, "timed_out": 0, "in_flight_at_horizon": 0,
          "queued_at_horizon": 0, "not_started": 0, "length_capped": 0}}
doc = {{"kind": "Result", "schema_version": 2, "name": "fake", "requests": counts,
       "metrics": {{"ttft_mean_ms": {{"value": 1500.0, "samples": 10}}, "tpot_mean_ms": {{"value": 4.5, "samples": 10}},
                   "itl_mean_ms": {{"value": 17.0, "samples": 10}}}},
       "reports": {{"engine": {{"cluster": {{"kv_capacity_tokens_per_replica": 100000}}}}, "kernel": {{"pool": "fake"}}}}}}
if "--trace-data" in a:
    recs = list(csv.DictReader(open(arg("--trace-data"))))
    main = [r for r in recs if r["session_id"].startswith("main-")]
    rows = []
    for r in recs:
        out = int(r["output_tokens"]) - (1 if SHORT and r is main[0] else 0)
        rid = (f"request_{{r['request_id']}}" if r["round_index"] == "0"
               else f"session_{{r['session_id']}}_round_1_0")
        arrival = int(r["arrival_time_us"])
        if r["round_index"] == "1":
            arrival = 0 if EARLY_HOLDER else int(r["think_time_us"])
        row = {{"id": rid, "fate": "completed", "arrival_us": arrival, "ttft_us": TTFT_US,
               "e2e_us": int(TTFT_US + TPOT_US * (out - 1)),
               "prompt_tokens": int(r["prefix_length"]) + int(r["input_tokens"]), "output_tokens": out}}
        if out > 1:
            row["tpot_us"] = TPOT_US
        if DROP and r is main[-1]:
            row = {{"id": rid, "fate": "dropped", "drop_reason": "unservable", "arrival_us": arrival,
                   "prompt_tokens": row["prompt_tokens"], "output_tokens": 0}}
        rows.append(row)
    counts["generated"] = len(rows)
    counts["completed"] = sum(r["fate"] == "completed" for r in rows)
    if DROP:
        counts["dropped"] = {{"unservable": 1}}
    doc["request_rows"] = rows
print(json.dumps(doc))
"""


def _exe(path: Path, body: str) -> str:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def _fake_blis(tmp: Path, *, validate: int = 0, drop: bool = False, early_holder: bool = False,
               short: bool = False) -> str:
    d = tmp / "sim"
    d.mkdir(exist_ok=True)
    (d / "blis_saw.json").unlink(missing_ok=True)
    return _exe(d / "blis", FAKE_BLIS.format(validate=validate, drop=drop, early_holder=early_holder,
                                                     short=short))


def _saw(env) -> list[dict]:
    p = Path(env.blis).parent / "blis_saw.json"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def _setup(tmp: Path, *, log: str = LOG, repo: str = "org/m", conc: int = 4, isl: int = 1024, osl: int = 1024,
           date: str = "2026-10-01", spec: str = "mtp", benchmark_type: str = "single_turn"):
    row = {"id": "1", "model": "m", "hardware": "h200", "precision": "fp8", "framework": "vllm",
           "benchmark_type": benchmark_type, "conc": conc, "isl": isl, "osl": osl, "spec_method": spec,
           "disagg": False, "is_multinode": False, "decode_tp": 1, "decode_ep": 1, "num_decode_gpu": 1,
           "date": date, "run_url": "https://github.com/o/r/actions/runs/1", "curve_workflow_run_id": "7",
           "image": "vllm/vllm-openai:v0.31.0", "metrics": {"mean_ttft": 0.2, "mean_tpot": 0.01}}
    ident = c.unit_identity(row, c.run_dates([row]))
    pid = c.point_id(ident)
    pdir = tmp / "pull" / "points" / pid
    pdir.mkdir(parents=True)
    log = log.replace("org/m", repo)
    (pdir / "server_log.gz").write_bytes(gzip.compress(log.encode(), mtime=0))
    entry = {"point_id": pid, "identity": ident, "row": row, "reasons": [], "records": ["1"],
             "measurements": [{"record": "1", "metrics": row["metrics"]}],
             "files": {"server_log": {"path": "server_log.gz", "sha256": "0" * 64, "from": "api:/server-log"}},
             "build": {"image": row["image"], "commit": "a" * 40, "source": "image_label", "ref": "v0.31.0",
                       "distance": 0, "match": "exact"}}
    env = sc.Env(blis=_fake_blis(tmp), blis_release="v0.12.0", blis_commit="b" * 40, catalog=tmp,
                 catalog_release="0.3.0", registry=tmp, registry_release="v0.2.0", kernel="v0.3.0",
                 defaults_helper=_exe(tmp / "blisdefaults", FAKE_DEFAULTS), corpus={"sha256": "c" * 64},
                 policy=st.load_policy()[0], vllm_defaults=st.load_vllm_defaults()[0])
    env.catalog_obj = sp.Catalog(root=tmp, models={"m": repo}, speculators={"m": "mtp"},
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


def _trace(work: Path, pid: str) -> list[dict]:
    return list(csv.DictReader((work / "single_turn" / pid / "trace.csv").open()))


def test_a_single_turn_point_is_scored_with_the_clients_means_and_rescores_identically():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        o, work = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        assert c.validate_dir(tmp / "c1") == []
        pts = list(csv.DictReader((tmp / "c1" / c.POINTS_CSV).open()))
        assert len(pts) == 1
        # The fake's rows: TTFT 180000 us and TPOT 9000 us on every request.
        assert float(pts[0]["pred_ttft_us"]) == 180000.0 and float(pts[0]["pred_tpot_us"]) == 9000.0
        assert float(pts[0]["meas_ttft_us"]) == 200000.0 and float(pts[0]["meas_tpot_us"]) == 10000.0
        # The trace holds the client's draws for (1024, 1024, 4), in order.
        ins, outs = ix.target_lengths(1024, 1024, 4)
        tr = _trace(work, entry["point_id"])
        assert [int(r["input_tokens"]) for r in tr] == ins and [int(r["output_tokens"]) for r in tr] == outs
        # The scenario carries the router block, its file beside it, and the drafter's acceptance.
        sdir = work / "single_turn" / entry["point_id"]
        scen = next(sdir.glob("p-*.yaml")).read_text()
        assert sc._parse_back(scen)["router"] == {"endpoint_picker_config": ix.ROUTER_CONFIG_NAME}
        assert (sdir / ix.ROUTER_CONFIG_NAME).read_bytes() == ix.router_config_bytes()
        assert "acceptance:" in scen and "acceptance_length: 2.4" in scen
        # blis ran in its own directory, with the harness's catalog and registry.
        saw = _saw(env)[0]
        assert Path(saw["cwd"]).resolve() == Path(env.blis).parent.resolve()
        assert saw["argv"][saw["argv"].index("--catalog") + 1] == str(env.catalog)
        assert "--format" in saw["argv"] and not any("metrics-path" in x for x in saw["argv"])
        _score(tmp, entry, env, tmp / "c2")
        for f in ("points.csv", "fidelity.jsonl", "facets.json", "not_scored.jsonl", "provenance.json"):
            assert (tmp / "c1" / f).read_bytes() == (tmp / "c2" / f).read_bytes(), f
    finally:
        shutil.rmtree(tmp)


def test_a_concurrency_no_fixture_holds_is_scored():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp, conc=3, isl=1000, osl=200)
        o, work = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        assert len(_trace(work, entry["point_id"])) == 30
    finally:
        shutil.rmtree(tmp)


def test_a_point_with_no_request_of_two_output_tokens_is_refused():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp, conc=1, osl=1)       # every output length is 0 or 1: no TPOT sample
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is None and o.reasons == ["blis_refused:metrics_incomplete"]
    finally:
        shutil.rmtree(tmp)


def test_a_request_that_ran_other_lengths_than_its_target_is_refused():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        env.blis = _fake_blis(tmp, short=True)
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is None and o.reasons == ["blis_refused:requests_not_the_points"]
    finally:
        shutil.rmtree(tmp)


def test_a_drafter_whose_acceptance_the_scenario_does_not_pin_is_not_replayed():
    tmp = Path(tempfile.mkdtemp())
    try:
        # Zero draft tokens: the scenario states a drafter but pins no acceptance for it.
        entry, env = _setup(tmp, log=LOG.replace("'num_speculative_tokens': 2", "'num_speculative_tokens': 0"))
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is None and o.reasons == ["client_scenario_not_replayable:single_turn_speculative"], o.reasons
        assert _saw(env) == []
    finally:
        shutil.rmtree(tmp)


def test_a_row_without_its_isl_is_refused_before_blis():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        entry["row"]["isl"] = None
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is None and o.reasons == ["required_setting_missing:replay.isl"]
        assert _saw(env) == []
    finally:
        shutil.rmtree(tmp)


def test_prefix_caching_off_replays_the_main_phase_cold():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        o, work = _score(tmp, entry, env, tmp / "c1")
        tr = _trace(work, entry["point_id"])
        assert all(r["session_id"].startswith("main-") for r in tr) and len(tr) == 40
        assert all(r["prefix_group"] == "" and r["arrival_time_us"] == "0" for r in tr)
        req = o.fidelity["requests"]
        assert (req["start"], req["copies"], req["count"]) == ("cold", 0, 40)
        assert req["client"] == ix.CLIENT_SUBJECT
    finally:
        shutil.rmtree(tmp)


def test_prefix_caching_on_replays_the_main_phase_primed():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp, log=LOG.replace("'enable_prefix_caching': False", "'enable_prefix_caching': True")
                            .replace("enable_prefix_caching=False", "enable_prefix_caching=True"))
        o, work = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        tr = _trace(work, entry["point_id"])
        warm = [r for r in tr if r["session_id"].startswith("warmup-")]
        assert len(warm) == 2 and len(tr) == 42           # dp 1: one copy and its holder round
        assert all(r["arrival_time_us"] == str(ix.PRIME_MAIN_START_US) for r in tr if r["session_id"].startswith("main-"))
        req = o.fidelity["requests"]
        assert (req["start"], req["copies"]) == ("primed", 1)
        pts = list(csv.DictReader((tmp / "c1" / c.POINTS_CSV).open()))
        assert float(pts[0]["pred_ttft_us"]) == 180000.0      # the warm-up rows are not in the mean
        assert c.validate_dir(tmp / "c1") == []
    finally:
        shutil.rmtree(tmp)


def test_a_primed_run_whose_warmup_was_not_drained_is_refused():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp, log=LOG.replace("'enable_prefix_caching': False", "'enable_prefix_caching': True")
                            .replace("enable_prefix_caching=False", "enable_prefix_caching=True"))
        env.blis = _fake_blis(tmp, early_holder=True)
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is None and o.reasons == ["blis_refused:warmup_not_drained"]
    finally:
        shutil.rmtree(tmp)


def test_a_result_with_a_dropped_request_is_refused():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        env.blis = _fake_blis(tmp, drop=True)
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is None and o.reasons == ["blis_refused:requests_incomplete"]
        assert c.validate_dir(tmp / "c1") == []
    finally:
        shutil.rmtree(tmp)


def test_a_result_that_does_not_validate_is_refused():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        env.blis = _fake_blis(tmp, validate=1)
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is None and o.reasons == ["blis_refused:result_invalid"]
        assert c.validate_dir(tmp / "c1") == []
    finally:
        shutil.rmtree(tmp)


def test_every_single_turn_point_names_the_send_gap_and_is_approximate():
    tmp = Path(tempfile.mkdtemp())
    try:
        # A point the prompt-length evidence verifies: gpt-oss-120b, 2026-02-25, 1024:8192, c=4.
        entry, env = _setup(tmp, repo="openai/gpt-oss-120b", isl=1024, osl=8192, date="2026-02-25")
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        assert [d["subject"] for d in o.fidelity["requests"]["differences"]] == ["send_gap"]
        assert o.fidelity["status"] == "approximate"
        assert c.validate_dir(tmp / "c1") == []
    finally:
        shutil.rmtree(tmp)


def test_an_unverified_point_names_the_sent_prompt_length_difference():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)          # org/m: the evidence holds no such point
        o, _ = _score(tmp, entry, env, tmp / "c1")
        diffs = o.fidelity["requests"]["differences"]
        assert [d["subject"] for d in diffs] == ["send_gap", "sent_prompt_lengths"]
        assert "not verified" in diffs[1]["detail"]
        assert o.fidelity["status"] == "approximate"
    finally:
        shutil.rmtree(tmp)


def test_the_fidelity_schema_requires_an_approximate_status_for_a_client_difference():
    import jsonschema
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        o, _ = _score(tmp, entry, env, tmp / "c1")
        v = jsonschema.Draft7Validator(json.loads(c.FIDELITY_SCHEMA.read_text()))
        assert v.is_valid(o.fidelity)
        assert not v.is_valid({**o.fidelity, "status": "exact"})
        assert not v.is_valid({**o.fidelity, "requests": {**o.fidelity["requests"], "extra": 1}})
        assert not v.is_valid({**o.fidelity, "requests": {**o.fidelity["requests"], "copies": 1}})  # cold
    finally:
        shutil.rmtree(tmp)


def _agentic(tmp: Path):
    sys.path.insert(0, str(HERE))
    from test_extract import _export
    entry, env = _setup(tmp, benchmark_type="agentic_traces", conc=8)
    pdir = tmp / "pull" / "points" / entry["point_id"]
    (pdir / "export.gz").write_bytes(gzip.compress(json.dumps(_export()).encode(), mtime=0))
    entry["files"]["client_export"] = {"path": "export.gz", "sha256": "0" * 64, "from": "artifact"}
    env.corpus = {"dataset": "semianalysisai/cc-traces-weka-062126", "revision": "rev", "sha256": "c" * 64,
                  "path": str(tmp / "traces.jsonl"), "file": "traces.jsonl"}
    return entry, env


def test_the_agentic_path_reads_the_registry_means_and_the_engine_report():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _agentic(tmp)
        o, work = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        assert c.validate_dir(tmp / "c1") == []
        pts = list(csv.DictReader((tmp / "c1" / c.POINTS_CSV).open()))
        # ttft_mean_ms 1500 and tpot_mean_ms 4.5 (not itl_mean_ms 17), in microseconds.
        assert float(pts[0]["pred_ttft_us"]) == 1500000.0 and float(pts[0]["pred_tpot_us"]) == 4500.0
        assert o.fidelity["resolved"][0]["blis"] == 100000 and o.fidelity["resolved"][0]["match"] == "exact"
        assert o.fidelity["blis_kernel_provenance"] == {"pool": "fake"}
        assert "requests" not in o.fidelity
        argv = _saw(env)[0]["argv"]
        assert "--agentic-scenario" in argv and "--format" in argv and not any("metrics-path" in x for x in argv)
        # The Result is cached for the same inputs: a rescore in the same work dir runs no blis.
        env.blis = _exe(Path(env.blis), "#!/bin/sh\nexit 99\n")
        o2 = sc.score_point(entry, tmp / "pull", work, env)
        assert o2.fidelity == o.fidelity and o2.csv_row == o.csv_row
        # A cached Result whose key differs is not reused.
        next((work / "results").glob("*.key")).write_text("other")
        o3 = sc.score_point(entry, tmp / "pull", work, env)
        assert o3.fidelity is None and o3.reasons[0].startswith("blis_refused")
    finally:
        shutil.rmtree(tmp)


def test_crosscheck_matches_the_contract_to_the_api_rows_and_catches_a_change():
    import crosscheck as xc
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        _score(tmp, entry, env, tmp / "c1")
        import ledger as ldg
        import ledger_fake
        lg = ldg.load(ledger_fake.write(tmp / "ledger", [entry["row"]]))
        n, problems = xc.check(tmp / "c1" / "points.csv", [entry["row"]], lg)
        assert (n, problems) == (2, [])
        changed = {**entry["row"], "metrics": {**entry["row"]["metrics"], "mean_tpot": 0.02}}
        n, problems = xc.check(tmp / "c1" / "points.csv", [changed], lg)
        assert len(problems) == 1 and "meas_tpot_us" in problems[0]
        assert xc.check(tmp / "c1" / "points.csv", [], lg)[1][0].endswith("not in the API rows given")
    finally:
        shutil.rmtree(tmp)


def test_a_point_refused_before_blis_never_calls_it():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        log = LOG.replace("'block_size': 16,", "'block_size': 16, 'prefill_schedule_interval': 4,")
        pdir = tmp / "pull" / "points" / entry["point_id"]
        (pdir / "server_log.gz").write_bytes(gzip.compress(log.encode(), mtime=0))
        env.blis = _exe(Path(env.blis), "#!/bin/sh\nexit 99\n")   # must not run
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
