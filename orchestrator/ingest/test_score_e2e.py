"""End-to-end: frozen points through score_point and write_contract, with a fake `blis`
executable standing in for BLIS (CI has no catalog or BLIS build), and a small fields.json
fixture (testdata/fields) standing in for the engine's field list. The fake blis
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
import dataclasses
import gzip
import json
import shutil
import stat
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import assess as asx  # noqa: E402
import contract as c  # noqa: E402
import inferencex_client as ix  # noqa: E402
import inferencex_runners as ir  # noqa: E402
import score as sc  # noqa: E402
import fields as fl  # noqa: E402
import settings as st  # noqa: E402
import support as sp  # noqa: E402

FIELDS = fl.parse((HERE / "testdata" / "fields" / "fields.json").read_bytes())

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
METHODS = {methods}
WP = {wp}
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
if WP is not None:
    doc["input"] = {{"workload_properties": WP}}
if METHODS is not None:
    doc["selected_entries"] = {{"coefficients": [
        {{"set": "cost-model-attention", "name": "n%d" % i, "method": m, "scope": {{}}, "file": "f.yaml"}}
        for i, m in enumerate(METHODS)]}}
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
               short: bool = False, methods=("measured",), workload_properties=None) -> str:
    d = tmp / "sim"
    d.mkdir(exist_ok=True)
    (d / "blis_saw.json").unlink(missing_ok=True)
    return _exe(d / "blis", FAKE_BLIS.format(validate=validate, drop=drop, early_holder=early_holder,
                                                     short=short, methods=repr(methods),
                                                     wp=repr(workload_properties)))


# A blis that answers only `catalog resolve --catalog DIR --model|--chip NAME --json`: a model
# is the entry MODELS gives its source repository (compared without regard to case), a chip is
# itself when CHIPS holds it, and anything else is null. The scorer asks the blis it scores
# with; the tests give the catalog its own fake so a replay fake can be swapped alone.
CATALOG_BLIS = """#!/usr/bin/env python3
import json, sys
MODELS, CHIPS = {models!r}, {chips!r}
a = sys.argv[1:]
assert a[:3] == ["catalog", "resolve", "--catalog"] and a[-1] == "--json", a
kind, q = a[4], a[5]
ident = MODELS.get(q.lower()) if kind == "--model" else (q if q in CHIPS else None)
out = {{"query": q, "identity": ident, "reason": "fake"}}
if kind == "--chip" and ident is not None:
    gpn, gpr = CHIPS[q]
    out["packaging"] = {{"gpus_per_node": gpn, "gpus_per_rack": gpr}}
print(json.dumps(out))
"""


def _catalog(tmp: Path, models: dict, chips: dict, speculators: dict) -> sp.Catalog:
    """A catalog at tmp/catalog: identities from a fake `blis catalog resolve`, and each model's
    graph.yaml naming its speculator."""
    root = tmp / "catalog"
    for name, method in speculators.items():
        (root / "models" / name).mkdir(parents=True, exist_ok=True)
        (root / "models" / name / "graph.yaml").write_text(f"speculator:\n  method: {method}\n")
    root.mkdir(parents=True, exist_ok=True)
    blis = _exe(tmp / "catalog-blis", CATALOG_BLIS.format(models={k.lower(): v for k, v in models.items()},
                                                          chips=dict(chips)))
    return sp.Catalog(blis=blis, root=root)


def _saw(env) -> list[dict]:
    p = Path(env.blis).parent / "blis_saw.json"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def job_log_text(isl: int, osl: int, conc: int, extra: str = "") -> str:
    """The CI job log line of a run whose client was given the launcher's defaults."""
    return (f"2026-10-01T02:42:03.2Z + python3 /workspace/utils/bench_serving/benchmark_serving.py --model m "
            f"--backend vllm --dataset-name random --random-input-len {isl} --random-output-len {osl} "
            f"--random-range-ratio 0.8 --num-prompts {10 * conc} --max-concurrency {conc} --request-rate inf "
            f"--ignore-eos --save-result --num-warmups {2 * conc} --result-filename x.json{extra}\n")


def _setup(tmp: Path, *, log: str = LOG, job_log: str | None = "default", client_commit: bool = True, repo: str = "org/m", conc: int = 4, isl: int = 1024, osl: int = 1024,
           date: str = "2026-10-01", spec: str = "mtp", benchmark_type: str = "single_turn",
           hardware: str = "mi355x", chips: dict | None = None, node_size: int | None = None):
    row = {"id": "1", "model": "m", "hardware": hardware, "precision": "fp8", "framework": "vllm",
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
             "client_commit": {"repo": "SemiAnalysisAI/InferenceX", "sha": "f" * 40, "date": "2026-10-01T00:00:00Z"}
             if client_commit else None,
             "measurements": [{"record": "1", "metrics": row["metrics"]}],
             "files": {"server_log": {"path": "server_log.gz", "sha256": "0" * 64, "from": "api:/server-log"}},
             "build": {"image": row["image"], "commit": "a" * 40, "source": "image_label", "ref": "v0.31.0",
                       "distance": 0, "match": "exact"}}
    # The launch configuration states the node when asked: resources.gpus_per_node.
    if node_size is not None:
        lc = {"roles": {"agg": {"args": {}}}, "resources": {"gpu_type": hardware, "gpus_per_node": node_size}}
        (pdir / "launch_config.gz").write_bytes(gzip.compress(json.dumps(lc).encode(), mtime=0))
        entry["files"]["launch_config"] = {"path": "launch_config.gz", "sha256": "0" * 64, "from": "artifact"}
    if job_log == "default":
        job_log = job_log_text(isl, osl, conc)
    if job_log is not None:
        (pdir / "job_log.gz").write_bytes(gzip.compress(job_log.encode(), mtime=0))
        entry["files"]["job_log"] = {"path": "job_log.gz", "sha256": "0" * 64, "from": "t"}
        entry["client_args"] = {"job_id": 5, "job_name": "j"}
    else:
        entry["client_args"] = None
    env = sc.Env(blis=_fake_blis(tmp), blis_release="v0.12.0", blis_commit="b" * 40, catalog=tmp,
                 catalog_release="0.3.0", registry=tmp, registry_release="v0.2.0", kernel="v0.3.0",
                 corpora={}, field_list=FIELDS, vllm_defaults=st.load_vllm_defaults()[0],
                 engine_release="0.31.0", sim_build="v0.12.0")
    env.catalog_obj = _catalog(tmp, {repo: "m"}, chips or {hardware: (None, None)}, {"m": "mtp"})
    env.parts = set(chips or {hardware})
    return entry, env


def _score(tmp: Path, entry, env, out: Path):
    work = tmp / ("work-" + out.name)
    o = sc._score_one(entry, tmp / "pull", work, env)
    prov = {"ingest": "api", "blis": {"release": "v0.12.0", "commit_sha": "b" * 40, "catalog": "0.3.0",
                                      "registry": "v0.2.0", "extractor_version": "blis-latency-kernel@v0.3.0"},
            "simulator": env.simulator(), "harness_digest": env.harness_digest, "experimental": False, "units": None,
            "engine": {"kind": "vllm", "version": "0.31.0"}, "left_out_records": 0,
            "vllm_ref": "v0.31.0", "vllm_max_distance": 2000, "fields_sha256": "d" * 64,
            "pulled_at": "2026-10-23T00:00:00Z", "corpora": [], "pull_manifest_sha256": "e" * 64,
            "source": {"name": "test", "url": "https://example.invalid/"}}
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
        assert o.fidelity is None and o.faults == ["blis_refused:metrics_incomplete"]
    finally:
        shutil.rmtree(tmp)


def test_a_request_that_ran_other_lengths_than_its_target_is_refused():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        env.blis = _fake_blis(tmp, short=True)
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is None and o.faults == ["blis_refused:requests_not_the_points"]
    finally:
        shutil.rmtree(tmp)


def test_a_drafter_with_no_recorded_acceptance_is_replayed_with_the_profile_and_names_it():
    # D8: the dashboard pins no acceptance the run did not record; blis resolves it from the
    # substrate's profile, and the point names the profile as an estimate.
    tmp = Path(tempfile.mkdtemp())
    try:
        log = LOG.replace(", 'synthetic_acceptance_length': 2.4", "")
        entry, env = _setup(tmp, log=log)
        env.blis = _fake_blis(tmp, workload_properties=[
            {"name": "speculative_acceptance", "values": {"acceptance_length": 3.1}, "source": "profile",
             "profile": "mtp/deepseek"}])
        o, work = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        scen = next((work / "single_turn" / entry["point_id"]).glob("p-*.yaml")).read_text()
        assert "acceptance" not in scen.replace("rejection_sample_method", "")
        sub = next(s for s in o.fidelity["substitutions"] if s["subject"] == "speculative_config.acceptance_length")
        assert sub == {"kind": "estimated", "subject": "speculative_config.acceptance_length",
                       "detail": "profile mtp/deepseek from the registry"}
        env.blis = _fake_blis(tmp)
        o, _ = _score(tmp, entry, env, tmp / "c2")
        assert [s["detail"] for s in o.fidelity["substitutions"]
                if s["subject"] == "speculative_config.acceptance_length"] == ["profile not reported"]
        # A recorded acceptance is passed, pinned, and names no substitution.
        tmp2 = Path(tempfile.mkdtemp())
        try:
            entry, env = _setup(tmp2)
            o, _ = _score(tmp2, entry, env, tmp2 / "c3")
            assert not [s for s in o.fidelity["substitutions"] if s["subject"].endswith("acceptance_length")]
        finally:
            shutil.rmtree(tmp2)
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
        assert o.fidelity is None and o.faults == ["blis_refused:warmup_not_drained"]
    finally:
        shutil.rmtree(tmp)


def test_a_result_with_a_dropped_request_is_refused():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        env.blis = _fake_blis(tmp, drop=True)
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is None and o.faults == ["blis_refused:requests_incomplete"]
        assert c.validate_dir(tmp / "c1") == []
    finally:
        shutil.rmtree(tmp)


def test_a_result_that_does_not_validate_is_refused():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        env.blis = _fake_blis(tmp, validate=1)
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is None and o.faults == ["blis_refused:result_invalid"]
        assert c.validate_dir(tmp / "c1") == []
    finally:
        shutil.rmtree(tmp)


def test_every_single_turn_point_names_the_send_gap_and_is_g2():
    tmp = Path(tempfile.mkdtemp())
    try:
        # A point the prompt-length evidence verifies: gpt-oss-120b, 2026-02-25, 1024:8192, c=4.
        entry, env = _setup(tmp, repo="openai/gpt-oss-120b", isl=1024, osl=8192, date="2026-02-25")
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        assert [d["subject"] for d in o.fidelity["requests"]["differences"]] == ["send_gap"]
        assert o.fidelity["grade"] == "G2"
        assert [s["subject"] for s in o.fidelity["substitutions"] if s["kind"] == "client_difference"] == ["send_gap"]
        # model and served_model_name are inert, unproven in the field list: named, as interim.
        assert {s["subject"] for s in o.fidelity["substitutions"] if s["kind"] == "interim_status"} == \
            {"model", "served_model_name"}
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
        assert o.fidelity["grade"] == "G2"
    finally:
        shutil.rmtree(tmp)


def test_the_fidelity_schema_refuses_g1_for_a_point_naming_a_client_difference():
    import jsonschema
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        o, _ = _score(tmp, entry, env, tmp / "c1")
        v = jsonschema.Draft7Validator(json.loads(c.FIDELITY_SCHEMA.read_text()))
        assert v.is_valid(o.fidelity)
        assert not v.is_valid({**o.fidelity, "grade": "G1", "substitutions": []})
        assert not v.is_valid({**o.fidelity, "requests": {**o.fidelity["requests"], "extra": 1}})
        assert not v.is_valid({**o.fidelity, "requests": {**o.fidelity["requests"], "copies": 1}})  # cold
    finally:
        shutil.rmtree(tmp)


def test_a_point_behind_a_router_blis_does_not_host_is_g5_and_never_simulated():
    # Design §11.4, X4: BLIS hosts only llm-d's router (inference-sim #2028).
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        entry["row"]["metrics"]["router_name"] = "vllm-router"
        env.blis = _exe(Path(env.blis), "#!/bin/sh\nexit 99\n")   # must not run
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is None and o.g5 == {"code": "router_unsupported", "subject": "vllm-router"}
        ns = json.loads((tmp / "c1" / c.NOT_SCORED_JSONL).read_text())
        assert ns["grade"] == "G5" and ns["g5_reasons"] == [o.g5]
        assert c.validate_dir(tmp / "c1") == []
    finally:
        shutil.rmtree(tmp)


def test_a_point_blis_refuses_is_listed_as_failed_not_graded():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        env.blis = _fake_blis(tmp, validate=1)
        _score(tmp, entry, env, tmp / "c1")
        failed = json.loads((tmp / "c1" / c.FAILED_JSONL).read_text())
        assert failed["faults"] == ["blis_refused:result_invalid"] and "grade" not in failed
        assert (tmp / "c1" / c.NOT_SCORED_JSONL).read_text() == ""
        assert json.loads((tmp / "c1" / c.PROVENANCE_JSON).read_text())["points"] == 1
    finally:
        shutil.rmtree(tmp)


def _agentic(tmp: Path):
    sys.path.insert(0, str(HERE))
    from test_extract import _export
    entry, env = _setup(tmp, benchmark_type="agentic_traces", conc=8)
    pdir = tmp / "pull" / "points" / entry["point_id"]
    (pdir / "export.gz").write_bytes(gzip.compress(json.dumps(_export()).encode(), mtime=0))
    entry["files"]["client_export"] = {"path": "export.gz", "sha256": "0" * 64, "from": "artifact"}
    env.corpora = {
        UNCAPPED: {"workload": "agentx-mvp-uncapped", "repo": "semianalysisai/cc-traces-weka-062126",
                   "revision": "23f152f6f0f9399a85901b89a6458def0ef16729", "file": "traces.jsonl",
                   "split": "train", "sha256": "c" * 64, "path": str(tmp / "uncapped" / "traces.jsonl")},
        CAPPED: {"workload": "agentx-mvp", "repo": "semianalysisai/cc-traces-weka-062126-256k",
                 "revision": "8fecd2fc56694469f758f0afbbb6335ad3043740", "file": "traces.jsonl",
                 "split": "train", "sha256": "d" * 64, "path": str(tmp / "capped" / "traces.jsonl")}}
    return entry, env


UNCAPPED = "semianalysis_cc_traces_weka_062126"
CAPPED = "semianalysis_cc_traces_weka_062126_256k"


def _set_alias(tmp: Path, entry, alias: str, repo: str | None):
    """Rewrite the point's client export so its run loaded `alias` (and recorded `repo`)."""
    from test_extract import _export
    doc = _export()
    doc["input_config"]["datasets"][0]["dataset"] = alias
    doc["metadata"]["dataset"]["loader"] = alias
    if repo is None:
        del doc["metadata"]["dataset"]["hf_dataset_name"]
    else:
        doc["metadata"]["dataset"]["hf_dataset_name"] = repo
    pdir = tmp / "pull" / "points" / entry["point_id"]
    (pdir / "export.gz").write_bytes(gzip.compress(json.dumps(doc).encode(), mtime=0))


def test_each_agentic_point_replays_the_corpus_its_own_run_loaded():
    # COV-12, D3: the alias the run's client recorded picks the catalog entry, and blis is given
    # that entry's revision, full sha256 and file, never one corpus for the whole night.
    import yaml
    for alias, repo, rev, sha, sub in (
            (UNCAPPED, "semianalysisai/cc-traces-weka-062126", "23f152f6f0f9399a85901b89a6458def0ef16729",
             "c" * 64, "uncapped"),
            (CAPPED, "semianalysisai/cc-traces-weka-062126-256k", "8fecd2fc56694469f758f0afbbb6335ad3043740",
             "d" * 64, "capped")):
        tmp = Path(tempfile.mkdtemp())
        try:
            entry, env = _agentic(tmp)
            _set_alias(tmp, entry, alias, repo)
            o, _ = _score(tmp, entry, env, tmp / "c1")
            assert o.fidelity is not None, o.reasons
            argv = _saw(env)[0]["argv"]
            assert argv[argv.index("--corpus-sha256") + 1] == sha
            assert argv[argv.index("--corpus") + 1] == str(tmp / sub / "traces.jsonl")
            spec = yaml.safe_load(Path(argv[argv.index("--workload-spec") + 1]).read_text())["replay"]["corpus"]
            assert spec["loader"] == alias and spec["sha256"] == sha
            assert spec["source"] == {"huggingface": repo, "revision": rev, "file": "traces.jsonl", "split": "train"}
            assert o.fidelity["replay"]["corpus"] == alias and o.fidelity["replay"]["corpus_sha256"] == sha
        finally:
            shutil.rmtree(tmp)


def test_an_agentic_point_whose_corpus_is_not_date_pinned_is_g5_value_not_recorded():
    for alias, repo, want in (
            ("semianalysis_cc_traces_weka_with_subagents", "semianalysisai/cc-traces-weka-062126",
             "value_not_recorded:replay.corpus=semianalysis_cc_traces_weka_with_subagents"),
            # The recorded repository is not the one the alias loads: two records of the run disagree.
            (UNCAPPED, "semianalysisai/cc-traces-weka-062126-256k", "conflict:replay.corpus_repo")):
        tmp = Path(tempfile.mkdtemp())
        try:
            entry, env = _agentic(tmp)
            _set_alias(tmp, entry, alias, repo)
            o, _ = _score(tmp, entry, env, tmp / "c1")
            assert o.fidelity is None and want in o.reasons, o.reasons
            assert _saw(env) == []
            assert c.validate_dir(tmp / "c1") == []
            ns = [json.loads(x) for x in (tmp / "c1" / c.NOT_SCORED_JSONL).read_text().splitlines()]
            code = want.partition(":")[0].replace("conflict", "value_conflict")
            assert ns[0]["grade"] == "G5" and {"code": code, "subject": want.partition(":")[2]} in ns[0]["g5_reasons"], ns[0]
        finally:
            shutil.rmtree(tmp)
    # No alias at all: from_export names it, and it is value_not_recorded too.
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _agentic(tmp)
        from test_extract import _export
        doc = _export()
        del doc["input_config"]["datasets"][0]["dataset"]
        del doc["metadata"]["dataset"]["loader"]
        (tmp / "pull" / "points" / entry["point_id"] / "export.gz").write_bytes(
            gzip.compress(json.dumps(doc).encode(), mtime=0))
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert "required_setting_missing:replay.corpus" in o.reasons and _saw(env) == []
    finally:
        shutil.rmtree(tmp)


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
        o2 = sc._score_one(entry, tmp / "pull", work, env)
        assert o2.fidelity == o.fidelity and o2.csv_row == o.csv_row
        # A cached Result whose key differs is not reused.
        next((work / "results").glob("*.key")).write_text("other")
        o3 = sc._score_one(entry, tmp / "pull", work, env)
        assert o3.fidelity is None and o3.faults[0].startswith("blis_refused")
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


def _with_log(tmp, entry, log):
    pdir = tmp / "pull" / "points" / entry["point_id"]
    (pdir / "server_log.gz").write_bytes(gzip.compress(log.encode(), mtime=0))


def test_the_scenario_engine_block_holds_the_runs_values_under_the_engines_own_names():
    # COV-3: every recorded value is copied verbatim; engine.version is stack.json's release.
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        o, work = _score(tmp, entry, env, tmp / "c1")
        scen_text = next((work / "single_turn" / entry["point_id"]).glob("p-*.yaml")).read_text()
        import yaml
        docs = list(yaml.safe_load_all(scen_text))
        scen, dep = docs[0], docs[1]
        assert scen["engine_version"] == "0.31.0"
        eng = dep["pools"][0]["engine"]
        assert {k: eng[k] for k in ("max_num_seqs", "max_num_batched_tokens", "block_size", "max_model_len",
                                    "enable_prefix_caching", "quantization", "cache_dtype")} == \
            {"max_num_seqs": 16, "max_num_batched_tokens": 8192, "block_size": 16, "max_model_len": 2304,
             "enable_prefix_caching": False, "quantization": "fp8", "cache_dtype": "auto"}
        assert eng["gpu_memory_utilization"] == 0.9 and eng["speculative"] == {
            "method": "mtp", "num_spec_tokens": 2, "rejection_sample_method": "synthetic"}
        assert dep["pools"][0]["parallel"] == {"tp": 1, "pp": 1, "dp": 1, "enable_expert_parallel": False}
        assert o.fidelity["run_release"] == "0.31.0"
        # Every point records the simulator build and engine release that scored it (COV-6).
        assert o.fidelity["simulator"] == {"build": "v0.12.0", "engine": {"kind": "vllm", "version": "0.31.0"},
                                           "harness_digest": "unreleased"}
    finally:
        shutil.rmtree(tmp)


REFUSAL = ('time=t level=fatal msg="kernelmodel: deployment states no max_num_seqs"\n')


def _refusing_blis(tmp, stderr):
    body = ("#!/usr/bin/env python3\nimport sys\nif sys.argv[1:4] == ['schema', 'validate', 'result']:\n"
            "    sys.exit(0)\nsys.stderr.write(%r)\nsys.exit(1)\n" % stderr)
    return _exe(Path(_fake_blis(tmp)), body)


def test_an_unrecorded_setting_is_left_unset_and_the_engines_refusal_is_value_not_recorded():
    # The dashboard states no required-settings list: max_num_seqs is left out of the scenario
    # (X19). If blis refuses for want of it, the point is G5 value_not_recorded naming the field
    # parsed from the refusal; one blis resolves is scored.
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        _with_log(tmp, entry, LOG.replace("'max_num_seqs': 16, ", ""))
        o, work = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity["grade"] == "G2" and o.fidelity["substitutions"] == [
            s for s in o.fidelity["substitutions"] if s["kind"] != "estimated"]
        scen_text = next((work / "single_turn" / entry["point_id"]).glob("p-*.yaml")).read_text()
        assert "max_num_seqs" not in scen_text
        env.blis = _refusing_blis(tmp, REFUSAL)
        o, _ = _score(tmp, entry, env, tmp / "c2")
        assert o.g5 == {"code": "value_not_recorded", "subject": "max_num_seqs"}
        env.blis = _refusing_blis(tmp, 'level=fatal msg="deployment states no  "\n')
        o, _ = _score(tmp, entry, env, tmp / "c3")
        assert o.g5["code"] == "value_not_recorded"
        env.blis = _refusing_blis(tmp, 'level=fatal msg="something else broke"\n')
        o, _ = _score(tmp, entry, env, tmp / "c4")
        assert o.fidelity is None and o.faults[0].startswith("blis_refused:")
    finally:
        shutil.rmtree(tmp)


def test_a_field_the_release_lacks_or_the_engine_does_not_model_is_g5():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        _with_log(tmp, entry, LOG.replace("'block_size': 16,", "'block_size': 16, 'monokernel': True,"))
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert o.g5 == {"code": "field_not_in_release", "subject": "monokernel"}
        # The log's release is not the one the defaults table was read at, so only the launch
        # config can state a field inside a config object.
        pdir = tmp / "pull" / "points" / entry["point_id"]
        lc = {"roles": {"agg": {"args": {"compilation-config": '{"custom_ops": ["+rms_norm"]}'}}}, "resources": {"gpus_per_node": 8}}
        (pdir / "launch_config.gz").write_bytes(gzip.compress(json.dumps(lc).encode(), mtime=0))
        entry["files"]["launch_config"] = {"path": "launch_config.gz", "sha256": "0" * 64, "from": "artifact"}
        o, _ = _score(tmp, entry, env, tmp / "c2")
        assert o.g5 == {"code": "field_not_modelled", "subject": "compilation_config.custom_ops"}
    finally:
        shutil.rmtree(tmp)


def test_a_not_modelled_field_with_a_substitute_rule_states_the_substitute_and_names_it():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        _with_log(tmp, entry, LOG.replace("'max_model_len': 2304, ", "'language_model_only': True, "))
        o, work = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        sub = next(s for s in o.fidelity["substitutions"] if s["subject"] == "language_model_only")
        assert sub["kind"] == "estimated" and '"max_model_len": 8192' in sub["detail"]
        scen_text = next((work / "single_turn" / entry["point_id"]).glob("p-*.yaml")).read_text()
        assert "max_model_len: 8192" in scen_text and "language_model_only" not in scen_text
    finally:
        shutil.rmtree(tmp)


def test_launch_config_and_logged_args_that_disagree_are_g5_value_conflict():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        pdir = tmp / "pull" / "points" / entry["point_id"]
        lc = {"roles": {"agg": {"args": {"max-num-seqs": 32}}}, "resources": {"gpus_per_node": 8}}
        (pdir / "launch_config.gz").write_bytes(gzip.compress(json.dumps(lc).encode(), mtime=0))
        entry["files"]["launch_config"] = {"path": "launch_config.gz", "sha256": "0" * 64, "from": "artifact"}
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert o.g5 == {"code": "value_conflict", "subject": "max_num_seqs"}
    finally:
        shutil.rmtree(tmp)


def _launch_size(tmp: Path, entry, size: int) -> None:
    pdir = tmp / "pull" / "points" / entry["point_id"]
    lc = {"roles": {"agg": {"args": {}}}, "resources": {"gpu_type": "x", "gpus_per_node": size}}
    (pdir / "launch_config.gz").write_bytes(gzip.compress(json.dumps(lc).encode(), mtime=0))
    entry["files"]["launch_config"] = {"path": "launch_config.gz", "sha256": "0" * 64, "from": "artifact"}


def _scenario(work: Path, entry) -> dict:
    import yaml
    return next(d for d in yaml.safe_load_all(_scenario_text(work, entry)) if d.get("kind") == "Scenario")


def _scenario_text(work: Path, entry) -> str:
    return next((work / "single_turn" / entry["point_id"]).glob("p-*.yaml")).read_text()


def test_a_launch_configs_node_size_is_written_and_named_as_the_launch_configs():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        _launch_size(tmp, entry, 8)
        o, work = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        assert _scenario(work, entry)["cluster"]["gpus_per_node"] == 8
        assert "cluster.gpus_per_node: launch_config" in _scenario_text(work, entry)
        assert not [s for s in o.fidelity["substitutions"] if s["kind"] == "later_record"]
    finally:
        shutil.rmtree(tmp)


def test_a_node_size_only_the_runner_table_has_is_written_and_the_point_names_its_commit():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        o, work = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        assert _scenario(work, entry)["cluster"]["gpus_per_node"] == 8
        assert "cluster.gpus_per_node: InferenceX runners.yaml at 5d06e10c" in _scenario_text(work, entry)
        assert not [s for s in o.fidelity["substitutions"] if s["kind"] == "later_record"]
    finally:
        shutil.rmtree(tmp)


def test_a_launch_size_that_differs_from_the_runner_table_is_g5_value_conflict():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        _launch_size(tmp, entry, 4)
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert o.g5 == {"code": "value_conflict", "subject": "cluster.gpus_per_node"}
    finally:
        shutil.rmtree(tmp)


def test_a_label_the_runner_table_does_not_size_is_g5_value_not_recorded():
    tmp = Path(tempfile.mkdtemp())
    try:
        for hw in ("rtx6000pro", "vr200"):
            entry, env = _setup(tmp, hardware=hw)
            o, _ = _score(tmp, entry, env, tmp / ("c-" + hw))
            assert o.g5 == {"code": "value_not_recorded", "subject": "cluster.gpus_per_node"}, hw
    finally:
        shutil.rmtree(tmp)


def test_a_row_before_the_first_record_is_g2_with_the_later_record_substitution():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp, date="2026-06-15")
        o, work = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        later = [s for s in o.fidelity["substitutions"] if s["kind"] == "later_record"]
        assert later == [{"kind": "later_record", "subject": "cluster.gpus_per_node",
                          "detail": "taken from InferenceX runners.yaml at 303669b0, recorded after the run "
                                    "(303669b0 of 2026-07-02)"}]
        assert o.fidelity["grade"] == "G2" and _scenario(work, entry)["cluster"]["gpus_per_node"] == 8
        assert c.validate_dir(tmp / "c1") == []
    finally:
        shutil.rmtree(tmp)


def test_an_unstable_label_before_its_first_record_stays_g5_value_not_recorded():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp, date="2026-06-15")
        env.runner_table = ir.Table(env.runner_table.versions, {
            **env.runner_table.labels,
            "mi355x": dataclasses.replace(env.runner_table.labels["mi355x"], stable=False, problems=("x: changed",))})
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert o.g5 == {"code": "value_not_recorded", "subject": "cluster.gpus_per_node"}
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
        assert o.fidelity is None and o.reasons == ["field_not_modelled:prefill_schedule_interval"]
        assert o.g5 == {"code": "field_not_modelled", "subject": "prefill_schedule_interval"}
        assert c.validate_dir(tmp / "c1") == []
    finally:
        shutil.rmtree(tmp)


def test_a_coefficient_not_measured_or_a_missing_report_makes_the_point_g2_and_never_g1():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        env.blis = _fake_blis(tmp, methods=("measured", "roofline"))
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert {"kind": "coefficient_method", "subject": "cost-model-attention/n1", "detail": "roofline"} \
            in o.fidelity["substitutions"]
        env.blis = _fake_blis(tmp, methods=None)
        o, _ = _score(tmp, entry, env, tmp / "c2")
        assert {"kind": "coefficient_method", "subject": "selected-entry report", "detail": "not read"} \
            in o.fidelity["substitutions"]
        assert c.validate_dir(tmp / "c2") == []
    finally:
        shutil.rmtree(tmp)



def test_a_single_turn_point_with_data_parallel_ranks_names_the_balancer_substitution():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp)
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert not [s for s in o.fidelity["substitutions"] if s["subject"] == "data-parallel balancer"]
        log = LOG.replace("'tensor_parallel_size': 1,", "'tensor_parallel_size': 1, 'data_parallel_size': 2,") \
            .replace("data_parallel_size=1", "data_parallel_size=2")
        _with_log(tmp, entry, log)
        entry["row"].update(num_decode_gpu=2)
        o, _ = _score(tmp, entry, env, tmp / "c2")
        assert o.fidelity is not None, o.reasons
        assert {"kind": "execution_mode", "subject": "data-parallel balancer", "detail":
                "llm-d endpoint picker profile vllm-dp-lb stands in for vLLM's internal load balancer"} \
            in o.fidelity["substitutions"]
        assert c.validate_dir(tmp / "c2") == []
    finally:
        shutil.rmtree(tmp)


def test_an_agentic_points_max_model_len_is_the_runs_own_and_never_a_default():
    # X19, design §11.2: the replay filters its corpus against the deployment's max_model_len,
    # so a recorded 1048576 is copied, and an unrecorded one is left unset, never a context length
    # the run did not state. blis refuses what it cannot resolve (value_not_recorded, score.value_refusal).
    import yaml
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _agentic(tmp)
        _with_log(tmp, entry, LOG.replace("'max_model_len': 2304", "'max_model_len': 1048576"))
        o, work = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        argv = _saw(env)[0]["argv"]
        scen = Path(argv[argv.index("--scenarios") + 1]) / argv[argv.index("--scenario") + 1]
        eng = list(yaml.safe_load_all(scen.read_text()))[1]["pools"][0]["engine"]
        assert eng["max_model_len"] == 1048576
        spec = yaml.safe_load(Path(argv[argv.index("--workload-spec") + 1]).read_text())["replay"]
        assert "max_context_length" not in spec          # the client filtered nothing
    finally:
        shutil.rmtree(tmp)
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _agentic(tmp)
        _with_log(tmp, entry, LOG.replace("'max_model_len': 2304, ", ""))
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        argv = _saw(env)[0]["argv"]
        scen = Path(argv[argv.index("--scenarios") + 1]) / argv[argv.index("--scenario") + 1]
        eng = list(yaml.safe_load_all(scen.read_text()))[1]["pools"][0]["engine"]
        assert "max_model_len" not in eng             # left unset: blis resolves it or refuses
    finally:
        shutil.rmtree(tmp)


def test_an_agentic_clients_max_context_length_reaches_the_replay_as_recorded():
    import yaml
    from test_extract import _export
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _agentic(tmp)
        doc = _export()
        doc["input_config"]["datasets"][0]["max_context_length"] = 1048576
        (tmp / "pull" / "points" / entry["point_id"] / "export.gz").write_bytes(
            gzip.compress(json.dumps(doc).encode(), mtime=0))
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        argv = _saw(env)[0]["argv"]
        spec = yaml.safe_load(Path(argv[argv.index("--workload-spec") + 1]).read_text())["replay"]
        assert spec["max_context_length"] == 1048576
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


def test_a_client_flag_the_harness_does_not_reproduce_makes_the_point_g5_value_not_recorded():
    tmp = Path(tempfile.mkdtemp())
    try:
        for extra, flag in ((" --use-chat-template", "--use-chat-template"), (" --seed 7", "--seed")):
            tmp = Path(tempfile.mkdtemp())
            entry, env = _setup(tmp, job_log=job_log_text(1024, 1024, 4, extra))
            o, _ = _score(tmp, entry, env, tmp / "c1")
            assert o.fidelity is None and o.reasons == [f"value_not_recorded:client:{flag}"]
            assert asx.g5_of(o.reasons[0]) == {"code": "value_not_recorded", "subject": f"client:{flag}"}
            assert _saw(env) == []
        tmp = Path(tempfile.mkdtemp())
        entry, env = _setup(tmp, job_log=job_log_text(1024, 1024, 4).replace("ratio 0.8", "ratio 1.0"))
        o, _ = _score(tmp, entry, env, tmp / "c2")
        assert o.reasons == ["value_not_recorded:client:--random-range-ratio"]
    finally:
        shutil.rmtree(tmp)


def test_an_expired_job_log_keeps_the_point_scored_and_names_client_flags_assumed():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp, job_log=None)
        o, _ = _score(tmp, entry, env, tmp / "c1")
        diffs = o.fidelity["requests"]["differences"]
        assert "client_flags" in [d["subject"] for d in diffs] and o.fidelity["grade"] == "G2"
        d = next(d for d in diffs if d["subject"] == "client_flags")
        assert d["kind"] == "client_difference" and \
            d["detail"] == "job log expired; the client's flags are assumed to be the launcher's defaults"
        tmp = Path(tempfile.mkdtemp())
        entry, env = _setup(tmp)
        o, _ = _score(tmp, entry, env, tmp / "c2")
        assert "client_flags" not in [d["subject"] for d in o.fidelity["requests"]["differences"]]
    finally:
        shutil.rmtree(tmp)


def test_a_run_with_no_recorded_inferencex_commit_names_client_release_unrecorded():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp, client_commit=False)
        o, _ = _score(tmp, entry, env, tmp / "c1")
        diffs = o.fidelity["requests"]["differences"]
        assert "client_release" in [d["subject"] for d in diffs] and o.fidelity["grade"] == "G2"
        tmp = Path(tempfile.mkdtemp())
        entry, env = _setup(tmp)
        o, _ = _score(tmp, entry, env, tmp / "c2")
        assert "client_release" not in [d["subject"] for d in o.fidelity["requests"]["differences"]]
    finally:
        shutil.rmtree(tmp)


def _scenario_cluster(tmp, entry):
    import yaml
    text = next((tmp / ("work-c1") / "single_turn" / entry["point_id"]).glob("p-*.yaml")).read_text()
    return yaml.safe_load(text.split("\n---\n")[0])["cluster"]


def test_a_gb200_nvl72_point_writes_neither_gpus_per_node_nor_gpus_per_rack():
    # Design §2.2, SUB-3: the catalog entry fixes 4 GPUs per node and 72 per rack. The table is
    # not consulted, so the point names no later_record.
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp, hardware="gb200", chips={"gb200-nvl72": (4, 72)}, node_size=4)
        env.parts = {"gb200-nvl72"}
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert o.g5 is None and o.fidelity is not None
        assert _scenario_cluster(tmp, entry) == {"hardware": "gb200-nvl72", "nodes": 1}
        assert not [s for s in o.fidelity["substitutions"] if s["kind"] == "later_record"]
    finally:
        shutil.rmtree(tmp)


def test_an_h100_point_writes_the_node_size_the_run_recorded():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp, hardware="h100", chips={"h100": (None, None)}, node_size=8)
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert o.g5 is None and o.fidelity is not None
        assert _scenario_cluster(tmp, entry) == {"hardware": "h100", "gpus_per_node": 8, "nodes": 1}
    finally:
        shutil.rmtree(tmp)


def test_a_point_with_no_recorded_node_size_on_a_chip_that_fixes_none_is_g5_value_not_recorded():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _setup(tmp, hardware="rtx6000pro", chips={"rtx6000pro": (None, None)}, node_size=None)
        o, _ = _score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is None
        assert o.g5 == {"code": "value_not_recorded", "subject": "cluster.gpus_per_node"}
    finally:
        shutil.rmtree(tmp)
