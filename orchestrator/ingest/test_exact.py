"""The dashboard's evaluator of an estimation's valid_when agrees with the substrate's (contracts/spec/fields Exact).

The vector file holds cases (an estimation, the facts, and what the Go evaluator answered). The committed file was produced by
running the cases through the Go evaluator at the substrate commit that defines it; BLIS_EXACT_VECTORS names another file of the
same shape (the engine owner's vectors from the resolution of vLLM's own functions). A divergence fails.
"""
import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fields as fl  # noqa: E402

VECTORS = Path(os.environ.get("BLIS_EXACT_VECTORS") or HERE / "testdata" / "exact-vectors.json")
CASES = json.loads(VECTORS.read_text())


def test_the_vectors_are_not_empty_and_hold_both_answers():
    assert {c["want"] for c in CASES} == {True, False}


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_the_port_answers_as_the_substrates_evaluator_did(case):
    facts = {k: v for k, v in case["facts"].items() if v not in (None, "")}
    assert fl.exact(case["estimation"], facts) is case["want"]


def test_a_field_list_states_valid_when_only_with_a_stand_in_and_a_clause():
    def parse(est):
        row = {"name": "X", "source": "env", "status": "not_modelled", "evidence": {"issue": "o/r#1"}, "estimation": est}
        return fl.parse(json.dumps({"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.32.0"}, "fields": [row]}))
    ok = {"rule": "leave_unset", "preserves": "p", "valid_when": [{"value_in": ["a"]}]}
    assert parse(ok).lookup("env.X") is not None or parse(ok)
    for bad in ({"rule": "none", "preserves": "p", "valid_when": [{"value_in": ["a"]}]},
                {"rule": "leave_unset", "valid_when": [{"value_in": ["a"]}]},
                {"rule": "leave_unset", "preserves": "p", "valid_when": []},
                {"rule": "leave_unset", "preserves": "p", "valid_when": [{}]},
                {"rule": "leave_unset", "preserves": "p", "valid_when": [{"nonsense": 1}]}):
        with pytest.raises(fl.FieldsError):
            parse(bad)


# ---- the consumer: settings.decide asks the evaluator, with the dashboard's facts, and holds no table of its own

import settings as st  # noqa: E402
import stand_in_facts as sif  # noqa: E402

FI = {"rule": "leave_unset", "preserves": "auto resolves to the stated backend",
      "valid_when": [{"value_in": ["auto"]},
                     {"value_in": ["mnnvl"], "tp_group_nodes": {"eq": 1}},
                     {"value_in": ["mnnvl"], "tp_group_nodes": {"gte": 2}, "compute_capability": {"gte": "10.0"}}]}


def _decide(value, tp, gpus_per_node, capability, name="SOME_NEW_VARIABLE"):
    row = {"name": name, "source": "env", "status": "not_modelled", "evidence": {"issue": "o/r#1"}, "estimation": FI}
    tp_row = {"name": "tensor_parallel_size", "source": "config", "status": "modelled", "evidence": {"traces": ["t.json"]},
              "estimation": {"rule": "none"}}
    flist = fl.parse(json.dumps({"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.32.0"},
                                 "fields": sorted([row, tp_row], key=lambda f: (f["name"], f["source"]))}))
    r = st.Reading()
    r.add(f"env.{name}", value)
    r.add("tensor_parallel_size", tp)
    return st.decide(st.merge({"launch_config": r}, {}), flist, "b300", sif.facts_of(gpus_per_node, capability))


@pytest.mark.parametrize("value,tp,gpn,cap,exact", [
    ("auto", 8, 8, "10.0", True), ("mnnvl", 8, 8, "9.0", True),            # one node: mnnvl is what auto picks
    ("mnnvl", 16, 8, "10.0", True), ("mnnvl", 16, 8, "9.0", False),        # two nodes: only from capability 10.0
    ("mnnvl", 16, 8, None, False),                                         # a capability the catalog does not state: false
    ("nccl", 8, 8, "10.0", False), ("mnnvl", 16, None, "10.0", False),     # a node size the dashboard cannot supply: false
])
def test_a_stand_in_is_used_only_where_the_engines_clauses_hold_for_the_points_facts(value, tp, gpn, cap, exact):
    c = _decide(value, tp, gpn, cap)
    if exact:
        assert c.reasons == [] and [x["kind"] for x in c.substitutions] == ["estimated"]
    else:
        assert c.reasons == ["field_not_modelled:env.SOME_NEW_VARIABLE"] and c.substitutions == []
