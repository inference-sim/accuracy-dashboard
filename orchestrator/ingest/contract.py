"""The extractor-to-summary contract (Discussion #28; orchestrator/ingest/CONTRACT.md).

Shared by both sides: the extractor (#29) writes a contract directory and the summary builder
(build_summary_v2.py, which writes summary v3) reads one. This module holds only what both must
agree on byte-for-byte: the point identity, the canonical JSON encoding, the file names, and a
validator for a contract directory. It runs nothing in the nightly pipeline.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build_summary import EXPECTED_HEADER  # noqa: E402

INGEST_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(INGEST_DIR))
import grade as gr  # noqa: E402

# The dashboard defines no schema for a point's fidelity record: the per-point record is the substrate's PointRecord (SUB-19), which
# the harness writes as pointrecords.jsonl and `blis schema validate point-record` validates (point_record_problems). What the
# dashboard owns are its own lists, not_scored.jsonl and failed.jsonl, whose definitions live in the summary schema.
LISTS_SCHEMA = INGEST_DIR.parent.parent / "schemas" / "summary.v3.json"

POINTS_CSV = "points.csv"
FIDELITY_JSONL = "fidelity.jsonl"
FACETS_JSON = "facets.json"
# The facets every scored point must carry: what the summary builder groups and labels it by.
FACET_KEYS = ("framework", "gpu", "identity", "model", "parallelism", "precision", "scenario", "serving",
              "spec_method", "sweep_id", "workload")
NOT_SCORED_JSONL = "not_scored.jsonl"
POINTRECORDS_JSONL = "pointrecords.jsonl"
FAILED_JSONL = "failed.jsonl"
PROVENANCE_JSON = "provenance.json"
CONTRACT_FILES = (POINTS_CSV, FIDELITY_JSONL, FACETS_JSON, NOT_SCORED_JSONL, FAILED_JSONL, POINTRECORDS_JSONL,
                  PROVENANCE_JSON)

# The per-point CSV columns build_summary.py reads, with its tier column replaced by the point's
# grade, then the two the contract adds.
GRADE_COLUMN = "grade"
POINTS_HEADER = EXPECTED_HEADER[:-1] + [GRADE_COLUMN, "point_id", "measured_date"]
assert EXPECTED_HEADER[-1] == "tier_unbracketed"

# A point's identity is its ledger unit's identity (design §10.2; blis-substrate
# ledger/inferencex/inferencex.go at 800ae263, IdentityFields): the source plus ten InferenceX
# fields. The point_id is the unit_id, so a point is matched to its unit by identifier and the
# id never changes with a BLIS release or a catalog mapping.
SOURCE = "inferencex"
IDENTITY_FIELDS = (
    "source", "model", "hardware", "precision", "framework", "benchmark_type",
    "configuration_hash", "recipe_fingerprint", "conc", "measured_date", "benchmark_run",
)
# The 17 fields of a record's serving configuration that the configuration hash covers, in
# InferenceX's own names (design §10.2).
CONFIGURATION_FIELDS = (
    "image", "isl", "osl", "offload_mode", "spec_method", "disagg", "is_multinode",
    "prefill_tp", "prefill_ep", "prefill_dp_attention", "prefill_num_workers", "num_prefill_gpu",
    "decode_tp", "decode_ep", "decode_dp_attention", "decode_num_workers", "num_decode_gpu",
)
DIGEST_MARK = "@sha256:"
_RUN_ID = re.compile(r"/actions/runs/(\d+)")


def canonical_dumps(value) -> str:
    """The one JSON encoding every contract file uses: sorted keys, no spaces, UTF-8 kept. It is
    the encoding blis-substrate's ledger.Canonical writes, so a point_id equals its unit_id."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def benchmark_run(run_url) -> int | None:
    """The numeric GitHub Actions run id in a run_url, without its attempt number; None when the
    record has no run_url or the URL names no run."""
    m = _RUN_ID.search(run_url) if isinstance(run_url, str) else None
    return int(m.group(1)) if m else None


def configuration(row: dict) -> dict:
    """The 17 configuration fields of an InferenceX record, every key present, a value the
    record lacks as None, integers and booleans as the record types them. The image is written
    without any suffix beginning "@sha256:", because InferenceX records the digest on some
    attempts of a run and not on others."""
    out = {}
    for f in CONFIGURATION_FIELDS:
        v = row.get(f)
        if isinstance(v, float):
            raise ValueError(f"row {row.get('id')}: {f} is a float ({v!r}); identifying fields hold no fractions")
        out[f] = v
    if isinstance(out["image"], str):
        out["image"] = out["image"].split(DIGEST_MARK, 1)[0]
    return out


def configuration_hash(row: dict) -> str:
    return hashlib.sha256(canonical_dumps(configuration(row)).encode("utf-8")).hexdigest()


def run_dates(rows) -> dict:
    """The measured date of each benchmark run: the earliest date among every record of the run,
    so all its attempts share one date (design §10.2). Every record counts, whatever its
    framework or measured values."""
    out: dict = {}
    for r in rows:
        run = benchmark_run(r.get("run_url"))
        if run is not None:
            d = str(r.get("date"))[:10]
            if run not in out or d < out[run]:
                out[run] = d
    return out


def unit_identity(row: dict, dates: dict) -> dict:
    """An InferenceX record's identity, as the ledger's ingest tool computes it. `dates` is
    run_dates() over every record of the source, so a record with a run id takes its run's
    earliest date; a record with no run id keeps its own date."""
    run = benchmark_run(row.get("run_url"))
    if run is not None and run not in dates:
        raise ValueError(f"row {row.get('id')}: benchmark run {run} has no measured date in the records given")
    conc = row.get("conc")
    if isinstance(conc, str) and conc.isdigit():
        conc = int(conc)
    return {"source": SOURCE, "model": row["model"], "hardware": row["hardware"],
            "precision": row["precision"], "framework": row["framework"],
            "benchmark_type": row["benchmark_type"], "configuration_hash": configuration_hash(row),
            "recipe_fingerprint": row.get("recipe_fingerprint") or None, "conc": conc,
            "measured_date": dates[run] if run is not None else str(row["date"])[:10],
            "benchmark_run": run}


def point_id(identity: dict) -> str:
    """sha256 (hex) of the canonical JSON of exactly IDENTITY_FIELDS: the unit_id."""
    if not isinstance(identity, dict):
        raise ValueError("identity must be an object")
    missing = [f for f in IDENTITY_FIELDS if f not in identity]
    extra = [f for f in identity if f not in IDENTITY_FIELDS]
    if missing or extra:
        raise ValueError(f"identity fields: missing {missing}, unexpected {extra}")
    if not isinstance(identity["conc"], int) or isinstance(identity["conc"], bool):
        raise ValueError("identity conc must be an int")
    run = identity["benchmark_run"]
    if run is not None and (not isinstance(run, int) or isinstance(run, bool)):
        raise ValueError("identity benchmark_run must be an int or null")
    fp = identity["recipe_fingerprint"]
    if fp is not None and (not isinstance(fp, str) or not fp):
        raise ValueError("identity recipe_fingerprint must be a non-empty string or null")
    if identity["source"] != SOURCE:
        raise ValueError(f"identity source must be {SOURCE!r}")
    return hashlib.sha256(canonical_dumps(identity).encode("utf-8")).hexdigest()


def ratio_str(numerator, denominator) -> str | None:
    """A ratio as a 4-significant-figure string, trailing zeros kept ("1.000", "1.048", "12.35").
    None when it's undefined (a zero or missing denominator)."""
    if numerator is None or not denominator:
        return None
    return f"{numerator / denominator:#.4g}".rstrip(".")


def points_sort_key(row: dict) -> tuple:
    """The order points.csv rows are written in."""
    return (row["scenario"], row["label"], int(row["concurrency"]), row["measured_date"], row["point_id"])


# A row the pull itself failed to read. Never a valid reason in a published contract.
PULL_ERROR = "artifact_unmatched:pull_error"
PROVENANCE_KEYS = ("ingest", "blis", "simulator", "harness_commit", "experimental", "units", "engine", "points", "left_out_records", "vllm_ref", "vllm_max_distance",
                   "fields_sha256", "pulled_at", "corpora", "pull_manifest_sha256", "source")


def _read_json(path: Path, problems: list[str]):
    """The parsed file, or None after recording why it couldn't be read."""
    try:
        text = path.read_text()
        value = json.loads(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        problems.append(f"{path.name}: unreadable: {e}")
        return None
    if text.rstrip("\n") != canonical_dumps(value):
        problems.append(f"{path.name} is not canonical JSON")
    return value


def _read_jsonl(path: Path, problems: list[str]) -> list[tuple[int, dict]]:
    """(line number, object) per line; malformed or non-canonical lines are recorded."""
    out = []
    try:
        lines = path.read_text().splitlines()
    except (OSError, UnicodeDecodeError) as e:
        problems.append(f"{path.name}: unreadable: {e}")
        return out
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as e:
            problems.append(f"{path.name}:{n}: not JSON: {e}")
            continue
        if not isinstance(value, dict):
            problems.append(f"{path.name}:{n}: not an object")
            continue
        if line != canonical_dumps(value):
            problems.append(f"{path.name}:{n}: not canonical JSON")
        out.append((n, value))
    return out


def _sorted_by(items, key) -> bool:
    keys = [key(x) for x in items]
    return keys == sorted(keys)


# What every point of one sweep shares: a sweep is one measured curve of one deployment.
SWEEP_SHARED = ("scenario", "label", "workload", "spec_method", "vllm_version", "precision", "parallelism")


def _sweep_problems(facets: dict, point_rows: list[dict]) -> list[str]:
    """A sweep (facets' sweep_id) holds at most one point per concurrency, and its points are
    one deployment: the shape metric anchors each curve at its lowest concurrency."""
    out = []
    sweeps: dict = {}
    for r in point_rows:
        f = facets.get(r["point_id"])
        if isinstance(f, dict) and "sweep_id" in f:
            sweeps.setdefault(f["sweep_id"], []).append((r, f))
    for sid, members in sorted(sweeps.items()):
        concs = [r["concurrency"] for r, _ in members]
        if len(concs) != len(set(concs)):
            out.append(f"{FACETS_JSON}: sweep {sid} has two points at one concurrency")
        for key in SWEEP_SHARED:
            if len({canonical_dumps(f.get(key)) for _, f in members}) > 1:
                out.append(f"{FACETS_JSON}: sweep {sid} mixes {key}")
    return out


def validate_dir(directory: str | Path) -> list[str]:
    """Every way a contract directory breaks CONTRACT.md; empty means valid. Never raises on
    malformed content: each problem is reported instead.

    Checks: the six files exist and parse; JSON is canonical; the CSV header and its rows'
    order; every scored id is in points.csv, fidelity.jsonl and facets.json exactly once and
    nowhere else; each id hashes from its identity, and the CSV agrees with that identity
    (concurrency, measured_date) and with its record's grade; each sweep is one deployment with
    one point per concurrency; fidelity, not-scored and failed records pass the schema; lists
    are sorted; every point has one grade with every substitution named, every G5 reason is on
    design §11.4's list, and each grade agrees with the point's own release and the engine
    release the run was scored on (grade.check: COV-4, COV-5, COV-6); scored, not-scored and
    failed points are disjoint and their counts sum to provenance's point count (COV-1).
    """
    import jsonschema

    d = Path(directory)
    problems: list[str] = []
    for name in CONTRACT_FILES:
        if not (d / name).is_file():
            problems.append(f"missing {name}")
    if problems:
        return problems

    schema = json.loads(LISTS_SCHEMA.read_text())
    sub = lambda name: jsonschema.Draft7Validator({**schema["definitions"][name], "definitions": schema["definitions"]})  # noqa: E731
    ns_validator, failed_validator = sub("notScored"), sub("failed")

    # ---- points.csv
    point_rows: list[dict] = []
    try:
        with open(d / POINTS_CSV, newline="") as fh:
            reader = csv.reader(fh)
            header = next(reader, None)
            if header != POINTS_HEADER:
                problems.append(f"{POINTS_CSV} header {header} != {POINTS_HEADER}")
                return problems
            for n, r in enumerate(reader, 2):
                if not r:
                    continue
                if len(r) != len(POINTS_HEADER):
                    problems.append(f"{POINTS_CSV}:{n}: {len(r)} columns, expected {len(POINTS_HEADER)}")
                    continue
                point_rows.append({"_line": n, **dict(zip(header, r))})
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        problems.append(f"{POINTS_CSV}: unreadable: {e}")
        return problems
    scored_ids = [r["point_id"] for r in point_rows]
    scored = set(scored_ids)
    if len(scored) != len(scored_ids):
        problems.append(f"{POINTS_CSV}: duplicate point_id")
    for r in point_rows:
        if r[GRADE_COLUMN] not in gr.GRADED:
            problems.append(f"{POINTS_CSV}:{r['_line']}: grade {r[GRADE_COLUMN]!r} is not one of {gr.GRADED}")
        if not r["concurrency"].isdigit():
            problems.append(f"{POINTS_CSV}:{r['_line']}: concurrency {r['concurrency']!r} is not an integer")
    if all(r["concurrency"].isdigit() for r in point_rows) and not _sorted_by(point_rows, points_sort_key):
        problems.append(f"{POINTS_CSV}: rows are not in (scenario, label, concurrency, measured_date, point_id) order")

    # ---- facets.json
    facets = _read_json(d / FACETS_JSON, problems)
    if facets is not None and not isinstance(facets, dict):
        problems.append(f"{FACETS_JSON}: not an object")
        facets = None
    if facets is not None:
        if set(facets) != scored:
            problems.append(f"{FACETS_JSON} ids != {POINTS_CSV} ids")
        for r in point_rows:
            pid = r["point_id"]
            f = facets.get(pid)
            if not isinstance(f, dict):
                problems.append(f"{FACETS_JSON}: {pid[:12]} missing or not an object")
                continue
            missing = [k for k in FACET_KEYS if k not in f]
            if missing:
                problems.append(f"{FACETS_JSON}: {pid[:12]} lacks {', '.join(missing)}")
                continue
            ident = f.get("identity")
            try:
                if point_id(ident) != pid:
                    problems.append(f"{FACETS_JSON}: {pid[:12]} identity hashes to a different id")
            except ValueError as e:
                problems.append(f"{FACETS_JSON}: {pid[:12]} identity invalid: {e}")
                continue
            if ident["measured_date"] != r["measured_date"]:
                problems.append(f"{POINTS_CSV}:{r['_line']}: measured_date disagrees with its identity")
            if str(ident["conc"]) != r["concurrency"]:
                problems.append(f"{POINTS_CSV}:{r['_line']}: concurrency disagrees with its identity")
        problems += _sweep_problems(facets, point_rows)

    # ---- fidelity.jsonl
    fid_lines = _read_jsonl(d / FIDELITY_JSONL, problems)
    fidelity: dict = {}
    for n, rec in fid_lines:
        pid = rec.get("point_id")
        body = {k: v for k, v in rec.items() if k != "point_id"}
        if not isinstance(body.get("grade"), str):
            problems.append(f"{FIDELITY_JSONL}:{n}: no grade")
        if isinstance(body.get("args"), list) and not _sorted_by(body["args"], lambda a: str(a.get("arg"))):
            problems.append(f"{FIDELITY_JSONL}:{n}: args are not sorted by arg")
        if isinstance(body.get("resolved"), list) and not _sorted_by(body["resolved"], lambda q: str(q.get("quantity"))):
            problems.append(f"{FIDELITY_JSONL}:{n}: resolved is not sorted by quantity")
        subs = body.get("substitutions")
        if isinstance(subs, list) and not _sorted_by(subs, lambda x: (str(x.get("kind")), str(x.get("subject")))):
            problems.append(f"{FIDELITY_JSONL}:{n}: substitutions are not sorted by kind, subject")
        if pid in fidelity:
            problems.append(f"{FIDELITY_JSONL}: duplicate point_id {str(pid)[:12]}")
        fidelity[pid] = body
    if not _sorted_by(fid_lines, lambda x: str(x[1].get("point_id"))):
        problems.append(f"{FIDELITY_JSONL}: lines are not sorted by point_id")
    if set(fidelity) != scored:
        problems.append(f"{FIDELITY_JSONL} ids != {POINTS_CSV} ids")
    grades = {r["point_id"]: r[GRADE_COLUMN] for r in point_rows}
    for pid in scored_ids:
        rec = fidelity.get(pid)
        if rec is not None and rec.get("grade") != grades[pid]:
            problems.append(f"{POINTS_CSV}: {pid[:12]} is graded {grades[pid]!r}, its record {rec.get('grade')!r}")

    # ---- not_scored.jsonl and failed.jsonl
    def records(name, v, what):
        lines = _read_jsonl(d / name, problems)
        ids = [str(x.get("point_id")) for _, x in lines]
        if len(set(ids)) != len(ids):
            problems.append(f"{name}: duplicate point_id")
        if ids != sorted(ids):
            problems.append(f"{name}: lines are not sorted by point_id")
        for n, x in lines:
            for err in v.iter_errors(x):
                loc = "/".join(str(p) for p in err.path) or "(root)"
                problems.append(f"{name}:{n} at {loc}: {err.message[:200]}")
            if x.get("point_id") in scored:
                problems.append(f"{name}:{n}: {str(x.get('point_id'))[:12]} is also scored")
            try:
                if point_id(x.get("identity")) != x.get("point_id"):
                    problems.append(f"{name}:{n}: identity hashes to a different id")
            except ValueError as e:
                problems.append(f"{name}:{n}: identity invalid: {e}")
        return lines
    ns_lines = records(NOT_SCORED_JSONL, ns_validator, "not scored")
    for n, ns in ns_lines:
        rs = ns.get("g5_reasons")
        if isinstance(rs, list) and rs != sorted(rs, key=lambda r: (str(r.get("code")), str(r.get("subject", "")))):
            problems.append(f"{NOT_SCORED_JSONL}:{n}: g5_reasons must be sorted by code, subject")
        if isinstance(rs, list) and ns.get("g5_reason") not in rs:
            problems.append(f"{NOT_SCORED_JSONL}:{n}: g5_reason is not one of its g5_reasons")
    # ---- pointrecords.jsonl: the substrate's record (pointrecord.py), one per scored or G5 point, or none
    # when no Result gave the run's data block. Its shape is the substrate validator's to check (test_pointrecord.py).
    pr_lines = _read_jsonl(d / POINTRECORDS_JSONL, problems)
    pr_ids = [str(x.get("point_id")) for _, x in pr_lines]
    if pr_ids and (pr_ids != sorted(pr_ids) or set(pr_ids) != scored | {str(x.get("point_id")) for _, x in ns_lines}
                   or len(pr_ids) != len(set(pr_ids))):
        problems.append(f"{POINTRECORDS_JSONL}: not one sorted record per scored and per G5 point")
    failed_lines = records(FAILED_JSONL, failed_validator, "failed")
    for n, x in failed_lines:
        fs = x.get("faults")
        if isinstance(fs, list) and fs != sorted(set(map(str, fs))):
            problems.append(f"{FAILED_JSONL}:{n}: faults must be sorted and unique")
    both = {x.get("point_id") for _, x in ns_lines} & {x.get("point_id") for _, x in failed_lines}
    if both:
        problems.append(f"{len(both)} point(s) are both not scored and failed")

    # ---- provenance.json
    prov = _read_json(d / PROVENANCE_JSON, problems)
    if prov is not None and not isinstance(prov, dict):
        problems.append(f"{PROVENANCE_JSON}: not an object")
        prov = None
    elif prov is not None:
        for key in PROVENANCE_KEYS:
            if key not in prov:
                problems.append(f"{PROVENANCE_JSON}: missing {key}")
        if prov.get("ingest", "api") != "api":
            problems.append(f"{PROVENANCE_JSON}: ingest must be 'api'")

    # ---- grades (COV-4, COV-5, COV-6) and the balance (COV-1)
    engine = ((prov or {}).get("engine") or {}).get("version")
    if prov is not None and not engine:
        problems.append(f"{PROVENANCE_JSON}: engine.version names no engine release")
    points = [{"point_id": pid, **rec, "build": {"release": rec.get("run_release")}} for pid, rec in fidelity.items()]
    points += [{**ns, "build": {"release": ns.get("run_release")}} for _, ns in ns_lines]
    if engine:
        # Failed points carry no grade, but were scored by the same simulator (COV-6).
        sims = [{"point_id": f.get("point_id"), "simulator": f.get("simulator"), "grade": gr.G5,
                 "g5_reason": {"code": gr.G5_CODES[0]}} for _, f in failed_lines]
        problems += [f"grade: {p}" for p in gr.check(points + sims, engine)]
        sim_build = ((prov or {}).get("simulator") or {}).get("build")
        if any((p.get("simulator") or {}).get("build") != sim_build for p in points + sims):
            problems.append(f"{PROVENANCE_JSON}: simulator.build {sim_build!r} is not the build every point names (COV-6)")
    total = (prov or {}).get("points")
    counted = len(scored) + len(ns_lines) + len(failed_lines)
    if isinstance(total, int) and total != counted:
        problems.append(f"{PROVENANCE_JSON}: points {total} != {len(scored)} scored + {len(ns_lines)} not scored "
                        f"+ {len(failed_lines)} failed (COV-1)")
    return problems


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: contract.py <contract-dir> [<contract-dir> ...]", file=sys.stderr)
        return 2
    bad = 0
    for directory in args:
        problems = validate_dir(directory)
        if problems:
            bad += 1
            print(f"INVALID: {directory}", file=sys.stderr)
            for p in problems:
                print(f"  {p}", file=sys.stderr)
        else:
            print(f"VALID: {directory}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())


def point_record_problems(directory, blis: str) -> list[str]:
    """The substrate's own validation of every record of pointrecords.jsonl: `blis schema validate point-record` on each, built from
    the pinned simulator and substrate (SUB-19). The dashboard checks the record against no schema of its own."""
    import subprocess
    import tempfile
    problems: list[str] = []
    lines = _read_jsonl(Path(directory) / POINTRECORDS_JSONL, problems)
    with tempfile.TemporaryDirectory() as t:
        for n, rec in lines:
            f = Path(t) / "record.json"
            f.write_text(json.dumps(rec))
            p = subprocess.run([blis, "schema", "validate", "point-record", str(f)], capture_output=True, text=True)
            if p.returncode != 0:
                problems.append(f"{POINTRECORDS_JSONL}:{n}: {(p.stdout + p.stderr).strip()[:400]}")
    return problems
