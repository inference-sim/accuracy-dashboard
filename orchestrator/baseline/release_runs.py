#!/usr/bin/env python3
"""Runs on the engine releases BLIS simulates, in every measurement source, at the source's latest data (#90).

No in-scope InferenceX point of the M2 pull ran vLLM v0.32.0, so none can reach G1 (docs/m3/baseline). This tool
reads each source at its latest published data, records the data revision it read, and lists the runs made on the
engine release BLIS runs (vLLM 0.32.0 in inference-sim v0.17.0's stack; SGLang 0.5.23, the release blis-sglang pins)
or on a release next to it, with counts, and with what each still needs before it can be graded: whether the
substrate's ledger holds it as a unit (only a unit is a point, design §10.2), and which G1 conditions its source's
data can decide.

A source is an adapter that yields one normalised record per measured run point:

    {"source", "record", "engine", "release", "build", "model", "hardware", "framework", "benchmark_type", "date"}

where `release` is the engine release the run's build names (None for a nightly or custom build) and `record` the
source's own id for the record. Two adapters exist:

  inferencex   the InferenceX API's /benchmarks rows (api.pull). The release is read from the image tag, as
               grade.run_release reads an official vLLM image with no banner (the server log's banner is read only
               when the point is frozen), and as m3_baseline.sglang_release reads an SGLang one.
  configiq     the Hugging Face dataset redhat-performance/configiq-performance-upstream-data: aggregate GuideLLM
               rows, one Parquet file per model and accelerator, `backend_version` "vLLM-X.Y.Z" (the dataset keeps
               only plain upstream release versions). Its records carry no run id, so `record` is the pair id and
               the row's index in its file at the pinned dataset commit.

A further source is a function from its files to these records and a revision; nothing else changes.

    release_runs.py report --inferencex-rows ROWS.json --inferencex-availability AVAIL.json --inferencex-read-at ISO
                           [--configiq DIR --configiq-commit SHA] --ledger LEDGER --ledger-revision TAG
                           --dump-tags TAGS.json --out PREFIX

ROWS.json is api.pull's rows, AVAIL.json the /availability body; DIR holds the dataset's manifest.json and its
pairs/<id>.parquet files, read with pyarrow (the dataset's own format; needed only for this source). None of these is
committed: the report keeps counts and record ids only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ingest"))
import m3_baseline as mb  # noqa: E402

FORMAT = "release-runs-1"
TARGETS = {"vllm": "0.32.0", "sglang": "0.5.23"}
_VLLM_IMAGE = re.compile(r"^vllm/vllm-openai(?:-rocm)?:v(\d+\.\d+\.\d+)$")
_CONFIGIQ_VERSION = re.compile(r"^vLLM-(\d+\.\d+\.\d+)$")
OUT_OF_SCOPE = ("mi300x", "mi325x", "mi355x")


class ReleaseError(ValueError):
    pass


def _parts(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def nearness(engine: str, release: str | None) -> str | None:
    """"target" for the release BLIS runs; "near" for the next release on either side (vLLM: another patch of the
    minor releases either side, 0.31.x and 0.33.x; SGLang, which releases by patch: 0.5.22 and 0.5.24, post releases
    included); None otherwise."""
    if release is None or engine not in TARGETS:
        return None
    t, r = _parts(TARGETS[engine]), _parts(release)
    if release == TARGETS[engine]:
        return "target"
    if engine == "vllm" and r[0] == t[0] and abs(r[1] - t[1]) == 1:
        return "near"
    if engine == "sglang" and r[:2] == t[:2] and abs(r[2] - t[2]) <= 1:
        return "near"
    return None


# ------------------------------------------------------------------------------------------- sources

def inferencex_records(rows: list[dict]) -> list[dict]:
    import engines
    out = []
    for r in rows:
        fw = engines.lookup(r["framework"])
        image = (r.get("image") or "").split("@", 1)[0]
        if fw.engine == engines.VLLM:
            m = _VLLM_IMAGE.match(image)
            release = m.group(1) if m else None
        elif fw.engine == engines.SGLANG:
            release = mb.sglang_release(image)
        else:
            release = None
        out.append({"source": "inferencex", "record": str(r["id"]), "engine": fw.engine, "release": release,
                    "build": image or None, "model": r["model"], "hardware": r["hardware"], "framework": r["framework"],
                    "benchmark_type": r["benchmark_type"], "date": str(r["date"])[:10]})
    return out


def configiq_records(rows_by_pair: dict[str, list[dict]]) -> list[dict]:
    """The dataset's rows, by pair id in file order."""
    out = []
    for pair, rows in sorted(rows_by_pair.items()):
        for i, r in enumerate(rows):
            m = _CONFIGIQ_VERSION.match(str(r.get("backend_version") or ""))
            if r.get("backend") != "vllm":
                raise ReleaseError(f"{pair} row {i}: backend {r.get('backend')!r}; the adapter reads vLLM rows only")
            out.append({"source": "configiq", "record": f"{pair}:{i}", "engine": "vllm",
                        "release": m.group(1) if m else None, "build": r.get("backend_version"),
                        "model": r["model_id"], "hardware": str(r["accelerator"]).lower(), "framework": "vllm",
                        "benchmark_type": "single_turn" if (r.get("turns") or 1) == 1 else "multi_turn", "date": None})
    return out


def read_configiq(directory: Path) -> tuple[dict[str, list[dict]], dict]:
    """The dataset's rows by pair, each file checked against the manifest's sha256 first."""
    manifest_raw = (directory / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    for p in manifest["pairs"]:
        f = directory / "pairs" / f"{p['id']}.parquet"
        got = hashlib.sha256(f.read_bytes()).hexdigest()
        if got != p["file_sha256"]:
            raise ReleaseError(f"{f}: sha256 {got}, the manifest says {p['file_sha256']}")
    try:
        import pyarrow.parquet as pq
    except ImportError:
        raise ReleaseError("the configiq source is Parquet; install pyarrow to read it") from None
    out = {}
    for p in manifest["pairs"]:
        f = directory / "pairs" / f"{p['id']}.parquet"
        rows = pq.read_table(f).to_pylist()
        if len(rows) != p["records"]:
            raise ReleaseError(f"{f}: {len(rows)} rows, the manifest says {p['records']}")
        out[p["id"]] = rows
    return out, {"manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(), "pairs": len(out),
                 "rows": sum(len(v) for v in out.values())}


# ------------------------------------------------------------------------------------------- the report

def ledger_status(records: list[dict], ledger_records: set[str], source_revision_end: str | None) -> dict[str, str]:
    """Whether the substrate's ledger holds each InferenceX record as (part of) a unit; other sources have no ledger
    entries yet, so their records are no points."""
    out = {}
    for r in records:
        if r["source"] != "inferencex":
            out[r["record"]] = "source_not_in_ledger"
        elif r["record"] in ledger_records:
            out[r["record"]] = "unit"
        elif source_revision_end and r["date"] and r["date"] > source_revision_end:
            out[r["record"]] = "newer_than_source_revision"
        else:
            out[r["record"]] = "not_in_ledger"
    return out


# What each source's data can decide of the G1 conditions (design §11.3) before scoring: the engine release from its
# build, and the rest only once a scored point's Result and record exist.
CONDITIONS = ("engine_release", "kernel_hash", "fields_modelled", "coefficients", "resolved_values", "client_requests")


def conditions(r: dict, status: str) -> dict:
    if r["release"] is None:
        rel = "false: nightly or custom build"
    elif nearness(r["engine"], r["release"]) == "target":
        rel = "true"
    else:
        rel = f"false: {r['release']}"
    out = {"engine_release": rel,
           "kernel_hash": "unevaluated: no source maps a library version to a kernel hash (blis-registry#73)"}
    if r["engine"] == "sglang":
        rest = "not scored: BLIS has no SGLang engine (blis-sglang#2)"
    elif status != "unit":
        rest = f"not scored: {status.replace('_', ' ')}"
    else:
        rest = "decided when the point is scored"
    if r["source"] == "configiq" and r["engine"] == "vllm":
        rest = ("not scorable as recorded: the dataset keeps no runtime arguments and no per-request rows, so the "
                "fields the run set and the requests it sent are not recorded")
    out.update({k: rest for k in CONDITIONS[2:]})
    return out


def report(records: list[dict], status: dict[str, str], revisions: dict) -> dict:
    found = [r for r in records if nearness(r["engine"], r["release"])]
    groups = defaultdict(Counter)
    for r in found:
        key = (r["source"], r["engine"], r["release"], nearness(r["engine"], r["release"]), r["framework"],
               r["hardware"], r["benchmark_type"])
        groups[key][status[r["record"]]] += 1
    rows = []
    for (src, eng, rel, near, fw, hw, bt), c in sorted(groups.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        sample = next(r for r in found if (r["source"], r["release"], r["framework"], r["hardware"], r["benchmark_type"])
                      == (src, rel, fw, hw, bt))
        rows.append({"source": src, "engine": eng, "release": rel, "nearness": near, "framework": fw, "hardware": hw,
                     "scope": "out_of_scope" if hw in OUT_OF_SCOPE else "in_scope", "benchmark_type": bt,
                     "records": sum(c.values()), "ledger": dict(sorted(c.items())),
                     "conditions": conditions(sample, status[sample["record"]])})
    by_release = Counter((r["source"], r["engine"], r["release"]) for r in records)
    return {"format": FORMAT, "targets": TARGETS, "revisions": revisions, "runs": rows,
            "records_by_release": [{"source": s, "engine": e, "release": rel, "records": n}
                                   for (s, e, rel), n in sorted(by_release.items(), key=lambda kv: tuple(str(x) for x in kv[0]))],
            "records": {"read": len(records), "on_target_or_near": len(found),
                        "on_target_in_scope": sum(1 for r in found if nearness(r["engine"], r["release"]) == "target"
                                                  and r["hardware"] not in OUT_OF_SCOPE)}}


def markdown(doc: dict) -> str:
    rv = doc["revisions"]
    ix = rv["inferencex"]
    L = ["# Runs on the engine releases BLIS runs", "",
         "Generated by `orchestrator/baseline/release_runs.py report`; do not edit by hand. How to read it: "
         "[README.md](README.md).", "",
         "## The data read", "",
         "| Source | Revision |", "|---|---|",
         f"| InferenceX API | read {ix['read_at']}; /availability sha256 `{ix['availability_sha256']}`; {ix['rows']} rows, "
         f"measured {ix['first_date']} to {ix['last_date']} |",
         f"| InferenceX dump | newest release `{ix['newest_dump']}`; the ledger's source revision `{ix['ledger_revision']}` |"]
    if "configiq" in rv:
        c = rv["configiq"]
        L.append(f"| redhat-performance/configiq-performance-upstream-data | commit `{c['commit']}`; manifest sha256 "
                 f"`{c['manifest_sha256']}`; {c['pairs']} pairs, {c['rows']} rows |")
    L += ["", f"Targets: vLLM {doc['targets']['vllm']}, SGLang {doc['targets']['sglang']}. "
          f"{doc['records']['on_target_or_near']} of {doc['records']['read']} records are on a target release or next "
          f"to one; {doc['records']['on_target_in_scope']} are on a target release on an in-scope chip.", "",
          "## The runs", "",
          "Ledger: `unit` is a point; `newer_than_source_revision` is a record the ledger's source revision predates "
          "(it becomes a point when the substrate's ledger takes it); `source_not_in_ledger` is a source the ledger "
          "has no entry for yet.", "",
          "| Source | Engine | Release | | Framework | Chip | Scope | Benchmark | Records | Ledger | Engine release (G1) | Other G1 conditions |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in doc["runs"]:
        led = ", ".join(f"{k} {v}" for k, v in r["ledger"].items())
        L.append(f"| {r['source']} | {r['engine']} | {r['release']} | {r['nearness']} | {r['framework']} | {r['hardware']} | "
                 f"{r['scope'].replace('_', ' ')} | {r['benchmark_type']} | {r['records']} | {led} | "
                 f"{r['conditions']['engine_release']} | {r['conditions']['fields_modelled']} |")
    L += ["", "## Records by release", "", "| Source | Engine | Release | Records |", "|---|---|---|---|"]
    L += [f"| {x['source']} | {x['engine'] or 'other'} | {x['release'] or 'nightly or custom'} | {x['records']} |"
          for x in doc["records_by_release"]]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report")
    r.add_argument("--inferencex-rows", required=True, type=Path)
    r.add_argument("--inferencex-availability", required=True, type=Path)
    r.add_argument("--inferencex-read-at", required=True)
    r.add_argument("--dump-tags", required=True, type=Path, help="the InferenceX-app release tags, a JSON list")
    r.add_argument("--configiq", type=Path)
    r.add_argument("--configiq-commit")
    r.add_argument("--ledger", required=True, type=Path)
    r.add_argument("--ledger-revision", required=True)
    r.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    try:
        import ledger as ldg
        rows = json.loads(a.inferencex_rows.read_text())
        records = inferencex_records(rows)
        dates = sorted(r["date"] for r in records)
        dumps = sorted(t for t in json.loads(a.dump_tags.read_text()) if t.startswith("db-dump/"))
        revisions = {"inferencex": {"read_at": a.inferencex_read_at, "rows": len(rows),
                                    "availability_sha256": hashlib.sha256(a.inferencex_availability.read_bytes()).hexdigest(),
                                    "first_date": dates[0], "last_date": dates[-1],
                                    "newest_dump": dumps[-1] if dumps else None, "ledger_revision": a.ledger_revision}}
        if a.configiq:
            if not a.configiq_commit or not re.fullmatch(r"[0-9a-f]{40}", a.configiq_commit):
                raise ReleaseError("--configiq needs --configiq-commit, the dataset's full commit")
            by_pair, rev = read_configiq(a.configiq)
            records += configiq_records(by_pair)
            revisions["configiq"] = {"commit": a.configiq_commit, **rev}
        lg = ldg.load(a.ledger)
        held = set(lg.by_record)
        end = a.ledger_revision.split("/", 1)[-1] if a.ledger_revision.startswith("db-dump/") else None
        # a dump of date D holds rows measured before D
        end = None if end is None else (__import__("datetime").date.fromisoformat(end)
                                         - __import__("datetime").timedelta(days=1)).isoformat()
        doc = report(records, ledger_status(records, held, end), revisions)
        a.out.parent.mkdir(parents=True, exist_ok=True)
        Path(f"{a.out}.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
        Path(f"{a.out}.md").write_text(markdown(doc))
        print(f"wrote {a.out}.json and .md: {doc['records']['on_target_or_near']} records on or next to a target release")
    except ReleaseError as e:
        print(f"release_runs: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
