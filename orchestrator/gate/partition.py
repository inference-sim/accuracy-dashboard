"""The keyed role rule of the ledger (design §10.2, D7), as the whole-run gate job reads it.

A unit's role is HMAC-SHA-256(seed, canonical JSON of its role key), the digest read as a big-endian
integer, mod 100, read against the source's cut-points; a unit on a legacy side reads the same draw
against its side's cut-point. This mirrors blis-substrate's ledger/roles.go and ledger/assign.go. The seed
exists only in the process of the secret-holding job: it is read from the environment variable the job
names, checked against the hash ledger.yaml records, and never written anywhere.

Only InferenceX has held units (no other source's rule is implemented here), so a ledger that asks for
another source's draw is refused rather than guessed at.
"""
from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingest"))
import contract  # noqa: E402

SOURCE = contract.SOURCE
SEED_BYTES = 32
ROLES = ("fit", "select", "validate", "held", "anchor", "report")
ROLE_KEY_FIELDS = ("source", "model", "hardware", "precision", "framework", "benchmark_type", "configuration_hash")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class PartitionError(ValueError):
    pass


def role_key(identity: dict) -> dict:
    """The role key of an InferenceX identity: the seven fields that name a deployment (blis-substrate
    ledger/inferencex RoleKeyFields)."""
    missing = [f for f in contract.IDENTITY_FIELDS if f not in identity]
    if missing or len(identity) != len(contract.IDENTITY_FIELDS):
        raise PartitionError("a unit's identity does not hold exactly the identity fields")
    if identity["source"] != SOURCE:
        raise PartitionError(f"identity.source is not {SOURCE!r}")
    return {f: identity[f] for f in ROLE_KEY_FIELDS}


def role_key_id(rk: dict) -> str:
    return hashlib.sha256(contract.canonical_dumps(rk).encode("utf-8")).hexdigest()


class Seed:
    """The role seed. It has no repr, no equality and no way to be written out."""
    __slots__ = ("_key",)

    def __init__(self, key: bytes):
        self._key = key

    def __repr__(self) -> str:
        return "Seed(<withheld>)"

    def draw(self, message: str) -> int:
        digest = hmac.new(self._key, message.encode("utf-8"), hashlib.sha256).digest()
        return int.from_bytes(digest, "big") % 100


def parse_seed(hex_seed: str, want_sha256: str) -> Seed:
    """The seed in its hex form, refused unless it is 32 bytes whose SHA-256 is the one ledger.yaml records.
    No message names the seed or any part of it."""
    try:
        key = bytes.fromhex(hex_seed.strip())
    except ValueError:
        raise PartitionError("seed: not hex") from None
    if len(key) != SEED_BYTES:
        raise PartitionError(f"seed: {len(key)} bytes, want {SEED_BYTES} (256 bits, D7)")
    if hashlib.sha256(key).hexdigest() != want_sha256:
        raise PartitionError("seed: its SHA-256 is not the one ledger.yaml records")
    return Seed(key)


def seed_from_env(name: str, want_sha256: str) -> Seed:
    """Read the seed from the environment variable `name`. The value is never an argument."""
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", name):
        raise PartitionError("the seed variable's name is not an environment variable name")
    value = os.environ.get(name)
    if not value:
        raise PartitionError(f"the environment variable {name} is not set; the gate job holds the seed (A3)")
    return parse_seed(value, want_sha256)


@dataclass(frozen=True)
class Config:
    partition_version: int
    seed_sha256: str
    cut_points: tuple          # ((role, from, to), ...)
    legacy: dict               # side -> ((role, from, to), ...)


def _cuts(rows, where) -> tuple:
    out, nxt = [], 0
    for i, r in enumerate(rows or []):
        if not isinstance(r, dict) or set(r) != {"role", "from", "to"} or r["role"] not in ROLES:
            raise PartitionError(f"{where}[{i}]: not a {{role, from, to}} cut-point")
        if r["from"] != nxt or not (r["from"] <= r["to"] <= 99):
            raise PartitionError(f"{where}[{i}]: cut-points cover 0..99 in order with no gap or overlap")
        nxt = r["to"] + 1
        out.append((r["role"], r["from"], r["to"]))
    if nxt != 100:
        raise PartitionError(f"{where}: cut-points end at {nxt - 1}, want 99")
    return tuple(out)


def load_config(ledger_dir: Path) -> Config:
    import yaml
    doc = yaml.safe_load((Path(ledger_dir) / "ledger.yaml").read_text())
    if not isinstance(doc, dict) or doc.get("kind") != "Ledger":
        raise PartitionError("ledger.yaml: kind is not Ledger")
    pv = doc.get("partition_version")
    if not isinstance(pv, int) or isinstance(pv, bool) or pv < 1:
        raise PartitionError("ledger.yaml: partition_version is not a positive integer")
    sha = (doc.get("seed") or {}).get("sha256")
    if not isinstance(sha, str) or not HEX64.match(sha):
        raise PartitionError("ledger.yaml records no seed hash; a ledger owner creates the seed")
    rule = (doc.get("rules") or {}).get(SOURCE)
    if not isinstance(rule, dict):
        raise PartitionError(f"ledger.yaml has no cut-points for {SOURCE}")
    legacy = {s: _cuts((rule.get("legacy") or {}).get(s), f"{SOURCE}.legacy.{s}") for s in ("FIT", "HELD")}
    return Config(pv, sha, _cuts(rule.get("cut_points"), f"{SOURCE}.cut_points"), legacy)


@dataclass(frozen=True)
class Unit:
    unit_id: str
    role_key: str
    identity: dict


def load_units(ledger_dir: Path) -> list[Unit]:
    raw = (Path(ledger_dir) / "units" / f"{SOURCE}.jsonl.gz").read_bytes()
    out = []
    for n, line in enumerate(gzip.decompress(raw).decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        u = json.loads(line)
        ident = u["identity"]
        if contract.point_id(ident) != u["unit_id"]:
            raise PartitionError(f"units line {n}: the identity does not hash to the unit_id")
        if role_key_id(role_key(ident)) != u["role_key"]:
            raise PartitionError(f"units line {n}: role_key is not the hash of the identity's role key")
        out.append(Unit(u["unit_id"], u["role_key"], ident))
    return out


def load_published(ledger_dir: Path, name: str) -> set:
    """The unit ids of a published list ('fit' or 'anchor')."""
    import yaml
    doc = yaml.safe_load((Path(ledger_dir) / "published" / f"{name}.yaml").read_text())
    return set(doc["units"] or [])


def load_legacy_sides(ledger_dir: Path) -> dict:
    """unit_id -> 'FIT' | 'HELD' from legacy-map.yaml, whose units are '<unit_id> <side>' lines."""
    import yaml
    p = Path(ledger_dir) / "legacy-map.yaml"
    if not p.exists():
        return {}
    doc = yaml.safe_load(p.read_text())
    sides = {}
    for line in doc.get("units") or []:
        uid, side = str(line).split()
        if side not in ("FIT", "HELD") or not HEX64.match(uid):
            raise PartitionError("legacy-map.yaml: a unit line is not '<unit_id> FIT|HELD'")
        sides[uid] = side
    return sides


def role_key_sides(units: list[Unit], legacy: dict) -> dict:
    """role_key id -> the side a new unit of that role key takes: its legacy units' side, FIT if both
    (blis-substrate LegacyMap.SetRoleKeySides)."""
    out = {}
    for u in units:
        s = legacy.get(u.unit_id)
        if s is not None and (u.role_key not in out or (out[u.role_key] == "HELD" and s == "FIT")):
            out[u.role_key] = s
    return out


def _role_of(cuts: tuple, d: int) -> str:
    for role, lo, hi in cuts:
        if lo <= d <= hi:
            return role
    raise PartitionError(f"draw {d} falls in no cut-point")


@dataclass(frozen=True)
class Assignment:
    role: str
    not_blind: bool            # on a legacy side: the old labels and side rules are public (§10.2)


def assign(units: list[Unit], cfg: Config, seed: Seed, legacy: dict) -> dict:
    """unit_id -> Assignment, for every unit. Only a process that holds the seed can call this."""
    sides = role_key_sides(units, legacy)
    out = {}
    for u in units:
        d = seed.draw(contract.canonical_dumps(role_key(u.identity)))
        side = legacy.get(u.unit_id) or sides.get(u.role_key)
        out[u.unit_id] = Assignment(_role_of(cfg.legacy[side] if side else cfg.cut_points, d), side is not None)
    return out
