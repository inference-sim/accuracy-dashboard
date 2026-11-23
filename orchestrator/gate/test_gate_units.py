"""The gate's parts: the role rule, the pre-registration, the budget, the predictions loader, the statistics
and the pull-request rule. Every test uses fakepartition's invented ledger and seed.

Run: python3 -m pytest orchestrator/gate/test_gate_units.py
"""
import copy
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import budget  # noqa: E402
import fakepartition as fp  # noqa: E402
import partition  # noqa: E402
import predictions as pd_  # noqa: E402
import prereg as pr  # noqa: E402
import reduce as rd  # noqa: E402
import rule  # noqa: E402
import stats  # noqa: E402

REPO = HERE.parent.parent
SHA = "e" * 64


@pytest.fixture(scope="module")
def fake(tmp_path_factory):
    return fp.build(tmp_path_factory.mktemp("ledger"), legacy_every=7)


# ---- the role rule ----

def test_a_role_is_a_function_of_the_role_key_alone(fake):
    by_key = {}
    for u in fake.units:
        by_key.setdefault(u.role_key, set()).add((fake.assigned[u.unit_id].role, fake.assigned[u.unit_id].not_blind))
    assert all(len(v) == 1 for v in by_key.values())
    assert {a.role for a in fake.assigned.values()} == {"fit", "select", "validate", "held", "anchor"}


def test_a_unit_on_a_legacy_side_reads_the_draw_against_its_sides_cut_point(fake):
    sides = {}
    for u in fake.units:
        a = fake.assigned[u.unit_id]
        if a.not_blind:
            sides.setdefault(a.role, 0)
            sides[a.role] += 1
    assert set(sides) == {"held", "anchor"}                       # the fake's legacy units are all on the HELD side
    assert all(a.not_blind for u in fake.units if u.unit_id in fake.legacy for a in [fake.assigned[u.unit_id]])


def test_a_new_unit_of_a_legacy_role_key_takes_the_legacy_side(fake):
    legacy_keys = {u.role_key for u in fake.units if u.unit_id in fake.legacy}
    assert legacy_keys and all(fake.assigned[u.unit_id].not_blind for u in fake.units if u.role_key in legacy_keys)


def test_a_wrong_seed_is_refused_and_never_named():
    for bad in ("00" * 32, "ab" * 31, "zz", ""):
        with pytest.raises(partition.PartitionError) as e:
            partition.parse_seed(bad, fp.SEED_SHA)
        assert bad not in str(e.value) or bad == ""
    assert fp.SEED_HEX not in repr(fake_seed()) and "withheld" in repr(fake_seed())


def fake_seed():
    return partition.parse_seed(fp.SEED_HEX, fp.SEED_SHA)


def test_the_seed_is_read_from_the_environment_only(monkeypatch):
    monkeypatch.delenv("LEDGER_SEED", raising=False)
    with pytest.raises(partition.PartitionError, match="LEDGER_SEED is not set"):
        partition.seed_from_env("LEDGER_SEED", fp.SEED_SHA)
    with pytest.raises(partition.PartitionError):
        partition.seed_from_env("not a name", fp.SEED_SHA)
    monkeypatch.setenv("LEDGER_SEED", fp.SEED_HEX)
    assert partition.seed_from_env("LEDGER_SEED", fp.SEED_SHA).draw("x") == fake_seed().draw("x")


def test_a_tampered_unit_list_is_refused(tmp_path):
    f = fp.build(tmp_path, keys={"A": 3})
    import gzip
    lines = gzip.decompress((f.ledger / "units" / "inferencex.jsonl.gz").read_bytes()).decode().splitlines()
    u = json.loads(lines[0])
    u["role_key"] = "0" * 64
    lines[0] = json.dumps(u)
    (f.ledger / "units" / "inferencex.jsonl.gz").write_bytes(gzip.compress("\n".join(lines).encode()))
    with pytest.raises(partition.PartitionError, match="role_key"):
        partition.load_units(f.ledger)


@pytest.mark.skipif(not Path(os.environ.get("BLIS_LEDGER_DIR", "/nonexistent")).is_dir(), reason="no blis-substrate checkout (BLIS_LEDGER_DIR)")
def test_the_real_units_hash_as_the_ledger_says():
    d = Path(os.environ["BLIS_LEDGER_DIR"])
    assert partition.load_units(d) and partition.load_config(d).partition_version >= 1


# ---- the pre-registration ----

def good():
    return fp.prereg_doc(SHA)


def test_a_good_preregistration_validates():
    assert pr.validate(good()) == []


@pytest.mark.parametrize("edit", [
    {"kind": "Other"}, {"id": "Bad Id"}, {"partition_version": 0}, {"hypothesis": "short"}, {"target_lanes": []},
    {"target_lanes": [{"gpu": "h100"}]}, {"target_lanes": [{}]}, {"sources": ["othersource"]},
    {"criteria": []}, {"criteria": [{"criterion": "error", "margin": -1}, {"criterion": "distance", "margin": 0.1}]},
    {"criteria": [{"criterion": "error", "margin": 0.1}, {"criterion": "error", "margin": 0.1}]},
    {"criteria": [{"criterion": "error", "margin": 0.1}]}, {"criteria": [{"criterion": "distance", "margin": 0.1}]},
    {"criteria": [{"criterion": "error", "margin": 0.1}, {"criterion": "error", "margin": 0.1}, {"criterion": "distance", "margin": 0.1}]},
    {"criteria": [{"criterion": "other", "margin": 0.1}]}, {"metrics": []}, {"metrics": ["TPOT"]},
    {"substream": "x"}, {"measured_sha256": "abc"},
])
def test_a_malformed_preregistration_is_refused(edit):
    doc = good()
    doc.update(edit)
    assert pr.validate(doc)


def test_a_preregistration_with_a_missing_or_extra_field_is_refused():
    d = good()
    del d["metrics"]
    assert pr.validate(d)
    d = good()
    d["note"] = "x"
    assert pr.validate(d)


def test_the_file_name_is_the_id_and_the_digest_is_stable(tmp_path):
    p = tmp_path / "row-99-example.json"
    p.write_text(json.dumps(good()))
    assert pr.load(p)["id"] == "row-99-example"
    q = tmp_path / "other.json"
    q.write_text(json.dumps(good()))
    with pytest.raises(pr.PreRegistrationError, match="file name"):
        pr.load(q)
    assert pr.digest(good()) == pr.digest(json.loads(json.dumps(good(), sort_keys=True)))
    changed = good()
    changed["predicted_change"] += " (edited)"
    assert pr.digest(changed) != pr.digest(good())


# ---- the budget ----

def ledger(b=2, ceiling=0.05):
    return {"kind": "GateLedger", "margin_ceiling": {"error": ceiling, "distance": ceiling},
            "partitions": {"1": {"budget": b, "evaluations": []}}}


def test_the_committed_ledger_has_no_budget_and_the_gate_refuses_on_it():
    doc = budget.load(REPO / budget.PATH)
    assert doc["partitions"]["1"]["budget"] is None and doc["partitions"]["1"]["evaluations"] == []
    with pytest.raises(budget.Refused, match="no budget"):
        budget.check_may_evaluate(doc, good())


def test_the_gate_refuses_without_a_recorded_margin_ceiling():
    with pytest.raises(budget.Refused, match="no margin ceiling"):
        budget.check_may_evaluate(ledger(ceiling=None), good())
    d = good()
    d["criteria"][0]["margin"] = 0.2
    with pytest.raises(budget.Refused, match="above the registry"):
        budget.check_may_evaluate(ledger(), d)


def test_one_evaluation_per_preregistration_and_none_past_the_budget():
    led = ledger(2)
    assert budget.check_may_evaluate(led, good()) == 1
    led = budget.record(led, "row-99-example", pr.digest(good()), fp.BASE, fp.CAND, 5, 1, "pass")
    with pytest.raises(budget.Refused, match="already received"):
        budget.check_may_evaluate(led, good())
    other = good()
    other["id"] = "row-98-other"
    assert budget.check_may_evaluate(led, other) == 2
    led = budget.record(led, "row-98-other", pr.digest(other), fp.BASE, fp.CAND, 6, 1, "fail")
    third = good()
    third["id"] = "row-97-third"
    with pytest.raises(budget.Refused, match="2 of 2"):
        budget.check_may_evaluate(led, third)


def test_a_missing_partition_version_is_refused():
    d = good()
    d["partition_version"] = 2
    with pytest.raises(budget.Refused, match="no entry"):
        budget.check_may_evaluate(ledger(), d)


def test_record_does_not_change_its_input_and_the_ledger_validates():
    led = ledger()
    before = copy.deepcopy(led)
    new = budget.record(led, "row-99-example", SHA, fp.BASE, fp.CAND, 5, 1, "unjudged")
    assert led == before and budget.validate(new) == [] and budget.dumps(new).endswith("\n")


@pytest.mark.parametrize("edit", [
    lambda d: d["partitions"]["1"].update(budget=-1), lambda d: d["partitions"]["1"].update(budget=1.5),
    lambda d: d.update(extra=1), lambda d: d["margin_ceiling"].update(error=-1),
    lambda d: d["partitions"].update({"x": {"budget": 1, "evaluations": []}}),
])
def test_a_malformed_ledger_is_refused(edit):
    d = ledger()
    edit(d)
    assert budget.validate(d)


def test_a_ledger_with_more_evaluations_than_its_budget_is_refused():
    led = budget.record(ledger(2), "row-99-example", SHA, fp.BASE, fp.CAND, 5, 1, "pass")
    led["partitions"]["1"]["budget"] = 0
    assert any("budget of 0" in e for e in budget.validate(led))


# ---- the predictions ----

def pred_doc(units, candidate=fp.CAND, harness=fp.HARNESS, value=1.0):
    return {"kind": "Predictions", "candidate": candidate, "harness": harness,
            "predictions": [{"source": "inferencex", "unit_id": u, "values": {"tpot": value}} for u in units]}


def write(tmp_path, doc, name="p.json"):
    p = tmp_path / name
    p.write_text(json.dumps(doc))
    return p


UNITS = [hashlib.sha256(str(i).encode()).hexdigest() for i in range(3)]


def test_good_predictions_load(tmp_path):
    p = pd_.load(write(tmp_path, pred_doc(UNITS)), fp.CAND, set(UNITS))
    assert p.values[UNITS[0]] == {"tpot": 1.0} and p.harness == fp.HARNESS


def test_a_reason_stands_for_a_unit_with_no_prediction(tmp_path):
    d = pred_doc(UNITS)
    d["predictions"][0] = {"source": "inferencex", "unit_id": UNITS[0], "reason": "the run failed"}
    assert pd_.load(write(tmp_path, d), fp.CAND, set(UNITS)).values[UNITS[0]] == {}


@pytest.mark.parametrize("make", [
    lambda: pred_doc(UNITS, candidate="f" * 40), lambda: pred_doc(UNITS, candidate="short"),
    lambda: pred_doc(UNITS, harness="x"), lambda: pred_doc(UNITS[:2]), lambda: pred_doc(UNITS + ["9" * 64]),
    lambda: pred_doc(UNITS + [UNITS[0]]), lambda: {**pred_doc(UNITS), "kind": "Other"},
    lambda: {**pred_doc(UNITS), "extra": 1}, lambda: pred_doc(UNITS, value="1"), lambda: pred_doc(UNITS, value=True),
])
def test_bad_predictions_are_refused(tmp_path, make):
    with pytest.raises(pd_.PredictionsError):
        pd_.load(write(tmp_path, make()), fp.CAND, set(UNITS))


def test_nan_and_infinity_and_oversize_are_refused(tmp_path, monkeypatch):
    p = tmp_path / "n.json"
    for bad in ("NaN", "Infinity", "-Infinity"):
        p.write_text(json.dumps(pred_doc(UNITS)).replace("1.0", bad, 1))
        with pytest.raises(pd_.PredictionsError):
            pd_.load(p, fp.CAND, set(UNITS))
    monkeypatch.setattr(pd_, "MAX_BYTES", 10)
    with pytest.raises(pd_.PredictionsError, match="cap"):
        pd_.load(write(tmp_path, pred_doc(UNITS)), fp.CAND, set(UNITS))


def test_a_predictions_error_never_names_a_unit(tmp_path):
    with pytest.raises(pd_.PredictionsError) as e:
        pd_.load(write(tmp_path, pred_doc(UNITS[:2])), fp.CAND, set(UNITS))
    assert not any(u in str(e.value) for u in UNITS)


# ---- the statistics (VAL-6) ----

def rng(label="x"):
    return stats.rng_for("gate/test", label)


def test_a_regression_larger_than_the_margin_cannot_pass_a_guard_lane():
    r = np.random.default_rng(1)
    d = 0.06 + r.normal(0, 0.01, 60)                      # the candidate is 0.06 worse; the margin is 0.02
    a = stats.analyse(d, 0.02, rng())
    assert a["p"] > 0.5 and not stats.holm([a["p"]])[0]


def test_a_real_improvement_rejects_the_null_of_no_improvement():
    r = np.random.default_rng(2)
    d = -0.05 + r.normal(0, 0.02, 60)
    a = stats.analyse(d, 0.0, rng())
    assert a["upper_95"] < 0 and a["p"] < 0.05 and stats.holm([a["p"]])[0]
    strong = stats.analyse(-0.5 + r.normal(0, 0.01, 60), 0.0, rng("s"))
    assert strong["below_floor"] and strong["p"] == stats.P_FLOOR
    assert not stats.analyse(r.normal(0.1, 0.01, 60), 0.0, rng("w"))["below_floor"]


def test_a_small_noisy_sample_cannot_pass_on_a_wide_interval():
    r = np.random.default_rng(3)
    d = -0.02 + r.normal(0, 0.3, 10)
    a = stats.analyse(d, 0.0, rng())
    assert a["upper_95"] > 0 and a["p"] > 0.05


def test_the_unit_resampled_is_the_role_key_not_the_unit():
    """Five perfectly correlated units per key give an interval no narrower than one unit per key."""
    r = np.random.default_rng(4)
    keys = [f"k{i}" for i in range(30)]
    effect = {k: float(r.normal(-0.03, 0.05)) for k in keys}
    one = [{"unit_id": f"{k}-0", "role_key": k} for k in keys]
    five = [{"unit_id": f"{k}-{j}", "role_key": k} for k in keys for j in range(5)]
    def meas(us):
        return {u["unit_id"]: {"meas": {"m": 1.0}} for u in us}

    out = []
    for us in (one, five):
        d = rd._diffs(us, "m", {u["unit_id"]: {"m": 1.1 + effect[u["role_key"]]} for u in us},
                      {u["unit_id"]: {"m": 1.1} for u in us}, meas(us))
        out.append(stats.analyse(d, 0.0, rng("same")))
    assert len(rd._diffs(five, "m", {u["unit_id"]: {"m": 1.0} for u in five}, {u["unit_id"]: {"m": 1.0} for u in five}, meas(five))) == 30
    assert out[1]["upper_95"] == out[0]["upper_95"] and out[1]["p"] == out[0]["p"]


def test_p_values_are_reproducible_by_substream_and_differ_across_substreams():
    d = np.random.default_rng(5).normal(-0.01, 0.05, 40)
    a, b = stats.analyse(d, 0.0, rng("a")), stats.analyse(d, 0.0, rng("a"))
    assert a == b
    assert stats.analyse(d, 0.0, rng("b"))["upper_95"] != a["upper_95"]


def test_a_constant_difference_is_decided_without_a_bootstrap():
    assert stats.analyse(np.full(20, -0.1), 0.0, rng()) == {"difference": pytest.approx(-0.1), "upper_95": pytest.approx(-0.1), "p": stats.P_FLOOR, "below_floor": True}
    assert stats.analyse(np.full(20, 0.1), 0.0, rng())["p"] == 1.0


def test_holm_step_down():
    assert stats.holm([0.001, 0.04, 0.5]) == [True, False, False]
    assert stats.holm([0.01, 0.02, 0.03]) == [True, True, True]
    assert stats.holm([0.02, 0.02]) == [True, True] and stats.holm([0.03, 0.03]) == [False, False]
    assert stats.holm([]) == []


# ---- the pull-request rule ----

@pytest.fixture
def base_root(tmp_path):
    (tmp_path / "state" / "gate" / "preregistrations").mkdir(parents=True)
    (tmp_path / rule.PATHS).write_text((REPO / rule.PATHS).read_text())
    (tmp_path / pr.DIR / "row-99-example.json").write_text(json.dumps(good()))
    return tmp_path


CITE = "Gate: pre-registration row-99-example"
NOT = "Gate: not an accuracy change - documentation only"


@pytest.mark.parametrize("body,changes,ok", [
    (CITE, [("M", "harness/run.sh")], True),
    (NOT, [("M", "docs/README.md")], True),
    (NOT, [("M", "harness/run.sh")], False),                      # an accuracy path cannot claim to be no change
    (NOT, [("M", "orchestrator/ingest/score.py")], False),
    ("no statement", [("M", "docs/README.md")], False),
    (CITE + "\n" + NOT, [("M", "docs/README.md")], False),
    ("Gate: pre-registration row-00-missing", [("M", "harness/run.sh")], False),
    (CITE, [("M", "state/gate/preregistrations/row-99-example.json")], False),     # edited after it was committed
    (CITE, [("D", "state/gate/preregistrations/row-99-example.json")], False),
    (NOT, [("A", "state/gate/preregistrations/new.txt")], False),
    (NOT, [("M", "state/gate/preregistrations/row-99-example.json")], False),
])
def test_the_pull_request_rule(base_root, body, changes, ok):
    assert (rule.check_pr(body, changes, base_root) == []) == ok


def test_a_preregistration_cannot_be_added_and_cited_in_one_pull_request(base_root):
    new = good()
    new["id"] = "row-98-new"
    (base_root / pr.DIR / "row-98-new.json").write_text(json.dumps(new))
    errs = rule.check_pr("Gate: pre-registration row-98-new", [("A", "state/gate/preregistrations/row-98-new.json"), ("M", "harness/run.sh")], base_root)
    assert any("must be on the base branch first" in e for e in errs)
    assert rule.check_pr(NOT, [("A", "state/gate/preregistrations/row-98-new.json")], base_root) == []
    (base_root / pr.DIR / "row-98-new.json").write_text(json.dumps({**new, "metrics": []}))
    assert rule.check_pr(NOT, [("A", "state/gate/preregistrations/row-98-new.json")], base_root)


def test_the_list_and_the_cited_preregistration_are_the_base_branchs(base_root, tmp_path_factory):
    head = tmp_path_factory.mktemp("head")
    (head / "state" / "gate" / "preregistrations").mkdir(parents=True)
    (head / rule.PATHS).write_text(json.dumps({"kind": "AccuracyPaths", "paths": ["nothing/"]}))
    (head / pr.DIR / "row-99-example.json").write_text(json.dumps(good()))
    assert rule.check_pr(NOT, [("M", "harness/run.sh")], head) == []
    assert rule.check_pr(NOT, [("M", "harness/run.sh")], head, base_root)
    (head / pr.DIR / "row-97-head-only.json").write_text(json.dumps({**good(), "id": "row-97-head-only"}))
    assert rule.check_pr("Gate: pre-registration row-97-head-only", [("M", "docs/README.md")], head, base_root)
    assert rule.check_pr("Gate: pre-registration row-97-head-only", [("M", "docs/README.md")], head) == []


def test_parse_changes_reads_name_status_and_renames():
    got = rule.parse_changes("M\ta/b.py\nR100\told.py\tnew.py\nA\tc.md\n")
    assert ("M", "a/b.py") in got and ("R", "old.py") in got and ("R", "new.py") in got


def test_the_committed_accuracy_paths_exist_or_are_prefixes():
    for p in rule.accuracy_paths(REPO):
        assert (REPO / p).exists(), p
