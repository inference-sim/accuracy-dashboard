"""Evaluation of the four G1 conditions that were unevaluated (design 11.3, issue #53).

A point is G1 only when every condition of G1 was evaluated and is true. Four conditions need
data the Result and the field list did not carry:

  coefficient_range  no priced coefficient was extrapolated or unidentified
  kernel_hash        each library version the run recorded maps to the kernel hash BLIS priced
  value_class        each modelled field the run set holds a value inside a class its evidence covers
  resolved_differs   each setting the run's log resolved equals the engine's resolution

Each is evaluated only when the data it needs is present for the point. Then it names a substitution
of its kind for every case where it is false, or nothing when it is true. When the data is absent
the condition stays unevaluated and the point names it so (grade.unchecked). Nothing here guesses a
missing datum or reads a registry file (X7): the data is the Result's and the field list's.

THE SHAPE READ HERE is the one blis-substrate layer 10 (substrate#43) and inference-sim PR 5
(#2103) are described to write, taken from the description, not from a released Result. Check it
against the released one. Each coefficient of doc["selected_entries"]["coefficients"] may carry

  "extrapolated": bool, "unidentified": bool, "fit_range": any   (from kernel.Trust)
  "kernel_impl": {"library": str, "variant": str, "code_hash": str,
                  "library_versions": {version: code_hash}}      (the hashes of the library
                                                                  versions the measurement covers)

and doc["resolutions"] is a list of {"setting": path, "engine": value, "host": value} (the engine's
resolution of a setting beside the host's, kernel.Resolution). The field list's value classes are
fields.Field.value_classes. `library_versions` and the top-level name `resolutions` are the least
certain names.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import fields as fl
import grade as gr


@dataclass
class Evaluation:
    kind: str
    evaluated: bool
    subs: list = field(default_factory=list)
    why: str = ""       # when not evaluated, what data is missing


def _unevaluated(kind: str, why: str) -> Evaluation:
    return Evaluation(kind, False, [], why)


def _coefficients(doc) -> list | None:
    report = (doc or {}).get("selected_entries")
    cs = report.get("coefficients") if isinstance(report, dict) else None
    return cs if isinstance(cs, list) and cs else None


def coefficient_range(doc) -> Evaluation:
    kind = "coefficient_range"
    cs = _coefficients(doc)
    if cs is None:
        return _unevaluated(kind, "the Result has no selected-entry report")
    subs = []
    for c in cs:
        if not isinstance(c.get("extrapolated"), bool) or not isinstance(c.get("unidentified"), bool):
            return _unevaluated(kind, f"coefficient {c.get('set')}/{c.get('name')} carries no extrapolated or unidentified flag")
        if c["extrapolated"] or c["unidentified"]:
            what = " and ".join(w for w, on in (("extrapolated", c["extrapolated"]), ("unidentified", c["unidentified"])) if on)
            rng = f", fit range {c['fit_range']}" if c.get("fit_range") is not None else ""
            subs.append({"kind": kind, "subject": f"{c['set']}/{c['name']}", "detail": what + rng})
    return Evaluation(kind, True, sorted(subs, key=lambda s: s["subject"]))


def kernel_hash(doc, libraries: dict | None) -> Evaluation:
    """libraries: library -> the version the run recorded (server log or launch configuration)."""
    kind = "kernel_hash"
    cs = _coefficients(doc)
    if cs is None:
        return _unevaluated(kind, "the Result has no selected-entry report")
    impls = {}
    for c in cs:
        k = c.get("kernel_impl")
        if isinstance(k, dict) and k.get("library"):
            impls[(k["library"], k.get("variant"))] = k
    if not impls:
        return _unevaluated(kind, "no coefficient names its kernel implementation")
    subs = []
    for (lib, variant), k in sorted(impls.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        if not k.get("code_hash") or not isinstance(k.get("library_versions"), dict):
            return _unevaluated(kind, f"{lib}: the Result names no code hash or no hash per library version")
        version = (libraries or {}).get(lib)
        if version is None:
            return _unevaluated(kind, f"the run records no version of {lib}")
        have = k["library_versions"].get(version)
        if have != k["code_hash"]:
            detail = (f"{lib} {version} has kernel hash {have}" if have else f"{lib} {version} maps to no kernel hash") \
                + f", BLIS priced {k['code_hash']}"
            subs.append({"kind": kind, "subject": lib, "detail": detail})
    return Evaluation(kind, True, subs)


def in_class(value, cls: dict) -> bool:
    if "values" in cls:
        return any(_same(value, v) for v in cls["values"])
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return ("min" not in cls or value >= cls["min"]) and ("max" not in cls or value <= cls["max"])


def _same(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return str(a) == str(b)


def value_class(requested: dict | None, field_list) -> Evaluation:
    """requested: path -> the value the run set, for the settings it set (not the engine's own
    resolution). Only a modelled field has value classes (VLM-3); a proven-inert one cannot matter."""
    kind = "value_class"
    subs = []
    for path, value in sorted((requested or {}).items()):
        f = field_list.lookup(path)
        if f is None or f.status != fl.MODELLED:
            continue
        if f.value_classes is None:
            return _unevaluated(kind, f"the field list states no value class for {path}")
        if not any(in_class(value, c) for c in f.value_classes):
            subs.append({"kind": kind, "subject": path,
                         "detail": f"{value!r} is outside every value class the evidence covers"})
    return Evaluation(kind, True, subs)


def resolved_value(doc, resolved: dict | None) -> Evaluation:
    """resolved: setting path -> the value the run's log resolved."""
    kind = "resolved_differs"
    rs = (doc or {}).get("resolutions")
    if not isinstance(rs, list) or not rs:
        return _unevaluated(kind, "the Result records no engine resolution")
    subs = []
    for r in rs:
        path = r.get("setting")
        if path in (resolved or {}) and not _same(resolved[path], r.get("engine")):
            subs.append({"kind": kind, "subject": path,
                         "detail": f"the run resolved {resolved[path]!r}, the engine resolves {r.get('engine')!r}"})
    return Evaluation(kind, True, sorted(subs, key=lambda s: s["subject"]))


def evaluate(doc, *, field_list, requested=None, resolved=None, libraries=None) -> list[Evaluation]:
    return [coefficient_range(doc), kernel_hash(doc, libraries), value_class(requested, field_list),
            resolved_value(doc, resolved)]


def split(evals: list[Evaluation]) -> tuple[list[dict], list[str]]:
    """(the substitutions the evaluated conditions name, the kinds still unevaluated)."""
    subs = [s for e in evals if e.evaluated for s in e.subs]
    return subs, [e.kind for e in evals if not e.evaluated]


assert set(gr.UNCHECKED_KINDS) == {"coefficient_range", "kernel_hash", "value_class", "resolved_differs"}
