"""What each side of a whole-run gate evaluation was scored against, and the trusted job's check of it.

The base and the candidate bind to their own simulator: each side's `.github/stack-pins.env` SIM_REF at the
commit it was dispatched on (the merge base for the base, the pull request head for the candidate) names the
inference-sim build, and through that build's stack.json the catalog, registry, ledger and engine fields it
scores over. A pull request that moves the pin is therefore evaluated as old build against new build, not
refused as "the two runs differ". What must still be one thing for both sides is the held-out partition's
ledger: the units handed out and the units graded are the same on both sides or there is nothing to compare.

The gate-candidate run records, next to its predictions, `sim.txt` (the simulator commit), `substrate.txt`
(the commit of the data) and `ledger.sha256`. The gate job does not believe them: it resolves the same values
from the pin read through the Actions API with main's own `resolve_data.sh` and compares.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SIM_REF = re.compile(r"^(v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?|[0-9a-f]{40})$")
RESOLVED_KEYS = ("SIM_COMMIT", "DATA_DIR", "DATA_COMMIT", "DATA_PIN", "FIELDS", "VLLM_REF")

# Provenance keys that name the simulator build or the data it read. Two sides that run different builds
# differ in them by construction; check_side binds them to each side's pin; they are not compared across sides.
SIDE_BOUND = ("blis", "simulator", "engine", "engines", "experimental", "vllm_ref", "vllm_max_distance",
              "fields_sha256", "pull_manifest_sha256", "corpora")


class BindingError(Exception):
    pass


def read_sim_pin(text: str) -> str:
    """SIM_REF from the text of a stack-pins.env: exactly one assignment, a release tag or a 40-hex commit."""
    found = []
    for line in text.splitlines():
        m = re.match(r"^\s*SIM_REF=(.*?)\s*$", line)
        if m:
            found.append(m.group(1).strip("\"'"))
    if len(found) != 1:
        raise BindingError(f"stack-pins.env assigns SIM_REF {len(found)} times; it must assign it once")
    if not SIM_REF.match(found[0]):
        raise BindingError("SIM_REF is neither a release tag nor a 40-hex commit")
    return found[0]


def ledger_digest(ledger_dir: Path) -> str:
    """One SHA-256 over every file of a ledger directory: each relative path and its bytes, in path order."""
    root = Path(ledger_dir)
    files = sorted(p for p in root.rglob("*") if p.is_file())
    if not files:
        raise BindingError(f"{ledger_dir} holds no ledger files")
    h = hashlib.sha256()
    for p in files:
        rel = p.relative_to(root).as_posix().encode()
        h.update(len(rel).to_bytes(8, "big") + rel)
        data = p.read_bytes()
        h.update(len(data).to_bytes(8, "big") + data)
    return h.hexdigest()


def parse_resolved(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    missing = [k for k in RESOLVED_KEYS if not out.get(k)]
    if missing:
        raise BindingError(f"resolve_data.sh did not print {', '.join(missing)}")
    return out


def _line(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        raise BindingError(f"the artifact holds no {path.name}") from None


def check_side(label: str, resolved: dict, artifact: Path) -> str:
    """Refuse (BindingError) unless the side's recorded simulator commit, data commit and ledger digest are the
    ones its pin resolves to. Returns the ledger digest the data carries."""
    artifact = Path(artifact)
    sim, data, led = _line(artifact / "sim.txt"), _line(artifact / "substrate.txt"), _line(artifact / "ledger.sha256")
    for name, v, pat in (("sim.txt", sim, HEX40), ("substrate.txt", data, HEX40), ("ledger.sha256", led, HEX64)):
        if not pat.match(v):
            raise BindingError(f"the {label} run's {name} is not a digest")
    if sim != resolved["SIM_COMMIT"]:
        raise BindingError(f"the {label} run scored simulator {sim[:12]}, not {resolved['SIM_COMMIT'][:12]} that its commit pins")
    if data != resolved["DATA_COMMIT"]:
        raise BindingError(f"the {label} run read data at {data[:12]}, not {resolved['DATA_COMMIT'][:12]} that its simulator pins")
    want = ledger_digest(Path(resolved["DATA_DIR"]) / "catalog" / "ledger")
    if led != want:
        raise BindingError(f"the {label} run's ledger is not the ledger its simulator pins carry")
    return want


def check_pair(base_ledger: str, cand_ledger: str) -> None:
    if base_ledger != cand_ledger:
        raise BindingError("the base and the candidate simulators carry different ledgers; the held-out partition "
                           "must be one ledger for both sides")
