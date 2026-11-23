"""A fake partition for tests: a ledger directory with a fixed test seed, invented deployments and a
legacy map, in the format blis-substrate writes. It holds no real unit and no real seed.

build() returns the directory's paths, the seed, and, for the tests that must know a unit's role, the
role table that partition.assign computes (a test may see it: it is the fake's).
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ingest"))
import contract  # noqa: E402
import partition  # noqa: E402
import predictions  # noqa: E402

SEED_HEX = "5eed" * 16
SEED_SHA = hashlib.sha256(bytes.fromhex(SEED_HEX)).hexdigest()
COMMIT = "a" * 40
BASE, CAND = "b" * 40, "c" * 40
HARNESS = "d" * 64
LANES = {"A": ("vllm", "h100", "model-a"), "B": ("vllm", "h200", "model-b"), "C": ("sglang", "h100", "model-a")}
CUTS = """kind: Ledger
partition_version: 1
seed:
  sha256: "%s"
rules:
  inferencex:
    cut_points:
      - {role: fit, from: 0, to: 29}
      - {role: select, from: 30, to: 39}
      - {role: validate, from: 40, to: 49}
      - {role: held, from: 50, to: 79}
      - {role: anchor, from: 80, to: 99}
    legacy:
      FIT:
        - {role: fit, from: 0, to: 74}
        - {role: select, from: 75, to: 99}
      HELD:
        - {role: held, from: 0, to: 59}
        - {role: anchor, from: 60, to: 99}
"""


def identity(lane: str, k: int, conc: int) -> dict:
    framework, hardware, model = LANES[lane]
    return {"source": contract.SOURCE, "model": model, "hardware": hardware, "precision": "fp8", "framework": framework,
            "benchmark_type": "e2e", "configuration_hash": f"cfg-{lane}-{k}", "recipe_fingerprint": "r" * 8,
            "conc": conc, "measured_date": "2026-01-01", "benchmark_run": 1000 + k}


class Fake:
    def __init__(self, ledger: Path, units, legacy, assigned, seed):
        self.ledger, self.units, self.legacy, self.assigned, self.seed = ledger, units, legacy, assigned, seed

    def held(self, lane=None, blind=True):
        return [u for u in self.units if self.assigned[u.unit_id].role == "held"
                and self.assigned[u.unit_id].not_blind != blind
                and (lane is None or u.identity["configuration_hash"].startswith(f"cfg-{lane}-"))]

    def lane_tuple(self, u):
        return (u.identity["framework"], COMMIT, u.identity["hardware"], u.identity["model"], u.identity["configuration_hash"])


def build(directory: Path, keys: dict | None = None, legacy_every: int = 0) -> Fake:
    """keys: lane name -> number of role keys (two units each). legacy_every: every n-th key is on the HELD legacy side."""
    keys = keys or {"A": 160, "B": 160}
    d = Path(directory)
    (d / "units").mkdir(parents=True, exist_ok=True)
    (d / "published").mkdir(exist_ok=True)
    lines = []
    for lane, n in keys.items():
        for k in range(n):
            for conc in (1, 8):
                ident = identity(lane, k, conc)
                lines.append({"unit_id": contract.point_id(ident), "identity": ident,
                              "role_key": partition.role_key_id(partition.role_key(ident)), "measurements": []})
    lines.sort(key=lambda u: u["unit_id"])
    (d / "units" / "inferencex.jsonl.gz").write_bytes(
        gzip.compress("".join(json.dumps(u, sort_keys=True) + "\n" for u in lines).encode(), mtime=0))
    (d / "ledger.yaml").write_text(CUTS % SEED_SHA)
    legacy = {}
    if legacy_every:
        i = 0
        for u in lines:
            if u["identity"]["configuration_hash"].rsplit("-", 1)[1] and int(u["identity"]["configuration_hash"].rsplit("-", 1)[1]) % legacy_every == 0:
                legacy[u["unit_id"]] = "HELD"
    (d / "legacy-map.yaml").write_text("kind: LegacyMap\nunits:\n" + "".join(f"  - {u} {s}\n" for u, s in sorted(legacy.items())))
    cfg = partition.load_config(d)
    units = partition.load_units(d)
    seed = partition.parse_seed(SEED_HEX, SEED_SHA)
    assigned = partition.assign(units, cfg, seed, partition.load_legacy_sides(d))
    for role in ("fit", "anchor"):
        ids = sorted(u.unit_id for u in units if assigned[u.unit_id].role == role)
        (d / "published" / f"{role}.yaml").write_text(
            f"kind: PublishedUnits\nrole: {role}\npartition_version: 1\nseed_sha256: {SEED_SHA}\nunits:\n" + "".join(f"  - {i}\n" for i in ids))
    return Fake(d, units, legacy, assigned, seed)


def measured_table(fake: Fake, path: Path, value=lambda i, u: 1000.0 + i) -> str:
    """Write the measured table (lane columns + meas_tpot) of every unit that is not on a published list, as
    the build step does; return its sha256. A value of None leaves the measurement blank."""
    rows = [u for u in fake.units if fake.assigned[u.unit_id].role not in ("fit", "anchor")]
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["point_id", "engine", "modelled_commit", "chip", "model", "layout", "meas_tpot"])
        for i, u in enumerate(sorted(rows, key=lambda u: u.unit_id)):
            w.writerow([u.unit_id, *fake.lane_tuple(u), "" if value(i, u) is None else repr(value(i, u))])
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def predictions_file(fake: Fake, measured_path: Path, path: Path, candidate: str, factor, harness: str = HARNESS) -> None:
    """Predictions for every measured unit: prediction = measurement * factor(unit)."""
    meas = {r["point_id"]: float(r["meas_tpot"] or 1.0) for r in csv.DictReader(Path(measured_path).read_text().splitlines())}
    by_id = {u.unit_id: u for u in fake.units}
    rows = [{"source": predictions.SOURCE, "unit_id": uid, "values": {"tpot": m * factor(by_id[uid])}} for uid, m in sorted(meas.items())]
    Path(path).write_text(json.dumps({"kind": predictions.KIND, "candidate": candidate, "harness": harness, "predictions": rows}))


def prereg_doc(sha: str, **over) -> dict:
    doc = {"kind": "PreRegistration", "id": "row-99-example", "partition_version": 1,
           "hypothesis": "the new term lowers the error on lane A", "layer": "prefill step time",
           "target_lanes": [{"engine": "vllm", "chip": "h100"}], "sources": ["inferencex"],
           "criteria": [{"criterion": "error", "margin": 0.02}, {"criterion": "distance", "margin": 0.02}], "metrics": ["tpot"],
           "substream": "gate/row-99", "predicted_change": "error falls by at least 0.05 on lane A", "measured_sha256": sha}
    doc.update(over)
    return doc
