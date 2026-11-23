#!/usr/bin/env python3
"""Write data/latest/funnel.json, the Sources tab's data, from what the night itself scored.

    funnel_night.py --ledger LEDGER_DIR --anchor anchor.yaml --contract CONTRACT_DIR \
                    --summary data/latest/summary.json --out data/latest/funnel.json

The file is funnel.py's InferenceX funnel (format funnel-2) placed by the night's own contract (every point's grade, G5 reason
or fault), plus the id of the snapshot it describes. It is written only when the contract is the whole of the summary: a night
that merged a delta into the last summary holds a contract of the delta alone, and a funnel built from it would be wrong. In
that case, and when an input is missing or refused, nothing is written, the reason is a workflow warning, and a funnel left by
an earlier snapshot is removed, so the tab shows its "not published" notice and never another night's table. This never fails
a night: the funnel is a view of the scoring, not part of it. configiq is not scored by the nightly, so it has no row here.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "baseline"))
sys.path.insert(0, str(HERE.parent / "ingest"))

import funnel as fn  # noqa: E402
import ledger as ldg  # noqa: E402


class Skip(Exception):
    """The funnel is not written, for this reason."""


def build(lg, anchor_ids: set, contract: Path, summary: dict) -> dict:
    """The funnel document of the night: the InferenceX funnel placed by `contract`, stamped with the summary's snapshot."""
    outcomes = fn.contract_outcomes(contract)
    points = (summary.get("coverage") or {}).get("points")
    if not outcomes or len(outcomes) != points:
        raise Skip(f"the contract holds {len(outcomes)} points and the summary {points}: it is not the whole of this snapshot "
                   "(a night that merged a delta holds the delta alone)")
    doc = fn.combine([fn.inferencex(lg, anchor_ids, None, outcomes)], complete=True)
    if doc["problems"]:
        raise Skip("the funnel does not add up: " + "; ".join(doc["problems"][:3]))
    doc["snapshot_id"] = summary["snapshot_id"]
    return fn.validate(doc)


def write(out: Path, summary_path: Path, make) -> str | None:
    """Write the funnel `make(summary)` returns to `out`; on a Skip or an unreadable input write nothing, drop a funnel of
    another snapshot and return the reason. None when written."""
    out = Path(out)
    try:
        summary = json.loads(Path(summary_path).read_text())
        doc = make(summary)
    except Skip as e:
        reason = str(e)
    except (fn.FunnelError, ldg.LedgerError, OSError, ValueError, KeyError) as e:
        reason = f"{type(e).__name__}: {e}"
    else:
        out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
        return None
    if out.is_file():
        try:
            current = json.loads(Path(summary_path).read_text()).get("snapshot_id")
            kept = current is not None and json.loads(out.read_text()).get("snapshot_id") == current
        except (OSError, ValueError):
            kept = False
        if not kept:
            out.unlink()
    return reason


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--ledger", required=True, type=Path, help="blis-substrate's catalog/ledger at the build's commit")
    ap.add_argument("--anchor", required=True, type=Path, help="the published anchor list (catalog/ledger/published/anchor.yaml)")
    ap.add_argument("--contract", required=True, type=Path, help="the contract directory the whole night was scored into")
    ap.add_argument("--summary", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    reason = write(a.out, a.summary, lambda s: build(ldg.load(a.ledger), ldg.read_unit_set(a.anchor, role="anchor"), a.contract, s))
    if reason:
        print(f"::warning title=funnel.json not written::{reason}")
        print(f"funnel_night: not written ({reason})", file=sys.stderr)
    else:
        print(f"funnel_night: wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
