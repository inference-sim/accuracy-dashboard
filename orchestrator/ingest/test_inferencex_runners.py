"""Tests for the InferenceX runner table (inferencex_runners.py) and its generator
(orchestrator/gen_inferencex_runners.py)."""
import copy
import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import gen_inferencex_runners as gen  # noqa: E402
import grade  # noqa: E402
import inferencex_runners as ir  # noqa: E402

T = ir.load()
FIRST = "303669b0"      # the first version of the committed table that records node sizes
FIRST_DATE = "2026-07-02"


def _res(label, day, launch=None, fixes=False, table=T):
    return ir.resolve(table, label, run_date=day, launch_size=launch, fixes_packaging=fixes)


# ------------------------------------------------------------------ the committed table

def test_the_committed_table_loads_and_names_the_commits_it_was_read_from():
    assert [v.commit[:8] for v in T.versions] == ["303669b0", "e9fc9880", "5d06e10c", "4a63bf50"]
    assert [v.records_node_sizes for v in T.versions] == [True, False, True, True]
    assert T.versions[0].date == FIRST_DATE


def test_every_record_names_the_line_of_its_gpus_per_node():
    for name, lab in T.labels.items():
        for commit, rec in lab.records.items():
            for c in rec.clusters:
                if c.gpus_per_node is not None:
                    assert c.source.startswith(next(v.path for v in T.versions if v.commit == commit) + ":"), (name, c)


def test_the_table_is_read_strictly():
    doc = json.loads(ir.DATA.read_text())
    for mutate, why in [
        (lambda d: d.update(extra=1), "unknown key"),
        (lambda d: d["versions"][0].update(commit="303669b0"), "short hash"),
        (lambda d: d["labels"]["mi355x"].update(stable=False), "stable disagrees with the records"),
        (lambda d: d["labels"]["mi355x"]["records"].popitem(), "a record missing"),
        (lambda d: d["labels"]["mi355x"]["first_recorded"].update(date="2026-01-01"), "first_recorded disagrees"),
        (lambda d: d["labels"]["gb200"]["records"][d["versions"][0]["commit"]].update(gpus_per_node=0), "size 0"),
    ]:
        bad = copy.deepcopy(doc)
        mutate(bad)
        with pytest.raises(ir.TableError):
            ir.parse(bad)


# ------------------------------------------------------------------ the stability check

def _v(commit, day, sizes=True):
    return ir.Version(commit * 40 if len(commit) == 1 else commit, day, "runners.yaml", sizes)


def _rec(size, *clusters, problem=None):
    return ir.Record(size, problem, tuple(ir.Cluster(c, size, "runners.yaml:1") for c in clusters))


def test_the_stability_check_flags_a_changed_size():
    a, b = _v("a", "2026-07-02"), _v("b", "2026-09-27")
    ok, problems, first = ir.stability([a, b], {a.commit: _rec(8, "x"), b.commit: _rec(8, "x")})
    assert ok and problems == [] and first == a
    ok, problems, first = ir.stability([a, b], {a.commit: _rec(8, "x"), b.commit: _rec(4, "x")})
    assert not ok and first == a and len(problems) == 1 and "4 GPUs per node" in problems[0]


def test_the_stability_check_flags_a_changed_cluster_and_a_missing_or_ambiguous_label():
    a, b = _v("a", "2026-07-02"), _v("b", "2026-09-27")
    ok, problems, _ = ir.stability([a, b], {a.commit: _rec(8, "x"), b.commit: _rec(8, "y")})
    assert not ok and "on y where" in problems[0]
    gone = ir.Record(None, "label not in runners.yaml", ())
    ok, problems, first = ir.stability([a, b], {a.commit: _rec(8, "x"), b.commit: gone})
    assert not ok and "label not in runners.yaml" in problems[0]
    ok, _, first = ir.stability([a, b], {a.commit: gone, b.commit: gone})
    assert not ok and first is None


def test_the_stability_result_for_the_committed_table():
    stable = sorted(n for n, lab in T.labels.items() if lab.stable)
    assert stable == ["gb200", "mi355x"]
    assert T.labels["gb300"].first_recorded.commit.startswith("5d06e10c") and not T.labels["gb300"].stable
    assert T.labels["b200"].first_recorded is None
    for n in ("rtx6000pro", "vr200"):
        assert not T.labels[n].stable and T.labels[n].first_recorded is None


# ------------------------------------------------------------------ the node size of a row

def test_a_launch_configs_size_is_used_and_named():
    r = _res("mi355x", "2026-10-01", launch=8)
    assert (r.gpus_per_node, r.provenance, r.substitution, r.reason) == (8, "cluster.gpus_per_node: launch_config", None, None)


def test_a_row_with_only_a_table_size_uses_it_and_names_the_commit():
    r = _res("mi355x", "2026-10-01")
    assert r.gpus_per_node == 8 and r.substitution is None and r.reason is None
    assert r.provenance == "cluster.gpus_per_node: InferenceX runners.yaml at 5d06e10c"
    r = _res("mi355x", "2026-11-06")
    assert r.provenance == "cluster.gpus_per_node: InferenceX runners.yaml at 4a63bf50"
    assert _res("mi355x", FIRST_DATE).provenance == "cluster.gpus_per_node: InferenceX runners.yaml at 303669b0"


def test_a_launch_size_that_differs_from_the_table_is_a_value_conflict():
    r = _res("mi355x", "2026-10-01", launch=4)
    assert r.reason == {"code": "value_conflict", "subject": "cluster.gpus_per_node"} and r.gpus_per_node is None


def test_a_label_with_no_runner_entry_stays_value_not_recorded():
    for label in ("rtx6000pro", "vr200", "b200"):
        r = _res(label, "2026-10-01")
        assert r.reason == {"code": "value_not_recorded", "subject": "cluster.gpus_per_node"}, label
    assert _res("vr200", "2026-10-01", launch=8).gpus_per_node == 8


def test_a_row_before_the_first_record_takes_it_as_a_later_record():
    r = _res("mi355x", "2026-06-15")
    assert r.gpus_per_node == 8 and r.reason is None
    assert r.substitution == {"kind": "later_record", "subject": "cluster.gpus_per_node",
                              "detail": "taken from InferenceX runners.yaml at 303669b0, recorded after the run "
                                        "(303669b0 of 2026-07-02)"}
    assert r.provenance == "cluster.gpus_per_node: InferenceX runners.yaml at 303669b0"
    assert _res("mi355x", "2026-07-01T23:00:00Z").substitution is not None
    assert _res("mi355x", FIRST_DATE).substitution is None


def test_a_launch_size_before_the_first_record_is_not_a_substitution_and_is_not_compared():
    r = _res("mi355x", "2026-06-15", launch=4)
    assert r.gpus_per_node == 4 and r.substitution is None and r.reason is None


def test_an_unstable_label_before_its_first_record_stays_value_not_recorded():
    unstable = dataclasses.replace(T.labels["mi355x"], stable=False, problems=("x: changed",))
    table = ir.Table(T.versions, {**T.labels, "mi355x": unstable})
    r = _res("mi355x", "2026-06-15", table=table)
    assert r.reason == {"code": "value_not_recorded", "subject": "cluster.gpus_per_node"} and r.substitution is None
    # From its first record on, the record in force is used.
    assert _res("mi355x", "2026-10-01", table=table).gpus_per_node == 8


def test_a_chip_whose_catalog_entry_fixes_packaging_states_no_node_size():
    for label in ("gb200", "gb300"):
        assert _res(label, "2026-10-01", fixes=True) == ir.NodeSize()
        assert _res(label, "2026-06-15", launch=4, fixes=True) == ir.NodeSize()


def test_later_record_is_a_g2_kind():
    assert "later_record" in grade.G2_KINDS
    out = grade.grade(engine_version="0.32.0", release=grade.Release("0.32.0", False),
                      substitutions=[_res("mi355x", "2026-06-15").substitution])
    assert out.grade == grade.G2


# ------------------------------------------------------------------ the catalog cross-check

def test_the_tables_sizes_equal_the_catalogs_for_chips_whose_entry_fixes_packaging():
    pk = json.loads((HERE / "testdata" / "catalog_packaging.json").read_text())
    assert pk["chips"]
    for label, chip in pk["chips"].items():
        sizes = {r.gpus_per_node for r in T.labels[label].records.values() if r.gpus_per_node is not None}
        assert sizes == {chip["GPUsPerNode"]}, (label, chip["catalog_entry"], sizes)


# ------------------------------------------------------------------ the generator

RUNNERS = """\
labels:
  mi355x:
    - mi355x-amds_00
  gb200:
    - gb200-nv_00
  cluster:mi355x-amds:
    - mi355x-amds_00
  cluster:gb200-nv:
    - gb200-nv_00
clusters:
  mi355x-amds:
    gpus-per-node: {mi}
    arch: x86_64
  gb200-nv:
    gpus-per-node: 4
    arch: arm64
"""
OLD = "mi355x:\n  - mi355x-amds_00\n"


def _git(d, *a):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
           "GIT_AUTHOR_DATE": "2026-08-01T12:00:00+00:00", "GIT_COMMITTER_DATE": "2026-08-01T12:00:00+00:00"}
    return subprocess.run(["git", "-C", str(d), "-c", "commit.gpgsign=false", *a], check=True,
                          capture_output=True, text=True, env=env).stdout.strip()


def _ix(tmp_path, mi_later=8):
    d = tmp_path / "ix"
    d.mkdir()
    _git(d, "init", "-q")
    (d / "runners.yaml").write_text(OLD)
    _git(d, "add", "."), _git(d, "commit", "-qm", "before node sizes")
    first = _git(d, "rev-parse", "HEAD")
    (d / "runners.yaml").write_text(RUNNERS.format(mi=8))
    _git(d, "commit", "-qam", "node sizes")
    second = _git(d, "rev-parse", "HEAD")
    (d / "runners.yaml").write_text(RUNNERS.format(mi=mi_later))
    _git(d, "commit", "-q", "--allow-empty", "-am", "later")
    return d, first, second, _git(d, "rev-parse", "HEAD")


def _args(d, *commits, out):
    return ["--ix", str(d), "--out", str(out), *[a for c in commits for a in ("--version", f"{c}:runners.yaml")]]


def test_the_generator_writes_a_table_the_loader_reads_with_the_lines_of_the_sizes(tmp_path):
    d, c0, c1, c2 = _ix(tmp_path)
    out = tmp_path / "t.json"
    assert gen.main(_args(d, c0, c1, c2, out=out)) == 0
    t = ir.load(out)
    assert [v.records_node_sizes for v in t.versions] == [False, True, True]
    mi = t.labels["mi355x"]
    assert mi.stable and mi.first_recorded.commit == c1
    cl = mi.records[c1].clusters[0]
    assert (cl.id, cl.gpus_per_node, cl.source) == ("mi355x-amds", 8, "runners.yaml:12")
    assert t.labels["gb200"].records[c2].clusters[0].source == "runners.yaml:15"


def test_the_generator_check_passes_on_the_file_it_wrote_and_fails_on_a_changed_one(tmp_path, capsys):
    d, c0, c1, c2 = _ix(tmp_path)
    out = tmp_path / "t.json"
    assert gen.main(_args(d, c0, c1, c2, out=out)) == 0
    assert gen.main(_args(d, c0, c1, c2, out=out) + ["--check"]) == 0
    doc = json.loads(out.read_text())
    doc["labels"]["mi355x"]["records"][c1]["clusters"][0]["gpus_per_node"] = 4
    out.write_text(gen.render(doc))
    assert gen.main(_args(d, c0, c1, c2, out=out) + ["--check"]) == 1
    assert "differs" in capsys.readouterr().err


def test_the_generator_marks_a_label_whose_size_changed_unstable_and_prints_it(tmp_path, capsys):
    d, c0, c1, c2 = _ix(tmp_path, mi_later=4)
    out = tmp_path / "t.json"
    assert gen.main(_args(d, c0, c1, c2, out=out)) == 0
    t = ir.load(out)
    assert not t.labels["mi355x"].stable and t.labels["gb200"].stable
    printed = capsys.readouterr().out
    assert "STABILITY CHECK" in printed and "UNSTABLE" in printed and "4 GPUs per node" in printed


def test_the_generator_refuses_a_version_it_cannot_read(tmp_path, capsys):
    d, c0, c1, c2 = _ix(tmp_path)
    assert gen.main(["--ix", str(d), "--out", str(tmp_path / "t.json"), "--version", "nope"]) == 2
    assert gen.main(["--ix", str(d), "--out", str(tmp_path / "t.json"), "--version", f"{c0}:runners.yaml"]) == 2
    assert "error" in capsys.readouterr().err
