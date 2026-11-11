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

THE SHAPE READ HERE is blis-substrate layer 10's, provisional commit 2a9ea3d1 of branch
m2/10-router-table-and-closeness-record (it will be rebased). Each entry of
doc["selected_entries"]["coefficients"] may carry

  "kernel_impls": [{library, variant, code_hash}]   the kernels the entry is valid for (maybe none)
  "fit_range": [{dim, low, high}]                   the fit's input range (maybe none)
  "extrapolated": true, "unidentified": true        written only when true (omitted when false)

and doc["resolutions"] is a list of {setting, host, engine, reason}, all values strings, `host`
absent when the host gave none and `reason` present only where host and engine differ. A field of
the field list may carry `value_classes`, an object (fields._value_classes).

What the shape cannot say, and what is done about it:

  * The Result has no version marker, and a boolean is omitted when false, so a coefficient without
    flags is either clean or written by an older build. A report is taken as written by a build
    that carries the data when some coefficient of it carries kernel_impls, fit_range or a flag;
    a report with none of them leaves coefficient_range unevaluated.
  * Resolutions are always written by a build that carries them (a mode resolved without moving is
    recorded too), so an absent or empty list leaves resolved_differs unevaluated.
  * The substrate holds no map from a library version to a kernel hash, and the dashboard has none
    (blis-registry#73 asks for the engine to publish one). kernel_hash is evaluated only when the
    caller passes such a map, `version_hashes`; the scorer passes none, so the condition stays
    unevaluated on every point until a published source exists.
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


_NEW_KEYS = ("kernel_impls", "fit_range", "extrapolated", "unidentified")


def coefficient_range(doc) -> Evaluation:
    kind = "coefficient_range"
    cs = _coefficients(doc)
    if cs is None:
        return _unevaluated(kind, "the Result has no selected-entry report")
    if not any(k in c for c in cs for k in _NEW_KEYS):
        return _unevaluated(kind, "no coefficient carries a fit range, kernel implementation or trust flag: "
                                  "the Result was written by a build that does not report them")
    subs = []
    for c in cs:
        flags = [w for w in ("extrapolated", "unidentified") if c.get(w) is True]
        if flags:
            rng = "; fit range " + ", ".join(f"{b['dim']} {b['low']} to {b['high']}" for b in c.get("fit_range") or [])
            subs.append({"kind": kind, "subject": f"{c['set']}/{c['name']}",
                         "detail": " and ".join(flags) + (rng if c.get("fit_range") else "")})
    return Evaluation(kind, True, sorted(subs, key=lambda s: s["subject"]))


def kernel_hash(doc, libraries: dict | None, version_hashes: dict | None = None) -> Evaluation:
    """libraries: library -> the version the run recorded. version_hashes: library -> {version ->
    kernel code hash}, from a source that publishes the hash of each library release (none exists
    yet; blis-registry#73). Both are needed for each library a coefficient's kernel_impls name."""
    kind = "kernel_hash"
    cs = _coefficients(doc)
    if cs is None:
        return _unevaluated(kind, "the Result has no selected-entry report")
    priced: dict = {}
    for c in cs:
        for k in c.get("kernel_impls") or []:
            priced.setdefault(k["library"], set()).add(k["code_hash"])
    if not priced:
        return _unevaluated(kind, "no coefficient names a kernel implementation")
    if not version_hashes:
        return _unevaluated(kind, "no source maps a library version to a kernel hash")
    subs = []
    for lib, hashes in sorted(priced.items()):
        version = (libraries or {}).get(lib)
        if version is None:
            return _unevaluated(kind, f"the run records no version of {lib}")
        table = version_hashes.get(lib)
        if table is None:
            return _unevaluated(kind, f"no source maps a version of {lib} to a kernel hash")
        have = table.get(version)
        if have not in hashes:
            detail = (f"{lib} {version} has kernel hash {have}" if have else f"{lib} {version} maps to no kernel hash") \
                + f", BLIS priced {', '.join(sorted(hashes))}"
            subs.append({"kind": kind, "subject": lib, "detail": detail})
    return Evaluation(kind, True, subs)


def _same(a, b) -> bool:
    """Equality of a value the run logged and a value the Result records as a string."""
    def norm(x):
        if isinstance(x, bool):
            return str(x).lower()
        return str(x).strip().lower()
    return norm(a) == norm(b)


def value_class(requested: dict | None, field_list) -> Evaluation:
    """requested: path -> the value the run set, for the settings it set (not the engine's own
    resolution). A modelled or proven-inert field carries value classes (VLM-3)."""
    kind = "value_class"
    subs = []
    for path, value in sorted((requested or {}).items()):
        f = field_list.lookup(path)
        if f is None or f.status not in (fl.MODELLED, fl.PROVEN_INERT):
            continue
        if f.value_classes is None:
            return _unevaluated(kind, f"the field list states no value class for {path}")
        if not fl.covers(value, f.value_classes):
            subs.append({"kind": kind, "subject": path,
                         "detail": f"{value!r} is outside every value class the evidence covers"})
    return Evaluation(kind, True, subs)


# The Result's setting names for the settings the run's log states under a vLLM name. A declined
# request is recorded under its own field name, which is the vLLM name, so it needs no entry.
# TEMPORARY, from the names the Result is described to use; settings with no entry here
# (expert_parallel_width, all_reduce_backend, cascade_attention, sequence_parallel_moe) are not
# compared.
RESOLUTION_NAMES = {"tensor_parallel_width": "tensor_parallel_size", "data_parallel_width": "data_parallel_size",
                    "async_scheduling": "async_scheduling"}


def resolved_value(doc, resolved: dict | None) -> Evaluation:
    """resolved: vLLM setting path -> the value the run's log resolved."""
    kind = "resolved_differs"
    rs = (doc or {}).get("resolutions")
    if not isinstance(rs, list) or not rs:
        return _unevaluated(kind, "the Result records no engine resolution")
    subs = []
    for r in rs:
        name = RESOLUTION_NAMES.get(r.get("setting"), r.get("setting"))
        if name in (resolved or {}) and not _same(resolved[name], r.get("engine")):
            subs.append({"kind": kind, "subject": name,
                         "detail": f"the run resolved {resolved[name]!r}, the engine resolves {r.get('engine')!r}"})
    return Evaluation(kind, True, sorted(subs, key=lambda s: s["subject"]))


def evaluate(doc, *, field_list, requested=None, resolved=None, libraries=None,
             version_hashes=None) -> list[Evaluation]:
    return [coefficient_range(doc), kernel_hash(doc, libraries, version_hashes), value_class(requested, field_list),
            resolved_value(doc, resolved)]


def split(evals: list[Evaluation]) -> tuple[list[dict], list[str]]:
    """(the substitutions the evaluated conditions name, the kinds still unevaluated)."""
    subs = [s for e in evals if e.evaluated for s in e.subs]
    return subs, [e.kind for e in evals if not e.evaluated]


assert set(gr.UNCHECKED_KINDS) == {"coefficient_range", "kernel_hash", "value_class", "resolved_differs"}
