"""The database-dump scoring lane of the nightly (plan row 12; design D3, COV-13).

The dump supplies the anchor units measured up to its cutoff; the API supplies the rest, and a unit is never taken from both. The
lane scores the anchor extract (dump_extract.py) in the same night, on the same BLIS release and harness commit as the API lane,
and keeps only its RESULTS, in the contract format the API lane writes, plus where they came from: every point is stamped
source=dump, the dump revision and the BLIS release scored, and provenance.json gets the `dump` block the summary builder reads.

  * decide()      a night reuses the last dump result only if the BLIS release, harness commit, catalog and registry versions, the
                  dump revision and the extract all match the result's; any change, or a forced rerun, scores the lane again.
  * gate()        the headline publishes only if both lanes were scored on one BLIS release and one harness commit.
  * add_lane()    puts the lane's contract into the API lane's before the summary is built.
  * night_lane()  what cli.py nightly calls: verify the extract, take its units from the API lane, score or reuse, return the result.
"""
from __future__ import annotations

import csv
import io
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import contract  # noqa: E402
import dump_extract as dx  # noqa: E402

LANE_JSON = "lane.json"
SOURCE = "dump"
KEY_FIELDS = ("blis_release", "harness_commit", "catalog_release", "registry_release", "dump_ref", "extract_sha256")


class LaneError(RuntimeError):
    pass


def lane_key(*, blis_release: str, harness_commit: str, catalog_release: str, registry_release: str, pin: dict) -> dict:
    """Everything a dump result depends on: the build that scored it, the harness that ran it, the data it read, the dump."""
    return {"blis_release": blis_release, "harness_commit": harness_commit, "catalog_release": catalog_release,
            "registry_release": registry_release, "dump_ref": pin["ref"], "extract_sha256": pin["extract_sha256"]}


@dataclass
class Decision:
    rerun: bool
    reason: str


def decide(prior: dict | None, key: dict, force: bool = False) -> Decision:
    """Reuse the last dump result (`prior`, its lane.json) only if every part of the key is the same."""
    if force:
        return Decision(True, "forced rerun")
    if prior is None:
        return Decision(True, "no dump result yet")
    have = prior.get("key") or {}
    changed = [f for f in KEY_FIELDS if have.get(f) != key.get(f)]
    if changed:
        return Decision(True, "changed since the last dump result: " + ", ".join(changed))
    return Decision(False, "same BLIS release, harness commit, catalog, registry and dump revision as the last dump result")


def gate(provenance: dict, lane: dict) -> list[str]:
    """Why the headline must not publish: the summary's provenance (the API lane's) and the dump result are not of one BLIS release
    and one harness commit. Empty means both lanes are one scoring."""
    out = []
    if (provenance.get("blis") or {}).get("release") != lane.get("blis_release"):
        out.append(f"the API lane was scored on BLIS {(provenance.get('blis') or {}).get('release')!r}, "
                   f"the dump lane on {lane.get('blis_release')!r}")
    if provenance.get("harness_commit") != lane.get("harness_commit"):
        out.append(f"the API lane was scored by harness commit {provenance.get('harness_commit')!r}, "
                   f"the dump lane by {lane.get('harness_commit')!r}")
    return out


def extract_units(extract: Path) -> list[str]:
    """The units the extract holds, sorted. Agentic units are not in the dump lane: an extract that holds one is refused."""
    m = json.loads((Path(extract) / "manifest.json").read_text())
    bad = [p["point_id"] for p in m["points"] if (p.get("identity") or {}).get("benchmark_type") != "single_turn"]
    if bad:
        raise LaneError(f"the extract holds {len(bad)} unit(s) that are not single_turn (first: {bad[0]}); "
                        "the dump lane scores no agentic unit")
    return sorted(p["point_id"] for p in m["points"])


def _read(path: Path):
    return json.loads(path.read_text())


def _lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def _write_lines(path: Path, rows: list[dict], key) -> None:
    path.write_text("".join(contract.canonical_dumps(r) + "\n" for r in sorted(rows, key=key)))


def stamp(directory: Path, key: dict, pin: dict, extract: Path) -> dict:
    """Mark a scored lane contract as the dump's: each point's facets get source, dump revision and BLIS release, provenance.json gets
    the `dump` block ({ref, sha256, pulled_at}: the dump revision, the SHA256SUMS hash the pin holds, when the extract was cut),
    and lane.json records the key, so the next night can decide whether to reuse it. Returns lane.json's content."""
    d = Path(directory)
    facets = _read(d / contract.FACETS_JSON)
    for pid in facets:
        facets[pid].update(source=SOURCE, dump_ref=key["dump_ref"], blis_release=key["blis_release"],
                           source_revision=key["dump_ref"])
    (d / contract.FACETS_JSON).write_text(contract.canonical_dumps(facets) + "\n")
    prov = _read(d / contract.PROVENANCE_JSON)
    cut = _read(Path(extract) / "manifest.json")["pulled_at"]
    prov["dump"] = {"ref": key["dump_ref"], "sha256": pin["sha256sums"], "pulled_at": cut}
    (d / contract.PROVENANCE_JSON).write_text(contract.canonical_dumps(prov) + "\n")
    lane = {"source": SOURCE, "key": key, "sha256sums": pin["sha256sums"], "pulled_at": cut, "points": prov["points"],
            **{f: key[f] for f in ("blis_release", "harness_commit", "dump_ref")}}
    (d / LANE_JSON).write_text(contract.canonical_dumps(lane) + "\n")
    return lane


def load_result(directory: Path) -> dict | None:
    """The last dump result's lane.json, or None if there is none or it is not a valid contract (then it is scored again)."""
    d = Path(directory)
    try:
        lane = _read(d / LANE_JSON)
    except (OSError, ValueError):
        return None
    if contract.validate_dir(d) or lane.get("source") != SOURCE:
        return None
    return lane


def add_lane(base: Path, lane: Path) -> None:
    """Add the dump lane's contract to the API lane's `base`, in place. The lanes must not share a unit. A base without substrate
    point records (one rebuilt from a published summary) keeps none, since the file is all or nothing (contract.validate_dir)."""
    base, lane = Path(base), Path(lane)
    rows = {}
    for d in (base, lane):
        with open(d / contract.POINTS_CSV, newline="") as fh:
            rows[d] = list(csv.DictReader(fh))
    ids = {d: {r["point_id"] for r in rows[d]} for d in rows}
    kinds = {d: {x["point_id"] for n in (contract.NOT_SCORED_JSONL, contract.FAILED_JSONL) for x in _lines(d / n)} for d in rows}
    both = (ids[base] | kinds[base]) & (ids[lane] | kinds[lane])
    if both:
        raise LaneError(f"{len(both)} unit(s) are in both lanes (first: {sorted(both)[0]}); a unit is never taken from the "
                        "dump and the API")
    merged = sorted(rows[base] + rows[lane], key=contract.points_sort_key)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=contract.POINTS_HEADER, extrasaction="ignore")
    w.writeheader()
    w.writerows(merged)
    (base / contract.POINTS_CSV).write_text(buf.getvalue())
    for name in (contract.FIDELITY_JSONL, contract.NOT_SCORED_JSONL, contract.FAILED_JSONL):
        _write_lines(base / name, _lines(base / name) + _lines(lane / name), lambda r: r["point_id"])
    facets = _read(base / contract.FACETS_JSON)
    bprov, lprov = _read(base / contract.PROVENANCE_JSON), _read(lane / contract.PROVENANCE_JSON)
    for f in facets.values():            # COV-13's source revision: the dump revision for the dump, the pull for the API feed
        f.setdefault("source_revision", f"api/{bprov['pulled_at']}")
    facets.update(_read(lane / contract.FACETS_JSON))
    (base / contract.FACETS_JSON).write_text(contract.canonical_dumps(facets) + "\n")
    if (base / contract.POINTRECORDS_JSONL).stat().st_size:
        _write_lines(base / contract.POINTRECORDS_JSONL,
                     _lines(base / contract.POINTRECORDS_JSONL) + _lines(lane / contract.POINTRECORDS_JSONL),
                     lambda r: str(r.get("point_id")))
    bprov["points"] += lprov["points"]
    bprov["dump"] = lprov["dump"]
    (base / contract.PROVENANCE_JSON).write_text(contract.canonical_dumps(bprov) + "\n")


def combined(base: Path, lane: Path, out: Path) -> Path:
    """A copy of the API lane's contract with the dump lane's in it, for the full (not merged) build."""
    shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(base, out)
    add_lane(out, lane)
    return Path(out)


def night_lane(*, extract: Path, state: Path, anchors: set, key_args: dict, force: bool, score, log=print) -> tuple[Path, dict, bool, list[str]]:
    """The dump lane of one night. `extract` is the restored anchor extract, `state` the directory the last result is kept in,
    `anchors` the night's anchor units (the extract holds no unit outside them), `key_args` the BLIS release, harness commit
    and data pins the night runs with, and `score(units_file, out_dir)` runs the
    harness on the extract and returns its exit status. Returns (result directory, lane.json, whether it was scored tonight,
    the units the API lane must leave to the dump). The extract is checked against the pin before anything is read from it."""
    pin = dx.load_pin()
    problems = dx.verify(extract, pin)
    if problems:
        raise LaneError("the anchor extract is not the pinned one: " + "; ".join(problems[:3]))
    units = extract_units(extract)
    stray = sorted(set(units) - set(anchors))
    if stray:
        raise LaneError(f"{len(stray)} unit(s) of the extract are not anchor units of this build (first: {stray[0]}); "
                        "the dump lane scores anchor units only")
    key = lane_key(pin=pin, **key_args)
    state = Path(state)
    prior = load_result(state)
    d = decide(prior, key, force)
    if not d.rerun:
        log(f"dump lane: reuse the last result ({d.reason})")
        return state, prior, False, units
    log(f"dump lane: score {len(units)} units ({d.reason})")
    work = state.with_name(state.name + ".new")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    units_file = work.with_name(work.name + ".units")
    units_file.write_text("".join(u + "\n" for u in units))
    rc = score(units_file, work)
    if rc != 0:
        raise LaneError(f"the dump lane failed to score (status {rc}); the headline stays at the last good night")
    lane = stamp(work, key, pin, extract)
    problems = contract.validate_dir(work)
    if problems:
        raise LaneError("the dump lane's contract is invalid: " + "; ".join(problems[:3]))
    shutil.rmtree(state, ignore_errors=True)
    work.rename(state)
    units_file.unlink()
    return state, lane, True, units
