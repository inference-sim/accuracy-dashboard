#!/usr/bin/env python3
"""Score a first-party corpus of runs on the engine release BLIS runs, as a corpus of its own (#91).

InferenceX alone gives no G1 point: no in-scope run of it used vLLM v0.32.0. Runs made on that release with their
whole configuration and their per-request exports can, and they answer the question users ask: does BLIS rank
configurations as measurement ranks them? This tool scores such a corpus. Per configuration and concurrency, over the
steady middle window of each run and across the whole cluster, it compares five figures. Each is a metric of the
simulator's registry (`blis metrics`), by its id, computed on both sides by that metric's definition (DEV-8); the tool
checks at run time that the registry defines each id as computed here, and refuses to run otherwise:

  output_tok_s          output tokens of the window's completed requests over the window's length (tokens/s)
  interactivity_p50     1000 over the p50 of the window's TPOT in ms (tokens/s per user)
  ttft_p99_ms           the p99 of the window's TTFTs (ms)
  itl_p50_ms            the p50 of every inter-token latency of the window's requests, pooled (ms): each request
                        row's `itl_us`, the gaps between its output tokens. BLIS's Result rows do not carry them yet
                        (inference-sim#2128), so the simulated side has no ITL figure until they do; nothing stands in
  cache_hit_rate        prompt tokens served from the prefix cache over the prompt tokens of the window's requests

Percentiles interpolate linearly between closest ranks (numpy's default, the registry's `numpy_linear`). For each set
of configurations measured on one workload it also reports whether BLIS orders them as the runs do: Spearman and
Kendall concordance of output throughput per GPU, and the regret of BLIS's top choice (ranking.group_metrics).

The steady middle window. The window is chosen on the measured run: the requests that arrived between the first
arrival plus a fraction f of the arrival span and the last arrival less f (the corpus states f, from 0 to below 0.5;
0.1 when it does not), so the ramp up and the drain are out. The simulated side is read over the same requests, by
request id, so both sides compare the same requests (COV-12); its window's length is the span of those requests'
simulated arrivals. A side with no completed request in the window has no figure, and a run with no figure on both
sides is a failed run.

THE CORPUS IS READ FROM A PATH GIVEN AT RUN TIME AND IS NEVER COMMITTED. The tool refuses a corpus directory, an
output for a private corpus, or a private-names file inside any work tree of this repository. For a private corpus
(`"visibility": "private"`) the full report, with every configuration in full beside its numbers, goes only to
`--out`. What may be published (`--public-out`) is the label given on the command line and the grade counts, only
over at least 10 runs, a grade held by fewer than 10 shown as "fewer than 10" (design D7). The label must be a short
slug sharing no word with the corpus's path and holding none of the private names given at run time
(`--private-names`, a file kept with the corpus). Messages about a private corpus name no path and quote no stderr;
the simulator's stderr goes to the private report directory.

Layout: <corpus>/corpus.json, with each run's files beside it.

    {"format": "first-party-corpus-1", "visibility": "private" | "public", "window_trim_fraction": 0.1,
     "runs": [{"id": "r1", "workload": "w", "concurrency": 8, "gpus": 8,
               "configuration": {"engine": {... the engine arguments the run passed, as vLLM names them ...}},
               "build": {"image": "vllm/vllm-openai:v0.32.0", "banner": "0.32.0"},
               "scenario": "r1/scenario.yaml",
               "measured_requests": "r1/requests.jsonl",
               "replay": ["replay", "--scenario", "r1/scenario.yaml", ...],
               "differences": [{"subject": "...", "detail": "..."}]}]}

`measured_requests` holds one JSON object per request with the Result's request-row names: id, fate, arrival_us,
ttft_us, tpot_us, e2e_us, prompt_tokens, output_tokens, cached_local_tokens, cached_external_tokens, and `itl_us`, the
list of the request's inter-token latencies. A source that publishes only aggregates states `measured_figures`
instead: per registry id, {"value", "scope", "aggregate", "window"}; it is compared only when its scope is the cluster,
it states no aggregate, and its window is the one this tool uses (`arrival_middle:<f>`). A source whose client
measured another window cannot be compared (DEV-8), and its run is refused.

The scenario and the configuration. A run's configuration is graded by the engine's field list, as score.py grades an
InferenceX point (fields.decide, design §11.2 and §11.4): a field the release does not list is G5
`field_not_in_release`, a not-modelled field with no estimation rule G5 `field_not_modelled`, an estimated or
inert-but-unproven field a named G2 substitution. The scenario the replay runs (`scenario`) must carry exactly the
configuration's engine block in its deployment's pool (COV-3), so a corpus cannot state one configuration and
simulate another.

The grade. The engine release BLIS runs is read from the scoring build's stack.json (beside `--blis`) and must be the
release of `--fields`; it is never a flag. Each run's own release is read from its recorded build (grade.run_release).
The Result's coefficient methods, every G1 condition the harness does not yet evaluate (named `unevaluated`), and the
corpus's differences (`client_difference`) complete it (grade.grade). A run is scored only on a Result that validates
(`blis schema validate result`) and that completed every request the run sent (result.requests_complete); anything
else is a failed run, never a scored one.

Every accuracy change scored on such a corpus follows design §12.3: it is pre-registered, fitted on the fit split
and judged once on held-out data; this tool scores and reports, it fits nothing.

    corpus.py score --corpus DIR --blis BIN --catalog DIR --registry DIR --fields FIELDS.json --out DIR
                    [--label SLUG --public-out FILE] [--private-names FILE]
"""
from __future__ import annotations

import argparse
import json
import math
import re
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
MIN_UNITS = 10          # design D7: no published aggregate of a non-public corpus over fewer than 10 units
FEW = "fewer than 10"
LABEL = re.compile(r"^[a-z0-9][a-z0-9-]{2,39}$")
DEFAULT_TRIM = 0.1
# The registry's definition of each figure as this tool computes it (blis-substrate contracts/metrics): checked
# against `blis metrics` before any run is scored.
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
_FLAGS_THE_HARNESS_SETS = ("--catalog", "--registry", "--format")


class CorpusError(ValueError):
    pass


# ------------------------------------------------------------------------------------------- definitions

def check_registry(registry: dict) -> list[str]:
    """Why the build's metric registry does not define the five figures as this tool computes them; [] when it does."""
    out = []
    for mid, want in FIGURES.items():
        d = registry.get(mid)
        if d is None:
            out.append(f"the simulator's metric registry has no {mid}")
            continue
        for k, v in want.items():
            if (d.get(k) or "") != v:
                out.append(f"the simulator's {mid} has {k} {d.get(k)!r}; this tool computes it with {v!r}")
    return out


# ------------------------------------------------------------------------------------------- figures

def percentile(xs: list[float], q: float) -> float | None:
    """The q-th percentile by linear interpolation between closest ranks (numpy's default)."""
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * q / 100
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def window_ids(rows: list[dict], trim: float) -> list[str]:
    """The ids of the requests that arrived in the middle of the run's arrival span."""
    arrivals = sorted(r["arrival_us"] for r in rows)
    if not arrivals:
        return []
    span = arrivals[-1] - arrivals[0]
    lo, hi = arrivals[0] + round(trim * span), arrivals[-1] - round(trim * span)
    return sorted(r["id"] for r in rows if lo <= r["arrival_us"] <= hi)


def figures(rows: list[dict], ids: list[str]) -> dict:
    """The five figures over the requests `ids` of one side's rows (measured or simulated)."""
    keep = set(ids)
    done = [r for r in rows if r.get("id") in keep and r.get("fate") == "completed"]
    if not done:
        return {m: None for m in METRICS} | {"requests": 0}
    t0 = min(r["arrival_us"] for r in done)
    t1 = max(r["arrival_us"] for r in done)
    tpots = [r["tpot_us"] / 1000 for r in done if r.get("tpot_us") and (r.get("output_tokens") or 0) >= 2]
    itls = [x / 1000 for r in done for x in (r.get("itl_us") or [])]
    prompt = sum(r.get("prompt_tokens") or 0 for r in done)
    cached = sum((r.get("cached_local_tokens") or 0) + (r.get("cached_external_tokens") or 0) for r in done)
    p50 = percentile(tpots, 50)
    ttfts = [r["ttft_us"] / 1000 for r in done if r.get("ttft_us") is not None]
    return {"requests": len(done),
            "output_tok_s": sum(r.get("output_tokens") or 0 for r in done) / ((t1 - t0) / 1e6) if t1 > t0 else None,
            "interactivity_p50": 1000 / p50 if p50 else None,
            "ttft_p99_ms": percentile(ttfts, 99),
            "itl_p50_ms": percentile(itls, 50),
            "cache_hit_rate": cached / prompt if prompt else None}


def errors(meas: dict, pred: dict) -> dict:
    """Signed percent error of each figure; the cache-hit rate, a fraction, as a difference in points."""
    out = {}
    for m in METRICS:
        a, b = meas.get(m), pred.get(m)
        if a is None or b is None:
            out[m] = None
        elif m == "cache_hit_rate":
            out[m] = 100 * (b - a)
        else:
            out[m] = 100 * (b - a) / a if a else None
    return out


def ranking(runs: list[dict]) -> dict:
    """Per workload, whether BLIS orders its configurations (each run a configuration at a concurrency) by output
    throughput per GPU as the runs do."""
    groups = defaultdict(list)
    for r in runs:
        if r.get("status") != "scored":
            continue
        m, p = r["measured"]["output_tok_s"], (r.get("simulated") or {}).get("output_tok_s")
        if m is None or p is None:
            continue
        groups[r["workload"]].append({"key": r["id"], "meas": m / r["gpus"], "pred": p / r["gpus"]})
    return {w: rk.group_metrics(items) for w, items in sorted(groups.items()) if len(items) >= rk.MIN_CONFIGS}


# ------------------------------------------------------------------------------------------- the corpus

def _toplevel(path: Path) -> Path | None:
    r = subprocess.run(["git", "-C", str(path), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                       capture_output=True, text=True)
    return Path(r.stdout.strip()).resolve() if r.returncode == 0 and r.stdout.strip() else None


def inside_repo(path: Path) -> bool:
    """Whether a path is inside any work tree of this repository (this checkout or another worktree of it)."""
    p = path.resolve()
    if p == ROOT or ROOT in p.parents:
        return True
    probe = p
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    if not probe.is_dir():
        probe = probe.parent
    ours, theirs = _toplevel(ROOT), _toplevel(probe)
    return ours is not None and ours == theirs


def check_label(label, corpus: Path, private_names: list[str]) -> None:
    """The label a private corpus publishes under must name nothing private: a short slug, sharing no word with the
    corpus's path (which may carry a private name), and holding none of the private names given at run time."""
    if not isinstance(label, str) or not LABEL.match(label):
        raise CorpusError(f"the label {label!r} is not a short slug of lower-case letters, digits and hyphens")
    words = {w for part in corpus.resolve().parts for w in re.split(r"[^a-z0-9]+", part.lower()) if len(w) >= 3}
    shared = sorted(words & set(label.split("-")))
    if shared:
        raise CorpusError(f"the label {label!r} shares a word with the corpus's path; choose a label of its own")
    if any(n and n.lower() in label for n in private_names):
        raise CorpusError(f"the label {label!r} holds a private name")


def load(corpus: Path) -> dict:
    if inside_repo(corpus):
        raise CorpusError("the corpus is inside a work tree of this repository; a corpus is read from a path given at "
                          "run time and never committed")
    doc = json.loads((corpus / "corpus.json").read_text())
    if doc.get("format") != FORMAT:
        raise CorpusError(f"corpus.json format {doc.get('format')!r}, want {FORMAT}")
    if doc.get("visibility") not in ("private", "public"):
        raise CorpusError("corpus.json must say whether it is private or public (visibility)")
    trim = doc.get("window_trim_fraction", DEFAULT_TRIM)
    if not isinstance(trim, (int, float)) or not 0 <= trim < 0.5:
        raise CorpusError(f"window_trim_fraction {trim!r} is not from 0 to below 0.5: the window would be empty")
    ids = [r["id"] for r in doc["runs"]]
    if len(set(ids)) != len(ids):
        raise CorpusError("two runs share an id")
    for r in doc["runs"]:
        for k in ("workload", "concurrency", "gpus", "configuration", "build", "replay", "scenario"):
            if k not in r:
                raise CorpusError(f"run {r.get('id')!r} states no {k}")
        if not isinstance(r["configuration"].get("engine"), dict):
            raise CorpusError(f"run {r['id']!r}: the configuration states no engine block")
        if ("measured_requests" in r) == ("measured_figures" in r):
            raise CorpusError(f"run {r['id']!r} states exactly one of measured_requests and measured_figures")
        for d in r.get("differences") or []:
            if not d.get("subject") or not d.get("detail"):
                raise CorpusError(f"run {r['id']!r}: a difference names no subject or no detail")
        for mid, fig in (r.get("measured_figures") or {}).items():
            if mid not in FIGURES:
                raise CorpusError(f"run {r['id']!r}: measured_figures names {mid}, not a figure of {METRICS}")
            want = {"scope": "cluster", "aggregate": "", "window": f"arrival_middle:{trim:g}"}
            got = {k: fig.get(k, "") for k in want}
            if got != want:
                raise CorpusError(f"run {r['id']!r}: {mid} is stated over {got}, not {want}: figures measured under "
                                  f"another definition or window are not compared (DEV-8)")
    return doc


def read_rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def replay_argv(run: dict, *, blis: str, catalog: Path, registry: Path) -> list[str]:
    """The run's replay command with this build's data. It runs in the corpus directory, so its relative paths, and
    any file it writes, stay in the corpus."""
    for a in run["replay"]:
        if a.split("=", 1)[0] in _FLAGS_THE_HARNESS_SETS:
            raise CorpusError(f"run {run['id']}: the replay names {a.split('=', 1)[0]}; the harness sets it")
    return [blis, *run["replay"], "--catalog", str(catalog), "--registry", str(registry), "--format", "json"]


def _flat(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, dict) and v:
            out |= _flat(v, f"{prefix}{k}.")
        else:
            out[f"{prefix}{k}"] = v
    return out


def scenario_engine(path: Path) -> dict:
    """The engine block of the scenario's deployment (its first pool)."""
    import yaml
    for doc in yaml.safe_load_all(path.read_text()):
        if isinstance(doc, dict) and isinstance(doc.get("pools"), list) and doc["pools"]:
            return doc["pools"][0].get("engine") or {}
    raise CorpusError("the scenario holds no deployment with a pool")


def check_scenario(run: dict, engine_block: dict) -> list[str]:
    """COV-3: the scenario's engine block is the run's configuration's, field for field (engine_version aside, which
    is the simulator's release by design §11.2)."""
    want = _flat(run["configuration"]["engine"])
    have = {k: v for k, v in _flat(engine_block).items() if k != "engine_version"}
    out = [f"{k}: the configuration states {want[k]!r}, the scenario {have.get(k)!r}"
           for k in sorted(want) if have.get(k) != want[k]]
    out += [f"{k}: the scenario states {have[k]!r}, which the configuration does not" for k in sorted(set(have) - set(want))]
    return out


def decide_configuration(run: dict, field_list) -> tuple[list[dict], list[dict]]:
    """The G5 reasons and the G2 substitutions the engine's field list gives the run's configuration (fields.decide,
    as score.py applies it to a value the run passed)."""
    import fields as fl
    g5, subs = [], []
    for path in sorted(_flat(run["configuration"]["engine"])):
        d = fl.decide(field_list, path, set_by_run=True)
        if d.g5:
            g5.append(d.g5)
        if d.substitution:
            subs.append(d.substitution)
    return g5, subs


def grade_run(run: dict, doc: dict, engine_release: str, field_list=None) -> dict:
    import result
    build = run["build"]
    rel = gr.run_release({"image": build.get("image")}, build.get("banner"))
    g5, decided = decide_configuration(run, field_list) if field_list is not None else ([], [])
    subs = [{"kind": "client_difference", "subject": d["subject"], "detail": d["detail"]} for d in run.get("differences") or []]
    subs += decided + result.coefficient_substitutions(doc) + gr.unchecked()
    g = gr.grade(engine_version=engine_release, release=rel, substitutions=subs, g5=g5 or None)
    return {"grade": g.grade, "run_release": rel.version, "substitutions": g.substitutions,
            **({"g5_reason": g.g5, "g5_reasons": g5} if g5 else {})}


def check_result(doc, sent: int | None) -> None:
    """A run counts as scored only on a Result: the Result kind at a schema version the harness reads, that completed
    every request the run sent (result.requests_complete), with at least one completed request row."""
    import result
    if not isinstance(doc, dict) or doc.get("kind") != result.KIND:
        raise CorpusError("the replay printed no Result document")
    if doc.get("schema_version") not in result.SCHEMA_VERSIONS:
        raise CorpusError(f"Result schema_version {doc.get('schema_version')!r} is not one the harness reads")
    if sent is not None:
        try:
            result.requests_complete(doc, sent)
        except result.ResultError as e:
            raise CorpusError(str(e)) from None
    rows = doc.get("request_rows")
    if not isinstance(rows, list) or not any(isinstance(r, dict) and r.get("fate") == "completed" for r in rows):
        raise CorpusError("the Result has no completed request row")


def score(*, corpus: Path, simulate, engine_release: str, field_list=None) -> dict:
    """simulate(run) -> the Result document of the run's replay, or raises (the run is then failed)."""
    doc = load(corpus)
    trim = float(doc.get("window_trim_fraction", DEFAULT_TRIM))
    runs = []
    for r in doc["runs"]:
        base = {**_public(r), "measured_window": _window_of(r, trim)}
        try:
            if "measured_requests" in r:
                mrows = read_rows(corpus / r["measured_requests"])
                ids = window_ids(mrows, trim)
                meas, sent = figures(mrows, ids), len(mrows)
            else:
                ids, sent = None, None
                meas = {m: (r["measured_figures"].get(m) or {}).get("value") for m in METRICS} | {"requests": None}
            problems = check_scenario(r, scenario_engine(corpus / r["scenario"]))
            if problems:
                raise CorpusError("the scenario is not the run's configuration: " + "; ".join(problems[:5]))
            res = simulate(r)
            check_result(res, sent)
            srows = res.get("request_rows") or []
            sim = figures(srows, ids if ids is not None else window_ids(srows, trim))
            if all(meas.get(m) is None for m in METRICS) or all(sim.get(m) is None for m in METRICS):
                raise CorpusError("the window holds no completed request on one side: no figure")
            g = grade_run(r, res, engine_release, field_list)
        except (CorpusError, subprocess.SubprocessError, OSError, ValueError, RuntimeError, KeyError, TypeError) as e:
            runs.append({**base, "status": "failed", "fault": _say(e, doc["visibility"])})
            continue
        status = "scored" if g["grade"] in gr.GRADED else "not_scored"
        runs.append({**base, "status": status, **g, "measured": meas, "simulated": sim,
                     **({"errors_pct": errors(meas, sim)} if status == "scored" else {})})
    grades = Counter(x.get("grade") if x["status"] != "failed" else "failed" for x in runs)
    return {"format": "first-party-corpus-report-1", "visibility": doc["visibility"],
            "engine_release": engine_release, "window_trim_fraction": trim, "runs": runs,
            "grades": {g: grades.get(g, 0) for g in (*gr.GRADES, "failed")}, "ranking": ranking(runs)}


def _say(e: Exception, visibility: str) -> str:
    """A fault's text. For a private corpus it carries no path."""
    text = str(e)
    if visibility == "private":
        text = re.sub(r"(/[^\s'\"]+)+", "<path>", text)
    return text[:300]


def _window_of(r: dict, trim: float) -> str:
    return f"arrival_middle:{trim:g} (measured requests, the same ids on the simulated side)" \
        if "measured_requests" in r else f"arrival_middle:{trim:g}, as the source states it"


def _public(r: dict) -> dict:
    return {"id": r["id"], "workload": r["workload"], "concurrency": r["concurrency"], "gpus": r["gpus"],
            "configuration": r["configuration"], "build": r["build"]}


def public_summary(rep: dict, label: str) -> dict:
    """What may be published of a corpus: the label and the grade counts; for a public corpus, the report itself."""
    if rep["visibility"] == "public":
        return {**rep, "label": label}
    n = len(rep["runs"])
    if n < MIN_UNITS:
        raise CorpusError(f"the corpus has {n} runs; a non-public corpus publishes nothing over fewer than {MIN_UNITS} (D7)")
    return {"format": "first-party-corpus-grades-1", "label": label, "engine_release": rep["engine_release"],
            "runs": n, "min_units": MIN_UNITS,
            "grades": {g: (c if c == 0 or c >= MIN_UNITS else FEW) for g, c in rep["grades"].items()}}


def engine_release_of(blis: str, fields_path: Path) -> tuple[str, object]:
    """The engine release BLIS runs: the scoring build's stack.json (beside the binary), which the field list must be
    for. Never a flag."""
    import fields as fl
    import stack as sk
    stack_path = Path(blis).resolve().parent / "stack.json"
    if not stack_path.is_file():
        raise CorpusError("the scoring build has no stack.json beside it: the engine release it runs is not stated")
    release = sk.load(stack_path).engine("vllm")
    field_list = fl.parse(Path(fields_path).read_bytes())
    if field_list.engine != {"kind": "vllm", "version": release}:
        raise CorpusError(f"the field list is for {field_list.engine}; the build runs vllm {release}")
    return release, field_list


def markdown(rep: dict, label: str) -> str:
    L = [f"# First-party corpus: {label}", "",
         f"Engine release {rep['engine_release']}; window: the middle of each run's arrivals, "
         f"{rep['window_trim_fraction']:g} trimmed at each end, the same requests on both sides. Grades: "
         + ", ".join(f"{g} {n}" for g, n in rep["grades"].items()) + ".", "",
         "| Run | Workload | Conc | Status | Grade | " + " | ".join(f"{m} measured | simulated | error" for m in METRICS)
         + " | Configuration |", "|---|---|---|---|---|" + "---|---|---|" * len(METRICS) + "---|"]

    def f(x):
        return "-" if x is None else f"{x:.3g}"
    for r in rep["runs"]:
        cells = " | ".join(f"{f((r.get('measured') or {}).get(m))} | {f((r.get('simulated') or {}).get(m))} | "
                           f"{f((r.get('errors_pct') or {}).get(m))}" for m in METRICS)
        L.append(f"| {r['id']} | {r['workload']} | {r['concurrency']} | {r['status']} | {r.get('grade', '-')} | {cells} | "
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
    s.add_argument("--blis", required=True, help="the scoring build; its stack.json beside it names the engine release")
    s.add_argument("--catalog", required=True, type=Path)
    s.add_argument("--registry", required=True, type=Path)
    s.add_argument("--fields", required=True, type=Path, help="the engine's fields.json at the release the build runs")
    s.add_argument("--out", required=True, type=Path, help="the full report's directory")
    s.add_argument("--label", help="the public-safe name the corpus is published under (required with --public-out)")
    s.add_argument("--public-out", type=Path, help="what may be published: the label and the grade counts")
    s.add_argument("--private-names", type=Path, help="names the label and the public output must not hold, one per line")
    a = ap.parse_args(argv)
    try:
        for p in (a.out, a.private_names):
            if p is not None and inside_repo(p):
                raise CorpusError("an output directory or the private-names file is inside a work tree of this "
                                  "repository; neither is ever committed")
        names = [x.strip() for x in a.private_names.read_text().splitlines() if x.strip()] if a.private_names else []
        doc = load(a.corpus)
        if a.public_out and not a.label:
            raise CorpusError("--public-out needs --label, the name the corpus is published under")
        if a.label:
            check_label(a.label, a.corpus, names)
        import blis_commands as bc
        bad = check_registry(bc.metrics(a.blis))
        if bad:
            raise CorpusError("; ".join(bad))
        release, field_list = engine_release_of(a.blis, a.fields)
        a.out.mkdir(parents=True, exist_ok=True)

        def simulate(run):
            import result
            out = subprocess.run(replay_argv(run, blis=a.blis, catalog=a.catalog, registry=a.registry),
                                 capture_output=True, text=True, timeout=7200, cwd=a.corpus)
            (a.out / f"{run['id']}.stderr").write_text(out.stderr)
            if out.returncode != 0:
                raise CorpusError(f"blis exited {out.returncode} (its stderr is in the report directory)")
            try:
                result.validate(a.blis, out.stdout.encode())
                return result.parse(out.stdout.encode())
            except result.ResultError as e:
                raise CorpusError(f"the replay's output is not a valid Result ({e.slug})") from None
        rep = score(corpus=a.corpus, simulate=simulate, engine_release=release, field_list=field_list)
        (a.out / "report.json").write_text(json.dumps({**rep, "label": a.label}, indent=1, sort_keys=True) + "\n")
        (a.out / "report.md").write_text(markdown(rep, a.label or "unlabelled"))
        if a.public_out:
            text = json.dumps(public_summary(rep, a.label), indent=1, sort_keys=True) + "\n"
            if any(n.lower() in text.lower() for n in names):
                raise CorpusError("the public summary would hold a private name")
            a.public_out.write_text(text)
        print(f"scored {len(rep['runs'])} runs: " + ", ".join(f"{g} {n}" for g, n in rep["grades"].items()))
    except CorpusError as e:
        print(f"corpus: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
