"""The pre-registration of a change to a measured or calibrated value (design VAL-6, T-B pre-register).

A pre-registration is a JSON file under state/gate/preregistrations/, committed to main before any
held-out data is read. It names the target lanes, the success criteria with a non-inferiority margin d for
each, the metrics, and the gate's bootstrap substream. A change receives one held evaluation per
pre-registration. The file is read strictly: an unknown field is refused (SUB-12).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingest"))
import contract  # noqa: E402

KIND = "PreRegistration"
CRITERIA = ("error", "distance")
LANE_FIELDS = ("engine", "modelled_commit", "chip", "model", "layout")
SOURCES = ("inferencex",)
ID = re.compile(r"^[a-z0-9][a-z0-9.-]{2,63}$")
METRIC = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SUBSTREAM = re.compile(r"^[a-z0-9][a-z0-9._/-]{2,63}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
KEYS = {"kind", "id", "partition_version", "hypothesis", "layer", "target_lanes", "sources", "criteria",
        "metrics", "substream", "predicted_change", "measured_sha256"}
DIR = Path("state") / "gate" / "preregistrations"


class PreRegistrationError(ValueError):
    pass


def _text(doc, key, errs):
    v = doc.get(key)
    if not isinstance(v, str) or len(v.strip()) < 10:
        errs.append(f"{key}: a sentence is required (at least 10 characters)")


def validate(doc) -> list[str]:
    """Every problem with a pre-registration document; empty when it is well formed."""
    if not isinstance(doc, dict):
        return ["not an object"]
    errs = []
    extra, missing = sorted(set(doc) - KEYS), sorted(KEYS - set(doc))
    if extra or missing:
        return [f"unexpected fields {extra}, missing fields {missing}"]
    if doc["kind"] != KIND:
        errs.append(f"kind: {doc['kind']!r}, want {KIND!r}")
    if not isinstance(doc["id"], str) or not ID.match(doc["id"]):
        errs.append("id: lowercase letters, digits, dots and dashes, 3 to 64 characters")
    pv = doc["partition_version"]
    if not isinstance(pv, int) or isinstance(pv, bool) or pv < 1:
        errs.append("partition_version: a positive integer")
    for key in ("hypothesis", "layer", "predicted_change"):
        _text(doc, key, errs)
    lanes = doc["target_lanes"]
    if not isinstance(lanes, list) or not lanes:
        errs.append("target_lanes: at least one lane")
    else:
        for i, lane in enumerate(lanes):
            if (not isinstance(lane, dict) or not lane or set(lane) - set(LANE_FIELDS)
                    or not all(isinstance(v, str) and v for v in lane.values())):
                errs.append(f"target_lanes[{i}]: a non-empty object of {list(LANE_FIELDS)}, each a non-empty string")
    if doc["sources"] != list(SOURCES):
        errs.append(f"sources: {list(SOURCES)} (only InferenceX units are held-out end to end)")
    crit = doc["criteria"]
    if not isinstance(crit, list) or not crit:
        errs.append("criteria: at least one")
    else:
        seen = set()
        for i, c in enumerate(crit):
            if not isinstance(c, dict) or set(c) != {"criterion", "margin"} or c["criterion"] not in CRITERIA:
                errs.append(f"criteria[{i}]: {{criterion: one of {list(CRITERIA)}, margin}}")
                continue
            m = c["margin"]
            if not isinstance(m, (int, float)) or isinstance(m, bool) or not math.isfinite(m) or m < 0:
                errs.append(f"criteria[{i}].margin: a finite number, zero or more")
            if c["criterion"] in seen:
                errs.append(f"criteria[{i}]: {c['criterion']} is listed twice")
            seen.add(c["criterion"])
    metrics = doc["metrics"]
    if (not isinstance(metrics, list) or not metrics or len(set(metrics)) != len(metrics)
            or not all(isinstance(m, str) and METRIC.match(m) for m in metrics)):
        errs.append("metrics: a non-empty list of distinct metric names")
    if not isinstance(doc["substream"], str) or not SUBSTREAM.match(doc["substream"]):
        errs.append("substream: the name of the gate's bootstrap substream (X6), 3 to 64 characters of [a-z0-9._/-]")
    if not isinstance(doc["measured_sha256"], str) or not HEX64.match(doc["measured_sha256"]):
        errs.append("measured_sha256: the SHA-256 of the measured table the evaluation reads")
    return errs


def digest(doc: dict) -> str:
    """sha256 of the canonical JSON of the document: what the budget ledger records."""
    return hashlib.sha256(contract.canonical_dumps(doc).encode("utf-8")).hexdigest()


def load(path) -> dict:
    p = Path(path)
    try:
        doc = json.loads(p.read_text(), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
    except (OSError, ValueError) as e:
        raise PreRegistrationError(f"{p.name}: cannot be read as JSON ({type(e).__name__})") from None
    errs = validate(doc)
    if errs:
        raise PreRegistrationError(f"{p.name}: " + "; ".join(errs))
    if p.stem != doc["id"]:
        raise PreRegistrationError(f"{p.name}: the file name is not the id {doc['id']!r}")
    return doc


def find(root: Path, prereg_id: str) -> dict:
    if not ID.match(prereg_id):
        raise PreRegistrationError("the pre-registration id is not an id")
    p = Path(root) / DIR / f"{prereg_id}.json"
    if not p.is_file():
        raise PreRegistrationError(f"no pre-registration {prereg_id!r} at {DIR}/ on this checkout")
    return load(p)


def lane_matches(pattern: dict, lane: dict) -> bool:
    return all(lane.get(k) == v for k, v in pattern.items())
