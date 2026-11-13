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


# ---- the engine owner's resolution cases (blis-vllm fields/stand_in_vectors.json, from vLLM's own functions), through the
# real estimations of the three fields (blis-vllm fields.json), by the port and by the consumer

REAL = os.environ.get("BLIS_VLLM_FIELDS")                     # blis-vllm's fields.json; else the committed copy of the three rows
ROWS = ({r["name"]: r for r in json.loads(Path(REAL).read_text())["fields"]} if REAL
        else {r["name"]: r for r in json.loads((HERE / "testdata" / "fields" / "stand_in_rows.json").read_text())})
OWNER_VECTORS = json.loads(Path(os.environ.get("BLIS_STAND_IN_VECTORS") or HERE / "testdata" / "stand_in_vectors.json").read_text())


def _facts(v):
    return {k: v[k] for k in ("value", "tp_group_nodes", "compute_capability") if v.get(k) not in (None, "")}


@pytest.mark.parametrize("v", OWNER_VECTORS, ids=[f"{v['field']}={v['value']!r} n={v.get('tp_group_nodes')} cc={v.get('compute_capability')}" for v in OWNER_VECTORS])
def test_the_port_answers_the_engine_owners_resolution_cases(v):
    assert fl.exact(ROWS[v["field"]]["estimation"], _facts(v)) is v["exact"]


@pytest.mark.parametrize("v", OWNER_VECTORS, ids=[f"{v['field']}={v['value']!r} n={v.get('tp_group_nodes')} cc={v.get('compute_capability')}" for v in OWNER_VECTORS])
def test_a_point_scores_through_the_generic_path_exactly_where_the_owner_says_the_stand_in_is_exact(v):
    name = v["field"]
    rows = sorted([ROWS[name], {"name": "tensor_parallel_size", "source": "config", "status": "modelled",
                                "evidence": {"traces": ["t.json"]}, "estimation": {"rule": "none"}}], key=lambda f: (f["name"], f["source"]))
    flist = fl.parse(json.dumps({"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.32.0"}, "fields": rows}))
    r = st.Reading()
    r.add(f"env.{name}", v["value"])
    nodes = v.get("tp_group_nodes")
    r.add("tensor_parallel_size", 8 * nodes if nodes else None)           # nodes of 8 GPUs
    c = st.decide(st.merge({"launch_config": r}, {}), flist, "p", sif.facts_of(8, v.get("compute_capability") or None))
    if v["exact"]:
        assert c.reasons == [] and [x["subject"] for x in c.substitutions] == [f"env.{name}"]
    else:
        assert c.reasons == [f"field_not_modelled:env.{name}"] and c.substitutions == []


@pytest.mark.skipif(not REAL, reason="BLIS_VLLM_FIELDS (blis-vllm's fields.json) is not set")
def test_the_engines_whole_field_list_parses_and_the_three_fields_state_when_their_stand_in_is_exact():
    flist = fl.parse(Path(REAL).read_bytes())
    for name in ("VLLM_FLASHINFER_ALLREDUCE_BACKEND", "UCX_RCACHE_MAX_UNRELEASED", "UCX_TLS"):
        assert "valid_when" in flist.lookup(f"env.{name}").estimation


# ---- the substrate's known-bad vectors (contracts/spec/fields exact_test.go TestEveryBadExactnessStatementIsRefused): each is refused,
# naming what the substrate names. A malformed clause must never parse, and so never count as vacuously exact.

_PRE = {"rule": "leave_unset", "preserves": "p"}
BAD = [
    ("unknown clause key", {**_PRE, "valid_when": [{"value_is": ["auto"]}]}, ["valid_when[0]", 'unknown key "value_is"']),
    ("unknown comparison operator", {**_PRE, "valid_when": [{"tp_group_nodes": {"ge": 1}}]},
     ["valid_when[0].tp_group_nodes", 'unknown key "ge"']),
    ("unknown key on the estimation", {**_PRE, "valid_if": []}, ["unknown key 'valid_if'"]),
    ("capability that is not major.minor", {**_PRE, "valid_when": [{"compute_capability": {"gte": "10"}}]},
     ["valid_when[0].compute_capability.gte", "<major>.<minor>"]),
    ("capability that is not a number", {**_PRE, "valid_when": [{"compute_capability": {"lt": "hopper"}}]}, ["compute_capability.lt"]),
    ("capability given as a number", {**_PRE, "valid_when": [{"compute_capability": {"gte": 10.0}}]}, ["gte"]),
    ("node count that is not a whole number", {**_PRE, "valid_when": [{"tp_group_nodes": {"eq": 1.5}}]}, ["eq"]),
    ("node count that is a boolean", {**_PRE, "valid_when": [{"tp_group_nodes": {"eq": True}}]}, ["eq"]),
    ("empty clause", {**_PRE, "valid_when": [{}]}, ["valid_when[0]", "at least one key"]),
    ("empty comparison", {**_PRE, "valid_when": [{"tp_group_nodes": {}}]}, ["valid_when[0].tp_group_nodes", "at least one of eq"]),
    ("empty valid_when", {**_PRE, "valid_when": []}, ["valid_when", "at least one clause"]),
    ("empty string list", {**_PRE, "valid_when": [{"value_in": []}]}, ["value_in", "at least one string"]),
    ("blank string in a list", {**_PRE, "valid_when": [{"value_in": ["auto", " "]}]}, ["value_in[1]"]),
    ("valid_when without preserves", {"rule": "leave_unset", "valid_when": [{"value_in": ["auto"]}]},
     ["estimation.preserves", "required with valid_when"]),
    ("valid_when on rule none", {"rule": "none", "valid_when": [{"value_in": ["auto"]}]}, ["estimation.valid_when", "only with rule"]),
    ("preserves on rule none", {"rule": "none", "preserves": "p"}, ["estimation.preserves", "only with rule"]),
    ("a clause whose keys are all null", {**_PRE, "valid_when": [{"value_in": None}]}, ["at least one key"]),
]


def _parse_est(est):
    row = {"name": "X", "source": "env", "status": "not_modelled", "evidence": {"issue": "o/r#1"}, "estimation": est}
    return fl.parse(json.dumps({"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.32.0"}, "fields": [row]}))


@pytest.mark.parametrize("name,est,want", BAD, ids=[b[0] for b in BAD])
def test_every_bad_exactness_statement_the_substrate_refuses_is_refused_here_too(name, est, want):
    with pytest.raises(fl.FieldsError) as e:
        _parse_est(est)
    for w in want:
        assert w in str(e.value), f"{w!r} not in {e.value}"


def test_a_null_valid_when_is_absent_as_in_the_substrates_decoder():
    est = _parse_est({"rule": "leave_unset", "preserves": "p", "valid_when": None}).fields["env.X"].estimation
    assert fl.exact(est, {"value": "anything"}) is True
