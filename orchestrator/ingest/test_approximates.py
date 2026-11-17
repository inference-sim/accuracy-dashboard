"""estimation.approximates (blis-substrate contracts/spec/fields): a field with no exact stand-in priced, for named values and
parts, as another execution mode. The dashboard ports the substrate's validation and evaluator; a covered point names the
substitution execution_mode (design 11.3, "an execution mode is substituted", a G2 condition) and is never an exact stand-in."""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fields as fl  # noqa: E402
import grade  # noqa: E402
import settings as st  # noqa: E402
import stand_in_facts as sif  # noqa: E402

APPROX = {"rule": "none", "approximates": {
    "mode": {"kernel_config.linear_backend": "auto"},
    "evidence": "the auto kernel's measured ramp",
    "differs": "the selected kernel's own speed",
    "when": [{"value_in": ["flashinfer_cutlass"], "compute_capability": {"gte": "10.0", "lt": "11.0"}}]}}


def _list(est):
    row = {"name": "kernel_config.linear_backend", "source": "config", "status": "not_modelled",
           "evidence": {"issue": "o/r#80"}, "estimation": est}
    return fl.parse(json.dumps({"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.33.0"}, "fields": [row]}))


def _decide(value, capability):
    r = st.Reading()
    r.add("kernel_config.linear_backend", value)
    return st.decide(st.merge({"launch_config": r}, {}), _list(APPROX), "b200", sif.facts_of(8, capability))


@pytest.mark.parametrize("value,cap,covered", [
    ("flashinfer_cutlass", "10.0", True), ("flashinfer_cutlass", "10.3", True),
    ("flashinfer_cutlass", "9.0", False), ("marlin", "10.0", False), ("flashinfer_cutlass", None, False),
])
def test_a_covered_value_is_priced_as_the_mode_and_names_an_execution_mode_substituted(value, cap, covered):
    c = _decide(value, cap)
    if covered:
        assert c.reasons == []
        assert [x["kind"] for x in c.substitutions] == ["execution_mode"]
        assert c.substitutions[0]["subject"] == "kernel_config.linear_backend"
        assert "auto" in c.substitutions[0]["detail"] and "own speed" in c.substitutions[0]["detail"]
        assert "execution_mode" in grade.G2_KINDS
    else:
        assert c.reasons == ["field_not_modelled:kernel_config.linear_backend"] and c.substitutions == []


def test_an_approximation_is_never_an_exact_stand_in():
    for value, cap in (("flashinfer_cutlass", "10.0"), ("marlin", "9.0")):
        assert fl.exact(APPROX, {"value": value, "compute_capability": cap}) is False
    assert fl.approximate(APPROX, {"value": "flashinfer_cutlass", "compute_capability": "10.0"}) is not None


@pytest.mark.parametrize("edit", [
    lambda a: a.pop("mode"), lambda a: a.pop("evidence"), lambda a: a.pop("differs"),
    lambda a: a.update(when=[]), lambda a: a.update(extra=1),
])
def test_an_approximation_missing_a_part_is_refused(edit):
    est = json.loads(json.dumps(APPROX))
    edit(est["approximates"])
    with pytest.raises(fl.FieldsError):
        _list(est)


def test_an_approximation_beside_a_stand_in_rule_is_refused():
    est = json.loads(json.dumps(APPROX))
    est["rule"] = "leave_unset"
    with pytest.raises(fl.FieldsError):
        _list(est)


EAGER = {"rule": "none", "approximates": {
    "mode": {"enforce_eager": True}, "evidence": "no graph, per-kernel rates",
    "differs": "no torch.compile fusion runs", "when": [{"value_in": ["true"]}]}}


def test_enforce_eager_true_is_written_to_the_engine_and_names_the_substitution():
    row = {"name": "enforce_eager", "source": "config", "status": "not_modelled", "evidence": {"issue": "o/r#59"}, "estimation": EAGER}
    flist = fl.parse(json.dumps({"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.33.0"}, "fields": [row]}))
    r = st.Reading()
    r.add("enforce_eager", True)
    c = st.decide(st.merge({"launch_config": r}, {}), flist, "b200", sif.facts_of(8, "10.0"))
    assert c.reasons == []
    assert c.mapped["engine.enforce_eager"][1] is True
    assert [x["kind"] for x in c.substitutions] == ["execution_mode"]
