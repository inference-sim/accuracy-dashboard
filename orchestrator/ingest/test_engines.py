"""Every framework InferenceX reports has a place in engines.py, and each one that no BLIS
engine scores is G5 with the reasons that are true of it, without fetching an artifact
(design 11.4; COV-1, COV-5).

Run: python3 -m pytest orchestrator/ingest/test_engines.py
"""
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assess as asx  # noqa: E402
import engines  # noqa: E402
import grade as gr  # noqa: E402
import ledger as ldg  # noqa: E402
import ledger_fake  # noqa: E402
import pull as pl  # noqa: E402
import score as sc  # noqa: E402

LABELS = ["vllm", "llmd-vllm", "vllm-disagg", "dynamo-vllm", "sglang", "dynamo-sglang", "mori-sglang", "trt",
          "dynamo-trt", "atom", "atom-disagg", "mooncake-atom", "tilert"]


def _row(framework, router=None, **kw):
    return {"id": "1", "model": "m", "hardware": "gb200", "precision": "fp8", "framework": framework,
            "benchmark_type": "single_turn", "conc": 4, "isl": 1024, "osl": 1024, "disagg": True,
            "is_multinode": True, "date": "2026-10-01", "image": "x/y:1",
            "run_url": "https://github.com/o/r/actions/runs/1",
            "metrics": {"router_name": router} if router else {}, **kw}


def _freeze(tmp, row):
    lg = ldg.load(ledger_fake.write(tmp / "ledger", [row]))
    (point,) = pl.place([row], lg).points

    def boom(*a, **k):
        raise AssertionError("an artifact or the API was fetched")
    resolver = types.SimpleNamespace(resolve=boom)
    gh = types.SimpleNamespace(repo="o/r", list_cached=boom, download=boom)
    return pl.freeze_point(point, resolver=resolver, gh=gh, fetch=boom, out=tmp / "out")


def _score(tmp, entry):
    env = sc.Env(blis="/nonexistent", blis_release="v0.16.0", blis_commit="a" * 40, catalog=tmp, catalog_release="c",
                 registry=tmp, registry_release="r", kernel="k", corpus=None)
    o = sc.score_point(entry, tmp / "pull", tmp / "w", env)
    sc.grade_outcome(o, "0.32.0", {"build": "v0.16.0", "engine": {"kind": "vllm", "version": "0.32.0"},
                                   "harness_digest": "unreleased"})
    return o


def test_the_table_names_every_framework_the_api_lists():
    assert sorted(engines.FRAMEWORKS) == sorted(LABELS)
    assert {l for l in LABELS if engines.scored(engines.FRAMEWORKS[l])} == \
        {"vllm", "llmd-vllm", "vllm-disagg", "dynamo-vllm"}
    with pytest.raises(engines.EngineError):
        engines.lookup("brand-new-engine")
    assert engines.unknown_labels([{"framework": "vllm"}, {"framework": "x"}]) == ["x"]


@pytest.mark.parametrize("label, router, want", [
    ("sglang", None, [{"code": "field_unclassified", "subject": "sglang: no field list published"}]),
    ("dynamo-sglang", "dynamo-router", [{"code": "field_unclassified", "subject": "sglang: no field list published"},
                                        {"code": "router_unsupported", "subject": "dynamo-router"}]),
    ("mori-sglang", "sglang-router", [{"code": "field_unclassified", "subject": "sglang: no field list published"},
                                      {"code": "router_unsupported", "subject": "sglang-router"}]),
    ("trt", None, [{"code": "engine_unsupported", "subject": "trt"}]),
    ("dynamo-trt", None, [{"code": "engine_unsupported", "subject": "dynamo-trt"},
                          {"code": "router_unsupported", "subject": "dynamo-router"}]),
    ("atom", None, [{"code": "engine_unsupported", "subject": "atom"}]),
    ("atom-disagg", None, [{"code": "engine_unsupported", "subject": "atom-disagg"}]),
    ("mooncake-atom", None, [{"code": "engine_unsupported", "subject": "mooncake-atom"}]),
    ("tilert", "tilert-pd-router", [{"code": "engine_unsupported", "subject": "tilert"},
                                    {"code": "router_unsupported", "subject": "tilert-pd-router"}]),
])
def test_a_framework_no_blis_engine_scores_is_g5_without_a_fetch(tmp_path, label, router, want):
    entry = _freeze(tmp_path, _row(label, router))
    assert entry["files"] == {} and entry["build"] is None
    o = _score(tmp_path, entry)
    assert o.fidelity is None and o.faults == []
    assert o.g5_reasons == sorted(want, key=lambda r: (r["code"], r["subject"]))
    # g5_reason is the first by design 11.4's order: router_unsupported comes before engine_unsupported.
    assert o.g5 == min(want, key=lambda r: gr.G5_CODES.index(r["code"]))


def test_a_vllm_engine_label_is_fetched_and_scored_not_called_engine_unsupported(tmp_path):
    for label in ("llmd-vllm", "vllm-disagg", "dynamo-vllm"):
        assert engines.reasons(engines.FRAMEWORKS[label]) == []
    # The default router of the label is its own: dynamo-vllm is router_unsupported with no row router.
    row = _row("dynamo-vllm")
    entry = {"point_id": "p" * 64, "identity": {}, "row": row, "reasons": [], "files": {}, "build": None}
    o = sc.Outcome(point_id="p" * 64, identity={}, row=row)
    assert asx.router_reason(row, engines.FRAMEWORKS["dynamo-vllm"].router) == ["router_unsupported:dynamo-router"]
    assert asx.router_reason(_row("llmd-vllm", "llm-d-router"), engines.FRAMEWORKS["llmd-vllm"].router) == []
    assert not hasattr(asx, "engine_reason") and entry and o


def test_every_row_is_recorded_or_listed_unlisted(tmp_path):
    rows = [{**_row(l), "id": str(i + 1)} for i, l in enumerate(LABELS)]
    lg = ldg.load(ledger_fake.write(tmp_path / "l", rows[:-1]))
    placed = pl.place(rows, lg)
    pl.check_placed(rows, placed)
    assert len(placed.points) == len(LABELS) - 1 and [u["framework"] for u in placed.unlisted] == ["tilert"]
    placed.unlisted.pop()
    with pytest.raises(ValueError, match="COV-1"):
        pl.check_placed(rows, placed)


def test_every_unit_ends_scored_g5_or_failed():
    o = sc.Outcome(point_id="a" * 64, identity={}, row={})
    assert sc.check_all_scored([{"point_id": "a" * 64}], [o])[0].endswith("(COV-1)")
    o.g5 = {"code": "engine_unsupported"}
    assert sc.check_all_scored([{"point_id": "a" * 64}], [o]) == []
    assert "outcomes for 2 points" in sc.check_all_scored([{"point_id": "a" * 64}, {"point_id": "b" * 64}], [o])[0]


def _disagg_entry(tmp, args, framework="vllm-disagg", router=None, with_launch=True):
    import gzip
    import json
    row = _row(framework, router)
    entry = _freeze_with_log(tmp, row)
    pdir = tmp / "pull" / "points" / entry["point_id"]
    log = ("INFO non-default args: {'model': 'm', %s}\nINFO Initializing a V1 LLM engine (v0.32.0) with config: model='m'\n"
           % args)
    (pdir / "server_log.gz").write_bytes(gzip.compress(log.encode(), mtime=0))
    entry["files"] = {"server_log": {"path": "server_log.gz", "sha256": "0" * 64, "from": "api"}}
    return entry


def _freeze_with_log(tmp, row):
    lg = ldg.load(ledger_fake.write(tmp / "ledger", [row]))
    (point,) = pl.place([row], lg).points
    from contract import point_id
    pid = point.point_id
    (tmp / "pull" / "points" / pid).mkdir(parents=True)
    return {"point_id": pid, "identity": dict(point.unit.identity), "row": row, "reasons": [], "files": {},
            "records": ["1"], "measurements": [], "build": {"image": "x/y:1"}}


def _fields(*specs):
    import fields as fl
    import json
    rows = sorted(({"name": n, "source": "config", "status": st_, "evidence":
                    {"traces": ["t"]} if st_ == "modelled" else {"issue": "o/r#1"}, "estimation": {"rule": "none"}}
                   for n, st_ in specs), key=lambda f: f["name"])
    return fl.parse(json.dumps({"kind": "FieldList", "engine": {"kind": "vllm", "version": "0.32.0"}, "fields": rows}))


def test_a_disaggregated_runs_recorded_topology_fields_go_through_the_field_list(tmp_path):
    kv = "'kv_transfer_config': KVTransferConfig(kv_connector='NixlConnector', kv_role='kv_producer')"
    env = sc.Env(blis="/nonexistent", blis_release="v0.16.0", blis_commit="a" * 40, catalog=tmp_path,
                 catalog_release="c", registry=tmp_path, registry_release="r", kernel="k", corpus=None,
                 field_list=_fields(("kv_transfer_config.kv_role", "not_modelled"),
                                    ("kv_transfer_config.kv_connector", "modelled")))
    o = sc.score_point(_disagg_entry(tmp_path / "a", kv), tmp_path / "a" / "pull", tmp_path / "w", env)
    assert o.reasons == ["field_not_modelled:kv_transfer_config.kv_role"]
    # No topology field recorded at all: value_not_recorded for the field that would be needed.
    o = sc.score_point(_disagg_entry(tmp_path / "b", "'tensor_parallel_size': 8"), tmp_path / "b" / "pull",
                       tmp_path / "w", env)
    assert o.reasons == ["field_not_in_release:tensor_parallel_size",
                         "required_setting_missing:kv_transfer_config.kv_role"]
    o = sc.score_point(_disagg_entry(tmp_path / "d", "'max_num_seqs': 8"), tmp_path / "d" / "pull",
                       tmp_path / "w", env)
    assert o.reasons == ["required_setting_missing:kv_transfer_config.kv_role"]
    assert asx.g5_of(o.reasons[0]) == {"code": "value_not_recorded", "subject": "kv_transfer_config.kv_role"}


def test_a_disaggregated_run_whose_topology_is_all_modelled_is_a_run_fault_not_an_invented_reason(tmp_path):
    kv = "'kv_transfer_config': KVTransferConfig(kv_connector='NixlConnector', kv_role='kv_producer')"
    env = sc.Env(blis="/nonexistent", blis_release="v0.16.0", blis_commit="a" * 40, catalog=tmp_path,
                 catalog_release="c", registry=tmp_path, registry_release="r", kernel="k", corpus=None,
                 field_list=_fields(("kv_transfer_config.kv_role", "modelled"),
                                    ("kv_transfer_config.kv_connector", "modelled")))
    o = sc.score_point(_disagg_entry(tmp_path / "c", kv), tmp_path / "c" / "pull", tmp_path / "w", env)
    assert o.reasons == ["setting_differs:disaggregated_topology"]


def test_the_fabric_reason_is_gone():
    assert not hasattr(pl, "_row_reasons") and not hasattr(pl, "MULTI_NODE_FABRIC")
