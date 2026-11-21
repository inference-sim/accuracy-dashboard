#!/usr/bin/env python3
"""Extract the anchor units of the pinned InferenceX database dump into a frozen pull (the layout `cli.py score|coverage`
reads: manifest.json plus points/<unit_id>/*.gz), in one pass over the public release, without the whole dump on disk.

The release is 17 zstd parts of one `pg_dump -Fc` archive with no inner compression. This script streams the parts
(sha256 of each checked against dump_pin.json), decompresses them with `zstd -dc`, reads the custom-format archive
sequentially from the pipe in Python (no PostgreSQL client needed) and keeps only what the anchor units need:

  benchmark_results, configs   every row is read; the rows of the anchor units' records are kept
  server_logs                  the log of the kept record of each selected unit (the bulk of the archive is skipped)
  workflow_runs                every row is read (it is the last table; a run's earliest record date needs all of them)

then reuses the harness's own `pull.freeze_point` on those rows with an offline adapter (no artifact or job log is read, the
build is recorded estimated). The units are the ledger's anchor-role units (the published anchor list; the ledger seed is never
used) whose kept record is a single-turn vLLM or SGLang run on a non-AMD chip with a server log in the dump: the same
selection the frozen anchor extract was cut with. The dump owns record ids up to its cutoff; a unit with any record missing
from the dump is the API's, and a unit with only some of its records in the dump stops the run.

No credential is read or sent: the parts and the public recipe repository are fetched anonymously, and base_model comes from
the public model-hub API unless `--base-models-from` names a manifest that already holds it. The extract is third-party data:
it is cached by CI and never committed (.gitignore), only its sha256 is (dump_pin.json).

  dump_extract.py extract --ledger L --anchor A --out DIR (--parts-dir D | --download) [--git-dir G] [--base-models-from M]
  dump_extract.py verify  --extract DIR            the files and the content hash match dump_pin.json (exit 1 if not)
  dump_extract.py hash    --extract DIR            print the content hash
  dump_extract.py cache-key                         print the Actions cache key (dump revision + pinned extract hash)
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import io
import json
import re
import resource
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import api  # noqa: E402
import build  # noqa: E402
import contract  # noqa: E402
import engines  # noqa: E402
import ledger as ldg  # noqa: E402
import pull as pl  # noqa: E402
import recipes as rcp  # noqa: E402
import settings as st  # noqa: E402
import support as sp  # noqa: E402

PIN_PATH = HERE / "dump_pin.json"
PULL_ERROR = "artifact_unmatched:pull_error"
SOURCE_LABEL = "db-dump+offline-adapter"
FROZEN_FROM = "dump:server_logs"
# The frameworks whose runs the lane scores, and the one chip family it leaves out (its runs are scorer-refused G5 today).
LANE_FRAMEWORKS = ("vllm", "sglang")
EXCLUDED_HARDWARE_PREFIX = "mi"
SELECTED_TYPE = "single_turn"
# Fields of manifest.json that say when or how the extract was cut, not what it holds: left out of the content hash.
VOLATILE = ("pulled_at", "base_models", "source")
TABLES = ("benchmark_results", "configs", "server_logs", "workflow_runs")


class DumpError(RuntimeError):
    pass


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- the pin
def load_pin(path: Path = PIN_PATH) -> dict:
    pin = json.loads(Path(path).read_text())
    for k in ("ref", "base_url", "sha256sums", "parts", "extract_sha256"):
        if k not in pin:
            raise DumpError(f"{path}: no {k}")
    if not re.fullmatch(r"db-dump/\d{4}-\d{2}-\d{2}", pin["ref"]):
        raise DumpError(f"{path}: ref {pin['ref']!r} is not db-dump/<date>")
    listing = "".join(f"{p['sha256']}  {p['name']}\n" for p in pin["parts"])
    if hashlib.sha256(listing.encode()).hexdigest() != pin["sha256sums"]:
        raise DumpError(f"{path}: the part hashes are not the pinned SHA256SUMS {pin['sha256sums']}")
    return pin


def cache_key(pin: dict) -> str:
    """The Actions cache key: the dump revision and the sha256 of the extract that revision gives."""
    return f"dump-extract-{pin['ref'].split('/', 1)[1]}-{pin['extract_sha256']}"


# ---------------------------------------------------------------- the part stream
def _read_url(url: str, tries: int = 8):
    """The bytes of a public URL, resuming a broken transfer where it stopped. Nothing is sent but the request."""
    offset = 0
    n = 0
    while True:
        req = urllib.request.Request(url, headers={"Range": f"bytes={offset}-"} if offset else {})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                if offset and r.status != 206:
                    raise DumpError(f"{url}: the server ignored the range request at byte {offset}")
                expect = r.headers.get("Content-Length")
                got = 0
                while True:
                    block = r.read(1 << 20)
                    if not block:
                        break
                    got += len(block)
                    offset += len(block)
                    yield block
                if expect is not None and got != int(expect):
                    raise ConnectionError(f"the transfer stopped after {got} of {expect} bytes")
                return
        except (OSError, http.client.HTTPException) as e:
            n += 1
            if n >= tries or isinstance(e, urllib.error.HTTPError) and e.code in (403, 404):
                raise DumpError(f"{url}: {e}") from e
            log(f"  retry {n} of {url.rsplit('/', 1)[-1]} at byte {offset}: {e}")
            time.sleep(min(2 ** n, 30))


def _read_file(path: Path):
    with open(path, "rb") as f:
        while True:
            block = f.read(1 << 20)
            if not block:
                return
            yield block


class PartStream:
    """`zstd -dc` over the pinned parts, fed by a thread that checks each part's sha256 as it passes. `read()` is the
    decompressed archive; `close()` returns only when every part has arrived and matched, and raises otherwise."""

    def __init__(self, pin: dict, parts_dir: Path | None):
        self.pin, self.parts_dir, self.err = pin, parts_dir, []
        self.sent = 0
        self.proc = subprocess.Popen(["zstd", "-dc", "-q"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.out = self.proc.stdout
        self.thread = threading.Thread(target=self._feed, daemon=True)
        self.thread.start()

    def _blocks(self, part: dict):
        if self.parts_dir is not None:
            return _read_file(self.parts_dir / part["name"])
        return _read_url(f"{self.pin['base_url']}/{part['name']}")

    def _feed(self):
        try:
            for part in self.pin["parts"]:
                h = hashlib.sha256()
                for block in self._blocks(part):
                    h.update(block)
                    self.sent += len(block)
                    self.proc.stdin.write(block)
                if h.hexdigest() != part["sha256"]:
                    raise DumpError(f"{part['name']}: sha256 {h.hexdigest()} is not the pinned {part['sha256']}")
                log(f"  part {part['name'][-6:]} sha256 ok ({self.sent / 1e9:.1f} GB in)")
        except BaseException as e:  # noqa: BLE001
            self.err.append(e)
        finally:
            try:
                self.proc.stdin.close()
            except OSError:
                pass

    def close(self):
        # Drain what is left (the archive ends after its last table), then insist on a clean finish.
        while self.out.read(1 << 22):
            pass
        self.thread.join()
        rc = self.proc.wait()
        if self.err:
            raise DumpError(str(self.err[0])) from self.err[0]
        if rc != 0:
            raise DumpError(f"zstd exited {rc}")


# ---------------------------------------------------------------- the pg_dump custom-format archive
class Archive:
    """Sequential reader of a `pg_dump -Fc` archive (format 1.14 to 1.16, no inner compression) on a pipe. The table of
    contents comes first and the data blocks follow in its order; the reader never seeks."""

    def __init__(self, f):
        self.f = f
        self.read_header()

    def read(self, n: int) -> bytes:
        b = self.f.read(n)
        if len(b) != n:
            raise DumpError(f"the archive ended {n - len(b)} bytes short")
        return b

    def skip(self, n: int) -> None:
        while n > 0:
            got = len(self.f.read(min(n, 1 << 23)))
            if not got:
                raise DumpError("the archive ended inside a data block")
            n -= got

    def byte(self) -> int:
        return self.read(1)[0]

    def int(self) -> int:
        sign = self.byte()
        v = int.from_bytes(self.read(self.int_size), "little")
        return -v if sign else v

    def str(self):
        n = self.int()
        return None if n < 0 else self.read(n).decode("utf-8")

    def read_header(self):
        if self.read(5) != b"PGDMP":
            raise DumpError("not a pg_dump archive")
        self.version = (self.byte(), self.byte(), self.byte())
        if not ((1, 14, 0) <= self.version <= (1, 16, 255)):
            raise DumpError(f"archive version {self.version} is not one this reader knows (1.14 to 1.16)")
        self.int_size, self.off_size = self.byte(), self.byte()
        if self.byte() != 1:
            raise DumpError("not the custom format")
        if self.byte() != 0:
            raise DumpError("the archive data is compressed; this reader reads only an uncompressed one")
        for _ in range(7):
            self.int()                                       # the creation time
        self.dbname, self.server_version, self.dump_version = self.str(), self.str(), self.str()
        self.toc = {}
        for _ in range(self.int()):
            e = {"id": self.int()}
            self.int()                                       # hadDumper
            for k in ("tableoid", "oid", "tag", "desc"):
                e[k] = self.str()
            self.int()                                       # section
            for k in ("defn", "drop", "copy", "namespace", "tablespace", "tableam"):
                e[k] = self.str()
            if self.version >= (1, 16, 0):
                self.int()                                   # relkind
            e["owner"] = self.str()
            self.str()                                       # withOids
            while self.str() is not None:                    # dependencies
                pass
            self.byte()                                      # the data offset: a flag byte, then off_size bytes
            self.read(self.off_size)
            self.toc[e["id"]] = e

    def blocks(self):
        """(toc entry, reader of its data chunks) for each data block, in file order, until the archive ends."""
        while True:
            b = self.f.read(1)
            if not b:
                return
            if b[0] != 1:
                raise DumpError(f"data block of type {b[0]}: this reader reads table data only")
            e = self.toc[self.int()]
            yield e


PIECE = 1 << 22


def chunks(a: Archive):
    """The bytes of the current data block, in pieces of at most PIECE bytes: a chunk is a whole COPY row, and a row of a
    table this reader skips can be gigabytes."""
    while True:
        n = a.int()
        if n == 0:
            return
        while n > 0:
            take = min(n, PIECE)
            yield a.read(take)
            n -= take


def skip_block(a: Archive) -> None:
    while True:
        n = a.int()
        if n == 0:
            return
        a.skip(n)


def rows(a: Archive, keep=None):
    """The rows of the COPY text of the current data block, as the bytes of each line without its newline. `keep` is called
    with the first field of a row; a row it rejects is dropped as its chunks pass and never held. A blank line and the `\\.`
    terminator are not rows (the archive ends a table's data with blank lines)."""
    pending, skipping, decided = bytearray(), False, keep is None
    for chunk in chunks(a):
        pos, n = 0, len(chunk)
        while pos < n:
            nl = chunk.find(b"\n", pos)
            end = n if nl < 0 else nl
            if not skipping:
                pending += chunk[pos:end]
                if not decided:
                    t = pending.find(b"\t")
                    if t >= 0 or nl >= 0:
                        if keep(bytes(pending[:t]) if t >= 0 else bytes(pending)):
                            decided = True
                        else:
                            skipping, pending = True, bytearray()
            if nl < 0:
                break
            if not skipping and pending and bytes(pending) != b"\\.":
                yield bytes(pending)
            pending, skipping, decided = bytearray(), False, keep is None
            pos = nl + 1
    if pending and not skipping:
        raise DumpError("a data block ends inside a row")


_ESC = {ord("b"): 8, ord("f"): 12, ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("v"): 11}


def copy_value(raw: bytes):
    """One COPY text field: None for \\N, else the text with the COPY escapes undone."""
    if raw == b"\\N":
        return None
    if b"\\" not in raw:
        return raw.decode("utf-8")
    out, i, n = bytearray(), 0, len(raw)
    while i < n:
        c = raw[i]
        if c != 0x5C or i + 1 >= n:
            out.append(c)
            i += 1
            continue
        d = raw[i + 1]
        if d in _ESC:
            out.append(_ESC[d])
            i += 2
        elif 0x30 <= d <= 0x37:
            j = i + 1
            while j < n and j < i + 4 and 0x30 <= raw[j] <= 0x37:
                j += 1
            out.append(int(raw[i + 1:j], 8) & 0xFF)
            i = j
        elif d == ord("x") and i + 2 < n and chr(raw[i + 2]) in "0123456789abcdefABCDEF":
            j = i + 2
            while j < n and j < i + 4 and chr(raw[j]) in "0123456789abcdefABCDEF":
                j += 1
            out.append(int(raw[i + 2:j], 16))
            i = j
        else:
            out.append(d)
            i += 2
    return out.decode("utf-8")


def columns(copy_stmt: str) -> list[str]:
    m = re.match(r"COPY\s+\S+\s+\((.*?)\)\s+FROM stdin;", copy_stmt or "", re.S)
    if not m:
        raise DumpError(f"not a COPY statement: {copy_stmt!r}")
    return [c.strip().strip('"') for c in m.group(1).split(",")]


def record(cols: list[str], raw: bytes) -> dict:
    f = raw.split(b"\t")
    if len(f) != len(cols):
        raise DumpError(f"a row has {len(f)} fields, its table {len(cols)}")
    return {c: copy_value(v) for c, v in zip(cols, f)}


_TS = re.compile(r"(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)(?:\.\d+)?([+-]\d\d)(?::?(\d\d))?$")


def utc_text(ts: str | None) -> str | None:
    """A timestamptz as the export prints the run start: UTC, to the second, 'YYYY-MM-DD HH:MM:SS+00'."""
    if ts is None:
        return None
    m = _TS.match(ts)
    if not m:
        raise DumpError(f"unreadable timestamp {ts!r}")
    y, mo, d, h, mi, sec, oh, om = m.groups()
    off = (-1 if oh.startswith("-") else 1) * (abs(int(oh)) * 60 + int(om or 0))
    t = datetime(int(y), int(mo), int(d), int(h), int(mi), int(sec)) - timedelta(minutes=off)
    return t.strftime("%Y-%m-%d %H:%M:%S") + "+00"


def _bool(v):
    return None if v is None else v == "t"


def _int(v):
    return None if v is None else int(v)


def _json(v):
    return None if v is None else json.loads(v)


def api_row(br: dict, cfg: dict, wr: dict) -> dict:
    """The live API's row for a dump record: the export row (benchmark_results joined with configs and workflow_runs) in the
    API's shape. The id is a string, run_url carries /attempts/N, curve_* are the record's run and date, and power_audit,
    power_invalid_reasons and workers are columns of benchmark_results."""
    r = {
        "id": str(int(br["id"])), "run_url": f"{wr['html_url']}/attempts/{int(wr['run_attempt'])}",
        "model": cfg["model"], "hardware": cfg["hardware"], "precision": cfg["precision"], "framework": cfg["framework"],
        "benchmark_type": br["benchmark_type"], "conc": _int(br["conc"]), "date": br["date"],
        "recipe_fingerprint": br["recipe_fingerprint"], "image": br["image"], "isl": _int(br["isl"]), "osl": _int(br["osl"]),
        "offload_mode": br["offload_mode"], "spec_method": cfg["spec_method"], "disagg": _bool(cfg["disagg"]),
        "is_multinode": _bool(cfg["is_multinode"]),
        "prefill_tp": _int(cfg["prefill_tp"]), "prefill_ep": _int(cfg["prefill_ep"]),
        "decode_tp": _int(cfg["decode_tp"]), "decode_ep": _int(cfg["decode_ep"]),
        "prefill_dp_attention": _bool(cfg["prefill_dp_attention"]), "decode_dp_attention": _bool(cfg["decode_dp_attention"]),
        "prefill_num_workers": _int(cfg["prefill_num_workers"]), "decode_num_workers": _int(cfg["decode_num_workers"]),
        "num_prefill_gpu": _int(cfg["num_prefill_gpu"]), "num_decode_gpu": _int(cfg["num_decode_gpu"]),
        "metrics": _json(br["metrics"]),
        "curve_workflow_run_id": None if br["workflow_run_id"] is None else str(int(br["workflow_run_id"])),
        "curve_date": br["date"], "curve_run_started_at": utc_text(wr["run_started_at"]),
        "power_audit": _json(br["power_audit"]), "power_invalid_reasons": _json(br["power_invalid_reasons"]),
        "workers": _json(br["workers"]),
    }
    return r


# ---------------------------------------------------------------- the selection and the single pass
def select_rule(row: dict) -> str | None:
    """None when the unit's kept row is in the lane, else why it is not."""
    if row["benchmark_type"] != SELECTED_TYPE:
        return "not_single_turn"
    if row["framework"] not in LANE_FRAMEWORKS:
        return "framework_not_scored"
    if str(row["hardware"]).startswith(EXCLUDED_HARDWARE_PREFIX):
        return "amd_chip"
    return None


class Slice:
    """What one pass over the archive keeps."""

    def __init__(self, lg, anchors: set[str]):
        self.lg, self.anchors = lg, anchors
        self.want_records = {r for u in anchors for r in lg.units[u].records()}
        self.slim = {}              # every record id -> (workflow_run_id, date)
        self.full = {}              # wanted record id -> benchmark_results row
        self.configs = {}
        self.runs = {}
        self.logs = {}              # server_log_id -> path of the log text
        self.selected = {}          # unit id -> kept record id
        self.skipped = Counter()
        self.max_id = 0
        self.counts = Counter()
        self.bytes_logs = 0

    def benchmark_results(self, a: Archive, entry: dict):
        cols = columns(entry["copy"])
        for need in ("id", "workflow_run_id", "date", "server_log_id", "metrics"):
            if need not in cols:
                raise DumpError(f"benchmark_results has no {need} column")
        i_id, i_wf, i_date = cols.index("id"), cols.index("workflow_run_id"), cols.index("date")
        for raw in rows(a):
            f = raw.split(b"\t")
            rid = int(f[i_id])
            self.slim[rid] = (copy_value(f[i_wf]), copy_value(f[i_date]))
            self.max_id = max(self.max_id, rid)
            if str(rid) in self.want_records:
                self.full[str(rid)] = {c: copy_value(v) for c, v in zip(cols, f)}
        self.counts["benchmark_results"] = len(self.slim)

    def pick_units(self):
        """The units to extract, once benchmark_results and configs are read: for each anchor unit, its kept row (the first
        of its records the dump holds) must meet the lane's rule and carry a server log."""
        for uid in sorted(self.anchors):
            recs = self.lg.units[uid].records()
            have = [r for r in recs if r in self.full]
            if not have:
                self.skipped["not_in_dump"] += 1              # the API's unit: its records are above the dump's cutoff
                continue
            if len(have) != len(recs):
                raise DumpError(f"unit {uid}: the dump holds {len(have)} of its {len(recs)} records; it is owned by both "
                                "the dump and the API")
            kept = self.full[have[0]]
            cfg = self.configs[kept["config_id"]]
            why = select_rule({**kept, **cfg})
            if why is None and kept["server_log_id"] is None:
                why = "no_server_log"
            if why:
                self.skipped[why] += 1
                continue
            self.selected[uid] = have[0]

    def server_logs(self, a: Archive, entry: dict, tmp: Path):
        cols = columns(entry["copy"])
        i_log = cols.index("server_log")
        want = {self.full[r]["server_log_id"].encode(): r for r in self.selected.values()}
        tmp.mkdir(parents=True, exist_ok=True)
        for raw in rows(a, keep=lambda first: first in want):
            f = raw.split(b"\t")
            sid = f[0].decode()
            text = copy_value(f[i_log])
            (tmp / sid).write_bytes(text.encode("utf-8"))
            self.logs[sid] = tmp / sid
            self.bytes_logs += len(text)
        self.counts["server_logs_kept"] = len(self.logs)

    def stream(self, a: Archive, tmp: Path):
        """Handle the data blocks in file order. benchmark_results and configs must precede server_logs, and workflow_runs
        come last in the archive pg_dump wrote; a reordered archive stops the run."""
        done = set()
        for e in a.blocks():
            name = e["tag"]
            if e["desc"] != "TABLE DATA" or name not in TABLES:
                skip_block(a)
                continue
            if name == "server_logs" and not {"benchmark_results", "configs"} <= done:
                raise DumpError("server_logs precedes benchmark_results or configs in this archive")
            if name == "workflow_runs" and "benchmark_results" not in done:
                raise DumpError("workflow_runs precedes benchmark_results in this archive")
            log(f"  reading {name}")
            if name == "benchmark_results":
                self.benchmark_results(a, e)
            elif name == "configs":
                cols = columns(e["copy"])
                self.configs = {r["id"]: r for r in (record(cols, raw) for raw in rows(a))}
                self.pick_units()
                log(f"  {len(self.selected)} units selected; skipped {dict(self.skipped)}")
            elif name == "server_logs":
                self.server_logs(a, e, tmp)
            else:
                cols = columns(e["copy"])
                self.runs = {r["id"]: r for r in (record(cols, raw) for raw in rows(a))}
                self.counts["workflow_runs"] = len(self.runs)
            done.add(name)
        if done != set(TABLES):
            raise DumpError(f"the archive lacks the tables {sorted(set(TABLES) - done)}")

    # -- after the pass
    def run_dates(self) -> dict:
        """contract.run_dates over every record of the dump: the earliest date of each benchmark run."""
        slim = []
        for rid, (wf, date) in self.slim.items():
            wr = self.runs.get(wf)
            if wr is not None:
                slim.append({"run_url": f"{wr['html_url']}/attempts/{int(wr['run_attempt'])}", "date": date})
        return contract.run_dates(slim)

    def point_rows(self) -> list[dict]:
        out = []
        for uid in self.selected:
            for rid in self.lg.units[uid].records():
                br = self.full[rid]
                out.append(api_row(br, self.configs[br["config_id"]], self.runs[br["workflow_run_id"]]))
        return out


# ---------------------------------------------------------------- freezing (the harness's own pull.freeze_point)
class Git:
    """A bare clone of the public recipe repository; a commit the clone lacks is fetched by sha (one at a time)."""

    def __init__(self, git_dir):
        self.dir, self.lock, self.failed = str(git_dir), threading.Lock(), set()

    def run(self, *args):
        return subprocess.run(["git", "--git-dir", self.dir, *args], capture_output=True)

    def ensure(self, sha):
        if self.run("cat-file", "-e", sha + "^{commit}").returncode == 0:
            return True
        with self.lock:
            if sha in self.failed:
                return False
            if self.run("cat-file", "-e", sha + "^{commit}").returncode == 0:
                return True
            time.sleep(0.5)
            ok = self.run("fetch", "-q", "origin", sha).returncode == 0
            if not ok:
                self.failed.add(sha)
            return ok

    def stamp(self, sha):
        if not self.ensure(sha):
            return None
        out = self.run("show", "-s", "--format=%ct", sha).stdout.decode().strip()
        return datetime.fromtimestamp(int(out), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if out else None


class GitRecipesDb(rcp.GitRecipes):
    def _tree(self, sha):
        self.git.ensure(sha)
        return super()._tree(sha)


class OfflineGH:
    """Stands in for artifacts.GitHubArtifacts: no artifact or job log is read; the run's commit comes from workflow_runs."""
    repo = pl.IX_REPO

    def __init__(self, shas, git):
        self.shas, self.git = shas, git

    def _gone(self, what):
        return urllib.error.HTTPError(f"offline:{what}", 404, "not fetched (offline adapter)", {}, io.BytesIO(b""))

    def list_cached(self, run_id):
        raise self._gone("artifacts")

    def run(self, run_id):
        sha = self.shas.get(str(run_id))
        if not sha:
            raise self._gone("run")
        return {"sha": sha, "date": self.git.stamp(sha)}

    def job_logs_cached(self, run_id, attempt):
        return {}, 1


class OfflineResolver:
    """The build is not resolved offline: every point's build is recorded estimated, with the reason."""

    def __init__(self, ref):
        self.ref = ref

    def resolve(self, image, server_log=None):
        b = build.Build(image=image or "", ref=self.ref)
        b.why = build.COMMIT_UNRESOLVABLE
        return b


def base_models(out: Path, points: list[dict], prior: dict | None, use_hub: bool) -> dict:
    """base_model of every served checkpoint repo, frozen so scoring needs no network."""
    import score as sc
    base = {}
    for e in points:
        if (e.get("checkpoint") or {}).get("repo"):
            base.setdefault(e["checkpoint"]["repo"], None)
        b = sc._read(out / "points" / e["point_id"], e["files"], "server_log")
        if b:
            rd = st.read_args(b.decode("utf-8", "replace"))
            for k in ("served_model_name", "model"):
                for v in rd.values.get(k, []):
                    for x in (v if isinstance(v, list) else [v]):
                        r = sp.hf_repo(x)
                        if r:
                            base.setdefault(r, None)
    for repo in sorted(base):
        if prior is not None and repo in prior:
            base[repo] = prior[repo]
        elif not use_hub:
            base[repo] = {"lookup_failed": "not looked up"}
        else:
            time.sleep(0.5)
            try:
                doc = api.decode(api.http_fetch(f"https://huggingface.co/api/models/{repo}"))
                bm = (doc.get("cardData") or {}).get("base_model")
                base[repo] = (bm[0] if isinstance(bm, list) and len(bm) == 1 else bm if isinstance(bm, str) else None)
            except urllib.error.HTTPError as e:
                base[repo] = None if e.code == 404 else {"lookup_failed": f"HTTP {e.code}"}
    return base


def freeze(sl: Slice, out: Path, git_dir: Path, workers: int) -> list[dict]:
    rows_ = sl.point_rows()
    lg = sl.lg
    placed = pl.place(rows_, lg, dates=sl.run_dates())
    byid = {p.point_id: p for p in placed.points}
    if set(byid) != set(sl.selected):
        raise DumpError(f"placing the rows gave {len(byid)} units, the selection {len(sl.selected)}")
    shas = {str(r["github_run_id"]): r["head_sha"] for r in sl.runs.values() if r["head_sha"]}
    git = Git(git_dir)

    def get(path):
        m = re.fullmatch(r"/repos/[^/]+/[^/]+/actions/runs/(\d+)", path)
        if m and m.group(1) in shas:
            return {"head_sha": shas[m.group(1)]}
        raise urllib.error.HTTPError(path, 404, "run not in workflow_runs", {}, io.BytesIO(b""))
    recipes = GitRecipesDb(get, pl.IX_REPO, git_dir)
    recipes.git = git
    gh = OfflineGH(shas, git)
    resolver = OfflineResolver(build.VLLM_REF)
    scoring = engines.DEFAULT_SCORING | {engines.SGLANG}
    log_of = {r: sl.logs[sl.full[r]["server_log_id"]] for r in sl.selected.values()}

    def fetch(url):
        m = re.search(r"/server-log\?id=(\d+)", url)
        if not m or m.group(1) not in log_of:
            raise RuntimeError("unexpected fetch " + url)
        return json.dumps({"serverLog": log_of[m.group(1)].read_bytes().decode("utf-8")}).encode()

    def one(uid):
        pt = byid[uid]
        try:
            e = pl.freeze_point(pt, resolver=resolver, gh=gh, fetch=fetch, out=out, recipes=recipes, scoring=scoring)
            if "server_log" in e["files"]:
                e["files"]["server_log"]["from"] = FROZEN_FROM
        except Exception as ex_:  # noqa: BLE001
            e = {"point_id": uid, "identity": dict(pt.unit.identity), "row": pt.row, "records": pt.records,
                 "measurements": pt.measurements, "files": {}, "build": None, "reasons": [PULL_ERROR],
                 "problems": [repr(ex_)[:500]]}
        e["source"] = SOURCE_LABEL
        return e

    done = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for n, e in enumerate(pool.map(one, sorted(byid)), 1):
            done.append(e)
            if n % 200 == 0:
                log(f"  frozen {n}/{len(byid)}")
    return done


def write_extract(out: Path, points: list[dict], pin: dict, lg, bases: dict, pulled_at: str, cutoff_id: int) -> str:
    dates = sorted(str(p["row"]["date"])[:10] for p in points)
    meta = {"window": [dates[0], dates[-1]], "pulled_at": pulled_at, "vllm_ref": build.VLLM_REF,
            "vllm_max_distance": build.VLLM_MAX_DISTANCE, "unnamed_slugs": [], "base_models": bases,
            "undated_row_ids": [], "ledger": {"revision": lg.revision, "unlisted": []},
            "source": f"{pin['ref']} via dump_extract.py (offline adapter)"}
    pl.write_manifest(out, meta, points)
    return content_sha256(out)


# ---------------------------------------------------------------- hashes and verification
def content_sha256(extract: Path) -> str:
    """sha256 of the manifest without the fields that say when or how it was cut (VOLATILE). The manifest holds each frozen
    file's sha256, so this covers every byte the score reads; `check_files` ties the files on disk to those."""
    m = json.loads((Path(extract) / "manifest.json").read_text())
    for k in VOLATILE:
        m.pop(k, None)
    return hashlib.sha256(contract.canonical_dumps(m).encode("utf-8")).hexdigest()


def check_files(extract: Path) -> list[str]:
    """Every file the manifest lists exists and gunzips to the bytes it hashes to; nothing else is in points/."""
    import gzip
    extract = Path(extract)
    m = json.loads((extract / "manifest.json").read_text())
    bad, listed = [], set()
    for e in m["points"]:
        for role, f in (e.get("files") or {}).items():
            p = extract / "points" / e["point_id"] / f["path"]
            listed.add(p)
            if not p.is_file():
                bad.append(f"{p.relative_to(extract)} is missing")
            elif hashlib.sha256(gzip.decompress(p.read_bytes())).hexdigest() != f["sha256"]:
                bad.append(f"{p.relative_to(extract)} is not the bytes the manifest hashes")
    on_disk = {p for p in (extract / "points").rglob("*") if p.is_file()} if (extract / "points").is_dir() else set()
    bad += [f"{p.relative_to(extract)} is not in the manifest" for p in sorted(on_disk - listed)]
    return bad


def verify(extract: Path, pin: dict) -> list[str]:
    extract = Path(extract)
    if not (extract / "manifest.json").is_file():
        return ["no manifest.json"]
    problems = check_files(extract)
    got = content_sha256(extract)
    if got != pin["extract_sha256"]:
        problems.append(f"the extract's content sha256 is {got}, not the pinned {pin['extract_sha256']}")
    return problems


# ---------------------------------------------------------------- the command
def cmd_extract(a) -> int:
    pin = load_pin(Path(a.pin))
    out = Path(a.out)
    if out.exists() and any(out.iterdir()):
        log(f"FATAL: {out} is not empty")
        return 2
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    lg = ldg.load(Path(a.ledger))
    anchors = ldg.read_unit_set(Path(a.anchor), "anchor")
    unknown = sorted(anchors - set(lg.units))
    if unknown:
        raise DumpError(f"{len(unknown)} anchor units are not units of the ledger {lg.revision}, the first {unknown[0]}")
    tmp = Path(a.tmp) if a.tmp else out.parent / (out.name + ".tmp")
    git_dir = Path(a.git_dir) if a.git_dir else tmp / "ix.git"
    if not git_dir.exists():
        log(f"cloning the recipe repository to {git_dir}")
        subprocess.run(["git", "clone", "--bare", "-q", f"https://github.com/{pl.IX_REPO}.git", str(git_dir)], check=True)
    sl = Slice(lg, anchors)
    ps = PartStream(pin, Path(a.parts_dir) if a.parts_dir else None)
    log(f"streaming {len(pin['parts'])} parts of {pin['ref']}")
    try:
        sl.stream(Archive(ps.out), tmp / "logs")
    finally:
        ps.close()
    stream_s = time.time() - t0
    log(f"stream done in {stream_s:.0f} s: {sl.counts['benchmark_results']} records, max id {sl.max_id}, "
        f"{len(sl.selected)} units, {sl.bytes_logs / 1e6:.0f} MB of logs kept")
    points = freeze(sl, out, git_dir, a.workers)
    prior = None
    if a.base_models_from:
        prior = json.loads(Path(a.base_models_from).read_text()).get("base_models") or {}
    bases = base_models(out, points, prior, use_hub=not a.no_hub)
    pulled_at = a.pulled_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sha = write_extract(out, points, pin, lg, bases, pulled_at, sl.max_id)
    report = {"ref": pin["ref"], "sha256sums": pin["sha256sums"], "pulled_at": pulled_at, "extract_sha256": sha,
              "units": len(points), "cutoff_record_id": sl.max_id, "records_in_dump": sl.counts["benchmark_results"],
              "skipped": dict(sl.skipped), "ledger_revision": lg.revision,
              "stream_seconds": round(stream_s), "total_seconds": round(time.time() - t0),
              "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1 << 20 if sys.platform == "darwin" else 1 << 10)),
              "log_bytes_kept": sl.bytes_logs}
    (out / "extract-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    shutil.rmtree(tmp / "logs", ignore_errors=True)
    log(json.dumps(report, sort_keys=True))
    problems = verify(out, pin) if not a.no_verify else []
    for p in problems:
        log("MISMATCH: " + p)
    return 1 if problems else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pin", default=str(PIN_PATH))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("extract")
    p.add_argument("--ledger", required=True)
    p.add_argument("--anchor", required=True)
    p.add_argument("--out", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--parts-dir")
    g.add_argument("--download", action="store_true")
    p.add_argument("--git-dir")
    p.add_argument("--tmp")
    p.add_argument("--base-models-from")
    p.add_argument("--no-hub", action="store_true", help="look up no base_model on the model hub")
    p.add_argument("--pulled-at")
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--no-verify", action="store_true", help="skip the check against the pinned extract hash")
    p = sub.add_parser("verify")
    p.add_argument("--extract", required=True)
    p = sub.add_parser("hash")
    p.add_argument("--extract", required=True)
    sub.add_parser("cache-key")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "extract":
            return cmd_extract(a)
        if a.cmd == "hash":
            print(content_sha256(Path(a.extract)))
            return 0
        pin = load_pin(Path(a.pin))
        if a.cmd == "cache-key":
            print(cache_key(pin))
            return 0
        problems = verify(Path(a.extract), pin)
        for p in problems:
            log("MISMATCH: " + p)
        if not problems:
            log(f"extract ok: content sha256 {pin['extract_sha256']}")
        return 1 if problems else 0
    except (DumpError, ldg.LedgerError, OSError) as e:
        log(f"FATAL: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
