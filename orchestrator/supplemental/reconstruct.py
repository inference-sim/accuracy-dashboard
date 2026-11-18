#!/usr/bin/env python3
"""Reconstruct a vLLM launch from InferenceX's own benchmark script at a commit, by running the script with the
benchmark environment it was given and stubs for everything but `vllm serve`, which records its arguments, the
config.yaml it was handed, and the VLLM_* / TORCH_* / PYTHON* variables in force. Nothing is simulated by hand: the
script's own shell logic (max-model-len arithmetic, config.yaml heredocs, exports) produces the launch.

  python3 reconstruct.py validate     # reconstruct surviving gpt-oss-120b vLLM units and compare with their server logs
  python3 reconstruct.py derive       # the 213 Llama-70B vLLM units whose run records are gone

Environment: INFERENCEX_GIT (a clone of the InferenceX repository with its history), MATCHED_PULL (the matched pull directory), OUT (where
validation.json and derived-213.json go; default beside this file). supplement.py then writes the file the scorer's --supplemental reads.
"""
import gzip, json, os, re, shlex, subprocess, sys, tempfile, collections
REPO = os.environ["INFERENCEX_GIT"]        # a clone of SemiAnalysisAI/InferenceX with its history
PULL = os.environ["MATCHED_PULL"]          # the matched pull directory (match.json, dump-rows.jsonl, pull-errors.json, rows-all-*.json)
OUT = os.environ.get("OUT", os.path.dirname(os.path.abspath(__file__)))

def git(*a):
    return subprocess.check_output(["git", "-C", REPO, *a], text=True)

STUB_VLLM = r'''#!/bin/bash
# records the launch; prints the line the script waits for
python3 - "$@" <<'P'
import json, os, sys
env = {k: v for k, v in os.environ.items() if k.startswith(("VLLM_", "TORCH_CUDA", "PYTHONNOUSERSITE", "NCCL_", "CUDA_", "HF_", "FLASHINFER"))}
cfg = open("config.yaml").read() if os.path.exists("config.yaml") else None
json.dump({"argv": sys.argv[1:], "config_yaml": cfg, "env": env}, open(os.environ["RECORD"], "w"))
P
/bin/sleep 1
echo "Application startup complete"
'''
STUB_NOOP = '#!/bin/bash\nexit 0\n'
LIB_STUB = '''check_env_vars() { :; }
start_gpu_monitor() { :; }
stop_gpu_monitor() { :; }
wait_for_server_ready() { :; }
run_benchmark_serving() { :; }
run_eval() { :; }
append_lm_eval_summary() { :; }
setup_eval_context() { :; }
'''

def run_script(commit, path, env):
    """Run <path> as of <commit> under bash with a restricted PATH in a temporary directory (not a sandbox: there is no network or
    filesystem isolation, so run it only on InferenceX's own scripts); return the recorded launch, or {"error": ...} if vllm was never started."""
    with tempfile.TemporaryDirectory() as d:
        for p in {path, "benchmarks/benchmark_lib.sh"}:
            try:
                blob = git("show", f"{commit}:{p}")
            except subprocess.CalledProcessError:
                if p == "benchmarks/benchmark_lib.sh":
                    continue
                raise
            blob = blob.replace("/workspace", os.path.join(d, "ws"))
            os.makedirs(os.path.join(d, "ws"), exist_ok=True)
            dst = os.path.join(d, "repo", p)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, "w").write(blob)
        # the script sources a library next to it (benchmarks/benchmark_lib.sh): stubbed, its functions only
        for p in (os.path.join(d, "repo", "benchmarks", "benchmark_lib.sh"),):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").write(LIB_STUB)
        bindir = os.path.join(d, "bin"); os.makedirs(bindir)
        for n in ("nvidia-smi", "sed", "pip", "hf", "git", "python3", "curl", "sleep", "nvidia-smi", "rocm-smi", "mktemp"):
            if n == "mktemp":
                open(os.path.join(bindir, n), "w").write('#!/bin/bash\necho ' + os.path.join(d, 'ws', 'server-stub.log') + '\n')
            else:
                open(os.path.join(bindir, n), "w").write(STUB_NOOP)
            os.chmod(os.path.join(bindir, n), 0o755)
        open(os.path.join(bindir, "vllm"), "w").write(STUB_VLLM); os.chmod(os.path.join(bindir, "vllm"), 0o755)
        real_python = subprocess.check_output(["bash", "-lc", "command -v python3"], text=True).strip()
        # the vllm stub needs a real python3; keep it under another name
        st = open(os.path.join(bindir, "vllm")).read().replace("python3 -", real_python + " -")
        open(os.path.join(bindir, "vllm"), "w").write(st)
        rec = os.path.join(d, "record.json")
        e = dict(os.environ); e.update({k: str(v) for k, v in env.items()})
        e["PATH"] = bindir + ":/usr/bin:/bin"; e["RECORD"] = rec; e.setdefault("PORT", "8888")
        wd = os.path.join(d, "work"); os.makedirs(wd)
        import time, signal
        logf = open(os.path.join(d, "out.log"), "w")
        p = subprocess.Popen(["bash", os.path.join(d, "repo", path)], cwd=wd, env=e, stdout=logf, stderr=logf, start_new_session=True)
        t0 = time.time()
        while time.time() - t0 < 25 and not os.path.exists(rec) and p.poll() is None:
            time.sleep(0.1)
        time.sleep(0.2)
        try: os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        p.wait()
        class _P: stderr = open(os.path.join(d, "out.log")).read()
        p = _P
        if not os.path.exists(rec):
            return {"error": "vllm never started", "stderr": p.stderr[-400:]}
        return json.load(open(rec))

def parse_yaml_flat(text):
    out = {}
    for line in (text or "").splitlines():
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m:
            v = m.group(2).strip()
            if v in ("true", "false"): v = (v == "true")
            elif re.fullmatch(r"-?\d+", v): v = int(v)
            elif v.startswith("'") and v.endswith("'"): v = v[1:-1]
            out[m.group(1).replace("-", "_")] = v
    return out

def final_args(rec):
    """vLLM's argument dictionary from a recorded launch: the config.yaml, then the command line over it."""
    argv = rec["argv"]
    a = parse_yaml_flat(rec.get("config_yaml"))
    i = 0
    if argv and argv[0] == "serve": argv = argv[1:]
    if argv and not argv[0].startswith("-"):
        a["model"] = argv[0]; argv = argv[1:]
    while i < len(argv):
        t = argv[i]
        if t.startswith("--"):
            if "=" in t:
                k, v = t[2:].split("=", 1)
            else:
                k = t[2:]
                if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                    v = argv[i + 1]; i += 1
                else:
                    v = True
            k = k.replace("-", "_")
            if isinstance(v, str):
                if re.fullmatch(r"-?\d+", v): v = int(v)
                elif re.fullmatch(r"-?\d+\.\d+", v): v = float(v)
            a[k] = v
        i += 1
    return a

# the names `--no-enable-prefix-caching` and similar become the dest with a False value
def normalise(a):
    out = dict(a)
    for k in list(out):
        if k.startswith("no_enable_"):
            out["enable_" + k[len("no_enable_"):]] = not out.pop(k)
        elif k.startswith("no_"):
            out[k[3:]] = not out.pop(k)
    out.pop("disable_log_requests", None); out.pop("config", None); out.pop("trust_remote_code", None)
    return out

# vLLM prints only the arguments that differ from its defaults ("non-default args"); a reconstructed value equal to the
# default is therefore absent from the log. The defaults that matter here, from vLLM's own argument table.
DEFAULTS = {"gpu_memory_utilization": 0.9, "tensor_parallel_size": 1, "enable_prefix_caching": None, "async_scheduling": None}
CC_DEFAULTS = {("pass_config", "eliminate_noops"): True}
# keys that are the runner's deployment and not the launch: the checkpoint's path on the runner, the port, the server count vLLM adds
IGNORED = ("model_tag", "host", "port", "api_server_count")

def recorded_args(logpath):
    t = gzip.open(logpath, "rt", errors="replace").read()
    m = re.search(r"non-default args: (\{.*\})", t)
    if not m: return None
    txt = re.sub(r"<[^<>]*>", "'enum'", m.group(1))
    return eval(txt, {"__builtins__": {}}, {"True": True, "False": False, "None": None})

def rows():
    r = {}
    import glob
    for f in sorted(glob.glob(f"{PULL}/rows-all-*.json")):
        if f.endswith(".availability.json"): continue
        for d in json.load(open(f)): r[str(d["id"])] = d
    dump = {}
    for l in open(f"{PULL}/dump-rows.jsonl"):
        d = json.loads(l); dump[str(d["id"])] = d
    return r, dump

def commit_at70(date, end_of_day=True):
    """The latest commit before the end (or start) of the day that still has the 70B scripts: the repository removed them
    for a few hours on 2025-10-29 and restored them, and the runs of that day are of the version that had them."""
    for c in git("rev-list", f"--before={date} {'23:59' if end_of_day else '00:00'}", "HEAD").split()[:60]:
        if subprocess.call(["git", "-C", REPO, "cat-file", "-e", f"{c}:.github/workflows/70b-tmpl.yml"], stderr=subprocess.DEVNULL) == 0:
            return c
    raise SystemExit("no commit with the 70B workflow before " + date)

def commit_at(date, end_of_day=True):
    return git("rev-list", "-1", f"--before={date} {'23:59' if end_of_day else '00:00'}", "HEAD").strip()

def validate():
    rows_all, dump = rows()
    man = json.load(open(f"{PULL}/pull/manifest.json"))
    pts = [p for p in man["points"] if p.get("files") and p["identity"]["framework"] == "vllm" and p["identity"]["model"] == "gptoss120b"
           and p["identity"]["hardware"] in ("h100", "h200", "b200") and p["identity"]["benchmark_type"] == "single_turn"]
    # spread over hardware and dates
    by = collections.defaultdict(list)
    for p in pts: by[(p["identity"]["hardware"], p["identity"]["measured_date"][:7])].append(p)
    chosen = []
    for k in sorted(by):
        chosen.append(by[k][len(by[k]) // 2])
    results = []
    for p in chosen:
        i = p["identity"]; hw = i["hardware"]; rid = str(p["records"][0]); row = rows_all[rid]
        logf = f"{PULL}/pull/points/{p['point_id']}/server_log.gz"
        rec_args = recorded_args(logf)
        script = f"benchmarks/single_node/gptoss_fp4_{hw}.sh"
        date = i["measured_date"]
        c_end, c_start = commit_at(date, True), commit_at(date, False)
        same = git("rev-parse", f"{c_end}:{script}").strip() == git("rev-parse", f"{c_start}:{script}").strip()
        env = {"MODEL": "openai/gpt-oss-120b", "TP": row["decode_tp"], "CONC": row["conc"], "ISL": row["isl"], "OSL": row["osl"],
               "RANDOM_RANGE_RATIO": "0.8", "RESULT_FILENAME": "x", "MAX_MODEL_LEN": "", "PORT": "8888"}
        got = run_script(c_end, script, env)
        res = {"unit": f"{hw} {date} conc{row['conc']} tp{row['decode_tp']} {row['isl']}/{row['osl']}", "commit": c_end[:9], "script_stable_through_the_day": same}
        if "error" in got: res["error"] = got
        else:
            fa = normalise(final_args(got)); ra = dict(rec_args or {})
            for k in IGNORED: ra.pop(k, None); fa.pop(k, None)
            # the checkpoint: the runner replaces the hub id with a local path; the last path component is compared
            for d_ in (fa, ra):
                if "model" in d_: d_["model"] = str(d_["model"]).rstrip("/").split("/")[-1].lower()
            for k, dv in DEFAULTS.items():
                if dv is not None and fa.get(k) == dv and k not in ra: fa.pop(k)
            diffs = {}
            for k in sorted(set(fa) | set(ra)):
                if k == "compilation_config":
                    # the log prints the whole resolved dict; the script states a subset, which must be inside it
                    want = fa.get(k)
                    if isinstance(want, str): want = json.loads(want)
                    have = ra.get(k) or {}
                    def sub(w, h):
                        return all((sub(v, h.get(kk)) if isinstance(v, dict) and isinstance(h.get(kk), dict) else h.get(kk) == v) for kk, v in (w or {}).items()) if isinstance(h, dict) else False
                    if isinstance(want, dict):
                        want = json.loads(json.dumps(want))
                        for (a1, a2), dv in CC_DEFAULTS.items():
                            if isinstance(want.get(a1), dict) and want[a1].get(a2) == dv and not (isinstance(have.get(a1), dict) and a2 in have[a1]):
                                want[a1].pop(a2)
                    if want is None:
                        # nothing stated: the log's dict must hold nothing but defaults, which a bare comparison cannot say
                        continue
                    if not sub(want, have): diffs[k] = (want, have)
                elif fa.get(k) != ra.get(k):
                    diffs[k] = (fa.get(k), ra.get(k))
            res["recorded"] = ra; res["reconstructed"] = fa; res["differences"] = diffs; res["equal"] = not diffs
            res["env"] = got["env"]
        results.append(res)
    json.dump(results, open(f"{OUT}/validation.json", "w"), indent=1, default=str)
    for r in results:
        print(r["unit"], r["commit"], "stable" if r["script_stable_through_the_day"] else "SCRIPT CHANGED THAT DAY", "EQUAL" if r.get("equal") else r.get("differences", r.get("error")))




def workflow_inputs(commit, hw, prec):
    """Image, model and max-model-len the workflow gave a 70B run on this hardware and precision, read from the
    workflow files at the commit (70b-tmpl.yml and full-sweep-tmpl.yml)."""
    t = git("show", f"{commit}:.github/workflows/70b-tmpl.yml")
    blocks = re.split(r"\n  (?=bmk-)", t)
    for b in blocks:
        m = re.match(r"(bmk-[a-z0-9-]+):", b)
        if not m: continue
        name = m.group(1)
        if name == f"bmk-{hw}-{prec}":
            g = lambda key: (re.search(rf"\n\s+{key}: '?([^'\n]+)'?", b) or [None, None])[1]
            return {"job": name, "image": g("image"), "model": g("model"), "framework": g("framework"), "tp_list": g("tp-list")}
    return None

def derive():
    rows_all, dump = rows()
    errs = json.load(open(f"{PULL}/pull-errors.json"))
    byu = {p["unit"]: p for p in json.load(open(f"{PULL}/match.json"))["points"]}
    units = [byu[k] for k in errs]
    full = git("show", "HEAD:.github/workflows/full-sweep-tmpl.yml") if False else None
    out = []
    cache = {}
    for u in units:
        rid = str(u["records"][0]); d = dump[rid]; row = d
        hw, prec, tp, conc, isl, osl = row["hardware"], row["precision"], row["decode_tp"], row["conc"], row["isl"], row["osl"]
        date = d["date"]
        c_end, c_start = commit_at70(date, True), commit_at70(date, False)
        # workflow max-model-len for the sweep (full-sweep-tmpl.yml): 2048 for 1k1k, 9216 for the 8k cases
        mml = 2048 if (isl, osl) == (1024, 1024) else 9216
        variants = []
        scripts = [f"benchmarks/70b_{prec}_{hw}_docker.sh", f"benchmarks/70b_{prec}_{hw}_slurm.sh"]
        for sc in scripts:
            try: git("cat-file", "-e", f"{c_end}:{sc}")
            except subprocess.CalledProcessError: continue
            wf = workflow_inputs(c_end, hw, prec)
            env = {"MODEL": (wf or {}).get("model") or "", "TP": tp, "CONC": conc, "ISL": isl, "OSL": osl, "MAX_MODEL_LEN": mml,
                   "RANDOM_RANGE_RATIO": "0.8", "RESULT_FILENAME": "x", "PORT": "8888", "PORT_OFFSET": "0", "SLURM_JOB_ID": "1", "SLURMD_NODENAME": "n"}
            key = (c_end, sc, json.dumps(env, sort_keys=True))
            if key not in cache:
                got = run_script(c_end, sc, env)
                cache[key] = got
            got = cache[key]
            a = normalise(final_args(got)) if "error" not in got else {"error": got}
            variants.append({"script": sc, "workflow": wf, "args": a, "env": got.get("env"), "config_yaml": got.get("config_yaml")})
        out.append({"unit": u["unit"], "split": u["split"], "cell": u["cell"], "hardware": hw, "precision": prec, "tp": tp, "conc": conc,
                    "isl": isl, "osl": osl, "date": date, "commit": c_end,
                    "scripts_same_start_end": {sc: git("rev-parse", f"{c_end}:{sc}").strip() == git("rev-parse", f"{c_start}:{sc}").strip() for sc in scripts if True and subprocess.call(["git","-C",REPO,"cat-file","-e",f"{c_end}:{sc}"])==0},
                    "variants": variants})
    json.dump(out, open(f"{OUT}/derived-213.json", "w"), indent=1, default=str)
    c = collections.Counter((o["split"], o["hardware"], o["precision"]) for o in out)
    print("units", len(out), dict(c))
    amb = [o for o in out if len(o["variants"]) > 1]
    same = [o for o in amb if all(v["args"] == o["variants"][0]["args"] for v in o["variants"])]
    print("units with two candidate scripts:", len(amb), "of which both give the same arguments:", len(same))
    err = [o for o in out if any("error" in v["args"] for v in o["variants"])]
    print("units where a script did not start vllm:", len(err))

if __name__ == "__main__":
    {"validate": validate, "derive": lambda: derive()}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__))()
