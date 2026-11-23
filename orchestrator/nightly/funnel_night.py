#!/usr/bin/env python3
"""Write data/latest/funnel.json, the Sources tab's data, from what the night itself scored.

    funnel_night.py --ledger LEDGER_DIR --anchor anchor.yaml --contract CONTRACT_DIR \
                    --summary data/latest/summary.json --out data/latest/funnel.json \
                    [--configiq data/supplemental/funnels/configiq.json]

The file is funnel.py's InferenceX funnel (format funnel-2) placed by the night's own contract (every point's grade, G5 reason
or fault), plus the id of the snapshot it describes. It is written only when the contract is the whole of the summary: a night
that merged a delta into the last summary holds a contract of the delta alone, and a funnel built from it would be wrong. In
that case, and when an input is missing or refused, nothing is written, the reason is a workflow warning, and a funnel left by
an earlier snapshot is removed, so the tab shows its "not published" notice and never another night's table. This never fails
a night: the funnel is a view of the scoring, not part of it.

configiq is not scored by the nightly (its ledger is pinned to one dataset revision), so its row is not built here: it is the
configiq funnel that a score-configiq run wrote (configiq_night.py's funnel.json), committed by hand beside the class file as
data/supplemental/funnels/configiq.json and passed with --configiq. It is added to the night's file as the second source. When
the file is absent the tab has no configiq row; when it is unreadable the night warns and the row is left out.

The file carries the dataset revision it was scored at (configiq_night.py stamps `dataset`). The night compares it with the
revision the ledger it reads pins for configiq (sources.yaml): after a version bump of the configiq data, until the funnel is
re-run (score-configiq) and committed again, the old row is not shown as current; the night leaves it out and warns, and warns
the same when the committed class file (--configiq-class) was derived at another revision.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "baseline"))
sys.path.insert(0, str(HERE.parent / "ingest"))

import configiq_night as cn  # noqa: E402
import funnel as fn  # noqa: E402
import ledger as ldg  # noqa: E402

REFRESH = ("re-run score-configiq at the new pin and commit its funnel.json as data/supplemental/funnels/configiq.json and its "
           "configiq.json as data/supplemental/classes/configiq.json")


class Skip(Exception):
    """The funnel is not written, for this reason."""


def read_configiq(path: Path | None, dataset: str | None = None) -> dict | None:
    """The configiq funnel of a committed score-configiq run (a funnel-2 document holding the one source `configiq`), None when
    there is no file. A file that is not a valid configiq funnel, or (when `dataset`, the revision the ledger pins, is given) one
    scored at another revision or carrying none, raises, and the caller leaves the row out with a warning."""
    if path is None or not Path(path).is_file():
        return None
    doc = fn.validate(json.loads(Path(path).read_text()))
    if list(doc["funnels"]) != ["configiq"]:
        raise fn.FunnelError(f"{path} holds the sources {sorted(doc['funnels'])}, not configiq alone")
    if dataset is not None and doc.get("dataset") != dataset:
        raise fn.FunnelError(f"it was scored at configiq dataset {doc.get('dataset') or '(no revision recorded)'} but the ledger "
                             f"pins {dataset}: {REFRESH}")
    return doc["funnels"]["configiq"]


def class_file_stale(path: Path | None, dataset: str) -> str | None:
    """A reason when the committed configiq class file was derived at another dataset revision than `dataset`, else None."""
    if path is None or not Path(path).is_file():
        return None
    got = (json.loads(Path(path).read_text()).get("provenance") or {}).get("dataset")
    return None if got == dataset else (f"derived at configiq dataset {got or '(no revision recorded)'} but the ledger pins "
                                       f"{dataset}: {REFRESH}")


def build(lg, anchor_ids: set, contract: Path, summary: dict, configiq: dict | None = None) -> dict:
    """The funnel document of the night: the InferenceX funnel placed by `contract`, with the committed configiq funnel when given,
    stamped with the summary's snapshot."""
    outcomes = fn.contract_outcomes(contract)
    points = (summary.get("coverage") or {}).get("points")
    if not outcomes or len(outcomes) != points:
        raise Skip(f"the contract holds {len(outcomes)} points and the summary {points}: it is not the whole of this snapshot "
                   "(a night that merged a delta holds the delta alone)")
    doc = fn.combine([fn.inferencex(lg, anchor_ids, None, outcomes), *([configiq] if configiq else [])], complete=True)
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
    except Exception as e:  # noqa: BLE001 -- a view of the scoring never fails the night; the type and message are the warning
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
    ap.add_argument("--configiq", type=Path, help="the committed funnel of a score-configiq run; no row when the file is absent")
    ap.add_argument("--configiq-class", type=Path, help="the committed configiq class file; warns when its dataset revision is stale")
    a = ap.parse_args(argv)
    try:
        dataset = cn.pins(a.ledger / "sources.yaml")[0] if a.configiq else None
        configiq = read_configiq(a.configiq, dataset)
        stale = class_file_stale(a.configiq_class, dataset) if dataset else None
        if stale:
            print(f"::warning title=configiq class file is stale::{a.configiq_class}: {stale}")
    except Exception as e:  # noqa: BLE001 -- a bad configiq file leaves its row out; it never takes the InferenceX table with it
        configiq = None
        print(f"::warning title=configiq funnel left out::{a.configiq}: {type(e).__name__}: {e}")
    reason = write(a.out, a.summary,
                   lambda s: build(ldg.load(a.ledger), ldg.read_unit_set(a.anchor, role="anchor"), a.contract, s, configiq))
    if reason:
        print(f"::warning title=funnel.json not written::{reason}")
        print(f"funnel_night: not written ({reason})", file=sys.stderr)
    else:
        print(f"funnel_night: wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
