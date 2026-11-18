"""Scoring Red Hat's configiq points by simulation (design §10.1-10.3, §11, COV-7, COV-10, COV-11, D7).

configiq.py turns the ledger's units into points and decides, from the unit's identity alone, which are consistent
with the launcher that published the dataset (the provisional band). Nothing consumed those points: no scenario was
built from one, `blis replay` was never called for one, and the coverage line of a configiq point stayed "awaiting
simulation" for ever (docs/m3/configiq/README.md names the lines). This module is that consumer.

For each point it decides one of three things, before and after the simulator:

  refused   a G5 point with a closed-list reason (grade.G5_CODES) and a subject naming what is missing. Nothing is
            simulated. The refusals are, in order: the engine (only vLLM is reconstructed from a configiq row: the
            launcher's presets are vLLM's), the chip and model the catalog does not have, the launch that cannot be
            reconstructed (the row equals no preset of the launcher that published it), a workload the row does not
            define (turn structure, lengths), and a measurement the row lacks.
  failed    the simulator refused the scenario or did not complete the requests: a runner fault, not a grade.
  scored    the scenario was simulated; the point carries its predicted figures, the figures it was compared with, the
            error of each, and every substitution it stands on.

The scenario is the run as the dataset records it. The model, chip, engine release the simulator runs, tensor
parallel size, the engine settings the row parsed (gpu-memory-utilization, max-num-seqs, max-model-len, chunked
prefill, prefix caching, KV cache dtype) and the GuideLLM workload (a closed loop at the row's concurrency,
`successful_requests` requests of the row's recorded mean prompt and output lengths) are the row's. Each gap is a
substitution on the point (never silent): the launcher's parallelism and blank flags, the frame GuideLLM did not
record, the node size, the constant length standing for a recorded length distribution, the engine release.

The grade is the one grade.grade gives the point's standard substitutions, capped at G3 (COV-7): a provisional point
is never better than G3, and never counts toward the headline (COV-11). A point on the development split's test set
is never simulated by this module and its figures are not read (D7); the split is the dashboard's development split,
applied to the point's role key.

Figures. GuideLLM records, per row, percentiles of TTFT, ITL, TPOT and request latency (configiq.METRICS). The
simulator's request rows give the same per-request quantities, and the same statistics are computed from them by
GuideLLM's own rules: a percentile is the first value whose cumulative weight reaches the quantile
(Percentiles.from_pdf, side="left"), ITL is weighted by output tokens - 1, TPOT by output tokens, TTFT and request
latency are not weighted. The headline pair, the same as the InferenceX harness compares (COV-11), is the mean TTFT
and the mean per-request TPOT, which GuideLLM names ITL.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "baseline"))
import assess as asx  # noqa: E402
import configiq as cq  # noqa: E402
import contract  # noqa: E402
import grade as gr  # noqa: E402
import inferencex_client as ix  # noqa: E402
import result  # noqa: E402
import score as sc_  # noqa: E402
import settings as st  # noqa: E402
import split as dev_split  # noqa: E402
import support as sp  # noqa: E402

SOURCE = cq.SOURCE
ENGINE = "vllm"
SCENARIO_SEED = 42
# The headline pair: GuideLLM's mean TTFT, and its mean ITL, which is the per-request TPOT of InferenceX and vLLM bench
# ((last token - first token) / (output tokens - 1)), the quantity the InferenceX harness compares (score.py).
HEADLINE = {"ttft": "ttft_mean", "tpot": "itl_mean"}
# GuideLLM's node size is not recorded; an HGX baseboard is 8 GPUs (catalog hardware/b200.yaml's comment names it the
# common chassis, and InferenceX's runner table says 8 for H200 and B200). A named substitution on every point.
ASSUMED_GPUS_PER_NODE = 8

# Refusal codes of this module, all on grade.G5_CODES.
ENGINE_UNSUPPORTED = "engine_unsupported"
LAUNCH_SUBJECT = "launch"
WORKLOAD_SUBJECT = "workload"


# Stated on every scored point: the bias of the mean TTFT of the scored gpt-oss-120b points is unexplained.
TTFT_NOTE = ("mean TTFT of the scored points (all gpt-oss-120b) is biased high, load-dependent, and the cause is unexplained: "
             "candidates are H200-specific launch settings, prefix caching by GuideLLM's prompts, and the latency model "
             "under lockstep waves; see docs/m3/configiq/README.md")


class ScoreError(ValueError):
    """The inputs are not what scoring a configiq point requires."""


# ------------------------------------------------------------------------------------------------ the split

def series(identity: dict) -> str:
    """A point's series for the development split (split.py): its role key, every identifying field but the
    concurrency, so one sweep and its re-measurements share a split (design §10.2) and a near-copy never lands on the
    other side of a fit."""
    key = {k: v for k, v in identity.items() if k != "concurrency"}
    return json.dumps(key, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def split_of(identity: dict) -> str:
    """train, validation or test, from the development split's salt and the point's series."""
    return dev_split.split_of(series(identity))


# ------------------------------------------------------------------------------------------------ refusals

def _differs(ident: dict) -> str:
    """Why a row equals no forge preset, named by the first thing that decides it. The test is configiq.forge_preset's;
    this only says which of its conditions failed."""
    ver = ident.get("backend_version")
    released = cq.VLLM_RELEASED.get(ver)
    if ident.get("backend") != "vllm" or not str(ver or "").startswith("vLLM-"):
        return f"engine {ident.get('backend')} {ver}: the launcher's presets are vLLM's"
    if released is None or released < cq.FORGE_HISTORY_START:
        return f"{ver} predates the launcher's history ({cq.FORGE_HISTORY_START}) or is not one it could have run"
    models = {p["model_id"] for p in cq.FORGE_PRESETS}
    if ident.get("model_id") not in models:
        return f"no preset of the launcher names model {ident.get('model_id')}"
    named = [p for p in cq.FORGE_PRESETS if p["model_id"] == ident["model_id"]]
    if not any(p["tp"] == ident.get("tp") for p in named):
        return (f"no preset of {ident['model_id']} sets tensor parallel size {ident.get('tp')} "
                f"(presets: {sorted({p['tp'] for p in named})})")
    cols = ("kv_quantization", "max_seq_len", "max_num_seqs", "precision", "chunked_prefill_enabled",
            "gpu_memory_utilization")
    for c in cols:
        if not any(p["tp"] == ident["tp"] and (p[c] == (None if ident[c] in (None, "", "unknown") else ident[c])
                                                if c == "kv_quantization" else p[c] == ident[c]) for p in named):
            return f"{c} {ident[c]!r} is not what any preset of {ident['model_id']} at tp {ident['tp']} passes"
    return f"{ver} was published after the last preset of {ident['model_id']} that matches the row"


def _workload_reasons(p: "cq.Point") -> list[dict]:
    """What the row does not say of the workload GuideLLM sent. Only a single-turn closed loop is rebuilt."""
    ident, out = p.identity, []
    turns = ident.get("turns")
    if turns not in (None, 1) or ident.get("prefix_tokens") or ident.get("prefix_count") or p.turn_slices:
        out.append({"code": "value_not_recorded",
                    "subject": f"{WORKLOAD_SUBJECT}: multi-turn sessions with a shared prefix ({turns} turns, "
                               f"prefix_tokens {ident.get('prefix_tokens')}, prefix_count {ident.get('prefix_count')}): "
                               f"the think time and each turn's lengths are not recorded"})
    return out


def _measurement_reasons(p: "cq.Point") -> list[dict]:
    """The row must record what the point is compared with and what the workload needs of it."""
    out = []
    if p.measured is None:
        return out        # a value_conflict is already among the point's reasons
    for k in HEADLINE.values():
        if k not in p.measured:
            out.append({"code": "value_not_recorded", "subject": f"measured {k}"})
    v = p.whole_runs[0]["values"]
    for c in ("successful_requests", "prompt_token_count_mean", "output_token_count_mean"):
        if cq._num(v.get(c)) is None or cq._num(v.get(c)) < 1:
            out.append({"code": "value_not_recorded", "subject": f"{WORKLOAD_SUBJECT}: {c}"})
    if not isinstance(p.identity.get("concurrency"), int) or p.identity["concurrency"] < 1:
        out.append({"code": "value_not_recorded", "subject": f"{WORKLOAD_SUBJECT}: concurrency"})
    else:
        # A time-limited sweep at concurrency M had M requests in flight whatever number finished, so replaying N < M requests
        # would misstate the load; the replay itself refuses a trace shorter than its concurrency (Failed to build session pool).
        # No clamp: the two records disagree about the run's shape, and the point says so by name.
        n, conc = cq._num(v.get("successful_requests")), p.identity["concurrency"]
        if n is not None and 1 <= n < conc:
            out.append({"code": "value_conflict", "subject": f"stated concurrency exceeds recorded requests: concurrency {conc}, {int(n)} requests"})
    return out


def refusals(p: "cq.Point") -> list[dict]:
    """Every reason a point is not simulated, each {"code", "subject"}, in the design's order (cq.G5_ORDER). Empty when
    the point is to be simulated. Decided from the unit's identity and the row's recorded figures, never from a
    simulation."""
    out: list[dict] = []
    backend = p.identity.get("backend")
    if backend != ENGINE:
        why = ("SGLang rows have no launcher presets to reconstruct a launch from, and the scenario writer here is vLLM's"
               if backend == "sglang" else "inference-sim hosts vLLM and SGLang only")
        out.append({"code": ENGINE_UNSUPPORTED, "subject": f"engine {backend}: {why}"})
    for r in p.g5:
        if r["code"] in (cq.CHIP_NOT_MODELLED, "not_in_catalog", "value_conflict"):
            out.append(r)
    if backend == ENGINE and not out and not p.provisional:
        # Nothing else is wrong with the row, and its launch cannot be reconstructed: it equals no preset of the launcher.
        out.append({"code": "value_not_recorded", "subject": f"{LAUNCH_SUBJECT}: {_differs(p.identity)}"})
    if p.provisional or not out:
        out += _workload_reasons(p)
        out += _measurement_reasons(p)
    return sorted(out, key=lambda r: (cq.G5_ORDER.index(r["code"]), r.get("subject", "")))


# ------------------------------------------------------------------------------------------------ the scenario

@dataclass
class Scenario:
    """What one configiq point is simulated as: the scenario text, the requests and the substitutions it stands on."""
    name: str
    text: str
    input_tokens: list
    output_tokens: list
    concurrency: int
    substitutions: list
    engine_block: dict
    gpus: int


def _int(v):
    f = cq._num(v)
    return None if f is None else int(round(f))


def _g(x) -> str:
    return "unrecorded" if x is None else f"{x:g}"


def lengths(p: "cq.Point") -> tuple[int, int, list[dict]]:
    """(prompt tokens, output tokens, substitutions): the row's recorded means, as a constant. GuideLLM sent the
    recorded lengths exactly when the mean equals the p99 (a single value has the same mean and p99); where they differ
    the lengths varied, the dataset keeps no distribution, and the constant mean stands for it, named."""
    v = p.whole_runs[0]["values"]
    pm, pq = cq._num(v["prompt_token_count_mean"]), cq._num(v.get("prompt_token_count_p99"))
    om, oq = cq._num(v["output_token_count_mean"]), cq._num(v.get("output_token_count_p99"))
    subs = []
    varied = [n for n, m, q in (("prompt", pm, pq), ("output", om, oq)) if q is None or abs(q - m) > 1e-9]
    if varied:
        subs.append({"kind": "client_difference", "subject": "request lengths",
                     "detail": f"the run's {' and '.join(varied)} lengths varied (prompt mean {pm:g} p99 {_g(pq)}, "
                               f"output mean {om:g} p99 {_g(oq)}) and the dataset keeps no distribution; "
                               f"every simulated request has the recorded mean"})
    nominal = (p.identity.get("isl"), p.identity.get("osl"))
    if (round(pm), round(om)) != nominal and not varied:
        subs.append({"kind": "client_difference", "subject": "request lengths",
                     "detail": f"the recorded token counts ({pm:g} in, {om:g} out) are simulated, not the nominal "
                               f"{nominal[0]} and {nominal[1]} (the request template adds tokens)"})
    return max(1, round(pm)), max(1, round(om)), subs


FRAME_SUBSTITUTIONS = (
    {"kind": "client_difference", "subject": "frame",
     "detail": "GuideLLM's stop rule, warm-up and measured window are not recorded: the simulation runs the recorded "
               "number of successful requests as one closed loop at the recorded concurrency, with no warm-up, and "
               "measures every request"},
    {"kind": "client_difference", "subject": "client release",
     "detail": "the GuideLLM release is not recorded; its definitions of the figures (configiq.METRICS) are those of "
               "the release at 3973120daa90fd50b52e08d1b6332772931cbdd3"},
)
NODE_SUBSTITUTION = {"kind": "estimated", "subject": "cluster.gpus_per_node",
                     "detail": f"the dataset records no node size; {ASSUMED_GPUS_PER_NODE} GPUs, an HGX baseboard "
                               f"(the catalog's B200 comment names it the common chassis)"}


def engine_block(ident: dict) -> tuple[dict, list[dict]]:
    """The vLLM engine block (vLLM's own names) from the row's parsed engine columns, and the substitutions for the
    columns it leaves blank. A blank column is not the engine's default (COV-10): for a row consistent with the
    launcher's presets it is a flag the preset did not pass, which the engine resolves itself; the point names that."""
    eng: dict = {}
    blank = []
    gmu = ident.get("gpu_memory_utilization")
    if gmu not in (None, ""):
        eng["gpu_memory_utilization"] = float(gmu)
    else:
        blank.append("gpu_memory_utilization")
    for col, key, conv in (("max_num_seqs", "max_num_seqs", int), ("max_seq_len", "max_model_len", int)):
        if ident.get(col) not in (None, ""):
            eng[key] = conv(float(ident[col]))
        else:
            blank.append(col)
    cp = ident.get("chunked_prefill_enabled")
    if cp in (None, ""):
        blank.append("chunked_prefill_enabled")
    else:
        eng["enable_chunked_prefill"] = cp in (True, "true", "True", "yes", 1)
    pc = ident.get("prefix_caching")
    if pc in ("yes", "no"):
        eng["enable_prefix_caching"] = pc == "yes"
    kv = ident.get("kv_quantization")
    if kv in (None, "", "unknown"):
        blank.append("kv_quantization")
    else:
        eng["kv_cache_dtype"] = kv
    subs = []
    if blank:
        subs.append({"kind": "estimated", "subject": "engine flags the row leaves blank",
                     "detail": f"{', '.join(blank)} not recorded: for a launcher-consistent row the preset passed none, "
                               f"and the engine resolves them itself ({cq.FORGE_BASE_ARGS})"})
    return eng, subs


# The keys vLLM reads a checkpoint's maximum length from, and the rope types whose `factor` it does not apply to
# max_position_embeddings (vllm/config/model.py _get_and_verify_max_len at v0.33.0, 4ba787ec9959e566d3b587a796dff07673324da5).
CONTEXT_KEYS = ("max_position_embeddings", "n_positions", "max_seq_len", "seq_length", "model_max_length",
                "max_sequence_length", "max_seq_length", "seq_len")
NO_FACTOR_ROPE = ("su", "longrope", "llama3", "yarn", "deepseek_yarn", "deepseek_llama_scaling")


def vllm_max_model_len(config: dict) -> int | None:
    """The max_model_len vLLM serves a checkpoint at when the launch passes no --max-model-len: the smallest of the
    config's length keys, times the rope scaling factor of a rope type that does not already include it. None when the
    config sets none of the keys (vLLM then assumes 2048, which the checkpoint does not state, so it is not supplied).
    The tokenizer config's model_max_length is not read (the catalog entry does not carry it), so a checkpoint whose
    tokenizer sets a smaller one is served shorter than this; the point names the derivation."""
    cfg = config.get("text_config", config) if isinstance(config, dict) else {}
    found = [cfg[k] for k in CONTEXT_KEYS if isinstance(cfg.get(k), (int, float)) and not isinstance(cfg.get(k), bool)]
    if not found:
        return None
    derived = float(min(found))
    ropes = []
    for key in ("rope_parameters", "rope_scaling"):
        v = cfg.get(key)
        if isinstance(v, dict):
            ropes += [v] if ("rope_type" in v or "type" in v) else [x for x in v.values() if isinstance(x, dict)]
    if ropes and "gemma3" not in str(cfg.get("model_type", "")):
        factor = 1.0
        for rp in ropes:
            if (rp.get("rope_type") or rp.get("type")) not in NO_FACTOR_ROPE and rp.get("factor") is not None:
                factor = rp["factor"]
        derived *= factor
    return int(derived)


def catalog_context(catalog_root, model: str) -> int | None:
    """The max_model_len vLLM serves a catalog model at when the launch passes none. From the entry's config.json when it
    commits one (vllm_max_model_len). Else from the derived graph's `global.context_window`, which the catalog writer derives
    from the config's max_position_embeddings when a licence keeps config.json itself out (X12 allows derived values; the
    writer refuses a config that scales its RoPE, so the value is vLLM's). None where neither exists."""
    d = Path(catalog_root) / "models" / model
    f = d / "config.json"
    if f.is_file():
        return vllm_max_model_len(json.loads(f.read_text()))
    g = d / "graph.yaml"
    if g.is_file():
        import yaml
        w = ((yaml.safe_load(g.read_text()) or {}).get("global") or {}).get("context_window")
        if isinstance(w, int) and not isinstance(w, bool) and w > 0:
            return w
    return None


def build(p: "cq.Point", *, model: str, chip: str, engine_release: str, packaging: dict,
          context: int | None = None) -> Scenario:
    """The scenario file and the requests for one provisional point. `packaging` is the catalog's packaging of the chip
    ({"gpus_per_node", "gpus_per_rack"}); a chip whose entry fixes the node size has it taken from the entry, as
    settings.build does. `context` is the max_model_len vLLM derives for the checkpoint (catalog_context), stated when
    the row leaves max_seq_len blank, because the simulator refuses a scenario with no window."""
    ident = p.identity
    name = f"cq-{p.unit_id[:16]}"
    tp = int(ident["tp"])
    eng, blank_subs = engine_block(ident)
    if "max_model_len" not in eng and context is not None:
        eng["max_model_len"] = context
    subs = [dict(s) for s in cq.PROVISIONAL_SUBSTITUTIONS] + [dict(s) for s in FRAME_SUBSTITUTIONS] + blank_subs
    if context is not None and eng.get("max_model_len") == context and ident.get("max_seq_len") in (None, ""):
        subs.append({"kind": "estimated", "subject": "engine.max_model_len",
                     "detail": f"the row leaves max_seq_len blank, so the launch passed no --max-model-len and vLLM serves the "
                               f"checkpoint's own length: {context}, from the catalog entry (its config.json by "
                               f"_get_and_verify_max_len at v0.33.0, the tokenizer config not read, or the graph's derived "
                               f"global.context_window)"})
    if "max_model_len" not in eng:
        subs.append({"kind": "estimated", "subject": "engine.max_model_len",
                     "detail": "the row leaves max_seq_len blank and the catalog entry commits no config.json to derive vLLM's "
                               "default from (its licence keeps the file out; the config hash and the derived graph are "
                               "committed); the scenario states none and the simulator resolves it from the graph, or refuses"})
    cluster = {"hardware": chip}
    per_node = packaging.get("gpus_per_node")
    if per_node is None:
        per_node = ASSUMED_GPUS_PER_NODE
        cluster["gpus_per_node"] = per_node
        subs.append(dict(NODE_SUBSTITUTION))
    cluster["nodes"] = max(1, -(-tp // per_node))
    scenario = {"kind": "Scenario", "name": name, "engine": {"kind": ENGINE, "version": engine_release.lstrip("v")},
                "model": model, "coefficients": list(st.COEFFICIENTS), "cluster": cluster}
    pool = {"role": "colocated", "nodes": cluster["nodes"], "parallel": {"dp": 1, "pp": 1, "tp": tp}, "engine": eng}
    deployment = {"kind": "Deployment", "name": name, "pools": [pool]}
    header = [f"point {p.unit_id}", f"configiq pair {ident['pair_id']}, {p.whole_runs[0]['record']}",
              "GENERATED by orchestrator/ingest/configiq_score.py from the row's recorded columns. Do not edit."]
    import yaml
    text = "\n".join(f"# {h}" for h in header) + "\n"
    text += yaml.safe_dump(scenario, sort_keys=False, default_flow_style=None, width=1000)
    text += "---\n" + yaml.safe_dump(deployment, sort_keys=False, default_flow_style=None, width=1000)
    n_in, n_out, len_subs = lengths(p)
    subs += len_subs
    v = p.whole_runs[0]["values"]
    n = _int(v["successful_requests"])
    errored = _int(v.get("errored_requests")) or 0
    if errored:
        subs.append({"kind": "client_difference", "subject": "errored requests",
                     "detail": f"{errored} requests errored in the run and are not simulated; the {n} successful ones are"})
    conc = int(ident["concurrency"])
    return Scenario(name=name, text=text, input_tokens=[n_in] * n, output_tokens=[n_out] * n, concurrency=conc,
                    substitutions=subs, engine_block=eng, gpus=tp)


# ------------------------------------------------------------------------------------------------ the figures

def _distribution(values: list, weights: list | None = None):
    """GuideLLM's Percentiles.from_pdf over (value, weight) pairs: sorted, equal values merged, weights normalised, and a
    percentile is the first value whose cumulative probability reaches the quantile (np.searchsorted side="left")."""
    pairs: dict = {}
    for i, x in enumerate(values):
        pairs[x] = pairs.get(x, 0.0) + (1.0 if weights is None else weights[i])
    xs = sorted(k for k, w in pairs.items() if w > 0)
    total = sum(pairs[k] for k in xs)
    if not xs or total <= 0:
        return None
    cdf, acc = [], 0.0
    for k in xs:
        acc += pairs[k] / total
        cdf.append(acc)
    mean = sum(k * pairs[k] for k in xs) / total
    return xs, cdf, mean


def _pct(dist, q: float) -> float:
    xs, cdf, _ = dist
    for k, c in zip(xs, cdf):
        if c >= q - 1e-12:
            return k
    return xs[-1]


QUANTILES = {"p1": 0.01, "median": 0.5, "p95": 0.95, "p99": 0.99, "p999": 0.999}


def predicted(rows: list[dict]) -> dict:
    """The statistics GuideLLM records, from the simulator's completed request rows, in the dataset's units (ms for
    TTFT, ITL and TPOT; seconds converted by configiq.METRICS to ms for request latency, as `measured` is). Keys are
    "<family>_<stat>", as configiq.Point.measured's. A family with no request that has the quantity is left out."""
    done = [r for r in rows if r.get("fate") == "completed"]
    out: dict = {}

    def put(fam, dist, stats):
        if dist is None:
            return
        for s in stats:
            if s == "mean":
                out[f"{fam}_mean"] = dist[2]
            elif s == "min":
                out[f"{fam}_min"] = dist[0][0]
            elif s == "max":
                out[f"{fam}_max"] = dist[0][-1]
            else:
                out[f"{fam}_{s}"] = _pct(dist, QUANTILES[s])
    ttft = [r["ttft_us"] / 1e3 for r in done if r.get("ttft_us") is not None]
    put("ttft", _distribution(ttft), cq.STATS["ttft"])
    itl = [(r["tpot_us"] / 1e3, r["output_tokens"] - 1) for r in done
           if r.get("tpot_us") is not None and r.get("output_tokens", 0) > 1]
    put("itl", _distribution([a for a, _ in itl], [w for _, w in itl]), cq.STATS["itl"])
    tpot = [(r["e2e_us"] / 1e3 / r["output_tokens"], r["output_tokens"]) for r in done
            if r.get("e2e_us") is not None and r.get("output_tokens", 0) > 0]
    put("tpot", _distribution([a for a, _ in tpot], [w for _, w in tpot]), cq.STATS["tpot"])
    lat = [r["e2e_us"] / 1e3 for r in done if r.get("e2e_us") is not None]
    put("request_latency", _distribution(lat), cq.STATS["request_latency"])
    return out


def errors(pred: dict, meas: dict) -> dict:
    """Signed relative error in percent, (predicted - measured) / measured, of each statistic both sides have."""
    return {k: (pred[k] - meas[k]) / meas[k] * 100 for k in sorted(meas) if k in pred and meas[k] > 0}


# ------------------------------------------------------------------------------------------------ the simulator

@dataclass
class Env:
    """What scoring a configiq point runs against: the simulator build and the pinned data, as score.Env."""
    blis: str
    catalog: Path
    registry: Path
    catalog_release: str
    registry_release: str
    engine_release: str            # the release the simulator runs (stack.json), e.g. "0.33.0"
    sim_build: str
    harness_commit: str
    field_list: object = None
    timeout_s: int = 3600
    catalog_obj: object = None
    parts: set = field(default_factory=set)
    max_rss_mb: int = 0

    def simulator(self) -> dict:
        return {"build": self.sim_build, "engine": {"kind": ENGINE, "version": self.engine_release},
                "harness_commit": self.harness_commit}


@dataclass
class Outcome:
    """One configiq point after scoring: refused (g5), failed (faults), or scored (figures)."""
    point: "cq.Point"
    split: str
    g5: list = field(default_factory=list)
    faults: list = field(default_factory=list)
    withheld: bool = False
    grade: str | None = None
    computed_grade: str | None = None
    substitutions: list = field(default_factory=list)
    predicted: dict | None = None
    errors: dict | None = None
    model: str | None = None
    concurrency_achieved: float | None = None
    requests: int | None = None

    @property
    def status(self) -> str:
        if self.withheld:
            return "withheld"
        if self.faults:
            return "failed"
        if self.g5:
            return "refused"
        return "scored" if self.predicted is not None else "unscored"


def scored_grade(release_of_run: str | None, engine_release: str, subs: list[dict]) -> tuple[str, str, list[dict]]:
    """(the point's grade, the grade before the cap, the substitutions it names): grade.grade over the standard
    substitutions plus the four G1 conditions this scorer evaluates none of (grade.unchecked), then capped at G3,
    because a provisional point is never better (COV-7). The substitutions are grade.grade's (which add the other
    release, where the run's is not the simulator's) and the provisional band's own kinds, which grade.grade does not
    take."""
    m = re.match(r"^vLLM-(\d+\.\d+\.\d+)$", release_of_run or "")
    release = gr.Release(version=m.group(1) if m else None, nightly_or_custom=m is None,
                         why=f"{release_of_run}" if m is None else "")
    standard = [s for s in subs if s["kind"] in gr.G2_KINDS] + gr.unchecked()
    g = gr.grade(engine_version=engine_release, release=release, substitutions=standard)
    capped = g.grade if gr.GRADES.index(g.grade) >= gr.GRADES.index(cq.PROVISIONAL_CAP) else cq.PROVISIONAL_CAP
    return capped, g.grade, g.substitutions + [s for s in subs if s["kind"] not in gr.G2_KINDS]


_REQ = re.compile(r"^request_(\d+)$")
# The engine's refusal of a scenario that lacks a value it would have to choose itself: 'deployment <field> is not
# stated' (blis-vllm resolves an unstated block_size only for some models and chips, blis-vllm#68).
_NOT_STATED = re.compile(r"deployment ([a-z_]+) is not stated|to (max_model_len), which is not stated")
_ISSUE = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/issues/\d+")


def request_pattern(rows: list[dict], n: int, conc: int) -> dict:
    """The simulated requests have GuideLLM's closed-loop pattern: request_0..request_{n-1} all completed, the first
    min(conc, n) arrive together, arrivals follow the request order, and no more than `conc` are in flight at once.
    Raises ValueError naming the first violation; returns the achieved mean concurrency (request-seconds in flight over
    the span from the first arrival to the last completion).

    inferencex_client.check_request_pattern also requires the mean to be within 10 percent of `conc`, which holds for
    the InferenceX client's ten rounds of requests. A configiq row carries whatever number of requests its stop rule let
    through (`successful_requests`), often fewer than ten rounds, and then the last round's falling load puts the mean
    below `conc` in the run itself: the dataset's own measured concurrency is below the target in the same way. The
    achieved figure is therefore reported beside the recorded one, not gated."""
    main = {}
    for r in rows:
        m = _REQ.match(str(r.get("id", "")))
        if r.get("fate") == "completed" and m:
            main[int(m.group(1))] = r
    if sorted(main) != list(range(n)):
        raise ValueError(f"the replay has {len(main)} completed requests, not request_0..request_{n - 1}")
    arr = [main[i]["arrival_us"] for i in range(n)]
    first = min(conc, n)
    if any(a != arr[0] for a in arr[:first]):
        raise ValueError(f"the first {first} requests do not arrive together")
    slack = ix.ORDER_SLACK_BASE_US + ix.ORDER_SLACK_PER_TOKEN_US * max(main[i].get("output_tokens") or 0 for i in range(n))
    for i in range(1, n):
        if arr[i] < arr[i - 1] - slack:
            raise ValueError(f"request {i} arrived {arr[i - 1] - arr[i]} us before request {i - 1}")
    events = sorted([(arr[i], 1) for i in range(n)] + [(arr[i] + main[i]["e2e_us"], -1) for i in range(n)],
                    key=lambda e: (e[0], e[1]))
    cur = peak = 0
    for _, step in events:
        cur += step
        peak = max(peak, cur)
    if peak > conc:
        raise ValueError(f"{peak} requests were in flight at once; the client's concurrency is {conc}")
    span = events[-1][0] - events[0][0]
    return {"achieved_concurrency": round(sum(main[i]["e2e_us"] for i in range(n)) / span, 3) if span > 0 else float(first)}


def _run(argv, env: Env, work: Path, pid: str):
    """One `blis replay`: (its validated Result, None, None), or (None, a fault, None), or (None, None, a G5 reason).
    A refusal that says a value was not stated is a G5 point (the dataset does not record it); any other refusal of a
    scenario the harness wrote from recorded values is a fault of the run, as in score.py (assess.RUN_FAULTS)."""
    logs = work / "logs"
    try:
        doc, raw, stderr = result.run(argv, blis=env.blis, cwd=str(Path(env.blis).parent), timeout=env.timeout_s)
    except subprocess.TimeoutExpired:
        return None, "blis_refused:timeout", None
    except result.RunFailed as e:
        logs.mkdir(parents=True, exist_ok=True)
        (logs / f"{pid}.err").write_text(e.stderr[-20000:])
        flat = re.sub(r"\s+", " ", e.stderr).replace('\\"', '"')
        m = _NOT_STATED.search(flat)
        if m:
            issue = _ISSUE.search(flat)
            return None, None, {"code": "value_not_recorded",
                                "subject": f"engine {m.group(1) or m.group(2)}: the row does not record it and the simulator cannot choose "
                                           f"it for this model and chip" + (f" ({issue.group(0)})" if issue else "")}
        reason = sc_.value_refusal(e.stderr, work, env.field_list) or sc_._blis_refusal(e.stderr, work)
        if reason.partition(":")[0] != "blis_refused":
            g = asx.g5_of(reason)
            return None, None, g
        return None, reason, None
    except result.ResultError as e:
        return None, f"blis_refused:{e.slug}", None
    return doc, None, None


def resolve(p: "cq.Point", env: Env) -> tuple[str | None, str | None, list[dict], int | None]:
    """(catalog model, catalog chip, G5 reasons, the checkpoint's default context) of a point, from the catalog the
    simulator reads. Reasons are decided from the unit's identity alone."""
    ident = p.identity
    sup = sp.check(env.catalog_obj, env.parts, checkpoints=[ident["model_id"]], base_models={},
                   hardware=ident["accelerator"].lower(), spec_method=None)
    if sup.reasons or sup.model is None or sup.chip is None:
        g5 = sorted([asx.g5_of(r) for r in sup.reasons], key=lambda r: (cq.G5_ORDER.index(r["code"]), r.get("subject", "")))
        return None, None, g5 or [{"code": "not_in_catalog", "subject": f"model {ident['model_id']}"}], None
    context = catalog_context(env.catalog, sup.model)
    if context is None and ident.get("max_seq_len") in (None, "") \
            and not (Path(env.catalog) / "models" / sup.model / "graph.yaml").is_file():
        return sup.model, sup.chip, [{"code": "not_in_catalog",
                                      "subject": f"model {sup.model}: the catalog entry has no derived graph"}], None
    return sup.model, sup.chip, [], context


def score_point(p: "cq.Point", env: Env, work: Path, *, simulate: bool = True) -> Outcome:
    """One point: refused, or simulated and compared. Every refusal that identity decides is decided first, for every
    split. A test-split point is then withheld: it is never simulated here and its figures are never read (D7). The
    logged evaluation of the test set (baseline/compare.evaluation_log) is a release's single test evaluation and is not
    wired for this source."""
    o = Outcome(point=p, split=split_of(p.identity))
    o.g5 = refusals(p)
    if o.g5:
        return o
    model, chip, o.g5, context = resolve(p, env)
    if o.g5:
        return o
    if o.split == "test":
        o.withheld = True
        return o
    o.model = model
    sc = build(p, model=model, chip=chip, engine_release=env.engine_release,
               packaging=env.catalog_obj.packaging(chip), context=context)
    o.requests = len(sc.input_tokens)
    work = Path(work).resolve()
    pdir = work / "points" / p.unit_id
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / f"{sc.name}.yaml").write_text(sc.text)
    replay = ix.main_phase(sc.input_tokens, sc.output_tokens, sc.concurrency)
    header_path, data_path = ix.write_trace(replay, pdir)
    argv = ix.replay_argv(env.blis, f"{sc.name}.yaml", pdir, header_path, data_path, replay.sessions, replay.pool,
                          SCENARIO_SEED)
    argv += ["--catalog", str(env.catalog), "--registry", str(env.registry)]
    if not simulate:
        o.substitutions = sc.substitutions
        return o
    key = hashlib.sha256(b"\0".join([sc.text.encode(), header_path.read_bytes(), data_path.read_bytes(),
                                      "\0".join(argv[1:]).encode()])).hexdigest()
    cache, kpath = pdir / "result.json", pdir / "result.key"
    if cache.exists() and kpath.exists() and kpath.read_text() == key:
        doc = json.loads(cache.read_text())
    else:
        doc, fault, g5 = _run(argv, env, work, p.unit_id)
        if g5:
            o.g5 = [g5]
            return o
        if fault:
            o.faults = [fault]
            return o
        cache.write_text(json.dumps(doc))
        kpath.write_text(key)
    try:
        result.requests_complete(doc, len(sc.input_tokens))
        rows = result.rows(doc)
        ix.summarize(rows, sc.input_tokens, sc.output_tokens)
        flight = request_pattern(rows, len(sc.input_tokens), sc.concurrency)
    except result.ResultError as e:
        o.faults = [f"blis_refused:{e.slug}"]
        return o
    except ValueError as e:
        o.faults = [f"blis_refused:request_pattern: {e}"[:300]]
        return o
    o.concurrency_achieved = flight["achieved_concurrency"]
    o.predicted = predicted(rows)
    o.errors = errors(o.predicted, p.measured or {})
    try:
        subs = list(sc.substitutions) + result.coefficient_substitutions(doc)
    except result.ResultError as e:
        o.faults = [f"blis_refused:{e.slug}"]
        o.predicted = o.errors = None
        return o
    o.grade, o.computed_grade, o.substitutions = scored_grade(ident_release(p), env.engine_release, subs)
    return o


def ident_release(p: "cq.Point") -> str:
    return p.identity["backend_version"]


# ------------------------------------------------------------------------------------------------ records and figures

def record(o: Outcome) -> dict:
    """The point's record for the summary: configiq.record's fields, completed by what scoring found."""
    r = cq.record(o.point)
    if o.split == "test":
        # The test set's figures are not read here (D7): the record keeps the unit's identity and what was decided
        # from it, not the measurement.
        r["measured"], r["repeat_spread"], r["turn_slices"], r["whole_runs"] = None, {}, [], []
    r["split"] = o.split
    r["status"] = o.status
    r["failed"] = bool(o.faults)
    if o.faults:
        r["faults"] = o.faults
    if o.g5:
        r["grade"] = "G5"
        r["provisional"] = False
        r["g5_reasons"] = o.g5
        r["g5_reason"] = o.g5[0]
        r["substitutions"], r["grade_cap"], r["backlog"] = [], None, []
    elif o.status == "scored":
        r["grade"] = o.grade
        r["g5_reason"], r["g5_reasons"] = None, []
        r["grade_before_cap"] = o.computed_grade
        r["substitutions"] = sorted(o.substitutions, key=lambda s: (s["kind"], s["subject"]))
        r["model_entry"] = o.model
        r["requests"] = o.requests
        r["achieved_concurrency"] = o.concurrency_achieved
        r["predicted"] = o.predicted
        r["errors_pct"] = o.errors
        r["backlog"] = list(r.get("backlog") or []) + [TTFT_NOTE]
    else:
        r["grade"] = None      # withheld or failed: no figure, no grade
        r["g5_reason"], r["g5_reasons"] = None, []
    return r


def points_csv(outcomes: list["Outcome"]) -> str:
    """The scored points in the InferenceX contract's points.csv columns, so the paired comparison and the figures that
    read it read this too: TPOT is the mean per-request TPOT (GuideLLM's itl_mean) and TTFT the mean TTFT, in
    microseconds. The measured date is empty: the dataset records none."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(contract.POINTS_HEADER)
    for o in sorted((o for o in outcomes if o.status == "scored"), key=lambda o: o.point.unit_id):
        p, i = o.point, o.point.identity
        meas = p.measured
        scen = f"{o.model}-{i['accelerator'].lower()}-{ENGINE}-tp{i['tp']}"
        label = f"{i['isl']}x{i['osl']}"
        w.writerow([scen, o.model, i["accelerator"].lower(), label, i["concurrency"],
                    round(meas[HEADLINE["tpot"]] * 1e3, 3), round(o.predicted[HEADLINE["tpot"]] * 1e3, 3),
                    round(meas[HEADLINE["ttft"]] * 1e3, 3), round(o.predicted[HEADLINE["ttft"]] * 1e3, 3),
                    o.grade, p.unit_id, ""])
    return buf.getvalue()


MIN_POINTS = 10
TOO_FEW = "too few points"


def figures(outcomes: list["Outcome"], splits=("train", "validation")) -> dict:
    """Error figures over the scored points of the given splits: for each statistic, the count, the mean absolute
    percentage error and the median signed error. Under MIN_POINTS a figure is "too few points" (COV-11). Reported, not
    gated."""
    pts = [o for o in outcomes if o.status == "scored" and o.split in splits]
    out: dict = {"splits": list(splits), "points": len(pts), "by_stat": {}}
    stats = sorted({k for o in pts for k in o.errors})
    for k in stats:
        xs = [o.errors[k] for o in pts if k in o.errors]
        if len(xs) < MIN_POINTS:
            out["by_stat"][k] = {"n": len(xs), "mape": TOO_FEW, "signed_median": TOO_FEW}
            continue
        s = sorted(xs)
        med = s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2
        out["by_stat"][k] = {"n": len(xs), "mape": sum(abs(x) for x in xs) / len(xs), "signed_median": med}
    return out


def coverage(outcomes: list["Outcome"]) -> dict:
    """What the scorer did with the points: counts by status and by first refusal, and the share that ran. `ran` is
    scored; `eligible` is scored plus withheld (decided runnable, not simulated because the point is on the test set);
    `failed` is a runner fault."""
    total = len(outcomes)
    c = {"points": total, "scored": 0, "refused": 0, "failed": 0, "withheld": 0}
    reasons: dict = {}
    for o in outcomes:
        c[{"scored": "scored", "refused": "refused", "failed": "failed", "withheld": "withheld"}.get(o.status, "refused")] += 1
        if o.status == "refused":
            r = o.g5[0]
            key = f"{r['code']}: {_reason_key(r['subject'])}"
            reasons[key] = reasons.get(key, 0) + 1
    runnable = c["scored"] + c["withheld"] + c["failed"]
    dev = [o for o in outcomes if o.split != "test"]
    dev_ran = sum(1 for o in dev if o.status == "scored")
    return {**c, "runnable": runnable,
            "runnable_share": runnable / total if total else None,
            "dev_points": len(dev), "dev_scored": dev_ran, "dev_share_ran": dev_ran / len(dev) if dev else None,
            "refusals_by_reason": dict(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0])))}


def _reason_key(subject: str) -> str:
    """A refusal's subject without the numbers that differ between points, so equal reasons are counted together."""
    s = re.sub(r"\(presets: [^)]*\)", "", subject)
    s = re.sub(r"(tensor parallel size )\S+", r"\1N", s)
    s = re.sub(r"(gpu_memory_utilization|max_seq_len|max_num_seqs|kv_quantization|precision|chunked_prefill_enabled) '[^']*'", r"\1 V", s)
    s = re.sub(r"\(\d+ turns, prefix_tokens \S+, prefix_count \S+\)", "(N turns)", s)
    s = re.sub(r"vLLM-\d+\.\d+\.\d+", "vLLM-X", s)
    s = re.sub(r"(repeat runs disagree on \S+):.*", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()[:160]


# ------------------------------------------------------------------------------------------------ the run

def catalog_view(catalog_root) -> dict:
    """What BLIS models, as configiq.points needs it: {"models": {hf repo: {"moe": bool}}, "chips": {names, upper
    case}}, from the catalog's model.yaml source repositories, graphs and hardware files."""
    import yaml
    root = Path(catalog_root)
    models, chips = {}, set()
    for d in sorted((root / "models").iterdir()):
        my, gy = d / "model.yaml", d / "graph.yaml"
        if not my.is_file():
            continue
        repo = (yaml.safe_load(my.read_text()).get("source") or {}).get("repo")
        if repo:
            models[repo] = {"moe": gy.is_file() and "GroupedGEMM" in gy.read_text()}
    for h in (root / "hardware").glob("*.yaml"):
        chips.add(h.stem.upper())
    return {"models": models, "chips": chips}


def load_points(ledger_dir, data_dir, export_path, catalog_root) -> tuple["cq.Ledger", list]:
    """Every configiq point of the pinned dataset revision: the ledger's unit list, report and sources
    (catalog/ledger), the dataset rows from blis-substrate's export of the downloaded files (checked against the pinned
    hashes in data_dir), and the catalog's view of models and chips."""
    ledger = Path(ledger_dir)
    lg = cq.load(ledger / "units" / "configiq.jsonl.gz", ledger / "reports" / "configiq.yaml", ledger / "sources.yaml")
    rows = cq.read_export(Path(export_path), Path(data_dir), lg)
    return lg, cq.points(lg, rows, catalog_view(catalog_root))


def score_all(points: list, env: Env, work: Path, *, workers: int = 1, log=lambda m: None) -> list["Outcome"]:
    """Score every point, in input order. Replays are subprocesses, so threads suffice; workers is a speed knob and
    never changes a figure."""
    from concurrent.futures import ThreadPoolExecutor
    done = [0]

    def one(p):
        try:
            o = score_point(p, env, work)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as e:
            o = Outcome(point=p, split=split_of(p.identity), faults=[f"scorer_error:{type(e).__name__}: {e}"[:300]])
        done[0] += 1
        if done[0] % 25 == 0 or done[0] == len(points):
            log(f"  [{done[0]}/{len(points)}]")
        return o
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        return list(ex.map(one, points))


def summary(outcomes: list["Outcome"], provenance: dict) -> dict:
    """The run's summary: the coverage counts, the by_source breakdown (by_source.py: provisional points are outside the
    headline), the error figures over train and validation, and the problems found checking them."""
    import by_source as bs
    recs = [record(o) for o in outcomes]
    br = bs.by_source(recs)[SOURCE]
    totals = {"points": 0, "graded": 0, "not_scored": br["not_scored"], "failed": br["failed"]}
    # Provisional points are not in the headline totals: by_source.check adds them to the points.
    problems = bs.check(bs.by_source(recs), {**totals, "points": br["points"] - br["provisional"]})
    cov = coverage(outcomes)
    return {"format": "configiq-score-1", "provenance": provenance, "coverage": cov, "by_source": br,
            "figures": figures(outcomes), "problems": problems,
            "grades": {g: sum(1 for o in outcomes if o.grade == g) for g in ("G3", "G4")}}


def write_outputs(out: Path, outcomes: list["Outcome"], provenance: dict) -> dict:
    """The score directory: configiq-points.jsonl (one canonical record per point, sorted by point id), points.csv (the
    scored points in the InferenceX contract's columns) and summary.json."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    recs = sorted((record(o) for o in outcomes), key=lambda r: r["point_id"])
    (out / "configiq-points.jsonl").write_text("".join(contract.canonical_dumps(r) + "\n" for r in recs))
    (out / "points.csv").write_text(points_csv(outcomes))
    doc = summary(outcomes, provenance)
    (out / "summary.json").write_text(contract.canonical_dumps(doc) + "\n")
    return doc
