#!/usr/bin/env python3
"""BLIS scored on exactly the points of a pinned external end-to-end accuracy artifact, with its metric, per cell (#88).

An external simulator publishes its own end-to-end accuracy as a pinned artifact: a summary of concurrency sweeps,
each point holding the measured TTFT and TPOT and the estimator's, all normalised to the sweep's measured point at
its lowest concurrency (`*_relative`). blis-substrate pins the artifact (kernel/scripts/<name>_e2e.pin.json, with the
zip's and the summary's SHA-256) and extracts its scoreable points (kernel/scripts/extract_<name>_e2e.py). The
artifact's measurements are InferenceX's own release db-dump/2026-09-28, the ledger's source revision. This tool
scores BLIS on the same points with the same metric, in this repository's harness, the one end-to-end scorer (design
§2.2, §11.7; COV-1). The estimator's name is an argument (`--estimator`), as is every path: it names nothing itself.

The metric, as the artifact computes it (checked against its own totals):

  MAPE    over every point of a cell, |pred(c) - meas(c)| / meas(c), in percent. Both curves are normalised by the
          same measured value, so the error of a relative is the error of the absolute.
  shape   over every point above a sweep's lowest concurrency c0, |pred(c)/pred(c0) - meas(c)/meas(c0)| /
          (meas(c)/meas(c0)), in percent: each curve normalised to its own value at c0.
  coverage  the estimator's points with a figure over the cell's points. A point BLIS does not score (refused by the
          simulator, G5, or no record found) is uncovered, as the estimator's failed points are its own.

A cell is (framework, chip, model, serving mode). Every cell is reported, won or lost: BLIS wins a cell when both its
MAPEs and both its shape errors are below the estimator's and its coverage is at least the estimator's.

    matched.py points --zip ZIP --pin PIN --extractor SCRIPT --out POINTS.json
    matched.py match  --points POINTS.json --dump-rows ROWS.jsonl --ledger LEDGER --extractor SCRIPT --out MATCH.json
                      [--units-out UNITS.txt]
    matched.py freeze --match MATCH.json --dump-rows ROWS.jsonl --ledger LEDGER --out PULL --cache CACHE --errors-out E.json
    matched.py report --points POINTS.json --match MATCH.json --contract DIR --splits SPLITS.json --pull-errors E.json
                      --estimator NAME
                      --out PREFIX [--evaluate-test --log LOG --label LABEL]

`points` checks the zip against the pin's SHA-256, unpacks summary.json, and runs the substrate's extractor, which
checks the summary's SHA-256 and the pinned run before it reads a row. `match` finds each point's record in the
dump (ROWS.jsonl is blis-substrate's ledger/inferencex/export.sql over the restored dump, never committed): same
model, chip, framework, precision, sequence lengths, parallel layout and concurrency, aggregated and with no
speculation, measured no later than the artifact's last measurement date, and the record's run giving the same
measured TPOT and TTFT curve; then the ledger unit that holds it. `report` reads the harness's contract of those
units. Accuracy over test or prospective points of the development split is withheld unless the evaluation is
logged (`--evaluate-test --log`, docs/m2/evaluation-protocol.md); coverage counts every point.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import runpy
import subprocess
import sys
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ingest"))

FORMAT = "matched-comparison-1"
METRICS = ("tpot", "ttft")
REL_TOL = 2e-3          # the artifact prints relatives to 6 digits; a curve matches when every ratio agrees to 0.2 %
ENGINES = {"vllm": "vllm", "sglang": "sglang", "trt": "trt"}


class MatchError(ValueError):
    pass


# ------------------------------------------------------------------------------------------- points

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_points(zip_path: Path, pin_path: Path, extractor: Path, out: Path) -> dict:
    pin = json.loads(pin_path.read_text())
    got = sha256(zip_path)
    if got != pin["zip_sha256"]:
        raise MatchError(f"{zip_path} has SHA-256 {got}; the pin records {pin['zip_sha256']}")
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as z:
            names = [n for n in z.namelist() if n.rsplit("/", 1)[-1] == "summary.json"]
            if len(names) != 1:
                raise MatchError(f"{zip_path} holds {len(names)} summary.json files, not one")
            summary = Path(tmp) / "summary.json"
            summary.write_bytes(z.read(names[0]))
        r = subprocess.run([sys.executable, "-I", str(extractor), str(summary), "-o", str(out), "--pin", str(pin_path)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise MatchError(f"the extractor refused the artifact: {r.stderr.strip()[-600:]}")
    return {"zip_sha256": got, "summary_sha256": pin["summary_sha256"], "artifact": pin.get("artifact"),
            "run_id": pin.get("run_id"), "extractor_output": r.stdout.strip().splitlines()[0] if r.stdout else ""}


# ------------------------------------------------------------------------------------------- match

def slugs_of(extractor: Path) -> dict[str, str]:
    """Catalog model name to InferenceX slug, inverted from the extractor's own map."""
    models = runpy.run_path(str(extractor))["MODELS"]
    inv = defaultdict(list)
    for slug, name in models.items():
        inv[name].append(slug)
    bad = {n: s for n, s in inv.items() if len(s) > 1}
    if bad:
        raise MatchError(f"the extractor maps several slugs to one model: {bad}")
    return {n: s[0] for n, s in inv.items()}


def sweep_keys(sw: dict, slug: str) -> list[tuple]:
    """The row keys a sweep can be. The artifact counts expert parallelism over the attention data-parallel ranks
    as well (moe_ep_size = InferenceX's decode_ep times attention_dp_size where attention is data-parallel), so a
    data-parallel sweep is looked for under both counts; the measured curve then decides."""
    par = sw["parallelism"]
    isl, osl = (int(x) for x in sw["workload"].split(":"))
    ep = int(par["moe_ep_size"] if par["moe_ep_size"] is not None else 1)
    dp = int(par["attention_dp_size"])
    eps = {ep} | ({ep // dp} if dp > 1 and ep % dp == 0 else set())
    return [(slug, sw["gpu"], sw["framework"], sw["precision"], isl, osl, int(par["tp_size"]), e, dp > 1)
            for e in sorted(eps)]


def row_key(r: dict) -> tuple:
    return (r["model"], r["hardware"], r["framework"], r["precision"], r.get("isl"), r.get("osl"), r.get("decode_tp"),
            r.get("decode_ep") or 1, bool(r.get("decode_dp_attention")))


def _metric(r: dict, m: str) -> float | None:
    v = (r.get("metrics") or {}).get(f"mean_{m}")
    return float(v) if v is not None else None


def match(points: dict, rows: list[dict], slugs: dict[str, str], through: str) -> list[dict]:
    """Each point of the artifact, with the dump record that measured it, or why there is none."""
    idx = defaultdict(list)
    for r in rows:
        if (r.get("benchmark_type") == "single_turn" and not r.get("disagg") and (r.get("spec_method") or "none") == "none"
                and not r.get("error") and str(r.get("date"))[:10] <= through):
            idx[row_key(r)].append(r)
    out = []
    for sw in points["sweeps"]:
        cands = [r for k in sweep_keys(sw, slugs[sw["model"]]) for r in idx.get(k, [])]
        runs = defaultdict(lambda: defaultdict(list))
        for r in cands:
            runs[str(r.get("github_run_id") or r["id"])][int(r["conc"])].append(r)
        c0 = sw["points"][0]["concurrency"]

        def fits(byc):
            if c0 not in byc:
                return False
            for m in METRICS:
                base = [_metric(r, m) for r in byc[c0]]
                for p in sw["points"]:
                    if p["concurrency"] not in byc:
                        return False
                    want = p[f"measured_{m}_relative"]
                    if not any(b and _metric(r, m) is not None and abs(_metric(r, m) / b - want) <= REL_TOL * want
                               for b in base for r in byc[p["concurrency"]]):
                        return False
            return True
        hits = [run for run, byc in runs.items() if fits(byc)]
        for p in sw["points"]:
            e = {"cell": cell(sw), "sweep": f"{sw['topology_id']}|{sw['label']}", "concurrency": p["concurrency"],
                 "framework": sw["framework"]}
            if len(hits) == 1:
                rec = sorted(runs[hits[0]][p["concurrency"]], key=lambda r: int(r["id"]))
                e["records"] = [str(r["id"]) for r in rec]
                e["split"] = split_kind(rec[0])
            else:
                e["records"] = []
                e["why"] = "no_record" if not hits else "several_runs"
            out.append(e)
    return out


def split_kind(row: dict) -> str:
    """The development split of a record (split.py's rule: its series and its measured date)."""
    import split as dsplit
    return dsplit.kind_of(dsplit.series_id(dsplit.from_row(row)), str(row.get("date"))[:10])


UNKNOWN = "unknown"
FIGURE_KINDS = ("train", "validation")


def cell(sw: dict) -> str:
    return f"{sw['framework']}|{sw['gpu']}|{sw['model']}|{sw['serving']}"


def place(matched: list[dict], ledger_dir: Path) -> None:
    import ledger as ldg
    lg = ldg.load(ledger_dir)
    for e in matched:
        units = sorted({lg.by_record[r].unit.unit_id for r in e["records"] if r in lg.by_record})
        if e["records"] and not units:
            e["why"] = "no_unit"
        elif len(units) > 1:
            e["why"] = "several_units"
        e["unit"] = units[0] if len(units) == 1 else None


def freeze(matched: list[dict], rows: list[dict], *, ledger_dir: Path, out: Path, cache: Path, workers: int,
           errors_out: Path) -> int:
    """Freeze the matched records' artifacts into a pull of their own, through the harness's own pull (cli.cmd_pull),
    as freeze_rows.py freezes pinned supplements: the rows are the dump's, not the live API's.

    A unit whose records GitHub and the API no longer hold (the run and its server log answer 404) cannot be frozen,
    and the harness refuses a pull holding such a unit. Those units are written to `errors_out` with the error, and
    the pull is made again without them (from the cache), so the report can count them as uncovered."""
    import shutil
    units = sorted({e["unit"] for e in matched if e.get("unit")})
    rc = _pull(matched, rows, units, ledger_dir=ledger_dir, out=out, cache=cache, workers=workers)
    manifest = json.loads((out / "manifest.json").read_text())
    bad = {e["point_id"]: (e.get("problems") or ["pull error"])[0] for e in manifest["points"]
           if "artifact_unmatched:pull_error" in e["reasons"]}
    errors_out.write_text(json.dumps(dict(sorted(bad.items())), indent=0, sort_keys=True) + "\n")
    if not bad:
        return rc
    shutil.rmtree(out)
    return _pull(matched, rows, [u for u in units if u not in bad], ledger_dir=ledger_dir, out=out, cache=cache,
                 workers=workers)


def _pull(matched, rows, units, *, ledger_dir, out, cache, workers) -> int:
    import types
    import api
    import cli
    keep = set(units)
    want = {r for e in matched if e.get("unit") in keep for r in e["records"]}
    mine = sorted((r for r in rows if str(r["id"]) in want), key=lambda r: int(r["id"]))
    dates = sorted({str(r["date"])[:10] for r in mine})

    def pull(fetch, *, today, window_days):
        return api.Pull(rows=mine, window=(dates[0], dates[-1]))
    real = api.pull
    api.pull = pull
    try:
        from datetime import date
        days = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days + 1
        return cli.cmd_pull(types.SimpleNamespace(out=str(out), today=dates[-1], window_days=days, cache=str(cache),
                                                  prior=None, only=units, download_workers=workers, ledger=str(ledger_dir)))
    finally:
        api.pull = real


# ------------------------------------------------------------------------------------------- report

def read_contract(d: Path) -> dict[str, dict]:
    out = {}
    with open(d / "points.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            out[r["point_id"]] = {"status": "scored", "grade": r["grade"],
                                  **{k: float(r[k]) for k in ("meas_ttft_us", "pred_ttft_us", "meas_tpot_us", "pred_tpot_us")}}
    for name, status in (("not_scored.jsonl", "not_scored"), ("failed.jsonl", "failed")):
        for line in (d / name).read_text().splitlines():
            if line.strip():
                n = json.loads(line)
                g = n.get("g5_reason") or {}
                reason = (f"{g['code']}:{g['subject']}"[:70] if g.get("subject") else g.get("code")) if g else \
                    ",".join(n.get("faults") or [])[:70]
                out[n["point_id"]] = {"status": status, "grade": n.get("grade", "failed"), "reason": reason}
    return out


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def cell_figures(entries: list[dict], side: str) -> dict:
    """MAPE and shape of one estimator over a cell's entries (each with meas_<m>, <side>_<m>, sweep, concurrency,
    withheld). Coverage counts every entry; errors only those not withheld."""
    covered = [e for e in entries if e.get(f"{side}_tpot") is not None]
    use = [e for e in covered if not e["withheld"]]
    out = {"points": len(entries), "covered": len(covered), "coverage_pct": 100 * len(covered) / len(entries) if entries else None,
           "with_figures": len(use)}
    for m in METRICS:
        out[f"{m}_mape_pct"] = _mean([abs(e[f"{side}_{m}"] - e[f"meas_{m}"]) / e[f"meas_{m}"] * 100 for e in use])
        sweeps = defaultdict(list)
        for e in entries:
            sweeps[e["sweep"]].append(e)
        sh = []
        for pts in sweeps.values():
            pts = sorted(pts, key=lambda e: e["concurrency"])
            p0 = pts[0]
            if p0.get(f"{side}_{m}") is None:
                continue
            for e in pts[1:]:
                if e.get(f"{side}_{m}") is None or e["withheld"] or p0["withheld"]:
                    continue
                mr = e[f"meas_{m}"] / p0[f"meas_{m}"]
                sh.append(abs(e[f"{side}_{m}"] / p0[f"{side}_{m}"] - mr) / mr * 100)
        out[f"{m}_shape_pct"] = _mean(sh)
        out[f"{m}_shape_n"] = len(sh)
    return out


def won(blis: dict, est: dict) -> bool:
    for k in ("tpot_mape_pct", "ttft_mape_pct", "tpot_shape_pct", "ttft_shape_pct"):
        if blis[k] is None or est[k] is None or not blis[k] < est[k]:
            return False
    return blis["coverage_pct"] >= est["coverage_pct"]


def entries_for(points: dict, matched: list[dict], contract: dict[str, dict], splits: dict, estimator: str,
                evaluate_test: bool) -> list[dict]:
    """One entry per artifact point, in the artifact's relative units: the measured relative, the estimator's, and
    BLIS's (its prediction over the measured value the harness read, times the measured relative)."""
    by = {(m["sweep"], m["concurrency"]): m for m in matched}
    out = []
    for sw in points["sweeps"]:
        for p in sw["points"]:
            m = by[(f"{sw['topology_id']}|{sw['label']}", p["concurrency"])]
            e = {"cell": cell(sw), "framework": sw["framework"], "sweep": m["sweep"], "concurrency": p["concurrency"],
                 "unit": m.get("unit"), "why": m.get("why")}
            for k in METRICS:
                e[f"meas_{k}"] = p[f"measured_{k}_relative"]
                e[f"est_{k}"] = p.get(f"{estimator}_{k}_relative")
            c = contract.get(m.get("unit") or "")
            if c and c["status"] == "scored":
                for k in METRICS:
                    # BLIS's prediction in the artifact's relative units: pred / meas(c) * meas_rel(c)
                    e[f"blis_{k}"] = c[f"pred_{k}_us"] / c[f"meas_{k}_us"] * e[f"meas_{k}"]
                e["blis_grade"] = c["grade"]
            else:
                for k in METRICS:
                    e[f"blis_{k}"] = None
                e["blis_status"] = (c or {}).get("status") or e["why"] or "not_in_contract"
                e["blis_reason"] = (c or {}).get("reason")
            kind = m.get("split") or UNKNOWN
            sp = splits.get(m.get("unit") or "")
            if sp and sp["kind"] != kind:
                raise MatchError(f"unit {m['unit']}: the splits file says {sp['kind']}, its record {kind}")
            e["kind"] = kind
            # Only train and validation points carry figures, unless a logged evaluation asks for the test and
            # prospective ones. A point of no known split is never shown: it could be a test point.
            e["withheld"] = kind == UNKNOWN or (kind not in FIGURE_KINDS and not evaluate_test)
            out.append(e)
    return out


def split_counts(entries: list[dict]) -> dict:
    out = {}
    for k in (*FIGURE_KINDS, "test", "prospective", UNKNOWN):
        es = [e for e in entries if e["kind"] == k]
        out[k] = {"points": len(es), "scored": sum(e.get("blis_tpot") is not None for e in es),
                  "withheld": sum(e["withheld"] for e in es)}
    return out


def build_report(entries: list[dict], estimator_label: str, provenance: dict, evaluate_test: bool,
                 evaluation: list[str] | None = None) -> dict:
    cells = defaultdict(list)
    for e in entries:
        cells[e["cell"]].append(e)
    rows = []
    for c in sorted(cells):
        es = cells[c]
        fw, gpu, model, mode = c.split("|")
        b, x = cell_figures(es, "blis"), cell_figures(es, "est")
        uncovered = defaultdict(int)
        for e in es:
            if e.get("blis_tpot") is None:
                uncovered[e.get("blis_reason") or e.get("blis_status")] += 1
        rows.append({"framework": fw, "gpu": gpu, "model": model, "mode": mode, "blis": b, "estimator": x,
                     "won": won(b, x), "blis_uncovered": dict(sorted(uncovered.items())),
                     "withheld": sum(e["withheld"] for e in es)})
    lanes = {}
    for fw in sorted({e["framework"] for e in entries}):
        es = [e for e in entries if e["framework"] == fw]
        b, x = cell_figures(es, "blis"), cell_figures(es, "est")
        both = [e for e in es if e.get("blis_tpot") is not None]
        lanes[fw] = {"blis": b, "estimator": x, "won": won(b, x),
                     "estimator_on_blis_points": cell_figures(both, "est") if both else None,
                     "cells": sum(r["framework"] == fw for r in rows), "cells_won": sum(r["won"] for r in rows if r["framework"] == fw)}
    if evaluate_test and not evaluation:
        raise MatchError("a report with test figures needs the evaluation-log rows that logged it")
    return {"format": FORMAT, "estimator": estimator_label, "provenance": provenance, "test_evaluated": evaluate_test,
            "evaluation": evaluation or [], "splits": split_counts(entries),
            "points": len(entries), "cells": rows, "lanes": lanes}


def _f(x, d=2):
    return "-" if x is None else f"{x:.{d}f}"


def markdown(rep: dict) -> str:
    est = rep["estimator"]
    L = [f"# BLIS on {est}'s points, with {est}'s metric", "",
         "Generated by `orchestrator/baseline/matched.py report`; do not edit by hand. How to read it: [README.md](README.md).", "",
         ("A logged test evaluation (evaluation log rows: " + "; ".join(r.strip("| ") for r in rep["evaluation"])
          + "): the test points' errors are included." if rep["test_evaluated"] else
          "Errors leave out the test and prospective points of the development split (their count is the Withheld "
          "column); coverage counts every point."), "",
         "Points by development split (points, BLIS-scored, withheld from errors): " + ", ".join(
             f"{k} {v['points']}/{v['scored']}/{v['withheld']}" for k, v in rep["splits"].items())
         + ". A point of no known split (`unknown`: no record found for it) is withheld from every error, "
           "because it could be a test point.", "",
         "## Totals by lane", "",
         f"| Lane | Points | BLIS coverage % | {est} coverage % | BLIS TPOT MAPE | {est} TPOT MAPE | BLIS TTFT MAPE | {est} TTFT MAPE | "
         f"BLIS TPOT shape | {est} TPOT shape | BLIS TTFT shape | {est} TTFT shape | Cells won | Lane won |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for fw, ln in rep["lanes"].items():
        b, x = ln["blis"], ln["estimator"]
        L.append(f"| {fw} | {b['points']} | {_f(b['coverage_pct'], 1)} | {_f(x['coverage_pct'], 1)} | {_f(b['tpot_mape_pct'])} | "
                 f"{_f(x['tpot_mape_pct'])} | {_f(b['ttft_mape_pct'])} | {_f(x['ttft_mape_pct'])} | {_f(b['tpot_shape_pct'])} | "
                 f"{_f(x['tpot_shape_pct'])} | {_f(b['ttft_shape_pct'])} | {_f(x['ttft_shape_pct'])} | "
                 f"{ln['cells_won']} of {ln['cells']} | {'won' if ln['won'] else 'lost'} |")
    L += ["", f"The same metric over only the points BLIS covers, so the errors compare like with like (coverage aside):", "",
          f"| Lane | Points both cover | BLIS TPOT MAPE | {est} | BLIS TTFT MAPE | {est} | BLIS TPOT shape | {est} | BLIS TTFT shape | {est} |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for fw, ln in rep["lanes"].items():
        x = ln.get("estimator_on_blis_points")
        if not x:
            L.append(f"| {fw} | 0 | - | - | - | - | - | - | - | - |")
            continue
        b = ln["blis"]
        L.append(f"| {fw} | {x['points']} | {_f(b['tpot_mape_pct'])} | {_f(x['tpot_mape_pct'])} | {_f(b['ttft_mape_pct'])} | "
                 f"{_f(x['ttft_mape_pct'])} | {_f(b['tpot_shape_pct'])} | {_f(x['tpot_shape_pct'])} | {_f(b['ttft_shape_pct'])} | "
                 f"{_f(x['ttft_shape_pct'])} |")
    L += ["", "## Every cell", "",
          f"| Framework | Chip | Model | Mode | Points | Withheld | BLIS coverage % | {est} coverage % | BLIS TPOT MAPE | {est} | "
          f"BLIS TTFT MAPE | {est} | BLIS TPOT shape | {est} | BLIS TTFT shape | {est} | Result | BLIS uncovered, by reason |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rep["cells"]:
        b, x = r["blis"], r["estimator"]
        unc = ", ".join(f"{k} {v}" for k, v in r["blis_uncovered"].items()) or "-"
        L.append(f"| {r['framework']} | {r['gpu']} | {r['model']} | {r['mode']} | {b['points']} | {r['withheld']} | "
                 f"{_f(b['coverage_pct'], 1)} | {_f(x['coverage_pct'], 1)} | {_f(b['tpot_mape_pct'])} | {_f(x['tpot_mape_pct'])} | "
                 f"{_f(b['ttft_mape_pct'])} | {_f(x['ttft_mape_pct'])} | {_f(b['tpot_shape_pct'])} | {_f(x['tpot_shape_pct'])} | "
                 f"{_f(b['ttft_shape_pct'])} | {_f(x['ttft_shape_pct'])} | {'won' if r['won'] else 'lost'} | {unc} |")
    return "\n".join(L) + "\n"


def log_evaluation(path: Path, commit: str, label: str, entries: list[dict]) -> list[str]:
    """Append the evaluation's rows to the log and return them, so the report can name the rows it was logged as."""
    import compare as cmp
    kinds = {}
    for k in ("test", "prospective"):
        es = [e for e in entries if e["kind"] == k]
        kinds[k] = {"points": len(es), "scored": sum(e.get("blis_tpot") is not None for e in es)}
    return cmp.evaluation_log(path, commit, label, {"kinds": kinds})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("points")
    for k in ("zip", "pin", "extractor", "out"):
        p.add_argument(f"--{k}", required=True, type=Path)
    m = sub.add_parser("match")
    for k in ("points", "dump-rows", "ledger", "extractor", "out"):
        m.add_argument(f"--{k}", required=True, type=Path)
    m.add_argument("--units-out", type=Path)
    f = sub.add_parser("freeze")
    for k in ("match", "dump-rows", "ledger", "out", "cache"):
        f.add_argument(f"--{k}", required=True, type=Path)
    f.add_argument("--download-workers", type=int, default=4)
    f.add_argument("--errors-out", required=True, type=Path, help="the units the pull could not read, with the error")
    r = sub.add_parser("report")
    for k in ("points", "match", "contract", "splits", "out", "pull-errors"):
        r.add_argument(f"--{k}", required=True, type=Path)
    r.add_argument("--estimator", required=True, help="the artifact's estimator, as its point fields name it")
    r.add_argument("--evaluate-test", action="store_true")
    r.add_argument("--log", type=Path)
    r.add_argument("--label", help="the evaluation log's estimator column for a logged test evaluation")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "points":
            prov = extract_points(a.zip, a.pin, a.extractor, a.out)
            print(json.dumps(prov, sort_keys=True))
        elif a.cmd == "match":
            pts = json.loads(a.points.read_text())
            rows = [json.loads(x) for x in a.dump_rows.read_text().splitlines() if x.strip()]
            through = pts["snapshot"]["measurement_date_through"]
            got = match(pts, rows, slugs_of(a.extractor), through)
            place(got, a.ledger)
            a.out.write_text(json.dumps({"format": "matched-points-1", "through": through, "points": got},
                                        indent=0, sort_keys=True) + "\n")
            if a.units_out:
                a.units_out.write_text("".join(f"{u}\n" for u in sorted({e["unit"] for e in got if e.get("unit")})))
            n = sum(1 for e in got if e.get("unit"))
            print(f"{n} of {len(got)} points matched to a ledger unit")
        elif a.cmd == "freeze":
            got = json.loads(a.match.read_text())["points"]
            rows = [json.loads(x) for x in a.dump_rows.read_text().splitlines() if x.strip()]
            return freeze(got, rows, ledger_dir=a.ledger, out=a.out, cache=a.cache, workers=a.download_workers,
                          errors_out=a.errors_out)
        else:
            if a.evaluate_test and not (a.log and a.label):
                raise MatchError("--evaluate-test needs --log and --label: a test evaluation is logged")
            pts = json.loads(a.points.read_text())
            matched_ = json.loads(a.match.read_text())["points"]
            contract = read_contract(a.contract)
            for unit, err in json.loads(a.pull_errors.read_text()).items():
                if unit not in contract:
                    contract[unit] = {"status": "not_frozen", "grade": None,
                                      "reason": "record_gone: " + ("HTTP 404" if "404" in err else err[:40])}
            splits = json.loads(a.splits.read_text())
            entries = entries_for(pts, matched_, contract, splits, a.estimator, a.evaluate_test)
            prov = json.loads((a.contract / "provenance.json").read_text())
            provenance = {"harness_commit": prov.get("harness_commit"), "simulator": (prov.get("simulator") or {}).get("build"),
                          "catalog": (prov.get("blis") or {}).get("catalog"), "fields_sha256": prov.get("fields_sha256"),
                          "experimental": prov.get("experimental"),
                          "artifact": pts["snapshot"].get("campaign", {}).get("run_id"),
                          "measurement_source_url": pts.get("measurement_source_url")}
            rows = log_evaluation(a.log, prov.get("harness_commit"), a.label, entries) if a.evaluate_test else None
            rep = build_report(entries, a.estimator, provenance, a.evaluate_test, rows)
            Path(f"{a.out}.json").write_text(json.dumps(rep, indent=1, sort_keys=True) + "\n")
            Path(f"{a.out}.md").write_text(markdown(rep))
            print(f"wrote {a.out}.json and .md")
    except MatchError as e:
        print(f"matched: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
