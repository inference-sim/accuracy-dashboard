"""A prefill/decode SGLang point (dashboard#110, the part after the aggregated path): its recipe's `roles` hold each pool's
flags, each pool's fields are decided by the SGLang field list, and the role and transfer backend are the deployment's.

Run: python3 -m pytest orchestrator/ingest/test_sglang_pd.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fields as fl  # noqa: E402
import pd_recipe as pdr  # noqa: E402
import score as sc  # noqa: E402
import sglang_settings as ss  # noqa: E402
import test_pd as tpd  # noqa: E402
import test_score_e2e as e2e  # noqa: E402
import test_sglang_scoring as tsg  # noqa: E402

RECIPE2 = """\
schema: 2
name: t
model: {path: m, container: lmsysorg/sglang:v0.5.23-cu130, precision: fp8}
resources: {gpu_type: mi355x, gpus_per_node: 8, fabric: ib-400g}
engine: sglang
frontend: {type: dynamo}
roles:
  prefill:
    nodes: 1
    workers: 1
    gpus: 1
    env: {SGLANG_FOO: "1"}
    args: {tensor-parallel-size: 1, disaggregation-mode: prefill, disaggregation-transfer-backend: nixl, mem-fraction-static: 0.8}
  decode:
    nodes: 1
    workers: 2
    args: {tensor-parallel-size: 4, disaggregation-mode: decode, disaggregation-transfer-backend: nixl, mem-fraction-static: 0.8}
benchmark: {type: sa-bench, isl: 1024, osl: 1024, concurrencies: "4x8"}
"""


def test_a_schema_2_recipe_is_parsed_per_pool_with_a_workers_gpus_stated_or_from_its_nodes():
    r = pdr.parse(RECIPE2)
    p, d = r.pools["prefill"], r.pools["decode"]
    assert (p.workers, p.gpus, p.nodes) == (1, 1, 1)
    assert (d.workers, d.gpus) == (2, 4)                       # no `gpus`: the node's 8 GPUs over its 2 workers
    assert d.flags["tensor-parallel-size"] == 4 and p.env == {"SGLANG_FOO": "1"}
    assert r.engine == "sglang" and r.gpus_per_node == 8 and r.fabric == "ib-400g"


def _fields(transfer_status):
    f = [tsg._field(n, "modelled") for n in ("model_path", "tp_size", "mem_fraction_static", "page_size", "pp_size", "dp_size",
                                              "context_length")]
    f += [tsg._field(n, transfer_status) for n in ss.TRANSFER_FIELDS]
    f += [tsg._field("SGLANG_FOO", "proven_inert", source="env")]
    return fl.parse(json.dumps({"kind": "FieldList", "engine": {"kind": "sglang", "version": tsg.RELEASE},
                                "fields": sorted(f, key=lambda x: (x["name"], x["source"]))}).encode())


def _point(tmp, transfer_status, recipe=RECIPE2):
    entry, env = tpd._pd_point(tmp, log=False, recipe_text=recipe, row={"framework": "dynamo-sglang", "image": tsg.IMAGE})
    entry_doc = json.loads(json.dumps(tpd.TABLE_ENTRY))
    for ratio in entry_doc["bound"]["ratios"]:
        ratio["regime"]["engine_version"] = tsg.RELEASE        # the router bound's regime is the engine release it was measured on
        ratio["regime"]["decode"] = {**ratio["regime"]["decode"], "expert_parallel": False}     # this recipe sets no expert parallelism
    (tmp / "routers" / "dynamo-round-robin.yaml").write_text(yaml.safe_dump(entry_doc))
    env.sglang = sc.EngineKit("sglang", tsg.RELEASE, _fields(transfer_status), "f" * 64, ss.load_declarations())
    return entry, env


def test_a_prefill_decode_sglang_point_is_refused_by_the_transfer_field_the_list_does_not_model():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _point(tmp, "not_modelled")
        o, _ = e2e._score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is None
        assert {"code": "field_not_modelled", "subject": "disaggregation_mode"} in o.g5_reasons
        assert not any(r["code"] == "topology_unsupported" for r in o.g5_reasons)
    finally:
        shutil.rmtree(tmp)


def test_a_prefill_decode_sglang_point_whose_fields_are_accepted_is_written_as_two_sglang_pools_with_the_backend():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _point(tmp, "proven_inert")
        o, work = e2e._score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        docs = list(yaml.safe_load_all(next((work / "single_turn" / entry["point_id"]).glob("p-*.yaml")).read_text()))
        scen = next(d for d in docs if d["kind"] == "Scenario")
        dep = next(d for d in docs if d["kind"] == "Deployment")
        assert scen["engine"] == {"kind": "sglang", "version": tsg.RELEASE}
        assert [p["role"] for p in dep["pools"]] == ["prefill", "decode"]
        assert [p["parallel"]["tp"] for p in dep["pools"]] == [1, 4]
        assert dep["pd_transfer"] == {"connector": "nixl"}
    finally:
        shutil.rmtree(tmp)


def test_a_transfer_backend_the_recipe_leaves_unstated_is_the_engines_declared_default_and_named_on_the_point():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _point(tmp, "proven_inert", recipe=RECIPE2.replace(" disaggregation-transfer-backend: nixl,", ""))
        o, work = e2e._score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        default = ss.load_declarations()["fields"]["disaggregation_transfer_backend"]["default"]
        dep = next(d for d in yaml.safe_load_all(next((work / "single_turn" / entry["point_id"]).glob("p-*.yaml")).read_text())
                   if d["kind"] == "Deployment")
        assert dep["pd_transfer"] == {"connector": default}
        subs = {s["subject"]: s for s in o.fidelity["substitutions"] if s["subject"].endswith("disaggregation_transfer_backend")}
        assert set(subs) == {"prefill.disaggregation_transfer_backend", "decode.disaggregation_transfer_backend"}
        assert all(s["kind"] == "estimated" and repr(default) in s["detail"] for s in subs.values())
    finally:
        shutil.rmtree(tmp)


def test_a_recipe_that_states_its_transfer_backend_is_given_no_such_substitution():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = _point(tmp, "proven_inert")
        o, _ = e2e._score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        assert not any(s["subject"].endswith("disaggregation_transfer_backend") for s in o.fidelity["substitutions"])
    finally:
        shutil.rmtree(tmp)
