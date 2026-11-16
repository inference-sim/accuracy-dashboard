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
                engine ports changed between the two releases (ported_changes.py), not G3 either (G4).
  the record    a value two records of one stage disagree on (value_conflict), a build no record names
                (build_unparseable), a record that is gone (the server log, the launch artifact, the recipe),
                a pool the row does not record: G5, until the source is corrected or the record found.
                A G2 substitution that comes from the data rather than from BLIS (a cluster fact taken from a
                later record, a client whose flags or counts were not recorded, a recipe standing in for the
                run's lost arguments, a value the run did not record, a router BLIS will never host) caps the
                point at G2.

Everything else that holds a point down (a field not modelled, a chip without coefficients, a coefficient that
is not measured, an unevaluated G1 condition, a refusal by the simulator) is BLIS work: it is listed as
`not_yet` and does not lower the ceiling.

A G5 or failed point's record lists its G5 reasons or faults, not the substitutions it would carry once
scored, so its ceiling is an upper bound: scoring it may name a data substitution that lowers it to G2.
"""
from __future__ import annotations

ORDER = ("G1", "G2", "G3", "G4", "G5")

# G5 reasons whose removal needs the source corrected (design §11.4: "a data issue, reported to the source").
DATA_G5_CODES = ("value_conflict", "build_unparseable")
# value_not_recorded subjects that mean a record of the run is gone or never existed, which only the record
# removes (docs/closeness-grades.md: "Removed only by the record"), as opposed to a single value an engine's
# estimation rule could cover (design §11.4: value_not_recorded "becomes G2 when an estimation rule covers it").
# The scorer's reason code (server_log_missing, artifact_unmatched, recipe_unresolved) becomes value_not_recorded and
# its qualifier the subject (assess.g5_of), so these are the qualifiers; a bare value_not_recorded is a server log
# missing with no qualifier (pull.py), and an api_<code> one a log the API answered with that HTTP status.
GONE_RECORD_SUBJECTS = ("", "no_recipe_fingerprint", "no_master_entry", "ambiguous", "not_in_tree", "unreadable",
                        "no_config_file", "run_commit_unreadable", "unreadable_artifact", "no_result", "several_results",
                        "no_run_url", "client_export", "agentic_export", "unreadable_agentic_export", "pull_error")
GONE_RECORD_PREFIXES = ("api_", "run_in_", "several_")
# topology_unsupported subjects the data, not BLIS, sets (grades.md: "Not removable: the row does not describe a
# prefill/decode run").
DATA_TOPOLOGY_SUBJECTS = ("pd_pool_not_recorded",)
# client_difference subjects that are facts of the record: the job log that held the client's flags expired, the
# run's request counts were not kept, the run's client or its build is not the one InferenceX pins. The others
# (send_gap, sent_prompt_lengths, client_saturation) are what BLIS does not yet model or verify.
DATA_CLIENT_SUBJECTS = ("client_flags", "failed_requests", "benchmark_client", "client_build")


def worse(a: str, b: str) -> str:
    return a if ORDER.index(a) >= ORDER.index(b) else b


def _subject_head(subject: str) -> str:
    return (subject or "").split(":", 1)[0]


def build_limit(run_release: str | None, engine_version: str, changed: list[str] | None) -> dict | None:
    """The cap the run's engine build sets; None for a run on the engine release the simulator runs."""
    if run_release is None:
        return {"cap": "G4", "code": "nightly_or_custom",
                "why": "the run used a nightly or custom build, not a release: G1 to G3 need a release"}
    if run_release == engine_version:
        return None
    if changed:
        return {"cap": "G4", "code": "changed_functions",
                "why": (f"the run used vLLM {run_release}; {len(changed)} function(s) the engine ports changed between "
                        f"{run_release} and {engine_version} (first: {sorted(changed)[0]}), so G3 cannot be reached, "
                        f"and G1 and G2 need a run on {engine_version}")}
    known = changed is not None
    return {"cap": "G3", "code": "other_release",
            "why": (f"the run used vLLM {run_release}, not {engine_version}: G1 and G2 need a run on {engine_version}; "
                    + ("no function the engine ports changed between the two releases" if known else
                       f"no comparison of the ported functions of {run_release} and {engine_version} is recorded"))}


def g5_limit(code: str, subject: str) -> dict | None:
    """The cap a G5 reason sets when the data, not BLIS, sets it."""
    if code in DATA_G5_CODES:
        return {"cap": "G5", "code": f"{code}:{subject}" if subject else code,
                "why": "two records of one stage disagree, or no record names the build: the source must be corrected"}
    if code == "value_not_recorded" and (_subject_head(subject) in GONE_RECORD_SUBJECTS
                                         or subject.startswith(GONE_RECORD_PREFIXES)):
        return {"cap": "G5", "code": f"{code}:{subject}" if subject else code,
                "why": "a record of the run (its server log, launch artifact or recipe) is gone or was never kept"}
    if code == "topology_unsupported" and subject in DATA_TOPOLOGY_SUBJECTS:
        return {"cap": "G5", "code": f"{code}:{subject}", "why": "the row records a pool with no workers or GPUs"}
    if code == "value_not_recorded":
        return {"cap": "G2", "code": f"{code}:{subject}" if subject else code,
                "why": "a value the run did not record: an estimation rule can stand in for it, named on the point"}
    if code == "router_unsupported":
        return {"cap": "G2", "code": f"{code}:{subject}",
                "why": "the run was behind a router BLIS does not host: at best a router-table policy stands in"}
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


def ceiling(point: dict, *, engine_version: str, ported: dict | None = None) -> dict:
    """The ceiling of one point of a contract (compare.Run's record: status, grade, run_release, g5_reasons,
    substitutions, args). Returns {"grade", "ceiling", "state", "limits", "not_yet"}: state is "at_ceiling" or
    "not_yet"; limits are the data's caps, worst first; not_yet the BLIS work between the grade and the ceiling
    (empty at the ceiling: work that does not change the grade, such as a coefficient below G4, is not listed)."""
    import ported_changes as pc
    status = point["status"]
    release = point.get("run_release")
    limits, not_yet = [], []
    b = build_limit(release, engine_version, pc.changed_functions(ported, release))
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
            lim = g5_limit(code, subject) if status == "not_scored" else None
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
    return {"grade": point["grade"], "ceiling": cap, "state": state, "limits": uniq,
            "not_yet": sorted(set(not_yet)) if state == "not_yet" else []}
