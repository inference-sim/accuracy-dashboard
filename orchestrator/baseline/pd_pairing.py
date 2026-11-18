#!/usr/bin/env python3
"""Pair the disaggregated cells of a pinned external end-to-end accuracy artifact with the InferenceX records
that measured them (the P/D half of the matched comparison, #88; the aggregated half is matched.py).

The artifact's extractor (the e2e extractor under blis-substrate kernel/scripts) carries every prefill/decode
topology whole, in the corpus's `disaggregated` list, with the measured and the estimator's absolute TTFT and TPOT
in ms. A topology is the pair of pools of one InferenceX run; the artifact states only the total GPU count and a
parallelism, so the pools come from the record.

    pd_pairing.py --corpus CORPUS.json --dump-rows ROWS.json --out PAIRS.json

A topology is paired with a run when every one of its points has a record of that run with the same model slug,
chip, framework, precision, sequence lengths and concurrency, whose pools total the topology's GPUs and whose mean or
median TTFT and TPOT agree with the artifact's measured values to MEASURED_TOL. More than one such run, or none, is
a named reason and no pairing (never a guess). Each pair carries the pools' shape from the record (workers, tensor
and expert parallel size, DP attention, GPUs), the record ids, and the development split of the series.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import split as dsplit  # noqa: E402

FORMAT = "matched-pd-pairs-1"
MEASURED_TOL = 5e-3     # the artifact prints milliseconds to many digits; a record agrees when within 0.5 %

# Checkpoint basename prefix -> InferenceX model slug. Longest prefix wins. A checkpoint with no slug is unpaired,
# by name; it is never matched on a guess.
SLUGS = {"MiniMax-M2.5": "minimaxm2.5", "MiniMax-M3": "minimaxm3", "Kimi-K2.5": "kimik2.5", "Kimi-K2.6": "kimik2.6",
         "GLM-5.1": "glm5.1", "GLM-5": "glm5", "DeepSeek-V4-Pro": "dsv4", "DeepSeek-R1-0528": "dsr1",
         "Qwen3.5-397B-A17B": "qwen3.5"}


class PairError(ValueError):
    pass


def slug_of(checkpoint: str) -> str | None:
    base = checkpoint.split("/")[-1]
    hits = [k for k in SLUGS if base.startswith(k)]
    return SLUGS[max(hits, key=len)] if hits else None


def _close(want: float, got) -> bool:
    return got is not None and want and abs(want - got) / abs(want) <= MEASURED_TOL


def _fits(point: dict, row: dict) -> bool:
    m = row.get("metrics") or {}
    return (any(_close(point["measured_tpot_ms"], m[k] * 1000) for k in ("mean_tpot", "median_tpot") if m.get(k) is not None)
            and any(_close(point["measured_ttft_ms"], m[k] * 1000) for k in ("mean_ttft", "median_ttft") if m.get(k) is not None))


def run_of(row: dict) -> str:
    """The workflow run that measured a record: the export's run id, else the run in its URL; a record that
    states neither is a run of its own, which a sweep of several concurrencies can never be."""
    if row.get("github_run_id"):
        return str(row["github_run_id"])
    m = re.search(r"/runs/(\d+)", str(row.get("run_url") or ""))
    return m.group(1) if m else f"row:{row['id']}"


def pools(row: dict) -> dict:
    side = lambda p: {"workers": row[f"{p}_num_workers"], "tp": row[f"{p}_tp"], "ep": row[f"{p}_ep"],
                      "dp_attention": bool(row[f"{p}_dp_attention"]), "gpus": row[f"num_{p}_gpu"]}
    return {"prefill": side("prefill"), "decode": side("decode")}


def pair(disaggregated: list[dict], rows: list[dict]) -> list[dict]:
    """One entry per point of every topology: its records and pools, or why there are none."""
    idx = defaultdict(list)
    for r in rows:
        if r.get("disagg") and not r.get("error"):
            idx[(r["model"], r["hardware"], r["framework"], r["precision"], r.get("isl"), r.get("osl"))].append(r)
    chips = {"gb200-nvl72": "gb200"}
    out = []
    for t in disaggregated:
        scored = [p for p in t["points"] if "measured_tpot_ms" in p and "measured_ttft_ms" in p]
        slug = slug_of(t["checkpoint"])
        isl, osl = (int(x) for x in t["workload"].split(":"))
        cell = f"{t['framework']}|{chips.get(t['gpu'], t['gpu'])}|{t['model'] or t['checkpoint']}|disaggregated"
        found, why = None, None
        if slug is None:
            why = "no_slug"
        elif not scored:
            why = "no_measured_point"
        else:
            cands = idx.get((slug, chips.get(t["gpu"], t["gpu"]), t["framework"], t["precision"], isl, osl), [])
            runs = defaultdict(lambda: defaultdict(list))
            for r in cands:
                if r["num_prefill_gpu"] + r["num_decode_gpu"] == t["total_gpus"]:
                    key = (run_of(r), r["prefill_num_workers"], r["decode_num_workers"],
                           r["prefill_tp"], r["decode_tp"], r["prefill_ep"], r["decode_ep"],
                           bool(r["prefill_dp_attention"]), bool(r["decode_dp_attention"]))
                    runs[key][int(r["conc"])].append(r)
            fits = {k: byc for k, byc in runs.items()
                    if all(any(_fits(p, r) for r in byc.get(p["concurrency"], [])) for p in scored)}
            if len(fits) == 1:
                found = next(iter(fits.values()))
            else:
                why = "no_record" if not fits else "several_runs"
        for p in t["points"]:
            e = {"cell": cell, "sweep": f"{t['topology_id']}|{t['label']}", "concurrency": p["concurrency"],
                 "framework": t["framework"], "serving": "disaggregated", "estimator_status": p["status"],
                 "total_gpus": t["total_gpus"]}
            rec = None
            if found is not None:
                rec = next((r for r in found.get(p["concurrency"], []) if "measured_tpot_ms" not in p or _fits(p, r)), None)
            if rec is None:
                e.update(records=[], why=why or "no_record_at_concurrency", split=None)
            else:
                e.update(records=[str(rec["id"])], pools=pools(rec),
                         split=dsplit.kind_of(dsplit.from_row(rec), str(rec.get("date"))[:10]))
            out.append(e)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--dump-rows", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    corpus = json.loads(Path(a.corpus).read_text())
    if "disaggregated" not in corpus:
        raise PairError(f"{a.corpus} has no `disaggregated` list: it was not made by an extractor that carries them")
    rows = json.loads(Path(a.dump_rows).read_text())
    pts = pair(corpus["disaggregated"], rows)
    Path(a.out).write_text(json.dumps({"format": FORMAT, "points": pts}, indent=1) + "\n")
    paired = sum(1 for p in pts if p["records"])
    print(f"{len(pts)} points, {paired} paired, {len(pts) - paired} not: "
          + ", ".join(f"{k} {v}" for k, v in sorted(_count(p.get('why') for p in pts if not p['records']).items())))
    return 0


def _count(it):
    c = defaultdict(int)
    for x in it:
        c[x] += 1
    return c


if __name__ == "__main__":
    sys.exit(main())
