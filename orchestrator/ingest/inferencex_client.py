"""The requests an InferenceX single-turn run sent, reproduced for `blis replay` (COV-12).

Ported from inference-sim's tools/harness (workload.go, promptlengths.go, blisrun.go, and
harness.go's Run, checkPrimed and summarize), which the dashboard ran as the Go command
signedprobe until score.py used this module instead. inference-sim docs/kernel-exclusive/APPLES-TO-APPLES.md cites every line of the
client this depends on. Nothing here imports or runs Go code.

What the client does. InferenceX's benchmark_serving.py, launched by benchmark_lib.sh with
--dataset-name random --random-range-ratio 0.8 --num-prompts 10*CONC --max-concurrency CONC
--request-rate inf --ignore-eos --num-warmups 2*CONC and no --seed, seeds numpy's legacy
global generator with 0 and draws every request's target lengths before it sends anything:

    input_lens  = np.random.randint(int(ISL*0.8), ISL+1, size=10*CONC)
    output_lens = np.random.randint(int(OSL*0.8), OSL+1, size=10*CONC)

target_lengths recomputes those draws with its own MT19937 and numpy's legacy bounded randint,
for any (ISL, OSL, CONC). The client then sends 2*CONC copies of request 0, waits for all of
them, and runs the main phase under a semaphore of CONC. main_phase and primed_phase state that
as a trace; check_primed and summarize read the simulator's per-request rows back and compute
the client's two means.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROUTER_CONFIG_NAME = "vllm-dp-lb.epp.yaml"
ROUTER_CONFIG_PATH = HERE / "inferencex" / ROUTER_CONFIG_NAME
WORKLOADS_SEED0 = HERE / "testdata" / "inferencex-workloads" / "seed0.json"
PROMPT_LENGTHS = HERE / "testdata" / "inferencex-workloads" / "prompt-lengths.json"

# The benchmark's constants, from the client and its launcher (APPLES-TO-APPLES.md "Sources").
RANGE_RATIO = 0.8                 # RANDOM_RANGE_RATIO in benchmark-tmpl.yml
REQUESTS_PER_CONCURRENCY = 10     # --num-prompts $((CONC*10))
WARMUPS_PER_CONCURRENCY = 2       # --num-warmups 2*CONC
CLIENT_ID = "inferencex-benchmark-serving"

# The primed main phase (blisrun.go). Main requests arrive at PRIME_MAIN_START_US, after every
# warm-up copy has completed; each copy's holder round waits PRIME_HOLD_US, after any main
# phase has completed, so a copy's pool slot admits no main request early.
PRIME_MAIN_START_US = 10_000_000_000       # 10^4 s
PRIME_HOLD_US = 1_000_000_000_000          # 10^6 s
PRIME_PREFIX_GROUP = "request-0-prompt"


# ------------------------------------------------------------------ numpy's legacy generator

class MT19937:
    """The reference Mersenne Twister (genrand_int32), seeded as np.random.seed(s) seeds the
    legacy RandomState for a 32-bit s: init_genrand(s)."""

    def __init__(self, seed: int):
        if not 0 <= seed < 2 ** 32:
            raise ValueError(f"seed {seed} is not a 32-bit unsigned integer")
        mt = [0] * 624
        mt[0] = seed
        for i in range(1, 624):
            mt[i] = (1812433253 * (mt[i - 1] ^ (mt[i - 1] >> 30)) + i) & 0xFFFFFFFF
        self.mt, self.idx = mt, 624

    def next32(self) -> int:
        mt = self.mt
        if self.idx >= 624:
            for i in range(624):
                y = (mt[i] & 0x80000000) | (mt[(i + 1) % 624] & 0x7FFFFFFF)
                v = mt[(i + 397) % 624] ^ (y >> 1)
                if y & 1:
                    v ^= 0x9908B0DF
                mt[i] = v
            self.idx = 0
        y = mt[self.idx]
        self.idx += 1
        y ^= y >> 11
        y ^= (y << 7) & 0x9D2C5680
        y ^= (y << 15) & 0xEFC60000
        y ^= y >> 18
        return y & 0xFFFFFFFF

    def randint(self, low: int, high: int, n: int) -> list[int]:
        """np.random.randint(low, high, size=n) on the legacy generator, high exclusive. For a
        range rng = high-1-low below 2^32 numpy draws one 32-bit output per attempt, masks it
        with the smallest all-ones mask covering rng and rejects values above rng
        (buffered_bounded_masked_uint32). A range of one value draws nothing."""
        rng = high - 1 - low
        if not 0 <= rng < 2 ** 32:
            raise ValueError(f"randint({low}, {high}): the range is empty or wider than 32 bits")
        if rng == 0:
            return [low] * n
        mask = (1 << rng.bit_length()) - 1
        out = []
        for _ in range(n):
            v = self.next32() & mask
            while v > rng:
                v = self.next32() & mask
            out.append(low + v)
        return out


def target_lengths(isl: int, osl: int, conc: int, *, seed: int = 0, range_ratio: float = RANGE_RATIO,
                   per_conc: int = REQUESTS_PER_CONCURRENCY) -> tuple[list[int], list[int]]:
    """The client's target input and output lengths for one point, in request order: a fresh
    generator per point (each concurrency is its own job and client process), the input draw
    first, then the output draw. The client's size-0 prefix draw consumes no generator state."""
    for name, v in (("isl", isl), ("osl", osl), ("conc", conc), ("per_conc", per_conc)):
        if not isinstance(v, int) or isinstance(v, bool) or v < 1:
            raise ValueError(f"{name} {v!r} is not a positive integer")
    n = per_conc * conc
    g = MT19937(seed)
    inputs = g.randint(int(isl * range_ratio), isl + 1, n)
    outputs = g.randint(int(osl * range_ratio), osl + 1, n)
    return inputs, outputs


# ------------------------------------------------------------------ the sent prompt lengths

_EVIDENCE_KEYS = {"what", "generator", "client", "environment", "revisions", "points"}
_REVISION_KEYS = {"repo", "revision", "committed", "roles", "files"}
_POINT_KEYS = {"scenario", "label", "concurrency", "served_model", "repo", "run_date", "isl", "osl",
               "client_path", "evidence", "max_abs_mismatch", "server_added_tokens"}
_REV_EVIDENCE_KEYS = {"revision", "requests", "max_abs_mismatch", "mean_mismatch", "requests_mismatched",
                      "server_added_tokens"}


def _is_hex(s, n: int) -> bool:
    return isinstance(s, str) and len(s) == n and all(c in "0123456789abcdef" for c in s)


def _strict(obj, keys: set, where: str):
    if not isinstance(obj, dict):
        raise ValueError(f"{where}: not an object")
    unknown = sorted(set(obj) - keys)
    if unknown:
        raise ValueError(f"{where}: unknown keys {unknown}")
    missing = sorted(keys - set(obj))
    if missing:
        raise ValueError(f"{where}: missing keys {missing}")


@dataclass
class PromptLengthEvidence:
    """The evidence that the prompt lengths a run's client SENT are its targets
    (orchestrator/scripts/inferencex_prompt_lengths.py writes it).

    A point is looked up by (repo, run_date, isl, osl, concurrency): the HF repository of the
    served checkpoint's tokenizer, the run's date (YYYY-MM-DD, the InferenceX row's `date`),
    and the row's isl, osl and conc. These are what an InferenceX API row and its server log
    give; the file's own scenario and label name the old corpus's deployments, which the
    dashboard does not use. Several deployments can share a key (one checkpoint on several
    chips); they then share the tokenizer, the client and the draws, so their evidence is the
    same, and the loader refuses a file where it is not."""
    path: str
    doc: dict
    by_key: dict = field(default_factory=dict)

    @staticmethod
    def load(path) -> "PromptLengthEvidence":
        path = str(path)
        doc = json.loads(Path(path).read_text())
        _strict(doc, _EVIDENCE_KEYS, path)
        if not doc["generator"] or not doc["environment"] or not doc["revisions"] or not doc["points"]:
            raise ValueError(f"{path} lacks its generator, environment, revisions or points")
        known = set()
        for i, r in enumerate(doc["revisions"]):
            _strict(r, _REVISION_KEYS, f"{path} revisions[{i}]")
            if not r["repo"] or not _is_hex(r["revision"], 40) or not r["roles"] or not r["files"]:
                raise ValueError(f"{path}: revision {r['repo']}@{r['revision']} is not pinned with its roles and files")
            for f, h in r["files"].items():
                if not _is_hex(h, 64):
                    raise ValueError(f"{path}: {r['repo']}@{r['revision']} {f} has no sha256")
            known.add(f"{r['repo']}@{r['revision']}")
        e = PromptLengthEvidence(path=path, doc=doc)
        for i, p in enumerate(doc["points"]):
            _strict(p, _POINT_KEYS, f"{path} points[{i}]")
            for j, ev in enumerate(p["evidence"]):
                if ev is None:
                    continue
                _strict(ev, _REV_EVIDENCE_KEYS, f"{path} points[{i}].evidence[{j}]")
                if f"{p['repo']}@{ev['revision']}" not in known:
                    raise ValueError(f"{path}: {p['scenario']} {p['label']} c={p['concurrency']} cites "
                                     f"{p['repo']}@{ev['revision']}, which the header does not pin")
            key = (p["repo"], p["run_date"], p["isl"], p["osl"], p["concurrency"])
            prior = e.by_key.get(key)
            if prior is not None and json.dumps(prior["evidence"], sort_keys=True) != json.dumps(p["evidence"], sort_keys=True):
                raise ValueError(f"{path}: two points with key {key} carry different evidence")
            e.by_key.setdefault(key, p)
        return e

    def verified(self, repo: str | None, run_date: str, isl: int, osl: int, concurrency: int) -> tuple[bool, str]:
        """Whether a point's sent prompt lengths are its targets: the file holds the point, and
        at every pinned revision the construction gave zero mismatch and the server added no
        token. The second value says why not."""
        p = self.by_key.get((repo, run_date, isl, osl, concurrency))
        if p is None:
            return False, (f"{Path(self.path).name} holds no evidence for the point (no engine log, so no run "
                           f"date or client version; or a gated tokenizer)")
        n = 0
        for ev in p["evidence"]:
            if ev is None:
                continue
            n += 1
            if ev["max_abs_mismatch"] != 0:
                return False, (f"at {p['repo']}@{ev['revision'][:8]} the client sent up to "
                               f"{ev['max_abs_mismatch']} tokens away from the target")
            for t in ev["server_added_tokens"]:
                if t != 0:
                    return False, f"at {p['repo']}@{ev['revision'][:8]} the server adds {t} special token(s)"
        if n == 0:
            return False, "no pinned revision of the point's tokenizer existed to check"
        return True, ""


# ------------------------------------------------------------------ the trace

@dataclass
class Replay:
    """One `blis replay` invocation: the trace and the pool that gates it."""
    header: dict
    records: list
    sessions: int   # --total-sessions: the trace's session count
    pool: int       # --concurrent-sessions


def _header() -> dict:
    return {"trace_version": 4, "time_unit": "microseconds", "mode": "generated"}


def _record(request_id: int, session_id: str, round_index: int, input_tokens: int, output_tokens: int, *,
            prefix_group: str = "", prefix_length: int = 0, arrival_time_us: int = 0,
            think_time_us: int | None = None) -> dict:
    return {"request_id": request_id, "client_id": CLIENT_ID, "tenant_id": "", "slo_class": "",
            "session_id": session_id, "round_index": round_index, "prefix_group": prefix_group,
            "prefix_length": prefix_length, "streaming": True, "input_tokens": input_tokens,
            "output_tokens": output_tokens, "text_tokens": 0, "image_tokens": 0, "audio_tokens": 0,
            "video_tokens": 0, "reason_ratio": 0.0, "model": "", "deadline_us": 0,
            "arrival_time_us": arrival_time_us, "first_chunk_time_us": 0, "last_chunk_time_us": 0,
            "status": "ok", "think_time_us": think_time_us}


def _check_lengths(input_lens, output_lens, conc):
    if len(input_lens) != len(output_lens) or not input_lens:
        raise ValueError(f"{len(input_lens)} input and {len(output_lens)} output lengths")
    if not isinstance(conc, int) or conc < 1:
        raise ValueError(f"concurrency {conc!r} is not a positive integer")


def main_phase(input_lens: list[int], output_lens: list[int], conc: int) -> Replay:
    """The main phase alone: request i of the benchmark is record i, a one-round session at
    exactly its target lengths, with no prefix group, no deadline and arrival 0. The pool of
    `conc`, not the trace, decides when each one starts: the first `conc` at t=0, then one per
    completion, in record order (the client's semaphore at --request-rate inf)."""
    _check_lengths(input_lens, output_lens, conc)
    records = [_record(i, f"main-{i}", 0, input_lens[i], output_lens[i]) for i in range(len(input_lens))]
    return Replay(header=_header(), records=records, sessions=len(records), pool=conc)


def primed_phase(input_lens: list[int], output_lens: list[int], conc: int, copies: int) -> Replay:
    """The main phase with request 0's prompt already cached, as the drained warm-up leaves it,
    written with existing trace features only. `copies` warm-up sessions come first: round 0
    is a copy of request 0 (its prompt as the shared prefix group, no further tokens, its
    output length) at t=0; round 1 is a one-token holder PRIME_HOLD_US later, which keeps the
    session's pool slot. Main request 0 is in the same prefix group, so its prompt is the
    copy's token for token. Every main request arrives at PRIME_MAIN_START_US. The pool is
    conc + copies, so the first `conc` main requests start together, in order. `copies` is the
    client's own warm-up count, WARMUPS_PER_CONCURRENCY x conc: the client sends and drains
    that many copies of request 0, whatever the deployment's data-parallel width (a data-parallel
    deployment is one instance whose engine holds the balancer)."""
    _check_lengths(input_lens, output_lens, conc)
    if not isinstance(copies, int) or copies < 1:
        raise ValueError(f"copies {copies!r} is not a positive integer")
    n = len(input_lens)
    records = []
    for j in range(copies):
        sid = f"warmup-{j}"
        records.append(_record(n + 2 * j, sid, 0, 0, output_lens[0], prefix_group=PRIME_PREFIX_GROUP,
                               prefix_length=input_lens[0]))
        records.append(_record(n + 2 * j + 1, sid, 1, 1, 1, think_time_us=PRIME_HOLD_US))
    main = main_phase(input_lens, output_lens, conc).records
    for r in main:
        r["arrival_time_us"] = PRIME_MAIN_START_US
    main[0].update(prefix_group=PRIME_PREFIX_GROUP, prefix_length=input_lens[0], input_tokens=0)
    records += main
    return Replay(header=_header(), records=records, sessions=n + copies, pool=conc + copies)


# The data CSV's columns, from blis-substrate contracts/spec/trace codec.go at 800ae263.
TRACE_COLUMNS = ["request_id", "client_id", "tenant_id", "slo_class", "session_id", "round_index",
                 "prefix_group", "prefix_length", "streaming", "input_tokens", "output_tokens",
                 "text_tokens", "image_tokens", "audio_tokens", "video_tokens", "reason_ratio",
                 "model", "deadline_us", "arrival_time_us", "first_chunk_time_us", "last_chunk_time_us",
                 "status"]
# Written after TRACE_COLUMNS, each only when some record carries it. The records here carry
# only think_time_us.
TRACE_OPTIONAL_COLUMNS = ["slo_target_us", "adapter", "think_time_us", "input_tokens_reset"]


def _cell(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return ""
    if isinstance(v, float):
        # Go's strconv.FormatFloat(f, 'f', -1, 64): the shortest decimal, no exponent.
        return format(v, "f").rstrip("0").rstrip(".") if v != int(v) else str(int(v))
    return str(v)


def write_trace(replay: Replay, directory) -> tuple[Path, Path]:
    """Write the trace as blis-substrate's trace format, version 4: trace.yaml (the header) and
    trace.csv (one row per record, the required columns in their order, then think_time_us
    when some record has one)."""
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    header_path, data_path = d / "trace.yaml", d / "trace.csv"
    h = replay.header
    header_path.write_text(f"trace_version: {h['trace_version']}\ntime_unit: {h['time_unit']}\nmode: {h['mode']}\n")
    optional = [c for c in TRACE_OPTIONAL_COLUMNS if any(r.get(c) is not None for r in replay.records)]
    with open(data_path, "w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(TRACE_COLUMNS + optional)
        for r in replay.records:
            w.writerow([_cell(r[c]) for c in TRACE_COLUMNS] + [_cell(r.get(c)) for c in optional])
    return header_path, data_path


def router_config_bytes() -> bytes:
    """The router configuration every point runs with: score endpoints by requests in flight,
    as vLLM's data-parallel load balancer places requests."""
    return ROUTER_CONFIG_PATH.read_bytes()


def replay_argv(blis: str, scenario_name: str, scenario_dir, header_path, data_path, sessions: int, pool: int,
                seed: int) -> list[str]:
    """The `blis replay` command line for one point. The pool flags are the client's gate:
    with --concurrent-sessions POOL every record is a one-round session (or a warm-up session
    of two rounds), the first POOL start at their arrival and each later one is admitted, in
    trace order, when a session completes. --total-sessions equals the trace's session count,
    so nothing is cloned, and there is no --shuffle-corpus, no think time and no deadline.
    The Result document is read from standard output (--format json). The catalog and
    registry are the simulator's own unless the caller appends --catalog and --registry."""
    return [blis, "replay",
            "--scenario", scenario_name, "--scenarios", str(scenario_dir),
            "--trace-header", str(header_path), "--trace-data", str(data_path),
            "--session-mode", "closed-loop",
            "--concurrent-sessions", str(pool), "--total-sessions", str(sessions),
            "--seed", str(seed), "--format", "json", "--log", "error"]


# ------------------------------------------------------------------ reading the Result back

def request_index(row_id: str) -> int:
    """The trace record index of a one-round session's request, from the id `blis replay`
    gives it, "request_<request_id>". Raises ValueError for any other id (a holder round)."""
    prefix = "request_"
    if not isinstance(row_id, str) or not row_id.startswith(prefix):
        raise ValueError(f"request id {row_id!r} has no {prefix!r} prefix")
    return int(row_id[len(prefix):])


def check_primed(rows: list[dict], n: int) -> None:
    """Refuse a primed run that is not "the main phase after a drained warm-up": a warm-up copy
    that had not completed before the main phase started; main request 0 not arriving with the
    main phase; or a holder round arriving before the last main request completed. `rows` are
    the Result's request_rows (times in simulated microseconds); n is the main-phase count."""
    last_main_end, first_holder = 0, None
    for r in rows:
        start = r["arrival_us"]
        end = start + (r.get("e2e_us") or 0)
        try:
            i = request_index(r["id"])
        except ValueError:
            first_holder = start if first_holder is None else min(first_holder, start)
            continue
        if i >= n:
            if r.get("fate") != "completed" or end >= PRIME_MAIN_START_US:
                raise ValueError(f"warm-up copy {r['id']} ended at {end} us, not before the main phase at "
                                 f"{PRIME_MAIN_START_US} us")
        else:
            if i == 0 and abs(start - PRIME_MAIN_START_US) > 1:
                raise ValueError(f"main request 0 arrived at {start} us, not with the main phase at "
                                 f"{PRIME_MAIN_START_US} us")
            last_main_end = max(last_main_end, end)
    if first_holder is not None and first_holder <= last_main_end:
        raise ValueError(f"a warm-up holder round arrived at {first_holder} us, before the main phase ended at "
                         f"{last_main_end} us")


def summarize(rows: list[dict], input_lens: list[int], output_lens: list[int], ignore=None) -> dict:
    """The client's two means over the main phase, after checking that the run simulated exactly
    the point's requests: every one of the n main-phase requests completed once, at its target
    prompt and output lengths.

    The client's mean_ttft is the mean of ttft over its successful requests, and mean_tpot the
    mean of (latency - ttft) / (output_len - 1) over those with output_len > 1, where latency
    runs to the LAST content chunk. contracts/spec/result defines a row's tpot_us as
    (E2E - TTFT) / (output tokens - 1); TPOT is read from it. Both means are over requests,
    not pooled over tokens. `ignore(id)` drops rows that are not main-phase requests (the
    warm-up copies and holder rounds of a primed run)."""
    n = len(input_lens)
    seen = [False] * n
    ttft_sum = tpot_sum = 0.0
    tpot_n = completed = 0
    first_ttft = None
    for r in rows:
        if r.get("fate") != "completed" or (ignore is not None and ignore(r["id"])):
            continue
        try:
            i = request_index(r["id"])
        except ValueError:
            i = -1
        if not 0 <= i < n or seen[i]:
            raise ValueError(f"completed request {r['id']!r} is not one of the point's {n} main-phase requests, "
                             f"or completed twice")
        seen[i] = True
        if r.get("prompt_tokens") != input_lens[i] or r.get("output_tokens") != output_lens[i]:
            raise ValueError(f"request {i} ran {r.get('prompt_tokens')} input and {r.get('output_tokens')} output "
                             f"tokens; the benchmark's targets are {input_lens[i]} and {output_lens[i]}")
        if r.get("ttft_us") is None:
            raise ValueError(f"completed request {i} has no ttft_us")
        completed += 1
        ttft_sum += r["ttft_us"]
        if i == 0:
            first_ttft = r["ttft_us"]
        if output_lens[i] > 1:
            if r.get("tpot_us") is None:
                raise ValueError(f"completed request {i} of {output_lens[i]} output tokens has no tpot_us")
            tpot_sum += r["tpot_us"]
            tpot_n += 1
    if completed != n:
        raise ValueError(f"completed {completed} of the point's {n} main-phase requests")
    return {"completed": completed, "tpot_requests": tpot_n, "mean_ttft_us": ttft_sum / completed,
            "mean_tpot_us": tpot_sum / tpot_n if tpot_n else None, "first_ttft_us": first_ttft}


# T1 tolerances. BLIS gives a freed lane's next request to the next record in order, but it lands
# one completion overhead after the request that freed the lane, and that overhead grows with the
# finished request's output tokens (detokenisation). Two lanes freeing within a few ms of each
# other can therefore hand their requests over in the other order: measured over the 168 baseline
# single-turn Results, at most 9.2 ms, or 9 us per output token of the longest request. The
# client's semaphore wakes waiters in order. Allowed: 1 ms plus 12 us per output token of the
# longest request. Mean concurrency over the main phase is below conc by the falling load of the
# last round (measured: at least 0.965 of conc).
ORDER_SLACK_BASE_US = 1000
ORDER_SLACK_PER_TOKEN_US = 12
MEAN_CONCURRENCY_TOLERANCE = 0.10


# T10. The InferenceX client is one asyncio process. Parsing a streamed chunk costs about 20 us
# on a laptop (exp/client_cost.py: about 50,000 chunks/s with server and client sharing the
# machine), so that is a floor on the ceiling; the real runners' ceiling is not measured. A run
# whose chunk rate conc / TPOT is above half the floor may have been limited by its client.
CLIENT_CHUNK_CEILING_PER_S = 50_000
CLIENT_BOUND_FRACTION = 0.5


def chunk_rate(conc: int, mean_tpot_us: float) -> float:
    """Chunks per second the client had to parse: conc streams, each emitting one chunk per TPOT."""
    return conc / (mean_tpot_us * 1e-6)


def client_bound(conc: int, mean_tpot_us: float) -> bool:
    return chunk_rate(conc, mean_tpot_us) > CLIENT_BOUND_FRACTION * CLIENT_CHUNK_CEILING_PER_S


def check_request_pattern(rows: list[dict], n: int, conc: int, ignore=None) -> dict:
    """The simulated main phase has the client's request pattern (COV-10): n completed requests
    request_0..request_{n-1}; the first `conc` arrive together; arrivals follow the request order
    (within the slack above); no more than `conc` are in flight at any instant (arrival to
    completion); and the mean number in flight, over the span from the first arrival to the last
    completion, is within MEAN_CONCURRENCY_TOLERANCE below `conc`. Raises ValueError naming the
    first violation; returns the achieved concurrency otherwise."""
    main = {}
    for r in rows:
        if r.get("fate") != "completed" or (ignore is not None and ignore(r["id"])):
            continue
        try:
            main[request_index(r["id"])] = r
        except ValueError:
            continue
    if sorted(main) != list(range(n)):
        raise ValueError(f"the main phase has {len(main)} completed requests, not request_0..request_{n - 1}")
    arr = [main[i]["arrival_us"] for i in range(n)]
    if any(a != arr[0] for a in arr[:conc]):
        raise ValueError(f"the first {conc} requests do not arrive together")
    slack = ORDER_SLACK_BASE_US + ORDER_SLACK_PER_TOKEN_US * max(main[i].get("output_tokens") or 0 for i in range(n))
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
    achieved = sum(main[i]["e2e_us"] for i in range(n)) / span if span > 0 else float(conc)
    if achieved < conc * (1 - MEAN_CONCURRENCY_TOLERANCE):
        raise ValueError(f"mean concurrency {achieved:.2f} is below {1 - MEAN_CONCURRENCY_TOLERANCE:.0%} of {conc}")
    return {"achieved_concurrency": round(achieved, 3)}


def main_phase_only(n: int):
    """The ignore function for a primed run: every row that is not main request 0..n-1."""
    def ignore(row_id: str) -> bool:
        try:
            return request_index(row_id) >= n
        except ValueError:
            return True
    return ignore


# ------------------------------------------------------------------ what remains different

CLIENT_SUBJECT = "inferencex benchmark_serving.py"
# The completion overhead BLIS adds before it releases the next request of a lane (registry
# coefficient cost-model-host-overheads, post-decode fixed overhead; inference-sim#1913).
COMPLETION_OVERHEAD_US = 777
SEND_GAP_DETAIL = (f"BLIS releases the next request at the previous one's completion plus the assumed "
                   f"completion overhead of {COMPLETION_OVERHEAD_US} us; the real client's gap (usage chunk, "
                   f"[DONE], session exit, event-loop wake-up) is not measured")


def client_differences(verified: bool, why: str, *, flags_assumed: bool = False,
                       release_unrecorded: bool = False, population_unrecorded: bool = False,
                       client_bound: bool = False, benchmark_client: str | None = None) -> list[dict]:
    """Every remaining difference between the run's client and the simulated one, each named on
    the point; any of them makes the point G2 (COV-12). Kind "client_difference" is the
    dashboard's name for design §11.3's G2 condition "the simulated requests differ from the
    ones the run's client sent"; contracts/spec/pointrecord has no kind for it yet.

    Always: the client's send gap. BLIS releases the next request of a closed-loop lane at the
    request's completion plus an assumed completion overhead (COMPLETION_OVERHEAD_US, the
    registry's cost-model-host-overheads coefficient; inference-sim#1913). The real client's gap,
    from the final usage chunk and `[DONE]` through the session exit and the event-loop wake-up
    to the next send, is not measured (APPLES-TO-APPLES.md "What else is not reproduced"). When `verified` is false: the sent prompt lengths are not verified
    equal to the replayed targets, for the reason `why`. When `flags_assumed`, the run's job log
    is gone and its client flags are taken to be the launcher's defaults. When `release_unrecorded`,
    the InferenceX commit of the run is not known. When `population_unrecorded`, the run's completed
    and num_prompts are in no pulled file, so requests the client lost cannot be ruled out. When
    `benchmark_client` is given, the run's benchmark was not InferenceX's client but the one it
    names (a prefill/decode run's srt-slurm benchmark), and the text says what is assumed equal."""
    out = [{"kind": "client_difference", "subject": "send_gap", "detail": SEND_GAP_DETAIL}]
    if benchmark_client:
        out.append({"kind": "client_difference", "subject": "benchmark_client", "detail": benchmark_client})
    if not verified:
        out.append({"kind": "client_difference", "subject": "sent_prompt_lengths",
                    "detail": f"sent prompt lengths not verified equal to the replayed targets: {why}"})
    if flags_assumed:
        out.append({"kind": "client_difference", "subject": "client_flags",
                    "detail": "job log expired; the client's flags are assumed to be the launcher's defaults"})
    if release_unrecorded:
        out.append({"kind": "client_difference", "subject": "client_release",
                    "detail": "the InferenceX commit of the run is not recorded"})
    if population_unrecorded:
        out.append({"kind": "client_difference", "subject": "failed_requests",
                    "detail": "the run's completed and num_prompts counts are not in the pulled data; "
                              "requests the client lost, which would leave a different population, are not ruled out"})
    if client_bound:
        out.append({"kind": "client_difference", "subject": "client_saturation",
                    "detail": f"the run's chunk rate (concurrency over TPOT) is above "
                              f"{CLIENT_BOUND_FRACTION:.0%} of {CLIENT_CHUNK_CEILING_PER_S} chunks/s, a floor on the "
                              f"single-process client's ceiling; the measured latencies may include client queueing"})
    return sorted(out, key=lambda d: (d["kind"], d["subject"]))
