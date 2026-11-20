#!/usr/bin/env python3
"""Count the InferenceX anchor units whose inputs can be recovered, without a simulator (requirements §3A.8, plan row 12).

A unit's inputs are the kept record's (pull.freeze_point). The count walks the anchor list and puts each unit in one place:

  excluded       not counted either way: AMD or TPU hardware (compare.scope), or a framework no BLIS engine runs
                 (engines.scored; TRT-LLM stays refused, §3A.4)
  recoverable    a probed source returned the unit's inputs
  not_recovered  no probed source did, with the reason

The only source probed is the API's /server-log, the first of design §11.6's order: it is what a vLLM aggregated
single-turn unit is scored from (pull.freeze_point). A unit that needs another input (an agentic export, a P/D recipe,
an SGLang launch command) is not_recovered with a `no_probe:` reason, and a unit the API holds no log for is
not_recovered with `api_server_log_<code>`: GitHub's job log and the recipe at the run's commit are not probed. So
`recoverable` is a floor, never an estimate, and the report says so. Nothing is simulated and nothing is downloaded
beyond the log's text.

    recoverable.py --ledger SUBSTRATE/catalog/ledger --anchor SUBSTRATE/catalog/ledger/published/anchor.yaml
                   --today YYYY-MM-DD --out recoverable.json [--units-out units.jsonl] [--workers 8]

Run it for real with the substrate checkout stack.json pins; it needs network access to the InferenceX API and no
token. `m3_baseline.py report --recoverable recoverable.json` publishes the count.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ingest"))
import api  # noqa: E402
import artifacts as art  # noqa: E402
import compare as cmp  # noqa: E402
import engines  # noqa: E402
import ledger as ldg  # noqa: E402

FORMAT = "recoverable-1"
EXCLUDED, RECOVERABLE, NOT_RECOVERED = "excluded", "recoverable", "not_recovered"
API_SERVER_LOG = "api_server_log"
AGENTIC = "agentic_traces"


class RecoverableError(ValueError):
    pass


def classify(unit, fetch) -> tuple[str, str]:
    """(status, source or reason) for one anchor unit. An HTTP error other than the API's 404 and 413 (facts about
    the source's data, as pull.freeze_point treats them) is a fault of the run and propagates."""
    ident = unit.identity
    if cmp.scope(ident["hardware"]) == cmp.SCOPE_OUT:
        return EXCLUDED, "amd_or_tpu"
    try:
        fw = engines.lookup(ident["framework"])
    except engines.EngineError:
        return EXCLUDED, f"unknown_framework:{ident['framework']}"
    if not engines.scored(fw, {engines.VLLM, engines.SGLANG}):
        return EXCLUDED, f"engine_unsupported:{fw.label}"
    if ident["benchmark_type"] == AGENTIC:
        return NOT_RECOVERED, "no_probe:agentic_export"
    if fw.topology != engines.AGGREGATED:
        return NOT_RECOVERED, "no_probe:pd_recipe"
    if fw.engine == engines.SGLANG:
        return NOT_RECOVERED, "no_probe:sglang_launch_command"
    try:
        text = api.server_log(fetch, unit.kept_record)
    except urllib.error.HTTPError as e:
        if e.code not in (404, 413):
            raise
        return NOT_RECOVERED, f"{API_SERVER_LOG}_{e.code}"
    if text and art.is_server_log(text.encode()):
        return RECOVERABLE, API_SERVER_LOG
    return NOT_RECOVERED, f"{API_SERVER_LOG}_not_a_log"


def count(units, fetch, workers: int = 1) -> tuple[dict, list]:
    """The counts of the anchor `units` and each unit's (unit_id, status, detail), sorted by unit id."""
    units = sorted(units, key=lambda u: u.unit_id)
    if workers > 1:
        with ThreadPoolExecutor(workers) as pool:
            out = list(pool.map(lambda u: classify(u, fetch), units))
    else:
        out = [classify(u, fetch) for u in units]
    per_unit = [(u.unit_id, s, d) for u, (s, d) in zip(units, out)]
    by = lambda status: dict(sorted(Counter(d for _, s, d in per_unit if s == status).items()))  # noqa: E731
    doc = {"anchor_units": len(units),
           "excluded": by(EXCLUDED), "recoverable": by(RECOVERABLE), "not_recovered": by(NOT_RECOVERED)}
    return doc, per_unit


def totals(doc: dict) -> dict:
    ex, rec, nr = (sum(doc[k].values()) for k in (EXCLUDED, RECOVERABLE, NOT_RECOVERED))
    return {"excluded": ex, "recoverable": rec, "not_recovered": nr, "counted": rec + nr}


def check(doc: dict) -> dict:
    """The document, if it is a recoverable.json whose parts add up to its anchor units."""
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise RecoverableError(f"not a {FORMAT} document")
    t = totals(doc)
    if t["excluded"] + t["counted"] != doc["anchor_units"]:
        raise RecoverableError(f"the parts ({t['excluded']} excluded, {t['recoverable']} recoverable, "
                               f"{t['not_recovered']} not recovered) do not add up to {doc['anchor_units']} anchor units")
    return doc


def build(units, anchor_ids: set, fetch, *, ledger_revision: str, anchor_sha256: str, today: str,
          workers: int = 1) -> tuple[dict, list]:
    missing = sorted(anchor_ids - set(units))
    if missing:
        raise RecoverableError(f"the anchor list names {len(missing)} units the ledger does not hold, the first "
                               f"{missing[0]}")
    doc, per_unit = count([units[i] for i in anchor_ids], fetch, workers)
    doc.update(format=FORMAT, checked_on=today, source={
        "api": api.BASE, "ledger_revision": ledger_revision, "anchor_list_sha256": anchor_sha256,
        "probed": [API_SERVER_LOG],
        "meaning": "Recoverable is a floor: the API's /server-log is the only source probed (GitHub job logs, "
                   "artifacts and recipes at the run's commit are not)."})
    return check(doc), per_unit


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--ledger", required=True, type=Path, help="a checkout of blis-substrate's catalog/ledger")
    ap.add_argument("--anchor", required=True, type=Path, help="the published anchor list")
    ap.add_argument("--today", required=True, help="the date of the check, written to the output")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--units-out", type=Path, help="one line per unit: its id, status and source or reason")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args(argv)
    try:
        lg = ldg.load(a.ledger)
        ids = ldg.read_unit_set(a.anchor, role="anchor")
        doc, per_unit = build(lg.units, ids, api.http_fetch, ledger_revision=lg.revision,
                              anchor_sha256=hashlib.sha256(a.anchor.read_bytes()).hexdigest(), today=a.today,
                              workers=a.workers)
    except (RecoverableError, ldg.LedgerError) as e:
        print(f"recoverable: {e}", file=sys.stderr)
        return 2
    a.out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    if a.units_out:
        a.units_out.write_text("".join(json.dumps({"unit_id": u, "status": s, "detail": d}, sort_keys=True) + "\n"
                                       for u, s, d in per_unit))
    t = totals(doc)
    print(f"wrote {a.out}: {doc['anchor_units']} anchor units, {t['excluded']} excluded, {t['recoverable']} "
          f"recoverable, {t['not_recovered']} not recovered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
