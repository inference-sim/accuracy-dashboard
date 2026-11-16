#!/usr/bin/env python3
"""Score a first-party corpus of runs on the engine release BLIS runs, as a corpus of its own, by the same path an
InferenceX point takes (#91).

InferenceX alone gives no G1 point: no in-scope run of it used vLLM v0.32.0. Runs made on that release with their
whole records can, and they answer the question users ask: does BLIS rank configurations as measurement ranks them?

THE SAME PATH. A first-party run is not given a scenario of its own: it holds the records an InferenceX run holds,
and the harness builds its scenario from them exactly as it builds an InferenceX point's (design §11.2: State,
Estimate, Decide, Price; COV-3, COV-12, X19). `freeze` turns the corpus into a frozen pull of the shape `cli.py pull`
writes (a manifest and each point's files), and `score` scores that pull with the scorer every InferenceX point goes
through (score.score_points): the run's server log and launch configuration are read and copied into the engine block, every
field is decided by the engine's field list, every value no record holds is a named substitution or a G5 reason,
the requests are the run's client's own (COV-12), and the point is graded by grade.grade. A private corpus takes no
shortcut the public one does not: nothing here builds, checks or grades a scenario.

Each run states its client, because the harness replays a client's requests only where it can recompute them:

  inferencex  InferenceX's single-turn client (utils/bench_serving/benchmark_serving.py), its command line in the
              run's job log (`job_log`) and its commit (`client.commit`): the scorer recomputes its seeded requests.
  agentx      an AgentX agentic run, with its client export (`client_export`) and command (`client_command`).

A run of any other client is frozen with the scorer's own reason, `client_scenario_not_replayable:<client>`, so it is
G5 value_not_recorded, counted, never simulated on requests it did not send.

The report reads the scorer's outcomes and its Results and compares, per configuration
and concurrency, five metrics of the simulator's registry by id, each checked against `blis metrics` (DEV-8):

  output_tok_s        measured: the client's output tokens per second (InferenceX `output_tput_per_gpu` times the
                      run's GPUs); simulated: output tokens of the main phase's completed requests over the span from
                      the first arrival to the last completion
  interactivity_p50   1000 over the p50 of TPOT in ms (measured: the client's `median_tpot`)
  ttft_p99_ms         the p99 of TTFT (measured: the client's `p99_ttft`)
  itl_p50_ms          the p50 of every inter-token latency, pooled (measured: the client's `median_itl`); BLIS's Result
                      rows carry no per-token times yet (inference-sim#2128), so the simulated side has none
  cache_hit_rate      the client records none, so no measured figure; the simulated one is reported alone

and, for each workload's set of configurations, whether BLIS orders them as the runs do (Spearman, Kendall, top-1 and
the regret of BLIS's top choice, ranking.group_metrics over output throughput per GPU). Grades are the scorer's (score.grade_outcome).

THE CORPUS IS READ FROM A PATH GIVEN AT RUN TIME AND IS NEVER COMMITTED, and neither is its pull, its contract or its
report. Every path the tool writes, and the corpus itself, is refused inside any work tree of this repository. For a
private corpus the full report goes only to `--out`; what may be published (`--public-out`) is the label given on the
command line and the grade counts, only over at least 10 runs, a grade held by fewer than 10 shown as "fewer than 10"
(design D7). The label must be a short slug sharing no word with the corpus's path and holding none of the private
names given at run time (`--private-names`).

Layout: <corpus>/corpus.json, with each run's files beside it.

    {"format": "first-party-corpus-2", "visibility": "private" | "public",
     "runs": [{"id": "r1", "workload": "w",
               "row": {... the run as InferenceX's API records a row: model, hardware, precision, framework,
                       benchmark_type, isl, osl, conc, image, date, spec_method, disagg, is_multinode, the pool sizes
                       (decode_tp, decode_ep, decode_dp_attention, num_decode_gpu, ...) and `metrics`, the client's own
                       statistics under InferenceX's names (mean_ttft, mean_tpot, p99_ttft, median_tpot, median_itl,
                       output_tput_per_gpu, in seconds as InferenceX records them) ...},
               "client": {"name": "inferencex", "repo": "SemiAnalysisAI/InferenceX", "commit": "<40 hex>"},
               "files": {"server_log": "r1/vllm.log", "launch_config": "r1/launch.json", "job_log": "r1/client.log"}}]}

    corpus.py score --corpus DIR --blis BUILD --sim-build TAG --catalog DIR --catalog-release TAG
                    --registry DIR --registry-release TAG --fields FIELDS.json --corpus-dir CORPORA
                    --harness-commit SHA --work DIR --out DIR [--label SLUG --public-out FILE] [--private-names FILE]

`score` checks and builds the scorer's inputs as `cli.py score` does (the build at its release, its stack's engine
release, the field list for that release, the checked AgentX corpora, the metric definitions), freezes the corpus into
a pull under --work, and scores it with score.score_points, the function `harness/run.sh` runs for every InferenceX
point. It writes no contract: the contract's point identity is the InferenceX ledger's (contract.point_id refuses
another source), and the outcomes are the same either way.

Every accuracy change scored on such a corpus follows design §12.3: pre-registered, fitted on the fit split and judged
once on held-out data; this tool scores and reports, it fits nothing.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ingest"))
import contract  # noqa: E402
import grade as gr  # noqa: E402
import ranking as rk  # noqa: E402

FORMAT = "first-party-corpus-2"
SOURCE = "first-party"
CLIENTS = {"inferencex": "single_turn", "agentx": "agentic_traces"}
ROLES = ("server_log", "launch_config", "job_log", "result_json", "client_export", "client_command")
MIN_UNITS = 10          # design D7: no published aggregate of a non-public corpus over fewer than 10 units
FEW = "fewer than 10"
LABEL = re.compile(r"^[a-z0-9][a-z0-9-]{2,39}$")
FIGURES = {
    "output_tok_s": {"formula": "output_throughput", "statistic": "rate", "population": "requests",
                     "unit": "tokens_per_s", "percentile_method": "", "denominator": "window"},
    "interactivity_p50": {"formula": "interactivity", "statistic": "p50", "population": "requests_min_2_output_tokens",
                          "unit": "tokens_per_s_per_user", "percentile_method": "numpy_linear", "denominator": ""},
    "ttft_p99_ms": {"formula": "ttft", "statistic": "p99", "population": "requests", "unit": "ms",
                    "percentile_method": "numpy_linear", "denominator": ""},
    "itl_p50_ms": {"formula": "itl", "statistic": "p50", "population": "tokens", "unit": "ms",
                   "percentile_method": "numpy_linear", "denominator": ""},
    "cache_hit_rate": {"formula": "cache_hit_rate", "statistic": "rate", "population": "admissions",
                       "unit": "fraction", "percentile_method": "", "denominator": ""},
}
METRICS = tuple(FIGURES)


class CorpusError(ValueError):
    pass


# ------------------------------------------------------------------------------------------- where things may live

def _common_dir(path: Path) -> Path | None:
    r = subprocess.run(["git", "-C", str(path), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                       capture_output=True, text=True)
    return Path(r.stdout.strip()).resolve() if r.returncode == 0 and r.stdout.strip() else None


def inside_repo(path: Path) -> bool:
    """Whether a path is inside any work tree of this repository (this checkout or another worktree of it)."""
    p = Path(path).resolve()
    if p == ROOT or ROOT in p.parents:
        return True
    probe = p
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    if not probe.is_dir():
        probe = probe.parent
    ours, theirs = _common_dir(ROOT), _common_dir(probe)
    return ours is not None and ours == theirs


def outside(*paths: Path) -> None:
    for p in paths:
        if p is not None and inside_repo(p):
            raise CorpusError("a corpus, its pull, its contract and its report are never in a work tree of this "
                              "repository; give paths outside it")


def check_label(label, corpus: Path, private_names: list[str]) -> None:
    """The label a private corpus publishes under must name nothing private."""
    if not isinstance(label, str) or not LABEL.match(label):
        raise CorpusError(f"the label {label!r} is not a short slug of lower-case letters, digits and hyphens")
    words = {w for part in corpus.resolve().parts for w in re.split(r"[^a-z0-9]+", part.lower()) if len(w) >= 3}
    if words & set(label.split("-")):
        raise CorpusError(f"the label {label!r} shares a word with the corpus's path; choose a label of its own")
    if any(n and n.lower() in label for n in private_names):
        raise CorpusError(f"the label {label!r} holds a private name")


# ------------------------------------------------------------------------------------------- the corpus

def load(corpus: Path) -> dict:
    outside(corpus)
    doc = json.loads((corpus / "corpus.json").read_text())
    if doc.get("format") != FORMAT:
        raise CorpusError(f"corpus.json format {doc.get('format')!r}, want {FORMAT}")
    if doc.get("visibility") not in ("private", "public"):
        raise CorpusError("corpus.json must say whether it is private or public (visibility)")
    ids = [r.get("id") for r in doc["runs"]]
    if len(set(ids)) != len(ids) or not all(isinstance(i, str) and i for i in ids):
        raise CorpusError("every run has an id of its own")
    for r in doc["runs"]:
        for k in ("workload", "row", "client", "files"):
            if k not in r:
                raise CorpusError(f"run {r['id']!r} states no {k}")
        unknown = set(r["files"]) - set(ROLES)
        if unknown:
            raise CorpusError(f"run {r['id']!r}: files names {sorted(unknown)}, not one of {ROLES}")
        for k in ("model", "hardware", "precision", "framework", "benchmark_type", "conc", "image", "date", "metrics"):
            if k not in r["row"]:
                raise CorpusError(f"run {r['id']!r}: its row states no {k}")
    return doc


def identity(row: dict) -> dict:
    """A first-party run's identity: the eleven fields of an InferenceX unit's, its source `first-party`, no
    benchmark run, measured on its own date (contract.IDENTITY_FIELDS)."""
    return {"source": SOURCE, "model": row["model"], "hardware": row["hardware"], "precision": row["precision"],
            "framework": row["framework"], "benchmark_type": row["benchmark_type"],
            "configuration_hash": contract.configuration_hash(row), "recipe_fingerprint": row.get("recipe_fingerprint"),
            "conc": int(row["conc"]), "measured_date": str(row["date"])[:10], "benchmark_run": None}


def point_id(ident: dict) -> str:
    """The run's id: the SHA-256 of its identity's canonical JSON, as a ledger unit's is (contract.point_id, which
    refuses a source other than InferenceX's, since the ledger holds InferenceX's units only)."""
    if set(ident) != set(contract.IDENTITY_FIELDS):
        raise CorpusError(f"identity fields {sorted(ident)}, want {sorted(contract.IDENTITY_FIELDS)}")
    return hashlib.sha256(contract.canonical_dumps(ident).encode("utf-8")).hexdigest()


def client_reasons(run: dict) -> list[str]:
    """The scorer's reason for a client whose requests the harness cannot recompute."""
    name = (run.get("client") or {}).get("name")
    if name not in CLIENTS:
        return [f"client_scenario_not_replayable:{name or 'unstated'}"]
    if CLIENTS[name] != run["row"]["benchmark_type"]:
        return [f"client_scenario_not_replayable:{name}_{run['row']['benchmark_type']}"]
    return []


def freeze(corpus: Path, out: Path, resolve_build) -> dict:
    """The corpus as a frozen pull the scorer reads, of the shape cli.py pull writes. resolve_build(image, server_log)
    is build.Resolver.resolve: the run's build is resolved as an InferenceX run's is."""
    outside(corpus, out)
    doc = load(corpus)
    points = []
    for run in doc["runs"]:
        row = {**run["row"], "id": run["id"], "run_url": None}
        ident = identity(row)
        pid = point_id(ident)
        pdir = out / "points" / pid
        pdir.mkdir(parents=True, exist_ok=True)
        files, server_log = {}, None
        for role, rel in sorted(run["files"].items()):
            raw = (corpus / rel).read_bytes()
            if role == "server_log":
                server_log = raw.decode("utf-8", "replace")
            gz = gzip.compress(raw, mtime=0)
            (pdir / f"{role}.gz").write_bytes(gz)
            files[role] = {"path": f"{role}.gz", "sha256": hashlib.sha256(gz).hexdigest(), "from": f"{SOURCE}:{role}"}
        client = run.get("client") or {}
        entry = {"point_id": pid, "identity": ident, "row": row, "records": [run["id"]],
                 "measurements": [{"record": run["id"], "metrics": row["metrics"]}], "files": files,
                 "reasons": client_reasons(run), "build": resolve_build(row["image"], server_log),
                 "client_args": {"job": "first-party"} if "job_log" in files else None,
                 "client_args_reason": None if "job_log" in files else "job_log_not_recorded",
                 "client_commit": ({"repo": client["repo"], "sha": client["commit"], "date": f"{row['date']}T00:00:00Z"}
                                   if client.get("repo") and re.fullmatch(r"[0-9a-f]{40}", str(client.get("commit")))
                                   else None)}
        points.append(entry)
    import build as bd
    dates = sorted(p["identity"]["measured_date"] for p in points)
    manifest = {"pulled_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "vllm_ref": bd.VLLM_REF,
                "vllm_max_distance": bd.VLLM_MAX_DISTANCE, "window": [dates[0], dates[-1]] if dates else ["", ""],
                "base_models": {}, "ledger": {"source": SOURCE, "unlisted": []}, "undated_row_ids": [],
                "unnamed_slugs": [], "points": sorted(points, key=lambda p: p["point_id"])}
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    (out / "units.txt").write_text("".join(p["point_id"] + "\n" for p in manifest["points"]))
    (out / "runs.json").write_text(json.dumps({p["records"][0]: p["point_id"] for p in points}, indent=1, sort_keys=True) + "\n")
    return manifest


# ------------------------------------------------------------------------------------------- figures

def percentile(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * q / 100
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def check_registry(registry: dict) -> list[str]:
    """Why the build's metric registry does not define the five figures as this tool computes them; [] when it does."""
    out = []
    for mid, want in FIGURES.items():
        d = registry.get(mid)
        if d is None:
            out.append(f"the simulator's metric registry has no {mid}")
            continue
        out += [f"the simulator's {mid} has {k} {d.get(k)!r}; this tool computes it with {v!r}"
                for k, v in want.items() if (d.get(k) or "") != v]
    return out


def measured_figures(metrics: dict, gpus: int) -> dict:
    """The five figures from the client's own statistics (InferenceX's names, in seconds)."""
    def ms(k):
        v = metrics.get(k)
        return None if v is None else float(v) * 1000
    med_tpot = ms("median_tpot")
    tput = metrics.get("output_tput_per_gpu")
    return {"output_tok_s": None if tput is None else float(tput) * gpus,
            "interactivity_p50": 1000 / med_tpot if med_tpot else None,
            "ttft_p99_ms": ms("p99_ttft"), "itl_p50_ms": ms("median_itl"), "cache_hit_rate": None}


def simulated_figures(rows: list[dict], n_main: int | None) -> dict:
    """The five figures from a Result's request rows: the main phase's completed requests (request_0 to
    request_<n-1>; a warm-up copy or holder round is not one)."""
    import inferencex_client as ix
    def main(r):
        try:
            return n_main is None or ix.request_index(r["id"]) < n_main
        except ValueError:
            return False
    done = [r for r in rows if r.get("fate") == "completed" and main(r)]
    if not done:
        return {m: None for m in METRICS}
    t0 = min(r["arrival_us"] for r in done)
    t1 = max(r["arrival_us"] + (r.get("e2e_us") or 0) for r in done)
    tpots = [r["tpot_us"] / 1000 for r in done if r.get("tpot_us") and (r.get("output_tokens") or 0) >= 2]
    itls = [x / 1000 for r in done for x in (r.get("itl_us") or [])]
    prompt = sum(r.get("prompt_tokens") or 0 for r in done)
    cached = sum((r.get("cached_local_tokens") or 0) + (r.get("cached_external_tokens") or 0) for r in done)
    p50 = percentile(tpots, 50)
    return {"output_tok_s": sum(r.get("output_tokens") or 0 for r in done) / ((t1 - t0) / 1e6) if t1 > t0 else None,
            "interactivity_p50": 1000 / p50 if p50 else None,
            "ttft_p99_ms": percentile([r["ttft_us"] / 1000 for r in done if r.get("ttft_us") is not None], 99),
            "itl_p50_ms": percentile(itls, 50), "cache_hit_rate": cached / prompt if prompt else None}


def errors(meas: dict, pred: dict) -> dict:
    out = {}
    for m in METRICS:
        a, b = meas.get(m), pred.get(m)
        out[m] = None if a is None or b is None else (100 * (b - a) if m == "cache_hit_rate" else
                                                      100 * (b - a) / a if a else None)
    return out


def ranking(runs: list[dict]) -> dict:
    groups = defaultdict(list)
    for r in runs:
        if r["status"] != "scored":
            continue
        m, p = r["measured"]["output_tok_s"], r["simulated"]["output_tok_s"]
        if m is not None and p is not None:
            groups[r["workload"]].append({"key": r["id"], "meas": m / r["gpus"], "pred": p / r["gpus"]})
    return {w: rk.group_metrics(items) for w, items in sorted(groups.items()) if len(items) >= rk.MIN_CONFIGS}


# ------------------------------------------------------------------------------------------- the report

def score(*, corpus: Path, work: Path, env, resolve_build, workers: int = 1) -> tuple[dict, list]:
    """Freeze the corpus into a pull under `work` and score it with the harness's scorer (score.score_points, the
    function harness/run.sh runs for every InferenceX point), then report from its outcomes and Results."""
    import score as sc
    outside(corpus, work)
    pull = work / "pull"
    manifest = freeze(corpus, pull, resolve_build)
    outcomes = sc.score_points(manifest["points"], pull, work / "score", env, workers=workers)
    return report(corpus=corpus, outcomes=outcomes, pull=pull, work=work / "score", env=env), outcomes


def result_of(work: Path, pid: str, benchmark_type: str) -> dict | None:
    """The Result the scorer validated and kept for a point (score.py's cache in its work directory)."""
    p = work / "single_turn" / pid / "result.json" if benchmark_type == "single_turn" else work / "results" / f"{pid}.json"
    return json.loads(p.read_text()) if p.is_file() else None


def report(*, corpus: Path, outcomes: list, pull: Path, work: Path, env) -> dict:
    doc = load(corpus)
    by = {o.point_id: o for o in outcomes}
    pids = json.loads((pull / "runs.json").read_text())
    runs = []
    for run in doc["runs"]:
        row, pid = run["row"], pids[run["id"]]
        o = by[pid]
        gpus = int(row.get("num_decode_gpu") or row.get("decode_tp") or 1)
        status = "failed" if o.faults else "scored" if o.fidelity is not None else "not_scored"
        base = {"id": run["id"], "point_id": pid, "workload": run["workload"], "concurrency": int(row["conc"]),
                "gpus": gpus, "row": {k: v for k, v in row.items() if k != "metrics"}, "client": run["client"],
                "status": status, "grade": (o.fidelity or {}).get("grade") or (gr.G5 if status == "not_scored" else "failed"),
                "run_release": o.run_release}
        if status != "scored":
            runs.append({**base, "reasons": o.g5_reasons or o.faults})
            continue
        res = result_of(work, pid, row["benchmark_type"])
        if res is None:
            raise CorpusError(f"run {run['id']} is scored but the scorer kept no Result for it")
        n_main = 10 * int(row["conc"]) if row["benchmark_type"] == "single_turn" else None
        meas = measured_figures(row["metrics"], gpus)
        sim = simulated_figures(res.get("request_rows") or [], n_main)
        runs.append({**base, "substitutions": o.fidelity["substitutions"], "scenario_args": o.fidelity.get("args"),
                     "measured": meas, "simulated": sim, "errors_pct": errors(meas, sim)})
    grades = Counter(r["grade"] for r in runs)
    return {"format": "first-party-corpus-report-2", "visibility": doc["visibility"],
            "engine_release": env.engine_release, "simulator": env.simulator(), "harness_commit": env.harness_commit,
            "runs": runs, "grades": {g: grades.get(g, 0) for g in (*gr.GRADES, "failed")}, "ranking": ranking(runs)}


def public_summary(rep: dict, label: str) -> dict:
    if rep["visibility"] == "public":
        return {**rep, "label": label}
    n = len(rep["runs"])
    if n < MIN_UNITS:
        raise CorpusError(f"the corpus has {n} runs; a non-public corpus publishes nothing over fewer than {MIN_UNITS} (D7)")
    return {"format": "first-party-corpus-grades-2", "label": label, "engine_release": rep["engine_release"],
            "runs": n, "min_units": MIN_UNITS,
            "grades": {g: (c if c == 0 or c >= MIN_UNITS else FEW) for g, c in rep["grades"].items()}}


def markdown(rep: dict, label: str) -> str:
    def f(x):
        return "-" if x is None else f"{x:.3g}"
    L = [f"# First-party corpus: {label}", "",
         f"Scored by the harness at {rep['harness_commit']}, simulator {(rep.get('simulator') or {}).get('build')}, "
         f"engine release {rep['engine_release']}. Grades: " + ", ".join(f"{g} {n}" for g, n in rep["grades"].items()) + ".", "",
         "| Run | Workload | Conc | Status | Grade | " + " | ".join(f"{m} measured | simulated | error" for m in METRICS)
         + " | Configuration |", "|---|---|---|---|---|" + "---|---|---|" * len(METRICS) + "---|"]
    for r in rep["runs"]:
        cells = " | ".join(f"{f((r.get('measured') or {}).get(m))} | {f((r.get('simulated') or {}).get(m))} | "
                           f"{f((r.get('errors_pct') or {}).get(m))}" for m in METRICS)
        L.append(f"| {r['id']} | {r['workload']} | {r['concurrency']} | {r['status']} | {r['grade']} | {cells} | "
                 f"`{json.dumps(r['row'], sort_keys=True)}` |")
    L += ["", "| Workload | Configurations | Spearman | Kendall | Top-1 | Regret of BLIS's top choice |", "|---|---|---|---|---|---|"]
    for w, m in rep["ranking"].items():
        L.append(f"| {w} | {m['configs']} | {f(m['spearman'])} | {f(m['kendall'])} | {m['top1']} | {f(m['regret'])} |")
    return "\n".join(L) + "\n"


def env_for(a):
    """The scorer's inputs, checked and built as cli.py score builds them for an InferenceX pull."""
    import cli
    import fields as fl
    import resolve_agentic_corpus as rac
    import score as sc
    import settings as st
    import stack as sk
    import support as sp
    blis = Path(a.blis).resolve()
    bad = cli.check_blis_inputs(blis, a.catalog_release, a.registry_release, a.sim_build)
    bad += cli.check_harness_commit(a.harness_commit)
    if not bad:
        bad += cli.check_metric_definitions(blis)
    try:
        engine_release = cli.read_stack(blis, None).engine("vllm")
        field_list, fields_sha = cli.read_fields(Path(a.fields), engine_release)
        corpora = rac.checked_corpora(Path(a.catalog), Path(a.corpus_dir))
    except (sk.StackError, fl.FieldsError, rac.CorpusError, OSError, ValueError) as e:
        bad.append(str(e))
    if bad:
        raise CorpusError("; ".join(bad))
    sim = blis.parent
    env = sc.Env(blis=str(blis), blis_release=cli._git(sim, "describe", "--tags", "--exact-match") or "unknown",
                 blis_commit=cli._git(sim, "rev-parse", "HEAD"), catalog=Path(a.catalog).resolve(),
                 catalog_release=a.catalog_release, registry=Path(a.registry).resolve(), registry_release=a.registry_release,
                 kernel="unknown", corpora=corpora, vllm_ref=__import__("build").VLLM_REF, field_list=field_list,
                 fields_sha256=fields_sha, base_models={}, vllm_defaults=st.load_vllm_defaults()[0],
                 vllm_defaults_release=st.vllm_defaults_release(), engine_release=engine_release)
    env.sim_build = a.sim_build or env.blis_release
    env.harness_commit = a.harness_commit
    env.catalog_obj = sp.Catalog(blis=str(blis), root=env.catalog)
    env.parts = sp.registry_parts(env.registry)
    return env


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score")
    for k in ("corpus", "work", "out", "catalog", "registry", "fields", "corpus-dir"):
        s.add_argument(f"--{k}", required=True, type=Path)
    s.add_argument("--blis", required=True, help="the scoring build, in the inference-sim checkout it was built from")
    s.add_argument("--sim-build", help="the build: a release tag or a full commit (default: the checkout's release tag)")
    s.add_argument("--catalog-release", required=True)
    s.add_argument("--registry-release", required=True)
    s.add_argument("--harness-commit", required=True, help="the full commit of this harness checkout (X8)")
    s.add_argument("--workers", type=int, default=1)
    s.add_argument("--label")
    s.add_argument("--public-out", type=Path)
    s.add_argument("--private-names", type=Path)
    a = ap.parse_args(argv)
    try:
        outside(a.corpus, a.work, a.out, a.private_names)
        names = [x.strip() for x in a.private_names.read_text().splitlines() if x.strip()] if a.private_names else []
        load(a.corpus)
        if a.public_out and not a.label:
            raise CorpusError("--public-out needs --label, the name the corpus is published under")
        if a.label:
            check_label(a.label, a.corpus, names)
        import blis_commands as bc
        bad = check_registry(bc.metrics(a.blis))
        if bad:
            raise CorpusError("; ".join(bad))
        env = env_for(a)
        import build as bd
        import clients
        token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip() or None
        resolver = bd.Resolver(registry=clients.DockerHubRegistry(), github=clients.GitHubREST(token), ref=bd.VLLM_REF)
        rep, _ = score(corpus=a.corpus, work=a.work, env=env, workers=a.workers,
                       resolve_build=lambda image, log: resolver.resolve(image or "", log).record())
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "report.json").write_text(json.dumps({**rep, "label": a.label}, indent=1, sort_keys=True) + "\n")
        (a.out / "report.md").write_text(markdown(rep, a.label or "unlabelled"))
        if a.public_out:
            text = json.dumps(public_summary(rep, a.label), indent=1, sort_keys=True) + "\n"
            if any(n.lower() in text.lower() for n in names):
                raise CorpusError("the public summary would hold a private name")
            a.public_out.write_text(text)
        print(f"{len(rep['runs'])} runs: " + ", ".join(f"{g} {n}" for g, n in rep["grades"].items()))
    except CorpusError as e:
        print(f"corpus: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
