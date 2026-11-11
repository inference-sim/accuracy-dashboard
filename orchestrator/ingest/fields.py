"""The engine's field list, fields.json, as the scorer reads it (design §11.1, §11.2; COV-3).

The engine repository classifies every configuration field and environment variable its
release reads (VLM-3), and states each field's estimation rule. The dashboard keeps no table of
its own: Decide and Estimate read this list only.

The scorer reads the list from `blis fields --engine <kind> --json`, which prints it at the
engine release the scoring build runs (cli.read_fields).

The loader is strict (SUB-12): unknown keys are refused at every level, and the rules of
blis-substrate contracts/spec/fields (Validate) are checked: the evidence a status takes, the
estimation rule's shape, and the order by name then source.

A setting a run records is named by its dotted path: a configuration field as the upstream
spells it ("max_num_seqs", "attention_config.backend"), or "env.<NAME>" for an environment
variable. A field of the list that holds a config object ("kv_transfer_config.kv_connector_extra_config")
covers every path below it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

MODELLED, PROVEN_INERT, NOT_MODELLED, INERT_UNPROVEN = "modelled", "proven_inert", "not_modelled", "inert_unproven"
STATUSES = (MODELLED, PROVEN_INERT, NOT_MODELLED, INERT_UNPROVEN)
EVIDENCE_FOR = {MODELLED: "traces", PROVEN_INERT: "proof", NOT_MODELLED: "issue", INERT_UNPROVEN: "note"}
LEAVE_UNSET, SUBSTITUTE, NONE = "leave_unset", "substitute", "none"

_LIST_KEYS = {"kind", "engine", "fields"}
_ENGINE_KEYS = {"kind", "version"}
_FIELD_KEYS = {"name", "source", "status", "evidence", "estimation", "value_classes"}
_CLASS_KEYS = {"type", "covered", "values", "thresholds", "covered_classes"}
_THRESHOLD_KEYS = {"value", "closed"}
CLASS_TYPES = ("boolean", "enumerated", "numeric")
_EVIDENCE_KEYS = {"traces", "proof", "issue", "note"}
_ESTIMATION_KEYS = {"rule", "setting", "reason"}


class FieldsError(ValueError):
    """The field list breaks contracts/spec/fields, naming the field and value."""


@dataclass(frozen=True)
class Field:
    name: str
    source: str              # config or env
    status: str
    evidence: dict
    estimation: dict
    # The value classes the field's evidence covers (VLM-3, blis-vllm#102), as the object
    # _value_classes reads; None when the list states none for the field.
    value_classes: dict | None = None

    @property
    def path(self) -> str:
        return self.name if self.source == "config" else f"env.{self.name}"


@dataclass
class FieldList:
    engine: dict
    fields: dict = field(default_factory=dict)     # path -> Field

    def lookup(self, path: str) -> Field | None:
        """The field a recorded path is: the field of that name, else the nearest field above
        it that holds a config object. None when the release has no such field."""
        if path in self.fields:
            return self.fields[path]
        parts = path.split(".")
        for i in range(len(parts) - 1, 0, -1):
            f = self.fields.get(".".join(parts[:i]))
            if f is not None:
                return f
        return None


def _keys(obj, allowed: set, where: str) -> dict:
    if not isinstance(obj, dict):
        raise FieldsError(f"{where}: must be an object, got {type(obj).__name__}")
    extra = sorted(set(obj) - allowed)
    if extra:
        raise FieldsError(f"{where}: unknown key {extra[0]!r}")
    return obj


def _no_duplicates(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise FieldsError(f"duplicate key {k!r}")
        out[k] = v
    return out


def _value_classes(raw, where: str, status: str) -> dict:
    """The value classes a field's evidence covers (blis-substrate fields.ValueClasses): {type,
    covered, values, thresholds, covered_classes}. A numeric field's class of x is the number of
    thresholds t with x > t.value, or x == t.value where the threshold is closed "above"."""
    c = _keys(raw, _CLASS_KEYS, where)
    t = c.get("type")
    if t not in CLASS_TYPES:
        raise FieldsError(f"{where}.type: must be one of {CLASS_TYPES}, got {t!r}")
    if t == "numeric":
        th = c.get("thresholds")
        if not isinstance(th, list) or not th:
            raise FieldsError(f"{where}.thresholds: a numeric field needs thresholds")
        for k, x in enumerate(th):
            x = _keys(x, _THRESHOLD_KEYS, f"{where}.thresholds[{k}]")
            if isinstance(x.get("value"), bool) or not isinstance(x.get("value"), (int, float)) or x.get("closed") not in ("above", "below"):
                raise FieldsError(f"{where}.thresholds[{k}]: a number value and closed 'above' or 'below'")
        cc = c.get("covered_classes")
        if not isinstance(cc, list) or not cc or any(isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= len(th) for n in cc):
            raise FieldsError(f"{where}.covered_classes: integers from 0 to {len(th)}")
    else:
        if "thresholds" in c or "covered_classes" in c:
            raise FieldsError(f"{where}: thresholds and covered_classes only for a numeric field")
        if not isinstance(c.get("covered"), list) or not c["covered"] or not all(isinstance(x, str) for x in c["covered"]):
            raise FieldsError(f"{where}.covered: a non-empty list of strings")
    if status == PROVEN_INERT and t != "numeric" and not c.get("values"):
        raise FieldsError(f"{where}.values: a proven-inert field lists every value")
    return c


def class_of(x, classes: dict) -> int:
    """The numeric class of x: the number of thresholds it is above (or on, where closed above)."""
    return sum(1 for t in classes["thresholds"] if x > t["value"] or (t["closed"] == "above" and x == t["value"]))


def covers(value, classes: dict) -> bool:
    """Whether the field's evidence covers `value` (the reimplementation of the substrate's
    ValueClasses.Covers, pinned by test_g1.py). Unlike the substrate it returns False, not an error,
    for a value of the wrong type, and accepts a number for an enumerated field by its text, because
    a value read from a log is parsed."""
    if classes["type"] == "numeric":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        return class_of(value, classes) in classes["covered_classes"]
    text = str(value).lower() if isinstance(value, bool) else str(value)
    return text in classes["covered"]


def parse(data: bytes | str) -> FieldList:
    doc = json.loads(data, object_pairs_hook=_no_duplicates)
    _keys(doc, _LIST_KEYS, "field list")
    if doc.get("kind") != "FieldList":
        raise FieldsError(f"kind: must be 'FieldList', got {doc.get('kind')!r}")
    eng = _keys(doc.get("engine"), _ENGINE_KEYS, "engine")
    if not eng.get("kind") or not eng.get("version"):
        raise FieldsError("engine: kind and version are required")
    fl = FieldList(engine={"kind": eng["kind"], "version": eng["version"]})
    prev = None
    for i, raw in enumerate(doc.get("fields") or []):
        where = f"fields[{i}]({raw.get('name') if isinstance(raw, dict) else '?'})"
        f = _keys(raw, _FIELD_KEYS, where)
        name, source, status = f.get("name"), f.get("source"), f.get("status")
        if not name:
            raise FieldsError(f"{where}.name: required")
        if source not in ("config", "env"):
            raise FieldsError(f"{where}.source: must be 'config' or 'env', got {source!r}")
        if status not in STATUSES:
            raise FieldsError(f"{where}.status: must be one of {STATUSES}, got {status!r}")
        ev = _keys(f.get("evidence"), _EVIDENCE_KEYS, f"{where}.evidence")
        if set(ev) != {EVIDENCE_FOR[status]}:
            raise FieldsError(f"{where}.evidence: status {status!r} takes exactly evidence.{EVIDENCE_FOR[status]}, "
                              f"got {sorted(ev)}")
        est = _keys(f.get("estimation"), _ESTIMATION_KEYS, f"{where}.estimation")
        rule = est.get("rule")
        if rule == SUBSTITUTE:
            if not est.get("setting") or not est.get("reason"):
                raise FieldsError(f"{where}.estimation: rule 'substitute' needs a setting and a reason")
        elif rule in (LEAVE_UNSET, NONE):
            if "setting" in est or "reason" in est:
                raise FieldsError(f"{where}.estimation: setting and reason only with rule 'substitute'")
        else:
            raise FieldsError(f"{where}.estimation.rule: must be one of leave_unset, substitute, none, got {rule!r}")
        key = (name, source)
        if prev is not None and not prev < key:
            raise FieldsError(f"{where}: out of order or repeated: {key} must sort after {prev}")
        prev = key
        classes = None
        if "value_classes" in f:
            if status not in (MODELLED, PROVEN_INERT):
                raise FieldsError(f"{where}.value_classes: only a modelled or proven-inert field has value classes")
            classes = _value_classes(f["value_classes"], f"{where}.value_classes", status)
        fld = Field(name, source, status, ev, est, classes)
        fl.fields[fld.path] = fld
    return fl


# ------------------------------------------------------------------ Decide and Estimate

@dataclass
class Decision:
    """What one recorded setting does to a point (design §11.2's Decide and Estimate)."""
    path: str
    status: str | None                # the field's status; None when the release has no field
    substitution: dict | None = None  # a G2 substitution to name on the point
    g5: dict | None = None            # a G5 reason


def decide(fl: FieldList, path: str, *, set_by_run: bool) -> Decision:
    """A recorded setting, by the engine's own classification.

    set_by_run: the run set the field (a value it passed, or a resolved value at other than
    the release's default). A field the run left at the engine's resolution changes nothing,
    whatever its status.
    """
    f = fl.lookup(path)
    if f is None:
        return Decision(path, None, g5={"code": "field_not_in_release", "subject": path})
    if not set_by_run:
        return Decision(path, f.status)
    if f.status in (MODELLED, PROVEN_INERT):
        return Decision(path, f.status)
    if f.status == INERT_UNPROVEN:
        return Decision(path, f.status, substitution={
            "kind": "interim_status", "subject": path,
            "detail": "inert, unproven: allowed only until M2 (release plan §3.3)"})
    # not_modelled: the estimation rule, if the engine states one.
    rule = f.estimation.get("rule")
    if rule == SUBSTITUTE:
        return Decision(path, f.status, substitution={
            "kind": "estimated", "subject": path,
            "detail": f"substitute {json.dumps(f.estimation['setting'], sort_keys=True)}: {f.estimation['reason']}"})
    if rule == LEAVE_UNSET:
        return Decision(path, f.status, substitution={
            "kind": "estimated", "subject": path, "detail": "left unset; the engine resolves the upstream default"})
    return Decision(path, f.status, g5={"code": "field_not_modelled", "subject": path})


def estimate_missing(fl: FieldList, path: str) -> Decision:
    """A value the simulation needs that the run did not record (design §11.2, Estimate)."""
    f = fl.lookup(path)
    if f is None:
        return Decision(path, None, g5={"code": "field_not_in_release", "subject": path})
    rule = f.estimation.get("rule")
    if rule == LEAVE_UNSET:
        return Decision(path, f.status, substitution={
            "kind": "estimated", "subject": path,
            "detail": "not recorded; left unset, so the engine resolves the upstream default"})
    if rule == SUBSTITUTE:
        return Decision(path, f.status, substitution={
            "kind": "estimated", "subject": path,
            "detail": f"not recorded; substitute {json.dumps(f.estimation['setting'], sort_keys=True)}: "
                      f"{f.estimation['reason']}"})
    return Decision(path, f.status, g5={"code": "value_not_recorded", "subject": path})
