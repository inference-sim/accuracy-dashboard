"""Tests of the before/after comparison (compare.py): the guards, the figures, and the committed tables."""
import copy
import csv
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ingest"))
import compare as c  # noqa: E402

H1 = "1" * 40
H2 = "2" * 40
HEADER = ["scenario", "model", "gpu", "label", "concurrency", "meas_tpot_us", "pred_tpot_us", "meas_ttft_us",
          "pred_ttft_us", "grade", "point_id", "measured_date"]


def pid(n):
    return f"{n:064x}"


def make_run(tmp, name, scored, not_scored=(), failed=(), harness=H1, units="u" * 64, pull="p" * 64):
    """scored: (n, model, gpu, conc, grade, pred_scale); not_scored: (n, gpu, [(code, subject)])."""
    d = Path(tmp) / name
    d.mkdir(parents=True)
    rows, facets, fid = [], {}, []
    sim = {"build": name, "harness_commit": harness}
    for n, model, gpu, conc, grade, scale in scored:
        meas_t, meas_f = 10000.0 * (1 + conc / 10), 400000.0 * (1 + conc / 10)
        rows.append([f"{model}-{gpu}.yaml", model, gpu, "8k1k", conc, meas_t, meas_t * scale, meas_f, meas_f * scale,
                     grade, pid(n), "2026-11-01"])
        facets[pid(n)] = {"framework": "vllm", "gpu": gpu, "model": model, "precision": "fp8", "spec_method": None}
        fid.append({"point_id": pid(n), "grade": grade, "substitutions": [], "simulator": sim})
    with open(d / "points.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        w.writerows(rows)
    (d / "facets.json").write_text(json.dumps(facets))
    (d / "fidelity.jsonl").write_text("".join(json.dumps(r) + "\n" for r in fid))
    ns = []
    for n, gpu, rs in not_scored:
        ns.append({"point_id": pid(n), "grade": "G5", "hardware": gpu, "model": "m", "framework": "vllm",
                   "precision": "fp8", "g5_reasons": [{"code": a, "subject": b} for a, b in rs], "simulator": sim})
    (d / "not_scored.jsonl").write_text("".join(json.dumps(r) + "\n" for r in ns))
    (d / "failed.jsonl").write_text("".join(json.dumps({"point_id": pid(n), "identity": {"hardware": "h100", "model": "m",
                                            "framework": "vllm", "precision": "fp8"}, "faults": ["blis_refused:timeout"]}) + "\n" for n in failed))
    (d / "provenance.json").write_text(json.dumps({
        "points": len(scored) + len(ns) + len(failed), "harness_commit": harness, "simulator": sim,
        "units": {"sha256": units, "count": len(scored) + len(ns) + len(failed), "not_in_pull": []},
        "pull_manifest_sha256": pull, "fields_sha256": "f" * 64, "engine": {"kind": "vllm", "version": "0.32.0"},
        "blis": {"release": name}, "experimental": False}))
    return d


def sweep(n0, model, gpu, grade, scale, concs=(1, 2, 4, 8)):
    return [(n0 + i, model, gpu, k, grade, scale) for i, k in enumerate(concs)]


# before: 12 b200 points G2 (scale 1.2), 3 points blocked on a field, 4 on amd, 1 failed
BEFORE = sweep(0, "m1", "b200", "G2", 1.2) + sweep(10, "m1", "b200", "G2", 1.2) + sweep(20, "m1", "b200", "G2", 1.2)
NS_B = [(100 + i, "b200", [("field_not_modelled", "x")]) for i in range(3)] \
    + [(200 + i, "mi355x", [("not_in_catalog", "")]) for i in range(4)] \
    + [(300, "b200", [("field_not_modelled", "x"), ("value_not_recorded", "y")])]
# after: the same 12 now G2 at scale 1.1, 3 of the blocked scored, one point refused
AFTER = [(n, m, g, k, gd, 1.1) for n, m, g, k, gd, _ in BEFORE[:-1]] + sweep(100, "m2", "b200", "G2", 1.3, (1, 2, 4))
NS_A = NS_B[3:]


@pytest.fixture
def runs(tmp_path):
    b = make_run(tmp_path, "before", BEFORE, NS_B, failed=[999])
    a = make_run(tmp_path, "after", AFTER, NS_A, failed=[999, BEFORE[-1][0]])
    return b, a


def test_pair_reports_both_scored_apart_from_newly_scored(runs):
    t = c.pair_report(c.Run(runs[0]), c.Run(runs[1]), "in_sample")
    assert t["scored_in_both"]["points"] == 11
    assert t["newly_scored"]["points"] == 3 and t["newly_refused"]["points"] == 1
    bt, at = t["scored_in_both"]["before"]["ttft"]["mape"], t["scored_in_both"]["after"]["ttft"]["mape"]
    assert bt["n"] == 11 and bt["value"] == pytest.approx(20.0) and at["value"] == pytest.approx(10.0)
    # three newly scored points are under the schema minimum of ten: shown as too few points, never as a number
    assert t["newly_scored"]["after"]["ttft"]["mape"]["value"] == "too few points"
    assert [x["id"] for x in t["newly_refused"]["list"]] == [pid(BEFORE[-1][0])]
    assert t["newly_refused"]["list"][0]["after_reasons"] == ["blis_refused:timeout"]


def test_coverage_movement_counts_single_cause_and_scope(runs):
    t = c.pair_report(c.Run(runs[0]), c.Run(runs[1]), "in_sample")
    mv = t["reason_movement"]["in_scope"]["all_reasons"]
    assert mv["field_not_modelled:x"]["before"] == {"blocks": 4, "alone": 3}      # 300 has two reasons
    assert mv["field_not_modelled:x"]["after"] == {"blocks": 1, "alone": 0}
    assert mv["field_not_modelled:x"]["delta_blocks"] == -3 and mv["field_not_modelled:x"]["delta_alone"] == -3
    assert mv["blis_refused:timeout"]["delta_alone"] == 1
    # AMD is out of scope: counted on its own, in no in-scope blocker, and its reason code is unchanged
    assert t["before"]["coverage"]["out_of_scope"]["not_scored"] == 4
    assert t["before"]["coverage"]["out_of_scope_by_chip"] == {"mi355x": 4}
    assert "not_in_catalog" not in t["reason_movement"]["in_scope"]["all_reasons"]
    assert "not_in_catalog" in t["reason_movement"]["out_of_scope"]["all_reasons"]
    assert {r["blocker"] for r in t["unlock"]["before"]} == {"field_not_modelled:x", "value_not_recorded:y", "blis_refused:timeout",
                                                             "out of scope (AMD, TPU)"}


def test_grade_table_shares_and_too_few(runs):
    g = c.run_report(c.Run(runs[0]), "in_sample")["grades"]
    assert g["G2"]["points"] == 12 and g["G2"]["share_of_graded"] == 1.0
    assert g["G1"]["points"] == 0 and g["G1"]["accuracy"]["ttft"]["mape"]["value"] == "too few points"
    assert g["G5"]["points"] == 8 and g["failed"]["points"] == 1
    assert g["G5"]["share_of_all"] == "too few points"      # 8 points, under the schema minimum of 10


def test_markdown_names_the_label_and_the_lists(runs):
    t = c.pair_report(c.Run(runs[0]), c.Run(runs[1]), "in_sample")
    md = c.pair_markdown(t)
    assert "IN-SAMPLE" in md and "no point is held out" in md
    assert "## Newly scored points (3)" in md and "## Newly refused points (1)" in md


# ---- the guards: each one fails on the thing it guards, and passes when only the change differs

def refuse(tmp_path, **after_kw):
    b = make_run(tmp_path, "before", BEFORE, NS_B)
    a = make_run(tmp_path, "after", AFTER, NS_A, **after_kw)
    with pytest.raises(c.CompareError) as e:
        c.pair_report(c.Run(b), c.Run(a), "in_sample")
    return str(e.value)


def test_two_harness_commits_are_refused(tmp_path):
    assert "two harness commits" in refuse(tmp_path, harness=H2)


def test_two_unit_sets_are_refused(tmp_path):
    assert "two unit sets" in refuse(tmp_path, units="v" * 64)


def test_two_pull_sets_are_refused(tmp_path):
    assert "two pull sets" in refuse(tmp_path, pull="q" * 64)


def test_two_point_sets_are_refused(tmp_path):
    b = make_run(tmp_path, "before", BEFORE, NS_B)
    a = make_run(tmp_path, "after", AFTER, NS_A[:-1])      # one point missing, counts adjusted by make_run
    with pytest.raises(c.CompareError, match="two point sets"):
        c.pair_report(c.Run(b), c.Run(a), "in_sample")


def test_a_point_scored_by_another_harness_commit_is_refused(tmp_path):
    b = make_run(tmp_path, "before", BEFORE, NS_B)
    a = make_run(tmp_path, "after", AFTER, NS_A)
    f = a / "fidelity.jsonl"
    rows = [json.loads(x) for x in f.read_text().splitlines()]
    rows[0]["simulator"]["harness_commit"] = H2
    f.write_text("".join(json.dumps(r) + "\n" for r in rows))
    with pytest.raises(c.CompareError, match="not only"):
        c.pair_report(c.Run(b), c.Run(a), "in_sample")


def test_a_run_without_a_units_file_is_refused(tmp_path):
    b = make_run(tmp_path, "before", BEFORE, NS_B)
    p = json.loads((b / "provenance.json").read_text())
    p["units"] = None
    (b / "provenance.json").write_text(json.dumps(p))
    with pytest.raises(c.CompareError, match="no units file"):
        c.run_report(c.Run(b), "in_sample")


def test_held_out_is_never_compared_with_in_sample(runs):
    b, a = c.Run(runs[0]), c.Run(runs[1])
    with pytest.raises(c.CompareError, match="held-out figure is never compared with an in-sample one"):
        c.check_pair(b, a, "in_sample", "held_out")
    with pytest.raises(c.CompareError, match="sample"):
        c.run_report(b, "anchor")


# ---- tables already written

def test_check_table_rejects_a_mixed_table(runs):
    t = c.pair_report(c.Run(runs[0]), c.Run(runs[1]), "in_sample")
    assert c.check_table(t) == []
    for key, bad in (("harness_commit", H2), ("units_sha256", "x" * 64), ("pull_manifest_sha256", "y" * 64),
                     ("point_set_sha256", "z" * 64), ("sample", "held_out")):
        m = copy.deepcopy(t)
        m["after"]["identity"][key] = bad
        assert c.check_table(m), key
    m = copy.deepcopy(t)
    m["sample"] = "held_out"
    assert c.check_table(m)
    m = copy.deepcopy(t)
    del m["before"]["identity"]["harness_commit"]
    assert c.check_table(m)


def test_committed_tables():
    """Every comparison table committed under docs/m2 (and its baseline) obeys the rules above."""
    root = HERE.parent.parent / "docs" / "m2"
    tables = sorted(p for p in root.rglob("*.json") if p.name == "table.json" or p.name.startswith("pair")) if root.is_dir() else []
    bad = [f"{p}: {pr}" for p in tables for pr in c.check_table(json.loads(p.read_text()))]
    assert not bad, bad
    for p in tables:
        data = p.parent / "contract"
        if p.name == "table.json" and data.is_dir():
            stored = json.loads(p.read_text())
            fresh = c.run_report(c.Run(data), stored["sample"])
            assert json.loads(json.dumps(fresh)) == stored, f"{p} is not what compare.py makes of {data}"
            assert (p.parent / "table.md").read_text() == c.run_markdown(fresh), f"{p.parent}/table.md is stale"


def test_scope_is_amd_and_tpu_only():
    assert [c.scope(x) for x in ("mi300x", "mi325x", "mi355x", "tpuv7", "b200", "h100", "gb200")] == \
        ["out_of_scope"] * 4 + ["in_scope"] * 3
