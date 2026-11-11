#!/usr/bin/env python3
"""Tables of InferenceX series classes and how the harness treats each (prints Markdown).

    series_classes.py --availability avail.json --rows rows.json --contract CONTRACT_DIR --units UNITS.txt

availability.json is /api/v1/availability; rows.json is the window's rows with the ledger unit of each
(`unit`: the unit id, "DIFFERS", or null), as written by the snippet in series-classes.md. The treatment
columns come from engines.py and assess.py, not from a copy of them.
"""
import argparse
import collections
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "orchestrator" / "ingest"))
import assess  # noqa: E402
import engines  # noqa: E402

OOS = lambda h: h in ("mi300x", "mi325x", "mi355x") or h.startswith("tpu")  # noqa: E731


def treatment(label: str, disagg: bool) -> str:
    fw = engines.FRAMEWORKS.get(label)
    if fw is None:
        return "framework not in engines.FRAMEWORKS: the pull stops"
    reasons = []
    if fw.router and not fw.router.startswith("llm-d"):
        reasons.append("router_unsupported")
    if fw.engine is None:
        reasons.append("engine_unsupported")
    elif fw.engine == engines.SGLANG:
        reasons.append("field_unclassified")
    if engines.scored(fw):
        # The engine is vLLM, so the artifacts are fetched and the point is scored by the harness;
        # a router the harness does not model makes it G5 when it is scored (pull.py).
        what = "disaggregated: two pools from the run's recipe, else a named topology_unsupported or recipe_unresolved reason" if disagg else "scored by the harness"
        return "fetched; " + (f"G5 {', '.join(reasons)} at scoring; else " if reasons else "") + what
    if reasons:
        return "G5 " + ", ".join(reasons) + " (no fetch)"
    return "fetched; " + ("disaggregated: two pools from the run's recipe, else a named topology_unsupported or recipe_unresolved reason" if disagg else "scored by the harness")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--availability", required=True)
    ap.add_argument("--rows", required=True)
    ap.add_argument("--contract", required=True)
    ap.add_argument("--units", required=True)
    a = ap.parse_args()
    av = json.load(open(a.availability))
    rows = json.load(open(a.rows))
    c = Path(a.contract)
    scored = {r["point_id"] for r in csv.DictReader(open(c / "points.csv"))}
    ns = {}
    for line in open(c / "not_scored.jsonl"):
        n = json.loads(line)
        ns[n["point_id"]] = n
    frozen = set(Path(a.units).read_text().split())
    cls = lambda r: (r["framework"], "disagg" if r["disagg"] else "agg", r["benchmark_type"])  # noqa: E731
    tab = collections.defaultdict(collections.Counter)
    for r in rows:
        t = tab[cls(r)]
        t["rows"] += 1
        t["oos"] += OOS(r["hardware"])
        u = r["unit"]
        if u is None:
            t["no_unit"] += 1
        elif u != "DIFFERS":
            t["unit"] += 1
            if u in frozen:
                t["scored"] += u in scored
                t["g5"] += u in ns
    avc = collections.Counter((x["framework"], "disagg" if x["disagg"] else "agg", x["benchmark_type"]) for x in av)
    print("| Framework | Topology | Type | Series | Window rows | AMD or TPU rows | Rows with no ledger unit | Units | In the baseline set: scored | G5 | Treatment |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for k in sorted(set(tab) | set(avc), key=lambda k: (-tab[k]["rows"], k)):
        t = tab[k]
        print(f"| {k[0]} | {k[1]} | {k[2]} | {avc[k]} | {t['rows']} | {t['oos']} | {t['no_unit']} | {t['unit']} | {t['scored']} | {t['g5']} | {treatment(k[0], k[1] == 'disagg')} |")
    print()
    print(f"Series in availability: {len(av)}. Window rows: {len(rows)}. Rows with a ledger unit: {sum(1 for r in rows if r['unit'] not in (None, 'DIFFERS'))}.")


if __name__ == "__main__":
    main()
