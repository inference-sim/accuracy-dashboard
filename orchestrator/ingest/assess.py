"""One point's grade inputs, from what the scorer found (design §11.2 to §11.4).

The scorer (score.py) reads every source a run records (settings.py: the launch configuration,
the logged passed arguments, the logged resolved configuration, the lines the engine prints
about values it chose, and the API row), builds the scenario, and runs the simulator. This
module turns what it found into the grade's inputs:

  State     a value any source records is copied. Two sources of the same stage that disagree
            (launch configuration against logged arguments) make the point G5 value_conflict.
  Decide    each setting the run set is looked up in the engine's fields.json (settings.decide,
            fields.decide).
  Estimate  a value the simulation needs that no source recorded takes the field's estimation
            rule (fields.estimate_missing), named on the point, or makes the point G5
            value_not_recorded.

The scorer's own refusal reasons are mapped onto design §11.4's closed list. A reason with no
place on that list is an error in the scorer, raised here, never published (COV-5).
"""
from __future__ import annotations

# The scorer's reasons, by code, and the §11.4 reason each is. A reason whose code is not here
# fails the run (COV-5). The qualifier after ":" becomes the G5 subject.
G5_FOR_REASON = {
    "model_not_in_catalog": "not_in_catalog",
    "hardware_no_coefficients": "not_in_catalog",
    "drafter_not_in_catalog": "not_in_catalog",
    # A repository several catalog entries claim, and nothing the run recorded picks one: the value that would
    # choose the entry is not recorded.
    "catalog_entry_ambiguous": "value_not_recorded",
    "conflict": "value_conflict",
    # The simulator refused the scenario with a message of its own (blis_refused:<what it said>): a named fact about the
    # point, not a fault of the run. Which blis_refused reasons are faults is FAULT_SLUGS below.
    "blis_refused": "blis_refused",
    "required_setting_missing": "value_not_recorded",
    "server_log_missing": "value_not_recorded",
    "recipe_unresolved": "value_not_recorded",
    "artifact_unmatched": "value_not_recorded",
    "client_scenario_not_replayable": "value_not_recorded",
    "router_unsupported": "router_unsupported",
    "topology_unsupported": "topology_unsupported",
    "engine_unsupported": "engine_unsupported",
    "code_not_visible": "code_not_visible",
    "build_unparseable": "build_unparseable",
    "measurement_contaminated": "measurement_contaminated",
    "field_not_in_release": "field_not_in_release",
    "field_not_modelled": "field_not_modelled",
    "field_unclassified": "field_unclassified",
    "value_not_recorded": "value_not_recorded",
    "value_conflict": "value_conflict",
}

# Reasons that are faults of the harness's run, not facts about the point: a run that holds
# one has not finished scoring and publishes nothing (COV-8).
#   setting_differs   the written scenario lost a value the run recorded (COV-3): a harness fault.
#   blis_crashed      the simulator exited without a fatal message of its own (a panic, a signal, no output): a crash.
#   blis_refused      the simulator refusing a scenario is NOT a fault when it says why: blis_refused:<what it said> is a
#                     named not-scored point (G5 blis_refused, design §11.4). Only the slugs in FAULT_SLUGS are faults.
RUN_FAULTS = ("blis_refused", "setting_differs", "blis_crashed")

# The blis_refused slugs that are faults of the run and not the simulator's own refusal: a limit of the runner (below), the
# extractor failing, and the harness finding the simulator's output malformed, incomplete or not the client's pattern
# (result.py's ResultError slugs and score.py's checks of the Result). A reason with any other slug is the simulator's
# refusal and is named.
FAULT_SLUGS = ("timeout", "insufficient_memory", "extractor_error", "run_failed", "result_invalid", "result_unreadable",
               "result_validate_failed", "result_schema_version", "metrics_incomplete", "figure_not_cluster_direct",
               "request_rows_missing", "requests_incomplete", "coefficient_method_unknown", "warmup_not_drained",
               "requests_not_the_points", "request_pattern_not_the_clients", "request_pattern")

# Run faults that are limits of the runner, not of the harness or the data: a larger runner or a
# longer timeout scores the point. A run whose only faults are these may publish, listing each
# such point as failed (CONTRACT.md "Failed points"); any other fault stops the publish (COV-8).
RUNNER_LIMITS = ("blis_refused:insufficient_memory", "blis_refused:timeout")

# The simulator refusals the nightly has met, by code (refusal_code). A refusal with another code still publishes, named, and
# the summary lists the code in new_refusal_codes so a person reads it; the night warns and does not stop.
KNOWN_REFUSAL_CODES = ("scenario", "the_Result_document", "Failed_to_load_trace")

# The share of a night's points that are simulator refusals no classifier turned into a named reason (value_refusal), above
# which the night warns (it still publishes). The most the nightly has met is 14 of 20,364 points (0.07 percent, the night of
# 2026-11-18, all Kimi-K2.5); the limit is 1 percent, about 14 times that, and the 5 percent fault limit of night_health
# (harness faults) is unchanged.
UNCLASSIFIED_WARN_SHARE = 0.01


def _split(reason: str) -> tuple[str, str]:
    code, _, subject = reason.partition(":")
    return code, subject


def is_named_refusal(reason: str) -> bool:
    """The simulator's own refusal, said in its own words: blis_refused with a slug that is not a fault of the run."""
    code, subject = _split(reason)
    if code != "blis_refused" or not subject:
        return False
    return not any(subject == f or subject.startswith(f + ":") for f in FAULT_SLUGS)


def refusal_code(subject: str) -> str:
    """A named refusal's code: its slug up to the first colon, cut to 40 characters, with digit runs written N, so the same
    refusal on another point or machine has the same code."""
    import re
    return re.sub(r"[0-9]+", "N", subject.partition(":")[0])[:40]


def is_run_fault(reason: str) -> bool:
    """A reason that makes the point a fault of the run (listed as failed; the night publishes only if every one is a
    runner limit): a run fault whose reason is not the simulator's named refusal."""
    return is_fault(reason) and not is_named_refusal(reason)


def is_fault(reason: str) -> bool:
    return reason.partition(":")[0] in RUN_FAULTS


class AssessError(ValueError):
    pass


def g5_of(reason: str) -> dict:
    code, _, subject = reason.partition(":")
    g = G5_FOR_REASON.get(code)
    if g is None:
        raise AssessError(f"the scorer's reason {reason!r} has no place on design §11.4's list (COV-5)")
    return {"code": g, "subject": subject} if subject else {"code": g}


def router_reason(row: dict, launch_router: str | None) -> list[str]:
    """A point measured behind a router BLIS does not host (design §11.4, X4): BLIS hosts only
    llm-d's router. The API row's router_name, or a launch configuration's frontend, names it."""
    name = (row.get("metrics") or {}).get("router_name") or launch_router
    if name and not str(name).startswith("llm-d"):
        return [f"router_unsupported:{name}"]
    return []
