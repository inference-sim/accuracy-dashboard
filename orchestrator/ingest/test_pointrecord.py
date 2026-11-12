"""Every point record the harness writes loads with the substrate's own loader and passes its validator (SUB-19).

pointrecords.jsonl holds the substrate's PointRecord, one per scored or G5 point (pointrecord.py,
docs/pointrecord.md). The loader and validator are Go, in blis-substrate (contracts/spec/pointrecord,
contracts.LoadPointRecord semantics: strict decoding, then Record.Validate). This test builds
testdata/pointrecord_validate/main.go against a substrate checkout at layer 10 and runs it over

  * records assembled here from scored single-turn and agentic points and a G5 point (fake blis), and
  * the committed pointrecords.jsonl of the baseline and the preliminary after-run;

and checks that known-bad records are refused: a missing required field, a digest in place of
harness_commit, a wrong G2 kind, an unknown key.

BLIS_SUBSTRATE_LAYER10 names the checkout (layer 10, the commit that identifies the harness by its commit,
blis-substrate #45). The test is skipped, with that reason, when the variable, a Go toolchain or the checkout
is absent; CI sets it where it has them.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parent.parent

SUBSTRATE = os.environ.get("BLIS_SUBSTRATE_LAYER10")
SKIP = pytest.mark.skipif(
    not SUBSTRATE or not (Path(SUBSTRATE or "x") / "contracts" / "spec" / "pointrecord").is_dir() or not shutil.which("go"),
    reason="BLIS_SUBSTRATE_LAYER10 (a blis-substrate checkout at layer 10, blis-substrate #45) and a Go toolchain are needed")


@pytest.fixture(scope="module")
def validator(tmp_path_factory):
    d = tmp_path_factory.mktemp("prh")
    shutil.copy(HERE / "testdata" / "pointrecord_validate" / "main.go", d / "main.go")
    (d / "go.mod").write_text(f"module prh\n\ngo 1.23\n\nrequire github.com/inference-sim/blis-substrate v0.0.0\n"
                              f"replace github.com/inference-sim/blis-substrate => {Path(SUBSTRATE).resolve()}\n")
    env = {**os.environ, "GOFLAGS": "-mod=mod"}
    out = subprocess.run(["go", "build", "-o", str(d / "prh"), "."], cwd=d, env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return d / "prh"


def run(validator, path):
    p = subprocess.run([str(validator), str(path)], capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def assembled(tmp: Path) -> Path:
    """A contract of a scored single-turn point, a scored agentic point and a G5 point; its pointrecords.jsonl."""
    import score as sc
    import test_score_e2e as T
    entry, env = T._setup(tmp, repo="openai/gpt-oss-120b", isl=1024, osl=8192, date="2026-02-25", conc=4)
    outs = [sc._score_one(entry, tmp / "pull", tmp / "w1", env)]
    g5, env5 = T._setup(tmp, repo="openai/gpt-oss-120b", isl=1024, osl=8192, date="2026-02-25", conc=8)
    g5["row"]["metrics"]["router_name"] = "vllm-router"
    outs.append(sc._score_one(g5, tmp / "pull", tmp / "w2", env))
    ag, envA = T._agentic(tmp)
    ag_out = sc._score_one(ag, tmp / "pull", tmp / "w3", envA)
    assert ag_out.fidelity is not None, ag_out.reasons
    outs.append(ag_out)
    out = tmp / "contract"
    sc.write_contract(out, outs, {"ingest": "api", "blis": {}, "simulator": env.simulator(), "harness_commit": env.harness_commit,
                                  "experimental": False, "units": None, "engine": {"kind": "vllm", "version": "0.31.0"},
                                  "left_out_records": 0, "vllm_ref": "v0.31.0", "vllm_max_distance": 2000,
                                  "fields_sha256": "d" * 64, "pulled_at": "2026-10-23T00:00:00Z", "corpora": [],
                                  "pull_manifest_sha256": "e" * 64, "source": {"name": "t", "url": "https://example.invalid/"}})
    return out / "pointrecords.jsonl"


def test_a_record_is_assembled_for_every_scored_and_g5_point():
    tmp = Path(tempfile.mkdtemp())
    try:
        path = assembled(tmp)
        recs = [json.loads(l) for l in path.read_text().splitlines()]
        assert sorted(r["grade"] for r in recs) == ["G2", "G2", "G5"]
        scored = next(r for r in recs if r["grade"] != "G5")
        assert scored["harness_commit"] == "c" * 40 and "harness_digest" not in scored
        assert {f["metric"] for f in scored["figures"]} == {"tpot_mean_ms", "ttft_mean_ms"}
        assert all(f["predicted_basis"] == f["measured_basis"] == {"scope": "cluster"} for f in scored["figures"])
        assert scored["simulator"]["data"]["catalog"]["hash"] == "a" * 64 and "settings" in scored and "args" not in scored
        agentic = next(r for r in recs if r["identity"]["benchmark_type"] == "agentic_traces")
        assert agentic["replay"]["corpus_sha256"] and agentic["replay"]["client"] == "aiperf"
        g5 = next(r for r in recs if r["grade"] == "G5")
        assert g5["g5_reason"]["code"] == "router_unsupported" and "figures" not in g5
    finally:
        shutil.rmtree(tmp)


@SKIP
def test_the_assembled_records_load_and_validate_with_the_substrates_validator(validator):
    tmp = Path(tempfile.mkdtemp())
    try:
        code, out, err = run(validator, assembled(tmp))
        assert code == 0, err
        assert out.strip() == "3 records, 0 refused"
    finally:
        shutil.rmtree(tmp)


@SKIP
def test_known_bad_records_are_refused(validator, tmp_path):
    tmp = Path(tempfile.mkdtemp())
    try:
        good = [json.loads(l) for l in assembled(tmp).read_text().splitlines()]
    finally:
        shutil.rmtree(tmp)
    scored = next(r for r in good if r["grade"] != "G5")

    def refused(rec, *words):
        p = tmp_path / "bad.jsonl"
        p.write_text(json.dumps(rec) + "\n")
        code, out, err = run(validator, p)
        assert code == 1 and all(w in err for w in words), (words, err)

    r = json.loads(json.dumps(scored)); del r["build"]["image"]; r["build"]["image"] = ""
    refused(r, "build.image")
    r = json.loads(json.dumps(scored)); del r["identity"]["recipe"]
    refused(r, "identity.recipe")
    r = json.loads(json.dumps(scored)); r["harness_commit"] = "sha256:" + "d" * 64        # a digest, not a commit
    refused(r, "harness_commit", "digest")
    r = json.loads(json.dumps(scored)); r["harness_digest"] = r.pop("harness_commit")     # the old field name
    refused(r, "harness_digest")
    r = json.loads(json.dumps(scored))
    r["substitutions"] = [{"kind": "client_difference_not_a_kind", "subject": "x", "detail": "d"}]
    refused(r, "substitutions[0].kind")
    r = json.loads(json.dumps(scored)); r["args"] = []                                      # the dashboard's own name
    refused(r, "args")
    r = json.loads(json.dumps(scored)); r["figures"][0]["measured_basis"] = {"scope": "instance", "member": "i0"}
    refused(r, "measured_basis")


@SKIP
@pytest.mark.parametrize("run_dir", ["baseline-v0.16.0", "preliminary-after"])
def test_the_committed_runs_records_load_and_validate(validator, run_dir):
    contract = ROOT / "docs" / "m2" / run_dir / "contract"
    recs = (contract / "pointrecords.jsonl").read_text().splitlines()
    ns = sum(1 for _ in (contract / "not_scored.jsonl").read_text().splitlines())
    sc_ = sum(1 for _ in (contract / "fidelity.jsonl").read_text().splitlines())
    assert len(recs) == ns + sc_ > 0
    code, out, err = run(validator, contract / "pointrecords.jsonl")
    assert code == 0, err[:3000]
    assert out.strip() == f"{len(recs)} records, 0 refused"


@SKIP
def test_the_grade_must_agree_with_the_substitutions_as_the_substrates_validator_reads_them(validator, tmp_path):
    """The dashboard keeps no schema that ties a grade to its substitutions (SUB-19): the substrate's validator does."""
    recs = [json.loads(l) for l in (ROOT / "docs" / "m2" / "pd-writer-experiment" / "contract" / "pointrecords.jsonl").read_text().splitlines()]
    g4 = next(r for r in recs if r["grade"] == "G4")
    unchecked = [{"kind": "unevaluated", "subject": "kernel_hash"}]

    def verdict(rec):
        p = tmp_path / "r.jsonl"
        p.write_text(json.dumps(rec) + "\n")
        return run(validator, p)[0]
    assert verdict(g4) == 0
    assert verdict({**g4, "grade": "G1"}) == 1                                  # G1 names no substitution
    assert verdict({**g4, "substitutions": []}) == 1                            # G4 names the one that makes it so
    assert verdict({**g4, "grade": "G2"}) == 1                                  # a G4 floor is not G2
    assert verdict({**g4, "grade": "G2", "substitutions": unchecked}) == 0      # an unevaluated condition makes G2
    assert verdict({**g4, "grade": "G1", "substitutions": unchecked}) == 1      # and not G1


def test_point_record_problems_runs_the_substrates_command_on_every_record(tmp_path):
    import contract as c
    fake = tmp_path / "blis"
    fake.write_text('#!/bin/sh\n[ "$1 $2 $3" = "schema validate point-record" ] || exit 2\ngrep -q \'"grade": "G9"\' "$4" && { echo "grade: bad"; exit 1; }\nexit 0\n')
    fake.chmod(0o755)
    d = tmp_path / "run"
    d.mkdir()
    (d / c.POINTRECORDS_JSONL).write_text(c.canonical_dumps({"grade": "G2", "point_id": "a"}) + "\n" + c.canonical_dumps({"grade": "G9", "point_id": "b"}) + "\n")
    problems = c.point_record_problems(d, str(fake))
    assert len(problems) == 1 and "pointrecords.jsonl:2" in problems[0] and "grade: bad" in problems[0]
