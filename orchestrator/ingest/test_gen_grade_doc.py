"""docs/grades.md is generated from grade.py, and every grade-level fact has prose."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import assess  # noqa: E402
import gen_grade_doc as g  # noqa: E402
import grade as gr  # noqa: E402


def test_prose_covers_exactly_the_members_of_grade_py():
    assert set(g.GRADE_TEXT) == set(gr.GRADES)
    assert set(g.G5_TEXT) == set(gr.G5_CODES)
    assert set(g.KIND_TEXT) == set(gr.G2_KINDS)
    assert set(g.G34_TEXT) == set(gr.G34_KINDS)
    assert set(g.RUN_FAULT_TEXT) == set(assess.RUN_FAULTS)
    assert set(gr.UNCHECKED_KINDS) <= set(gr.G2_KINDS)


def test_the_committed_document_is_what_the_code_writes():
    assert g.DOC.read_text() == g.render(), "run orchestrator/ingest/gen_grade_doc.py"


def test_the_document_names_every_g5_reason_and_unevaluated_condition():
    text = g.DOC.read_text()
    for code in gr.G5_CODES:
        assert f"`{code}`" in text
    for kind in gr.UNCHECKED_KINDS:
        assert f"`{kind}`" in text
    assert gr.NOT_CHECKED_KIND == "unevaluated" and "`unevaluated`" in text


def test_every_named_subject_has_prose_and_is_in_the_document():
    import pd as pdm
    import pd_recipe as pdr
    assert set(g.TOPOLOGY_SUBJECT_TEXT) == set(pdm.TOPOLOGY_SLUGS)
    assert set(g.RECIPE_SLUG_TEXT) == set(pdr.SLUGS)
    text = g.DOC.read_text()
    for slug in (*pdm.TOPOLOGY_SLUGS, *pdr.SLUGS):
        assert f"`{slug}`" in text


def test_every_router_outcome_that_refuses_has_prose():
    import router_table as rtab
    assert set(g.ROUTER_OUTCOME_TEXT) == set(rtab.OUTCOMES) - {rtab.MAPPED}
    for k in g.ROUTER_OUTCOME_TEXT:
        assert f"`{k}`" in g.DOC.read_text()
