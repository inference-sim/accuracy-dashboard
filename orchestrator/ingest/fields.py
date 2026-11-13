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
_ESTIMATION_KEYS = {"rule", "setting", "reason", "preserves", "valid_when"}



_CLAUSE_LISTS = ("value_in", "value_list_has_any", "value_list_has_none", "value_not_prefixed")
_CLAUSE_KEYS = set(_CLAUSE_LISTS) | {"tp_group_nodes", "compute_capability"}
_COMPARISONS = ("eq", "gt", "gte", "lt", "lte")


def _check_valid_when(est: dict, where: str) -> None:
    """The substrate's validation of preserves and valid_when (contracts/spec/fields validate.go and load.go), ported whole: only a
    rule with a stand-in has them; valid_when needs the sentence `preserves` and at least one clause; a clause sets at least one
    known key and holds for no value when it sets nothing; a string list is non-empty with no blank entry; a comparison sets at
    least one known operator; a node count is a whole number; a capability is "<major>.<minor>". A null valid_when is absent."""
    at = f"{where}.estimation"
    preserves = est.get("preserves")
    if preserves is not None and not isinstance(preserves, str):
        raise FieldsError(f"{at}.preserves: must be a string")
    vw = est.get("valid_when")
    if est.get("rule") not in (LEAVE_UNSET, SUBSTITUTE):
        if preserves:
            raise FieldsError(f"{at}.preserves: only with rule {LEAVE_UNSET!r} or {SUBSTITUTE!r}, got rule {est.get('rule')!r}")
        if vw is not None:
            raise FieldsError(f"{at}.valid_when: only with rule {LEAVE_UNSET!r} or {SUBSTITUTE!r}, got rule {est.get('rule')!r}")
        return
    if vw is None:
        return
    if not isinstance(vw, list):
        raise FieldsError(f"{at}.valid_when: must be a list of clauses")
    if not preserves:
        raise FieldsError(f"{at}.preserves: required with valid_when: the sentence naming what the upstream resolves identically")
    if not vw:
        raise FieldsError(f"{at}.valid_when: must list at least one clause; omit it to apply the rule to every value")
    for i, c in enumerate(vw):
        _check_clause(c, f"{at}.valid_when[{i}]")


def _no_keys_outside(obj: dict, allowed, at: str) -> None:
    for k in obj:
        if k not in allowed:
            raise FieldsError(f'{at}: unknown key "{k}"')


def _check_clause(c, at: str) -> None:
    if not isinstance(c, dict):
        raise FieldsError(f"{at}: a clause is an object")
    _no_keys_outside(c, _CLAUSE_KEYS, at)
    # a null key is an unset key, as the substrate's decoder reads it
    set_keys = 0
    for key in _CLAUSE_LISTS:
        vals = c.get(key)
        if vals is None:
            continue
        set_keys += 1
        if not isinstance(vals, list) or any(not isinstance(v, str) for v in vals):
            raise FieldsError(f"{at}.{key}: must be a list of strings")
        if not vals:
            raise FieldsError(f"{at}.{key}: must list at least one string")
        for j, v in enumerate(vals):
            if not v.strip():
                raise FieldsError(f"{at}.{key}[{j}]: must not be empty")
    for key, kind in (("tp_group_nodes", "nodes"), ("compute_capability", "capability")):
        cmp = c.get(key)
        if cmp is None:
            continue
        set_keys += 1
        if not isinstance(cmp, dict):
            raise FieldsError(f"{at}.{key}: must be an object of comparisons")
        _no_keys_outside(cmp, _COMPARISONS, f"{at}.{key}")
        given = {op: v for op, v in cmp.items() if v is not None}
        if not given:
            raise FieldsError(f"{at}.{key}: must set at least one of eq, gt, gte, lt, lte")
        for op, v in given.items():
            if kind == "nodes" and (not isinstance(v, int) or isinstance(v, bool)):
                raise FieldsError(f"{at}.{key}.{op}: must be a whole number, got {v!r}")
            if kind == "capability":
                if not isinstance(v, str):
                    raise FieldsError(f'{at}.{key}.{op}: must be a string "<major>.<minor>", such as "10.0", got {v!r}')
                if _capability(v) is None:
                    raise FieldsError(f'{at}.{key}.{op}: must be "<major>.<minor>", such as "10.0", got {v!r}')
    if set_keys == 0:
        raise FieldsError(f"{at}: a clause must set at least one key, or it would hold for every value")


def _capability(s):
    import re
    m = re.fullmatch(r"([0-9]+)\.([0-9]+)", str(s).strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def _compare(cmp: dict, have, parse) -> bool:
    ok = {"eq": lambda r: r == 0, "gt": lambda r: r > 0, "gte": lambda r: r >= 0, "lt": lambda r: r < 0, "lte": lambda r: r <= 0}
    for k, want in cmp.items():
        if want is None:                    # null is an unset comparison, as in the substrate's decoder
            continue
        w = parse(want)
        if k not in ok or w is None or not ok[k]((have > w) - (have < w)):
            return False
    return True


def exact(estimation: dict, facts: dict) -> bool:
    """Whether the estimation rule's stand-in is exact for a recorded value: the substrate's evaluator
    (contracts/spec/fields Exact), ported. Never exact for a rule without a stand-in; exact for every value when valid_when is
    absent; else exact when at least one clause holds. `facts`: value (any case, untrimmed), tp_group_nodes (int), compute_capability
    ("major.minor"); a fact left out makes a clause that needs it false."""
    if estimation.get("rule") not in (LEAVE_UNSET, SUBSTITUTE):
        return False
    clauses = estimation.get("valid_when")
    if clauses is None:
        return True
    v = str(facts.get("value", "")).strip().lower()
    fold = lambda s: str(s).strip().lower()
    items = {i.strip() for i in v.split(",") if i.strip()}
    nodes, cap = facts.get("tp_group_nodes"), _capability(facts.get("compute_capability", ""))

    def holds(c: dict) -> bool:
        if c.get("value_in") is not None and v not in {fold(s) for s in c["value_in"]}:
            return False
        if c.get("value_list_has_any") is not None and not any(fold(s) in items for s in c["value_list_has_any"]):
            return False
        if c.get("value_list_has_none") is not None and any(fold(s) in items for s in c["value_list_has_none"]):
            return False
        if any(v.startswith(fold(p)) for p in c.get("value_not_prefixed") or ()):
            return False
        if c.get("tp_group_nodes") is not None and (not isinstance(nodes, int) or isinstance(nodes, bool)
                                       or not _compare(c["tp_group_nodes"], nodes, lambda x: x if isinstance(x, int) else None)):
            return False
        if c.get("compute_capability") is not None and (cap is None or not _compare(c["compute_capability"], cap, _capability)):
            return False
        return True
    return any(holds(c) for c in clauses)


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
        th = c.get("thresholds", [])      # none: one class, number 0
        if not isinstance(th, list):
            raise FieldsError(f"{where}.thresholds: a list")
        if [t.get("value") for t in th if isinstance(t, dict)] != sorted({t.get("value") for t in th if isinstance(t, dict)}):
            raise FieldsError(f"{where}.thresholds: strictly increasing")
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
    return sum(1 for t in classes.get("thresholds", []) if x > t["value"] or (t["closed"] == "above" and x == t["value"]))


def covers(value, classes: dict) -> bool:
    """Whether the field's evidence covers `value` (the reimplementation of the substrate's
    ValueClasses.Covers, pinned by test_g1.py). Unlike the substrate it returns False, not an error,
    for a value of the wrong type or a NaN or infinite number (a number written as a string is read as the substrate reads it), and accepts a number for an enumerated field by its text, because
    a value read from a log is parsed."""
    if classes["type"] == "numeric":
        if isinstance(value, str):
            try:
                value = float(value.strip())
            except ValueError:
                return False
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value in (float("inf"), float("-inf")):
            return False       # not a finite number (the substrate refuses NaN and infinity)
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
        _check_valid_when(est, where)
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
