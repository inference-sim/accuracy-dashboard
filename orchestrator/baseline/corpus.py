#!/usr/bin/env python3
"""Score a first-party corpus of runs on the engine release BLIS runs, as a corpus of its own (#91).

InferenceX alone gives no G1 point: no in-scope run of it used vLLM v0.32.0. Runs made on that release with their
whole configuration and their per-request exports can, and they answer the question users ask: does BLIS rank
configurations as measurement ranks them? This tool scores such a corpus and compares, per configuration and
concurrency, over the steady middle window of each run and across the whole cluster:

  output throughput     output tokens of the window's completed requests over the window's length (tokens/s)
  interactivity p50     the median over the window's requests of 1 / TPOT (output tokens per second per user)
  TTFT p99              the 99th percentile of the window's TTFTs (ms)
  ITL p50               the median over the window's requests of TPOT, the request's mean inter-token latency (ms):
                        the Result's request rows carry no per-token times, so both sides use the per-request mean
                        (one definition on both sides, DEV-8)
  cache-read rate       cached prompt tokens over prompt tokens, over the window's requests

and, for each set of configurations measured on one workload, whether BLIS orders them as the runs do: Spearman and
Kendall concordance of output throughput per GPU, and the regret of BLIS's top choice (ranking.group_metrics).

The steady middle window. Both sides use one rule: the requests that arrived between the first arrival plus a
fraction f of the arrival span and the last arrival less f (the corpus states f; 0.1 when it does not), so the ramp
up and the drain are out of both. A side with no completed request in its window has no figure.

THE CORPUS IS READ FROM A PATH GIVEN AT RUN TIME AND IS NEVER COMMITTED. The tool refuses a corpus directory, or an
output for a private corpus, inside this repository's checkout. For a private corpus (`"visibility": "private"`) the
full report, with every configuration in full beside its numbers, goes only to `--out`; the only thing written for
publication (`--public-out`) is the corpus's label and its grade counts, as accuracy-dashboard#91 states.

Layout: <corpus>/corpus.json, with each run's files beside it.

    {"format": "first-party-corpus-1", "label": "a public-safe name", "visibility": "private" | "public",
     "window_trim_fraction": 0.1,
     "runs": [{"id": "r1", "workload": "w", "concurrency": 8, "gpus": 8,
               "configuration": {... the run's full engine and deployment configuration, as it ran ...},
               "build": {"image": "vllm/vllm-openai:v0.32.0", "banner": "0.32.0"},
               "measured_requests": "r1/requests.jsonl",
               "replay": ["replay", "--scenario", "r1/scenario.yaml", ...],
               "differences": [{"subject": "...", "detail": "..."}]}]}

A source that publishes aggregates and no per-request rows (the configiq dataset's GuideLLM rows) states
`measured_figures` instead: the five figures by the names above, over the window its client measured, which `window`
names; such a run's window is the source's, not the rule above, and the report says so per run.

`measured_requests` holds one JSON object per request with the Result's request-row names: id, fate, arrival_us,
ttft_us, tpot_us, e2e_us, prompt_tokens, output_tokens, cached_local_tokens, cached_external_tokens. `replay` is the
`blis` command that replays the run's requests, without the binary; the harness runs it with the build it scores
(`--blis`) and adds `--catalog`, `--registry` and `--format json`; a path argument is read relative to the run's
corpus. `differences` names every way the replayed requests differ from the ones the run sent (COV-12); each is a
G2 `client_difference`.

A run is graded by the same rules as an InferenceX point (grade.grade): its release from its recorded build
(grade.run_release), the Result's coefficient methods, every G1 condition the harness cannot yet evaluate named
`unevaluated`, and the corpus's differences.

Every accuracy change scored on such a corpus follows design §12.3: it is pre-registered, fitted on the fit split
and judged once on held-out data; this tool scores and reports, it fits nothing.

    corpus.py score --corpus DIR --blis BIN --catalog DIR --registry DIR --engine-release 0.32.0 --out DIR
                    [--public-out FILE]
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ingest"))
import grade as gr  # noqa: E402
import ranking as rk  # noqa: E402

FORMAT = "first-party-corpus-1"
METRICS = ("output_throughput_tps", "interactivity_p50_tps", "ttft_p99_ms", "itl_p50_ms", "cache_read_rate")
DEFAULT_TRIM = 0.1


class CorpusError(ValueError):
    pass


# ------------------------------------------------------------------------------------------- figures

def percentile(xs: list[float], q: float) -> float | None:
    """The q-th percentile by linear interpolation between closest ranks (numpy's default)."""
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * q / 100
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def window(rows: list[dict], trim: float) -> tuple[int, int] | None:
    arrivals = sorted(r["arrival_us"] for r in rows)
    if not arrivals:
        return None
    span = arrivals[-1] - arrivals[0]
    return arrivals[0] + round(trim * span), arrivals[-1] - round(trim * span)


def figures(rows: list[dict], trim: float) -> dict:
    """The five figures over the steady middle window of one run's request rows (measured or simulated)."""
    w = window(rows, trim)
    done = [r for r in rows if r.get("fate") == "completed" and w and w[0] <= r["arrival_us"] <= w[1]]
    if not done:
        return {m: None for m in METRICS} | {"requests": 0}
    start = min(r["arrival_us"] for r in done)
    end = max(r["arrival_us"] + (r.get("e2e_us") or 0) for r in done)
    tpots = [r["tpot_us"] for r in done if r.get("tpot_us")]
    prompt = sum(r.get("prompt_tokens") or 0 for r in done)
    cached = sum((r.get("cached_local_tokens") or 0) + (r.get("cached_external_tokens") or 0) for r in done)
    p50 = percentile(tpots, 50)
    return {"requests": len(done),
            "output_throughput_tps": sum(r.get("output_tokens") or 0 for r in done) / ((end - start) / 1e6) if end > start else None,
            "interactivity_p50_tps": percentile([1e6 / t for t in tpots], 50),
            "ttft_p99_ms": (lambda v: None if v is None else v / 1000)(percentile([r["ttft_us"] for r in done if r.get("ttft_us") is not None], 99)),
            "itl_p50_ms": None if p50 is None else p50 / 1000,
            "cache_read_rate": cached / prompt if prompt else None}


def errors(meas: dict, pred: dict) -> dict:
    """Signed percent error of each figure; the cache-read rate, a ratio, as a difference in points."""
    out = {}
    for m in METRICS:
        a, b = meas.get(m), pred.get(m)
        if a is None or b is None:
            out[m] = None
        elif m == "cache_read_rate":
            out[m] = 100 * (b - a)
        else:
            out[m] = 100 * (b - a) / a if a else None
    return out


def ranking(runs: list[dict]) -> dict:
    """Per workload, whether BLIS orders its configurations (each run a configuration at a concurrency) by output
    throughput per GPU as the runs do."""
    groups = defaultdict(list)
    for r in runs:
        m, p = r["measured"]["output_throughput_tps"], (r.get("simulated") or {}).get("output_throughput_tps")
        if m is None or p is None:
            continue
        groups[r["workload"]].append({"key": r["id"], "meas": m / r["gpus"], "pred": p / r["gpus"]})
    return {w: rk.group_metrics(items) for w, items in sorted(groups.items()) if len(items) >= rk.MIN_CONFIGS}


# ------------------------------------------------------------------------------------------- the corpus

def inside_repo(path: Path) -> bool:
    p = path.resolve()
    return p == ROOT or ROOT in p.parents


def load(corpus: Path) -> dict:
    if inside_repo(corpus):
        raise CorpusError(f"{corpus} is inside this checkout; a corpus is read from a path given at run time and never committed")
    doc = json.loads((corpus / "corpus.json").read_text())
    if doc.get("format") != FORMAT:
        raise CorpusError(f"corpus.json format {doc.get('format')!r}, want {FORMAT}")
    if doc.get("visibility") not in ("private", "public"):
        raise CorpusError("corpus.json must say whether it is private or public (visibility)")
    ids = [r["id"] for r in doc["runs"]]
    if len(set(ids)) != len(ids):
        raise CorpusError("two runs share an id")
    for r in doc["runs"]:
        for k in ("workload", "concurrency", "gpus", "configuration", "build", "replay"):
            if k not in r:
                raise CorpusError(f"run {r.get('id')!r} states no {k}")
        if ("measured_requests" in r) == ("measured_figures" in r):
            raise CorpusError(f"run {r.get('id')!r} states exactly one of measured_requests and measured_figures")
        unknown = set(r.get("measured_figures") or {}) - set(METRICS) - {"requests", "window"}
        if unknown:
            raise CorpusError(f"run {r.get('id')!r}: measured_figures names {sorted(unknown)}, not one of {METRICS}")
    return doc


def read_rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def replay_argv(run: dict, corpus: Path, *, blis: str, catalog: Path, registry: Path) -> list[str]:
    """The run's replay command, its relative paths read in the corpus, with this build's data."""
    argv = []
    for a in run["replay"]:
        if a in ("--catalog", "--registry", "--format"):
            raise CorpusError(f"run {run['id']}: the replay names {a}; the harness sets it")
        p = corpus / a
        argv.append(str(p) if not a.startswith("-") and p.exists() else a)
    return [blis, *argv, "--catalog", str(catalog), "--registry", str(registry), "--format", "json"]


def grade_run(run: dict, doc: dict | None, engine_release: str) -> dict:
    import result
    build = run["build"]
    rel = gr.run_release({"image": build.get("image")}, build.get("banner"))
    subs = [{"kind": "client_difference", "subject": d["subject"], "detail": d["detail"]} for d in run.get("differences") or []]
    subs += result.coefficient_substitutions(doc) if doc is not None else []
    subs += gr.unchecked()
    g = gr.grade(engine_version=engine_release, release=rel, substitutions=subs)
    return {"grade": g.grade, "run_release": rel.version, "substitutions": g.substitutions}


def score(*, corpus: Path, simulate, engine_release: str) -> dict:
    """simulate(run) -> the Result document of the run's replay, or raises (the point is then failed)."""
    doc = load(corpus)
    trim = float(doc.get("window_trim_fraction", DEFAULT_TRIM))
    runs = []
    for r in doc["runs"]:
        meas = (figures(read_rows(corpus / r["measured_requests"]), trim) if "measured_requests" in r
                else {m: r["measured_figures"].get(m) for m in METRICS} | {"requests": r["measured_figures"].get("requests")})
        try:
            res = simulate(r)
        except (CorpusError, subprocess.SubprocessError, OSError, ValueError) as e:
            runs.append({**_public(r), "status": "failed", "fault": str(e)[:300], "measured": meas,
                         "measured_window": _window_of(r, trim)})
            continue
        sim = figures(res.get("request_rows") or [], trim)
        g = grade_run(r, res, engine_release)
        runs.append({**_public(r), "status": "scored", **g, "measured": meas, "simulated": sim,
                     "errors_pct": errors(meas, sim), "measured_window": _window_of(r, trim)})
    grades = Counter(x.get("grade", "failed") for x in runs)
    return {"format": "first-party-corpus-report-1", "label": doc.get("label"), "visibility": doc["visibility"],
            "engine_release": engine_release, "window_trim_fraction": trim, "runs": runs,
            "grades": {g: grades.get(g, 0) for g in (*gr.GRADED, "failed")}, "ranking": ranking(runs)}


def _window_of(r: dict, trim: float) -> str:
    if "measured_figures" in r:
        return f"the source's own: {r['measured_figures'].get('window') or 'not stated'}"
    return f"arrival middle, {trim:g} trimmed at each end"


def _public(r: dict) -> dict:
    return {"id": r["id"], "workload": r["workload"], "concurrency": r["concurrency"], "gpus": r["gpus"],
            "configuration": r["configuration"], "build": r["build"]}


def public_summary(rep: dict) -> dict:
    """What may be published of a corpus: its label and its grade counts; for a public corpus, the report itself."""
    if rep["visibility"] == "public":
        return rep
    return {"format": "first-party-corpus-grades-1", "label": rep["label"], "engine_release": rep["engine_release"],
            "runs": len(rep["runs"]), "grades": rep["grades"]}


def markdown(rep: dict) -> str:
    L = [f"# First-party corpus: {rep['label']}", "",
         f"Engine release {rep['engine_release']}; window: the middle of each run's arrivals, "
         f"{rep['window_trim_fraction']:g} trimmed at each end. Grades: "
         + ", ".join(f"{g} {n}" for g, n in rep["grades"].items()) + ".", "",
         "| Run | Workload | Conc | Grade | " + " | ".join(f"{m} measured | simulated | error" for m in METRICS) + " | Configuration |",
         "|---|---|---|---|" + "---|---|---|" * len(METRICS) + "---|"]

    def f(x):
        return "-" if x is None else f"{x:.3g}"
    for r in rep["runs"]:
        cells = " | ".join(f"{f(r['measured'][m])} | {f((r.get('simulated') or {}).get(m))} | {f((r.get('errors_pct') or {}).get(m))}"
                           for m in METRICS)
        L.append(f"| {r['id']} | {r['workload']} | {r['concurrency']} | {r.get('grade', 'failed')} | {cells} | "
                 f"`{json.dumps(r['configuration'], sort_keys=True)}` |")
    L += ["", "| Workload | Configurations | Spearman | Kendall | Top-1 | Regret of BLIS's top choice |", "|---|---|---|---|---|---|"]
    for w, m in rep["ranking"].items():
        L.append(f"| {w} | {m['configs']} | {f(m['spearman'])} | {f(m['kendall'])} | {m['top1']} | {f(m['regret'])} |")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score")
    s.add_argument("--corpus", required=True, type=Path)
    s.add_argument("--blis", required=True)
    s.add_argument("--catalog", required=True, type=Path)
    s.add_argument("--registry", required=True, type=Path)
    s.add_argument("--engine-release", required=True)
    s.add_argument("--out", required=True, type=Path, help="the full report's directory")
    s.add_argument("--public-out", type=Path, help="what may be published: the label and the grade counts")
    a = ap.parse_args(argv)
    try:
        doc = load(a.corpus)
        if doc["visibility"] == "private" and inside_repo(a.out):
            raise CorpusError(f"{a.out} is inside this checkout; a private corpus's report never is")

        def simulate(run):
            argv_ = replay_argv(run, a.corpus, blis=a.blis, catalog=a.catalog, registry=a.registry)
            out = subprocess.run(argv_, capture_output=True, text=True, timeout=7200)
            if out.returncode != 0:
                raise CorpusError(f"blis exited {out.returncode}: {out.stderr.strip()[-300:]}")
            return json.loads(out.stdout)
        rep = score(corpus=a.corpus, simulate=simulate, engine_release=a.engine_release)
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "report.json").write_text(json.dumps(rep, indent=1, sort_keys=True) + "\n")
        (a.out / "report.md").write_text(markdown(rep))
        if a.public_out:
            a.public_out.write_text(json.dumps(public_summary(rep), indent=1, sort_keys=True) + "\n")
        print(f"scored {len(rep['runs'])} runs: " + ", ".join(f"{g} {n}" for g, n in rep["grades"].items()))
    except CorpusError as e:
        print(f"corpus: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
