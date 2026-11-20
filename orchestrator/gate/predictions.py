"""The candidate's predictions, read as untrusted input (design §12.3, X22).

A candidate job runs a pull request's code with no secret and writes one Predictions document. This loader
is the gate job's only door to it: a size cap, strict fields, the candidate commit equal to the head the
Actions API reports for the run, every handed unit covered once, finite values, and metric names of one
shape. Nothing the document says is trusted beyond that: the roles, the measured values and the scoring
come from the gate's own side. Error messages name a field and a count, never a unit or a value.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

MAX_BYTES = 64 * 1024 * 1024
KIND = "Predictions"
METRIC = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
HEX40, HEX64 = re.compile(r"^[0-9a-f]{40}$"), re.compile(r"^[0-9a-f]{64}$")
DOC_KEYS = {"kind", "candidate", "harness", "predictions"}
SOURCE = "inferencex"


class PredictionsError(ValueError):
    pass


@dataclass(frozen=True)
class Predictions:
    candidate: str
    harness: str
    values: dict       # unit_id -> {metric: float}; a unit with a reason has {}


def load(path, want_candidate: str, want_units: set) -> Predictions:
    p = Path(path)
    size = p.stat().st_size
    if size > MAX_BYTES:
        raise PredictionsError(f"the document is {size} bytes; the cap is {MAX_BYTES}")
    try:
        doc = json.loads(p.read_bytes(), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
    except ValueError:
        raise PredictionsError("not JSON, or holds a NaN or an infinity") from None
    if not isinstance(doc, dict) or set(doc) != DOC_KEYS:
        raise PredictionsError(f"the fields are not exactly {sorted(DOC_KEYS)}")
    if doc["kind"] != KIND:
        raise PredictionsError(f"kind is not {KIND}")
    if not isinstance(doc["candidate"], str) or not HEX40.match(doc["candidate"]):
        raise PredictionsError("candidate is not a 40-hex commit")
    if doc["candidate"] != want_candidate:
        raise PredictionsError("candidate is not the head commit of the run the Actions API reports (X22)")
    if not isinstance(doc["harness"], str) or not HEX64.match(doc["harness"]):
        raise PredictionsError("harness is not a SHA-256 digest of the harness the run used")
    rows = doc["predictions"]
    if not isinstance(rows, list):
        raise PredictionsError("predictions is not a list")
    out: dict = {}
    for i, r in enumerate(rows):
        if not isinstance(r, dict) or not (set(r) == {"source", "unit_id", "values"} or set(r) == {"source", "unit_id", "reason"}):
            raise PredictionsError(f"predictions[{i}]: fields are not source, unit_id and values or reason")
        if r["source"] != SOURCE:
            raise PredictionsError(f"predictions[{i}]: source is not {SOURCE}")
        uid = r["unit_id"]
        if not isinstance(uid, str) or not HEX64.match(uid):
            raise PredictionsError(f"predictions[{i}]: unit_id is not 64 lowercase hex digits")
        if uid in out:
            raise PredictionsError(f"predictions[{i}]: a unit is predicted twice")
        if "reason" in r:
            if not isinstance(r["reason"], str) or not r["reason"] or len(r["reason"]) > 200:
                raise PredictionsError(f"predictions[{i}]: reason is not a short non-empty string")
            out[uid] = {}
            continue
        vals = r["values"]
        if not isinstance(vals, dict) or not vals:
            raise PredictionsError(f"predictions[{i}]: values is not a non-empty object")
        for m, v in vals.items():
            if not METRIC.match(m):
                raise PredictionsError(f"predictions[{i}]: a metric name is not [a-z][a-z0-9_]{{0,63}}")
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise PredictionsError(f"predictions[{i}]: a value is not a finite number")
        out[uid] = {m: float(v) for m, v in vals.items()}
    unknown, missing = set(out) - want_units, want_units - set(out)
    if unknown:
        raise PredictionsError(f"{len(unknown)} predictions are for units that were not handed to the candidate")
    if missing:
        raise PredictionsError(f"{len(missing)} handed units have no prediction; an absent prediction is a reason, not a gap")
    return Predictions(doc["candidate"], doc["harness"], out)
