"""Commit distance (design §11.3): the provider that reads upgrade reports and an engine checkout, and the scorer's
grade of a run on another upstream commit."""
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build as bld  # noqa: E402
import commit_distance as cd  # noqa: E402
import score as sc  # noqa: E402

RUN, SCORED, OTHER = "a" * 40, "c" * 40, "d" * 40


def report(**over):
    r = {"from": {"commit": RUN}, "to": {"commit": SCORED},
         "surface": {"added": [], "removed": []},
         "fields": {"added": [], "removed": [], "status_changed": []},
         "source": {"ported_files_changed": [], "code_paths": [{"path": "host", "changed": [], "added": [], "removed": []}],
                    "kernel_impls": {"added": [], "removed": [], "changed": []}}}
    for k, v in over.items():
        if k in ("surface", "fields"):
            r[k] = {**r[k], **v}
        else:
            r["source"] = {**r["source"], k: v}
    return r


CASES = [
    ("nothing_differs", report(), []),
    ("surface_item_added", report(surface={"added": [{"id": "flag.x"}]}), ["surface:flag.x"]),
    ("surface_item_removed", report(surface={"removed": [{"id": "flag.y"}]}), ["surface:flag.y"]),
    ("field_status_changed", report(fields={"status_changed": [{"name": "block_size"}]}), ["field:block_size"]),
    ("ported_file_changed", report(ported_files_changed=[{"upstream": "vllm/v1/a.py", "files": ["a.go"]}]),
     ["file:vllm/v1/a.py"]),
    ("function_hash_changed", report(code_paths=[{"path": "host", "changed": ["f"], "added": [], "removed": []}]),
     ["function:host:f"]),
    ("kernel_impl_changed", report(kernel_impls={"added": [], "removed": [], "changed": [["gemm", "s", "l", "v", "sm90"]]}),
     ["kernel_impl:gemm/s/l/v/sm90"]),
    ("code_paths_not_derived", report(code_paths={"error": "refused"}), None),
]


@pytest.mark.parametrize("name, rep, want", CASES, ids=[c[0] for c in CASES])
def test_a_report_says_what_differs_between_its_two_commits(name, rep, want):
    assert cd.changes(rep) == want


def test_a_pair_has_a_diff_only_when_a_report_names_that_pair_in_either_order():
    d = cd.Distance([report(surface={"added": [{"id": "flag.x"}]})])
    assert d(RUN, SCORED) == ["surface:flag.x"] and d(SCORED, RUN) == ["surface:flag.x"]
    assert d(OTHER, SCORED) is None and d(RUN, OTHER) is None


def test_a_report_without_a_commit_is_refused_not_ignored():
    with pytest.raises(cd.DistanceError):
        cd.Distance([{"from": {"commit": "abc"}, "to": {"commit": SCORED}}])


def _git(repo, *args):
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env, check=True)
    return r.stdout.strip()


@pytest.fixture
def checkout(tmp_path):
    """base -(v1)- x1 - x2 (main); base - y1 (side, tagged v0.9-side)."""
    _git(tmp_path, "init", "-q", "-b", "main")
    commits = {}

    def commit(name):
        (tmp_path / "f").write_text(name)
        _git(tmp_path, "add", "f")
        _git(tmp_path, "commit", "-q", "-m", name)
        commits[name] = _git(tmp_path, "rev-parse", "HEAD")

    commit("base")
    _git(tmp_path, "tag", "v1")
    commit("x1")
    commit("x2")
    _git(tmp_path, "tag", "v2")
    _git(tmp_path, "checkout", "-q", "-b", "side", "v1")
    commit("y1")
    _git(tmp_path, "tag", "v1-side")
    return tmp_path, commits


def test_the_distance_is_the_counts_from_the_merge_base_to_each_commit_and_the_tags_between(checkout):
    repo, c = checkout
    rec = cd.Distance(checkout=repo).record(c["x2"], c["y1"])
    assert rec == {"run_commit": c["x2"], "scored_commit": c["y1"], "merge_base": c["base"],
                   "run_commits": 2, "scored_commits": 1, "tags": ["v1-side", "v2"]}
    assert cd.Distance(checkout=repo).record(c["y1"], c["x2"])["run_commits"] == 1


@pytest.mark.parametrize("use_checkout, commit", [(False, "x1"), (True, "missing")])
def test_no_distance_is_recorded_without_a_checkout_or_with_a_commit_it_lacks(checkout, use_checkout, commit):
    repo, c = checkout
    d = cd.Distance(checkout=repo if use_checkout else None)
    assert d.record(c.get(commit, "f" * 40), c["y1"]) is None


def _outcome(*, build, engine_commit, subs=()):
    o = sc.Outcome(point_id="p" * 64, identity={}, row={"image": build["image"]}, reasons=[], build=build,
                   banner=None, subs=list(subs), engine_commit=engine_commit)
    o.fidelity = {"build": build, "args": [], "resolved": []}
    o.csv_row = [None] * 12
    return o


IMG = "vllm/vllm-openai:nightly-xyz"
BUILD = {"image": IMG, "commit": RUN, "match": "exact"}
KINDS = lambda o: {s["kind"] for s in o.fidelity["substitutions"]}  # noqa: E731

GRADE_CASES = [
    # name, build, scored commit, distance provider, grade, kinds present among the substitutions
    ("same_commit_is_not_asked", BUILD, RUN, "never", "G2", set()),
    ("another_commit_nothing_ported_differs", BUILD, SCORED, [], "G3", {"other_release"}),
    ("another_commit_a_ported_function_differs", BUILD, SCORED, ["function:host:f"], "G4", {"changed_functions"}),
    ("another_commit_no_published_diff", BUILD, SCORED, None, "G4", {"ported_functions_unpublished"}),
    ("outside_the_old_bound_is_still_by_commit", {**BUILD, "why": "outside_distance", "match": "estimated"},
     SCORED, [], "G3", {"other_release"}),
    ("custom_build_is_g4", {**BUILD, "why": "custom_build", "match": "estimated"}, SCORED, [], "G4",
     {"nightly_or_custom"}),
    ("no_recorded_commit_is_g4", {"image": IMG, "commit": None, "match": "estimated", "why": "commit_unresolvable"},
     SCORED, [], "G4", {"nightly_or_custom"}),
]


@pytest.mark.parametrize("name, build, scored, diff, grade, kinds", GRADE_CASES, ids=[c[0] for c in GRADE_CASES])
def test_a_run_on_another_commit_is_graded_by_its_commit_distance(name, build, scored, diff, grade, kinds):
    def distance(run, sc_):
        if diff == "never":
            raise AssertionError("asked about the same commit")
        return diff

    class Provider:
        __call__ = staticmethod(distance)

        def record(self, run, scored_):
            return None

    o = _outcome(build=build, engine_commit=scored)
    sc.grade_outcome(o, "0.33.0", None, Provider())
    assert o.fidelity["grade"] == grade
    got = KINDS(o)
    assert kinds <= got
    assert (grade == "G2") == ("other_release" not in got and "nightly_or_custom" not in got)


def test_the_commit_distance_counts_are_recorded_on_a_point_graded_by_it():
    rec = {"run_commit": RUN, "scored_commit": SCORED, "merge_base": "b" * 40, "run_commits": 3, "scored_commits": 5,
           "tags": ["v0.33.0"]}

    class Provider:
        def __call__(self, run, scored):
            return []

        def record(self, run, scored):
            return rec

    o = _outcome(build=BUILD, engine_commit=SCORED)
    sc.grade_outcome(o, "0.33.0", None, Provider())
    assert o.fidelity["grade"] == "G3"
    assert o.fidelity["commit_distance"] == {**rec, "state": "no_ported_change", "ported_changes": 0}


STATE_CASES = [
    # name, build, scored commit, what the provider says differs, state, ported_changes
    ("same_commit", BUILD, RUN, "never", "same", None),
    ("nothing_ported_differs", BUILD, SCORED, [], "no_ported_change", 0),
    ("ported_functions_differ", BUILD, SCORED, ["function:host:f", "file:a.py"], "ported_change", 2),
    ("no_published_diff", BUILD, SCORED, None, "unpublished", None),
    ("outside_the_old_bound_is_by_commit", {**BUILD, "why": "outside_distance", "match": "estimated"}, SCORED, [],
     "no_ported_change", 0),
    ("custom_build", {**BUILD, "why": "custom_build", "match": "estimated"}, SCORED, [], "custom_build", None),
    ("run_commit_unresolvable", {"image": IMG, "commit": None, "match": "estimated", "why": "commit_unresolvable"},
     SCORED, [], "commit_unresolvable", None),
    ("run_commit_in_conflict", {**BUILD, "why": "commit_conflict", "match": "estimated"}, SCORED, [],
     "commit_conflict", None),
]


@pytest.mark.parametrize("name, build, scored, diff, state, n", STATE_CASES, ids=[c[0] for c in STATE_CASES])
def test_every_point_on_a_recorded_engine_commit_is_labelled_by_its_commit_distance_without_a_checkout(
        name, build, scored, diff, state, n):
    """The label is the grade's own reason in one word, so a slice or a funnel can cut by it; it needs no checkout."""
    def distance(run, sc_):
        assert diff != "never", "asked about the same commit"
        return diff

    o = _outcome(build=build, engine_commit=scored)
    sc.grade_outcome(o, "0.33.0", None, distance)
    rec = o.fidelity["commit_distance"]
    assert (rec["state"], rec.get("ported_changes")) == (state, n)
    assert rec["scored_commit"] == scored and rec["run_commit"] == build.get("commit")
    assert rec["state"] in cd.STATES


class Counted:
    """A provider with a checkout: the diff says nothing ported differs, and the counts are the run's and the model's."""
    def __init__(self, run_commits, scored_commits):
        self.n = (run_commits, scored_commits)

    def __call__(self, run, scored):
        return []

    def record(self, run, scored):
        return {"run_commit": run, "scored_commit": scored, "merge_base": "b" * 40, "run_commits": self.n[0],
                "scored_commits": self.n[1], "tags": []}


BOUND = bld.VLLM_MAX_DISTANCE
APART_CASES = [
    # name, engine, run commits, scored commits, state, grade
    ("at_the_bound_is_by_commit", "vllm", BOUND - 5, 5, "no_ported_change", "G3"),
    ("one_past_the_bound", "vllm", BOUND - 5, 6, "outside_distance", "G4"),
    ("counted_on_the_modelled_side", "vllm", 0, BOUND + 1, "outside_distance", "G4"),
    ("sglang_has_no_such_bound", "sglang", BOUND + 500, BOUND + 500, "no_ported_change", "G3"),
]


@pytest.mark.parametrize("name, engine, n_run, n_scored, state, grade", APART_CASES, ids=[c[0] for c in APART_CASES])
def test_a_vllm_run_further_from_the_modelled_commit_than_the_build_bound_is_g4_outside_distance(
        name, engine, n_run, n_scored, state, grade):
    """The bound is build.VLLM_MAX_DISTANCE, applied to the commits that separate the run's commit from the modelled
    one when a checkout counts them; the point is still scored, as G4 nightly_or_custom naming the distance."""
    o = _outcome(build=BUILD, engine_commit=SCORED)
    o.engine = engine
    sc.grade_outcome(o, "0.33.0", None, Counted(n_run, n_scored))
    rec = o.fidelity["commit_distance"]
    assert (rec["state"], o.fidelity["grade"]) == (state, grade)
    assert rec["state"] in cd.STATES
    if state == "outside_distance":
        assert rec["commits_apart"] == n_run + n_scored and rec["max_distance"] == BOUND
        assert "nightly_or_custom" in KINDS(o) and not KINDS(o) & {"other_release", "changed_functions"}
        detail = [s["detail"] for s in o.fidelity["substitutions"] if s["kind"] == "nightly_or_custom"][0]
        assert str(n_run + n_scored) in detail and str(BOUND) in detail
    else:
        assert "commits_apart" not in rec


def test_without_a_checkout_no_commit_count_is_known_so_the_bound_is_not_applied():
    o = _outcome(build=BUILD, engine_commit=SCORED)
    sc.grade_outcome(o, "0.33.0", None, lambda r, s: [])
    assert o.fidelity["commit_distance"]["state"] == "no_ported_change" and o.fidelity["grade"] == "G3"


def test_a_result_that_states_no_commit_has_no_commit_distance_to_record():
    o = _outcome(build={"image": "vllm/vllm-openai:v0.33.0", "commit": RUN, "match": "exact"}, engine_commit=None)
    sc.grade_outcome(o, "0.33.0")
    assert "commit_distance" not in o.fidelity


def test_the_label_agrees_with_the_grade():
    """G1/G2 only on the modelled commit, G3 only when nothing ported differs, G4 for every other state."""
    want = {"same": {"G1", "G2"}, "no_ported_change": {"G3"}}
    for name, build, scored, diff, state, _ in STATE_CASES:
        o = _outcome(build=build, engine_commit=scored)
        sc.grade_outcome(o, "0.33.0", None, lambda r, s, d=diff: d)
        assert o.fidelity["grade"] in want.get(state, {"G4"}), name


def test_a_run_on_the_modelled_commit_runs_the_modelled_release():
    o = _outcome(build=BUILD, engine_commit=RUN)
    sc.grade_outcome(o, "0.33.0")
    assert o.fidelity["run_release"] == "0.33.0" and o.run_release == "0.33.0"


def test_a_result_that_states_no_commit_is_graded_by_release_as_before():
    o = _outcome(build={"image": "vllm/vllm-openai:v0.33.0", "commit": RUN, "match": "exact"}, engine_commit=None)
    o.banner = "0.33.0"
    sc.grade_outcome(o, "0.33.0")
    assert o.fidelity["run_release"] == "0.33.0" and "other_release" not in KINDS(o)


def test_the_harness_passes_the_commit_distance_inputs_to_the_scorer(tmp_path):
    import cli
    base = dict(sim="v0.16.0", units="u", pull="p", out="o", catalog="c", registry="r", corpus_dir="k", fields="f",
                catalog_release="v0.3.0", registry_release="v0.2.0")
    assert "--engine-report" not in cli.harness_command(**base) and "--engine-checkout" not in cli.harness_command(**base)
    cmd = cli.harness_command(**base, engine_reports=["a.json", "b.json"], engine_checkout="vllm")
    assert [cmd[i + 1] for i, x in enumerate(cmd) if x == "--engine-report"] == [str(Path("a.json").resolve()),
                                                                                str(Path("b.json").resolve())]
    assert cmd[cmd.index("--engine-checkout") + 1] == str(Path("vllm").resolve())


def test_an_unreadable_upgrade_report_is_refused_by_name(tmp_path):
    with pytest.raises(cd.DistanceError, match="missing.json"):
        cd.Distance.load([tmp_path / "missing.json"])
