"""dump_lane: the skip key, the publish gate, the lane's merge into the API lane's contract and the night's lane -- on the contract
fixture, with a stand-in scorer, no network and no dump."""
import csv
import io
import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as c  # noqa: E402
import dump_extract as dx  # noqa: E402
import dump_lane as dl  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "testdata" / "contract" / "run-a"
PIN = {"ref": "db-dump/2026-09-28", "extract_sha256": "a" * 64, "sha256sums": "b" * 64}
KEY_ARGS = {"blis_release": "v0.12.0", "harness_commit": "0123456789abcdef0123456789abcdef01234567",
            "catalog_release": "v0.3.0", "registry_release": "v0.2.0"}
KEY = dl.lane_key(pin=PIN, **KEY_ARGS)


def lines(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def put_lines(path, rows):
    path.write_text("".join(c.canonical_dumps(r) + "\n" for r in sorted(rows, key=lambda r: r["point_id"])))


def other_units(src: Path, dst: Path) -> Path:
    """The fixture contract with every point another unit (its benchmark run moved, so its id and its sweep are new)."""
    shutil.copytree(src, dst)
    facets = json.loads((dst / c.FACETS_JSON).read_text())
    new = {}
    for pid, f in facets.items():
        f["identity"]["benchmark_run"] += 1000
        f["sweep_id"] += "-dump"
        new[pid] = c.point_id(f["identity"])
    records = {}
    for name in (c.NOT_SCORED_JSONL, c.FAILED_JSONL):
        records[name] = lines(dst / name)
        for r in records[name]:
            r["identity"]["benchmark_run"] = (r["identity"]["benchmark_run"] or 0) + 1000
            new[r["point_id"]] = r["point_id"] = c.point_id(r["identity"])
    for name in (c.POINTS_CSV, c.FIDELITY_JSONL):
        text = (dst / name).read_text()
        for old, nid in new.items():
            text = text.replace(old, nid)
        (dst / name).write_text(text)
    for name, rows in records.items():
        put_lines(dst / name, rows)
    put_lines(dst / c.FIDELITY_JSONL, lines(dst / c.FIDELITY_JSONL))
    (dst / c.FACETS_JSON).write_text(c.canonical_dumps(dict(sorted((new[p], f) for p, f in facets.items()))) + "\n")
    with open(dst / c.POINTS_CSV, newline="") as fh:
        rows = sorted(csv.DictReader(fh), key=c.points_sort_key)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=c.POINTS_HEADER)
    w.writeheader()
    w.writerows(rows)
    (dst / c.POINTS_CSV).write_text(buf.getvalue())
    return dst


def make_extract(root: Path, units, kind="single_turn"):
    root.mkdir(parents=True)
    pts = [{"point_id": u, "identity": {"benchmark_type": kind}, "files": {}} for u in units]
    (root / "manifest.json").write_text(json.dumps({"pulled_at": "2026-11-01T02:03:04Z", "points": pts}))
    return root


# ---------------------------------------------------------------- the skip key
def test_a_night_with_nothing_changed_reuses_the_last_dump_result():
    lane = {"key": KEY}
    d = dl.decide(lane, dict(KEY))
    assert not d.rerun and "same" in d.reason


@pytest.mark.parametrize("field,value", [
    ("blis_release", "v0.13.0"), ("harness_commit", "f" * 40), ("catalog_release", "v0.4.0"),
    ("registry_release", "v0.3.0"), ("dump_ref", "db-dump/2026-10-31"), ("extract_sha256", "c" * 64)])
def test_a_change_in_any_part_of_the_key_scores_the_lane_again_and_names_it(field, value):
    d = dl.decide({"key": KEY}, {**KEY, field: value})
    assert d.rerun and field in d.reason


def test_the_key_covers_every_input_and_no_other():
    assert set(KEY) == set(dl.KEY_FIELDS)
    assert KEY["dump_ref"] == PIN["ref"] and KEY["extract_sha256"] == PIN["extract_sha256"]


def test_no_last_result_or_a_forced_rerun_scores_the_lane():
    assert dl.decide(None, KEY).rerun
    d = dl.decide({"key": KEY}, KEY, force=True)
    assert d.rerun and "forced" in d.reason
    assert dl.decide({}, KEY).rerun                      # a lane.json without a key is not a result to reuse


# ---------------------------------------------------------------- the publish gate
PROV = {"blis": {"release": "v0.12.0"}, "harness_commit": KEY_ARGS["harness_commit"]}
LANE = {"blis_release": "v0.12.0", "harness_commit": KEY_ARGS["harness_commit"]}


def test_the_gate_passes_two_lanes_of_one_release_and_one_harness_commit():
    assert dl.gate(PROV, LANE) == []


def test_the_gate_refuses_another_release_another_harness_commit_or_both():
    one = dl.gate(PROV, {**LANE, "blis_release": "v0.11.0"})
    assert len(one) == 1 and "v0.12.0" in one[0] and "v0.11.0" in one[0]
    two = dl.gate(PROV, {**LANE, "harness_commit": "9" * 40})
    assert len(two) == 1 and "harness" in two[0]
    assert len(dl.gate(PROV, {"blis_release": "x", "harness_commit": "y"})) == 2
    assert dl.gate({}, LANE) != []                       # a summary that names neither is not one scoring with the lane


# ---------------------------------------------------------------- the lane's contract
def scored_lane(tmp_path) -> Path:
    lane = other_units(FIXTURE, tmp_path / "lane")
    pin_ext = make_extract(tmp_path / "ext", [])
    dl.stamp(lane, KEY, PIN, pin_ext)
    return lane


def test_stamp_marks_every_point_and_the_provenance_and_the_result_stays_a_valid_contract(tmp_path):
    lane = scored_lane(tmp_path)
    assert c.validate_dir(lane) == []
    facets = json.loads((lane / c.FACETS_JSON).read_text())
    assert facets and all((f["source"], f["dump_ref"], f["blis_release"], f["source_revision"])
                          == ("dump", PIN["ref"], "v0.12.0", PIN["ref"]) for f in facets.values())
    prov = json.loads((lane / c.PROVENANCE_JSON).read_text())
    assert prov["dump"] == {"ref": PIN["ref"], "sha256": PIN["sha256sums"], "pulled_at": "2026-11-01T02:03:04Z"}
    rec = json.loads((lane / dl.LANE_JSON).read_text())
    assert rec["key"] == KEY and rec["source"] == "dump" and rec["points"] == prov["points"]
    assert dl.load_result(lane) == rec


def test_a_result_that_is_not_a_valid_contract_is_not_reused(tmp_path):
    lane = scored_lane(tmp_path)
    (lane / c.FIDELITY_JSONL).write_text("")
    assert dl.load_result(lane) is None
    assert dl.load_result(tmp_path / "none") is None


def test_add_lane_puts_both_lanes_in_one_valid_contract_with_the_dump_block(tmp_path):
    lane = scored_lane(tmp_path)
    base = tmp_path / "base"
    shutil.copytree(FIXTURE, base)
    n_base = json.loads((base / c.PROVENANCE_JSON).read_text())["points"]
    n_lane = json.loads((lane / c.PROVENANCE_JSON).read_text())["points"]
    dl.add_lane(base, lane)
    assert c.validate_dir(base) == []
    prov = json.loads((base / c.PROVENANCE_JSON).read_text())
    assert prov["points"] == n_base + n_lane and prov["dump"]["ref"] == PIN["ref"]
    assert prov["left_out_records"] == 3                  # the API lane's, not the dump's
    facets = json.loads((base / c.FACETS_JSON).read_text())
    assert sum(f.get("source") == "dump" for f in facets.values()) == len(json.loads((lane / c.FACETS_JSON).read_text()))
    pulled = json.loads((FIXTURE / c.PROVENANCE_JSON).read_text())["pulled_at"]
    assert {f["source_revision"] for f in facets.values() if f.get("source") != "dump"} == {f"api/{pulled}"}
    assert {f["source_revision"] for f in facets.values() if f.get("source") == "dump"} == {PIN["ref"]}


def test_a_unit_in_both_lanes_is_refused(tmp_path):
    lane = scored_lane(tmp_path)
    base = tmp_path / "base"
    shutil.copytree(FIXTURE, base)
    shutil.copytree(base, tmp_path / "again")
    with pytest.raises(dl.LaneError, match="both lanes"):
        dl.add_lane(base, tmp_path / "again")
    before = (base / c.POINTS_CSV).read_text()
    assert before == (FIXTURE / c.POINTS_CSV).read_text()  # nothing was written before the refusal
    dl.add_lane(base, lane)


def test_combined_leaves_the_api_lanes_contract_alone(tmp_path):
    lane = scored_lane(tmp_path)
    base = tmp_path / "base"
    shutil.copytree(FIXTURE, base)
    out = dl.combined(base, lane, tmp_path / "both")
    assert c.validate_dir(out) == [] and "dump" in json.loads((out / c.PROVENANCE_JSON).read_text())
    assert {p.name: p.read_bytes() for p in base.iterdir()} == {p.name: p.read_bytes() for p in FIXTURE.iterdir()}


# ---------------------------------------------------------------- the extract's units
def test_the_extract_units_are_its_manifest_points_and_never_agentic(tmp_path):
    assert dl.extract_units(make_extract(tmp_path / "a", ["2" * 64, "1" * 64])) == ["1" * 64, "2" * 64]
    with pytest.raises(dl.LaneError, match="not single_turn"):
        dl.extract_units(make_extract(tmp_path / "b", ["1" * 64], kind="agentic_traces"))


# ---------------------------------------------------------------- a night's lane
class FakePin:
    def __init__(self, monkeypatch):
        monkeypatch.setattr(dx, "load_pin", lambda *a, **k: PIN)
        self.verify_problems = []
        monkeypatch.setattr(dx, "verify", lambda extract, pin: self.verify_problems)


def run_lane(tmp_path, monkeypatch, units, *, anchors=None, force=False, rc=0, key_args=KEY_ARGS):
    pin = FakePin(monkeypatch)
    ext = tmp_path / "ext"
    if not ext.exists():
        make_extract(ext, units)
    calls = []

    def score(units_file, out):
        calls.append(units_file.read_text().split())
        if rc == 0:
            shutil.copytree(other_units(FIXTURE, tmp_path / "scored"), out, dirs_exist_ok=True)
            shutil.rmtree(tmp_path / "scored")
        return rc

    got = dl.night_lane(extract=ext, state=tmp_path / "state" / "dump", anchors=set(units) if anchors is None else anchors,
                        key_args=key_args, force=force, score=score, log=lambda m: None)
    return got, calls, pin


UNITS = ["1" * 64, "2" * 64]


def test_a_first_night_scores_the_lane_and_the_next_reuses_it(tmp_path, monkeypatch):
    (state, lane, scored, units), calls, _ = run_lane(tmp_path, monkeypatch, UNITS)
    assert scored and units == sorted(UNITS) and calls == [sorted(UNITS)]
    assert lane["key"] == KEY and c.validate_dir(state) == []
    (_, again, scored, _), calls, _ = run_lane(tmp_path, monkeypatch, UNITS)
    assert not scored and calls == [] and again == lane


def test_a_new_release_or_harness_or_a_force_flag_scores_the_lane_again(tmp_path, monkeypatch):
    run_lane(tmp_path, monkeypatch, UNITS)
    for extra in ({"blis_release": "v0.13.0"}, {"harness_commit": "e" * 40}, {"registry_release": "v0.9.0"}):
        (_, lane, scored, _), calls, _ = run_lane(tmp_path, monkeypatch, UNITS, key_args={**KEY_ARGS, **extra})
        assert scored and len(calls) == 1 and lane["key"] == {**KEY, **extra}
    (_, _, scored, _), calls, _ = run_lane(tmp_path, monkeypatch, UNITS, force=True)
    assert scored and len(calls) == 1


def test_a_failed_lane_keeps_the_last_result_and_stops_the_night(tmp_path, monkeypatch):
    (state, lane, _, _), _, _ = run_lane(tmp_path, monkeypatch, UNITS)
    with pytest.raises(dl.LaneError, match="headline stays"):
        run_lane(tmp_path, monkeypatch, UNITS, force=True, rc=1)
    assert dl.load_result(state) == lane


def test_an_extract_that_is_not_the_pinned_one_is_refused_before_anything_is_scored(tmp_path, monkeypatch):
    pin = FakePin(monkeypatch)
    pin.verify_problems = ["the extract's content hash is not the pinned one"]
    make_extract(tmp_path / "ext", UNITS)
    called = []
    with pytest.raises(dl.LaneError, match="not the pinned one"):
        dl.night_lane(extract=tmp_path / "ext", state=tmp_path / "s", anchors=set(UNITS), key_args=KEY_ARGS, force=False,
                      score=lambda *a: called.append(a) or 0, log=lambda m: None)
    assert called == []


def test_an_extract_unit_outside_the_anchor_list_is_refused(tmp_path, monkeypatch):
    with pytest.raises(dl.LaneError, match="anchor units only"):
        run_lane(tmp_path, monkeypatch, UNITS, anchors={UNITS[0]})


# ---------------------------------------------------------------- the summary the two lanes make
def ids_of(directory: Path) -> set:
    with open(directory / c.POINTS_CSV, newline="") as fh:
        got = {r["point_id"] for r in csv.DictReader(fh)}
    return got | {r["point_id"] for n in (c.NOT_SCORED_JSONL, c.FAILED_JSONL) for r in lines(directory / n)}


def test_an_api_only_night_puts_the_lanes_current_dump_points_in_the_merged_summary_once(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import build_summary_v2 as b2
    import validate_summary_v2 as vs2
    lane = scored_lane(tmp_path)
    base = tmp_path / "base"
    shutil.copytree(FIXTURE, base)
    api_ids, n_api, n_dump = ids_of(base), len(ids_of(base)), len(ids_of(lane))
    prior = b2.build(dl.combined(base, lane, tmp_path / "both"), generated_at="2026-11-01T00:00:00Z", evaluator_commit="t")
    assert prior["coverage"]["points"] == n_api + n_dump
    # the API lane's window holds its own units only: last night's dump points are pruned, the lane's come in again
    merged = b2.build_merged(prior, FIXTURE, api_ids, generated_at="2026-11-02T00:00:00Z", evaluator_commit="t",
                             work=tmp_path / "w1", lane_dir=lane)
    assert merged["coverage"]["points"] == n_api + n_dump
    assert [s["id"] for s in merged["provenance"]["ground_truth"]["sources"]].count("dump") == 1
    assert vs2.problems(merged) == []
    # with no lane the pruned dump points are simply gone: the lane is what keeps them in the headline
    bare = b2.build_merged(prior, FIXTURE, api_ids, generated_at="2026-11-02T00:00:00Z", evaluator_commit="t",
                           work=tmp_path / "w2")
    assert bare["coverage"]["points"] == n_api


def test_the_harness_command_carries_a_worker_count_only_when_one_is_given():
    import cli
    base = dict(sim="v0.16.0", units="u", pull="p", out="o", catalog="c", registry="r", corpus_dir="k", fields="f",
                catalog_release="v0.3.0", registry_release="v0.2.0")
    assert "--workers" not in cli.harness_command(**base)
    cmd = cli.harness_command(**base, workers=2)
    assert cmd[cmd.index("--workers") + 1] == "2"
