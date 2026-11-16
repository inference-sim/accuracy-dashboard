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
                           [--configiq DIR --configiq-commit SHA] --ledger LEDGER --stack STACK.json
                           --engines docs/m3/baseline/engines.json --dump-tags TAGS.json --out PREFIX

The targets are read, never kept here: vLLM's release from the scoring simulator's stack.json, SGLang's from
blis-sglang's provenance (engines.json). The ledger's source revision is the loaded ledger's own. The configiq
commit is checked by fetching the dataset's manifest at that commit. Each row of the report carries its record
ids, its ledger status (a row holds one status), and the best grade its release, router and topology allow: a run
behind a router BLIS does not host is never G1 (design §11.3), and is G5 where the router table maps no policy.

ROWS.json is api.pull's rows, AVAIL.json the /availability body; DIR holds the dataset's manifest.json and its
pairs/<id>.parquet files, read with pyarrow (the dataset's own format; needed only for this source). None of these is
committed: the report keeps counts and record ids (derived identifiers) only.
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
import ceiling as cl  # noqa: E402
import compare as cmp  # noqa: E402
import grade as gr  # noqa: E402
import m3_baseline as mb  # noqa: E402

FORMAT = "release-runs-1"
_CONFIGIQ_VERSION = re.compile(r"^vLLM-(\d+\.\d+\.\d+)$")


def targets_of(stack: dict, engines: dict) -> dict:
    """The engine releases BLIS runs: vLLM's from the scoring simulator's stack.json, SGLang's from blis-sglang's
    provenance (engines.json, m3_baseline.py engines). Never a table of this file's own (LIF-6, COV-6)."""
    vllm = next((e["version"] for e in stack.get("engines") or [] if e.get("kind") == "vllm"), None)
    if not vllm:
        raise ReleaseError("the stack names no vLLM engine release")
    return {"vllm": vllm, "sglang": engines["sglang"]["version"]}


class ReleaseError(ValueError):
    pass


def _parts(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def nearness(engine: str, release: str | None, targets: dict) -> str | None:
    """"target" for the release BLIS runs; "near" for a release next to it (vLLM: another patch of its own minor
    release, or any patch of the minor releases either side, 0.32.x, 0.31.x and 0.33.x; SGLang, which releases by
    patch: 0.5.22 and 0.5.24, post releases included); None otherwise."""
    if release is None or engine not in targets:
        return None
    t, r = _parts(targets[engine]), _parts(release)
    if release == targets[engine]:
        return "target"
    if engine == "vllm" and r[0] == t[0] and abs(r[1] - t[1]) <= 1:
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
            release = gr.run_release({"image": image}, None).version
        elif fw.engine == engines.SGLANG:
            release = mb.sglang_release(image)
        else:
            release = None
        out.append({"source": "inferencex", "record": str(r["id"]), "engine": fw.engine, "release": release,
                    "router": fw.router, "topology": "disaggregated" if r.get("disagg") else "aggregated",
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
            out.append({"source": "configiq", "record": f"{pair}:{i}", "engine": "vllm", "router": None,
                        "topology": "aggregated",
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

def ledger_status(records: list[dict], ledger_records: set[str], source_revision_end: str | None,
                  left_out: dict | None = None) -> dict[str, str]:
    """Whether the substrate's ledger holds each InferenceX record as (part of) a unit, leaves it out (with the
    ledger's own reason), or predates it; other sources have no ledger entries yet, so their records are no points."""
    out = {}
    left_out = left_out or {}
    for r in records:
        if r["source"] != "inferencex":
            out[r["record"]] = "source_not_in_ledger"
        elif r["record"] in ledger_records:
            out[r["record"]] = "unit"
        elif r["record"] in left_out:
            out[r["record"]] = f"left_out:{left_out[r['record']]}"
        elif source_revision_end and r["date"] and r["date"] > source_revision_end:
            out[r["record"]] = "newer_than_source_revision"
        else:
            out[r["record"]] = "not_in_ledger"
    return out


def source_revision_end(revision: str) -> str | None:
    """The last measured date a ledger revision holds: a db-dump of date D holds rows measured before D."""
    from datetime import date, timedelta
    if not revision.startswith("db-dump/"):
        return None
    return (date.fromisoformat(revision.split("/", 1)[1]) - timedelta(days=1)).isoformat()


# What each source's data can decide of the G1 conditions (design §11.3) before scoring: the engine release from its
# build, the router and the topology from its label; the rest only once a scored point's Result and record exist.
CONDITIONS = ("engine_release", "router", "topology", "kernel_hash", "fields_modelled", "coefficients",
              "resolved_values", "client_requests")


def router_condition(router: str | None, routers: list[dict]) -> tuple[str, str]:
    """(condition, best grade the router allows). No router, or llm-d's, allows G1. Another router is never G1
    (§11.3): G2 where the router table maps it to an llm-d policy, G5 where it maps no policy for any mode, and G2
    as an upper bound where the run's mode is not recorded on the record (§11.4)."""
    if router is None or str(router).startswith("llm-d"):
        return "true", "G1"
    lim = cl.router_cap(router, routers)
    if lim["cap"] == "G5":
        return f"false: behind {router}, which the router table maps to no llm-d policy", "G5"
    return f"false: behind {router}; {lim['why']}", "G2?" if lim.get("bound") else "G2"


def conditions(r: dict, status: str, targets: dict, routers: list[dict]) -> dict:
    if r["release"] is None:
        rel = "false: nightly or custom build"
    elif nearness(r["engine"], r["release"], targets) == "target":
        rel = "true"
    else:
        rel = f"false: {r['release']}"
    router, best = router_condition(r.get("router"), routers)
    topo = "true" if r.get("topology") != "disaggregated" else \
        "true only if the harness writes the run's prefill/decode pools (topology_unsupported otherwise)"
    out = {"engine_release": rel, "router": router, "topology": topo,
           "kernel_hash": "unevaluated: no source maps a library version to a kernel hash (inference-sim/blis-substrate#149)"}
    if r["engine"] == "sglang":
        rest = "not scored: BLIS has no SGLang engine (blis-sglang#2)"
    elif status != "unit":
        rest = f"not scored: {status.replace('_', ' ')}"
    else:
        rest = "decided when the point is scored"
    if r["source"] == "configiq" and r["engine"] == "vllm":
        rest = ("not scorable as recorded: the dataset keeps no runtime arguments and no per-request rows, so the "
                "fields the run set and the requests it sent are not recorded")
    out.update({k: rest for k in CONDITIONS[4:]})
    if r["source"] == "configiq":
        # the record holds no run arguments: G5 value_not_recorded as recorded, whatever the release
        out["can_reach_g1"], out["best_grade"] = False, "G5"
        return out
    can_g1 = rel == "true" and best == "G1" and topo == "true"
    out["can_reach_g1"] = can_g1
    out["best_grade"] = "G1" if can_g1 else (best if best in ("G5", "G2", "G2?") else "G2" if rel == "true" else
                                            "G4" if r["release"] is None else "G3?")
    return out


def report(records: list[dict], status: dict[str, str], revisions: dict, targets: dict, routers: list[dict]) -> dict:
    found = [r for r in records if nearness(r["engine"], r["release"], targets)]
    groups = defaultdict(list)
    for r in found:
        key = (r["source"], r["engine"], r["release"], nearness(r["engine"], r["release"], targets), r["framework"],
               r["hardware"], r["benchmark_type"], status[r["record"]])
        groups[key].append(r)
    rows = []
    for (src, eng, rel, near, fw, hw, bt, st), rs in sorted(groups.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        rows.append({"source": src, "engine": eng, "release": rel, "nearness": near, "framework": fw, "hardware": hw,
                     "scope": cmp.scope(hw), "benchmark_type": bt, "ledger": st, "records": len(rs),
                     "record_ids": sorted(x["record"] for x in rs),
                     "conditions": conditions(rs[0], st, targets, routers)})
    by_release = Counter((r["source"], r["engine"], r["release"]) for r in records)
    target_in = [x for x in rows if x["nearness"] == "target" and x["scope"] == cmp.SCOPE_IN]
    return {"format": FORMAT, "targets": targets, "revisions": revisions, "runs": rows,
            "records_by_release": [{"source": s_, "engine": e, "release": rel, "records": n}
                                   for (s_, e, rel), n in sorted(by_release.items(), key=lambda kv: tuple(str(x) for x in kv[0]))],
            "records": {"read": len(records), "on_target_or_near": len(found),
                        "on_target_in_scope": sum(x["records"] for x in target_in),
                        "on_target_in_scope_that_can_reach_g1": sum(x["records"] for x in target_in
                                                                     if x["conditions"]["can_reach_g1"]),
                        "on_target_in_scope_vllm_inferencex_g1": sum(x["records"] for x in target_in
                                                                      if x["conditions"]["can_reach_g1"] and x["engine"] == "vllm"
                                                                      and x["source"] == "inferencex")}}


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
        L.append(f"| redhat-performance/configiq-performance-upstream-data | commit `{c['commit']}` (its manifest checked "
                 f"against the files read); manifest sha256 `{c['manifest_sha256']}`; {c['pairs']} pairs, {c['rows']} rows |")
    rc = doc["records"]
    L += ["", f"Targets: vLLM {doc['targets']['vllm']} (the scoring simulator's stack.json), SGLang "
          f"{doc['targets']['sglang']} (blis-sglang's provenance). {rc['on_target_or_near']} of {rc['read']} records are "
          f"on a target release or next to one; {rc['on_target_in_scope']} are on a target release on an in-scope chip, "
          f"and **{rc['on_target_in_scope_that_can_reach_g1']} of them can reach G1** with their data "
          f"({rc['on_target_in_scope_vllm_inferencex_g1']} of them vLLM runs of InferenceX); the others are behind a router "
          f"BLIS does not host, or kept as aggregates with no run arguments.", "",
          "## The runs", "",
          "Ledger: `unit` is a point; `newer_than_source_revision` is a record the ledger's source revision predates "
          "(it becomes a point when the substrate's ledger takes it); `left_out:<reason>` a record the ledger leaves "
          "out, with its reason; `source_not_in_ledger` a source the ledger has no entry for yet. Best grade: what the "
          "record's release, router and topology allow, before scoring; `?` an upper bound the data cannot decide. "
          "The record ids of each row are in release-runs.json.", "",
          "| Source | Engine | Release | | Framework | Chip | Scope | Benchmark | Records | Ledger | Router (G1) | Best grade | Other G1 conditions |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in doc["runs"]:
        c = r["conditions"]
        L.append(f"| {r['source']} | {r['engine']} | {r['release']} | {r['nearness']} | {r['framework']} | {r['hardware']} | "
                 f"{r['scope'].replace('_', ' ')} | {r['benchmark_type']} | {r['records']} | {r['ledger']} | "
                 f"{c['router']} | {c['best_grade']} | {c['fields_modelled']} |")
    L += ["", "## Records by release", "", "| Source | Engine | Release | Records |", "|---|---|---|---|"]
    L += [f"| {x['source']} | {x['engine'] or 'other'} | {x['release'] or 'nightly or custom'} | {x['records']} |"
          for x in doc["records_by_release"]]
    return "\n".join(L) + "\n"


def check_configiq_commit(commit: str, manifest_sha256: str, fetch=None) -> None:
    """The dataset's manifest at the commit given is the one read: fetched from Hugging Face at that revision and
    hashed. A commit that does not hold this manifest is refused."""
    if not re.fullmatch(r"[0-9a-f]{40}", commit or ""):
        raise ReleaseError("--configiq needs --configiq-commit, the dataset's full 40-hex commit")
    if fetch is None:
        import urllib.request

        def fetch(url):
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
    url = f"https://huggingface.co/datasets/redhat-performance/configiq-performance-upstream-data/resolve/{commit}/manifest.json"
    got = hashlib.sha256(fetch(url)).hexdigest()
    if got != manifest_sha256:
        raise ReleaseError(f"the dataset's manifest at {commit} has sha256 {got}, the one read {manifest_sha256}")


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
    r.add_argument("--stack", required=True, type=Path, help="the scoring simulator's stack.json")
    r.add_argument("--engines", required=True, type=Path, help="docs/m3/baseline/engines.json: SGLang's release and the router table")
    r.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    try:
        import ledger as ldg
        rows = json.loads(a.inferencex_rows.read_text())
        if not rows:
            raise ReleaseError(f"{a.inferencex_rows} holds no InferenceX row: the source read is empty")
        records = inferencex_records(rows)
        dates = sorted(r["date"] for r in records)
        dumps = sorted(t for t in json.loads(a.dump_tags.read_text()) if t.startswith("db-dump/"))
        if not dumps:
            raise ReleaseError(f"{a.dump_tags} names no db-dump release")
        lg = ldg.load(a.ledger)
        revisions = {"inferencex": {"read_at": a.inferencex_read_at, "rows": len(rows),
                                    "availability_sha256": hashlib.sha256(a.inferencex_availability.read_bytes()).hexdigest(),
                                    "first_date": dates[0], "last_date": dates[-1],
                                    "newest_dump": dumps[-1], "ledger_revision": lg.revision}}
        if a.configiq:
            by_pair, rev = read_configiq(a.configiq)
            check_configiq_commit(a.configiq_commit, rev["manifest_sha256"])
            records += configiq_records(by_pair)
            revisions["configiq"] = {"commit": a.configiq_commit, **rev}
        engines_doc = json.loads(a.engines.read_text())
        targets = targets_of(json.loads(a.stack.read_text()), engines_doc)
        status = ledger_status(records, set(lg.by_record), source_revision_end(lg.revision), lg.left_out)
        doc = report(records, status, revisions, targets, engines_doc["routers"]["entries"])
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
