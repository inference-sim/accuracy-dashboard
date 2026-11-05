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
    "conflict": "value_conflict",
    "required_setting_missing": "value_not_recorded",
    "server_log_missing": "value_not_recorded",
    "artifact_unmatched": "value_not_recorded",
    "client_scenario_not_replayable": "value_not_recorded",
    "router_unsupported": "router_unsupported",
    "topology_unsupported": "topology_unsupported",
    "engine_unsupported": "engine_unsupported",
    "code_not_visible": "code_not_visible",
    "build_unparseable": "build_unparseable",
    "field_not_in_release": "field_not_in_release",
    "field_not_modelled": "field_not_modelled",
    "field_unclassified": "field_unclassified",
    "value_not_recorded": "value_not_recorded",
    "value_conflict": "value_conflict",
}

# Reasons that are faults of the harness's run, not facts about the point: a run that holds
# one has not finished scoring and publishes nothing (COV-8). blis_refused is the simulator
# refusing a scenario the harness wrote from recorded values; it names an engine or substrate
# gap, and stays a run fault until the engine's fields.json classifies what it refused.
# setting_differs is the written scenario losing a value the run recorded (COV-3).
RUN_FAULTS = ("blis_refused", "setting_differs")

# Run faults that are limits of the runner, not of the harness or the data: a larger runner or a
# longer timeout scores the point. A run whose only faults are these may publish, listing each
# such point as failed (CONTRACT.md "Failed points"); any other fault stops the publish (COV-8).
RUNNER_LIMITS = ("blis_refused:insufficient_memory", "blis_refused:timeout")


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
