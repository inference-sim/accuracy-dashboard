"""A point's grade ceiling: the best grade its recorded data allows, and why (design §11.3; COV-4, COV-9).

A grade says how close a point's comparison is today. The ceiling says how close it can ever be with the data
that exists for it, if every piece of BLIS work it needs were done: every field modelled, every coefficient
measured, every catalog entry added, the ported-function list published. So a reader can tell the two cases
apart:

  not yet       the grade is below the ceiling. What holds it there is BLIS work, named on the point.
  at ceiling    the grade is the ceiling. Only new data (another run, a record that was lost, a corrected
                source) can raise it.

The ceiling is computed from the point's own record (its contract entry) and from evidence about the engine,
never from a table of settings. Each limit names the grade it caps the point at, the fact of the data that
sets it, and the evidence:

  the build     a nightly or custom build is not a release: G1 to G3 need one (G4 at best). A release other
                than the one the simulator runs cannot be G1 or G2 (G3 at best); and when a function the
                engine ports changed between the two releases (ported_changes.py), not G3 either (G4). Where no
                such comparison exists (an engine whose port does not exist yet, as SGLang's), G3 is only an upper
                bound and the point says so (`ceiling_is_upper_bound`).
  the record    each G5 reason has one class, read from the baseline's issue file beside the issue it cites
                (class_of; CLASSES): BLIS work and a record the source still holds are "not yet"; a value an
                estimation rule can stand in for caps at G2; a record that is gone or two records that disagree cap
                at G5; a router BLIS does not host is decided by the router table (router_cap). A reason with no
                class is refused, never assumed. A G2 substitution that comes from the data rather than from BLIS (a
                cluster fact taken from a later record, a client whose flags or counts were not recorded, a value the
                run did not record, a router BLIS will never host) caps a scored point at G2.

Everything else that holds a point down (a field not modelled, a chip without coefficients, a coefficient that
is not measured, an unevaluated G1 condition, a refusal by the simulator) is BLIS work: it is listed as
`not_yet` and does not lower the ceiling. Where the data cannot decide between two caps (no ported-function
comparison, a router whose mode is not recorded) the ceiling is the better one, marked an upper bound.

A G5 or failed point's record lists its G5 reasons or faults, not the substitutions it would carry once
scored, so its ceiling is an upper bound: scoring it may name a data substitution that lowers it to G2.
"""
from __future__ import annotations

ORDER = ("G1", "G2", "G3", "G4", "G5")

# What a G5 reason means for the ceiling. One source decides it: the reason's entry in the baseline's issue file
# (docs/m3/baseline/issues.json, its "limit"), checked against the issue it cites. The codes below are BLIS work by
# design §11.4 itself ("cleared when the engine models the field", "a model-onboarding trigger", "add the engine"),
# so they need no entry; any other reason with no class is refused, never assumed.
#   blis      BLIS work removes it: not yet, no cap.
#   source    the source holds the record and could serve it (the API refuses a large log): not yet, no cap.
#   estimate  a value the run did not record, which an estimation rule can stand in for: G2 at best.
#   data      the record is gone, was never kept, or two records disagree: G5 until the source changes.
#   router    a router BLIS does not host: decided by the router table (router_cap).
CLASSES = ("blis", "source", "estimate", "data", "router")
BLIS_BY_DESIGN = ("field_not_modelled", "field_unclassified", "field_not_in_release", "not_in_catalog",
                  "engine_unsupported", "code_not_visible")
# client_difference subjects that are facts of the record: the job log that held the client's flags expired, the
# run's request counts were not kept, the run's client or its build is not the one InferenceX pins. The others
# (send_gap, sent_prompt_lengths, client_saturation) are what BLIS does not yet model or verify.
DATA_CLIENT_SUBJECTS = ("client_flags", "failed_requests", "benchmark_client", "client_build")


class CeilingError(ValueError):
    """A reason has no class, or a class is not one of CLASSES."""


def reason_key(code: str, subject: str) -> str:
    return f"{code}:{subject}" if subject else code


def class_of(code: str, subject: str, classes: dict) -> str:
    if code in BLIS_BY_DESIGN:
        return "blis"
    c = classes.get(reason_key(code, subject)) or classes.get(code)
    if c is None:
        raise CeilingError(f"the G5 reason {reason_key(code, subject)!r} has no class: say in the issue file whether it "
                           f"is BLIS work, a value an estimate can cover, or a limit of the data")
    if c not in CLASSES:
        raise CeilingError(f"the class {c!r} of {reason_key(code, subject)!r} is not one of {CLASSES}")
    return c


def router_cap(subject: str, routers: list[dict]) -> dict:
    """A router BLIS does not host, by the router table (blis-substrate catalog/routers): G2 when the table maps the
    run's router and mode to an llm-d policy (the point then names the policy, router_differs), G5 when every entry of
    the router says no policy is close enough. A reason that does not name the mode, or a router the table has no
    entry for, is undecided between the two: G2 is then only an upper bound."""
    name, _, outcome = subject.partition(":")
    router = name.removesuffix("-router")
    mine = [r for r in routers if r.get("router") == router]
    mapped = [r for r in mine if r.get("policy") not in (None, "", "none")]
    if outcome == "no_policy" or (mine and not mapped):
        return {"cap": "G5", "code": f"router_unsupported:{subject}",
                "why": f"the router table maps no llm-d policy to {router}: BLIS hosts only llm-d's router"}
    why = (f"the router table maps {router} to an llm-d policy for {', '.join(sorted(r['mode'] for r in mapped))} "
           f"and to none for {', '.join(sorted(r['mode'] for r in mine if r not in mapped)) or 'no mode'}; the run's "
           f"mode is not recorded on the point" if mine else f"the router table has no entry for {router} yet")
    return {"cap": "G2", "code": f"router_unsupported:{subject}", "bound": True,
            "why": why + ": G2 (a named policy) at best, G5 if no policy is close enough"}


def worse(a: str, b: str) -> str:
    return a if ORDER.index(a) >= ORDER.index(b) else b


def build_limit(run_release: str | None, engine_version: str, changed: list[str] | None, engine: str = "vLLM") -> dict | None:
    """The cap the run's engine build sets; None for a run on the engine release the simulator runs."""
    if run_release is None:
        return {"cap": "G4", "code": "nightly_or_custom",
                "why": "the run used a nightly or custom build, not a release: G1 to G3 need a release"}
    if run_release == engine_version:
        return None
    if changed:
        return {"cap": "G4", "code": "changed_functions",
                "why": (f"the run used {engine} {run_release}; {len(changed)} function(s) the engine ports changed between "
                        f"{run_release} and {engine_version} (first: {sorted(changed)[0]}), so G3 cannot be reached, "
                        f"and G1 and G2 need a run on {engine_version}")}
    if changed is not None:
        return {"cap": "G3", "code": "other_release",
                "why": (f"the run used {engine} {run_release}, not {engine_version}: G1 and G2 need a run on "
                        f"{engine_version}; no function the engine's port cites changed between the two releases")}
    # No comparison exists (for SGLang, no port exists to compare): G3 is an upper bound, not a finding. Whether a
    # ported function changed, which would make it G4, is unknown until the port publishes what it ports.
    return {"cap": "G3", "code": "other_release_unknown", "bound": True,
            "why": (f"the run used {engine} {run_release}, not {engine_version}: G1 and G2 need a run on {engine_version}; "
                    f"G3 is an upper bound: no comparison of the ported functions of {run_release} and {engine_version} "
                    f"exists, so whether G3 or only G4 can be reached is unknown")}


def g5_limit(code: str, subject: str, classes: dict, routers: list[dict] = ()) -> dict | None:
    """The cap a G5 reason sets, by its class (class_of); None for BLIS work or a record the source still holds."""
    c = class_of(code, subject, classes)
    key = reason_key(code, subject)
    if c == "data":
        return {"cap": "G5", "code": key,
                "why": "a record of the run is gone or was never kept, or two records disagree: only the source removes it"}
    if c == "estimate":
        return {"cap": "G2", "code": key,
                "why": "a value the run did not record: an estimation rule can stand in for it, named on the point"}
    if c == "router":
        return router_cap(subject, list(routers))
    return None


def substitution_limit(s: dict, recorded: set[str]) -> dict | None:
    """The cap a G2 substitution sets when it comes from the data. `recorded`: the fields the run set (the
    point's args with a recorded value), so an estimation rule standing in for a setting the engine does not
    model (BLIS work) is told from one standing in for a value the run never recorded (data)."""
    kind, subject = s.get("kind"), s.get("subject", "")
    data = (kind in ("later_record", "router_differs")
            or (kind == "client_difference" and subject in DATA_CLIENT_SUBJECTS)
            or (kind == "estimated" and subject not in recorded))
    if not data:
        return None
    return {"cap": "G2", "code": f"{kind}:{subject}", "why": f"named on the point from the data: {s.get('detail') or kind}"}


def ceiling(point: dict, *, engine_version: str, ported: dict | None = None, classes: dict | None = None,
            routers: list[dict] = (), engine: str = "vLLM") -> dict:
    """The ceiling of one point of a contract (compare.Run's record: status, grade, run_release, g5_reasons,
    substitutions, args). Returns {"grade", "ceiling", "state", "limits", "not_yet"}: state is "at_ceiling" or
    "not_yet"; limits are the data's caps, worst first; not_yet the BLIS work between the grade and the ceiling
    (empty at the ceiling: work that does not change the grade, such as a coefficient below G4, is not listed)."""
    import ported_changes as pc
    status = point["status"]
    release = point.get("run_release")
    limits, not_yet = [], []
    b = build_limit(release, engine_version, pc.changed_functions(ported, release), engine)
    if b:
        limits.append(b)
    if status == "scored":
        recorded = {a.get("arg") for a in point.get("args") or [] if a.get("measured") is not None}
        for s in point.get("substitutions") or []:
            if s.get("kind") in ("other_release", "nightly_or_custom", "changed_functions", "ported_functions_unpublished"):
                continue
            lim = substitution_limit(s, recorded)
            if lim:
                limits.append(lim)
            else:
                not_yet.append(f"{s['kind']}:{s.get('subject', '')}")
    else:
        for code, subject in point.get("g5_reasons") or []:
            lim = g5_limit(code, subject, classes or {}, routers) if status == "not_scored" else None
            if lim:
                limits.append(lim)
            if not lim or lim["cap"] != "G5":
                not_yet.append(f"{code}:{subject}" if subject else code)
    cap = "G1"
    for lim in limits:
        cap = worse(cap, lim["cap"])
    grade = point["grade"] if point["grade"] in ORDER else "G5"
    seen, uniq = set(), []
    for lim in sorted(limits, key=lambda x: (-ORDER.index(x["cap"]), x["code"])):
        if lim["code"] not in seen:
            seen.add(lim["code"])
            uniq.append(lim)
    state = "at_ceiling" if grade == cap else "not_yet"
    at_cap = [lim for lim in uniq if lim["cap"] == cap]
    bound = bool(at_cap) and all(lim.get("bound") for lim in at_cap)
    return {"grade": point["grade"], "ceiling": cap, "state": state, "limits": uniq,
            "ceiling_is_upper_bound": bound,
            "not_yet": sorted(set(not_yet)) if state == "not_yet" else []}
