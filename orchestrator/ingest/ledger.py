"""The ledger's InferenceX units, as the scoring harness reads them (design §10.2, §11.7).

A point is one ledger unit. Its point_id is the unit_id, taken from the ledger's unit list
(blis-substrate catalog/ledger/units/inferencex.jsonl.gz) by the record's row id, so records the
ledger joins into one unit (duplicates, merged records and several measurements) are one point.
The harness also recomputes each record's identity with contract.unit_identity and requires it
to give the unit_id the list names (or, for a merged record, the unit_id the list says its own
identity has), so an API row that differs from the pinned source revision is refused, not
scored under a stale id.

The ingest report (catalog/ledger/reports/inferencex.yaml) lists every record the ledger left
out, with its reason; those are counted in coverage and never scored (COV-7).

Every reader here is strict: an unknown key is refused (SUB-12).
"""
from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from pathlib import Path

import contract

UNIT_KEYS = {"unit_id", "role_key", "identity", "measurements"}
MEASUREMENT_KEYS = {"record", "measured", "duplicates", "merged", "recorded"}
REPORT_KEYS = {"kind", "source", "revision", "input", "records", "units", "role_keys", "duplicates",
               "merged", "joined_units", "joined_records", "left_out", "units_by_framework"}
PUBLISHED_KEYS = {"kind", "role", "partition_version", "seed_sha256", "units"}

KEPT, DUPLICATE, MERGED = "kept", "duplicate", "merged"


class LedgerError(ValueError):
    """The ledger files, or a record checked against them, are not what the harness requires."""


@dataclass
class Unit:
    unit_id: str
    role_key: str
    identity: dict
    measurements: list

    @property
    def kept_record(self) -> str:
        """The record whose fields the unit carries: the smallest row id among its kept records."""
        return min((m["record"] for m in self.measurements), key=int)

    def records(self) -> list[str]:
        """Every record of the unit, kept, duplicate and merged, in row-id order."""
        out = []
        for m in self.measurements:
            out.append(m["record"])
            out += m["duplicates"]
            out += [x["record"] for x in m["merged"]]
        return sorted(out, key=int)


@dataclass
class Placement:
    """Where the ledger puts one record."""
    unit: Unit
    how: str                      # kept, duplicate or merged
    own_unit_id: str              # the unit_id the record's own identity has


@dataclass
class Ledger:
    units: dict = field(default_factory=dict)        # unit_id -> Unit
    by_record: dict = field(default_factory=dict)    # row id (str) -> Placement
    left_out: dict = field(default_factory=dict)     # row id (str) -> reason
    revision: str = ""

    def place(self, row: dict, dates: dict) -> Placement | None:
        """The record's unit, or None when the ledger's source revision does not hold the
        record. Raises LedgerError when the row's recomputed identity disagrees with the unit
        list."""
        rid = str(row["id"])
        p = self.by_record.get(rid)
        if p is None:
            return None
        got = contract.point_id(contract.unit_identity(row, dates))
        if got != p.own_unit_id:
            raise LedgerError(
                f"row {rid}: its identity hashes to {got}, but the ledger's unit list ({self.revision}) "
                f"gives {p.own_unit_id}; the row differs from the pinned source revision")
        return p


def _strict(obj, keys: set, where: str) -> dict:
    if not isinstance(obj, dict):
        raise LedgerError(f"{where}: not an object")
    extra = set(obj) - keys
    missing = keys - set(obj)
    if extra or missing:
        raise LedgerError(f"{where}: unexpected keys {sorted(extra)}, missing {sorted(missing)}")
    return obj


def read_units(path: Path) -> list[Unit]:
    raw = Path(path).read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    out = []
    for n, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        u = _strict(json.loads(line), UNIT_KEYS, f"{path}:{n}")
        for i, m in enumerate(u["measurements"]):
            _strict(m, MEASUREMENT_KEYS, f"{path}:{n}: measurements[{i}]")
        unit = Unit(u["unit_id"], u["role_key"], u["identity"], u["measurements"])
        if contract.point_id(unit.identity) != unit.unit_id:
            raise LedgerError(f"{path}:{n}: unit {unit.unit_id}: its identity hashes to another id")
        out.append(unit)
    return out


def load(ledger_dir: Path, source: str = contract.SOURCE) -> Ledger:
    """The units and the left-out records of one source, from a checkout of catalog/ledger."""
    import yaml
    d = Path(ledger_dir)
    lg = Ledger()
    for u in read_units(d / "units" / f"{source}.jsonl.gz"):
        if u.unit_id in lg.units:
            raise LedgerError(f"unit {u.unit_id} is listed twice")
        lg.units[u.unit_id] = u
        for m in u.measurements:
            for rid, how, own in ([(m["record"], KEPT, u.unit_id)]
                                  + [(x, DUPLICATE, u.unit_id) for x in m["duplicates"]]
                                  + [(x["record"], MERGED, x["unit_id"]) for x in m["merged"]]):
                if rid in lg.by_record:
                    raise LedgerError(f"record {rid} is in two units")
                lg.by_record[rid] = Placement(u, how, own)
    rep = _strict(yaml.safe_load((d / "reports" / f"{source}.yaml").read_text()), REPORT_KEYS,
                  f"reports/{source}.yaml")
    lg.revision = str(rep["revision"])
    for reason, ids in sorted((rep["left_out"] or {}).items()):
        for rid in ids:
            lg.left_out[str(rid)] = reason
    return lg


def read_unit_set(path: Path) -> set[str]:
    """A set of ledger units to score (design §11.7): a published list (published/<role>.yaml,
    kind PublishedUnits) or a plain file of unit ids, one per line."""
    text = Path(path).read_text()
    first = next((ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")), "")
    if first.startswith("kind:") or first.startswith("{"):
        import yaml
        doc = _strict(yaml.safe_load(text), PUBLISHED_KEYS, str(path))
        if doc["kind"] != "PublishedUnits":
            raise LedgerError(f"{path}: kind {doc['kind']!r}, want PublishedUnits")
        ids = doc["units"]
    else:
        ids = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    bad = [i for i in ids if not (isinstance(i, str) and len(i) == 64 and all(c in "0123456789abcdef" for c in i))]
    if bad:
        raise LedgerError(f"{path}: {bad[0]!r} is not a unit_id")
    return set(ids)
