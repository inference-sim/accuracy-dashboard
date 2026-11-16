"""Tests of the ported-function comparison (ported_changes.py), on two small git repositories built here."""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ported_changes as pc  # noqa: E402

V32 = '''def kept(a):
    return a + 1


def moved(b):
    return b * 2


class Scheduler:
    def schedule(self, x):
        return x - 1
'''


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                    "-c", "tag.gpgsign=false", *args], check=True, capture_output=True)


def upstream(tmp: Path) -> Path:
    """A vLLM-like repository: v0.31.0, where schedule() differs and the other two functions are reformatted or
    moved, and v0.32.0."""
    repo = tmp / "vllm"
    (repo / "vllm" / "core").mkdir(parents=True)
    git(repo, "init", "-q")
    old = ('def moved(b):\n    return b*2\n\n\ndef kept(a):\n    return (a + 1)\n\n\n'
           'class Scheduler:\n    def schedule(self, x):\n        return x - 2\n')
    for tag, text in (("v0.31.0", old), ("v0.32.0", V32)):
        (repo / "vllm" / "core" / "sched.py").write_text(text)
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", tag)
        git(repo, "tag", tag)
    return repo


def port(tmp: Path, commit: str) -> Path:
    repo = tmp / "port"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "sched.go").write_text(
        f"// SPDX-License-Identifier: Apache-2.0\n// Derived from vllm/core/sched.py at vLLM v0.32.0 ({commit}):\n"
        "// kept (:1-2), moved (:5-6) and Scheduler.schedule (:10-11).\n\npackage sched\n")
    (repo / "other.go").write_text("// original to this repository\n\npackage sched\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "port")
    return repo


def test_a_changed_ported_function_is_named_and_a_reformatted_or_moved_one_is_not(tmp_path):
    up = upstream(tmp_path)
    commit = subprocess.run(["git", "-C", str(up), "rev-parse", "v0.32.0"], capture_output=True, text=True).stdout.strip()
    doc = pc.generate(port(tmp_path, commit), up, ["0.31.0"])
    assert doc["engine_release"] == "0.32.0"
    assert [c["function"] for c in doc["cited"]] == ["Scheduler.schedule", "kept", "moved"]
    assert doc["releases"]["0.31.0"]["changed"] == ["vllm/core/sched.py:Scheduler.schedule"]
    assert sorted(doc["releases"]["0.31.0"]["unchanged"]) == ["vllm/core/sched.py:kept", "vllm/core/sched.py:moved"]
    assert pc.changed_functions(doc, "0.31.0") == ["vllm/core/sched.py:Scheduler.schedule"]
    assert pc.changed_functions(doc, "0.30.0") is None


def test_check_fails_when_the_file_is_not_what_the_checkouts_give(tmp_path):
    up = upstream(tmp_path)
    commit = subprocess.run(["git", "-C", str(up), "rev-parse", "v0.32.0"], capture_output=True, text=True).stdout.strip()
    p = port(tmp_path, commit)
    out = tmp_path / "ported.json"
    assert pc.main(["gen", "--port", str(p), "--vllm", str(up), "--release", "0.31.0", "--out", str(out)]) == 0
    assert pc.main(["check", "--port", str(p), "--vllm", str(up), str(out)]) == 0
    out.write_text(out.read_text().replace('"changed": [\n', '"changed": [\n    "vllm/core/sched.py:kept",\n', 1))
    assert pc.main(["check", "--port", str(p), "--vllm", str(up), str(out)]) == 1


def test_a_header_range_in_another_file_is_read_against_that_file():
    prov, ranges = pc.cited_ranges(
        "// Derived from vllm/a/b.py at vLLM v0.32.0 (" + "0" * 40 + "):\n"
        "// f (:1-2), with g (vllm/a/c.py:3-4) and :5-6, then b.py:7-8, 9-10 and other.py:11-12.\npackage x\n")
    assert prov == ("vllm/a/b.py", "v0.32.0", "0" * 40)
    assert ranges == [("vllm/a/b.py", 1, 2), ("vllm/a/c.py", 3, 4), ("vllm/a/c.py", 5, 6),
                      ("vllm/a/b.py", 7, 8), ("vllm/a/b.py", 9, 10)]
