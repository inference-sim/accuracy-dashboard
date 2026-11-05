"""Stage 2: score a frozen pull with one BLIS release and write the contract directory
(orchestrator/ingest/CONTRACT.md).

Per point: settings (settings.py) -> support (support.py) -> replay inputs (replay.py, agentic)
-> the scenario file -> `blis replay --agentic-scenario` -> the diff of what BLIS was given
against what the run recorded -> the point's grade (grade_outcome): a fidelity record graded G1
to G4, a G5 record with its reasons, or a failed record with its run faults.

Single-turn points go through the same extraction and are replayed as the run's client sent
them (inferencex_client, COV-12) by `blis replay` (score_single_turn). Every run's Result is read
from blis's standard output and validated (result.py).
"""
from __future__ import annotations

import csv
import dataclasses
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
import assess as asx  # noqa: E402
import contract  # noqa: E402
import fields as fl  # noqa: E402
import grade as gr  # noqa: E402
import inferencex_client as ix  # noqa: E402
import replay as rp  # noqa: E402
import result  # noqa: E402
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
    """What scoring runs against: one BLIS release and its pinned repos. blis is the path of
    the blis binary; it runs with its working directory set to the binary's directory."""
    blis: str
    blis_release: str
    blis_commit: str
    catalog: Path
    catalog_release: str
    registry: Path
    registry_release: str
    kernel: str
    corpus: dict          # {"dataset", "revision", "sha256", "path", "file"}
    corpus_cache: Path | None = None
    vllm_ref: str = "v0.32.0"
    # The engine's field list (fields.py) at the release the simulator runs, and its sha256.
    field_list: object = None
    fields_sha256: str = ""
    base_models: dict = field(default_factory=dict)   # HF repo -> base_model (frozen)
    timeout_s: int = 7200
    # vLLM's own defaults for the fields of the config objects its log prints whole
    # (vllm_defaults.json), so a field printed at its default is not taken as set by the run.
    vllm_defaults: dict = field(default_factory=dict)
    # The vLLM release the table was read at; it applies only to a run of that release.
    vllm_defaults_release: str = ""
    # The engine release the scoring simulator runs (stack.json, LIF-6), e.g. "0.32.0".
    engine_release: str = ""
    # The simulator build that scores the run: a release tag, or a commit (pointrecord Simulator).
    sim_build: str = ""
    # The harness image digest every point records (design §11.7, X8): sha256:<hex>, or unreleased.
    harness_digest: str = "unreleased"
    catalog_obj: sp.Catalog | None = None
    parts: set = field(default_factory=set)
    # A per-replay resident-memory ceiling in MB (0 = none). An agentic replay whose RSS exceeds
    # it is killed individually and the point is not-scored with an insufficient_memory reason, so
    # one memory-heavy trace can't OOM the whole CI job. Peak RAM is trace-content-driven and
    # unpredictable per point (profiled: a c64 point used 11.5GB where a c128 used 6.9GB), so a
    # reactive RSS cap is the only reliable bound on a fixed-RAM runner; 0 locally scores everything.
    max_rss_mb: int = 0

    def simulator(self) -> dict:
        """The simulator block every point of this run records: its build and engine release."""
        return {"build": self.sim_build, "engine": {"kind": "vllm", "version": self.engine_release},
                "harness_digest": self.harness_digest}


def _read(point_dir: Path, files: dict, role: str) -> bytes | None:
    f = files.get(role)
    if not f:
        return None
    return gzip.decompress((point_dir / f["path"]).read_bytes())


def _checkpoints(c: st.Decided, launch_cfg: dict | None) -> list[str]:
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


def measured(entry: dict) -> dict:
    """The point's measured values: the mean, over the unit's measurements, of each metric
    (design §10.2: a unit holding several measurements is scored against their mean, COV-10).
    A metric a measurement lacks is left out of that metric's mean; a metric no measurement
    has is absent."""
    ms = entry.get("measurements") or [{"metrics": entry["row"].get("metrics") or {}}]
    out = {}
    for key in sorted({k for m in ms for k in (m.get("metrics") or {})}):
        vals = [(m["metrics"] or {}).get(key) for m in ms]
        vals = [float(v) for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if vals:
            out[key] = sum(vals) / len(vals)
    return out


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


_STATES_NO = re.compile(r"\bstates no ([A-Za-z_][A-Za-z0-9_.]*)")


def value_refusal(stderr: str, work: Path, field_list) -> str | None:
    """The G5 reason for an engine refusal that says the scenario lacks a value ("states no
    <field>"), else None. The field is parsed from the refusal's text. The field's estimation rule
    (fields.estimate_missing) is applied to it: the engine has already refused to resolve it, so
    a rule that would leave it unset or substitute another setting cannot help here, and the
    reason is value_not_recorded in every case (design 11.4). A refusal that says "states no"
    but names no parseable field takes the refusal's slug as the subject."""
    slug = _blis_refusal(stderr, work)
    text = slug.partition(":")[2]
    if "states_no" not in text and "states no" not in stderr:
        return None
    m = _STATES_NO.search(re.sub(r"\s+", " ", stderr))
    name = m.group(1) if m else None
    if name is None:
        return f"required_setting_missing:{text}"
    if field_list is not None:
        dec = fl.estimate_missing(field_list, name)
        if dec.g5 and dec.g5["code"] != "value_not_recorded":
            return f"{dec.g5['code']}:{name}"
    return f"required_setting_missing:{name}"


class MemoryExceeded(Exception):
    """A capped subprocess's RSS exceeded the ceiling and it was killed."""


def _rss_mb(pid: int) -> float:
    """Resident memory (MB) of a process and its children. Go reserves huge VIRTUAL address space,
    so only RSS is meaningful -- an RLIMIT_AS cap would kill blis on startup. Reads /proc on Linux
    (the CI runner); falls back to `ps` elsewhere (local macOS). Best-effort: returns 0 if unknown."""
    import os
    total = 0.0
    try:
        # Linux: sum this pid + descendants from /proc/*/statm (field 2 = resident pages).
        pagesize = os.sysconf("SC_PAGE_SIZE")
        pids = _proc_tree(pid)
        for p in pids:
            try:
                with open(f"/proc/{p}/statm") as fh:
                    total += int(fh.read().split()[1]) * pagesize
            except (OSError, ValueError, IndexError):
                pass
        if total:
            return total / 1024 / 1024
    except (OSError, ValueError, AttributeError):
        pass
    # Fallback (macOS/local): ps rss is in KB, for the single pid.
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
        return int(out.stdout.strip() or 0) / 1024
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def _proc_tree(root: int) -> list:
    """`root` and all its descendant pids (Linux /proc). Just [root] if the tree can't be read."""
    import os
    children: dict = {}
    try:
        for p in os.listdir("/proc"):
            if not p.isdigit():
                continue
            try:
                with open(f"/proc/{p}/stat") as fh:
                    ppid = int(fh.read().split()[3])
                children.setdefault(ppid, []).append(int(p))
            except (OSError, ValueError, IndexError):
                pass
    except OSError:
        return [root]
    out, stack = [], [root]
    while stack:
        cur = stack.pop()
        out.append(cur)
        stack.extend(children.get(cur, []))
    return out


def run_capped(argv, *, timeout, max_rss_mb=0, poll_s=2, cwd=None):
    """subprocess.run(capture_output, text) with an optional RSS ceiling. If max_rss_mb > 0 and the
    process tree's resident memory exceeds it, the process is killed and MemoryExceeded is raised --
    so one memory-heavy replay is killed alone, never taking down the whole job. With max_rss_mb==0
    this is a plain subprocess.run (local / big-runner scores everything)."""
    if not max_rss_mb:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd)
    start = 0.0
    while True:
        try:
            out, err = proc.communicate(timeout=poll_s)
            return subprocess.CompletedProcess(argv, proc.returncode, out, err)
        except subprocess.TimeoutExpired:
            pass
        if _rss_mb(proc.pid) > max_rss_mb:
            proc.kill()
            proc.communicate()
            raise MemoryExceeded(f"replay RSS exceeded {max_rss_mb} MB")
        start += poll_s
        if start >= timeout:
            proc.kill()
            proc.communicate()
            raise subprocess.TimeoutExpired(argv, timeout)


def resolved_kv(log: str, doc: dict | None) -> list[dict]:
    """The KV pool vLLM allocated vs BLIS's, per engine core, BLIS's from the engine's report in
    the Result (kv_capacity_tokens_per_replica). Never passed to BLIS."""
    found = [int(x.replace(",", "")) for x in re.findall(r"GPU KV cache size: ([0-9,]+) tokens", log)]
    if not found:
        return []
    rec = {"quantity": "kv_cache_tokens_per_replica"}
    if len(set(found)) > 1:
        return [{**rec, "measured": None, "blis": None, "match": "conflict"}]
    rec["measured"] = found[0]
    if len(found) > 1:
        rec["occurrences"] = len(found)
    blis = result.engine_report(doc or {}, "kv_capacity_tokens_per_replica")
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


def _blis_value(dep: dict, loc: str):
    """The value at a scenario location in the Deployment as written."""
    if loc == "offload.tiers.cpu_dram":
        tiers = (dep.get("offload") or {}).get("tiers") or []
        return next((t["bytes"] for t in tiers if t.get("tier") == "cpu_dram"), None)
    if loc.startswith("offload."):
        return _get(dep, loc)
    if loc.startswith("engine.env."):
        return ((dep["pools"][0].get("engine") or {}).get("env") or {}).get(loc[len("engine.env."):])
    return _get(dep["pools"][0], loc)


def _diff_args(args: list, dep: dict, b: st.Built) -> list[str]:
    """Fill each copied arg's `blis` from the scenario as WRITTEN (parsed back), and its match:
    exact when the scenario carries the recorded value under the upstream's own name, mapped when
    under the engine block's renamed field (blis_field names it), differs or absent_in_blis
    otherwise (a fault: the writer lost a recorded value, COV-3)."""
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
            elif f.startswith("engine.env."):
                want = str(want)
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
    measurements: list = field(default_factory=list)
    fidelity: dict | None = None
    facets: dict | None = None
    csv_row: list | None = None
    banner: str | None = None       # the vLLM version the server log's banner prints
    build: dict | None = None       # the run's recorded build (build.py), from the pull
    # The substitutions the field list names (an estimate, an interim status), from settings.
    subs: list = field(default_factory=list)
    # Set by grade_outcome: the run's own engine release (None for a nightly or custom build);
    # for a G5 point its reason and every reason found; for a failed point its run faults.
    run_release: str | None = None
    simulator: dict | None = None   # {"build", "engine": {"kind", "version"}, "harness_digest"}
    g5: dict | None = None
    g5_reasons: list = field(default_factory=list)
    faults: list = field(default_factory=list)


def _score_one(entry: dict, pull_dir: Path, work: Path, env: Env) -> Outcome:
    """score_point with the uniform error capture the driver used to do inline, so both the serial
    and the parallel path record a point that raises as not-scored (never drop it)."""
    try:
        o = score_point(entry, pull_dir, work, env)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        o = Outcome(point_id=entry["point_id"], identity=entry["identity"], row=entry["row"],
                    reasons=sorted(set(entry["reasons"] + ["blis_refused:extractor_error"])),
                    measurements=entry.get("measurements") or [], build=entry.get("build"))
    grade_outcome(o, env.engine_release, env.simulator())
    return o


# A process-pool worker scores into its OWN work subdir, because score_point writes
# work/scenarios/<scenario>.yaml keyed by scenario name, not point id -- two points that share a
# scenario name would race that file across processes. Per-worker dirs isolate it; the per-point
# results/<pid>.json cache stays correct either way (pid is unique). The worker's env and pull_dir
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
      * single-turn (no corpus): light RAM, safe to run `workers`-wide.
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
            f"{e['point_id'][:12]} -> {o.fidelity['grade'] if o.fidelity else o.faults or o.reasons}")

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
    # blis runs in its binary's directory, so every path it is given is absolute.
    work = work.resolve()
    o = Outcome(point_id=pid, identity=ident, row=row, reasons=list(entry["reasons"]),
                measurements=entry.get("measurements") or [], build=entry.get("build"))
    o.reasons += asx.engine_reason(row, ENGINES)
    pdir = pull_dir / "points" / pid
    log_b = _read(pdir, entry["files"], "server_log")
    if log_b is None:
        # The pull may already have said why (the API answered 413): that reason stands alone.
        bare = [] if "server_log_missing:api_413" in o.reasons else ["server_log_missing"]
        o.reasons = sorted(set(o.reasons + bare + asx.router_reason(row, None)))
        return o
    log = log_b.decode("utf-8", "replace")
    o.banner = _banner_version(log)
    lc_b = _read(pdir, entry["files"], "launch_config")
    launch = json.loads(lc_b) if lc_b else None
    # A run measured behind a router BLIS does not host is never scored as if llm-d had routed
    # it (design §11.4, X4; inference-sim #2028), so BLIS is not asked about it.
    o.reasons += asx.router_reason(row, _launch_router(launch))

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
    defaults = st.defaults_for(o.banner, env.vllm_defaults, env.vllm_defaults_release)
    c = st.decide(st.merge(readings, defaults), env.field_list)
    o.reasons += c.reasons
    o.subs = list(c.substitutions)
    o.reasons += row_vs_run(row, c)

    cat = env.catalog_obj
    spec = c.mapped.get("engine.speculative.method", (None, None))[1]
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
        for k in ("isl", "osl", "conc"):
            v = row.get(k)
            if not isinstance(v, int) or isinstance(v, bool) or v < 1:
                o.reasons.append(f"required_setting_missing:replay.{k}")

    if sup.model is None or part_name not in cat.hardware:
        o.reasons = sorted(set(o.reasons))
        return o
    part = st.Part(name=part_name)
    name = f"p-{pid[:16]}"
    b = st.build(c, name=name, model=sup.model, part=part, engine_version=env.engine_release,
                 field_list=env.field_list)
    o.reasons += b.reasons
    o.subs += b.substitutions
    header = [f"point {pid}", f"InferenceX row {row['id']} ({row['run_url']})",
              "GENERATED by orchestrator/ingest/score.py from the run's own settings. Do not edit."]
    spec = b.deployment["pools"][0]["engine"].get("speculative") or {}
    if b.acceptance_length is not None and spec.get("num_spec_tokens"):
        # The run's own synthetic acceptance, pinned in the scenario so every replay runs it: the
        # agentic one (which also takes --speculative-acceptance-length) and the single-turn one
        # (which passes no flag).
        b.scenario["acceptance"] = {"value": {"num_spec_tokens": int(spec["num_spec_tokens"]),
                                              "acceptance_length": float(b.acceptance_length)}}
    text = st.to_yaml(b, header)
    sdir = work / "scenarios"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / f"{name}.yaml").write_text(text)
    dep = _parse_back(text)
    args = c.args
    if o.reasons:
        # Already not scored. BLIS is asked only about a point nothing else refused: its
        # verdict on a known gap (e.g. a drafter the catalog doesn't describe) would restate
        # that gap as a second reason and count the point twice.
        o.reasons = sorted(set(o.reasons))
        return o
    o.reasons += _diff_args(args, dep, b)
    args.sort(key=lambda a: a["arg"])
    o.reasons = sorted(set(o.reasons))
    if o.reasons:
        return o

    if not agentic:
        return score_single_turn(o, entry, env, work, b, header, name, dep, args, log, sup)

    # ---- the replay
    spec_doc = rp.workload_spec(r, env.corpus["sha256"], env.corpus["revision"], env.corpus["file"])
    spec_path = work / "workloads" / f"{pid}.yaml"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    import yaml
    spec_path.write_text(yaml.safe_dump({"replay": spec_doc}, sort_keys=False))
    argv = [env.blis, "replay", "--agentic-scenario", r.replayed_as,
            "--workload-spec", str(spec_path), "--concurrency", str(r.concurrency),
            "--seed", str(r.seed), "--corpus", env.corpus["path"], "--corpus-sha256", env.corpus["sha256"],
            "--scenario", f"{name}.yaml", "--scenarios", str(sdir),
            "--catalog", str(env.catalog), "--registry", str(env.registry), "--format", "json"]
    if b.acceptance_length is not None:
        argv += ["--speculative-acceptance-length", b.acceptance_length]
    if env.corpus_cache:
        argv += ["--corpus-cache", str(env.corpus_cache)]
    # The cached Result is reused only for the exact same inputs: scenario, workload, argv.
    key = hashlib.sha256((text + spec_path.read_text() + "\0".join(argv[1:])).encode()).hexdigest()
    doc = _run_result(o, argv, key, work / "results" / f"{pid}.json", env, work,
                      runner=lambda a, timeout, cwd: run_capped(a, timeout=timeout, max_rss_mb=env.max_rss_mb,
                                                                cwd=cwd))
    if doc is None:
        return o
    try:
        pttft, ptpot = (result.figure(doc, result.TTFT_MEAN_MS) * 1e3, result.figure(doc, result.TPOT_MEAN_MS) * 1e3)
    except result.ResultError as e:
        o.reasons = [f"blis_refused:{e.slug}"]
        return o

    try:
        o.subs += result.coefficient_substitutions(doc)
    except result.ResultError as e:
        o.reasons = [f"blis_refused:{e.slug}"]
        return o
    m = measured(entry)
    o.fidelity = {"build": entry["build"], "args": args,
                  "resolved": resolved_kv(log, doc), "replay": r.record(env.corpus["sha256"]),
                  "blis_kernel_provenance": result.kernel_report(doc)}
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
                 None, pid, ident["measured_date"]]     # the grade column is filled by grade_outcome
    return o


# The engines a BLIS engine repository models (design §11.4, engine_unsupported).
ENGINES = {"vllm"}


def _launch_router(launch: dict | None) -> str | None:
    """The router a launch configuration's frontend names; vLLM's own API server is none."""
    fe = (launch or {}).get("frontend") if isinstance(launch, dict) else None
    t = fe.get("type") if isinstance(fe, dict) else None
    return None if t in (None, "vllm") else str(t)


def _single_turn_label(isl: int, osl: int) -> str:
    k = lambda n: f"{n // 1024}k" if n % 1024 == 0 else str(n)
    return f"{k(isl)}{k(osl)}"


# The scenario seed every single-turn replay runs with (the old harness's Config.Seed). The
# requests are the client's own (inferencex_client), so the seed draws only what they leave
# open, such as a router's tie-breaks (COV-10).
SINGLE_TURN_SEED = 42


def _run_result(o: Outcome, argv: list[str], key: str, cache: Path, env: Env, work: Path,
                runner=None) -> dict | None:
    """The Result of one `blis replay`, read from its standard output and validated
    (result.run), or None with the point's refusal set on `o`. blis runs in its binary's
    directory. The validated document is cached at `cache` and reused only for the same `key`,
    a hash of every input the run reads."""
    key_path = cache.with_suffix(".key")
    if cache.exists() and key_path.exists() and key_path.read_text() == key:
        return json.loads(cache.read_text())
    cache.unlink(missing_ok=True)
    logs = work / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    try:
        doc, raw, stderr = result.run(argv, blis=env.blis, cwd=str(Path(env.blis).parent), timeout=env.timeout_s,
                                      runner=runner)
    except subprocess.TimeoutExpired:
        o.reasons = ["blis_refused:timeout"]
        return None
    except MemoryExceeded:
        # This replay's resident memory exceeded the runner's ceiling; it is killed alone and
        # the point is not scored, so one heavy trace cannot OOM the whole job. This is a
        # runner-capacity limit, not a fidelity choice, so a larger-RAM run can score it later.
        o.reasons = ["blis_refused:insufficient_memory"]
        return None
    except result.RunFailed as e:
        (logs / f"{o.point_id}.err").write_text(e.stderr[-20000:])
        o.reasons = [value_refusal(e.stderr, work, env.field_list) or _blis_refusal(e.stderr, work)]
        return None
    except result.ResultError as e:
        (logs / f"{o.point_id}.err").write_text(str(e)[-20000:])
        o.reasons = [f"blis_refused:{e.slug}"]
        return None
    (logs / f"{o.point_id}.err").write_text(stderr[-20000:])
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(raw)
    key_path.write_text(key)
    return doc


def score_single_turn(o: Outcome, entry: dict, env: Env, work: Path, b: st.Built, header: list[str],
                      name: str, dep: dict, args: list, log: str, sup: sp.Support) -> Outcome:
    """One single-turn point, replayed as the run's client sent it (COV-12).

    The requests are the client's seed-0 draws for the row's (isl, osl, conc)
    (inferencex_client.target_lengths). Where the scenario's engine states
    enable_prefix_caching false, the warm-up leaves nothing the main phase reads, so the main
    phase runs from an empty engine. Otherwise it runs primed: request 0's prompt cached on each
    of the deployment's dp replicas by dp warm-up copies, as the client's drained warm-up leaves
    it. The scenario gains the router block of every single-turn point (vLLM's data-parallel
    balancer, which places by requests in flight), written beside it. The predicted means are
    the client's own, computed from the Result's request rows (inferencex_client.summarize);
    the fidelity record's `requests` names how the requests were replayed and every difference
    from the run's client."""
    row, pid, ident = entry["row"], entry["point_id"], entry["identity"]
    model = b.scenario["model"]
    pool = dep["pools"][0]
    eng, par = pool["engine"], pool["parallel"]
    if "speculative" in eng and "acceptance" not in b.scenario:
        # The replay passes no acceptance flag: a drafter is priced only when the scenario pins
        # its acceptance.
        o.reasons = ["client_scenario_not_replayable:single_turn_speculative"]
        return o
    m = measured(entry)
    try:
        meas_ttft_us, meas_tpot_us = float(m["mean_ttft"]) * 1e6, float(m["mean_tpot"]) * 1e6
    except (KeyError, TypeError, ValueError):
        o.reasons = ["required_setting_missing:measured.mean_ttft_or_tpot"]
        return o
    isl, osl, conc = int(row["isl"]), int(row["osl"]), int(row["conc"])
    ins, outs = ix.target_lengths(isl, osl, conc)
    primed = eng.get("enable_prefix_caching") is not False
    copies = max(int(par.get("dp") or 1), 1) if primed else 0
    replay = ix.primed_phase(ins, outs, conc, copies) if primed else ix.main_phase(ins, outs, conc)

    pdir = (work / "single_turn" / pid).resolve()
    pdir.mkdir(parents=True, exist_ok=True)
    routed = dataclasses.replace(b, deployment={**b.deployment,
                                                "router": {"endpoint_picker_config": ix.ROUTER_CONFIG_NAME}})
    text = st.to_yaml(routed, header)
    (pdir / f"{name}.yaml").write_text(text)
    router = ix.router_config_bytes()
    (pdir / ix.ROUTER_CONFIG_NAME).write_bytes(router)
    header_path, data_path = ix.write_trace(replay, pdir)
    argv = ix.replay_argv(env.blis, f"{name}.yaml", pdir, header_path, data_path, replay.sessions, replay.pool,
                          SINGLE_TURN_SEED)
    if env.catalog:
        argv += ["--catalog", str(env.catalog)]
    if env.registry:
        argv += ["--registry", str(env.registry)]
    key = hashlib.sha256(b"\0".join([text.encode(), router, header_path.read_bytes(), data_path.read_bytes(),
                                      "\0".join(argv[1:]).encode()])).hexdigest()
    doc = _run_result(o, argv, key, pdir / "result.json", env, work)
    if doc is None:
        return o
    try:
        result.requests_complete(doc, len(replay.records))
        rows = result.rows(doc)
    except result.ResultError as e:
        o.reasons = [f"blis_refused:{e.slug}"]
        return o
    try:
        if primed:
            ix.check_primed(rows, len(ins))
    except ValueError:
        o.reasons = ["blis_refused:warmup_not_drained"]
        return o
    try:
        s = ix.summarize(rows, ins, outs, ignore=ix.main_phase_only(len(ins)) if primed else None)
    except ValueError:
        o.reasons = ["blis_refused:requests_not_the_points"]
        return o
    if s["mean_tpot_us"] is None:
        o.reasons = ["blis_refused:metrics_incomplete"]
        return o

    try:
        o.subs += result.coefficient_substitutions(doc)
    except result.ResultError as e:
        o.reasons = [f"blis_refused:{e.slug}"]
        return o
    verified, why = _prompt_lengths().verified(sup.checkpoint, row.get("date"), isl, osl, conc)
    differences = ix.client_differences(verified, why)
    o.fidelity = {"build": entry["build"], "args": args, "resolved": [],
                  "blis_kernel_provenance": result.kernel_report(doc),
                  "requests": {"client": ix.CLIENT_SUBJECT, "start": "primed" if primed else "cold",
                               "copies": copies, "count": len(ins), "differences": differences}}
    ep = (par["tp"] * par["dp"]) if par.get("enable_expert_parallel") else 1
    label = _single_turn_label(isl, osl)
    scen = f"{model}-{row['hardware']}-{row['precision']}-vllm-tp{par['tp']}-dp{par['dp']}-ep{ep}"
    o.facets = {"identity": ident, "sweep_id": sweep_id(row, scen, label),
                "scenario": scen, "label": label, "workload": f"{isl}:{osl}",
                "model": model, "gpu": row["hardware"], "precision": row["precision"], "framework": "vllm",
                "serving": "aggregated", "spec_method": row.get("spec_method") or "none",
                "parallelism": {"tp": par["tp"], "pp": par["pp"], "dp": par["dp"], "ep": ep},
                "image": row.get("image"), "vllm_version": _banner_version(log)}
    o.csv_row = [scen, model, row["hardware"], label, ident["conc"],
                 round(meas_tpot_us, 3), round(s["mean_tpot_us"], 3),
                 round(meas_ttft_us, 3), round(s["mean_ttft_us"], 3),
                 None, pid, ident["measured_date"]]     # the grade column is filled by grade_outcome
    return o


_EVIDENCE: list = []


def _prompt_lengths() -> ix.PromptLengthEvidence:
    """The sent-prompt-length evidence (inferencex_client.PROMPT_LENGTHS), loaded once per
    process."""
    if not _EVIDENCE:
        _EVIDENCE.append(ix.PromptLengthEvidence.load(ix.PROMPT_LENGTHS))
    return _EVIDENCE[0]


def substitutions(o_subs: list[dict], fidelity: dict) -> list[dict]:
    """Every G2 substitution a scored point names (design §11.3): each one its settings named
    (an estimation rule applied, a field with a status allowed only during a release plan), and
    each difference between the run's client and the simulated one (COV-12)."""
    return list(o_subs) + list((fidelity.get("requests") or {}).get("differences") or [])


def grade_outcome(o: Outcome, engine_release: str, simulator: dict | None = None) -> None:
    """Give one outcome its grade (design §11.3, §11.4; COV-4, COV-5), from data alone.

    A scored point is G1 to G4, its record naming every substitution, and its points.csv row
    carrying the grade. A point not scored is G5 with every reason found, each mapped onto
    §11.4's list (assess.g5_of; any other reason raises). A point carrying a run fault (the
    simulator refused the scenario, or the scenario lost a recorded value) is neither: it is
    listed as failed (o.faults), never graded. The run's own release is recorded on every point
    (§11.2), read from its recorded build and the server log's banner, and the simulator build and
    engine release that scored it (pointrecord's Simulator), on every point."""
    rel = gr.run_release(o.build or {"image": o.row.get("image")}, o.banner)
    o.run_release = rel.version
    o.simulator = simulator
    faults = sorted({r for r in o.reasons if asx.is_fault(r)})
    if faults:
        o.fidelity, o.facets, o.csv_row, o.faults = None, None, None, faults
        return
    if o.fidelity is None:
        g5 = sorted({tuple(sorted(asx.g5_of(r).items())) for r in o.reasons})
        if not g5:
            raise gr.GradeError(f"point {o.point_id[:12]} was not scored and names no reason")
        g = gr.grade(engine_version=engine_release, release=rel, substitutions=[], g5=[dict(x) for x in g5])
        o.g5 = g.g5
        o.g5_reasons = sorted((dict(x) for x in g5), key=lambda r: (r["code"], r.get("subject", "")))
        return
    g = gr.grade(engine_version=engine_release, release=rel, substitutions=substitutions(o.subs, o.fidelity))
    o.fidelity = {**o.fidelity, "grade": g.grade, "substitutions": g.substitutions, "run_release": rel.version,
                  "simulator": simulator}
    o.csv_row[contract.POINTS_HEADER.index(contract.GRADE_COLUMN)] = g.grade


def row_vs_run(row: dict, c: st.Decided) -> list[str]:
    """The API row's summary fields must agree with what the run's own logs say; the logs
    are what's scored, and a disagreement means the row and the artifacts aren't the same run."""
    out = []
    spec = c.mapped.get("engine.speculative.method", (None, None))[1]
    row_spec = row.get("spec_method")
    if row_spec and (row_spec == "none") != (spec is None):
        out.append("conflict:spec_method")
    offload = c.mapped.get("offload.connector", (None, None))[1]
    row_off = row.get("offload_mode")
    if row_off in ("on", "off") and (row_off == "on") != (offload is not None):
        out.append("conflict:offload_mode")
    if not row.get("disagg"):
        out += _row_topology_vs_run(row, c)
    return out


def _row_topology_vs_run(row: dict, c: st.Decided) -> list[str]:
    """The row's parallel layout against the one the run's log states.

    InferenceX records a single-node point's layout in its own terms, which differ from vLLM's
    in two known ways: with DP attention its "tp" is the attention width tp x dp (vLLM logs
    tp=1, dp=8 for its "TP 8, DP attention"); and some rows count expert-parallel ranks on top
    of tensor-parallel ones in num_decode_gpu (tp x ep), though EP shares the TP GPUs (its own
    results/topology.py counts tp x pp x pcp). Either spelling of the same GPUs agrees; a row
    whose width or GPU count matches neither describes a different run."""
    def logged(field, default=1):
        v = c.mapped.get(field, (None, None))[1]
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
                o.facets["sweep_id"] = f"{sid}|{o.point_id[:12]}"


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
    ns, failed = [], []
    for o in outcomes:
        if o.fidelity is not None:
            continue
        m = measured({"row": o.row, "measurements": o.measurements})
        rec = {"point_id": o.point_id, "identity": o.identity, "measured_date": o.identity["measured_date"],
               "model": o.row["model"], "hardware": o.row["hardware"], "precision": o.row["precision"],
               "framework": o.row["framework"], "benchmark_type": o.row["benchmark_type"],
               "conc": o.identity["conc"], "image": o.row.get("image"), "run_release": o.run_release,
               "simulator": o.simulator,
               "measured": {"ttft_ms": _ms(m.get("mean_ttft")), "tpot_ms": _ms(m.get("mean_tpot"))}}
        if o.faults:
            failed.append({**rec, "faults": o.faults})
        else:
            ns.append({**rec, "grade": gr.G5, "g5_reason": o.g5, "g5_reasons": o.g5_reasons})
    for name, recs in ((contract.NOT_SCORED_JSONL, ns), (contract.FAILED_JSONL, failed)):
        recs.sort(key=lambda r: r["point_id"])
        (out / name).write_text("".join(contract.canonical_dumps(r) + "\n" for r in recs))
    prov = {**provenance, "points": len(outcomes)}
    (out / contract.PROVENANCE_JSON).write_text(contract.canonical_dumps(prov) + "\n")


def _ms(seconds):
    return None if seconds is None else round(float(seconds) * 1e3, 6)
