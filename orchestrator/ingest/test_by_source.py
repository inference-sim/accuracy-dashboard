"""Coverage by source (COV-7, blis-design#14): sources sum to the totals, provisional points stay out of the
headline, and the breakdown validates against summary v4.

Run: python3 -m pytest orchestrator/ingest/test_by_source.py
"""
import json
import sys
from pathlib import Path

import jsonschema
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import by_source as bs  # noqa: E402

SCHEMA = json.loads((HERE.parent.parent / "schemas" / "summary.v4.json").read_text())


def pt(source, grade, *, provisional=False, failed=False, release="vLLM-0.32.0", chip="B200", model="m", code=None):
    return {"point_id": f"{source}-{grade}-{release}-{chip}-{model}-{code}", "source": source, "engine_release": release,
            "chip": chip, "model": model, "grade": grade, "provisional": provisional, "failed": failed,
            "g5_reason": {"code": code} if code else None}


POINTS = [pt("inferencex", "G2"), pt("inferencex", "G4", chip="H200"),
          pt("inferencex", "G5", code="value_not_recorded"), pt("inferencex", None, failed=True),
          pt("configiq", "G3", provisional=True), pt("configiq", None, provisional=True, release="vLLM-0.28.0"),
          pt("configiq", "G5", chip="MI355X", code="chip_not_modelled"),
          pt("configiq", "G5", model="x", code="not_in_catalog")]
TOTALS = {"points": 4 + 2, "graded": 2, "not_scored": 3, "failed": 1}  # headline: the 2 provisional are left out


def test_provisional_points_are_their_own_band_outside_graded():
    b = bs.by_source(POINTS)
    c = b["configiq"]
    assert (c["points"], c["graded"], c["provisional"], c["not_scored"]) == (4, 0, 2, 2)
    assert c["provisional_grades"]["G3"] == 1 and c["grades"]["G3"] == 0
    assert c["g5_reasons"] == {"chip_not_modelled": 1, "not_in_catalog": 1}
    assert b["inferencex"]["graded"] == 2 and b["inferencex"]["failed"] == 1


def test_each_source_breaks_down_by_release_chip_and_model():
    c = bs.by_source(POINTS)["configiq"]
    assert set(c["by_engine_release"]) == {"vLLM-0.28.0", "vLLM-0.32.0"}
    assert c["by_chip"]["MI355X"]["not_scored"] == 1
    assert c["by_model"]["x"]["points"] == 1


def test_the_breakdown_sums_to_the_totals_and_validates_against_summary_v4():
    b = bs.by_source(POINTS)
    assert bs.check(b, TOTALS) == []
    jsonschema.validate(b, {"$ref": "#/properties/coverage/properties/by_source", **SCHEMA})


def test_a_provisional_point_counted_in_the_headline_is_caught():
    b = bs.by_source(POINTS)
    assert bs.check(b, dict(TOTALS, graded=3))  # a total that counts the provisional G3 as graded
    b["configiq"]["graded"] += 1                # a breakdown that does
    assert any("graded" in p for p in bs.check(b, TOTALS))


@pytest.mark.parametrize("bad", [pt("configiq", "G2", provisional=True), pt("configiq", None),
                                 pt("configiq", "G5"), {**pt("configiq", "G3"), "chip": ""}])
def test_points_the_breakdown_cannot_place_are_refused(bad):
    with pytest.raises(bs.BySourceError):
        bs.by_source([bad])


def test_the_breakdown_does_not_depend_on_input_order():
    assert json.dumps(bs.by_source(POINTS)) == json.dumps(bs.by_source(list(reversed(POINTS))))
