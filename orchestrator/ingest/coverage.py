"""The coverage report: every unit of the window graded from its data by the scorer's own code,
without a simulator, counted in units and in rows (design §11.3, §11.6, COV-1, COV-7).

A point is graded by score.score_point(simulate=False): the same checks, the same scenario, and
the scorer stops where it would call the simulator. Such a point keeps the grade its data gives
so far (`would_run_simulator`): it names the substitutions the scorer knows offline (those its
settings named, the single-turn client's differences, the data-parallel balancer) and the two
that only the Result can replace, "selected-entry report not read" and, for a drafter with no
recorded acceptance, "profile not read". So it is G2 at best, never G1. It still needs the
simulator, and it may still become G5 or failed there; the report says so.

Counts are of two kinds and every one is labelled. A row is an API record; a unit is a ledger
unit, the point of the dashboard, and the ledger joins several rows into one (duplicates, merged
records and the other attempts of a run). Rows the ledger holds no unit for are counted as rows
only, with the reason.

The frozen pull holds a unit's artifacts under the point id of the identity it was frozen with.
The window's rows are placed in the ledger afresh (pull.place) and each unit takes the artifacts
of the manifest entry of any of its rows, by row id; a scratch directory of links lets the scorer
read them under the unit's present id. A unit whose framework's engine the harness scores
(engines.scored) but whose artifacts the pull does not hold is counted as `not_in_pull`, not
graded. A reason the pull wrote that only a simulator run can give (blis_refused, setting_differs)
is dropped from the entry and counted, because a pull runs no simulator.
"""
from __future__ import annotations

import json
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import assess as asx
import backlog as bl
import engines
import fields as fl
import grade as gr
import ledger as ldg
import pull as pl
import resolve_agentic_corpus as rac
import score as sc
import settings as st
import stack as sk
import support as sp

PULL_ERROR = "artifact_unmatched:pull_error"
FAILED, NOT_IN_PULL = "failed", "not_in_pull"
GRADE_KEYS = (*gr.GRADES, FAILED, NOT_IN_PULL)

PENDING = ("A unit marked would_run_simulator was graded without the simulator, from its data so far. "
           "It still needs the simulator: the Result's selected-entry report and its coefficient methods "
           "are added there, so is the drafter's acceptance profile, and the simulator may still refuse "
           "the point (failed) or the scenario may lose a recorded value. Such a unit is G2 at best.")


class CoverageError(ValueError):
    """The inputs of a coverage report do not agree with each other."""


def window_rows(rows: list[dict], window: list[str]) -> list[dict]:
    """The rows measured within [start, end] (both ends included)."""
    start, end = window
    return [r for r in rows if start <= str(r["date"])[:10] <= end]


def place_all(rows: list[dict], lg) -> tuple[pl.Placed, list[dict]]:
    """pull.place over the rows, where a row that differs from the ledger's source revision
    (ledger.RowDiffers) does not stop the report: it is listed with the reason
    `differs_from_source_revision` among the rows that hold no unit, and counted as such. (The
    nightly's pull refuses such a row; a report states it.)"""
    keep, differing = list(rows), []
    while True:
        try:
            placed = pl.place(keep, lg)
            break
        except ldg.RowDiffers as e:
            row = next(r for r in keep if str(r["id"]) == e.record)
            keep.remove(row)
            differing.append(row)
    for r in differing:
        placed.unlisted.append({"record": str(r["id"]), "reason": "differs_from_source_revision", "model": r["model"],
                                "hardware": r["hardware"], "framework": r["framework"],
                                "benchmark_type": r["benchmark_type"], "conc": r["conc"], "date": str(r["date"])[:10]})
    pl.check_placed(rows, placed)
    return placed, differing


def manifest_entries(manifest: dict) -> tuple[dict, Counter]:
    """The manifest's entries by every row id they hold, and the pull reasons that only a simulator
    run can give, dropped from them and counted."""
    by_row: dict = {}
    dropped: Counter = Counter()
    for e in manifest["points"]:
        keep = []
        for r in e["reasons"]:
            if asx.is_fault(r):
                dropped[r] += 1
            else:
                keep.append(r)
        e = {**e, "reasons": keep}
        for rid in e.get("records") or [str(e["row"]["id"])]:
            by_row[str(rid)] = e
    return by_row, dropped


def entries_for(placed: pl.Placed, by_row: dict, overlay: Path, pull_dir: Path) -> tuple[list[dict], list[dict]]:
    """(entries to grade, units with no artifacts in the pull). A unit of a framework the harness
    does not score has none to fetch. Every other unit takes the entry of its rows in the manifest,
    its artifact directory linked into `overlay` under the unit's id."""
    entries, missing = [], []
    (overlay / "points").mkdir(parents=True, exist_ok=True)
    for p in placed.points:
        base = {"point_id": p.point_id, "identity": dict(p.unit.identity), "row": p.row, "records": p.records,
                "measurements": p.measurements}
        if not engines.scored(engines.lookup(p.row["framework"])):
            entries.append({**base, "reasons": [], "files": {}, "build": None})
            continue
        old = next((by_row[r] for r in p.records if r in by_row), None)
        if old is None or PULL_ERROR in old["reasons"]:
            missing.append({**base, "why": "pull_error" if old else "no_entry"})
            continue
        entries.append({**old, **base, "reasons": old["reasons"]})
        src = pull_dir / "points" / old["point_id"]
        if src.is_dir():
            (overlay / "points" / p.point_id).symlink_to(src.resolve())
    return entries, missing


def make_env(*, fields_path: Path, stack_path: Path, catalog: Path, registry: Path, base_models: dict) -> sc.Env:
    """The scorer's inputs with no simulator: the field list, the engine release, the catalog read
    from its checkout (support.CheckoutCatalog) and the registry's parts. The corpora are the
    catalog's replay workloads, with no corpus file: nothing is replayed."""
    release = sk.load(stack_path).engine("vllm")
    field_list = fl.parse(Path(fields_path).read_bytes())
    if field_list.engine != {"kind": "vllm", "version": release}:
        raise CoverageError(f"{fields_path} is the field list of {field_list.engine}, but the stack runs vllm {release}")
    try:
        corpora = {a: {**rac.catalog_entry(catalog, a), "path": str(Path(catalog) / "corpus-not-read")}
                   for a in sorted(rac.CATALOG_WORKLOADS)}
    except rac.CorpusError as e:
        raise CoverageError(str(e)) from None
    vdefaults, _ = st.load_vllm_defaults()
    env = sc.Env(blis="", blis_release="", blis_commit="", catalog=Path(catalog), catalog_release="",
                 registry=Path(registry), registry_release="", kernel="", corpora=corpora, field_list=field_list,
                 base_models=base_models, vllm_defaults=vdefaults, vllm_defaults_release=st.vllm_defaults_release(),
                 engine_release=release)
    env.catalog_obj = sp.CheckoutCatalog(blis="", root=Path(catalog))
    env.parts = sp.registry_parts(registry)
    return env


def unit_record(o: sc.Outcome) -> dict:
    rec = {"point_id": o.point_id, "framework": o.row["framework"], "hardware": o.row["hardware"],
           "release": o.run_release, "would_run_simulator": o.would_run_simulator}
    if o.faults:
        return {**rec, "grade": FAILED, "faults": o.faults}
    if o.fidelity is None:
        return {**rec, "grade": gr.G5, "g5": o.g5, "g5_reasons": o.g5_reasons}
    return {**rec, "grade": o.fidelity["grade"], "substitutions": o.fidelity["substitutions"]}


def report(*, rows: list[dict], placed: pl.Placed, records: list[dict], missing: list[dict], window: list[str],
           rows_source: str, dropped: Counter, anchor: set | None) -> dict:
    """The one document. Every count says whether it counts rows or units."""
    units = records + [{"point_id": m["point_id"], "framework": m["row"]["framework"], "hardware": m["row"]["hardware"],
                        "grade": NOT_IN_PULL, "why": m["why"]} for m in missing]
    if len(units) != len(placed.points):
        raise CoverageError(f"{len(placed.points)} units placed but {len(units)} reported")
    by_fw: dict = defaultdict(Counter)
    for u in units:
        by_fw[u["framework"]][u["grade"]] += 1
    rows_fw = Counter(r["framework"] for r in rows)
    unlisted = Counter(x["reason"] for x in placed.unlisted)
    graded = [u for u in units if u["grade"] in (*gr.GRADES,)]
    sim_pending = Counter(u["framework"] for u in units if u.get("would_run_simulator"))
    first = Counter(f"{u['g5']['code']}" + (f":{u['g5']['subject']}" if u["g5"].get("subject") else "")
                    for u in graded if u["grade"] == gr.G5)
    every = Counter()
    for u in graded:
        if u["grade"] == gr.G5:
            for r in {(r["code"], r.get("subject", "")) for r in u["g5_reasons"]}:
                every[r[0] + (f":{r[1]}" if r[1] else "")] += 1
    out = {
        "window": window,
        "rows": {
            "counted": "rows", "source": rows_source, "in_window": len(rows),
            "by_framework": dict(sorted(rows_fw.items())),
            "in_a_unit": len(rows) - len(placed.unlisted),
            "beyond_the_first_of_a_unit": len(rows) - len(placed.unlisted) - len(placed.points),
            "no_unit": {"count": len(placed.unlisted), "by_reason": dict(sorted(unlisted.items())),
                        "by_framework": dict(sorted(Counter(x["framework"] for x in placed.unlisted).items()))},
        },
        "units": {
            "counted": "units", "total": len(units),
            "grades": {g: sum(c[g] for c in by_fw.values()) for g in GRADE_KEYS},
            "by_framework": {fw: {"units": sum(c.values()), **{g: c[g] for g in GRADE_KEYS}}
                             for fw, c in sorted(by_fw.items())},
            "would_run_simulator": {"counted": "units", "total": sum(sim_pending.values()),
                                    "by_framework": dict(sorted(sim_pending.items()))},
            "not_in_pull": dict(sorted(Counter(m["why"] for m in missing).items())),
            "pull_reasons_dropped": {"counted": "pull entries", "reasons": dict(sorted(dropped.items())),
                                     "why": "the pull runs no simulator, so a reason only a simulator run can give is stale"},
            "note": PENDING,
        },
        "top_not_g1": {"counted": "units",
                       "over": "units graded G2 to G5 (not failed, not not_in_pull); a unit counts once per reason",
                       "top": [{"reason": k, "units": n}
                               for k, n in bl.top([u for u in units if u["grade"] in gr.GRADES], 10)]},
        "g5_reasons": {"counted": "units", "first_reason": dict(first.most_common()),
                       "all_reasons": dict(every.most_common())},
    }
    if anchor is not None:
        mine = [u for u in units if u["point_id"] in anchor]
        c = Counter(u["grade"] for u in mine)
        out["anchor"] = {"counted": "units", "listed": len(anchor), "in_window": len(mine),
                         "not_in_window": len(anchor) - len(mine), "grades": {g: c[g] for g in GRADE_KEYS},
                         "would_run_simulator": sum(1 for u in mine if u.get("would_run_simulator"))}
    total = sum(out["units"]["grades"].values())
    if total != len(units):
        raise CoverageError(f"the grades sum to {total} units, not {len(units)}")
    return out


def run(*, pull_dir: Path, ledger: Path, fields_path: Path, stack_path: Path, catalog: Path, registry: Path,
        rows_path: Path | None = None, units_path: Path | None = None, workers: int = 1, work: Path | None = None) -> dict:
    """The report for a frozen pull. `rows_path` holds every row of the window (a JSON list of API
    rows); without it the rows are the manifest's own, which are one row per unit."""
    manifest = json.loads((pull_dir / "manifest.json").read_text())
    window = list(manifest["window"])
    if rows_path is not None:
        rows, source = window_rows(json.loads(Path(rows_path).read_text()), window), f"{rows_path} (window rows)"
    else:
        rows, source = [e["row"] for e in manifest["points"]], "the manifest's rows (one per unit; joined records not counted)"
    lg = ldg.load(ledger)
    placed, differing = place_all(rows, lg)
    by_row, dropped = manifest_entries(manifest)
    env = make_env(fields_path=fields_path, stack_path=stack_path, catalog=catalog, registry=registry,
                   base_models=manifest.get("base_models") or {})
    with tempfile.TemporaryDirectory() as tmp:
        overlay = Path(tmp)
        entries, missing = entries_for(placed, by_row, overlay, pull_dir)
        outcomes = sc.score_points(entries, overlay, Path(work) if work else overlay / "work", env,
                                   workers=workers, simulate=False)
    anchor = ldg.read_unit_set(units_path) if units_path else None
    return report(rows=rows, placed=placed, records=[unit_record(o) for o in outcomes], missing=missing,
                  window=window, rows_source=source, dropped=dropped, anchor=anchor)
