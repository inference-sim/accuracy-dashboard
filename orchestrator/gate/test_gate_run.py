"""The gate job end to end on a fake partition: the verdict, the lanes, the refusals, and the guarantee that
nothing a run prints, logs or writes holds a held-out unit, a role key, a per-unit value or the seed.

Run: python3 -m pytest orchestrator/gate/test_gate_run.py
"""
import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import budget  # noqa: E402
import fakepartition as fp  # noqa: E402
import gate  # noqa: E402
import guard as gd  # noqa: E402
import prereg as pr  # noqa: E402
import reduce as rd  # noqa: E402

VALUE = lambda i, u: 1234.5678 + i * 0.0137          # noqa: E731  (distinctive per-unit measurements)


@pytest.fixture(scope="module")
def fake(tmp_path_factory):
    return fp.build(tmp_path_factory.mktemp("ledger"), legacy_every=7)


class World:
    """One evaluation's inputs on disk: a checkout root (ledger + pre-registration), tables, predictions."""

    def __init__(self, tmp, fake, *, base=lambda u: 1.10, cand=lambda u: 1.10, over=None, budget_n=3, ceiling=0.05, value=VALUE):
        self.tmp, self.fake = Path(tmp), fake
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.measured = self.tmp / "measured.csv"
        sha = fp.measured_table(fake, self.measured, value=value)
        self.root = self.tmp / "root"
        (self.root / pr.DIR).mkdir(parents=True)
        led = {"kind": "GateLedger", "margin_ceiling": {"error": ceiling, "distance": ceiling},
               "partitions": {"1": {"budget": budget_n, "evaluations": []}}}
        (self.root / budget.PATH).write_text(budget.dumps(led))
        self.prereg = fp.prereg_doc(sha, **(over or {}))
        (self.root / pr.DIR / "row-99-example.json").write_text(json.dumps(self.prereg))
        fp.predictions_file(fake, self.measured, self.tmp / "base.json", fp.BASE, base)
        fp.predictions_file(fake, self.measured, self.tmp / "cand.json", fp.CAND, cand)
        self.out = self.tmp / "out"

    def argv(self, **kw):
        a = {"--root": self.root, "--ledger": self.fake.ledger, "--prereg": "row-99-example", "--measured": self.measured,
             "--base-predictions": self.tmp / "base.json", "--candidate-predictions": self.tmp / "cand.json",
             "--base": fp.BASE, "--candidate": fp.CAND, "--run-id": 7, "--out": self.out}
        a.update(kw)
        return ["evaluate", *[x for k, v in a.items() for x in (k, str(v))]]

    def run(self, monkeypatch, capsys, seed=fp.SEED_HEX, **kw):
        if seed is None:
            monkeypatch.delenv("LEDGER_SEED", raising=False)
        else:
            monkeypatch.setenv("LEDGER_SEED", seed)
        try:
            code = gate.main(self.argv(**kw))
        except SystemExit as e:
            code = e.code
        cap = capsys.readouterr()
        return code, cap.out, cap.err

    def report(self):
        return json.loads((self.out / "report.json").read_text())

    def forbidden(self):
        f = self.fake
        words = {u.unit_id for u in f.units} | {u.role_key for u in f.units} | {fp.SEED_HEX}
        words |= {w[:16] for w in words if len(w) == 64 and w != fp.SEED_HEX}
        words |= {f"{VALUE(i, None):.4f}"[:7] for i in range(0, 200, 17)}
        return words

    def everything(self, *streams):
        text = "\n".join(streams)
        for p in sorted(self.out.glob("*")) if self.out.exists() else []:
            text += "\n" + p.read_text()
        return text


H100 = lambda u: u.identity["hardware"] == "h100"  # noqa: E731


@pytest.fixture
def error_only(monkeypatch):
    """The only way to a `pass` while distance is unjudged: a test-world gate that requires the error criterion alone."""
    monkeypatch.setattr(pr, "CRITERIA", ("error",))
    return {"criteria": [{"criterion": "error", "margin": 0.02}]}


def test_a_pass_returns_aggregates_and_records_one_evaluation(tmp_path, fake, monkeypatch, capsys, error_only):
    w = World(tmp_path, fake, cand=lambda u: 1.05 if H100(u) else 1.10, over=error_only)
    code, out, err = w.run(monkeypatch, capsys)
    assert code == 0 and "pass: evaluation 1 of 3" in out
    rep = w.report()
    assert rep["verdict"] == "pass" and rep["evaluation"] == 1 and rep["budget"] == 3
    target = [l for l in rep["lanes"] if l["target"]]
    assert target and all(l["passes"] for l in rep["lanes"]) and target[0]["results"][0]["difference"] < 0
    assert sorted(l["role_keys"] for l in rep["lanes"]) == sorted(len({u.role_key for u in fake.held(x)}) for x in "AB")   # held keys only
    led = json.loads((w.out / "ledger.json").read_text())
    ev = led["partitions"]["1"]["evaluations"]
    assert [e["preregistration"] for e in ev] == ["row-99-example"] and ev[0]["run_id"] == 7 and ev[0]["verdict"] == "pass"
    assert budget.validate(led) == []
    comment = (w.out / "comment.md").read_text()
    assert comment.startswith("<!-- whole-run-gate partition=1 preregistration=row-99-example -->")
    assert rep["preregistration_sha256"] == pr.digest(w.prereg)


def test_the_one_evaluation_is_spent_and_a_second_request_is_refused(tmp_path, fake, monkeypatch, capsys):
    w = World(tmp_path, fake)
    assert w.run(monkeypatch, capsys)[0] == 0
    (w.root / budget.PATH).write_text((w.out / "ledger.json").read_text())
    code, out, err = w.run(monkeypatch, capsys)
    assert code != 0 and "already received its one held evaluation" in str(code)


def test_the_gate_refuses_without_a_budget(tmp_path, fake, monkeypatch, capsys):
    w = World(tmp_path, fake, budget_n=None)
    code, *_ = w.run(monkeypatch, capsys)
    assert "no budget" in str(code) and not w.out.exists()


def test_the_gate_refuses_once_the_budget_is_spent(tmp_path, fake, monkeypatch, capsys):
    w = World(tmp_path, fake, budget_n=0)
    code, *_ = w.run(monkeypatch, capsys)
    assert "0 of 0" in str(code) and not w.out.exists()


def test_a_guard_lane_that_regresses_past_the_margin_fails(tmp_path, fake, monkeypatch, capsys):
    w = World(tmp_path, fake, cand=lambda u: 1.05 if H100(u) else 1.16)       # h200 is 0.06 worse; the margin is 0.02
    assert w.run(monkeypatch, capsys)[0] == 0
    rep = w.report()
    assert rep["verdict"] == "fail"
    assert [l["passes"] for l in rep["lanes"] if not l["target"]] == [False]
    assert json.loads((w.out / "ledger.json").read_text())["partitions"]["1"]["evaluations"][0]["verdict"] == "fail"


def test_a_target_lane_that_does_not_improve_fails(tmp_path, fake, monkeypatch, capsys):
    w = World(tmp_path, fake)                                                   # candidate = base
    assert w.run(monkeypatch, capsys)[0] == 0 and w.report()["verdict"] == "fail"


def test_a_regression_on_units_that_are_not_blind_does_not_change_the_verdict(tmp_path, fake, monkeypatch, capsys, error_only):
    legacy_keys = {u.role_key for u in fake.units if fake.assigned[u.unit_id].not_blind}
    w = World(tmp_path, fake, cand=lambda u: (1.50 if u.role_key in legacy_keys else 1.05) if H100(u) else 1.10, over=error_only)
    assert w.run(monkeypatch, capsys)[0] == 0
    rep = w.report()
    assert rep["verdict"] == "pass"
    nb = rep["not_blind"]["lanes"]
    assert nb and all("p_value" not in r and r["rejected"] is None for l in nb for r in l["results"])
    assert any(r["difference"] > 0.3 for l in nb for r in l["results"])


def test_a_criterion_that_cannot_be_judged_gives_unjudged_not_pass(tmp_path, fake, monkeypatch, capsys):
    w = World(tmp_path, fake, cand=lambda u: 1.05 if H100(u) else 1.10)
    assert w.run(monkeypatch, capsys)[0] == 0
    rep = w.report()
    assert rep["verdict"] == "unjudged" and rep["target_unjudged"]
    assert all(r["criterion"] == "error" for l in rep["lanes"] for r in l["results"])


def test_a_preregistration_that_omits_a_criterion_is_not_evaluated(tmp_path, fake, monkeypatch, capsys):
    w = World(tmp_path, fake, cand=lambda u: 1.05 if H100(u) else 1.10, over={"criteria": [{"criterion": "error", "margin": 0.02}]})
    code, *_ = w.run(monkeypatch, capsys)
    assert "exactly one of each of error, distance" in str(code) and not w.out.exists()


def test_lanes_are_named_by_their_shared_fields_and_never_list_their_members(tmp_path, fake, monkeypatch, capsys):
    w = World(tmp_path, fake, cand=lambda u: 1.05 if H100(u) else 1.10)
    assert w.run(monkeypatch, capsys)[0] == 0
    text = (w.out / "report.json").read_text() + (w.out / "comment.md").read_text()
    assert "cfg-" not in text                                                  # no layout of a held unit is named
    names = {l["name"] for l in w.report()["lanes"]}
    assert names == {f"vllm/{fp.COMMIT}/h100/model-a/*", f"vllm/{fp.COMMIT}/h200/model-b/*"}
    assert all(l["member_lanes"] >= 10 and l["merged"] for l in w.report()["lanes"])


def test_a_short_lane_is_unjudged_and_only_counted(tmp_path, monkeypatch, capsys):
    f = fp.build(tmp_path / "led", keys={"A": 160, "C": 12}, legacy_every=0)
    w = World(tmp_path / "w", f, over={"target_lanes": [{"engine": "sglang"}]}, cand=lambda u: 1.05)
    assert w.run(monkeypatch, capsys)[0] == 0
    rep = w.report()
    assert rep["unjudged_lanes"] >= 1 and "sglang" not in (w.out / "report.json").read_text().replace('"engine": "sglang"', "")
    assert rep["verdict"] == "unjudged" and rep["target_unjudged"][0]["target_lane"] == 0


def test_a_lane_with_too_few_scored_role_keys_is_unjudged_on_that_metric(tmp_path, fake, monkeypatch, capsys):
    keep = {u.role_key for u in fake.held("B")[:6]}                           # at most six role keys keep a measurement
    w = World(tmp_path, fake, cand=lambda u: 1.05 if H100(u) else 1.10,
              value=lambda i, u: None if (u.identity["hardware"] == "h200" and u.role_key not in keep) else VALUE(i, u))
    assert w.run(monkeypatch, capsys)[0] == 0
    lane = next(l for l in w.report()["lanes"] if not l["target"])
    assert lane["results"] == [] and "fewer than 10 role keys" in lane["unjudged"][0]["reason"]


def test_the_gate_refuses_a_report_that_is_not_aggregates_only(tmp_path, fake, monkeypatch, capsys):
    real = rd.reduce_report
    def leaky(*a, **k):
        r = real(*a, **k)
        r["lanes"][0]["per_unit"] = [1.0, 2.0]
        return r
    monkeypatch.setattr(rd, "reduce_report", leaky)
    w = World(tmp_path, fake, cand=lambda u: 1.05)
    code, *_ = w.run(monkeypatch, capsys)
    assert "outside the aggregate schema" in str(code) and not w.out.exists()


def test_lane_merging_follows_engine_commit_chip_then_engine_commit():
    def lane(chip, layout, e="vllm"):
        return (e, "c1", chip, "m", layout)
    def units(tag, n):
        return [{"unit_id": f"{tag}{i}", "role_key": f"{tag}{i}"} for i in range(n)]
    by_lane = {lane("h100", "x"): units("a", 6), lane("h100", "y"): units("b", 6),          # merge on chip: 12 keys
               lane("h200", "z"): units("c", 6), lane("b200", "w"): units("d", 6),          # merge on engine+commit: 12 keys
               lane("h100", "q", e="sglang"): units("e", 4)}                                # alone: unjudged
    judged, left = rd.build_lanes(by_lane)
    sets = sorted(sorted(m[2] for m in members) for members, _ in judged)
    assert sets == [["b200", "h200"], ["h100", "h100"]] and left == 1
    assert rd._name([lane("h200", "z"), lane("b200", "w")]) == "vllm/c1/*/m/*"


def test_a_lane_of_nine_role_keys_is_unjudged_and_of_ten_is_judged():
    def us(n):
        return [{"unit_id": str(i), "role_key": str(i)} for i in range(n)]
    assert rd.lanes_of({("e", "c", "h", "m", "l"): us(9)}) == ([], 1)
    assert len(rd.lanes_of({("e", "c", "h", "m", "l"): us(10)})[0]) == 1


def test_refusals_for_inputs_that_are_not_the_pre_registered_ones(tmp_path, fake, monkeypatch, capsys):
    w = World(tmp_path, fake, cand=lambda u: 1.05)
    cases = [
        ({"--candidate": "f" * 40}, "head commit of the run"),
        ({"--base": "e" * 40}, "head commit of the run"),
        ({"--prereg": "no-such-thing"}, "no pre-registration"),
    ]
    for kw, why in cases:
        code, *_ = w.run(monkeypatch, capsys, **kw)
        assert why in str(code), (kw, code)
    code, *_ = w.run(monkeypatch, capsys, seed="12" * 32)
    assert "seed" in str(code) and "12" * 32 not in str(code)
    code, *_ = w.run(monkeypatch, capsys, seed=None)
    assert "LEDGER_SEED is not set" in str(code)
    assert not w.out.exists()


def test_the_measured_table_must_be_the_pinned_one(tmp_path, fake, monkeypatch, capsys):
    w = World(tmp_path, fake)
    w.measured.write_text(w.measured.read_text() + "\n")
    code, *_ = w.run(monkeypatch, capsys)
    assert "measured_sha256" in str(code) and not w.out.exists()


def test_the_measured_table_may_not_hold_a_published_unit(tmp_path, fake, monkeypatch, capsys):
    w = World(tmp_path, fake)
    anchor = next(u for u in fake.units if fake.assigned[u.unit_id].role == "anchor")
    with open(w.measured, "a", newline="") as f:
        csv.writer(f, lineterminator="\n").writerow([anchor.unit_id, *fake.lane_tuple(anchor), "1.0"])
    w.prereg["measured_sha256"] = hashlib.sha256(w.measured.read_bytes()).hexdigest()
    (w.root / pr.DIR / "row-99-example.json").write_text(json.dumps(w.prereg))
    fp.predictions_file(fake, w.measured, w.tmp / "base.json", fp.BASE, lambda u: 1.1)
    fp.predictions_file(fake, w.measured, w.tmp / "cand.json", fp.CAND, lambda u: 1.1)
    code, *_ = w.run(monkeypatch, capsys)
    assert "published fit or anchor" in str(code)


def test_base_and_candidate_must_have_run_under_one_harness(tmp_path, fake, monkeypatch, capsys):
    w = World(tmp_path, fake)
    fp.predictions_file(fake, w.measured, w.tmp / "cand.json", fp.CAND, lambda u: 1.0, harness="9" * 64)
    code, *_ = w.run(monkeypatch, capsys)
    assert "different harnesses" in str(code)


def test_a_preregistration_for_another_partition_version_is_refused(tmp_path, fake, monkeypatch, capsys):
    w = World(tmp_path, fake, over={"partition_version": 2})
    led = json.loads((w.root / budget.PATH).read_text())
    led["partitions"]["2"] = {"budget": 1, "evaluations": []}
    (w.root / budget.PATH).write_text(budget.dumps(led))
    code, *_ = w.run(monkeypatch, capsys)
    assert "another partition version" in str(code)


# ---- aggregates only ----

def test_nothing_a_run_prints_or_writes_holds_a_unit_a_role_key_a_value_or_the_seed(tmp_path, fake, monkeypatch, capsys):
    w = World(tmp_path, fake, cand=lambda u: 1.05 if H100(u) else 1.10)
    code, out, err = w.run(monkeypatch, capsys)
    assert code == 0
    text = w.everything(out, err)
    assert len(text) > 1000
    for word in w.forbidden():
        assert word not in text, "a held-out datum or the seed is in the output"
    for name in ("report.json", "comment.md", "ledger.json"):
        t = (w.out / name).read_text()
        assert not any(u.unit_id in t or u.role_key in t for u in fake.units)


def test_the_refusals_name_neither_a_unit_nor_the_seed(tmp_path, fake, monkeypatch, capsys):
    w = World(tmp_path, fake)
    for kw in ({"--candidate": "f" * 40}, {"--prereg": "nope"}):
        code, out, err = w.run(monkeypatch, capsys, **kw)
        assert not any(x in f"{code}{out}{err}" for x in w.forbidden())
    code, out, err = w.run(monkeypatch, capsys, seed="12" * 32)
    assert "12" * 32 not in f"{code}{out}{err}"


def test_an_unexpected_error_names_its_type_and_nothing_else(tmp_path, fake, monkeypatch, capsys):
    w = World(tmp_path, fake)
    secret = fake.units[0].unit_id

    def boom(*a, **k):
        raise KeyError(secret)
    monkeypatch.setattr(rd, "reduce_report", boom)
    code, out, err = w.run(monkeypatch, capsys)
    assert "internal error (KeyError)" in str(code) and secret not in f"{code}{out}{err}"


def test_the_guard_scrubs_what_it_withholds_and_refuses_a_report_that_is_not_aggregates():
    g = gd.Guard({"a" * 64, "seedvalue"})
    assert "a" * 64 not in g.scrub(f"x {'a' * 64} y") and "seedvalue" not in g.scrub("seedvalue")
    assert "a" * 16 not in g.scrub("prefix " + "a" * 16)
    lane = {"name": "n", "lane": {"engine": "vllm"}, "member_lanes": 3, "merged": True, "target": True, "role_keys": 12,
            "results": [{"criterion": "error", "metric": "tpot", "null_difference_at_least": 0.0, "role_keys": 12, "difference": 0.0,
                         "upper_95": 0.0, "p_value": 1.0, "rejected": False}], "unjudged": [], "passes": False}
    rep = {"kind": "WholeRunGateReport", "min_points": 10, "lanes": [lane], "not_blind": {"note": "n", "lanes": [], "unjudged_lanes": 0},
           "target_unjudged": []}
    g.check_report(rep)
    def bad(edit):
        r = json.loads(json.dumps(rep))
        edit(r)
        with pytest.raises(gd.LeakError):
            g.check_report(r)
    bad(lambda r: r["lanes"][0].update(per_unit=[1.0]))                       # a field outside the schema
    bad(lambda r: r["lanes"][0].update(role_keys=9))                          # an aggregate of fewer than ten role keys
    bad(lambda r: r["lanes"][0]["results"][0].update(role_keys=3))
    bad(lambda r: r["lanes"][0]["results"][0].update(units=["x"]))
    bad(lambda r: r.update(min_points=1))
    bad(lambda r: r.update(extra=1))
    bad(lambda r: r["lanes"][0].update(name="a" * 64))                        # a withheld id in a name
    bad(lambda r: r["lanes"][0].update(lane={"unit_id": "x"}))
    bad(lambda r: r["target_unjudged"].append({"unit": "x"}))


# ---- the commands, as the workflows run them ----

def test_the_cli_reads_the_seed_from_the_environment_only(tmp_path, fake):
    w = World(tmp_path, fake, cand=lambda u: 1.05 if H100(u) else 1.10)
    cmd = [sys.executable, str(HERE / "gate.py"), *w.argv()]
    assert fp.SEED_HEX not in " ".join(cmd)
    run = lambda env: subprocess.run(cmd, capture_output=True, text=True, env=env)  # noqa: E731
    base_env = {k: v for k, v in os.environ.items() if k != "LEDGER_SEED"}
    r = run(base_env)
    assert r.returncode != 0 and "LEDGER_SEED is not set" in r.stderr and not w.out.exists()
    r = run({**base_env, "LEDGER_SEED": fp.SEED_HEX})
    assert r.returncode == 0, r.stderr
    assert fp.SEED_HEX not in r.stdout + r.stderr and "Traceback" not in r.stderr
    assert (w.out / "report.json").is_file()


def test_check_commands_report_problems_with_a_nonzero_exit(tmp_path, capsys):
    root = tmp_path
    (root / pr.DIR).mkdir(parents=True)
    (root / pr.DIR / "bad-one.json").write_text(json.dumps({"kind": "PreRegistration"}))
    assert gate.main(["check-prereg", "--root", str(root)]) == 1
    (root / pr.DIR / "bad-one.json").write_text(json.dumps(fp.prereg_doc(hashlib.sha256(b"").hexdigest(), id="bad-one")))
    assert gate.main(["check-prereg", "--root", str(root)]) == 0
    assert gate.main(["check-ledger", "--root", str(root)]) == 1                                 # no ledger file
    assert gate.main(["check-ledger", "--root", str(HERE.parent.parent)]) == 0
    capsys.readouterr()


def test_check_pr_reads_the_body_and_the_changes(tmp_path):
    body, ch = tmp_path / "body.md", tmp_path / "changes.txt"
    body.write_text("Summary\n\nGate: not an accuracy change - documentation only\n")
    ch.write_text("M\tdocs/README.md\n")
    assert gate.main(["check-pr", "--body-file", str(body), "--changes-file", str(ch), "--root", str(HERE.parent.parent)]) == 0
    ch.write_text("M\tharness/run.sh\n")
    assert gate.main(["check-pr", "--body-file", str(body), "--changes-file", str(ch), "--root", str(HERE.parent.parent)]) == 1


def _contract(directory: Path, fake, held_ids=None):
    directory.mkdir(parents=True)
    cols = "scenario,model,gpu,label,concurrency,meas_tpot_us,pred_tpot_us,meas_ttft_us,pred_ttft_us,grade,point_id,measured_date".split(",")
    with open(directory / "points.csv", "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(cols)
        for i, u in enumerate(fake.units[:40]):
            w.writerow(["s", u.identity["model"], u.identity["hardware"], "l", 1, 100 + i, 110 + i, "", "", "A", u.unit_id, "2026-01-01"])
    (directory / "provenance.json").write_text('{"harness": "x"}')


def test_build_measured_and_contract_to_predictions(tmp_path, fake, capsys):
    _contract(tmp_path / "c", fake)
    out = tmp_path / "m.csv"
    assert gate.main(["build-measured", "--contract", str(tmp_path / "c"), "--ledger", str(fake.ledger),
                      "--modelled-commit", fp.COMMIT, "--out", str(out)]) == 0
    rows = list(csv.DictReader(out.read_text().splitlines()))
    published = set()
    for role in ("fit", "anchor"):
        published |= {u.unit_id for u in fake.units if fake.assigned[u.unit_id].role == role}
    assert rows and not ({r["point_id"] for r in rows} & published)
    assert list(rows[0])[:6] == ["point_id", "engine", "modelled_commit", "chip", "model", "layout"]
    assert {r["modelled_commit"] for r in rows} == {fp.COMMIT}
    handed = tmp_path / "handed.txt"
    ids = [r["point_id"] for r in rows] + ["9" * 64]
    handed.write_text("\n".join(ids))
    pred = tmp_path / "p.json"
    assert gate.main(["contract-to-predictions", "--contract", str(tmp_path / "c"), "--handed", str(handed),
                      "--candidate", fp.CAND, "--out", str(pred)]) == 0
    doc = json.loads(pred.read_text())
    by = {r["unit_id"]: r for r in doc["predictions"]}
    assert by["9" * 64]["reason"] and "tpot_us" in next(r for r in doc["predictions"] if "values" in r)["values"]
    assert doc["candidate"] == fp.CAND and len(doc["harness"]) == 64
    capsys.readouterr()


def test_harness_digest_ignores_the_commit_and_what_binds_a_side_to_its_simulator(tmp_path):
    def digest(doc):
        p = tmp_path / "p.json"
        p.write_text(json.dumps(doc))
        return gate.harness_digest(p)
    a = {"harness_commit": "a" * 40, "simulator": {"harness_commit": "a" * 40, "build": "v1"}, "ingest": "api", "points": 14,
         "units": 7, "pulled_at": "2026-11-01", "blis": {"release": "v1", "commit_sha": "a" * 40}, "engine": {"kind": "vllm", "version": "0.33.0"},
         "vllm_ref": "v0.33.0", "vllm_max_distance": 10, "fields_sha256": "1" * 64, "pull_manifest_sha256": "2" * 64,
         "corpora": {"x": "y"}, "experimental": False}
    b = {**a, "harness_commit": "b" * 40, "simulator": {"harness_commit": "b" * 40, "build": "v1"}}
    assert digest(a) == digest(b)
    # a different simulator build and the data it carries do not make two sides different harnesses ...
    other_sim = {**a, "simulator": {"harness_commit": "a" * 40, "build": "v2"}, "blis": {"release": "v2", "commit_sha": "c" * 40},
                 "engine": {"kind": "vllm", "version": "0.34.0"}, "vllm_ref": "v0.34.0", "fields_sha256": "3" * 64,
                 "pull_manifest_sha256": "4" * 64, "corpora": {"x": "z"}, "experimental": True, "engines": [{"kind": "sglang"}]}
    assert digest(a) == digest(other_sim)
    # ... but anything else about the run does: the units handed out, the pull, the ingest, and any key not named as side-bound
    for change in ({"points": 15}, {"units": 8}, {"pulled_at": "2026-11-02"}, {"ingest": "dump"}, {"new_setting": 1}):
        assert digest(a) != digest({**a, **change}), change


def test_handed_units_exclude_published_fit_and_anchor(tmp_path, fake, capsys):
    out = tmp_path / "h.txt"
    assert gate.main(["handed-units", "--ledger", str(fake.ledger), "--out", str(out)]) == 0
    ids = set(out.read_text().split())
    pub = {u.unit_id for u in fake.units if fake.assigned[u.unit_id].role in ("fit", "anchor")}
    assert ids and not (ids & pub) and ids | pub == {u.unit_id for u in fake.units}
    capsys.readouterr()


def test_unrecorded_names_the_runs_the_ledger_does_not_hold(tmp_path, capsys):
    root = tmp_path / "root"
    (root / "state" / "gate").mkdir(parents=True)
    led = json.loads((HERE.parent.parent / "state" / "gate" / "ledger.json").read_text())
    led["partitions"]["1"]["budget"] = 5
    led = budget.record(led, "row-1-x", "a" * 64, "b" * 40, "c" * 40, 777, 1, "pass")
    (root / "state" / "gate" / "ledger.json").write_text(budget.dumps(led))
    ids = tmp_path / "ids.txt"
    ids.write_text("777\n")
    assert gate.main(["unrecorded", "--run-ids", str(ids), "--root", str(root)]) == 0
    ids.write_text("777\n778\n")
    assert gate.main(["unrecorded", "--run-ids", str(ids), "--root", str(root)]) == 1
    assert "gate run 778" in capsys.readouterr().out


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
