"""The evaluation budget of each partition version, and the record of every held evaluation spent against it.

The ledger is state/gate/ledger.json. A partition version's budget is a maintainer decision (A5): until it is a
number the gate refuses to evaluate, and nothing in this module supplies a default. An evaluation is spent
by a pre-registration, once: a second request for the same pre-registration is refused. The next release uses
a new partition version when the budget is reached (VAL-6, §13.5).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

PATH = Path("state") / "gate" / "ledger.json"
KIND = "GateLedger"
HEX40, HEX64 = re.compile(r"^[0-9a-f]{40}$"), re.compile(r"^[0-9a-f]{64}$")
ENTRY_KEYS = {"n", "preregistration", "preregistration_sha256", "base", "candidate", "run_id", "verdict"}
VERDICTS = ("pass", "fail", "unjudged")


class Refused(Exception):
    """The gate may not run, with the reason."""


def validate(doc) -> list[str]:
    if not isinstance(doc, dict) or set(doc) != {"kind", "margin_ceiling", "partitions"} or doc["kind"] != KIND:
        return [f"not a {KIND} document with kind, margin_ceiling and partitions"]
    errs = []
    mc = doc["margin_ceiling"]
    if not isinstance(mc, dict) or set(mc) != {"error", "distance"}:
        errs.append("margin_ceiling: {error, distance}, each a number or null (null: the registry's value is not recorded)")
    else:
        for k, v in mc.items():
            if v is not None and (not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0):
                errs.append(f"margin_ceiling.{k}: a number, zero or more, or null")
    for pv, part in (doc["partitions"] or {}).items():
        if not re.fullmatch(r"[1-9][0-9]*", pv) or not isinstance(part, dict) or set(part) != {"budget", "evaluations"}:
            errs.append(f"partitions[{pv}]: {{budget, evaluations}} under a positive-integer key")
            continue
        b = part["budget"]
        if b is not None and (not isinstance(b, int) or isinstance(b, bool) or b < 0):
            errs.append(f"partitions[{pv}].budget: a whole number or null (null: A5 not yet decided)")
        ids = set()
        for i, e in enumerate(part["evaluations"]):
            if not isinstance(e, dict) or set(e) != ENTRY_KEYS:
                errs.append(f"partitions[{pv}].evaluations[{i}]: not a record of {sorted(ENTRY_KEYS)}")
                continue
            if (e["n"] != i + 1 or not HEX40.match(str(e["base"])) or not HEX40.match(str(e["candidate"]))
                    or not HEX64.match(str(e["preregistration_sha256"])) or e["verdict"] not in VERDICTS
                    or not isinstance(e["run_id"], int) or isinstance(e["run_id"], bool)):
                errs.append(f"partitions[{pv}].evaluations[{i}]: a field is malformed or n is not {i + 1}")
            if e["preregistration"] in ids:
                errs.append(f"partitions[{pv}].evaluations[{i}]: {e['preregistration']} is evaluated twice")
            ids.add(e["preregistration"])
        if isinstance(b, int) and len(part["evaluations"]) > b:
            errs.append(f"partitions[{pv}]: {len(part['evaluations'])} evaluations recorded against a budget of {b}")
    return errs


def load(path) -> dict:
    doc = json.loads(Path(path).read_text())
    errs = validate(doc)
    if errs:
        raise Refused("the budget ledger is malformed: " + "; ".join(errs))
    return doc


def dumps(doc) -> str:
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def spent(doc, partition_version: int) -> int:
    part = doc["partitions"].get(str(partition_version))
    return len(part["evaluations"]) if part else 0


def check_may_evaluate(doc, prereg) -> int:
    """Return the evaluation number this pre-registration would take; raise Refused when it may not run."""
    pv = prereg["partition_version"]
    part = doc["partitions"].get(str(pv))
    if part is None:
        raise Refused(f"partition version {pv} has no entry in the budget ledger; a maintainer adds it with its budget (A5)")
    if part["budget"] is None:
        raise Refused(f"partition version {pv} has no budget: the number is a maintainer decision (A5) and is not set")
    if any(e["preregistration"] == prereg["id"] for e in part["evaluations"]):
        raise Refused(f"pre-registration {prereg['id']} already received its one held evaluation")
    n = len(part["evaluations"])
    if n >= part["budget"]:
        raise Refused(f"partition version {pv}: {n} of {part['budget']} held evaluations are spent; "
                      f"the next release uses a new partition version")
    for c in prereg["criteria"]:
        ceiling = doc["margin_ceiling"][c["criterion"]]
        if ceiling is None:
            raise Refused(f"no margin ceiling is recorded for {c['criterion']}: the invariant registry's value is not in the ledger")
        if c["margin"] > ceiling:
            raise Refused(f"the margin for {c['criterion']} is above the registry's ceiling")
    return n + 1


def record(doc, prereg_id, prereg_sha256, base, candidate, run_id, partition_version, verdict):
    """The ledger with one evaluation added, or Refused. The input is not changed."""
    new = json.loads(json.dumps(doc))
    part = new["partitions"].get(str(partition_version))
    if part is None:
        raise Refused(f"partition version {partition_version} has no entry")
    part["evaluations"].append({"n": len(part["evaluations"]) + 1, "preregistration": prereg_id,
                                "preregistration_sha256": prereg_sha256, "base": base, "candidate": candidate,
                                "run_id": run_id, "verdict": verdict})
    errs = validate(new)
    if errs:
        raise Refused("; ".join(errs))
    return new


def recorded_run_ids(doc) -> set:
    return {e["run_id"] for part in doc["partitions"].values() for e in part["evaluations"]}
