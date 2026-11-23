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
    write_ledger(tmp_path, "pass")
    return tmp_path


def write_ledger(root, verdict, *, prereg="row-99-example", head="a" * 40, base="b" * 40):
    """The base branch's ledger holding one evaluation of the pre-registration, of the head and merge base `check` uses by default."""
    doc = budget.record(ledger(), prereg, pr.digest(good()), base, head, 5, 1, verdict) if verdict else ledger()
    (root / budget.PATH).write_text(budget.dumps(doc))


def check(body, changes, root, base_root=None, **landing):
    """rule.check_pr for a pull request #7 whose merge base holds what `root` holds, unless `landing` says otherwise."""
    kw = {"number": 7, "head": "a" * 40, "merge_base": "b" * 40, "merge_base_root": root, **landing}
    return rule.check_pr(body, changes, root, base_root, rule.Landing(**kw))


CITE = "Gate: pre-registration row-99-example"
NOT = "Gate: not an accuracy change - documentation only"


@pytest.mark.parametrize("body,changes,ok", [
    (CITE, [("M", "harness/run.sh")], True),
    (NOT, [("M", "docs/README.md")], True),
    (NOT, [("M", "harness/run.sh")], False),                      # an accuracy path cannot claim to be no change
    (NOT, [("M", "orchestrator/ingest/score.py")], False),
    (NOT, [("M", "orchestrator/ingest/result.py")], False),       # extracts the predicted metric from the Result
    (NOT, [("M", "orchestrator/ingest/pointrecord.py")], False),
    (NOT, [("A", "orchestrator/ingest/new_module.py")], False),
    (NOT, [("M", "orchestrator/baseline/freeze.py")], False),
    (NOT, [("M", "orchestrator/resolve_agentic_corpus.py")], False),
    (NOT, [("M", "orchestrator/vllm_defaults.json")], False),
    (NOT, [("M", "schemas/summary.v3.json")], False),
    (NOT, [("M", ".github/workflows/gate-candidate.yml")], False),
    (NOT, [("M", ".github/workflows/gate-rule.yml")], False),
    (NOT, [("M", ".github/workflows/whole-run-gate.yml")], False),
    (NOT, [("M", "state/gate/accuracy-paths.json")], False),       # the gate's own policy and checker are on the list
    (NOT, [("M", "state/gate/exceptions.json")], True),            # decisions on recorded evaluations, not scoring code; validated, read from base only
    (NOT, [("M", "orchestrator/gate/rule.py")], False),
    (NOT, [("M", "orchestrator/gate/surface.py")], False),
    (NOT, [("A", "orchestrator/gate/new_check.py")], False),
    (NOT, [("D", "orchestrator/gate/gate.py")], False),
    (NOT, [("M", "orchestrator/gate/test_gate_units.py")], True),  # a test module is not the checker
    (NOT, [("M", "state/gate/ledger.json")], True),                # the ledger is committed as data, after each evaluation
    (NOT, [("M", "orchestrator/ingest/test_result.py")], True),    # a test file is not scoring code
    (NOT, [("M", "orchestrator/ingest/testdata/inferencex-workloads/seed0.json")], False),   # data the scorer reads
    ("no statement", [("M", "docs/README.md")], False),
    (CITE + "\n" + NOT, [("M", "docs/README.md")], False),
    ("Gate: pre-registration row-00-missing", [("M", "harness/run.sh")], False),
    (CITE, [("M", "state/gate/preregistrations/row-99-example.json")], False),     # edited after it was committed
    (CITE, [("D", "state/gate/preregistrations/row-99-example.json")], False),
    (NOT, [("A", "state/gate/preregistrations/new.txt")], False),
    (NOT, [("M", "state/gate/preregistrations/row-99-example.json")], False),
])
def test_the_pull_request_rule(base_root, body, changes, ok):
    assert (check(body, changes, base_root) == []) == ok


def test_a_preregistration_cannot_be_added_and_cited_in_one_pull_request(base_root):
    new = good()
    new["id"] = "row-98-new"
    (base_root / pr.DIR / "row-98-new.json").write_text(json.dumps(new))
    errs = check("Gate: pre-registration row-98-new", [("A", "state/gate/preregistrations/row-98-new.json"), ("M", "harness/run.sh")], base_root)
    assert any("must be on the base branch first" in e for e in errs)
    assert check(NOT, [("A", "state/gate/preregistrations/row-98-new.json")], base_root) == []
    (base_root / pr.DIR / "row-98-new.json").write_text(json.dumps({**new, "metrics": []}))
    assert check(NOT, [("A", "state/gate/preregistrations/row-98-new.json")], base_root)


def test_the_list_and_the_cited_preregistration_are_the_base_branchs(base_root, tmp_path_factory):
    head = tmp_path_factory.mktemp("head")
    (head / "state" / "gate" / "preregistrations").mkdir(parents=True)
    (head / rule.PATHS).write_text(json.dumps({"kind": "AccuracyPaths", "paths": ["nothing/"]}))
    (head / pr.DIR / "row-99-example.json").write_text(json.dumps(good()))
    assert check(NOT, [("M", "harness/run.sh")], head) == []
    assert check(NOT, [("M", "harness/run.sh")], head, base_root)
    (head / pr.DIR / "row-97-head-only.json").write_text(json.dumps({**good(), "id": "row-97-head-only"}))
    assert check("Gate: pre-registration row-97-head-only", [("M", "docs/README.md")], head, base_root)
    assert not any("base branch" in e and "pre-registration" in e for e in check("Gate: pre-registration row-97-head-only", [("M", "docs/README.md")], head))


def head_tree(tmp_path, files, name="head"):
    root = tmp_path / name
    for rel, text in {"harness/run.sh": "run\n", "orchestrator/ingest/score.py": "score\n", **files}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return root


def test_a_pull_request_that_carries_its_own_scoring_code_is_refused_whatever_the_change_list_says(base_root, tmp_path):
    merge_base = head_tree(tmp_path, {}, "mb")
    head = head_tree(tmp_path, {"orchestrator/ingest/score.py": "predicted = measured\n"})
    errs = check(NOT, [("M", "docs/README.md")], head, base_root, merge_base_root=merge_base)
    assert any("scoring surface" in e and "orchestrator/ingest/score.py" in e for e in errs)
    assert any("scoring surface" in e for e in check(CITE, [("M", "harness/run.sh")], head, base_root, merge_base_root=merge_base))
    same = head_tree(tmp_path, {}, "same")
    assert not any("scoring surface" in e for e in check(NOT, [("M", "docs/README.md")], same, base_root, merge_base_root=merge_base))


EXC = {"pull_request": 7, "head": "a" * 40, "reason": "the distance criterion is unjudged; accepted by hand",
       "preregistration": "row-99-example", "verdict": "unjudged"}
DEFECT = "https://github.com/inference-sim/accuracy-dashboard/issues/190"


def grant(root, *entries):
    (root / rule.EXCEPTIONS).parent.mkdir(parents=True, exist_ok=True)
    (root / rule.EXCEPTIONS).write_text(json.dumps({"kind": "GateExceptions", "exceptions": list(entries)}))


def test_a_maintainer_exception_bound_to_a_recorded_evaluation_covers_the_surface(base_root, tmp_path):
    merge_base = head_tree(tmp_path, {}, "mb")
    head = head_tree(tmp_path, {"orchestrator/ingest/score.py": "reviewed change\n"})
    write_ledger(base_root, "unjudged")
    grant(base_root, EXC)
    change = [("M", "orchestrator/ingest/score.py")]
    assert check(CITE, change, head, base_root, merge_base_root=merge_base) == []
    for other in ({"number": 8}, {"head": "c" * 40}, {"merge_base": "c" * 40}):
        assert any("scoring surface" in e or "exception" in e for e in check(CITE, change, head, base_root, merge_base_root=merge_base, **other))
    (head / rule.EXCEPTIONS).parent.mkdir(parents=True, exist_ok=True)
    grant(head, EXC)
    (base_root / rule.EXCEPTIONS).unlink()
    assert any("scoring surface" in e for e in check(CITE, change, head, base_root, merge_base_root=merge_base))


@pytest.mark.parametrize("doc", [
    {"kind": "GateExceptions", "exceptions": [{"pull_request": 7, "head": "a" * 40}]},
    {"kind": "GateExceptions", "exceptions": [{**EXC, "pull_request": "7"}]},
    {"kind": "GateExceptions", "exceptions": [{**EXC, "head": "main"}]},
    {"kind": "GateExceptions", "exceptions": [{**EXC, "reason": "short"}]},
    {"kind": "GateExceptions", "exceptions": [{k: v for k, v in EXC.items() if k != "preregistration"}]},   # not bound to an evaluation
    {"kind": "GateExceptions", "exceptions": [{k: v for k, v in EXC.items() if k != "verdict"}]},
    {"kind": "GateExceptions", "exceptions": [{**EXC, "preregistration": "Not An Id"}]},
    {"kind": "GateExceptions", "exceptions": [{**EXC, "verdict": "pass"}]},                  # a pass needs no exception
    {"kind": "GateExceptions", "exceptions": [{**EXC, "verdict": "fail"}]},                  # a fail needs its defect
    {"kind": "GateExceptions", "exceptions": [{**EXC, "verdict": "fail", "defect": "later"}]},
    {"kind": "GateExceptions", "exceptions": [{**EXC, "verdict": "fail", "defect": 0}]},
    {"kind": "GateExceptions", "exceptions": [{**EXC, "verdict": "fail", "defect": "https://example.com/issues/3"}]},
    {"kind": "GateExceptions", "exceptions": [{**EXC, "defect": 12}]},                       # an unjudged verdict has no defect
    {"kind": "GateExceptions", "exceptions": [{**EXC, "extra": 1}]},
    {"kind": "Other", "exceptions": []},
])
def test_an_exceptions_file_is_well_formed_where_a_pull_request_adds_it(base_root, tmp_path, doc):
    head = head_tree(tmp_path, {})
    (head / rule.EXCEPTIONS).parent.mkdir(parents=True, exist_ok=True)
    (head / rule.EXCEPTIONS).write_text(json.dumps(doc))
    errs = check(NOT, [("M", rule.EXCEPTIONS.as_posix())], head, base_root, merge_base_root=head)
    assert any("GateExceptions" in e for e in errs)                         # a malformed edit fails the rule check
    for good_entry in (EXC, {**EXC, "verdict": "fail", "defect": 190}, {**EXC, "verdict": "fail", "defect": DEFECT}):
        grant(head, good_entry)
        errs = check(NOT, [("M", rule.EXCEPTIONS.as_posix())], head, base_root, merge_base_root=head)
        assert errs == []                                                   # a valid edit, declared not an accuracy change, passes


def test_a_pull_request_that_only_adds_a_valid_exception_lands_with_a_passing_check(base_root, tmp_path):
    """The reviewed exception needs no evaluation of its own: it takes effect for later pull requests once on base."""
    (base_root / rule.EXCEPTIONS).unlink(missing_ok=True)
    merge_base = head_tree(tmp_path, {}, "mb")
    head = head_tree(tmp_path, {})
    grant(head, EXC)
    assert check(NOT, [("A", rule.EXCEPTIONS.as_posix())], head, base_root, merge_base_root=merge_base) == []
    assert check(NOT, [("M", rule.EXCEPTIONS.as_posix())], head, base_root, merge_base_root=merge_base) == []
    # the head's document is validated, never consumed: it does not stand in for the pull request's own check
    assert rule.exceptions(base_root) == [] and rule.exception_for(base_root, 7, "a" * 40) is None


def test_an_exception_pull_request_that_also_touches_an_accuracy_path_is_an_accuracy_change(base_root, tmp_path):
    merge_base = head_tree(tmp_path, {}, "mb")
    head = head_tree(tmp_path, {})
    grant(head, EXC)
    changes = [("M", rule.EXCEPTIONS.as_posix()), ("M", "harness/run.sh")]
    assert any("must cite a pre-registration" in e for e in check(NOT, changes, head, base_root, merge_base_root=merge_base))


def test_a_pull_request_cannot_grant_itself_the_exception_for_its_own_scoring_change(base_root, tmp_path):
    """Known bad: one pull request changes the scoring surface and adds the exception for its own head."""
    merge_base = head_tree(tmp_path, {}, "mb")
    head = head_tree(tmp_path, {"orchestrator/ingest/score.py": "predicted = measured\n"}, "head")
    (base_root / rule.EXCEPTIONS).unlink(missing_ok=True)
    write_ledger(base_root, "unjudged")
    grant(head, EXC)                                                         # on the head only, bound to this head
    change = [("M", "orchestrator/ingest/score.py"), ("A", rule.EXCEPTIONS.as_posix())]
    for body in (CITE, NOT):
        assert any("scoring surface" in e for e in check(body, change, head, base_root, merge_base_root=merge_base)), body
    # and for a change that moves no surface, the head's exception does not waive the evaluation either
    assert check(CITE, [("M", "harness/run.sh"), ("A", rule.EXCEPTIONS.as_posix())], head, base_root, merge_base_root=merge_base)


@pytest.mark.parametrize("ledger_args,ok", [
    (dict(verdict="pass"), True),
    (dict(verdict=None), False),                                  # no evaluation recorded
    (dict(verdict="unjudged"), False),
    (dict(verdict="fail"), False),
    (dict(verdict="pass", head="c" * 40), False),                 # the evaluation scored another head
    (dict(verdict="pass", base="c" * 40), False),                 # ... or another merge base
    (dict(verdict="pass", prereg="row-98-other"), False),         # ... or another pre-registration
])
def test_a_cited_preregistration_needs_a_passing_evaluation_of_this_head_and_merge_base(base_root, ledger_args, ok):
    write_ledger(base_root, **ledger_args)
    errs = check(CITE, [("M", "harness/run.sh")], base_root)
    assert (errs == []) == ok
    assert ok or any("evaluat" in e for e in errs)


def test_the_evaluation_is_the_base_branchs_ledger_not_the_pull_requests(base_root, tmp_path_factory):
    head = tmp_path_factory.mktemp("head")
    (head / "state" / "gate").mkdir(parents=True)
    write_ledger(head, "pass")
    (base_root / budget.PATH).unlink()
    assert check(CITE, [("M", "harness/run.sh")], head, base_root)
    write_ledger(base_root, None)
    assert check(CITE, [("M", "state/gate/ledger.json")], head, base_root)


def test_an_evaluation_of_an_edited_preregistration_does_not_count(base_root):
    other = {**good(), "hypothesis": "a different hypothesis than the one that was evaluated"}
    (base_root / pr.DIR / "row-99-example.json").write_text(json.dumps(other))
    assert any("evaluation" in e for e in check(CITE, [("M", "harness/run.sh")], base_root))


def test_a_ledger_that_cannot_be_read_refuses_rather_than_passes(base_root):
    (base_root / budget.PATH).write_text("{")
    assert any("ledger" in e for e in check(CITE, [("M", "harness/run.sh")], base_root))
    (base_root / budget.PATH).unlink()
    assert any("ledger" in e for e in check(CITE, [("M", "harness/run.sh")], base_root))


def test_a_maintainer_exception_records_a_decision_on_a_held_evaluation(base_root):
    """VAL-6: an unjudged verdict may be waived on the maintainer's word; a fail only with its defect; a pass needs nothing."""
    change = [("M", "harness/run.sh")]
    for verdict, entry in (("unjudged", EXC), ("fail", {**EXC, "verdict": "fail", "defect": DEFECT}),
                           ("fail", {**EXC, "verdict": "fail", "defect": 190})):
        write_ledger(base_root, verdict)
        (base_root / rule.EXCEPTIONS).unlink(missing_ok=True)
        assert check(CITE, change, base_root)
        grant(base_root, entry)
        assert check(CITE, change, base_root) == []
        assert check(CITE, change, base_root, head="c" * 40)
        assert check(CITE, change, base_root, number=8)


def test_an_exception_with_no_recorded_evaluation_does_not_pass(base_root):
    """The exception never replaces the evaluation (the case the review found: an empty ledger and an exception passed)."""
    write_ledger(base_root, None)
    grant(base_root, EXC)
    errs = check(CITE, [("M", "harness/run.sh")], base_root)
    assert any("exception" in e and "evaluation" in e for e in errs)
    grant(base_root, {**EXC, "verdict": "fail", "defect": DEFECT})
    assert check(CITE, [("M", "harness/run.sh")], base_root)
    (base_root / budget.PATH).unlink()
    assert check(CITE, [("M", "harness/run.sh")], base_root)       # an unreadable ledger holds no evaluation either


@pytest.mark.parametrize("ledger_args", [
    dict(verdict="unjudged", head="c" * 40),                      # the evaluation scored another head
    dict(verdict="unjudged", base="c" * 40),                      # ... or another merge base
    dict(verdict="unjudged", prereg="row-98-other"),              # ... or another pre-registration
])
def test_an_exception_does_not_cover_an_evaluation_of_another_head_base_or_preregistration(base_root, ledger_args):
    write_ledger(base_root, **ledger_args)
    grant(base_root, EXC)
    assert check(CITE, [("M", "harness/run.sh")], base_root)


def test_an_exception_does_not_cover_an_evaluation_of_an_edited_preregistration(base_root):
    write_ledger(base_root, "unjudged")
    (base_root / pr.DIR / "row-99-example.json").write_text(json.dumps({**good(), "hypothesis": "a different hypothesis than the evaluated one"}))
    grant(base_root, EXC)
    assert check(CITE, [("M", "harness/run.sh")], base_root)


def test_an_exception_whose_verdict_is_not_the_ledgers_does_not_pass(base_root):
    write_ledger(base_root, "fail")
    grant(base_root, EXC)                                         # states unjudged; the gate returned fail
    assert any("ledger records fail" in e for e in check(CITE, [("M", "harness/run.sh")], base_root))
    write_ledger(base_root, "unjudged")
    grant(base_root, {**EXC, "verdict": "fail", "defect": DEFECT})  # states fail; the gate returned unjudged
    assert any("ledger records unjudged" in e for e in check(CITE, [("M", "harness/run.sh")], base_root))


def test_an_exception_for_a_failing_evaluation_without_a_defect_is_refused(base_root):
    write_ledger(base_root, "fail")
    (base_root / rule.EXCEPTIONS).write_text(json.dumps({"kind": "GateExceptions", "exceptions": [{**EXC, "verdict": "fail"}]}))
    assert check(CITE, [("M", "harness/run.sh")], base_root)


def test_an_exception_for_another_preregistration_does_not_cover_this_one(base_root):
    write_ledger(base_root, "unjudged")
    grant(base_root, {**EXC, "preregistration": "row-98-other"})
    assert any("row-98-other" in e for e in check(CITE, [("M", "harness/run.sh")], base_root))


def test_an_exception_does_not_waive_the_citation_of_a_preregistration(base_root):
    write_ledger(base_root, "unjudged")
    grant(base_root, EXC)
    assert check(NOT, [("M", "harness/run.sh")], base_root)
    assert check("Gate: pre-registration row-00-missing", [("M", "harness/run.sh")], base_root)


def test_a_passing_evaluation_needs_no_exception_and_an_exception_does_not_cover_the_surface_for_it(base_root, tmp_path):
    write_ledger(base_root, "pass")
    assert check(CITE, [("M", "harness/run.sh")], base_root) == []
    merge_base = head_tree(tmp_path, {}, "mb")
    head = head_tree(tmp_path, {"orchestrator/ingest/score.py": "changed\n"})
    grant(base_root, EXC)
    assert any("scoring surface" in e for e in check(CITE, [("M", "orchestrator/ingest/score.py")], head, base_root, merge_base_root=merge_base))


# ---- the gate cannot be weakened by a pull request that calls itself no accuracy change ----

def gate_trees(base_root, tmp_path, edit):
    """A merge base holding the gate as main has it, and a head that differs by `edit` (path -> new text, None deletes)."""
    files = {rel: (REPO / rel).read_text() for rel in ("state/gate/accuracy-paths.json", "orchestrator/gate/rule.py", "orchestrator/gate/surface.py")}
    files["state/gate/exceptions.json"] = json.dumps({"kind": "GateExceptions", "exceptions": []})
    merge_base = head_tree(tmp_path, files, "mb")
    head = head_tree(tmp_path, {k: v for k, v in {**files, **edit}.items() if v is not None}, "head")
    for rel, text in edit.items():
        if text is None:
            (head / rel).unlink(missing_ok=True)
    return merge_base, head


@pytest.mark.parametrize("name,rel,edit", [
    ("deleting a scoring path from the list", "state/gate/accuracy-paths.json",
     lambda t: json.dumps({"kind": "AccuracyPaths", "paths": [p for p in json.loads(t)["paths"] if p != "harness/"]})),
    ("weakening rule.py", "orchestrator/gate/rule.py", lambda t: t + "\ndef check_pr(*a, **k):\n    return []\n"),
    ("weakening surface.py", "orchestrator/gate/surface.py", lambda t: t + "\ndef differing(*a, **k):\n    return []\n"),
])
def test_a_pull_request_cannot_weaken_the_gate_by_calling_itself_no_accuracy_change(base_root, tmp_path, name, rel, edit):
    original = (REPO / rel).read_text()
    merge_base, head = gate_trees(base_root, tmp_path, {rel: edit(original)})
    # the change list names the file: the rule needs a citation, which `not an accuracy change` is not
    errs = check(NOT, [("M", rel)], head, base_root, merge_base_root=merge_base)
    assert any("must cite a pre-registration" in e for e in errs), name
    # the change list lies (it names a document only): the trees still differ on the scoring surface
    errs = check(NOT, [("M", "docs/README.md")], head, base_root, merge_base_root=merge_base)
    assert any("scoring surface" in e and rel in e for e in errs), name
    # citing a pre-registration does not help without a recorded evaluation or an exception bound to one
    write_ledger(base_root, None)
    assert check(CITE, [("M", rel)], head, base_root, merge_base_root=merge_base), name
    # an evaluation recorded for this head and merge base plus a bound exception on the base branch lets it land
    write_ledger(base_root, "unjudged")
    grant(base_root, EXC)
    assert check(CITE, [("M", rel)], head, base_root, merge_base_root=merge_base) == [], name


def test_the_gate_is_on_the_accuracy_paths():
    paths = rule.accuracy_paths(REPO)
    for f in ("state/gate/accuracy-paths.json", "orchestrator/gate/rule.py", "orchestrator/gate/surface.py",
              "orchestrator/gate/gate.py", ".github/workflows/gate-rule.yml"):
        assert rule.touches(f, paths), f
    assert not rule.touches("orchestrator/gate/test_gate_units.py", paths)
    assert not rule.touches("state/gate/ledger.json", paths) and not rule.touches("state/gate/preregistrations/x.json", paths)
    assert not rule.touches("state/gate/exceptions.json", paths)             # reviewed data, validated and read from base only


def test_the_pull_request_that_adds_a_preregistration_needs_no_evaluation(base_root):
    write_ledger(base_root, None)
    new = {**good(), "id": "row-98-new"}
    head = base_root.parent / "head-new"
    (head / pr.DIR).mkdir(parents=True)
    (head / pr.DIR / "row-98-new.json").write_text(json.dumps(new))
    assert check(NOT, [("A", "state/gate/preregistrations/row-98-new.json")], head, base_root, merge_base_root=head) == []


def test_parse_changes_reads_name_status_and_renames():
    got = rule.parse_changes("M\ta/b.py\nR100\told.py\tnew.py\nA\tc.md\n")
    assert ("M", "a/b.py") in got and ("R", "old.py") in got and ("R", "new.py") in got


def test_the_committed_accuracy_paths_exist_or_are_prefixes():
    for p in rule.accuracy_paths(REPO):
        assert (REPO / p).exists(), p
