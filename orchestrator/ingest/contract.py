"""The extractor-to-summary contract (Discussion #28; orchestrator/ingest/CONTRACT.md).

Shared by both sides: the extractor (#29) writes a contract directory and the v2 summary
builder (#30) reads one. This module holds only what both must agree on byte-for-byte: the
point identity, the canonical JSON encoding, the file names, and a validator for a contract
directory. It runs nothing in the nightly pipeline.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build_summary import EXPECTED_HEADER  # noqa: E402

INGEST_DIR = Path(__file__).resolve().parent
FIDELITY_SCHEMA = INGEST_DIR / "fidelity.schema.json"

POINTS_CSV = "points.csv"
FIDELITY_JSONL = "fidelity.jsonl"
FACETS_JSON = "facets.json"
# The facets every scored point must carry: what the summary builder groups and labels it by.
FACET_KEYS = ("framework", "gpu", "identity", "model", "parallelism", "precision", "scenario", "serving",
              "spec_method", "sweep_id", "workload")
NOT_SCORED_JSONL = "not_scored.jsonl"
PROVENANCE_JSON = "provenance.json"
CONTRACT_FILES = (POINTS_CSV, FIDELITY_JSONL, FACETS_JSON, NOT_SCORED_JSONL, PROVENANCE_JSON)

# The signedprobe per-point CSV columns, then the two the contract adds.
POINTS_HEADER = EXPECTED_HEADER + ["point_id", "measured_date"]

# A point's identity, in InferenceX's own terms, so it never changes with a BLIS release or a
# catalog mapping. `recipe_fingerprint` is InferenceX's sha256 of the bound recipe; rows that
# have none are identified by their API row id instead ("row:<id>").
IDENTITY_FIELDS = (
    "model", "hardware", "precision", "framework", "benchmark_type",
    "recipe", "conc", "measured_date",
)


def canonical_dumps(value) -> str:
    """The one JSON encoding every contract file uses: sorted keys, no spaces, UTF-8 kept."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def recipe_key(recipe_fingerprint: str | None, row_id: str | int | None) -> str:
    """The `recipe` identity component: the fingerprint, else "row:<API row id>"."""
    if recipe_fingerprint:
        return recipe_fingerprint
    if row_id is None or str(row_id) == "":
        raise ValueError("a point needs a recipe_fingerprint or an API row id")
    return f"row:{row_id}"


def point_id(identity: dict) -> str:
    """sha256 (hex) of the canonical JSON of exactly IDENTITY_FIELDS."""
    if not isinstance(identity, dict):
        raise ValueError("identity must be an object")
    missing = [f for f in IDENTITY_FIELDS if f not in identity]
    extra = [f for f in identity if f not in IDENTITY_FIELDS]
    if missing or extra:
        raise ValueError(f"identity fields: missing {missing}, unexpected {extra}")
    if not isinstance(identity["conc"], int) or isinstance(identity["conc"], bool):
        raise ValueError("identity conc must be an int")
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


# A scored point's points.csv tier, by its fidelity status, in the tier strings
# build_summary.TIER_MAP already reads: an exact point is apples-to-apples; an approximate
# one (a setting BLIS can't state was approximated, or a vLLM build BLIS doesn't model) only
# counts in the "all" tier.
TIER_BY_STATUS = {"exact": "MEASURED-OR-RESOLVED", "approximate": "ALL (approximate)"}
PROVENANCE_KEYS = ("ingest", "blis", "vllm_ref", "vllm_max_distance", "policy_sha256", "pulled_at",
                   "corpus", "pull_manifest_sha256", "source")


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

    Checks: the five files exist and parse; JSON is canonical; the CSV header and its rows'
    order; every scored id is in points.csv, fidelity.jsonl and facets.json exactly once and
    nowhere else; each id hashes from its identity, and the CSV agrees with that identity
    (concurrency, measured_date); each sweep is one deployment with one point per concurrency;
    scored points are exact or approximate, with that status's tier; fidelity
    records and reasons pass the schema; lists are sorted; not-scored ids are unique, sorted,
    disjoint from scored ones, and carry sorted unique reasons; provenance has every key.
    """
    import jsonschema

    d = Path(directory)
    problems: list[str] = []
    for name in CONTRACT_FILES:
        if not (d / name).is_file():
            problems.append(f"missing {name}")
    if problems:
        return problems

    schema = json.loads(FIDELITY_SCHEMA.read_text())
    validator = jsonschema.Draft7Validator(schema)
    reason_validator = jsonschema.Draft7Validator(
        {**schema["definitions"]["reason"], "definitions": schema["definitions"]})
    note_validator = jsonschema.Draft7Validator(
        {**schema["definitions"]["note"], "definitions": schema["definitions"]})

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
        if r["tier_unbracketed"] not in TIER_BY_STATUS.values():
            problems.append(f"{POINTS_CSV}:{r['_line']}: tier {r['tier_unbracketed']!r} is not a scored tier")
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
        for err in validator.iter_errors(body):
            loc = "/".join(str(p) for p in err.path) or "(root)"
            problems.append(f"{FIDELITY_JSONL}:{n} at {loc}: {err.message}")
        if isinstance(body.get("args"), list) and not _sorted_by(body["args"], lambda a: str(a.get("arg"))):
            problems.append(f"{FIDELITY_JSONL}:{n}: args are not sorted by arg")
        if isinstance(body.get("resolved"), list) and not _sorted_by(body["resolved"], lambda q: str(q.get("quantity"))):
            problems.append(f"{FIDELITY_JSONL}:{n}: resolved is not sorted by quantity")
        if pid in fidelity:
            problems.append(f"{FIDELITY_JSONL}: duplicate point_id {str(pid)[:12]}")
        fidelity[pid] = body
    if not _sorted_by(fid_lines, lambda x: str(x[1].get("point_id"))):
        problems.append(f"{FIDELITY_JSONL}: lines are not sorted by point_id")
    if set(fidelity) != scored:
        problems.append(f"{FIDELITY_JSONL} ids != {POINTS_CSV} ids")
    tiers = {r["point_id"]: r["tier_unbracketed"] for r in point_rows}
    for pid in scored_ids:
        rec = fidelity.get(pid)
        if rec is None:
            continue
        want = TIER_BY_STATUS.get(rec.get("status"))
        if want is None:
            problems.append(f"{FIDELITY_JSONL}: scored point {pid[:12]} must be status exact or approximate")
        elif tiers[pid] != want:
            problems.append(f"{POINTS_CSV}: {pid[:12]} is status {rec['status']}, so its tier is {want!r}")

    # ---- not_scored.jsonl
    ns_lines = _read_jsonl(d / NOT_SCORED_JSONL, problems)
    ns_ids = [str(ns.get("point_id")) for _, ns in ns_lines]
    if len(set(ns_ids)) != len(ns_ids):
        problems.append(f"{NOT_SCORED_JSONL}: duplicate point_id")
    if ns_ids != sorted(ns_ids):
        problems.append(f"{NOT_SCORED_JSONL}: lines are not sorted by point_id")
    for n, ns in ns_lines:
        pid = ns.get("point_id")
        if pid in scored:
            problems.append(f"{NOT_SCORED_JSONL}:{n}: {str(pid)[:12]} is also scored")
        reasons = ns.get("reasons")
        if not isinstance(reasons, list) or not reasons:
            problems.append(f"{NOT_SCORED_JSONL}:{n}: no reasons")
            reasons = []
        elif reasons != sorted(set(map(str, reasons))):
            problems.append(f"{NOT_SCORED_JSONL}:{n}: reasons must be sorted and unique")
        for reason in reasons:
            if not reason_validator.is_valid(reason):
                problems.append(f"{NOT_SCORED_JSONL}:{n}: unknown reason {reason!r}")
        notes = ns.get("notes", [])
        if not isinstance(notes, list):
            problems.append(f"{NOT_SCORED_JSONL}:{n}: notes is not a list")
            notes = []
        for note in notes:
            if not note_validator.is_valid(note):
                problems.append(f"{NOT_SCORED_JSONL}:{n}: malformed note {note!r}")
            elif note["reason"] not in reasons:
                problems.append(f"{NOT_SCORED_JSONL}:{n}: note for {note['reason']!r}, which is not one of its reasons")
        note_reasons = [str(x.get("reason")) for x in notes if isinstance(x, dict)]
        if note_reasons != sorted(set(note_reasons)):
            problems.append(f"{NOT_SCORED_JSONL}:{n}: notes must be sorted by reason, one per reason")
        try:
            if point_id(ns.get("identity")) != pid:
                problems.append(f"{NOT_SCORED_JSONL}:{n}: identity hashes to a different id")
        except ValueError as e:
            problems.append(f"{NOT_SCORED_JSONL}:{n}: identity invalid: {e}")

    # ---- provenance.json
    prov = _read_json(d / PROVENANCE_JSON, problems)
    if prov is not None and not isinstance(prov, dict):
        problems.append(f"{PROVENANCE_JSON}: not an object")
    elif prov is not None:
        for key in PROVENANCE_KEYS:
            if key not in prov:
                problems.append(f"{PROVENANCE_JSON}: missing {key}")
        if prov.get("ingest", "api") != "api":
            problems.append(f"{PROVENANCE_JSON}: ingest must be 'api'")
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
