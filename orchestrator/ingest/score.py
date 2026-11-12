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
sys.path.insert(0, str(HERE.parent))
import extract_single_turn_bench_args as sx  # noqa: E402
import assess as asx  # noqa: E402
import contract  # noqa: E402
import engines  # noqa: E402
import fields as fl  # noqa: E402
import g1  # noqa: E402
import grade as gr  # noqa: E402
import pd as pdm  # noqa: E402
import pd_recipe as pdr  # noqa: E402
import router_table as rt  # noqa: E402
import inferencex_client as ix  # noqa: E402
import inferencex_runners as ir  # noqa: E402
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
    # Every date-pinned AgentX corpus alias -> its catalog replay workload entry, with the path of a
    # local file checked against the entry's full sha256 (resolve_agentic_corpus.checked_corpora):
    # {"workload", "repo", "revision", "file", "split", "sha256", "path"}. A point is replayed with
    # the entry of the alias its own client recorded (COV-12, D3).
    corpora: dict
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
    # The harness commit every point records (design §11.7, X8): the 40-hex commit of the dashboard checkout.
    harness_commit: str = ""
    catalog_obj: sp.Catalog | None = None
    # InferenceX's GPUs per node by hardware label (inferencex_runners.json).
    runner_table: ir.Table = field(default_factory=ir.load)
    parts: set = field(default_factory=set)
    # A per-replay resident-memory ceiling in MB (0 = none). An agentic replay whose RSS exceeds
    # it is killed individually and the point is not-scored with an insufficient_memory reason, so
    # one memory-heavy trace can't OOM the whole CI job. Peak RAM is trace-content-driven and
    # unpredictable per point (profiled: a c64 point used 11.5GB where a c128 used 6.9GB), so a
    # reactive RSS cap is the only reliable bound on a fixed-RAM runner; 0 locally scores everything.
    max_rss_mb: int = 0
    # A router table other than the catalog's own (cli score --router-table): for an experiment with a
    # candidate entry; a run that uses one is experimental.
    routers_dir: Path | None = None
    # A router build (a full commit) to assume where a run records only a wheel version: for an experiment.
    assumed_router_revision: str | None = None
    # An llm-d policy to stand in for a router the table does not map, to measure the two-pool writer's accuracy
    # apart from the router question (cli score --router-policy-experiment): the point names it as an
    # experiment, and the run is experimental.
    router_policy_experiment: str | None = None
    # A category the caller asks the acceptance profile to fall back to where the workload states none (design D8:
    # "a fallback category the user requested"); cli score --speculative-fallback-category. The point names it as an
    # `estimated` substitution on workload.category, and the run is experimental.
    speculative_fallback_category: str | None = None
    # The checkout of the router (llm-d's router fork) at a pinned commit, which publishes the endpoint-picker file of each
    # policy (cli score --router-checkout). A prefill/decode point passes the router's file for its policy unchanged.
    router_checkout: Path | None = None

    def simulator(self) -> dict:
        """The simulator block every point of this run records: its build and engine release."""
        return {"build": self.sim_build, "engine": {"kind": "vllm", "version": self.engine_release},
                "harness_commit": self.harness_commit}


def corpora_provenance(corpora: dict) -> list[dict]:
    """provenance.json's corpora: each AgentX corpus the run could replay, by alias, with the
    catalog workload that pins it, sorted by alias."""
    return [{"alias": a, "workload": e["workload"], "dataset": e["repo"], "revision": e["revision"],
             "sha256": e["sha256"]} for a, e in sorted(corpora.items())]


def corpus_reasons(r: "rp.Replay", corpora: dict) -> list[str]:
    """Why a run's corpus cannot be replayed, from the alias its client recorded (the export's
    dataset, cross-checked against benchmark_command.txt's --public-dataset).

    No alias: from_export already names required_setting_missing:replay.corpus. An alias that is
    not date-pinned (a rolling one) does not say which corpus was read, so the run did not record
    it: design §11.4's value_not_recorded, with the alias in the subject. A dataset repository the
    export records that is not the one the alias loads is a conflict between two records of the
    run (value_conflict)."""
    if not r.corpus:
        return []
    entry = corpora.get(r.corpus)
    if entry is None:
        return [f"value_not_recorded:replay.corpus={r.corpus}"]
    if r.corpus_repo and r.corpus_repo != entry["repo"]:
        return ["conflict:replay.corpus_repo"]
    return []


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


SUCCESS_OUTCOMES = ("success", "succeeded", "completed", "ok")


def measured_population(entry: dict, pdir: Path, conc: int) -> tuple[list[str], bool]:
    """T6: what the measured side recorded of how many requests the client ran. Reads
    `completed`, `num_prompts` and `benchmark_outcome` from the run's row, its measurements and
    its frozen result file, wherever present. Returns (reasons, recorded). A run that completed
    fewer than its 10 x conc requests measured a different, easier population (the slowest are
    the ones lost): conflict:measured.completed. A benchmark_outcome that is not a success:
    conflict:measured.benchmark_outcome. `recorded` is False when neither count is present
    anywhere, which the point names as the client_difference `failed_requests`."""
    sources = [entry.get("row") or {}] + [m.get("metrics") or {} for m in entry.get("measurements") or []]
    sources += [m for m in entry.get("measurements") or []]
    raw = _read(pdir, entry.get("files") or {}, "result_json")
    if raw:
        try:
            sources.append(json.loads(raw))
        except ValueError:
            pass

    def find(key):
        vals = [s[key] for s in sources if isinstance(s, dict) and s.get(key) is not None]
        return vals
    completed, prompts, outcome = find("completed"), find("num_prompts"), find("benchmark_outcome")
    reasons = []
    expected = 10 * conc
    if any(v != expected for v in completed) or any(v != expected for v in prompts):
        reasons.append("conflict:measured.completed")
    if any(str(v).lower() not in SUCCESS_OUTCOMES for v in outcome):
        reasons.append("conflict:measured.benchmark_outcome")
    return reasons, bool(completed or prompts)


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


# The substrate's refusal when no acceptance profile holds the key (contracts/spec/acceptance Resolve):
# "... no profile for <model>/<method>/k<n>/thinking-<mode>/<category> in <sets>". The pair named is the gap.
_NO_PROFILE = re.compile(r"acceptance: no profile for \S+/\S+/k\d+/thinking-(\w+)/(\S+) in ")
_STATES_NO = re.compile(r"\bstates no ([A-Za-z_][A-Za-z0-9_.]*)")
# "the workload states no thinking mode": the simulator wants a statement about the WORKLOAD (it
# selects the acceptance profile), not a field of the engine's list. The reason names the workload
# statement, so it is not looked up in fields.json (where it would read as a missing field).
_WORKLOAD_STATES_NO = re.compile(r"\bthe workload states no ([A-Za-z_][A-Za-z0-9_ ]*?)(?: mode)?\s*[,;.:]")


def value_refusal(stderr: str, work: Path, field_list) -> str | None:
    """The G5 reason for an engine refusal that says the scenario lacks a value ("states no
    <field>"), else None. The field is parsed from the refusal's text. The field's estimation rule
    (fields.estimate_missing) is applied to it: the engine has already refused to resolve it, so
    a rule that would leave it unset or substitute another setting cannot help here, and the
    reason is value_not_recorded in every case (design 11.4). A refusal that says "states no"
    but names no parseable field takes the refusal's slug as the subject."""
    slug = _blis_refusal(stderr, work)
    text = slug.partition(":")[2]
    miss = _NO_PROFILE.search(re.sub(r"\s+", " ", stderr))
    if miss:
        return f"value_not_recorded:profile_not_available:{miss.group(2)}/{miss.group(1)}"
    if "states_no" not in text and "states no" not in stderr:
        return None
    flat = re.sub(r"\s+", " ", stderr)
    w = _WORKLOAD_STATES_NO.search(flat)
    if w:
        return f"required_setting_missing:workload.{w.group(1).strip().replace(' ', '_')}_mode"
    m = _STATES_NO.search(flat)
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
        f = st.vllm_location(a["blis_field"]) if b.vllm_names else a["blis_field"]
        a["blis_field"] = f
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
            if f.startswith("engine.env."):
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
    simulator: dict | None = None   # {"build", "engine": {"kind", "version"}, "harness_commit"}
    g5: dict | None = None
    g5_reasons: list = field(default_factory=list)
    faults: list = field(default_factory=list)
    # Set by score_point(simulate=False) when the scorer would now hand the point to the simulator:
    # the point carries what its data gives so far and is not a scored point (no figures).
    would_run_simulator: bool = False
    # What the G1 evaluations read (g1.py): the settings the run set, the values its log resolved, the
    # library versions it recorded; and, set once the Result is read, the conditions still unevaluated.
    g1_inputs: dict | None = None
    unevaluated: list = field(default_factory=lambda: list(gr.UNCHECKED_KINDS))
    # What the point record (pointrecord.py) needs of the Result and the run: the Result's data block, and
    # the number of requests behind the predicted and the measured mean.
    result_data: dict | None = None
    samples: tuple | None = None


def _score_one(entry: dict, pull_dir: Path, work: Path, env: Env, simulate: bool = True) -> Outcome:
    """score_point with the uniform error capture the driver used to do inline, so both the serial
    and the parallel path record a point that raises as not-scored (never drop it). With
    simulate=False the point is graded without a simulator (score_point) and carries no
    simulator block."""
    try:
        o = score_point(entry, pull_dir, work, env, simulate=simulate)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        o = Outcome(point_id=entry["point_id"], identity=entry["identity"], row=entry["row"],
                    reasons=sorted(set(entry["reasons"] + ["blis_refused:extractor_error"])),
                    measurements=entry.get("measurements") or [], build=entry.get("build"))
    grade_outcome(o, env.engine_release, env.simulator() if simulate else None)
    return o


# A process-pool worker scores into its OWN work subdir, because score_point writes
# work/scenarios/<scenario>.yaml keyed by scenario name, not point id -- two points that share a
# scenario name would race that file across processes. Per-worker dirs isolate it; the per-point
# results/<pid>.json cache stays correct either way (pid is unique). The worker's env and pull_dir
# are set once per process in the initializer, so each task ships only the small `entry`.
_W: dict = {}


def _worker_init(pull_dir: str, env: Env, work: str, simulate: bool):
    _W["pull_dir"] = Path(pull_dir)
    _W["env"] = env
    _W["simulate"] = simulate
    # os.getpid() is stable for the life of a pool worker -> a fixed per-worker dir it reuses, so
    # the scenario cache within one worker still helps across its tasks.
    import os
    _W["work"] = Path(work) / f"w{os.getpid()}"
    _W["work"].mkdir(parents=True, exist_ok=True)


def _worker_score(entry: dict) -> Outcome:
    return _score_one(entry, _W["pull_dir"], _W["work"], _W["env"], _W["simulate"])


def _is_agentic(entry: dict) -> bool:
    return entry["row"].get("benchmark_type") == "agentic_traces"


def score_points(points: list, pull_dir: Path, work: Path, env: Env, *, workers: int = 1,
                 agentic_workers: int = 1, log=lambda m: None, simulate: bool = True) -> list:
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
        _run_pool(single, pull_dir, work, env, max(workers, 1), record, simulate)
    if agentic:
        log(f"score: {len(agentic)} agentic on {max(agentic_workers, 1)} worker(s) (corpus-heavy)")
        _run_pool(agentic, pull_dir, work, env, max(agentic_workers, 1), record, simulate)
    return [results[i] for i in range(n)]   # input order; write_contract re-sorts anyway


def unread_result_substitutions(b: st.Built) -> list[dict]:
    """The substitutions only the simulator's Result can replace, named while it has not been read
    (score_point with simulate=False): the selected-entry report, and the acceptance profile of a
    drafter whose acceptance the run did not record."""
    return result.coefficient_substitutions({}) + _acceptance_subs(b, None)


def _acceptance_subs(b: st.Built, doc: dict | None, log: str | None = None) -> list[dict]:
    """A drafter with no recorded acceptance is simulated with the substrate's profile (D8); the
    scenario pins nothing and the point names the profile blis resolved."""
    spec, _ = st.speculative_block(b.deployment["pools"][0]["engine"])
    if spec is None or b.acceptance_length is not None:
        return []
    return [result.acceptance_substitution(doc, st.realised_acceptance(log) if log is not None else False)]


def thinking_argv(b: st.Built) -> list[str]:
    """The workload's thinking mode, stated to `blis replay` where the run recorded it, with the fallback
    category a caller requested. A speculative run with neither is not given one (the profile it would
    select is a guess); the point is G5 value_not_recorded."""
    if not (b.thinking and spec_of(b)):
        return []
    argv = ["--speculative-thinking", b.thinking]
    if b.fallback_category:
        argv += ["--speculative-fallback-category", b.fallback_category]
    return argv


# Design §11.2 and D8: a speculative point's acceptance profile is keyed by the workload's category and
# thinking mode. A value the run did not record comes from a substrate profile or the point stays G5
# value_not_recorded; the dashboard supplies neither. A server's reasoning parser is an engine capability and
# says nothing about the prompts it was sent, so it is never read as a thinking mode or a category. The
# fixed-length InferenceX client sends random tokens (`--dataset-name random`): it states a thinking mode for
# some models (`--dsv4`) and no category at all (docs/m2/workload-statements.md), so a speculative point of that
# client with no pinned or logged acceptance length is not scored.
CATEGORY_NOT_STATED = "value_not_recorded:workload_category_not_stated"


def require_workload_category(o: "Outcome", b: st.Built, requested: str | None = None) -> None:
    """A speculative point whose acceptance length is neither pinned nor logged needs the workload's category. The
    caller's requested fallback category (Env.speculative_fallback_category) stands in and is named; with none, the
    gap is named and the point stays G5."""
    if spec_of(b) is None or b.acceptance_length is not None:
        return
    if requested and b.fallback_category is None:
        b.fallback_category = requested
        o.subs.append({"kind": "estimated", "subject": "workload.category",
                       "detail": f"the benchmark states no workload category; the fallback category {requested} was "
                                 f"requested for the acceptance profile"})
    if b.fallback_category is None and CATEGORY_NOT_STATED not in o.reasons:
        o.reasons.append(CATEGORY_NOT_STATED)


def spec_of(b: st.Built):
    return st.speculative_block(b.deployment["pools"][0]["engine"])[0]


def note_realised_acceptance(fidelity: dict, b: st.Built, log: str) -> None:
    """Record the acceptance length the run's server logged, beside what the simulation used,
    on every point of a speculative deployment."""
    if st.speculative_block(b.deployment["pools"][0]["engine"])[0] is None:
        return
    fidelity["acceptance"] = {"realised": st.realised_acceptance(log),
                              "simulated": ("log" if b.acceptance_from_log else "recorded")
                              if b.acceptance_length is not None else "profile",
                              **({"simulated_length": float(b.acceptance_length)} if b.acceptance_length is not None else {})}


def check_all_scored(points: list, outcomes: list) -> list[str]:
    """COV-1: every unit the window holds ends scored, G5 with a reason, or failed. The outcomes
    are the points, one each, and each is one of those three."""
    out = []
    want = sorted(e["point_id"] for e in points)
    got = sorted(o.point_id for o in outcomes)
    if want != got:
        out.append(f"{len(got)} outcomes for {len(want)} points: every unit must end scored or G5 (COV-1)")
    for o in outcomes:
        if o.fidelity is None and o.g5 is None and not o.faults:
            out.append(f"{o.point_id[:12]}: neither scored, G5 nor failed (COV-1)")
    return out


def _run_pool(indexed: list, pull_dir: Path, work: Path, env: Env, workers: int, record,
              simulate: bool = True) -> None:
    """Score a list of (index, entry) at the given concurrency, calling record(index, outcome) as
    each finishes. workers<=1 runs in-process (no pool), else a ProcessPoolExecutor."""
    if workers <= 1:
        for idx, e in indexed:
            record(idx, _score_one(e, pull_dir, work, env, simulate))
        return
    from concurrent.futures import ProcessPoolExecutor, as_completed
    with ProcessPoolExecutor(max_workers=workers, initializer=_worker_init,
                             initargs=(str(pull_dir), env, str(work), simulate)) as ex:
        futs = {ex.submit(_worker_score, e): idx for idx, e in indexed}
        for fut in as_completed(futs):
            record(futs[fut], fut.result())


def score_point(entry: dict, pull_dir: Path, work: Path, env: Env, *, simulate: bool = True) -> Outcome:
    """One frozen point, scored: the checks, the scenario, the simulator run, the figures.

    With simulate=False the same code runs up to the simulator call (the checks, the scenario, the
    simulator's command line) and a point the scorer would hand to the simulator is returned
    there, with would_run_simulator true, no figures, and the substitutions its data gives so far:
    those its settings named, the single-turn client's differences, the data-parallel balancer,
    and "selected-entry report not read" (and, for a drafter with no recorded acceptance, the
    profile not read), which only the Result can replace. Its grade (grade_outcome) is the grade
    that data gives, so it is G2 at best, never G1. A point the scorer refuses before the
    simulator is the same outcome with or without it. `blis` is not run, and a point from
    simulate=False is never written to a contract (write_contract refuses it)."""
    row, ident, pid = entry["row"], entry["identity"], entry["point_id"]
    # blis runs in its binary's directory, so every path it is given is absolute.
    work = work.resolve()
    o = Outcome(point_id=pid, identity=ident, row=row, reasons=list(entry["reasons"]),
                measurements=entry.get("measurements") or [], build=entry.get("build"))
    fw = engines.lookup(row["framework"])
    if not engines.scored(fw):
        # Nothing was fetched and BLIS is not asked: G5 for the label's reasons and its router.
        o.reasons = sorted(set(o.reasons + engines.reasons(fw) + asx.router_reason(row, fw.router)))
        return o
    pdir = pull_dir / "points" / pid
    if row.get("disagg"):
        return score_pd(o, entry, pdir, env, work, fw, simulate=simulate)
    log_b = _read(pdir, entry["files"], "server_log")
    agg = aggregated_recipe(entry, pdir) if log_b is None else None
    if log_b is None and agg is None:
        # The pull may already have said why (the API answered 413 or 404): that reason stands alone.
        bare = [] if any(r.startswith("server_log_missing:api_") for r in o.reasons) else ["server_log_missing"]
        o.reasons = sorted(set(o.reasons + bare + asx.router_reason(row, fw.router)))
        return o
    log = log_b.decode("utf-8", "replace") if log_b is not None else ""
    o.banner = _banner_version(log)
    lc_b = _read(pdir, entry["files"], "launch_config")
    launch = json.loads(lc_b) if lc_b else None
    recovery = []
    if agg is not None:
        # A colocated multi-node run whose log is gone: its arguments are its aggregated recipe's
        # named on the point as a recovery, and the log is not asked for.
        launch, derived = pdm.aggregated_launch(agg, entry["recipe"])
        o.reasons = [r for r in o.reasons if r.partition(":")[0] != "server_log_missing"] + pdr.check_row(agg, row)
        recovery = [pdm.recovery_substitution("aggregated", entry["recipe"],
                                              sorted(k.replace("-", "_") for k in agg.pools["aggregated"].flags), derived)]
    # A run measured behind a router BLIS does not host is never scored as if llm-d had routed
    # it (design §11.4, X4; inference-sim #2028), so BLIS is not asked about it.
    o.reasons += asx.router_reason(row, _launch_router(launch) or fw.router)

    # A colocated engine over several nodes (row.is_multinode, not disagg) is one pool: build() sizes the
    # cluster from the engine's ranks and states the fabric. A prefill/decode run never
    # reaches here: score_pd takes it before the log is read.
    if agg is not None:
        readings, problems = {src: st.Reading() for src in st.SOURCES}, []
        readings["launch_config"] = st.read_launch_config(launch)
    else:
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
    c = st.decide(st.merge(readings, defaults), env.field_list, part_name)
    o.reasons += c.reasons
    o.subs = recovery + list(c.substitutions)
    o.reasons += row_vs_run(row, c)

    o.g1_inputs = {"requested": st.requested_values(c.settings),
                   "resolved": {p: v[0] for p, v in readings["resolved_config"].values.items() if v},
                   "libraries": {}}      # no source of the run's library versions is read yet
    cat = env.catalog_obj
    spec = c.mapped.get("engine.speculative.method", (None, None))[1]
    cks = _checkpoints(c, launch)
    served = [x for k in ("served_model", "model") for x in ([c.roles.get(k)] if not isinstance(c.roles.get(k), list) else c.roles.get(k))]
    draft_ck, draft_reason = sp.resolve_draft(c.roles.get("drafter"), served, entry)
    if draft_reason:
        o.reasons.append(draft_reason)
        spec = None         # the drafter cannot be judged without its checkpoint; one reason, not two
    conflict = None if cks else sp.served_conflict(entry)
    if not cks and (entry.get("checkpoint") or {}).get("repo"):
        # The log served a local path; the run's own recipe names the checkpoint (pull.py).
        cks = [entry["checkpoint"]["repo"]]
    sup = sp.check(cat, env.parts, checkpoints=cks, base_models=env.base_models,
                   hardware=part_name, spec_method=spec, draft_checkpoint=draft_ck,
                   num_spec_tokens=c.mapped.get("engine.speculative.num_spec_tokens", (None, None))[1])
    if conflict:
        o.reasons.append(conflict)
        sup.reasons = [r for r in sup.reasons if r != "model_not_in_catalog"]
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
            o.reasons += corpus_reasons(r, env.corpora)
    else:
        for k in ("isl", "osl", "conc"):
            v = row.get(k)
            if not isinstance(v, int) or isinstance(v, bool) or v < 1:
                o.reasons.append(f"required_setting_missing:replay.{k}")

    if sup.model is None or sup.chip is None:
        o.reasons = sorted(set(o.reasons))
        return o
    part = st.Part(name=part_name)
    name = f"p-{pid[:16]}"
    catalog_size = cat.packaging(sup.chip)["gpus_per_node"]
    node = ir.resolve(env.runner_table, row["hardware"], run_date=ident["measured_date"],
                      launch_size=st.recorded_node_size(launch), fixes_packaging=catalog_size is not None)
    b = st.build(c, name=name, model=sup.model, part=part, engine_version=env.engine_release,
                 field_list=env.field_list, catalog_node_size=catalog_size, node=node,
                 draft_model=sup.drafter, launch_config=launch)
    o.reasons += b.reasons
    o.subs += b.substitutions
    b.thinking = st.recorded_thinking(c.settings)
    header = [f"point {pid}", f"InferenceX row {row['id']} ({row['run_url']})",
              "GENERATED by orchestrator/ingest/score.py from the run's own settings. Do not edit."]
    if b.node_source:
        header.append(b.node_source)
    spec, tokens_key = st.speculative_block(b.deployment["pools"][0]["engine"])
    spec = spec or {}
    realised = st.realised_acceptance(log)
    if spec and b.acceptance_length is None and realised and st.engine_takes_acceptance(env.field_list):
        # The run set no acceptance length, but its server logged the one it realised; the engine
        # states acceptance by that field, so the log's figure stands in for the registry's profile
        # (which would need a thinking mode and a category the run does not record).
        b.acceptance_length = f"{realised['mean_acceptance_length']:g}"
        b.acceptance_from_log = True
        o.subs.append({"kind": "estimated", "subject": result.ACCEPTANCE_SUBJECT,
                       "detail": f"the mean acceptance length the run's server logged, "
                                 f"{realised['mean_acceptance_length']} over {realised['log_lines']} interval(s), "
                                 f"{realised['drafted_tokens']} drafted tokens; the run set none"})
    if not agentic:       # an AgentX workload's category and thinking mode are the catalog workload file's, not the run's to state
        require_workload_category(o, b, env.speculative_fallback_category)
    if b.acceptance_length is not None and spec.get(tokens_key):
        # The run's own synthetic acceptance, pinned in the scenario so every replay runs it: the
        # agentic one (which also takes --speculative-acceptance-length) and the single-turn one
        # (which passes no flag).
        b.scenario["acceptance"] = {"value": {"num_spec_tokens": int(spec[tokens_key]),
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
        return score_single_turn(o, entry, env, work, b, header, name, dep, args, log, sup, pdir, simulate=simulate)

    # ---- the replay
    corpus = env.corpora[r.corpus]
    spec_doc = rp.workload_spec(r, corpus)
    spec_path = work / "replay-specs" / f"{pid}.yaml"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    import yaml
    spec_path.write_text(yaml.safe_dump({"replay": spec_doc}, sort_keys=False))
    argv = [env.blis, "replay", "--agentic-scenario", r.replayed_as,
            "--workload-spec", str(spec_path), "--concurrency", str(r.concurrency),
            "--seed", str(r.seed), "--corpus", corpus["path"], "--corpus-sha256", corpus["sha256"],
            "--scenario", f"{name}.yaml", "--scenarios", str(sdir),
            "--catalog", str(env.catalog), "--registry", str(env.registry), "--format", "json"]
    if b.acceptance_length is not None:
        argv += ["--speculative-acceptance-length", b.acceptance_length]
    argv += thinking_argv(b)
    if env.corpus_cache:
        argv += ["--corpus-cache", str(env.corpus_cache)]
    if not simulate:
        o.subs += unread_result_substitutions(b)
        o.fidelity = {"build": entry["build"], "args": args, "resolved": []}
        o.would_run_simulator = True
        return o
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
        o.subs += _acceptance_subs(b, doc, log)
    except result.ResultError as e:
        o.reasons = [f"blis_refused:{e.slug}"]
        return o
    evaluate_g1(o, doc, env)
    m = measured(entry)
    o.fidelity = {"build": entry["build"], "args": args,
                  "resolved": resolved_kv(log, doc), "replay": {**r.record(corpus["sha256"]), "differences": rp.client_differences(r)},
                  "blis_kernel_provenance": result.kernel_report(doc)}
    note_realised_acceptance(o.fidelity, b, log)
    o.result_data = result.data_block(doc)
    # The pulled data does not hold the number of requests the client averaged over; the simulated count
    # stands for both sides and pointrecord.py says so.
    n_agentic = int((doc.get("metrics") or {}).get(result.TTFT_MEAN_MS, {}).get("samples") or 0)
    o.samples = (n_agentic, n_agentic)
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


# A single-turn point with data-parallel ranks is simulated as ONE instance whose engine holds
# the whole data-parallel group, its ranks, waves and vLLM's internal balancer (inference-sim
# cmd/engine_driver_build.go). The scenario still carries the endpoint picker profile
# vllm-dp-lb (inferencex/vllm-dp-lb.epp.yaml); with one endpoint it picks nothing, so the
# profile is inert and stands for the balancer only in name. The point names it anyway
# (design 11.3, an execution mode substituted).
DP_BALANCER = {"kind": "execution_mode", "subject": "data-parallel balancer",
               "detail": "llm-d endpoint picker profile vllm-dp-lb stands in for vLLM's internal load balancer"}


def client_reasons(entry: dict, pdir: Path, client: dict) -> list[str]:
    """What the run's job log says about the client it ran (COV-12). A flag the harness does not
    reproduce makes the point G5 value_not_recorded, subject `client:<flag>`: the client drew other
    requests. A job log that is gone (client_args null) leaves the flags assumed; a run whose
    InferenceX commit is unknown leaves the release unrecorded. Both set `client` for the point's
    named client differences."""
    row = entry["row"]
    log_b = _read(pdir, entry["files"], "job_log")
    client["flags_assumed"] = log_b is None
    client["release_unrecorded"] = not entry.get("client_commit")
    pop_reasons, recorded = measured_population(entry, pdir, int(row["conc"]))
    client["population_unrecorded"] = not recorded
    if log_b is None:
        return pop_reasons
    flags = sx.client_flag_differences(log_b.decode("utf-8", "replace"), int(row["isl"]), int(row["osl"]),
                                       int(row["conc"]))
    return pop_reasons + [f"value_not_recorded:client:{f}" for f in flags]


@dataclass
class PdRun:
    """What a prefill/decode point adds to the single-turn replay: the endpoint picker file the
    deployment names (written beside the scenario), the instance counts `blis replay` takes as
    flags, and how the point is labelled."""
    epp_name: str
    epp_bytes: bytes
    prefill: int
    decode: int
    parallelism: dict
    label: str                     # the shape in the scenario's name: "pd-1p1x4tp1-1d4tp4ep4"
    client_note: str | None = None  # the benchmark_client difference's text
    router: dict | None = None      # the router table's outcome for the point (score.pd_router)
    subs: list = field(default_factory=list)


def score_single_turn(o: Outcome, entry: dict, env: Env, work: Path, b: st.Built, header: list[str],
                      name: str, dep: dict, args: list, log: str, sup: sp.Support, pdir_in: Path, *,
                      simulate: bool = True, pd_run: "PdRun | None" = None) -> Outcome:
    """One single-turn point, replayed as the run's client sent it (COV-12).

    The requests are the client's seed-0 draws for the row's (isl, osl, conc)
    (inferencex_client.target_lengths). Where the scenario's engine states
    enable_prefix_caching false, the warm-up leaves nothing the main phase reads, so the main
    phase runs from an empty engine. Otherwise it runs primed by the client's own warm-up: the
    2*CONC copies of request 0 it sends and drains before the main phase (inferencex_client.
    WARMUPS_PER_CONCURRENCY), so the warm-up state is the client's and not an equivalent of it,
    whatever the deployment's data-parallel width. The scenario gains the router block of every
    single-turn point, written beside it (the data-parallel balancer is inside the engine: see
    DP_BALANCER). The predicted means are
    the client's own, computed from the Result's request rows (inferencex_client.summarize);
    the fidelity record's `requests` names how the requests were replayed and every difference
    from the run's client."""
    row, pid, ident = entry["row"], entry["point_id"], entry["identity"]
    model = b.scenario["model"]
    pool = dep["pools"][-1]       # the one pool of a colocated point; the decode pool of a P/D one
    eng, par = pool["engine"], pool["parallel"]
    m = measured(entry)
    try:
        meas_ttft_us, meas_tpot_us = float(m["mean_ttft"]) * 1e6, float(m["mean_tpot"]) * 1e6
    except (KeyError, TypeError, ValueError):
        o.reasons = ["required_setting_missing:measured.mean_ttft_or_tpot"]
        return o
    isl, osl, conc = int(row["isl"]), int(row["osl"]), int(row["conc"])
    client: dict = {}
    refused = client_reasons(entry, pdir_in, client)
    if refused:
        o.reasons = sorted(set(o.reasons + refused))
        return o
    ins, outs = ix.target_lengths(isl, osl, conc)
    # sa-bench (a prefill/decode run's client) sends its warm-up as a separate process whose prompts the main phase
    # never reads, so a prefill/decode point starts cold whatever its prefix-caching setting; the InferenceX client
    # primes with copies of request 0 and a single-turn point is primed unless prefix caching is off.
    primed = pd_run is None and any((p["engine"] or {}).get("enable_prefix_caching") is not False for p in dep["pools"])
    copies = ix.WARMUPS_PER_CONCURRENCY * conc if primed else 0
    replay = ix.primed_phase(ins, outs, conc, copies) if primed else ix.main_phase(ins, outs, conc)

    pdir = (work / "single_turn" / pid).resolve()
    pdir.mkdir(parents=True, exist_ok=True)
    if pd_run is None:
        routed = dataclasses.replace(b, deployment={**b.deployment,
                                                    "router": {"endpoint_picker_config": ix.ROUTER_CONFIG_NAME}})
        router, router_name = ix.router_config_bytes(), ix.ROUTER_CONFIG_NAME
    else:
        routed, router, router_name = b, pd_run.epp_bytes, pd_run.epp_name
    text = st.to_yaml(routed, header)
    (pdir / f"{name}.yaml").write_text(text)
    (pdir / router_name).write_bytes(router)
    header_path, data_path = ix.write_trace(replay, pdir)
    argv = ix.replay_argv(env.blis, f"{name}.yaml", pdir, header_path, data_path, replay.sessions, replay.pool,
                          SINGLE_TURN_SEED)
    if env.catalog:
        argv += ["--catalog", str(env.catalog)]
    if env.registry:
        argv += ["--registry", str(env.registry)]
    argv += thinking_argv(b)
    if pd_run is not None:
        argv += ["--num-instances", str(pd_run.prefill + pd_run.decode), "--prefill-instances", str(pd_run.prefill),
                 "--decode-instances", str(pd_run.decode)]
        o.subs += pd_run.subs
    verified, why = _prompt_lengths().verified(sup.checkpoint, row.get("date"), isl, osl, conc)
    bound = ix.client_bound(conc, meas_tpot_us)
    speculative = st.speculative_block(dep["pools"][0]["engine"])[0] is not None
    differences = ix.client_differences(verified, why, client_bound=bound,
                                        benchmark_client=pd_run.client_note if pd_run else None,
                                        chat_template_assumed=speculative, **client)
    if int(par.get("dp") or 1) > 1 and pd_run is None:
        o.subs.append(DP_BALANCER)
    requests = {"client": ix.CLIENT_SUBJECT, "start": "primed" if primed else "cold",
                "copies": copies, "count": len(ins), "client_bound": bound,
                "chunk_rate_per_s": round(ix.chunk_rate(conc, meas_tpot_us), 1), "differences": differences}
    if not simulate:
        o.subs += unread_result_substitutions(b)
        o.fidelity = {"build": entry["build"], "args": args, "resolved": [], "requests": requests}
        o.would_run_simulator = True
        return o
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
        flight = ix.check_request_pattern(rows, len(ins), conc, ignore=ix.main_phase_only(len(ins)) if primed else None)
    except ValueError:
        o.reasons = ["blis_refused:request_pattern_not_the_clients"]
        return o
    requests["achieved_concurrency"] = flight["achieved_concurrency"]

    try:
        o.subs += result.coefficient_substitutions(doc)
        o.subs += _acceptance_subs(b, doc, log)
    except result.ResultError as e:
        o.reasons = [f"blis_refused:{e.slug}"]
        return o
    evaluate_g1(o, doc, env)
    o.fidelity = {"build": entry["build"], "args": args, "resolved": [],
                  "blis_kernel_provenance": result.kernel_report(doc), "requests": requests}
    if pd_run is not None and pd_run.router:
        o.fidelity["router"] = pd_run.router
    note_realised_acceptance(o.fidelity, b, log)
    o.result_data = result.data_block(doc)
    o.samples = (len(ins), len(ins))       # the client's num-prompts: 10 x concurrency requests
    ep = (par["tp"] * par["dp"]) if par.get("enable_expert_parallel") else 1
    label = _single_turn_label(isl, osl)
    scen = f"{model}-{row['hardware']}-{row['precision']}-vllm-tp{par['tp']}-dp{par['dp']}-ep{ep}"
    parallelism = {"tp": par["tp"], "pp": par["pp"], "dp": par["dp"], "ep": ep}
    if pd_run is not None:
        scen = f"{model}-{row['hardware']}-{row['precision']}-vllm-{pd_run.label}"
        parallelism = pd_run.parallelism
    o.facets = {"identity": ident, "sweep_id": sweep_id(row, scen, label),
                "scenario": scen, "label": label, "workload": f"{isl}:{osl}",
                "model": model, "gpu": row["hardware"], "precision": row["precision"],
                "framework": "vllm" if pd_run is None else row["framework"],
                "serving": "aggregated" if pd_run is None else "disaggregated",
                "spec_method": row.get("spec_method") or "none",
                "parallelism": parallelism,
                "image": row.get("image"), "vllm_version": _banner_version(log)}
    o.csv_row = [scen, model, row["hardware"], label, ident["conc"],
                 round(meas_tpot_us, 3), round(s["mean_tpot_us"], 3),
                 round(meas_ttft_us, 3), round(s["mean_ttft_us"], 3),
                 None, pid, ident["measured_date"]]     # the grade column is filled by grade_outcome
    return o



# ---------------------------------------------------------------- prefill/decode points

def router_experiment(name: str, policy: str, reasons: list[str], rec: dict | None):
    """The stand-in of a router-policy experiment for a router the table did not map: (policy, substitutions,
    reasons, record). It is a measurement of the writer, not a grade of the router: the substitution says so."""
    key = rt.router_key(name)
    sub = {"kind": "execution_mode", "subject": f"router {key} (experiment)",
           "detail": f"EXPERIMENT ONLY: the run's {key} router was replaced by llm-d's {policy} policy with no router table "
                     f"entry, build or bound for it (the table said: {', '.join(reasons)}); the figure measures the two-pool "
                     f"writer under that stand-in and is not a graded result"}
    return policy, [sub], [], {"outcome": "experiment", "policy": policy, "table": reasons}


def pd_router(row: dict, name: str | None, recipe: "pdr.Recipe | None", table: "rt.Table", ctx: dict | None = None,
              assumed_revision: str | None = None):
    """(policy, substitutions, reasons, record) for a P/D point's router (design §11.3, §11.4).

    llm-d's own router: the row does not say which endpoint picker configuration it ran, so there is no
    policy to simulate (value_not_recorded). Another router: the table is asked for the run's router, mode
    (the recipe's; none set is the frontend's default, round-robin), session-affinity setting and build
    (the recipe's pinned commit, if any), as the substrate's Resolve does. Only a `mapped` entry whose
    bound has a ratio in the point's regime (`ctx`: lengths, concurrency, catalog model, hardware part and
    pool shape) gives a G2 `router_differs`, carrying the entry's policy, build, differences and bound
    whatever its ratios are; the record holds the matched ratios and `bound_wide`. Every other outcome
    leaves the point `router_unsupported` and names it in the subject (`no_entry`, `no_policy`,
    `revision_not_covered`, `no_bound_for_regime`); with no recipe to say the mode, or no context yet, the
    subject is the router alone."""
    if not name or str(name).startswith("llm-d"):
        return None, [], ["required_setting_missing:router.endpoint_picker_config"], None
    base = f"router_unsupported:{name}"
    key = rt.router_key(name)
    if recipe is None or (recipe.frontend.get("type") or "").lower() != key:
        return None, [], [base], None
    mode, ttl, stated = pdr.router_mode(recipe)
    revision, assumed = pdr.router_revision(recipe), False
    if revision is None and assumed_revision:
        revision, assumed = assumed_revision, True
    entry, outcome = table.resolve(key, mode, ttl, revision)
    if outcome != rt.MAPPED:
        return None, [], [f"{base}:{outcome}"], {"outcome": outcome, "entry": entry.name if entry else None, "mode": mode}
    if ctx is None:
        return None, [], [base], None
    matched = rt.matched_ratios(entry, workload=rt.workload_kind(ctx["isl"], ctx["osl"]), conc=ctx["conc"],
                                model=ctx["model"], hardware=ctx["hardware"], shape=ctx["shape"],
                                engine_version=ctx.get("engine_version"), fabric=ctx.get("fabric"),
                                prefill=ctx.get("prefill"), decode=ctx.get("decode"))
    if not matched:
        return None, [], [f"{base}:{rt.NO_BOUND}"], {"outcome": rt.NO_BOUND, "entry": entry.name, "mode": mode}
    point = {"workload": rt.workload_kind(ctx["isl"], ctx["osl"]), "concurrency": ctx["conc"], "model": ctx["model"],
             "hardware": ctx["hardware"], "engine_version": ctx["engine_version"], "fabric": ctx["fabric"],
             "shape": ctx["shape"], "prefill": ctx["prefill"], "decode": ctx["decode"]}
    sub = rt.substitution(entry, key, revision, matched, point, assumed=assumed)
    if not stated:
        sub["detail"] += "; the recipe sets no router mode, so the frontend's default ran"
    return entry.policy, [sub], [], {"outcome": rt.MAPPED, "entry": entry.name, "policy": entry.policy, "mode": mode,
                                     "revision": revision, "matched_ratios": matched, "bound_wide": rt.bound_wide(matched)}


def _router_config_refusal(o: Outcome, router_name: str | None, e: "pdm.PolicyConfigError") -> Outcome:
    """G5 router_unsupported with the named slug: the router publishes no configuration for the policy the table names."""
    o.reasons = sorted(set(o.reasons + [f"router_unsupported:{router_name}:{e.slug}"]))
    return o


def aggregated_recipe(entry: dict, pdir: Path) -> "pdr.Recipe | None":
    """The aggregated recipe the pull kept for a colocated multi-node row, or None (not multi-node, no
    recipe frozen, or a recipe of prefill/decode pools)."""
    row = entry["row"]
    if not (row.get("is_multinode") and not row.get("disagg") and entry.get("recipe")):
        return None
    rb = _read(pdir, entry["files"], "recipe")
    if rb is None:
        return None
    try:
        r = pdr.parse(rb.decode("utf-8", "replace"))
    except ValueError:
        return None
    return r if "aggregated" in r.pools else None


def logged_configs(log: str) -> list[dict]:
    """The resolved engine configuration of each engine core a server log prints, as flat dicts
    (settings.read_resolved reads them together)."""
    import pyrepr
    out = []
    for line in sorted(set(st._RESOLVED.findall(log))):
        try:
            out.append(st.flatten(pyrepr.parse_kwargs(line)))
        except pyrepr.ReprError:
            continue
    return out


def score_pd(o: Outcome, entry: dict, pdir: Path, env: Env, work: Path, fw, *, simulate: bool = True) -> Outcome:
    """One prefill/decode point (design §11.4 topology_unsupported, §11.2, §11.3; dashboard #61). The two pools' engine arguments are the run's recipe's (a P/D server log is one worker's, and
    usually gone), named on the point as the recovery they are; the shape is refused by name where the
    stack cannot express it (pd.py); the router is read from the router table (pd_router); the
    scenario states two pools and the NIXL connector, and the instance counts reach `blis replay` as
    flags. The replay is the single-turn one."""
    row, pid, ident = entry["row"], entry["point_id"], entry["identity"]
    rb = _read(pdir, entry["files"], "recipe")
    recipe = None
    if entry.get("recipe") and rb:
        try:
            recipe = pdr.parse(rb.decode("utf-8", "replace"))
        except ValueError:
            o.reasons.append("recipe_unresolved:unreadable")
    else:
        o.reasons.append(f"recipe_unresolved:{entry.get('recipe_reason') or 'not_frozen'}")
    if recipe is not None:
        # The recipe answers what the missing log would have.
        o.reasons = [r for r in o.reasons if r.partition(":")[0] != "server_log_missing"]
    else:
        # Without a recipe the pools' arguments are not known. A log that records topology fields still
        # has them decided by the engine's field list (design §11.4), as every other recorded field is.
        log_b = _read(pdir, entry["files"], "server_log")
        if log_b is not None:
            lc = _read(pdir, entry["files"], "launch_config")
            o.reasons += st.topology_reasons(json.loads(lc) if lc else None,
                                             st.read_args(log_b.decode("utf-8", "replace")), env.field_list)
    pools = pdm.pools_of(row, recipe)
    router_name = (row.get("metrics") or {}).get("router_name") or fw.router
    table = rt.load(env.catalog, env.routers_dir)
    o.reasons += pdm.topology_reasons(row, pools)
    if recipe is None or pools is None:
        o.reasons += pd_router(row, router_name, recipe, table)[2]
        o.reasons = sorted(set(o.reasons))
        return o
    o.reasons += pdr.check_row(recipe, row)
    log_b = _read(pdir, entry["files"], "server_log")
    if log_b is not None and pools is not None:
        o.reasons += pdm.log_conflicts(logged_configs(log_b.decode("utf-8", "replace")), recipe, pools)

    meta = entry["recipe"]
    cat = env.catalog_obj
    part_name = (sp.catalog_part(cat, env.parts, row["hardware"]) if cat else None) or row["hardware"]
    decided, taken, launches = {}, {}, {}
    for role, pool in pools.items():
        launches[role] = pdm.pseudo_launch(recipe, role, row, pool)
        rd, taken[role] = pdm.read_pool(launches[role])
        c = st.decide(st.merge({"launch_config": rd}, {}), env.field_list, part_name)
        decided[role] = c
        o.reasons += c.reasons
        o.subs += c.substitutions
        stated = sorted(k.replace("-", "_") for k in recipe.pools[role].flags)
        derived = sorted(f for f in ("tensor_parallel_size", "pipeline_parallel_size", "data_parallel_size")
                         if f in rd.values and f.replace("_", "-") not in recipe.pools[role].flags)
        o.subs.append(pdm.recovery_substitution(role, meta, stated, derived))
        for p in pdm.TRANSFER_PATHS:
            if p in taken[role]:
                dec = fl.decide(env.field_list, p, set_by_run=True)
                if dec.g5:
                    o.reasons.append(f"{dec.g5['code']}:{p}")
    connectors = {t.get("kv_transfer_config.kv_connector") for t in taken.values()}
    if len(connectors) > 1:
        o.reasons.append("conflict:kv_transfer_config.kv_connector")
    if None in connectors:
        o.reasons.append("required_setting_missing:kv_transfer_config.kv_connector")
    placement = pdm.placement_substitution(recipe)
    if placement:
        o.subs.append(placement)

    # The model, chip and drafter, from the recipe's master entry (the HF repo the sweep served).
    c_dec = decided["decode"]
    spec = c_dec.mapped.get("engine.speculative.method", (None, None))[1]
    served = [x for k in ("served_model", "model") for x in ([c_dec.roles.get(k)] if not isinstance(c_dec.roles.get(k), list) else c_dec.roles.get(k))]
    draft_ck, draft_reason = sp.resolve_draft(c_dec.roles.get("drafter"), served, entry)
    if draft_reason:
        o.reasons.append(draft_reason)
        spec = None
    cks = [meta["model"]] if meta.get("model") else []
    sup = sp.check(cat, env.parts, checkpoints=cks, base_models=env.base_models, hardware=part_name, spec_method=spec,
                   draft_checkpoint=draft_ck, num_spec_tokens=c_dec.mapped.get("engine.speculative.num_spec_tokens", (None, None))[1])
    o.reasons += sup.reasons
    for k in ("isl", "osl", "conc"):
        v = row.get(k)
        if not isinstance(v, int) or isinstance(v, bool) or v < 1:
            o.reasons.append(f"required_setting_missing:replay.{k}")
    ctx = {"isl": row.get("isl"), "osl": row.get("osl"), "conc": row.get("conc"), "model": sup.model, "hardware": part_name,
           "shape": f"{pools['prefill'].workers}P{pools['decode'].workers}D",
           # The rest of the regime (the substrate's exact form): the engine release, the fabric the run recorded
           # (an assumed class is not a recorded one, so it is None), and each pool's per-instance parallelism.
           "engine_version": env.engine_release, "fabric": recipe.fabric or st.recorded_fabric(launches["decode"]),
           "prefill": pdm.pool_parallel(pools["prefill"], recipe.pools["prefill"].flags),
           "decode": pdm.pool_parallel(pools["decode"], recipe.pools["decode"].flags)}
    policy, rsubs, rreasons, rrec = pd_router(row, router_name, recipe, table, ctx, env.assumed_router_revision)
    if policy is None and env.router_policy_experiment and rreasons and all(r.startswith("router_unsupported") for r in rreasons):
        policy, rsubs, rreasons, rrec = router_experiment(router_name, env.router_policy_experiment, rreasons, rrec)
    o.reasons += rreasons
    o.subs += rsubs
    if sup.model is None or sup.chip is None:
        o.reasons = sorted(set(o.reasons))
        return o

    name = f"p-{pid[:16]}"
    part = st.Part(name=part_name)
    catalog_size = cat.packaging(sup.chip)["gpus_per_node"]
    node = ir.resolve(env.runner_table, row["hardware"], run_date=ident["measured_date"],
                      launch_size=recipe.gpus_per_node, fixes_packaging=catalog_size is not None)
    builts = {role: st.build(decided[role], name=name, model=sup.model, part=part, engine_version=env.engine_release,
                             field_list=env.field_list, catalog_node_size=catalog_size, node=node,
                             draft_model=sup.drafter, launch_config=launches[role]) for role in pools}
    b = pdm.build_pd(builts, recipe, pools, taken, name=name, policy=policy, per_node=catalog_size or node.gpus_per_node)
    o.reasons += b.reasons
    o.subs += b.substitutions
    b.thinking = st.recorded_thinking({**decided["prefill"].settings, **decided["decode"].settings})
    require_workload_category(o, b, env.speculative_fallback_category)
    if row.get("benchmark_type") != "single_turn":
        o.reasons.append(f"topology_unsupported:{pdm.AGENTIC}")
    header = [f"point {pid}", f"InferenceX row {row['id']} ({row['run_url']})",
              f"GENERATED by orchestrator/ingest/score.py from the run's recipe {meta['path']} at {meta['commit']}. Do not edit."]
    if b.node_source:
        header.append(b.node_source)
    text = st.to_yaml(b, header)
    sdir = work / "scenarios"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / f"{name}.yaml").write_text(text)
    dep = _parse_back(text)
    args = []
    for role, pool_dict in zip(("prefill", "decode"), dep["pools"]):
        view = {**dep, "pools": [pool_dict]}
        pool_args = decided[role].args
        o.reasons += _diff_args(pool_args, view, b)
        for a in pool_args:
            args.append({**a, "arg": f"{role}.{a['arg']}"})
    args.sort(key=lambda a: a["arg"])
    o.reasons = sorted(set(o.reasons))
    if o.reasons or policy is None:
        return o
    label = "pd-" + "-".join(f"{p.workers}{r[0]}{p.gpus}tp{p.tp}" + (f"ep{p.ep}" if p.ep > 1 else "") for r, p in pools.items())
    # The facets' parallelism is the decode pool's (the labels every point has), then each pool's own.
    dpar = dep["pools"][1]["parallel"]
    par = {"tp": dpar["tp"], "pp": dpar["pp"], "dp": dpar["dp"],
           "ep": dpar["tp"] * dpar["dp"] if dpar.get("enable_expert_parallel") else 1}
    par.update({f"{r}_{k}": v for r, p in pools.items() for k, v in (("workers", p.workers), ("tp", p.tp), ("ep", p.ep), ("dp", p.dp))})
    try:
        if env.router_checkout is None:
            raise pdm.PolicyConfigError("router_checkout_not_given", "no router checkout was given (--router-checkout)")
        epp = pdm.epp_file(policy, env.router_checkout)
    except pdm.PolicyConfigError as e:
        return _router_config_refusal(o, router_name, e)
    run = PdRun(epp_name=pdm.epp_name(policy), epp_bytes=epp, prefill=pools["prefill"].workers,
                decode=pools["decode"].workers, parallelism=par, label=label,
                client_note=pdm.benchmark_client_note(recipe), router=rrec)
    return score_single_turn(o, entry, env, work, b, header, name, dep, args, "", sup, pdir, simulate=simulate, pd_run=run)

_EVIDENCE: list = []


def _prompt_lengths() -> ix.PromptLengthEvidence:
    """The sent-prompt-length evidence (inferencex_client.PROMPT_LENGTHS), loaded once per
    process."""
    if not _EVIDENCE:
        _EVIDENCE.append(ix.PromptLengthEvidence.load(ix.PROMPT_LENGTHS))
    return _EVIDENCE[0]


def evaluate_g1(o: Outcome, doc: dict, env: "Env") -> None:
    """Evaluate the four G1 conditions from the Result and the run's recorded settings; a condition
    whose data is absent stays unevaluated and the point keeps naming it (grade.unchecked)."""
    inputs = o.g1_inputs or {}
    subs, o.unevaluated = g1.split(g1.evaluate(doc, field_list=env.field_list, requested=inputs.get("requested"),
                                               resolved=inputs.get("resolved"), libraries=inputs.get("libraries")))
    o.subs += subs


def substitutions(o_subs: list[dict], fidelity: dict, unevaluated=None) -> list[dict]:
    """Every G2 substitution a scored point names (design §11.3): each one its settings named
    (an estimation rule applied, a field with a status allowed only during a release plan), and
    each difference between the run's client and the simulated one (COV-12). It also names, on
    every point, each G1 condition that is unevaluated (grade.UNCHECKED_KINDS), so the scorer
    publishes a G1 only when every condition has been checked."""
    return list(o_subs) + list((fidelity.get("requests") or {}).get("differences") or []) \
        + list((fidelity.get("replay") or {}).get("differences") or []) \
        + gr.unchecked(unevaluated)


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
    g = gr.grade(engine_version=engine_release, release=rel, substitutions=substitutions(o.subs, o.fidelity, o.unevaluated))
    o.fidelity = {**o.fidelity, "grade": g.grade, "substitutions": g.substitutions, "run_release": rel.version,
                  "simulator": simulator}
    if not o.would_run_simulator:      # a point graded without the simulator has no points.csv row
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
    # A colocated engine over several nodes is recorded in the row's prefill fields (the decode ones are 0).
    side = "prefill" if row.get("is_multinode") else "decode"
    row_tp, row_ep = row.get(f"{side}_tp"), row.get(f"{side}_ep")
    if row_tp and int(row_tp) not in ({tp, tp * dp} if row.get(f"{side}_dp_attention") else {tp}):
        out.append("conflict:tp")
    gpus = row.get(f"num_{side}_gpu")
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
    unsimulated = [o.point_id[:12] for o in outcomes if o.would_run_simulator]
    if unsimulated:
        raise ValueError(f"{len(unsimulated)} point(s) were graded without the simulator and have no figures "
                         f"({', '.join(unsimulated[:3])}); a contract holds only scored points")
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
    import pointrecord
    csv_rows = {r["point_id"]: r for r in csv.DictReader(io.StringIO(buf.getvalue()))}
    (out / contract.POINTRECORDS_JSONL).write_text(pointrecord.dumps(pointrecord.assemble(outcomes, provenance, csv_rows)))
    prov = {**provenance, "points": len(outcomes)}
    (out / contract.PROVENANCE_JSON).write_text(contract.canonical_dumps(prov) + "\n")


def _ms(seconds):
    return None if seconds is None else round(float(seconds) * 1e3, 6)
