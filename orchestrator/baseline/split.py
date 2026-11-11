"""The development split of InferenceX points, for choosing and checking estimators.

This is a DEVELOPMENT split, labelled as such wherever it is used: it is separate from the ledger's
official anchor list (design D7, COV-2: roles drawn from a seed no candidate job can read), which
stays the ledger owners'. A figure on this split's test set is "development split, not the ledger's
held-out". See docs/m2/evaluation-protocol.md.

  GROUP     the InferenceX series: model, hardware, framework, precision, spec_method, disagg,
            benchmark_type, ISL, OSL and image. Rows of one series are never split: adjacent
            concurrency points are near-duplicates and would leak.
  ASSIGN    sha256(SALT, "\0", series id), first 8 bytes as an integer, mod 100: below TRAIN_PCT
            train, below TRAIN_PCT + VALIDATION_PCT validation, else test.
  PROSPECTIVE  a point measured after FREEZE_DATE is test whatever its series hashes to, is never
            used in a fit or a selection, and is reported apart.

The constants are pinned by a test. The registry's fitters read the published list
docs/m2/series-split.json (series id to split, with the row ids and run ids of each series), or call
split_of on a series; either gives the same answer.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

SALT = "blis-dev-split-1"
TRAIN_PCT, VALIDATION_PCT = 60, 20            # the rest, 20, is test
FREEZE_DATE = "2026-11-09"                    # the date of the frozen pull; later points are prospective
SERIES_FIELDS = ("model", "hardware", "framework", "precision", "spec_method", "disagg", "benchmark_type",
                 "isl", "osl", "image")
SPLITS = ("train", "validation", "test")
KINDS = ("train", "validation", "test", "prospective")     # prospective is a subset of test


class SplitError(ValueError):
    pass


def _image(ref) -> str:
    return str(ref or "").split("@", 1)[0]


def _int(x):
    return None if x is None else int(x)


def from_row(row: dict) -> dict:
    """The series of an InferenceX API row."""
    return {"model": row["model"], "hardware": row["hardware"], "framework": row["framework"],
            "precision": row["precision"], "spec_method": row.get("spec_method") or "none",
            "disagg": bool(row.get("disagg")), "benchmark_type": row["benchmark_type"],
            "isl": _int(row.get("isl")), "osl": _int(row.get("osl")), "image": _image(row.get("image"))}


def from_contract(facets: dict) -> dict:
    """The series of a scored point of a contract directory: its facets and identity carry the same
    fields as the row (the facet `model` is the catalog's name, so the identity's slug is used)."""
    ident = facets["identity"]
    w = str(facets["workload"]).split(":")
    isl, osl = (int(w[0]), int(w[1])) if len(w) == 2 and all(x.isdigit() for x in w) else (None, None)
    return {"model": ident["model"], "hardware": ident["hardware"], "framework": ident["framework"],
            "precision": ident["precision"], "spec_method": facets.get("spec_method") or "none",
            "disagg": facets.get("serving") == "disaggregated", "benchmark_type": ident["benchmark_type"],
            "isl": isl, "osl": osl, "image": _image(facets.get("image"))}


def series_id(series: dict) -> str:
    """The series as one canonical string: its fields in SERIES_FIELDS order."""
    missing = [f for f in SERIES_FIELDS if f not in series]
    if missing:
        raise SplitError(f"a series names {missing} too")
    return json.dumps([series[f] for f in SERIES_FIELDS], separators=(",", ":"), ensure_ascii=False)


def bucket(sid: str) -> int:
    """0 to 99, from the salt and the series id."""
    h = hashlib.sha256(SALT.encode() + b"\0" + sid.encode()).digest()
    return int.from_bytes(h[:8], "big") % 100


def split_of(series) -> str:
    """train, validation or test, for a series (a dict of SERIES_FIELDS or its id string). The date
    of a point does not enter: see kind_of for the prospective override."""
    b = bucket(series if isinstance(series, str) else series_id(series))
    return "train" if b < TRAIN_PCT else "validation" if b < TRAIN_PCT + VALIDATION_PCT else "test"


def kind_of(series, measured_date: str | None) -> str:
    """train, validation, test or prospective: a point measured after FREEZE_DATE is prospective."""
    if measured_date and str(measured_date)[:10] > FREEZE_DATE:
        return "prospective"
    return split_of(series)


def usable_for_fit(series, measured_date: str | None) -> bool:
    """Only train, and never a prospective point, may feed a fit; train and validation may feed a
    selection (leave-one-group-out)."""
    return kind_of(series, measured_date) == "train"


def usable_for_selection(series, measured_date: str | None) -> bool:
    return kind_of(series, measured_date) in ("train", "validation")


def logo_folds(points: list[dict]):
    """Leave-one-group-out folds over the train and validation points: yields (held_out_series_id,
    fit_points, held_out_points). `points` each carry "series" (an id) and "kind". Test and
    prospective points are dropped before the folds exist."""
    pool = [p for p in points if p["kind"] in ("train", "validation")]
    for sid in sorted({p["series"] for p in pool}):
        yield sid, [p for p in pool if p["series"] != sid], [p for p in pool if p["series"] == sid]


def assign_manifest(manifest: dict) -> dict:
    """point id to {"series", "kind"} for every point of a pull's manifest (the row gives the series,
    the unit's identity its measured date)."""
    out = {}
    for p in manifest["points"]:
        sid = series_id(from_row(p["row"]))
        out[p["point_id"]] = {"series": sid, "kind": kind_of(sid, (p.get("identity") or {}).get("measured_date"))}
    return out


# ------------------------------------------------------------------------------ the published list

def series_list(rows: list[dict]) -> dict:
    """The list the registry's fitters read: every series of the rows, its split, and its row ids and
    workflow run ids (so a coefficient's citation of a row or a run can be checked)."""
    out: dict = {}
    for r in rows:
        sid = series_id(from_row(r))
        e = out.setdefault(sid, {"split": split_of(sid), "rows": [], "runs": set(), "dates": [0, 0]})
        e["rows"].append(str(r["id"]))
        m = re.search(r"/runs/(\d+)", str(r.get("run_url") or ""))
        if m:
            e["runs"].add(m.group(1))
    doc = {"salt": SALT, "train_pct": TRAIN_PCT, "validation_pct": VALIDATION_PCT, "freeze_date": FREEZE_DATE,
           "fields": list(SERIES_FIELDS), "series": {}}
    for sid in sorted(out):
        e = out[sid]
        doc["series"][sid] = {"split": e["split"], "rows": sorted(e["rows"], key=lambda x: (len(x), x)),
                              "runs": sorted(e["runs"])}
    return doc


def check_list(doc: dict) -> list[str]:
    """Problems with a published list: constants that differ from this module's, or a split that is
    not what the rule gives."""
    out = []
    for k, want in (("salt", SALT), ("train_pct", TRAIN_PCT), ("validation_pct", VALIDATION_PCT),
                    ("freeze_date", FREEZE_DATE), ("fields", list(SERIES_FIELDS))):
        if doc.get(k) != want:
            out.append(f"{k} is {doc.get(k)!r}, the module's is {want!r}")
    for sid, e in (doc.get("series") or {}).items():
        if e.get("split") != split_of(sid):
            out.append(f"series {sid}: split {e.get('split')!r}, the rule gives {split_of(sid)!r}")
    return out


# ------------------------------------------------------------------------- the citation check

_UNIT = re.compile(r"\b[0-9a-f]{64}\b")
_ROW = re.compile(r"\b(?:row|rows|record|records)\s+#?(\d+(?:\s*(?:,|and)\s*\d+)*)", re.I)
_RUN = re.compile(r"\bruns?\s+#?(\d+(?:\s*(?:,|and)\s*\d+)*)", re.I)


def cited_withheld(cite: str, doc: dict) -> list[str]:
    """What a citation text cites that belongs to a validation or test series of the published list:
    InferenceX benchmark row ids ("row 123456"), and workflow run ids when the citation names
    InferenceX and not CollectiveX (a CollectiveX run is a kernel sweep, not a benchmark series).
    A coefficient may cite a train series only."""
    withheld_rows, withheld_runs = {}, {}
    for sid, e in doc["series"].items():
        if e["split"] != "train":
            for r in e["rows"]:
                withheld_rows[r] = sid
            for r in e["runs"]:
                withheld_runs[r] = sid
    hits = []
    for m in _ROW.finditer(cite):
        for n in re.findall(r"\d+", m.group(1)):
            if n in withheld_rows:
                hits.append(f"row {n} (series {withheld_rows[n]})")
    if "inferencex" in cite.lower() and "collectivex" not in cite.lower():
        for m in _RUN.finditer(cite):
            for n in re.findall(r"\d+", m.group(1)):
                if n in withheld_runs:
                    hits.append(f"run {n} (series {withheld_runs[n]})")
    return hits


def check_registry(registry: Path, doc: dict) -> list[str]:
    """Every coefficient entry whose citations name a validation or test InferenceX series. The
    registry's own CI runs this against the published list at a pinned commit; the dashboard never
    reads a registry file (X7)."""
    import yaml
    out = []
    for f in sorted(Path(registry).glob("coefficients/*.yaml")):
        data = yaml.safe_load(f.read_text()) or {}
        for ent in data.get("coefficients") or []:
            for name, body in (ent.items() if isinstance(ent, dict) else []):
                for s in (body or {}).get("sources") or []:
                    for hit in cited_withheld(str(s.get("cite", "")), doc):
                        out.append(f"{f.name}: {name} cites {hit}")
    return out


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    l = sub.add_parser("list", help="write the published series list from API rows (a JSON list)")
    l.add_argument("--rows", required=True)
    l.add_argument("--out", required=True)
    s = sub.add_parser("splits", help="write point id -> series and split for a frozen pull")
    s.add_argument("--pull", required=True)
    s.add_argument("--out", required=True)
    c = sub.add_parser("check-list")
    c.add_argument("list")
    r = sub.add_parser("check-registry", help="fail if a coefficient cites a validation or test series")
    r.add_argument("--registry", required=True)
    r.add_argument("--list", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "list":
        doc = series_list(json.loads(Path(a.rows).read_text()))
        Path(a.out).write_text(json.dumps(doc, indent=1, sort_keys=False) + "\n")
        print(f"wrote {a.out}: {len(doc['series'])} series")
        return 0
    if a.cmd == "splits":
        m = json.loads((Path(a.pull) / "manifest.json").read_text())
        doc = assign_manifest(m)
        Path(a.out).write_text(json.dumps(doc, indent=0, sort_keys=True) + "\n")
        from collections import Counter
        print(f"wrote {a.out}: {dict(Counter(v['kind'] for v in doc.values()))}")
        return 0
    doc = json.loads(Path(a.list).read_text())
    problems = check_list(doc) if a.cmd == "check-list" else check_list(doc) + check_registry(Path(a.registry), doc)
    for p in problems:
        print(p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
