"""Client adapters for first-party runs: a run's own load-generator records become the replay input (COV-12).

The harness replays a run's requests only from what its client recorded: the arrival or in-flight schedule, the
session structure, each request's input and output lengths, the think time between rounds, and the window measured.
InferenceX's single-turn client and AgentX exports are read by score.py itself. This module reads the two clients the
first-party data uses, and gives the corpus scorer (corpus.py) for each run:

  trace     a TraceV2 header and data file `blis replay` reads (the harness's own writer, inferencex_client.write_trace,
            or BLIS's own converter, `blis convert otel`)
  flags     the replay's pool and session flags
  measured  the client's own per-request rows of the measured window, under the Result's request-row names
  differences  every way the replayed requests or their schedule differ from the run's, each a named client_difference

  aiperf           profile_export.jsonl (one record per request: its conversation, turn, start and end times, input and
                   output lengths, TTFT and inter-chunk latencies) and profile_export_aiperf.json (the resolved input
                   configuration: the profiling phase's concurrency). The sessions are replayed as a closed loop of the
                   phase's concurrency (--concurrent-sessions), each round at its recorded absolute input length, the
                   think time the gap the client left between a round's end and the next round's start. Warm-up records
                   are replayed, and only profiling records are measured.
  inference-perf   the OTel traces (one JSON per session), per_request_lifecycle_metrics.json (each request's start, end,
                   token times and lengths) and the rendered load configuration (its stage's concurrent_sessions). The
                   traces are converted by `blis convert otel` (accumulate context growth) and replayed as a pooled
                   closed loop of the stage's concurrent sessions, over every recorded session.

Pooled closed-loop session replay is checked request by request in inference-sim#2131, and the faults it found in
pooled replay and in `convert otel` are inference-sim#2130; until they land, an inference-perf replay names them as a
client difference, so no such point is G1.

Everything a client file states is data: nothing in it is executed. The files are read with json and yaml only, and
`blis convert otel` reads the traces as its own input.
"""
from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


class ClientError(ValueError):
    """A run's client records cannot give a replay input; the text names what is missing or inconsistent."""


@dataclass
class ClientReplay:
    header: Path
    data: Path
    flags: list[str]
    measured: list[dict]                    # the client's rows of the measured window, Result request-row names
    differences: list[dict] = field(default_factory=list)
    requests: int = 0                       # how many requests the trace holds


def _diff(subject: str, detail: str) -> dict:
    return {"kind": "client_difference", "subject": subject, "detail": detail}


# ------------------------------------------------------------------------------------------- aiperf

def aiperf(records: list[dict], export: dict, out: Path) -> ClientReplay:
    """aiperf's per-request export as a closed-loop session replay."""
    import inferencex_client as ix
    phases = [p for p in (export.get("input_config") or {}).get("phases") or [] if p.get("kind", p.get("name")) == "profiling"]
    if len(phases) != 1 or not isinstance(phases[0].get("concurrency"), int) or phases[0]["concurrency"] < 1:
        raise ClientError("the aiperf export states no single profiling phase with a concurrency")
    pool = phases[0]["concurrency"]
    rows = []
    for r in records:
        md, m = r.get("metadata") or {}, r.get("metrics") or {}
        if md.get("was_cancelled"):
            continue
        need = [md.get("conversation_id"), md.get("turn_index"), md.get("request_start_ns"), md.get("request_end_ns"),
                (m.get("input_sequence_length") or {}).get("value"), (m.get("output_sequence_length") or {}).get("value")]
        if any(v is None for v in need):
            raise ClientError(f"an aiperf record lacks a conversation, turn, start, end or length: {md.get('x_request_id')}")
        rows.append(r)
    if not rows:
        raise ClientError("the aiperf export holds no completed request")
    t0 = min(r["metadata"]["request_start_ns"] for r in rows)
    by_session = defaultdict(list)
    for r in rows:
        by_session[r["metadata"]["conversation_id"]].append(r)
    order = sorted(by_session, key=lambda s: min(x["metadata"]["request_start_ns"] for x in by_session[s]))
    records_out, measured, rid = [], [], 0
    for sid in order:
        turns = sorted(by_session[sid], key=lambda x: x["metadata"]["turn_index"])
        prev_end = None
        for k, r in enumerate(turns):
            md, m = r["metadata"], r["metrics"]
            start_us = (md["request_start_ns"] - t0) // 1000
            think = None if prev_end is None else max(0, (md["request_start_ns"] - prev_end) // 1000)
            isl, osl = int(m["input_sequence_length"]["value"]), int(m["output_sequence_length"]["value"])
            records_out.append(ix._record(rid, sid, k, isl, osl, arrival_time_us=start_us if k == 0 else 0, think_time_us=think))
            if md.get("benchmark_phase", "profiling") == "profiling":
                ttft = (m.get("time_to_first_token") or {}).get("value")
                itls = [float(x) * 1000 for x in ((m.get("inter_chunk_latency") or {}).get("value") or [])]
                e2e_us = (md["request_end_ns"] - md["request_start_ns"]) // 1000
                measured.append({"id": f"{sid}:{k}", "fate": "completed", "arrival_us": start_us,
                                 "ttft_us": None if ttft is None else float(ttft) * 1000, "e2e_us": e2e_us,
                                 "tpot_us": (e2e_us - float(ttft) * 1000) / (osl - 1) if ttft is not None and osl > 1 else None,
                                 "prompt_tokens": isl, "output_tokens": osl, "itl_us": itls})
            prev_end = md["request_end_ns"]
            rid += 1
    rep = ix.Replay(header={"trace_version": 4, "time_unit": "microseconds", "mode": "generated"}, records=records_out,
                    sessions=len(order), pool=pool)
    header, data = ix.write_trace(rep, out)
    return ClientReplay(header=header, data=data, requests=rid, measured=measured,
                        flags=["--session-mode", "closed-loop", "--concurrent-sessions", str(pool),
                               "--total-sessions", str(len(order))],
                        differences=[_diff("session_inputs", "each round is replayed at the absolute input length the "
                                           "client recorded; the shared prefix between rounds is not stated, so the "
                                           "prefix cache sees no reuse the client's text had")])


# ------------------------------------------------------------------------------------------- inference-perf

def inference_perf(otel_dir: Path, per_request: list[dict], load_config: dict, out: Path, blis: str) -> ClientReplay:
    """inference-perf's OTel traces, converted by BLIS's own `convert otel`, as a pooled closed-loop session replay."""
    stages = ((load_config.get("load") or {}).get("stages") or [])
    if len(stages) != 1 or not isinstance(stages[0].get("concurrent_sessions"), int):
        raise ClientError("the inference-perf load configuration states no single stage with concurrent_sessions")
    pool = stages[0]["concurrent_sessions"]
    out.mkdir(parents=True, exist_ok=True)
    prefix = out / "trace"
    r = subprocess.run([blis, "convert", "otel", "--input", str(otel_dir), "--trace-output", str(prefix),
                        "--context-growth", "accumulate"], capture_output=True, text=True)
    if r.returncode != 0:
        raise ClientError(f"blis convert otel exited {r.returncode}")
    header, data = Path(f"{prefix}.yaml"), Path(f"{prefix}.csv")
    import csv
    with open(data, newline="") as fh:
        rows = list(csv.DictReader(fh))
    sessions = {x["session_id"] for x in rows}
    if not rows:
        raise ClientError("blis convert otel wrote no request")
    measured = []
    for k, q in enumerate(per_request):
        if q.get("error"):
            continue
        info = q.get("info") or {}
        resp = info.get("response_metrics") or {}
        times = resp.get("output_token_times") or resp.get("chunk_times") or []
        start, end = q.get("start_time"), q.get("end_time")
        if start is None or end is None or not times:
            raise ClientError(f"inference-perf request {k} lacks its start, end or token times")
        out_tokens = int(resp.get("output_tokens") or len(times))
        ttft_us = (times[0] - start) * 1e6
        e2e_us = (end - start) * 1e6
        gaps = [(b - a) * 1e6 for a, b in zip(times, times[1:])]
        measured.append({"id": str(k), "fate": "completed", "arrival_us": int((start - per_request[0]["start_time"]) * 1e6),
                         "ttft_us": ttft_us, "e2e_us": e2e_us,
                         "tpot_us": (e2e_us - ttft_us) / (out_tokens - 1) if out_tokens > 1 else None,
                         "prompt_tokens": int(((info.get("request_metrics") or {}).get("text") or {}).get("input_tokens") or 0),
                         "output_tokens": out_tokens, "itl_us": gaps})
    return ClientReplay(header=header, data=data, requests=len(rows), measured=measured,
                        flags=["--concurrent-sessions", str(pool), "--total-sessions", str(len(sessions))],
                        differences=[_diff("pooled_session_replay", "a pooled closed-loop session replay of BLIS's own "
                                           "`convert otel` conversion; the faults found in both are inference-sim#2130, "
                                           "checked by inference-sim#2131")])
