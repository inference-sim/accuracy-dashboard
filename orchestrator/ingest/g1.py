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

THE SHAPE READ HERE is blis-substrate layer 10's (branch m2/10-router-table-and-closeness-record,
provisional until it is rebased). doc["selected_entries"] carries `closeness_version: 1` when every
coefficient was recorded whole; then each coefficient states its `kernel_impls` ([{library, variant,
code_hash}]) and `fit_range` ([{dim, low, high}]) or none, and an omitted `extrapolated` or
`unidentified` means false. Without the marker the report does not say, and the conditions that
read those data stay unevaluated. doc["resolutions"] is a list of {setting, pool, host, engine,
reason}, all values strings, `host` absent when the host gave none, `pool` the pool role
(colocated, prefill, decode, or decode-0, decode-1 when several share a role). A field of the field
list may carry `value_classes` (fields._value_classes).

The substrate holds no map from a library version to a kernel hash and the dashboard has none
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


CLOSENESS_VERSION = 1


def _whole(doc) -> bool:
    """Whether the report says every coefficient was recorded whole (closeness_version 1)."""
    return ((doc or {}).get("selected_entries") or {}).get("closeness_version") == CLOSENESS_VERSION


def coefficient_range(doc) -> Evaluation:
    kind = "coefficient_range"
    cs = _coefficients(doc)
    if cs is None:
        return _unevaluated(kind, "the Result has no selected-entry report")
    if not _whole(doc):
        return _unevaluated(kind, "the report carries no closeness_version: it does not say whether a coefficient "
                                  "was extrapolated or unidentified")
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
    if not _whole(doc):
        return _unevaluated(kind, "the report carries no closeness_version: it does not say which kernels were priced")
    priced: dict = {}
    for c in cs:
        impls = c.get("kernel_impls") or []
        if c.get("fit_range") and not impls:
            # A fitted coefficient is tied to a kernel; one that names none cannot be compared, and
            # skipping it would call the condition true for a coefficient nobody checked.
            return _unevaluated(kind, f"the fitted coefficient {c.get('set')}/{c.get('name')} names no kernel implementation")
        for k in impls:
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


def _bool_text(v):
    return None if v is None else str(bool(v)).lower()


def run_value(setting: str, resolved: dict):
    """The value the run's log resolved for a Result resolution setting, as the Result writes it, or
    None when the log states none or the setting has no single vLLM name. The settings and the
    vLLM setting each answers are the table of blis-substrate docs/contracts/reference/result.md
    (TEMPORARY copy, X7)."""
    r = resolved
    if setting == "tensor_parallel_width":
        return r.get("tensor_parallel_size")
    if setting == "data_parallel_width":
        return r.get("data_parallel_size")
    if setting == "expert_parallel_width":
        # derived: tensor, prefill-context and data-parallel width multiplied with
        # enable_expert_parallel on, else 1
        ep = r.get("enable_expert_parallel")
        if ep is None:
            return None
        if not ep:
            return 1
        tp, dp = r.get("tensor_parallel_size"), r.get("data_parallel_size")
        return None if tp is None or dp is None else tp * dp * (r.get("prefill_context_parallel_size") or 1)
    if setting == "all_reduce_backend":
        d = r.get("disable_custom_all_reduce")
        return None if d is None else ("nccl" if d else "custom")
    if setting == "async_scheduling":
        return _bool_text(r.get("async_scheduling"))
    if setting == "cascade_attention":
        d = r.get("disable_cascade_attn")
        return None if d is None else _bool_text(not d)
    if setting == "sequence_parallel_moe":
        return None         # no single vLLM name
    return r.get(setting)   # a declined request is recorded under the engine's own field name


def resolved_value(doc, resolved: dict | None, resolved_by_pool: dict | None = None) -> Evaluation:
    """resolved: vLLM setting -> the value the run's log resolved, for a colocated point.
    resolved_by_pool: pool -> that dict, for a disaggregated one. A resolution naming a pool the
    run gives no values for is not compared."""
    kind = "resolved_differs"
    rs = (doc or {}).get("resolutions")
    if not isinstance(rs, list) or not rs:
        return _unevaluated(kind, "the Result records no engine resolution")
    subs = []
    for r in rs:
        pool = r.get("pool") or "colocated"
        values = resolved if pool == "colocated" else (resolved_by_pool or {}).get(pool)
        if values is None:
            continue
        have = run_value(r.get("setting"), values)
        if have is not None and not _same(have, r.get("engine")):
            where = "" if pool == "colocated" else f" in the {pool} pool"
            subs.append({"kind": kind, "subject": r["setting"] if pool == "colocated" else f"{r['setting']} ({pool})",
                         "detail": f"the run resolved {have!r}{where}, the engine resolves {r.get('engine')!r}"})
    return Evaluation(kind, True, sorted(subs, key=lambda s: s["subject"]))


def evaluate(doc, *, field_list, requested=None, resolved=None, libraries=None,
             version_hashes=None, resolved_by_pool=None) -> list[Evaluation]:
    return [coefficient_range(doc), kernel_hash(doc, libraries, version_hashes), value_class(requested, field_list),
            resolved_value(doc, resolved, resolved_by_pool)]


def split(evals: list[Evaluation]) -> tuple[list[dict], list[str]]:
    """(the substitutions the evaluated conditions name, the kinds still unevaluated)."""
    subs = [s for e in evals if e.evaluated for s in e.subs]
    return subs, [e.kind for e in evals if not e.evaluated]


assert set(gr.UNCHECKED_KINDS) == {"coefficient_range", "kernel_hash", "value_class", "resolved_differs"}
