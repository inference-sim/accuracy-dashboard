#!/usr/bin/env python3
"""Freeze, once per ledger version, every GitHub input the night's anchor units need (docs/nightly.md).

The ledger extract (ledger_extract.py) holds the rows and the vLLM logs of the pinned dump. What it does not hold
came from GitHub at every night: each run's artifact listing, its agentic exports and launch configs, the job logs
of its client, the P/D recipes at its commit, and the build resolver's vLLM commit lookups. Asked every night, those
spent the REST budget every agent and workflow shares, and broke when an artifact expired. This freezes them once,
into a pull of every anchor unit (the harness's own pull, cli.cmd_pull), and packs it into one archive pinned by its
sha256 beside the extract. The night replays the archive and asks GitHub nothing (cli.cmd_nightly).

The recipes and the resolver's commit questions are answered from blobless clones of InferenceX and vLLM, and each
run's head commit from the pinned source (gitlocal.py, ledger_extract.run_heads), so only the artifact listings,
artifact downloads and the job-log archives use REST. A unit whose inputs GitHub no longer holds is G5 with the reason
the pull names (artifact_unmatched:run_gone_404 and the like), decided here, once.

    freeze_ledger.py freeze --extract E --ledger DIR --out PULL --cache DIR --vllm-clone DIR --ix-clone DIR
                            [--shard K/N] [--per-hour 1500] [--floor 1000] [--batch 200]
        Resumable: a point already in PULL is kept. The runs are split into N shards by run id, so two freezes
        (here and in Actions) never fetch the same run. Before each batch the REST budget is read (GET /rate_limit,
        which spends none); below --floor it waits for the reset, and it spends at most --per-hour an hour.
        Exit 0 when every point is frozen, 3 when --until came first (the next run continues from PULL).
    freeze_ledger.py merge --pulls A B ... --out PULL
    freeze_ledger.py pack --pull PULL --out ARCHIVE.tar.gz
        Prints {"sha256", "bytes", "points"}: the archive's bytes depend only on its files.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import sys
import tarfile
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import api  # noqa: E402
import cli  # noqa: E402
import clients  # noqa: E402
import ledger as ldg  # noqa: E402
import ledger_extract as lx  # noqa: E402
import pull as pl  # noqa: E402

LOOKUPS = "lookups.json"


def shard_of(run: str | None, n: int) -> int:
    """The shard a run belongs to: its id's sha256 modulo n (a point with no run is shard 0)."""
    return 0 if run is None else int(hashlib.sha256(run.encode()).hexdigest(), 16) % n


def rate(token: str) -> tuple[int, int]:
    """(core requests remaining, the reset time) of the token's REST budget. GET /rate_limit spends none."""
    doc = clients._get_json("https://api.github.com/rate_limit", {"Authorization": f"Bearer {token}"}, 60)
    core = doc["resources"]["core"]
    return int(core["remaining"]), int(core["reset"])


class Budget:
    """At most `per_hour` requests an hour, and never below `floor` left: wait otherwise."""

    def __init__(self, token, per_hour, floor, sleep=time.sleep, clock=time.time, rate_fn=rate):
        self.token, self.per_hour, self.floor = token, per_hour, floor
        self.sleep, self.clock, self.rate_fn = sleep, clock, rate_fn
        self.hour_start, self.hour_left = None, None
        self.spent = 0

    def before_batch(self, log=print) -> None:
        remaining, reset = self.rate_fn(self.token)
        now = self.clock()
        if self.hour_start is None or now - self.hour_start >= 3600:
            self.hour_start, self.hour_left = now, remaining
        used = self.hour_left - remaining
        if used >= self.per_hour:
            wait = 3600 - (now - self.hour_start)
            log(f"freeze: {used} requests this hour, the most it spends; waiting {int(wait)} s")
            self.sleep(max(wait, 1))
            return self.before_batch(log)
        if remaining < self.floor:
            wait = max(reset - now, 1) + 5
            log(f"freeze: {remaining} requests left, below the floor of {self.floor}; waiting {int(wait)} s for the reset")
            self.sleep(wait)
            self.hour_start = None
            return self.before_batch(log)


def freeze(a) -> int:
    lg = ldg.load(Path(a.ledger))
    anchors = ldg.read_unit_set(Path(a.ledger) / "published" / "anchor.yaml", role="anchor")
    records = {str(r) for u in anchors if u in lg.units for r in lg.units[u].records()}
    rows, logs = lx.read(Path(a.extract), keep_log=records.__contains__)
    heads = lx.run_heads(Path(a.extract))
    mine, _ = cli.read_source_rows(rows, lg, anchors)
    k, n = (int(x) for x in a.shard.split("/"))
    points = [p for p in pl.place(mine, lg).points
              if shard_of(str(api.run_of(p.row)[0]) if api.run_of(p.row) else None, n) == k]
    out = Path(a.out)
    done = set()
    if (out / "manifest.json").is_file():
        done = {e["point_id"] for e in json.loads((out / "manifest.json").read_text())["points"]
                if cli.PULL_ERROR not in e["reasons"]}
    todo = sorted(p.point_id for p in points if p.point_id not in done)
    print(f"freeze: shard {k}/{n}: {len(points)} anchor units, {len(done)} frozen, {len(todo)} to freeze")
    store = json.loads((out / LOOKUPS).read_text()) if (out / LOOKUPS).is_file() else {}
    token = clients.require_github_token()
    budget = Budget(token, a.per_hour, a.floor)
    for i in range(0, len(todo), a.batch):
        if a.until and time.time() > a.until:
            print(f"freeze: stopping at the time limit with {len(done)} of {len(points)} frozen; a later run continues")
            return 3
        batch = todo[i:i + a.batch]
        while True:
            budget.before_batch()
            try:
                rc = cli.cmd_pull(types.SimpleNamespace(
                    out=str(out), today=None, window_days=180, cache=a.cache, prior=str(out) if done else None,
                    only=sorted(done | set(batch)), download_workers=a.workers, ledger=a.ledger, rows=mine,
                    source_logs=logs, run_heads=heads, vllm_clone=a.vllm_clone, ix_clone=a.ix_clone, lookups=store))
            except clients.RateLimited as e:
                print(f"freeze: rate limited ({e}); waiting for the reset")
                budget.hour_start = None
                remaining, reset = rate(token)
                time.sleep(max(reset - time.time(), 1) + 5)
                continue
            break
        (out / LOOKUPS).write_text(json.dumps(store, sort_keys=True, indent=0))
        if rc != 0:
            print(f"freeze: the pull exited {rc}; stopping (its manifest names the failed points)")
            return rc
        done |= set(batch)
        print(f"freeze: {len(done)} of {len(points)} frozen")
    return 0


def merge(pulls: list[Path], out: Path) -> int:
    """One pull from shards that froze disjoint runs: the points, their files, the base models and the lookups."""
    out.mkdir(parents=True, exist_ok=True)
    metas, points, store = [], {}, {}
    for p in pulls:
        m = json.loads((p / "manifest.json").read_text())
        metas.append({k: v for k, v in m.items() if k != "points"})
        for e in m["points"]:
            if e["point_id"] in points:
                raise ValueError(f"point {e['point_id']} is in two shards")
            points[e["point_id"]] = e
            src = p / "points" / e["point_id"]
            if src.is_dir():
                shutil.copytree(src, out / "points" / e["point_id"], dirs_exist_ok=True)
        if (p / LOOKUPS).is_file():
            for kind, d in json.loads((p / LOOKUPS).read_text()).items():
                store.setdefault(kind, {}).update(d)
    meta = dict(metas[0])
    meta["base_models"] = {k: v for m in metas for k, v in (m.get("base_models") or {}).items()}
    meta["pulled_at"] = max(m["pulled_at"] for m in metas)
    pl.write_manifest(out, meta, sorted(points.values(), key=lambda e: e["point_id"]))
    (out / LOOKUPS).write_text(json.dumps(store, sort_keys=True, indent=0))
    return len(points)


def pack(pull: Path, out: Path) -> dict:
    """A tar of the pull, every entry with mode 0644, owner 0 and time 0, in path order, gzip with no name or time."""
    files = sorted(f for f in pull.rglob("*") if f.is_file())
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for f in files:
            info = tarfile.TarInfo(str(f.relative_to(pull)))
            data = f.read_bytes()
            info.size, info.mode, info.mtime, info.uid, info.gid, info.uname, info.gname = len(data), 0o644, 0, 0, 0, "", ""
            tar.addfile(info, io.BytesIO(data))
    import gzip
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as fh:
        with gzip.GzipFile(filename="", mode="wb", fileobj=fh, mtime=0, compresslevel=9) as gz:
            gz.write(buf.getvalue())
    points = len(json.loads((pull / "manifest.json").read_text())["points"])
    return {"sha256": lx.sha256(out), "bytes": out.stat().st_size, "points": points}


def unpack(archive: Path, pin: dict, out: Path) -> None:
    """The archive's files into `out`, after its sha256 and size are checked against the pin's."""
    got = lx.sha256(archive)
    if got != pin["sha256"] or archive.stat().st_size != pin["bytes"]:
        raise ValueError(f"{archive} has sha256 {got}; the pin names {pin['sha256']}")
    with tarfile.open(archive, "r:gz") as tar:
        for m in tar.getmembers():
            if not m.isfile() or m.name.startswith(("/", "..")) or ".." in Path(m.name).parts:
                raise ValueError(f"{archive}: entry {m.name} is not a file inside the pull")
        tar.extractall(out, filter="data")


def replay(archive: Path, pin: dict, work: Path, anchors: set[str], vllm_ref: str, token: str | None) -> int:
    """The night's pull, from the frozen archive: its points of `anchors`, with each build record made again for the
    engine release this night scores (`vllm_ref`), from the archive's recorded lookups. Returns the requests made: a
    lookup the archive does not hold (a new release moves the reference) is asked live and counted."""
    import build
    import lookups as lkp
    import score as sc
    if work.exists():
        shutil.rmtree(work)
    unpack(archive, pin, work)
    m = json.loads((work / "manifest.json").read_text())
    store = json.loads((work / LOOKUPS).read_text()) if (work / LOOKUPS).is_file() else {}
    resolver = build.Resolver(registry=clients.DockerHubRegistry(), github=clients.GitHubREST(token), ref=vllm_ref)
    gh, reg = lkp.wrap(resolver, store)
    keep = []
    for e in m["points"]:
        if e["point_id"] not in anchors:
            pl.prune_point_files(work, e["point_id"])
            continue
        if e.get("build") is not None:
            log = sc._read(work / "points" / e["point_id"], e["files"], "server_log")
            e["build"] = resolver.resolve(e["row"].get("image") or "",
                                          log.decode("utf-8", "replace") if log else None).record()
        keep.append(e)
    meta = {k: v for k, v in m.items() if k != "points"}
    meta.update(vllm_ref=vllm_ref, vllm_max_distance=build.VLLM_MAX_DISTANCE)
    pl.write_manifest(work, meta, keep)
    return gh.misses + reg.misses


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("freeze")
    for k in ("--extract", "--ledger", "--out", "--cache", "--vllm-clone", "--ix-clone"):
        f.add_argument(k, required=True)
    f.add_argument("--shard", default="0/1")
    f.add_argument("--per-hour", type=int, default=1500)
    f.add_argument("--floor", type=int, default=1000)
    f.add_argument("--batch", type=int, default=200)
    f.add_argument("--workers", type=int, default=4)
    f.add_argument("--until", type=int, default=0, help="stop before this Unix time (exit 3: not yet complete)")
    m = sub.add_parser("merge")
    m.add_argument("--pulls", nargs="+", required=True)
    m.add_argument("--out", required=True)
    k = sub.add_parser("pack")
    k.add_argument("--pull", required=True)
    k.add_argument("--out", required=True)
    a = p.parse_args(argv)
    if a.cmd == "freeze":
        return freeze(a)
    if a.cmd == "merge":
        print(json.dumps({"points": merge([Path(x) for x in a.pulls], Path(a.out))}))
        return 0
    print(json.dumps(pack(Path(a.pull), Path(a.out)), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
