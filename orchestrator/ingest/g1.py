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

THE SHAPE READ HERE is the substrate's selected-entry report (contracts/spec/result, ClosenessVersion 2;
version 1 is still read for the range). doc["selected_entries"] carries `closeness_version` when at
least one coefficient was recorded and every one was recorded whole: that says the recorder passed on
everything each entry states, not that a condition was decided. Per coefficient:

  "kernel_impls": [{library, variant, code_hash}]   the kernels the entry is valid for (not the kernels priced)
  "primitive":    the lowered primitive the name prices, empty for a name that prices no kernel   (version 2)
  "priced":       [{library, variant, code_hash}]   the kernels BLIS priced with it                (version 2)
  "kernel_match": "exact" or "unkeyed"                                                              (version 2)
  "fit_range":   [{dim, low, high}]                 the fit's input range
  "ci95":        {...}                              the entry's 95 percent interval
  "extrapolated": true, "unidentified": true        written only when true

Extrapolated is evaluated only for a coefficient that states a fit_range, unidentified only for one
that states a ci95, and the kernel hash only for an exact entry, against `priced`. Where the entry
states none of it, a false (an omitted flag) is "not evaluated". So a flag counts as evaluated only
when the entry states what it needs, and most registry-measured coefficients leave their
conditions unevaluated. A flag that is true is evidence whatever else is missing.

doc["resolutions"] is a list of {setting, pool, host, engine, reason}, all values strings, `host`
absent when the host gave none, `pool` the pool role (colocated, prefill, decode, or decode-0,
decode-1 when several share a role). A field of the field list may carry `value_classes`
(fields._value_classes).

The substrate holds no map from a library version to a kernel hash and the dashboard has none
(blis-registry#73 asks for the engine to publish one). kernel_hash is evaluated only when the
caller passes such a map, `version_hashes`, and the run's `libraries`; the scorer passes neither, so
the condition stays unevaluated on every point until a published source exists.
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


# The substrate emits closeness_version 2 (result.ClosenessVersion). Version 1 reports are still read
# for the range condition, which they carry whole; they carry no priced implementation, so the kernel
# hash is not decided from them.
CLOSENESS_VERSIONS = (1, 2)
PRICED_VERSION = 2


def _version(doc):
    return ((doc or {}).get("selected_entries") or {}).get("closeness_version")


def _whole(doc) -> bool:
    """Whether the report says every coefficient was recorded whole (closeness_version 1 or 2)."""
    return _version(doc) in CLOSENESS_VERSIONS


def coefficient_range(doc) -> Evaluation:
    kind = "coefficient_range"
    cs = _coefficients(doc)
    if cs is None:
        return _unevaluated(kind, "the Result has no selected-entry report")
    if not _whole(doc):
        return _unevaluated(kind, "the report carries no closeness_version: it does not say whether a coefficient "
                                  "was extrapolated or unidentified")
    subs, undecided = [], []
    for c in cs:
        flags = [w for w, need in (("extrapolated", "fit_range"), ("unidentified", "ci95")) if c.get(w) is True]
        if flags:
            rng = "; fit range " + ", ".join(f"{b['dim']} {b['low']} to {b['high']}" for b in c.get("fit_range") or [])
            subs.append({"kind": kind, "subject": f"{c['set']}/{c['name']}",
                         "detail": " and ".join(flags) + (rng if c.get("fit_range") else "")})
        if not c.get("fit_range") or not c.get("ci95"):
            undecided.append(f"{c['set']}/{c['name']}")
    if subs:
        return Evaluation(kind, True, sorted(subs, key=lambda s: s["subject"]))     # known to be false
    if undecided:
        return _unevaluated(kind, f"{len(undecided)} coefficient(s) state no fit range or no interval, so "
                                  f"extrapolated or unidentified is not evaluated for them (first: {undecided[0]})")
    return Evaluation(kind, True, [])


def kernel_hash(doc, libraries: dict | None, version_hashes: dict | None = None) -> Evaluation:
    """Each library version the run recorded maps to the kernel hash BLIS priced (design 11.3, G1).

    The hash BLIS priced is a coefficient's `priced` list, not its `kernel_impls`: the latter is every
    build the entry is valid for, which can name a sibling the run did not run (result.go,
    SelectedCoefficient.Priced). The condition is decided only for an entry whose `kernel_match` is
    exact. An unkeyed entry that prices a kernel (it has a `primitive`) applies to every build without
    having been shown to match the one that ran, so it leaves the condition unevaluated; an unkeyed
    entry that prices no kernel (host overheads, memory sizes) has no hash to compare and is passed over.

    libraries: library -> the version the run recorded. version_hashes: library -> {version ->
    {variant -> kernel code hash}}, from a source that publishes the hash of each library release
    (none exists yet; blis-registry#73). A library holds one hash per variant, so a version is keyed
    by variant as well; the hash covers the target architecture (design 6.2)."""
    kind = "kernel_hash"
    cs = _coefficients(doc)
    if cs is None:
        return _unevaluated(kind, "the Result has no selected-entry report")
    if _version(doc) != PRICED_VERSION:
        return _unevaluated(kind, "the report carries no closeness_version 2: it does not say which kernels were priced")
    priced: dict = {}       # (library, variant) -> the code hashes BLIS priced
    undecided = []
    for c in cs:
        who = f"{c.get('set')}/{c.get('name')}"
        match = c.get("kernel_match")
        if match == "exact":
            if not c.get("priced"):
                undecided.append(f"{who} is exact but names no priced implementation")
            for k in c.get("priced") or []:
                priced.setdefault((k["library"], k["variant"]), set()).add(k["code_hash"])
        elif match == "unkeyed":
            if c.get("primitive"):
                undecided.append(f"{who} prices {c['primitive']} but states no kernel implementation, so nothing shows "
                                 f"it was measured on the kernel that ran")
        else:
            undecided.append(f"{who} states no kernel_match")
    subs = []
    for (lib, variant), hashes in sorted(priced.items()):
        version = (libraries or {}).get(lib)
        if version is None:
            undecided.append(f"the run records no version of {lib}")
            continue
        by_version = (version_hashes or {}).get(lib)
        if by_version is None:
            undecided.append(f"no source maps a version of {lib} to a kernel hash")
            continue
        have = (by_version.get(version) or {}).get(variant)
        if have not in hashes:
            detail = (f"{lib} {version} ({variant}) has kernel hash {have}" if have
                      else f"{lib} {version} ({variant}) maps to no kernel hash") + f", BLIS priced {', '.join(sorted(hashes))}"
            subs.append({"kind": kind, "subject": lib, "detail": detail})
    if subs:
        return Evaluation(kind, True, subs)         # known to be false
    if not priced and not undecided:
        undecided.append("no coefficient names a kernel implementation it priced")
    if undecided:
        return _unevaluated(kind, undecided[0] + (f" (and {len(undecided) - 1} more)" if len(undecided) > 1 else ""))
    return Evaluation(kind, True, [])


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
    if requested is None:
        return _unevaluated(kind, "the run's set settings were not supplied")
    subs = []
    for path, value in sorted(requested.items()):
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
        if r.get("tensor_parallel_size") == 1:
            return None         # no tensor-parallel all-reduce group exists at width 1, so there is nothing to resolve
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
    compared = 0
    for r in rs:
        pool = r.get("pool") or "colocated"
        values = resolved if pool == "colocated" else (resolved_by_pool or {}).get(pool)
        if values is None:
            continue
        have = run_value(r.get("setting"), values)
        if have is not None:
            compared += 1
        if have is not None and not _same(have, r.get("engine")):
            where = "" if pool == "colocated" else f" in the {pool} pool"
            subs.append({"kind": kind, "subject": r["setting"] if pool == "colocated" else f"{r['setting']} ({pool})",
                         "detail": f"the run resolved {have!r}{where}, the engine resolves {r.get('engine')!r}"})
    if not compared:
        # A condition the data cannot decide is never assumed to hold (design 11.3).
        return _unevaluated(kind, "the run's log resolves none of the settings the Result records")
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
