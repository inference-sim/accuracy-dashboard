"""Stage 2: score a frozen pull with one BLIS release and write the contract directory
(orchestrator/ingest/CONTRACT.md).

Per point: settings (settings.py) -> support (support.py) -> replay inputs (replay.py, agentic)
-> the scenario file -> `blis replay --agentic-scenario` -> the diff of what BLIS was given
against what the run recorded -> one fidelity record, or a not-scored record with reasons.

Single-turn points go through the same extraction and are scored with inference-sim's
signedprobe at the same BLIS tag (score_single_turn).
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import contract  # noqa: E402
import replay as rp  # noqa: E402
import settings as st  # noqa: E402
import support as sp  # noqa: E402

AGENTIC_LABEL = "agentx"

# The API row fields that vary from point to point within one InferenceX curve. Every other
# field is the curve's (run, model, part, parallelism, drafter, DP attention, offload, ...), so
# rows that differ in any of them are separate curves even inside one workflow run. A field the
# API adds later counts as the curve's: at worst that splits a curve, never merges two.
PER_POINT_ROW_FIELDS = ("conc", "id", "metrics", "power_audit", "power_invalid_reasons", "recipe_fingerprint")


def sweep_id(row: dict, scenario: str, label: str) -> str:
    """The measured curve a point belongs to (facets' sweep_id), for the shape metric."""
    curve = {k: v for k, v in row.items() if k not in PER_POINT_ROW_FIELDS}
    h = hashlib.sha256(contract.canonical_dumps(curve).encode()).hexdigest()[:12]
    return f"{row.get('curve_workflow_run_id')}|{scenario}|{label}|{h}"


@dataclass
class Env:
    """What scoring runs against: one BLIS release and its pinned repos."""
    blis: str
    blis_release: str
    blis_commit: str
    catalog: Path
    catalog_release: str
    registry: Path
    registry_release: str
    kernel: str
    defaults_helper: str
    corpus: dict          # {"dataset", "revision", "sha256", "path", "file"}
    corpus_cache: Path | None = None
    vllm_ref: str = "v0.31.0"
    policy: dict = field(default_factory=dict)
    policy_sha256: str = ""
    base_models: dict = field(default_factory=dict)   # HF repo -> base_model (frozen)
    timeout_s: int = 7200
    vllm_defaults: dict = field(default_factory=dict)
    vllm_defaults_sha256: str = ""
    catalog_obj: sp.Catalog | None = None
    parts: set = field(default_factory=set)
    # Single-turn: inference-sim's signedprobe at the same tag, and the benchmark workloads it
    # replays (its testdata/inferencex-workloads/seed0.json: InferenceX's request lengths per
    # (isl, osl, concurrency)).
    signedprobe: str = ""
    single_turn_workloads: set = field(default_factory=set)   # {(isl, osl, conc)}


def _read(point_dir: Path, files: dict, role: str) -> bytes | None:
    f = files.get(role)
    if not f:
        return None
    return gzip.decompress((point_dir / f["path"]).read_bytes())


def _checkpoints(c: st.Classified, launch_cfg: dict | None) -> list[str]:
    """The served checkpoint's candidate HF repos, most authoritative first: the launch
    config's model path, then the served model name, then --model."""
    out = []
    if launch_cfg:
        r = sp.hf_repo(((launch_cfg.get("model") or {}).get("path")))
        if r:
            out.append(r)
    for role in ("served_model", "model"):
        v = c.roles.get(role)
        for x in (v if isinstance(v, list) else [v]):
            r = sp.hf_repo(x)
            if r and r not in out:
                out.append(r)
    return out


def _metrics_us(m: dict) -> tuple[float, float]:
    # TPOT is the per-token figure aiperf reports (request_itl_mean_ms), not the step interval.
    return float(m["ttft_mean_ms"]) * 1e3, float(m["request_itl_mean_ms"]) * 1e3


def _blis_refusal(stderr: str, work: Path) -> str:
    """blis_refused:<slug> from BLIS's fatal message, with this run's paths removed so the
    reason is the same on every machine."""
    m = re.findall(r'level=fatal msg="([^"]+)"', stderr) or re.findall(r"level=fatal msg=(.+)", stderr)
    text = (m[-1] if m else stderr.strip().splitlines()[-1] if stderr.strip() else "no output")
    text = text.replace(str(work), "").replace(str(work.resolve()), "")
    text = re.sub(r"(/[^\s\"']+)+", "<path>", text)
    text = re.sub(r"\bp-[0-9a-f]{16}\b", "<scenario>", text)
    slug = re.sub(r"[^A-Za-z0-9_.:=-]+", "_", text)[:80].strip("_")
    return f"blis_refused:{slug}" if slug else "blis_refused"


def resolved_kv(log: str, metrics: dict | None) -> list[dict]:
    """The KV pool vLLM allocated vs BLIS's, per engine core. Never passed to BLIS."""
    found = [int(x.replace(",", "")) for x in re.findall(r"GPU KV cache size: ([0-9,]+) tokens", log)]
    if not found:
        return []
    rec = {"quantity": "kv_cache_tokens_per_replica"}
    if len(set(found)) > 1:
        return [{**rec, "measured": None, "blis": None, "match": "conflict"}]
    rec["measured"] = found[0]
    if len(found) > 1:
        rec["occurrences"] = len(found)
    blis = (metrics or {}).get("kv_capacity_tokens_per_replica")
    # (No KV line at all returns [] above: the record then has no KV comparison, which the
    # fidelity record states by its absence; the line is printed by every v1 engine.)
    if not blis:
        return [{**rec, "blis": None, "match": "unreadable"}]
    rec.update(blis=int(blis), delta=int(blis) - found[0], ratio=contract.ratio_str(int(blis), found[0]),
               match="exact" if int(blis) == found[0] else "differs")
    return [rec]


def _parse_back(scenario_text: str) -> dict:
    import yaml
    docs = list(yaml.safe_load_all(scenario_text))
    dep = next(d for d in docs if d.get("kind") == "Deployment")
    return dep


def _get(d: dict, dotted: str):
    for k in dotted.split("."):
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def _blis_value(dep: dict, blis_field: str):
    """The value at a policy blis_field in the Deployment as written."""
    if blis_field == "offload.tiers.cpu_dram":
        tiers = (dep.get("offload") or {}).get("tiers") or []
        return next((t["bytes"] for t in tiers if t.get("tier") == "cpu_dram"), None)
    if blis_field.startswith("offload."):
        return _get(dep, blis_field)
    return _get(dep["pools"][0], blis_field)


def _diff_args(args: list, dep: dict, b: st.Built) -> list[str]:
    """Fill each mapped arg's `blis` from the scenario as WRITTEN (parsed back), and its match:
    exact when the BLIS field has the arg's own name, mapped when it's a renamed field (named
    in blis_field), differs / absent_in_blis otherwise (a refusal: the writer lost it)."""
    reasons = []
    for a in args:
        if "_value" not in a:
            continue
        want = a.pop("_value")
        f = a["blis_field"]
        if f == "replay.acceptance_length":
            got, want = b.acceptance_length, str(want)
        elif f.startswith("offload."):
            # The offload writer converts units (per-rank bytes -> the engine's tier); its own
            # checks refused any disagreement, so the arg records what BLIS was given.
            got = _blis_value(dep, f)
            a["blis"] = got
            a["match"] = "mapped" if got is not None else "absent_in_blis"
            if got is None:
                reasons.append(f"setting_differs:{a['arg']}")
            continue
        else:
            got = _blis_value(dep, f)
            if f == "engine.frontend":
                want = st.FRONTEND[want]
        a["blis"] = json.dumps(got) if isinstance(got, list) else (repr(got) if isinstance(got, float) else got)
        if got is None:
            a["match"] = "absent_in_blis"
        elif json.dumps(got, sort_keys=True) != json.dumps(want, sort_keys=True):
            a["match"] = "differs"
        else:
            a["match"] = "exact" if a["arg"].split(".")[-1] == f.split(".")[-1] else "mapped"
        if a.pop("_approximated", False) and a["match"] in ("exact", "mapped"):
            a["match"] = "approximated"
        if a["match"] in ("absent_in_blis", "differs"):
            reasons.append(f"setting_differs:{a['arg']}")
        if a["match"] != "mapped":
            a.pop("blis_field", None)
    return reasons


@dataclass
class Outcome:
    point_id: str
    identity: dict
    row: dict
    reasons: list = field(default_factory=list)
    fidelity: dict | None = None
    facets: dict | None = None
    csv_row: list | None = None


def _score_one(entry: dict, pull_dir: Path, work: Path, env: Env) -> Outcome:
    """score_point with the uniform error capture the driver used to do inline, so both the serial
    and the parallel path record a point that raises as not-scored (never drop it)."""
    try:
        return score_point(entry, pull_dir, work, env)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return Outcome(point_id=entry["point_id"], identity=entry["identity"], row=entry["row"],
                       reasons=sorted(set(entry["reasons"] + ["blis_refused:extractor_error"])))


# A process-pool worker scores into its OWN work subdir, because score_point writes
# work/scenarios/<scenario>.yaml keyed by scenario name, not point id -- two points that share a
# scenario name would race that file across processes. Per-worker dirs isolate it; the per-point
# metrics/<pid>.json cache stays correct either way (pid is unique). The worker's env and pull_dir
# are set once per process in the initializer, so each task ships only the small `entry`.
_W: dict = {}


def _worker_init(pull_dir: str, env: Env, work: str):
    _W["pull_dir"] = Path(pull_dir)
    _W["env"] = env
    # os.getpid() is stable for the life of a pool worker -> a fixed per-worker dir it reuses, so
    # the scenario cache within one worker still helps across its tasks.
    import os
    _W["work"] = Path(work) / f"w{os.getpid()}"
    _W["work"].mkdir(parents=True, exist_ok=True)


def _worker_score(entry: dict) -> Outcome:
    return _score_one(entry, _W["pull_dir"], _W["work"], _W["env"])


def _is_agentic(entry: dict) -> bool:
    return entry["row"].get("benchmark_type") == "agentic_traces"


def score_points(points: list, pull_dir: Path, work: Path, env: Env, *, workers: int = 1,
                 agentic_workers: int = 1, log=lambda m: None) -> list:
    """Score every point. The result is collected in input order regardless of completion order,
    and write_contract re-sorts by point_id, so the contract is identical whatever the worker
    count -- concurrency is a speed knob, never a correctness or determinism lever.

    Split by benchmark type, because the two kinds have opposite resource profiles:
      * single-turn (signedprobe, no corpus): light RAM, safe to run `workers`-wide.
      * agentic (blis replay + the 1.8GB corpus): each replay holds the parsed corpus in RAM, so
        two at once OOM a 16GB runner -- capped at `agentic_workers` (default 1, serial).
    So the light majority runs parallel while the heavy minority serializes, which keeps a
    BLIS-release night (full-window rescore) inside the runner's memory without serializing the
    whole window. On a big box pass agentic_workers > 1 if the RAM is there."""
    agentic = [(i, e) for i, e in enumerate(points) if _is_agentic(e)]
    single = [(i, e) for i, e in enumerate(points) if not _is_agentic(e)]
    n = len(points)
    results: dict = {}
    done = [0]

    def record(idx, o):
        results[idx] = o
        done[0] += 1
        e = points[idx]
        log(f"  [{done[0]}/{n}] {e['row']['model']} {e['row']['hardware']} c{e['row']['conc']} "
            f"{e['point_id'][:12]} -> {o.fidelity['status'] if o.fidelity else o.reasons}")

    if single:
        log(f"score: {len(single)} single-turn on {max(workers, 1)} worker(s)")
        _run_pool(single, pull_dir, work, env, max(workers, 1), record)
    if agentic:
        log(f"score: {len(agentic)} agentic on {max(agentic_workers, 1)} worker(s) (corpus-heavy)")
        _run_pool(agentic, pull_dir, work, env, max(agentic_workers, 1), record)
    return [results[i] for i in range(n)]   # input order; write_contract re-sorts anyway


def _run_pool(indexed: list, pull_dir: Path, work: Path, env: Env, workers: int, record) -> None:
    """Score a list of (index, entry) at the given concurrency, calling record(index, outcome) as
    each finishes. workers<=1 runs in-process (no pool), else a ProcessPoolExecutor."""
    if workers <= 1:
        for idx, e in indexed:
            record(idx, _score_one(e, pull_dir, work, env))
        return
    from concurrent.futures import ProcessPoolExecutor, as_completed
    with ProcessPoolExecutor(max_workers=workers, initializer=_worker_init,
                             initargs=(str(pull_dir), env, str(work))) as ex:
        futs = {ex.submit(_worker_score, e): idx for idx, e in indexed}
        for fut in as_completed(futs):
            record(futs[fut], fut.result())


def score_point(entry: dict, pull_dir: Path, work: Path, env: Env) -> Outcome:
    row, ident, pid = entry["row"], entry["identity"], entry["point_id"]
    o = Outcome(point_id=pid, identity=ident, row=row, reasons=list(entry["reasons"]))
    pdir = pull_dir / "points" / pid
    log_b = _read(pdir, entry["files"], "server_log")
    if log_b is None:
        o.reasons = sorted(set(o.reasons + ["server_log_missing"]))
        return o
    log = log_b.decode("utf-8", "replace")
    lc_b = _read(pdir, entry["files"], "launch_config")
    launch = json.loads(lc_b) if lc_b else None

    readings, problems = st.read_all(log, launch)
    # The API row's router is its own source: it states the frontend, nothing about the engine.
    rm = row.get("metrics") or {}
    if rm.get("router_name") and "frontend.router" not in readings["launch_config"].values:
        readings["api_row"] = st.Reading()
        readings["api_row"].add("frontend.router", f"{rm['router_name']}/{rm.get('router_version') or ''}".rstrip("/"))
    if problems:
        o.reasons.append("conflict:server_log_unreadable")
    # The catalog part the row's hardware label names (support.catalog_part); the label itself
    # stays what the row is shown and keyed by.
    part_name = (sp.catalog_part(env.catalog_obj, env.parts, row["hardware"]) if env.catalog_obj else None) \
        or row["hardware"]
    c = st.classify(st.merge(readings, env.policy, env.vllm_defaults), env.policy, env.vllm_defaults,
                    family=env.catalog_obj.capability.get(part_name) if env.catalog_obj else None)
    o.reasons += c.reasons
    o.reasons += row_vs_run(row, c)

    cat = env.catalog_obj
    spec = c.mapped.get("engine.speculative.method", (None, None, None))[1]
    cks = _checkpoints(c, launch)
    if not cks and (entry.get("checkpoint") or {}).get("repo"):
        # The log served a local path; the run's own recipe names the checkpoint (pull.py).
        cks = [entry["checkpoint"]["repo"]]
    sup = sp.check(cat, env.parts, checkpoints=cks, base_models=env.base_models,
                   hardware=part_name, spec_method=spec)
    o.reasons += sup.reasons

    agentic = row["benchmark_type"] == "agentic_traces"
    r = None
    if agentic:
        exp_b = _read(pdir, entry["files"], "client_export")
        if exp_b is None:
            o.reasons.append("artifact_unmatched:client_export")
        else:
            r = rp.from_export(json.loads(exp_b))
            cmd = _read(pdir, entry["files"], "client_command")
            rp.cross_check(r, cmd.decode("utf-8", "replace") if cmd else None, row.get("conc"))
            o.reasons += r.reasons
            if not r.corpus_repo:
                o.reasons.append("required_setting_missing:replay.corpus_repo")
            elif r.corpus_repo != env.corpus["dataset"]:
                o.reasons.append(f"corpus_changed:{r.corpus_repo}")
    else:
        o.reasons += single_turn_replayable(row, env)

    if sup.model is None or part_name not in cat.hardware:
        o.reasons = sorted(set(o.reasons))
        return o
    part = st.Part(name=part_name, memory_gib=cat.hardware[part_name])
    try:
        defaults = st.blis_defaults(env.defaults_helper, part)
    except subprocess.SubprocessError as ex:
        # Kept with the point's own reasons, never replaced by a bare extractor error.
        o.reasons = sorted(set(o.reasons + [_helper_failure(ex)]))
        return o
    name = f"p-{pid[:16]}"
    b = st.build(c, name=name, model=sup.model, part=part, engine_version=env.vllm_ref, defaults=defaults)
    o.reasons += b.reasons
    header = [f"point {pid}", f"InferenceX row {row['id']} ({row['run_url']})",
              "GENERATED by orchestrator/ingest/score.py from the run's own settings. Do not edit."]
    text = st.to_yaml(b, header)
    sdir = work / "scenarios"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / f"{name}.yaml").write_text(text)
    dep = _parse_back(text)
    args = c.args + b.defaults_used
    if o.reasons:
        # Already not scored. BLIS is asked only about a point nothing else refused: its
        # verdict on a known gap (e.g. a drafter the catalog doesn't describe) would restate
        # that gap as a second reason and count the point twice.
        o.reasons = sorted(set(o.reasons))
        return o
    o.reasons += kernel_defaults(args, b.kernel_resolves, env, sdir, f"{name}.yaml")
    if b.acceptance_needed:
        o.reasons += acceptance_default(args, b, env, log, part_name, sup.model)
        if o.reasons:
            o.reasons = sorted(set(o.reasons))
            return o
    if b.kernel_resolves or b.acceptance_needed or b.acceptance_length is not None:
        # State what the kernel resolved, so every consumer (signedprobe's harness requires a
        # stated block_size) runs the same value the kernel would have assumed.
        eng = b.deployment["pools"][0]["engine"]
        for a in args:
            if a["arg"] in b.kernel_resolves and a["match"] == "blis_default":
                eng[a["arg"]] = a["blis"]
        spec = eng.get("speculative") or {}
        if b.acceptance_needed:
            al = float(next(a["blis"] for a in args if a["arg"] == ACCEPTANCE_ARG))
        elif b.acceptance_length is not None:
            al = float(b.acceptance_length)       # the run's own synthetic acceptance
        else:
            al = None
        if al is not None and spec.get("num_spec_tokens"):
            # Pinned in the scenario, so every consumer runs it: blis replay (which also takes
            # --speculative-acceptance-length) and signedprobe (which passes no acceptance flag).
            b.scenario["acceptance"] = {"value": {"num_spec_tokens": int(spec["num_spec_tokens"]),
                                                  "acceptance_length": al}}
        text = st.to_yaml(b, header)
        (sdir / f"{name}.yaml").write_text(text)
        dep = _parse_back(text)
    o.reasons += fill_blis_side(args, env, sdir, f"{name}.yaml", sup.model)
    o.reasons += _diff_args(args, dep, b)
    args.sort(key=lambda a: a["arg"])
    o.reasons = sorted(set(o.reasons))
    if o.reasons:
        return o

    if not agentic:
        return score_single_turn(o, entry, env, work, sdir, name, text, dep, args, log, _estimated(args))

    # ---- the replay
    metrics_path = work / "metrics" / f"{pid}.json"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    spec_doc = rp.workload_spec(r, env.corpus["sha256"], env.corpus["revision"], env.corpus["file"])
    spec_path = work / "workloads" / f"{pid}.yaml"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    import yaml
    spec_path.write_text(yaml.safe_dump({"replay": spec_doc}, sort_keys=False))
    argv = [env.blis, "replay", "--agentic-scenario", r.replayed_as,
            "--workload-spec", str(spec_path), "--concurrency", str(r.concurrency),
            "--seed", str(r.seed), "--corpus", env.corpus["path"], "--corpus-sha256", env.corpus["sha256"],
            "--scenario", f"{name}.yaml", "--scenarios", str(sdir),
            "--catalog", str(env.catalog), "--registry", str(env.registry),
            "--metrics-path", str(metrics_path)]
    if b.acceptance_length is not None:
        argv += ["--speculative-acceptance-length", b.acceptance_length]
    if env.corpus_cache:
        argv += ["--corpus-cache", str(env.corpus_cache)]
    # The cached result is reused only for the exact same inputs: scenario, workload, argv.
    key = hashlib.sha256((text + spec_path.read_text() + "\0".join(argv[1:])).encode()).hexdigest()
    key_path = metrics_path.with_suffix(".key")
    if metrics_path.exists() and (not key_path.exists() or key_path.read_text() != key):
        metrics_path.unlink()
    if not metrics_path.exists():
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=env.timeout_s)
        except subprocess.TimeoutExpired:
            o.reasons = ["blis_refused:timeout"]
            return o
        (work / "logs").mkdir(exist_ok=True)
        (work / "logs" / f"{pid}.err").write_text(proc.stderr[-20000:])
        if proc.returncode != 0 or not metrics_path.exists():
            o.reasons = [_blis_refusal(proc.stderr, work)]
            return o
        key_path.write_text(key)
    metrics = json.loads(metrics_path.read_text())
    try:
        pttft, ptpot = _metrics_us(metrics)
    except (KeyError, TypeError, ValueError):
        o.reasons = ["blis_refused:metrics_incomplete"]
        return o

    m = row.get("metrics") or {}
    status = point_status(_estimated(args), entry["build"])
    o.fidelity = {"status": status, "build": entry["build"], "args": args,
                  "resolved": resolved_kv(log, metrics), "replay": r.record(env.corpus["sha256"]),
                  "blis_kernel_provenance": metrics.get("kernel_provenance")}
    par = dep["pools"][0]["parallel"]
    ep = (par["tp"] * par["dp"]) if par.get("enable_expert_parallel") else 1
    scen = f"{sup.model}-{row['hardware']}-{row['precision']}-vllm-tp{par['tp']}-dp{par['dp']}-ep{ep}-agentx"
    o.facets = {"identity": ident, "sweep_id": sweep_id(row, scen, AGENTIC_LABEL),
                "scenario": scen, "label": AGENTIC_LABEL, "workload": AGENTIC_LABEL, "model": sup.model,
                "gpu": row["hardware"], "precision": row["precision"], "framework": "vllm",
                "serving": "aggregated", "spec_method": row.get("spec_method") or "none",
                "parallelism": {"tp": par["tp"], "pp": par["pp"], "dp": par["dp"], "ep": ep},
                "image": row.get("image"), "vllm_version": _banner_version(log)}
    o.csv_row = [scen, sup.model, row["hardware"], AGENTIC_LABEL, ident["conc"],
                 round(float(m["mean_tpot"]) * 1e6, 3), round(ptpot, 3),
                 round(float(m["mean_ttft"]) * 1e6, 3), round(pttft, 3),
                 contract.TIER_BY_STATUS[status], pid, ident["measured_date"]]
    return o


def blis_resolution(env, scenarios: Path, scenario: str) -> dict | str:
    """What BLIS resolves for the scenario as written (orchestrator/blisdefaults -resolve):
    the kernel's own resolution, including every requested value it overrode and why. If BLIS
    refuses the scenario, its refusal as a blis_refused reason instead."""
    out = subprocess.run([env.defaults_helper, "-resolve", "-scenarios", str(scenarios), "-scenario", scenario,
                          "-catalog", str(env.catalog), "-registry", str(env.registry)],
                         capture_output=True, text=True, timeout=600)
    if out.returncode != 0:
        return _blis_refusal(out.stderr.replace("blisdefaults: ", ""), scenarios.parent)
    return json.loads(out.stdout)


ACCEPTANCE_ARG = "speculative_config.acceptance_length"
_REQUEST = re.compile(r'"POST (/v1/[\w/]+)')


def _thinking(log: str) -> str | None:
    """The thinking mode a run's requests ran in, when the log shows it unambiguously: raw
    /v1/completions prompts go through no chat template, so no reasoning mode applies ("off").
    Chat requests' mode depends on their template arguments, which the log doesn't state."""
    paths = set(_REQUEST.findall(log or ""))
    return "off" if paths == {"/v1/completions"} else None


def acceptance_default(args: list, b, env, log: str, hardware: str, model: str) -> list[str]:
    """The run drafted without recording its acceptance: take BLIS's own registry default for
    the drafter (blisdefaults -acceptance, blis-schemas' resolver) and record it as estimated.
    Refused when the thinking mode can't be read, or BLIS has no profile."""
    method, k = b.acceptance_needed
    thinking = _thinking(log)
    if thinking is None:
        return ["required_setting_missing:speculative_config.synthetic_acceptance_length"]
    out = subprocess.run([env.defaults_helper, "-acceptance", "-registry", str(env.registry), "-model", model,
                          "-method", method, "-k", str(k), "-thinking", thinking, "-device", hardware],
                         capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        return ["required_setting_missing:speculative_config.synthetic_acceptance_length"]
    res = json.loads(out.stdout)
    where = f" (measured on {res['measured_on']})" if res.get("measured_on") else ""
    fell = f"; the run's requests state no category, so BLIS's only one for this drafter was used" \
        if res.get("fallback_from") else ""
    # As a decimal string: fidelity records hold no floats (contract canonical JSON).
    args.append({"arg": ACCEPTANCE_ARG, "measured": None, "source": "blis_default", "blis": repr(float(res["acceptance_length"])),
                 "match": "approximated",
                 "note": f"The run didn't record its draft acceptance; BLIS used its registry default "
                         f"{res['profile']}{where}{fell}."})
    return []


def kernel_defaults(args: list, paths: list, env, scenarios: Path, scenario: str) -> list[str]:
    """For each required setting no source recorded and the scenario leaves to BLIS, record the
    value BLIS's kernel resolved, read from BLIS (blisdefaults -resolve). If BLIS reports none,
    or refuses the scenario, the point isn't scored."""
    if not paths:
        return []
    res = blis_resolution(env, scenarios, scenario)
    if isinstance(res, str):
        return [res]
    got = {a["name"]: a for a in res.get("assumptions", [])}
    reasons = []
    for path in paths:
        a = got.get(path)
        if a is None:
            reasons.append(f"required_setting_missing:{path}")
            continue
        v = int(a["value"]) if a["value"].isdigit() else a["value"]
        args.append({"arg": path, "measured": None, "source": "blis_default", "blis": v,
                     "match": "blis_default", "rule": f"BLIS kernel: {a['reason']}"[:300]})
    return reasons


def fill_blis_side(args: list, env, scenarios: Path, scenario: str, model: str) -> list[str]:
    """For each approximated setting, record what BLIS actually used, read from BLIS -- never a
    placeholder. A setting whose source BLIS can't report refuses the point."""
    need = [a for a in args if a.get("_blis_from")]
    if not need:
        return []
    reasons, res = [], None
    for a in need:
        src = a.pop("_blis_from")
        if src.startswith("resolved."):
            if res is None:
                res = blis_resolution(env, scenarios, scenario)
                if isinstance(res, str):
                    # BLIS refuses the scenario itself: that is the point's reason, next to its others.
                    reasons.append(res)
            if isinstance(res, str):
                continue
            # The kernel's resolved value: reported whole for the fields blisdefaults states
            # (cache_dtype), else the override it made of the requested one.
            field = src.split(".", 1)[1]
            hit = [o["resolved"] for o in res["overrides"] if o["field"] == field]
            a["blis"] = res.get(field) or (hit[0] if hit else None)
        elif src == "priced.index_cache":
            # The indexer record the kernel prices on this chip, under the cache dtype it
            # resolved, named by vLLM's layout for its head width. One record or none.
            if res is None:
                res = blis_resolution(env, scenarios, scenario)
                if isinstance(res, str):
                    reasons.append(res)
            if isinstance(res, str):
                continue
            index = [c for c in res.get("caches", []) if c["kind"] == "index"]
            if not index:
                # The model has no sparse indexer (Kimi, Qwen ...): vLLM reads the setting
                # nowhere, so it changes nothing BLIS prices. Recorded, not estimated.
                a.update(blis=None, match="inert", note="The model has no sparse indexer, so this setting has no effect.")
                continue
            names = {sp.index_record_format(c["bytes_per_entry"], c.get("head_dim", 0)) for c in index}
            a["blis"] = names.pop() if len(names) == 1 else None
        if a["blis"] is None:
            reasons.append(f"setting_differs:{a['arg']}")
    return reasons


def single_turn_replayable(row: dict, env) -> list[str]:
    """signedprobe replays InferenceX's single-turn benchmark from its own request-length
    fixture; a (isl, osl, concurrency) the fixture doesn't hold can't be replayed."""
    try:
        key = (int(row["isl"]), int(row["osl"]), int(row["conc"]))
    except (KeyError, TypeError, ValueError):
        return ["required_setting_missing:replay.isl_osl"]
    if key not in env.single_turn_workloads:
        return [f"client_scenario_not_replayable:single_turn_{key[0]}:{key[1]}_c{key[2]}"]
    return []


def _single_turn_label(isl: int, osl: int) -> str:
    k = lambda n: f"{n // 1024}k" if n % 1024 == 0 else str(n)
    return f"{k(isl)}{k(osl)}"


# The engine fields signedprobe sets on the scenario it runs (harness.applyPointConfig): each is
# passed as the scenario we wrote states it, so signedprobe runs exactly that scenario and never
# substitutes its own vLLM resolution for one of them.
_PROBE_FIELDS = (("max_num_seqs", "max_num_seqs"), ("max_num_batched_tokens", "max_num_batched_tokens"),
                 ("max_model_len", "max_model_len"), ("block_size", "block_size"),
                 ("enable_prefix_caching", "enable_prefix_caching"),
                 ("gpu_memory_utilization", "gpu_memory_utilization"),
                 ("max_cudagraph_capture_size", "max_cudagraph_capture_size"))


def single_turn_inputs(row: dict, dep: dict, scenario_file: str) -> tuple[dict, dict, dict] | list[str]:
    """signedprobe's three inputs for one point: a one-sweep corpus, the measured means
    (absolutes) and the engine settings, all keyed by the scenario file and workload label."""
    pool = dep["pools"][0]
    eng, par = pool["engine"], pool["parallel"]
    if "speculative" in eng and "acceptance" not in (dep.get("_scenario") or {}):
        # signedprobe passes no acceptance flag to blis replay: a drafter is priced only when
        # the scenario pins its acceptance.
        return ["client_scenario_not_replayable:single_turn_speculative"]
    m = row.get("metrics") or {}
    try:
        ttft_us, tpot_us = float(m["mean_ttft"]) * 1e6, float(m["mean_tpot"]) * 1e6
    except (KeyError, TypeError, ValueError):
        return ["required_setting_missing:measured.mean_ttft_or_tpot"]
    isl, osl, conc = int(row["isl"]), int(row["osl"]), int(row["conc"])
    label = _single_turn_label(isl, osl)
    ep = par["tp"] * par["dp"] if par.get("enable_expert_parallel") else 1
    sweep = {"scenario": scenario_file, "model": dep.get("_model", ""), "gpu": row["hardware"],
             "workload": f"{isl}:{osl}", "label": label, "framework": "vllm", "precision": row["precision"],
             "serving": "aggregated", "spec_method": "none",
             "parallelism": {"tp": par["tp"], "pp": par["pp"], "dp": par["dp"], "ep": ep},
             "points": [{"concurrency": conc}]}
    corpus = {"source": "orchestrator/ingest (one InferenceX API row)", "measurement_source": "InferenceX API",
              "sweeps": [sweep]}
    absolutes = {"source": "InferenceX API", "anchors": [
        {"scenario": scenario_file, "label": label, "framework": "vllm", "gpu": row["hardware"],
         "absolute_tpot_us": {str(conc): round(tpot_us, 3)}, "absolute_ttft_us": {str(conc): round(ttft_us, 3)}}]}
    passed = {k: eng[f] for k, f in _PROBE_FIELDS if f in eng}
    # vLLM v0.31.0 caches prefixes unless told not to; stated so signedprobe never decides it.
    passed.setdefault("enable_prefix_caching", True)
    passed["enable_expert_parallel"] = bool(par.get("enable_expert_parallel"))
    settings = {"source": "orchestrator/ingest (the run's server log)", "settings": [
        {"scenario": scenario_file, "label": label, "framework": "vllm", "gpu": row["hardware"],
         "by_concurrency": {str(conc): {"passed": passed, "resolved": {}}}}]}
    return corpus, absolutes, settings


def score_single_turn(o, entry, env, work: Path, sdir: Path, name: str, text: str, dep: dict,
                      args: list, log: str, approximated: bool):
    """One single-turn point through signedprobe (inference-sim cmd/signedprobe at the BLIS tag)."""
    row, pid, ident = entry["row"], entry["point_id"], entry["identity"]
    scen_doc = next((d for d in __import__("yaml").safe_load_all(text) if d.get("kind") == "Scenario"), {})
    dep = {**dep, "_model": scen_doc.get("model", ""), "_scenario": scen_doc}
    got = single_turn_inputs(row, dep, f"{name}.yaml")
    if isinstance(got, list):
        o.reasons = sorted(set(got))
        return o
    corpus, absolutes, settings = got
    pdir = work / "single_turn" / pid
    pdir.mkdir(parents=True, exist_ok=True)
    files = {}
    for role, doc in (("corpus", corpus), ("absolutes", absolutes), ("settings", settings)):
        files[role] = pdir / f"{role}.json"
        files[role].write_text(contract.canonical_dumps(doc) + "\n")
    argv = [env.signedprobe, "-blis", env.blis, "-corpus", str(files["corpus"]), "-scenarios", str(sdir),
            "-absolutes", str(files["absolutes"]), "-engine-settings", str(files["settings"]),
            "-catalog", str(env.catalog), "-registry", str(env.registry)]
    out_path = pdir / "signedprobe.csv"
    key = hashlib.sha256((text + "".join(files[r].read_text() for r in sorted(files)) + "\0".join(argv[1:])).encode()).hexdigest()
    key_path = pdir / "signedprobe.key"
    if not (out_path.exists() and key_path.exists() and key_path.read_text() == key):
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=env.timeout_s)
        except subprocess.TimeoutExpired:
            o.reasons = ["blis_refused:timeout"]
            return o
        (pdir / "signedprobe.err").write_text(proc.stderr[-20000:])
        if proc.returncode != 0:
            o.reasons = [_blis_refusal(_probe_error(proc.stderr), work)]
            return o
        out_path.write_text(proc.stdout)
        key_path.write_text(key)
    import csv as _csv
    rows = list(_csv.DictReader(out_path.read_text().splitlines()))
    if len(rows) != 1:
        o.reasons = ["blis_refused:metrics_incomplete"]
        return o
    pr = rows[0]
    status = point_status(approximated, entry["build"])
    o.fidelity = {"status": status, "build": entry["build"], "args": args, "resolved": [],
                  "blis_kernel_provenance": None}
    pool = dep["pools"][0]
    par = pool["parallel"]
    ep = (par["tp"] * par["dp"]) if par.get("enable_expert_parallel") else 1
    label = corpus["sweeps"][0]["label"]
    scen = f"{dep['_model']}-{row['hardware']}-{row['precision']}-vllm-tp{par['tp']}-dp{par['dp']}-ep{ep}"
    o.facets = {"identity": ident, "sweep_id": sweep_id(row, scen, label),
                "scenario": scen, "label": label, "workload": corpus["sweeps"][0]["workload"],
                "model": dep["_model"], "gpu": row["hardware"], "precision": row["precision"], "framework": "vllm",
                "serving": "aggregated", "spec_method": row.get("spec_method") or "none",
                "parallelism": {"tp": par["tp"], "pp": par["pp"], "dp": par["dp"], "ep": ep},
                "image": row.get("image"), "vllm_version": _banner_version(log)}
    o.csv_row = [scen, dep["_model"], row["hardware"], label, ident["conc"],
                 float(pr["meas_tpot_us"]), float(pr["pred_tpot_us"]),
                 float(pr["meas_ttft_us"]), float(pr["pred_ttft_us"]),
                 contract.TIER_BY_STATUS[status], pid, ident["measured_date"]]
    return o


def _helper_failure(ex: Exception) -> str:
    return "blis_refused:timeout" if isinstance(ex, subprocess.TimeoutExpired) else "blis_refused:defaults_helper_failed"


def _probe_error(stderr: str) -> str:
    """signedprobe's own failure line (first run error / no latency), else its last line."""
    for line in stderr.splitlines():
        if line.startswith("first run error") or line.startswith("no latency observed"):
            return line.split(": ", 1)[-1]
    return stderr


def _estimated(args: list) -> bool:
    """Whether BLIS estimated any setting, from the final per-setting records (an estimate that
    turned out to change nothing, e.g. an indexer setting on a model with no indexer, is inert)."""
    return any(a.get("match") == "approximated" for a in args)


def point_status(approximated: bool, build: dict) -> str:
    """exact only when BLIS was given every setting as the run recorded it AND the run's build is
    the one BLIS models; otherwise approximate (shown as "estimated"). A build never refuses."""
    return "approximate" if approximated or build.get("match") != "exact" else "exact"


def row_vs_run(row: dict, c: st.Classified) -> list[str]:
    """The API row's summary fields must agree with what the run's own logs say; the logs
    are what's scored, and a disagreement means the row and the artifacts aren't the same run."""
    out = []
    spec = c.mapped.get("engine.speculative.method", (None, None, None))[1]
    row_spec = row.get("spec_method")
    if row_spec and (row_spec == "none") != (spec is None):
        out.append("conflict:spec_method")
    offload = c.mapped.get("offload.connector", (None, None, None))[1]
    row_off = row.get("offload_mode")
    if row_off in ("on", "off") and (row_off == "on") != (offload is not None):
        out.append("conflict:offload_mode")
    if not row.get("disagg"):
        out += _row_topology_vs_run(row, c)
    return out


def _row_topology_vs_run(row: dict, c: st.Classified) -> list[str]:
    """The row's parallel layout against the one the run's log states.

    InferenceX records a single-node point's layout in its own terms, which differ from vLLM's
    in two known ways: with DP attention its "tp" is the attention width tp x dp (vLLM logs
    tp=1, dp=8 for its "TP 8, DP attention"); and some rows count expert-parallel ranks on top
    of tensor-parallel ones in num_decode_gpu (tp x ep), though EP shares the TP GPUs (its own
    results/topology.py counts tp x pp x pcp). Either spelling of the same GPUs agrees; a row
    whose width or GPU count matches neither describes a different run."""
    def logged(field, default=1):
        v = c.mapped.get(field, (None, None, None))[1]
        return int(v) if v is not None else default
    tp, dp, pp, pcp = logged("parallel.tp", 0), logged("parallel.dp"), logged("parallel.pp"), logged("parallel.pcp")
    if not tp:
        return []
    world = tp * dp * pp * pcp
    out = []
    row_tp, row_ep = row.get("decode_tp"), row.get("decode_ep")
    if row_tp and int(row_tp) not in ({tp, tp * dp} if row.get("decode_dp_attention") else {tp}):
        out.append("conflict:tp")
    gpus = row.get("num_decode_gpu")
    if gpus and int(gpus) != world and not (row_tp and row_ep and int(gpus) == int(row_tp) * int(row_ep)
                                             and int(row_tp) * pp * pcp == world):
        out.append("conflict:num_gpus")
    return sorted(out)


def _banner_version(log: str) -> str | None:
    m = re.search(r"V1 LLM engine \(v([0-9][0-9A-Za-z.+]*)\)", log)
    return m.group(1) if m else None


def split_repeated_sweeps(scored: list[Outcome]) -> None:
    """A sweep holds one point per concurrency (CONTRACT.md). If two rows of one curve ever share
    a concurrency, which point belongs with which can't be told, so each point of that sweep
    becomes its own sweep: their errors are scored, their trend isn't. Never seen in the API so
    far; this keeps a future row shape from failing the whole contract."""
    by: dict = {}
    for o in scored:
        by.setdefault(o.facets["sweep_id"], []).append(o)
    for sid, os_ in by.items():
        concs = [o.identity["conc"] for o in os_]
        if len(concs) != len(set(concs)):
            for o in os_:
                o.facets["sweep_id"] = f"{sid}|{o.identity['recipe']}"


def write_contract(out: Path, outcomes: list[Outcome], provenance: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    scored = [o for o in outcomes if o.fidelity is not None]
    split_repeated_sweeps(scored)
    rows = sorted((o.csv_row for o in scored),
                  key=lambda r: contract.points_sort_key(dict(zip(contract.POINTS_HEADER, map(str, r)))))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(contract.POINTS_HEADER)
    w.writerows(rows)
    (out / contract.POINTS_CSV).write_text(buf.getvalue())
    fid = sorted(({"point_id": o.point_id, **o.fidelity} for o in scored), key=lambda r: r["point_id"])
    (out / contract.FIDELITY_JSONL).write_text("".join(contract.canonical_dumps(r) + "\n" for r in fid))
    (out / contract.FACETS_JSON).write_text(contract.canonical_dumps({o.point_id: o.facets for o in scored}) + "\n")
    ns = []
    policy = provenance.get("_policy") or {}
    for o in outcomes:
        if o.fidelity is not None:
            continue
        m = o.row.get("metrics") or {}
        reasons = sorted(set(o.reasons)) or ["blis_refused"]
        rec = {"point_id": o.point_id, "identity": o.identity, "measured_date": o.identity["measured_date"],
               "model": o.row["model"], "hardware": o.row["hardware"], "precision": o.row["precision"],
               "framework": o.row["framework"], "benchmark_type": o.row["benchmark_type"],
               "conc": o.identity["conc"], "image": o.row.get("image"),
               "measured": {"ttft_ms": _ms(m.get("mean_ttft")), "tpot_ms": _ms(m.get("mean_tpot"))},
               "reasons": reasons}
        n = [{"reason": x, **nt} for x in reasons if (nt := note_for(policy, x))]
        if n:
            rec["notes"] = n
        ns.append(rec)
    ns.sort(key=lambda r: r["point_id"])
    (out / contract.NOT_SCORED_JSONL).write_text("".join(contract.canonical_dumps(r) + "\n" for r in ns))
    prov = {k: v for k, v in provenance.items() if not k.startswith("_")}
    (out / contract.PROVENANCE_JSON).write_text(contract.canonical_dumps(prov) + "\n")


def _ms(seconds):
    return None if seconds is None else round(float(seconds) * 1e3, 6)


def note_for(policy: dict, reason: str) -> dict | None:
    """The policy's fixed note for a setting_not_modelled:<path> reason, if it has one."""
    code, _, path = reason.partition(":")
    if code != "setting_not_modelled" or not policy:
        return None
    hit = st.lookup(policy, path)
    if not hit or not hit[1].get("note"):
        return None
    return {"text": hit[1]["note"]}
