"""The documentation under docs/ stays whole and current: every relative link resolves, every page is
reachable from docs/README.md, the generated pages are what their generators write, and the numbers the
pages state about the baseline are the committed baseline's."""
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DOCS = ROOT / "docs"
SKIP_DIRS = {"mockups", "screenshots"}
LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)\)")


def pages():
    return [p for p in sorted(DOCS.rglob("*.md")) if not SKIP_DIRS & set(p.relative_to(DOCS).parts)]


def local_links(page: Path):
    for target in LINK.findall(page.read_text()):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        yield target.split("#")[0], target


def test_every_relative_link_resolves():
    bad = []
    for page in pages():
        for path, raw in local_links(page):
            if path and not (page.parent / path).resolve().exists():
                bad.append(f"{page.relative_to(ROOT)}: {raw}")
    assert not bad, bad


def test_every_page_is_reachable_from_the_readme():
    seen, todo = set(), [DOCS / "README.md"]
    while todo:
        page = todo.pop()
        if page in seen or page.suffix != ".md" or not page.exists():
            continue
        seen.add(page)
        todo += [(page.parent / path).resolve() for path, _ in local_links(page) if path]
    unreachable = [str(p.relative_to(ROOT)) for p in pages() if p.resolve() not in seen]
    assert not unreachable, unreachable


def test_the_pages_the_readme_promises_exist():
    for name in ("overview", "scoring-pipeline", "closeness-grades", "grades", "coverage-accounting", "reproducing",
                 "before-after", "disaggregation", "limits", "coefficients"):
        assert (DOCS / f"{name}.md").is_file(), name
    for name in ("evaluation-protocol", "evaluation-log"):
        assert (DOCS / "m2" / f"{name}.md").is_file(), name


def test_the_generated_grade_page_is_current():
    r = subprocess.run([sys.executable, str(ROOT / "orchestrator" / "ingest" / "gen_grade_doc.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_the_reproducing_page_states_the_committed_baselines_hashes():
    base = DOCS / "m2" / "baseline-v0.16.0"
    prov = json.loads((base / "contract" / "provenance.json").read_text())
    table = json.loads((base / "table.json").read_text())
    text = (DOCS / "reproducing.md").read_text()
    for v in (prov["harness_commit"], prov["pull_manifest_sha256"], prov["units"]["sha256"], prov["fields_sha256"],
              table["identity"]["point_set_sha256"], prov["blis"]["commit_sha"]):
        assert v in text, v
    assert str(table["identity"]["points"]) in text


def test_every_harness_commit_a_run_page_states_is_the_one_its_contract_records():
    """G11. The README and table of a committed run name the harness commit that scored it; the
    machine record is its contract/provenance.json."""
    for run in sorted((DOCS / "m2").iterdir()):
        prov_path = run / "contract" / "provenance.json"
        if not prov_path.exists():
            continue
        commit = json.loads(prov_path.read_text())["harness_commit"]
        for name in ("README.md", "table.md", "table.json", "preliminary-after-run.md"):
            path = run / name
            if not path.exists():
                continue
            text = path.read_text()
            stated = set(re.findall(r'"harness_commit": "([0-9a-f]{40})"', text))
            for line in text.splitlines():
                if re.search(r"harness commit|^\| Harness \|", line, re.I):
                    stated |= set(re.findall(r"`([0-9a-f]{7,40})`", line))
            assert all(commit.startswith(s) for s in stated), (path, stated, commit)


def test_the_series_classes_page_does_not_call_a_fetched_label_unfetched():
    """dynamo-vllm's engine is vLLM, so engines.scored() fetches it; only its router makes it G5."""
    text = (DOCS / "m2" / "series-classes.md").read_text()
    for line in text.splitlines():
        if line.startswith("| dynamo-vllm |") or line.startswith("| vllm"):
            assert "(no fetch)" not in line, line


def test_the_evaluation_protocol_states_the_constants_and_the_split_sizes():
    sys.path.insert(0, str(HERE))
    import split as sp
    text = (DOCS / "m2" / "evaluation-protocol.md").read_text()
    for v in (sp.SALT, sp.FREEZE_DATE, "60", "20"):
        assert v in text
    table = json.loads((DOCS / "m2" / "baseline-v0.16.0" / "table.json").read_text())
    kinds = table["development_split"]["kinds"]
    for k in ("train", "validation", "test"):
        assert f"| {k} | {kinds[k]['points']} |" in text, k


def test_the_log_is_a_table_that_compare_py_can_append_to():
    text = (DOCS / "m2" / "evaluation-log.md").read_text()
    assert text.rstrip().splitlines()[-1].startswith("|---")       # the header is last: rows append below it
    sys.path.insert(0, str(HERE))
    import compare as c
    assert "| Date | Commit | Estimator | Split | Points | Scored |" in text and "| Date | Commit | Estimator | Split | Points | Scored |" in c.LOG_HEADER
