"""A prefill/decode point is written as a substrate point record, and loads with the substrate's validator.

The scored point carries `router_differs` with the router build, the entry's difference statements and its
bound (the substrate's layer 12 record); the G5 points carry the named reasons the substrate's closed list
holds (`topology_unsupported`, `value_not_recorded`, `value_conflict`, `router_unsupported`).

BLIS_SUBSTRATE_LAYER10 names a checkout at layer 10 (G5 records), BLIS_SUBSTRATE_ROUTER_BOUNDS one at layer 12
(a record with `router_differs`); each test is skipped, with the reason, when its variable, a Go toolchain or the
checkout is absent.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

import score as sc
import test_pd as P
import test_pointrecord as TP
from test_pointrecord import validator  # noqa: F401  (the fixture)

L12 = os.environ.get("BLIS_SUBSTRATE_ROUTER_BOUNDS")
SKIP12 = pytest.mark.skipif(
    not L12 or not (Path(L12 or "x") / "contracts" / "spec" / "routertable" / "bound.go").is_file() or not shutil.which("go"),
    reason="BLIS_SUBSTRATE_ROUTER_BOUNDS (a blis-substrate checkout at layer 12, the router table's bounds) and a Go toolchain are needed")


def _build_validator(substrate: str, tmp: Path) -> Path:
    shutil.copy(TP.HERE / "testdata" / "pointrecord_validate" / "main.go", tmp / "main.go")
    (tmp / "go.mod").write_text("module prh\n\ngo 1.23\n\nrequire github.com/inference-sim/blis-substrate v0.0.0\n"
                                f"replace github.com/inference-sim/blis-substrate => {Path(substrate).resolve()}\n")
    out = subprocess.run(["go", "build", "-o", str(tmp / "prh"), "."], cwd=tmp, env={**os.environ, "GOFLAGS": "-mod=mod"},
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return tmp / "prh"


@pytest.fixture(scope="module")
def validator12(tmp_path_factory):
    return _build_validator(L12, tmp_path_factory.mktemp("prh12"))


def pd_records(tmp: Path) -> list[dict]:
    """A scored prefill/decode point, and three G5 ones: a pool on DP attention, no recipe, a log that contradicts the recipe."""
    outs, env0 = [], None
    cases = [dict(), dict(row={"prefill_dp_attention": True, "num_prefill_gpu": 8, "prefill_tp": 8},
                          recipe_text=P.RECIPE.replace("gpus_per_prefill: 1", "gpus_per_prefill: 8")),
             dict(with_recipe=False, log=False), dict()]
    for i, kw in enumerate(cases):
        d = tmp / f"p{i}"
        d.mkdir()
        entry, env = P._pd_point(d, **({"log": False} if i != 3 else {}) | kw)
        entry["point_id"] = entry["point_id"]
        outs.append(sc._score_one(entry, d / "pull", d / "w", env))
        env0 = env0 or env
    assert [o.fidelity is not None for o in outs] == [True, False, False, False], [o.reasons for o in outs]
    out = tmp / "contract"
    sc.write_contract(out, outs, {"ingest": "api", "blis": {}, "simulator": env0.simulator(), "harness_commit": env0.harness_commit,
                                  "experimental": True, "units": None, "engine": {"kind": "vllm", "version": "0.31.0"},
                                  "left_out_records": 0, "vllm_ref": "v0.31.0", "vllm_max_distance": 2000,
                                  "fields_sha256": "d" * 64, "pulled_at": "2026-10-23T00:00:00Z", "corpora": [],
                                  "pull_manifest_sha256": "e" * 64, "source": {"name": "t", "url": "https://example.invalid/"}})
    return [json.loads(l) for l in (out / "pointrecords.jsonl").read_text().splitlines()]


def test_a_prefill_decode_point_is_a_disaggregated_record_with_the_router_substitution_whole():
    tmp = Path(tempfile.mkdtemp())
    try:
        recs = pd_records(tmp)
        scored = next(r for r in recs if r["grade"] != "G5")
        assert scored["facets"]["serving"] == "disaggregated"
        assert {"tp", "pp", "dp", "ep"} == set(scored["facets"]["parallelism"])
        rd = next(s for s in scored["substitutions"] if s["kind"] == "router_differs")
        assert rd["revision"] == P.REV and rd["policy"] == "round-robin" and rd["entry"] == "dynamo-round-robin"
        assert rd["difference"] == [{"aspect": "counter", "text": "counters differ"}] and rd["bound"]["ratios"]
        g5 = sorted((r["g5_reason"]["code"], r["g5_reason"].get("subject")) for r in recs if r["grade"] == "G5")
        assert ("topology_unsupported", "pd_pool_data_parallel") in g5
        assert any(c == "value_not_recorded" and s == "not_in_tree" for c, s in g5) or ("router_unsupported", "dynamo-router") in g5
        assert all(r["facets"]["serving"] == "disaggregated" for r in recs if r["grade"] == "G5")
    finally:
        shutil.rmtree(tmp)


@TP.SKIP
def test_the_g5_records_of_prefill_decode_points_load_with_the_substrates_validator(validator):
    tmp = Path(tempfile.mkdtemp())
    try:
        recs = pd_records(tmp)
        g5 = [r for r in recs if r["grade"] == "G5"]
        path = tmp / "g5.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in g5))
        code, out, err = TP.run(validator, path)
        assert code == 0, err
        assert out.strip() == f"{len(g5)} records, 0 refused" and len(g5) == 3
    finally:
        shutil.rmtree(tmp)


@SKIP12
def test_the_scored_record_with_the_router_substitution_loads_where_the_substrate_has_the_bounds(validator12):
    # Needs a substrate checkout with both the record's harness_commit (layer 10) and the router table's
    # difference and bound (layer 12): layer 12 stacked on layer 11. Skipped until one exists.
    tmp = Path(tempfile.mkdtemp())
    try:
        recs = pd_records(tmp)
        path = tmp / "all.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in recs))
        code, out, err = TP.run(validator12, path)
        assert code == 0, err
        assert out.strip() == f"{len(recs)} records, 0 refused", out
    finally:
        shutil.rmtree(tmp)
