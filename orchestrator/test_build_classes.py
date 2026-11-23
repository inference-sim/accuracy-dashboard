"""The classes page's data (orchestrator/build_classes.py): the regular InferenceX class, the reconstructed-recipe class and the
configiq class, each counted on its own and never mixed.

Every input here is synthetic (X12); expectations are worked by hand from the fixtures, never read back from the builder. What is
asserted is the document a reader would see: how many points, how many of each grade, what error, and that a class never leaks into
another's counts.

Run: python3 -m pytest orchestrator/test_build_classes.py
"""
import csv
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_classes as bc  # noqa: E402

META = {"command": "make it", "heads": {"harness": "abc"}, "pulled_at": "2026-11-16"}
SUB = {"kind": "client_difference", "subject": "send_gap", "detail": "closed loop"}


def jl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def contract(tmp_path, errors, refused=0, failed=0):
    """A contract directory of len(errors) G4 points; each error is the TTFT and TPOT percent error of one point
    (measured 1000 us, predicted 1000 * (1 + e/100))."""
    d = tmp_path / "contract"
    d.mkdir()
    jl(d / "fidelity.jsonl", [{"point_id": f"p{i}", "grade": "G4", "substitutions": [SUB]} for i in range(len(errors))])
    with open(d / "points.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["point_id", "grade", "meas_ttft_us", "pred_ttft_us", "meas_tpot_us", "pred_tpot_us"])
        for i, e in enumerate(errors):
            w.writerow([f"p{i}", "G4", 1000, 1000 * (1 + e / 100), 1000, 1000 * (1 + e / 100)])
    jl(d / "not_scored.jsonl", [{"g5_reason": {"code": "no_recipe", "subject": "x"}} for _ in range(refused)])
    jl(d / "failed.jsonl", [{"point_id": f"f{i}"} for i in range(failed)])
    return d


def _doc(*classes):
    return {"format": bc.FORMAT, "generated_at": "t", "snapshot_id": "s", "classes": list(classes)}


def derive(d, **kw):
    return bc.derive_contract(d, cid="inferencex-reconstructed", label="L", note="N", kind="reconstructed", meta=META, **kw)


def test_contract_class_counts_and_error_worked_by_hand(tmp_path):
    errors = [10, -10, 20, -20, 30, -30, 40, -40, 50, -50, 60]  # 11 points
    c = derive(contract(tmp_path, errors, refused=3, failed=1))
    assert c["counts"] == {"points": 15, "scored": 11, "refused": 3, "failed": 1, "withheld": 0}
    assert c["grades"] == {"G1": 0, "G2": 0, "G3": 0, "G4": 11, "G5": 3}
    g4 = c["accuracy_by_grade"]["G4"]["ttft"]
    assert g4["n"] == 11
    assert g4["mape"] == pytest.approx(sum(abs(e) for e in errors) / 11)
    assert g4["signed_median"] == pytest.approx(10)
    assert c["substitutions"] == [{**SUB, "points": 11}]
    assert c["refusals"] == [{"code": "no_recipe", "subject": bc.OTHER_SETTINGS, "points": 3}]  # a reason under the minimum is one row per code
    assert bc.check(_doc(_regular(), c)) == []


def test_a_figure_under_ten_points_is_too_few(tmp_path):
    c = derive(contract(tmp_path, [5, 6, 7]))
    assert c["accuracy_by_grade"]["G4"]["ttft"] == {"n": 3, "mape": bc.TOO_FEW, "signed_median": bc.TOO_FEW}


def _configiq_dir(tmp_path, n_train=10, n_test=4, withheld_split=()):
    """A score_configiq directory. n_test scored points fall on the dev split's test set; D9 scores them like any other. With
    withheld_split the run withheld that split on request (a local experiment): those points are not scored."""
    d = tmp_path / "cq"
    d.mkdir()
    n_scored = n_train + (0 if withheld_split else n_test)
    cov = {"points": n_train + n_test + 2, "scored": n_scored, "refused": 1, "failed": 1, "withheld": n_test if withheld_split else 0,
           "refusals_by_reason": {"field_not_in_release: engine.max_model_len": 1}}
    br = {"provisional_grades": {"G3": n_scored}, "grades": {"G5": 1}}
    (d / "summary.json").write_text(json.dumps({"coverage": cov, "by_source": br,
                                                "provenance": {"dataset": {"revision": "rev"},
                                                               "split": {"name": "dev", "withheld": list(withheld_split)}}}))
    recs = [{"status": "scored", "split": "train", "grade": "G3", "model": "m/a" if i < 7 else "m/b", "substitutions": [SUB],
             "errors_pct": {"ttft_mean": 100.0, "itl_mean": -10.0, "tpot_median": 5.0}} for i in range(n_train)]
    if withheld_split:
        recs += [{"status": "withheld", "split": "test", "grade": None, "model": "m/a"} for _ in range(n_test)]
    else:
        recs += [{"status": "scored", "split": "test", "grade": "G3", "model": "m/a", "substitutions": [SUB],
                  "errors_pct": {"ttft_mean": 1.0, "itl_mean": -1.0, "tpot_median": 1.0}} for _ in range(n_test)]
    jl(d / "configiq-points.jsonl", recs)
    return d


def test_configiq_class_is_an_anchor_source_that_is_also_provisional_and_drops_no_split(tmp_path):
    """D9: every configiq unit is an anchor unit, so the test-split points are in the figures. anchor and kind are two facts."""
    c = bc.derive_configiq(_configiq_dir(tmp_path), cid="configiq", label="L", note="N", meta=META)
    assert c["kind"] == "provisional" and c["anchor"] is True
    assert c["counts"] == {"points": 16, "scored": 14, "refused": 1, "failed": 1, "withheld": 0}
    acc = c["accuracy_by_grade"]["G3"]
    assert acc["ttft"]["n"] == 14 and acc["ttft"]["mape"] == pytest.approx((10 * 100.0 + 4 * 1.0) / 14)
    assert "anchor-only" in c["partition"] and "test partition" not in c["partition"]
    assert bc.check(_doc(_regular(), c)) == []


def test_a_split_withheld_on_request_is_not_scored_and_is_named_in_the_partition(tmp_path):
    c = bc.derive_configiq(_configiq_dir(tmp_path, withheld_split=("test",)), cid="configiq", label="L", note="N", meta=META)
    assert c["counts"]["scored"] == 10 and c["counts"]["withheld"] == 4 and c["accuracy_by_grade"]["G3"]["ttft"]["n"] == 10
    assert "local experiment" in c["partition"] and "test partition is withheld" in c["partition"]
    assert bc.check(_doc(_regular(), c)) == []


def test_configiq_card_withholds_the_named_figure_and_lists_no_refusal(tmp_path):
    """The card is the rows, the rows scored, the partition and one plain line: no refusal is listed, and a withheld statistic is
    absent as a number and present as its reason (a rule fixed on the data's clarity)."""
    c = bc.derive_configiq(_configiq_dir(tmp_path), cid="configiq", label="L", note="N", meta=META,
                           withheld_figures={"ttft": "awaits the definition"}, plain_line="the rest wait",
                           model_gaps={"m/b": "ours"})
    assert c["refusals"] == []
    assert set(c["accuracy_by_grade"]["G3"]) == {"tpot", "itl"}
    assert c["figure_notes"] == {"ttft": "awaits the definition"}
    assert c["plain_line"] == "the rest wait" and "anchor-only" in c["partition"]
    assert c["counts"]["scored"] == 14 and c["counts"]["points"] == 16
    by = {m["model"]: m for m in c["by_model"]}
    assert (by["m/a"]["scored"], by["m/b"]["scored"]) == (11, 3)  # the four test-split rows are m/a's, scored like the rest
    assert by["m/b"]["gap"] == "ours" and by["m/a"]["gap"] is None
    assert "ttft" not in by["m/a"]["accuracy"] and by["m/a"]["accuracy"]["itl"]["mape"] != bc.TOO_FEW  # 11 points: over the minimum
    assert not any("ttft" in json.dumps(g) for g in c["accuracy_by_grade"].values())


def test_one_off_refusal_reasons_are_one_row_per_code_and_keep_their_count(tmp_path):
    d = contract(tmp_path, [1.0] * 10)
    reasons = [("field_not_modelled", "vendor_specific_kernel_setting")] * 3 + [("field_not_modelled", "another_one_off_flag")] * 2 \
        + [("field_not_modelled", "moe_runner_backend")] * bc.MIN_NAMED_POINTS + [("value_not_recorded", "launch_command")] * 2
    jl(d / "not_scored.jsonl", [{"g5_reason": {"code": c, "subject": s}} for c, s in reasons])
    c = derive(d)
    assert c["counts"]["refused"] == len(reasons) == sum(r["points"] for r in c["refusals"])
    assert c["refusals"] == [{"code": "field_not_modelled", "subject": "moe_runner_backend", "points": bc.MIN_NAMED_POINTS},
                             {"code": "field_not_modelled", "subject": bc.OTHER_SETTINGS, "points": 5},
                             {"code": "value_not_recorded", "subject": bc.OTHER_SETTINGS, "points": 2}]


def test_the_regular_card_says_its_sglang_points_are_not_the_sglang_cards(tmp_path):
    before = _build(tmp_path)
    assert all("note" not in e for e in before["classes"][0]["engines"])  # no SGLang class: nothing to point at
    (tmp_path / "supp" / "sglang.json").write_text(json.dumps({**derive(contract(tmp_path, [1.0] * 12)), "id": "sglang", "kind": "regular"}))
    after = bc.build(tmp_path / "summary.json", tmp_path / "supp", "t")
    notes = {e["engine"]: e.get("note") for e in after["classes"][0]["engines"]}
    assert notes["vllm"] is None and "not added here" in notes["sglang"]
    assert after["classes"][0]["counts"] == before["classes"][0]["counts"]  # the SGLang class changes none of the regular counts


def _regular(points=100, graded=40):
    grades = {"G1": 0, "G2": 0, "G3": 0, "G4": graded, "G5": points - graded}
    return {"id": "inferencex", "label": "R", "kind": "regular", "interim": False, "note": "n",
            "counts": {"points": points, "scored": graded, "refused": points - graded, "failed": 0, "withheld": 0},
            "grades": grades,
            "accuracy_by_grade": {g: {s: {"n": 0, "mape": bc.TOO_FEW, "signed_median": None} for s in ("ttft", "tpot")} for g in bc.GRADED},
            "refusals": [], "substitutions": [], "provenance": {"command": "c", "heads": {}, "pulled_at": "d"}}


def _summary(points=100, graded=40):
    g = {x: {"ttft": {"n": 0, "mape": bc.TOO_FEW}, "tpot": {"n": 0, "mape": bc.TOO_FEW}} for x in bc.GRADED}
    g["G4"] = {"ttft": {"n": graded, "mape": 25.0}, "tpot": {"n": graded, "mape": 24.0}}
    return {"snapshot_id": "snap", "generated_at": "2026-11-18T00:00:00Z", "provenance": {"pulled_at": "2026-11-16"},
            "coverage": {"points": points, "graded": graded, "not_scored": points - graded, "failed": 0,
                         "by_grade": {"G1": 0, "G2": 0, "G3": 0, "G4": graded, "G5": points - graded},
                         "g5_reasons": {"no_recipe": points - graded},
                         "by_engine": {"vllm": {"points": 60, "graded": graded, "grades": {"G4": graded, "G5": 20}},
                                       "sglang": {"points": 40, "graded": 0, "grades": {"G5": 40}}}},
            "headline": {"grades": g}}


def _build(tmp_path, supplemental_points=None):
    sdir = tmp_path / "supp"
    sdir.mkdir(exist_ok=True)
    (tmp_path / "summary.json").write_text(json.dumps(_summary()))
    if supplemental_points is not None:
        (sdir / "inferencex-reconstructed.json").write_text(json.dumps(derive(contract(tmp_path, supplemental_points))))
    return bc.build(tmp_path / "summary.json", sdir, "2026-11-18T00:00:00Z")


def test_the_reconstructed_class_never_changes_the_regular_counts(tmp_path):
    without = _build(tmp_path)
    with_it = _build(tmp_path, [1.0] * 12)
    assert [c["id"] for c in with_it["classes"]] == ["inferencex", "inferencex-reconstructed"]
    assert with_it["classes"][0] == without["classes"][0]
    assert with_it["classes"][0]["counts"]["scored"] == 40 and with_it["classes"][1]["counts"]["scored"] == 12
    assert [e["engine"] for e in with_it["classes"][0]["engines"]] == ["sglang", "vllm"]


def test_an_unknown_supplemental_file_is_refused_by_name(tmp_path):
    _build(tmp_path)
    (tmp_path / "supp" / "mystery.json").write_text("{}")
    with pytest.raises(bc.ClassesError, match="mystery"):
        bc.build(tmp_path / "summary.json", tmp_path / "supp", "t")


def test_a_derived_file_without_its_provenance_is_refused(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"command": "x"}))
    with pytest.raises(bc.ClassesError, match="heads"):
        bc._meta(str(p))


@pytest.mark.parametrize("mutate,expect", [
    (lambda c: c["grades"].update(G3=1, G4=11), "never better than G4"),
    (lambda c: c["counts"].update(points=99), "points 99"),
    (lambda c: c["accuracy_by_grade"]["G4"]["ttft"].update(mape=5.0, n=3), "COV-11"),
    (lambda c: c.update(kind="mystery"), "kind"),
])
def test_check_names_what_is_wrong(tmp_path, mutate, expect):
    good = derive(contract(tmp_path, [1.0] * 12))
    mutate(good)
    assert any(expect in p for p in bc.check(_doc(_regular(), good)))


def test_the_committed_classes_agree_with_the_committed_summary():
    """The nightly rebuilds both; a classes.json that disagrees with the summary beside it is a build that was skipped."""
    root = HERE.parent / "data" / "latest"
    classes, summary = json.loads((root / "classes.json").read_text()), json.loads((root / "summary.json").read_text())
    assert bc.check(classes) == []
    assert classes["snapshot_id"] == summary["snapshot_id"]
    reg = classes["classes"][0]
    assert reg["counts"]["scored"] == summary["coverage"]["graded"] and reg["counts"]["points"] == summary["coverage"]["points"]
    assert reg["grades"] == {g: summary["coverage"]["by_grade"][g] for g in bc.GRADES}


def test_a_provisional_class_is_never_graded_above_g3(tmp_path):
    """configiq's points are provisional (COV-7): a G1 or G2 among them is a build that skipped the cap, and check says so."""
    c = bc.derive_configiq(_configiq_dir(tmp_path), cid="configiq", label="L", note="N", meta=META)
    assert bc.check(_doc(_regular(), c)) == []
    c["grades"].update(G1=2, G3=c["grades"]["G3"] - 2)  # the same number of scored points, two of them above the cap
    assert any("capped at G3" in p for p in bc.check(_doc(_regular(), c)))


def test_itl_error_counts_only_points_that_stream_one_token_per_chunk(tmp_path):
    """Measured ITL is comparable with the simulator's per-token ITL only when it sits within 15 percent of the measured TPOT; a point that
    streamed several tokens per chunk is counted apart, not scored. Eleven comparable points err by +10 percent, two stream in chunks."""
    d = contract(tmp_path, [0.0] * 13)
    itl, points = {}, []
    for i in range(13):
        chunked = i >= 11
        measured_itl, measured_tpot = (0.040, 0.010) if chunked else (0.010, 0.0105)  # seconds
        points.append({"point_id": f"p{i}", "measurements": [{"metrics": {"mean_itl": measured_itl, "mean_tpot": measured_tpot}}]})
        itl[f"p{i}"] = {"itl_mean_ms": measured_itl * 1000 * 1.10}
    (tmp_path / "itl.json").write_text(json.dumps(itl))
    (tmp_path / "manifest.json").write_text(json.dumps({"points": points}))
    c = derive(d, itl_json=tmp_path / "itl.json", manifest=tmp_path / "manifest.json")
    f = c["accuracy_by_grade"]["G4"]["itl"]
    assert f["n"] == 11 and f["mape"] == pytest.approx(10.0) and f["signed_median"] == pytest.approx(10.0)
    assert c["itl_streamed_in_chunks_left_out"] == 2
    assert "itl" not in derive(d)["accuracy_by_grade"]["G4"]  # without the inputs a class has no ITL figure, not an invented one
