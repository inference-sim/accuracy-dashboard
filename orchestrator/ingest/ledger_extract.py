#!/usr/bin/env python3
"""The ledger's pinned source, as a compact extract the nightly reads instead of the dump (design §2.2, COV-1).

The ledger's units were drawn from one InferenceX database dump (blis-substrate catalog/ledger/sources.yaml). The night
scores every anchor unit on the record the ledger was made from, so it needs that dump's rows. The dump is 34 GB, and
its restore does not fit a standard runner. The extract holds what the ledger's units need: every row of the dump,
exactly as the substrate's ledger/inferencex/export.sql prints it, and each row's vLLM server log where the dump holds
one (server_logs.server_log through benchmark_results.server_log_id), and the source's supplements: the records
InferenceX published after the dump that sources.yaml pins by content hash, as the substrate's own
`ledger supplement-records` fetches them (it refuses any whose content differs from its pin). It is one gzip JSONL
file, one row per line in row-id order, so the same inputs give the same bytes.

    ledger_extract.py build --export-sql FILE --supplements FILE --ledger DIR --out EXTRACT.jsonl.gz [--psql PSQL] [--db NAME]
        Reads a database restore.sh restored from the pinned dump, writes the extract, and checks that the rows it
        holds place exactly the ledger's units. Prints {"sha256", "bytes", "rows", "logs", "units"}.
    ledger_extract.py restore --sources SOURCES.yaml [--db NAME] [--bin DIR]
        Restores the tables the extract reads (benchmark_results, configs, workflow_runs, server_logs) from the dump
        sources.yaml pins: each part is downloaded, checked against the SHA-256 sources.yaml states, and streamed
        through zstd into pg_restore (PostgreSQL 17), so one part is on disk at a time. As the substrate's
        restore.sh does, with server_logs added; the dump is only restored, never executed.
    ledger_extract.py check-source --sources SOURCES.yaml --anchor-list ANCHOR.yaml --pin PIN.json
        Whether a blis-substrate release's sources.yaml is the one the pinned extract was built from.
    ledger_extract.py check --extract FILE --pin PIN.json --ledger DIR
        The night's check before it reads the extract: its sha256, size and ledger revision are the pin's, and its
        rows place no unit the ledger does not hold.

Redistribution (X12): sources.yaml records the InferenceX data's licence as NOASSERTION, so the extract is never
committed and never published. It is built by the ledger-extract workflow, kept in the Actions cache under its sha256,
and named by .github/ledger-extract.json.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ledger as ldg  # noqa: E402
import pull as pl  # noqa: E402

TABLES = ("benchmark_results", "configs", "workflow_runs", "server_logs")


class ExtractError(ValueError):
    pass


def _psql(psql: str, db: str, *, sql: str | None = None, file: Path | None = None) -> str:
    args = [psql, "-d", db, "-At", "-v", "ON_ERROR_STOP=1"]
    args += ["-f", str(file)] if file else ["-c", sql]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise ExtractError(f"psql exited {r.returncode}: {r.stderr.strip()[-500:]}")
    return r.stdout


def source_digest(sources: dict, anchor_list: bytes) -> str:
    """The sha256 of what the extract is made from: the inferencex source's pinned revision and supplements in
    sources.yaml, and the published anchor list (whose records' logs it carries), as canonical JSON. Another digest
    means another extract."""
    src = next(x for x in sources["sources"] if x["id"] == "inferencex")
    body = {"revision": src["revision"], "supplements": src.get("supplements") or [],
            "anchor_list_sha256": hashlib.sha256(anchor_list).hexdigest()}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def check_source(sources: dict, anchor_list: bytes, pin: dict) -> None:
    if source_digest(sources, anchor_list) != pin.get("source_sha256"):
        raise ExtractError("this sources.yaml pins another InferenceX dump or other supplements than the ledger "
                           f"extract (built for {pin.get('substrate_ref')}, {pin.get('ledger_revision')}): run the "
                           "ledger-extract workflow for this blis-substrate release and commit its pin")


def dump_parts(sources: dict) -> tuple[str, list[dict]]:
    """(the download base URL, the parts with their SHA-256) of the inferencex source's pinned dump."""
    src = next(x for x in sources["sources"] if x["id"] == "inferencex")
    rev = src["revision"]
    if rev.get("kind") != "release_assets" or "/releases/tag/" not in rev["url"]:
        raise ExtractError(f"the inferencex source is pinned as {rev.get('kind')}, not a release's assets")
    return rev["url"].replace("/releases/tag/", "/releases/download/"), rev["assets"]


def restore(sources: dict, db: str, bindir: str = "", fetch=None) -> None:
    import shutil
    import tempfile
    import urllib.request
    base, parts = dump_parts(sources)
    tool = (lambda t: str(Path(bindir) / t)) if bindir else (lambda t: t)
    subprocess.run([tool("createdb"), db], check=True)
    restore_args = [tool("pg_restore"), "--no-owner", "--no-privileges", "-d", db]
    for t in TABLES:
        restore_args += ["-t", t]
    zstd = subprocess.Popen(["zstd", "-dc"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    pgr = subprocess.Popen(restore_args, stdin=zstd.stdout)
    zstd.stdout.close()
    get = fetch or (lambda url, path: shutil.copyfileobj(urllib.request.urlopen(url, timeout=600), open(path, "wb")))
    with tempfile.TemporaryDirectory() as tmp:
        part = Path(tmp) / "part"
        try:
            for a in parts:
                get(f"{base}/{a['name']}", part)
                got = sha256(part)
                if got != a["sha256"]:
                    raise ExtractError(f"{a['name']} has sha256 {got}; sources.yaml pins {a['sha256']}")
                with open(part, "rb") as fh:
                    shutil.copyfileobj(fh, zstd.stdin)
                part.unlink()
        finally:
            zstd.stdin.close()
            zstd.wait()
            pgr.wait()
    if zstd.returncode != 0 or pgr.returncode != 0:
        raise ExtractError(f"zstd exited {zstd.returncode} and pg_restore {pgr.returncode}")


def log_ids(rows: list[dict], lg, anchors: set[str]) -> list[int]:
    """The rows whose vLLM server log the extract carries: the records of the anchor units (only anchors are scored,
    COV-2) that the scorer reads a log for, single-turn rows of a framework a BLIS engine scores. An agentic point's
    log is in its run's artifacts; a framework no engine scores is G5 without one."""
    import engines
    want = {str(r) for u in anchors if u in lg.units for r in lg.units[u].records()}
    return sorted(int(r["id"]) for r in rows if str(r["id"]) in want and r.get("benchmark_type") == "single_turn"
                  and engines.scored(engines.lookup(r["framework"])))


def write_extract(dump_lines, logs, out: Path, supplements: list[dict] = ()) -> dict:
    """Write the extract. `dump_lines` is export.sql's output, one JSON object per row, kept as its text (the dump's
    numbers as the dump prints them); `logs` yields (row id, log text) in id order; `supplements` are the pinned
    supplement rows. Each line gets "server_log" (null when there is none), and lines are in row-id order. gzip with
    no name and no time, so the bytes depend only on the content."""
    lines, seen = [], set()
    for line in dump_lines:
        line = line.strip()
        if not line:
            continue
        rid = int(json.loads(line)["id"])
        lines.append((rid, line))
    for r in supplements:
        lines.append((int(r["id"]), json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False)))
    lines.sort(key=lambda x: x[0])
    for rid, _ in lines:
        if rid in seen:
            raise ExtractError(f"row {rid} is both a dump row and a supplement, or appears twice")
        seen.add(rid)
    logs = iter(logs)
    nxt = next(logs, None)
    n_logs = 0
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as fh:
        with gzip.GzipFile(filename="", mode="wb", fileobj=fh, mtime=0, compresslevel=9) as gz:
            for rid, text in lines:
                while nxt is not None and int(nxt[0]) < rid:
                    nxt = next(logs, None)
                log = None
                if nxt is not None and int(nxt[0]) == rid:
                    log, nxt = nxt[1], next(logs, None)
                    n_logs += 1
                assert text.endswith("}"), rid
                gz.write((text[:-1] + ',"server_log":' + json.dumps(log, ensure_ascii=False) + "}\n").encode("utf-8"))
    return {"sha256": sha256(out), "bytes": out.stat().st_size, "rows": len(lines), "logs": n_logs}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path: Path, keep_log=None) -> tuple[list[dict], dict[str, str]]:
    """(the rows, as export.sql printed them; the server logs by row id, those `keep_log(row id)` is true of)."""
    rows, logs = [], {}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            log = r.pop("server_log", None)
            if log is not None and (keep_log is None or keep_log(str(r["id"]))):
                logs[str(r["id"])] = log
            rows.append(r)
    return rows, logs


def check_units(rows: list[dict], lg, *, exact: bool = True) -> int:
    """The extract's rows place the ledger's units: none is another revision's (a row whose content differs from the
    ledger's record raises ledger.RowDiffers), and, when `exact`, none is missing. The build is exact; the night only
    needs none foreign, since an anchor the source lacks is G5 there (cli.UNSOURCED)."""
    placed = pl.place(rows, lg)
    got = {p.point_id for p in placed.points}
    want = set(lg.units)
    if got - want or (exact and got != want):
        raise ExtractError(f"the extract places {len(got)} units and the ledger {lg.revision} holds {len(want)}: "
                           f"{len(want - got)} missing, {len(got - want)} not the ledger's")
    return len(got)


def check(extract: Path, pin: dict, lg, keep_log=None) -> tuple[list[dict], dict[str, str]]:
    got = sha256(extract)
    if got != pin["sha256"] or extract.stat().st_size != pin["bytes"]:
        raise ExtractError(f"{extract} has sha256 {got} and {extract.stat().st_size} bytes; the pin names "
                           f"{pin['sha256']} and {pin['bytes']}")
    if pin.get("ledger_revision") != lg.revision:
        raise ExtractError(f"the pin is for ledger revision {pin.get('ledger_revision')}, the ledger is {lg.revision}")
    rows, logs = read(extract, keep_log)
    check_units(rows, lg, exact=False)
    return rows, logs


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--export-sql", required=True)
    b.add_argument("--supplements", required=True, help="the JSON array of rows `ledger supplement-records -out FILE` writes")
    b.add_argument("--ledger", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--psql", default="psql")
    b.add_argument("--db", default="ixdump")
    b.add_argument("--sources", required=True)
    cs = sub.add_parser("check-source")
    cs.add_argument("--sources", required=True)
    cs.add_argument("--pin", required=True)
    cs.add_argument("--anchor-list", required=True, help="the release's catalog/ledger/published/anchor.yaml")
    r = sub.add_parser("restore")
    r.add_argument("--sources", required=True)
    r.add_argument("--db", default="ixdump")
    r.add_argument("--bin", default="", help="the PostgreSQL 17 bin directory (default: PATH)")
    c = sub.add_parser("check")
    c.add_argument("--extract", required=True)
    c.add_argument("--pin", required=True)
    c.add_argument("--ledger", required=True)
    a = p.parse_args(argv)
    import yaml
    if a.cmd == "restore":
        restore(yaml.safe_load(Path(a.sources).read_text()), a.db, a.bin)
        return 0
    if a.cmd == "check-source":
        check_source(yaml.safe_load(Path(a.sources).read_text()), Path(a.anchor_list).read_bytes(),
                     json.loads(Path(a.pin).read_text()))
        print("the ledger extract is this release's")
        return 0
    lg = ldg.load(Path(a.ledger))
    if a.cmd == "build":
        import csv
        anchor_list = Path(a.ledger) / "published" / "anchor.yaml"
        anchors = ldg.read_unit_set(anchor_list, role="anchor")
        dump_lines = _psql(a.psql, a.db, file=Path(a.export_sql)).splitlines()
        supp = json.loads(Path(a.supplements).read_text())      # a JSON array of rows
        rows = [json.loads(x) for x in dump_lines if x.strip()] + supp
        ids = log_ids(rows, lg, anchors)
        sql = (f"copy (select br.id, sl.server_log from benchmark_results br join server_logs sl on sl.id = br.server_log_id "
               f"where br.id = any('{{{','.join(map(str, ids))}}}'::bigint[]) order by br.id) to stdout with (format csv)")
        import io
        proc = subprocess.Popen([a.psql, "-d", a.db, "-At", "-v", "ON_ERROR_STOP=1", "-c", sql], stdout=subprocess.PIPE)
        text = io.TextIOWrapper(proc.stdout, encoding="utf-8", newline="")      # csv reads the quoted newlines itself
        csv.field_size_limit(1 << 31)          # a server log is one field, up to tens of MB
        info = write_extract(dump_lines, ((int(i), t) for i, t in csv.reader(text)), Path(a.out), supp)
        if proc.wait() != 0:
            raise ExtractError(f"psql exited {proc.returncode} reading the server logs")
        del rows
        got, _ = read(Path(a.out), keep_log=lambda _: False)
        info["units"] = check_units(got, lg)
        info["ledger_revision"] = lg.revision
        info["source_sha256"] = source_digest(yaml.safe_load(Path(a.sources).read_text()), anchor_list.read_bytes())
        print(json.dumps(info, sort_keys=True))
        return 0
    pin = json.loads(Path(a.pin).read_text())
    rows, logs = check(Path(a.extract), pin, lg)
    print(json.dumps({"rows": len(rows), "logs": len(logs), "sha256": pin["sha256"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
