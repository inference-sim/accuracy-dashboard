"""Stage 2: score a frozen pull with one BLIS release and write the contract directory
(orchestrator/ingest/CONTRACT.md).

Per point: settings (settings.py) -> support (support.py) -> replay inputs (replay.py, agentic)
-> the scenario file -> `blis replay --agentic-scenario` -> the diff of what BLIS was given
against what the run recorded -> one fidelity record, or a not-scored record with reasons.

Single-turn points go through the same extraction; their scoring (signedprobe) is not wired
here yet, so they're recorded not scored with blis_refused:single_turn_scorer_pending.
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
    c = st.classify(st.merge(readings, env.policy, env.vllm_defaults), env.policy, env.vllm_defaults)
    o.reasons += c.reasons
    o.reasons += row_vs_run(row, c)

    cat = env.catalog_obj
    spec = c.mapped.get("engine.speculative.method", (None, None, None))[1]
    sup = sp.check(cat, env.parts, checkpoints=_checkpoints(c, launch), base_models=env.base_models,
                   hardware=row["hardware"], spec_method=spec)
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
        o.reasons.append("blis_refused:single_turn_scorer_pending")

    if sup.model is None or row["hardware"] not in cat.hardware:
        o.reasons = sorted(set(o.reasons))
        return o
    part = st.Part(name=row["hardware"], memory_gib=cat.hardware[row["hardware"]])
    defaults = st.blis_defaults(env.defaults_helper, part)
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
    o.reasons += fill_blis_side(args, env, sdir, f"{name}.yaml", sup.model)
    o.reasons += _diff_args(args, dep, b)
    args.sort(key=lambda a: a["arg"])
    o.reasons = sorted(set(o.reasons))
    if o.reasons:
        return o

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
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=env.timeout_s)
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
    status = "approximate" if c.approximated else "exact"
    o.fidelity = {"status": status, "build": entry["build"], "args": args,
                  "resolved": resolved_kv(log, metrics), "replay": r.record(env.corpus["sha256"]),
                  "blis_kernel_provenance": metrics.get("kernel_provenance")}
    par = dep["pools"][0]["parallel"]
    ep = (par["tp"] * par["dp"]) if par.get("enable_expert_parallel") else 1
    scen = f"{sup.model}-{row['hardware']}-{row['precision']}-vllm-tp{par['tp']}-dp{par['dp']}-ep{ep}-agentx"
    o.facets = {"identity": ident, "sweep_id": f"{row.get('curve_workflow_run_id')}|{scen}|{AGENTIC_LABEL}",
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
                         capture_output=True, text=True)
    if out.returncode != 0:
        return _blis_refusal(out.stderr.replace("blisdefaults: ", ""), scenarios.parent)
    return json.loads(out.stdout)


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
            field = src.split(".", 1)[1]
            hit = [o for o in res["overrides"] if o["field"] == field]
            a["blis"] = hit[0]["resolved"] if hit else None
        elif src == "graph.index_cache":
            a["blis"] = env.catalog_obj.index_caches.get(model)
        if a["blis"] is None:
            reasons.append(f"setting_differs:{a['arg']}")
    return reasons


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
    tp = c.mapped.get("parallel.tp", (None, None, None))[1]
    dp = c.mapped.get("parallel.dp", (None, None, None))[1] or 1
    gpus = row.get("num_decode_gpu")
    if tp and gpus and not row.get("disagg") and int(gpus) != int(tp) * int(dp):
        out.append("conflict:num_gpus")
    return out


def _banner_version(log: str) -> str | None:
    m = re.search(r"V1 LLM engine \(v([0-9][0-9A-Za-z.+]*)\)", log)
    return m.group(1) if m else None


def write_contract(out: Path, outcomes: list[Outcome], provenance: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    scored = [o for o in outcomes if o.fidelity is not None]
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
