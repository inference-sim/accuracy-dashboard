"""The serving stacks InferenceX reports, and what the harness can say about each (design §11.4).

InferenceX labels every row with a `framework`. This table is the one place that maps a label to

  engine    the engine kind the run executed, or None when no BLIS engine repository exists for it
  router    the router every deployment of the label runs behind by construction (Dynamo's
            frontend, TileRT's prefill-decode router), or None when the label does not fix
            one. A router the API row records (`metrics.router_name`) or the launch
            configuration names takes precedence (assess.router_reason).
  topology  "aggregated", "disaggregated", or "either" when the label covers both

The table is a fact about InferenceX's labels, not a classification of settings (design §11.1):
which fields an engine models still comes only from its fields.json.

Only the labels whose engine is "vllm" fetch artifacts and are scored. Every other label's
points are G5 without any fetch, each with every reason that is true of it (grade.G5_CODES
order decides which is the point's g5_reason):

  router_unsupported   the point ran behind a router BLIS does not host (llm-d's is the only
                       one), whatever its engine. The router is the row's, else the label's.
  field_unclassified   the engine has an engine repository that publishes no field list.
                       blis-sglang exists and is empty until M3, so "no BLIS engine repository
                       exists" is false for SGLang, and the only true reason is that the engine
                       has classified no field.
  engine_unsupported   no BLIS engine repository exists for the engine (TensorRT-LLM, ATOM,
                       TileRT, teacup, rubin-july, tokenspeed): engine = None.
"""
from __future__ import annotations

from dataclasses import dataclass

VLLM = "vllm"
SGLANG = "sglang"

# The one place the SGLang family's reason is written: design §11.4's field_unclassified also
# covers "the engine's repository publishes no field list yet". It goes when blis-sglang
# publishes a field list (M3).
SGLANG_FIELD_LIST_UNPUBLISHED = "field_unclassified:sglang: no field list published"

AGGREGATED, DISAGGREGATED, EITHER = "aggregated", "disaggregated", "either"


class EngineError(ValueError):
    """A framework label this table does not name."""


@dataclass(frozen=True)
class Framework:
    label: str
    engine: str | None
    router: str | None
    topology: str


def _f(label, engine, router, topology):
    return label, Framework(label, engine, router, topology)


FRAMEWORKS = dict([
    _f("vllm", VLLM, None, AGGREGATED),
    _f("llmd-vllm", VLLM, "llm-d-router", DISAGGREGATED),
    _f("vllm-disagg", VLLM, None, DISAGGREGATED),
    _f("dynamo-vllm", VLLM, "dynamo-router", EITHER),
    _f("sglang", SGLANG, None, AGGREGATED),
    _f("dynamo-sglang", SGLANG, "dynamo-router", EITHER),
    _f("mori-sglang", SGLANG, None, DISAGGREGATED),
    _f("trt", None, None, AGGREGATED),
    _f("dynamo-trt", None, "dynamo-router", EITHER),
    _f("atom", None, None, AGGREGATED),
    _f("atom-disagg", None, None, DISAGGREGATED),
    _f("mooncake-atom", None, None, DISAGGREGATED),
    _f("tilert", None, "tilert-pd-router", DISAGGREGATED),
    # Labels InferenceX added after the table was written. Each runs an engine BLIS has no repository
    # for, as far as the rows say (all aggregated): G5 engine_unsupported, so the pull names them
    # instead of stopping on them.
    _f("teacup", None, None, AGGREGATED),
    _f("rubin-july", None, None, AGGREGATED),
    _f("tokenspeed", None, None, AGGREGATED),
])


def lookup(label) -> Framework:
    fw = FRAMEWORKS.get(label)
    if fw is None:
        raise EngineError(f"framework {label!r} is not in engines.FRAMEWORKS: name its engine, router and topology")
    return fw


def unknown_labels(rows: list[dict]) -> list[str]:
    """The framework labels of `rows` the table does not name, sorted."""
    return sorted({str(r.get("framework")) for r in rows if r.get("framework") not in FRAMEWORKS})


def scored(fw: Framework) -> bool:
    """Whether the harness fetches this framework's artifacts and scores its points."""
    return fw.engine == VLLM


def reasons(fw: Framework) -> list[str]:
    """The reasons the label alone gives, in the scorer's `code:subject` form."""
    if fw.engine == VLLM:
        return []
    if fw.engine == SGLANG:
        return [SGLANG_FIELD_LIST_UNPUBLISHED]
    return [f"engine_unsupported:{fw.label}"]
