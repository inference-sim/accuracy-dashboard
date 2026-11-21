#!/usr/bin/env python3
"""Score every configiq anchor unit and write its funnel (plan Table W rows 16 and 26; design D9).

configiq is anchor-only: every unit is an anchor unit, scored on the dashboard, never fit, selected, validated, held or
withheld as a test split, and never used to judge a change. The units scored are every id of the substrate's configiq
ledger less rules.configiq.left_out of its ledger.yaml (the units the D2 join found read under a training role; none before
row 26's partition version) -- never read from anchor.yaml, which holds no configiq id until that release.

  configiq_night.py --substrate DIR --blis BLIS --catalog DIR --registry DIR --fields FILE --substrate-version V
                    --substrate-commit SHA --sim-build TAG --harness-commit SHA --out DIR [--workers N]

Steps, each a command of this repository or of the substrate (nothing is fetched but the dataset files, whose sha256 the
substrate's sources.yaml pins, and a mismatch stops the run):
  1 fetch the pinned files of the configiq dataset revision        2 export them to JSON lines (substrate export.py, pyarrow)
  3 score_configiq.py (every anchor unit, no split withheld)       4 build_classes.py derive-configiq -> OUT/classes/configiq.json
  5 baseline/funnel.py -> OUT/funnel.json: the scored count (the provisional band, outside the headline) and the G5
    count per reason; with --published DIR it fails when a configiq id is in a published fit, select or validate list.

Run by hand through .github/workflows/score-configiq.yml, not by the nightly: the ledger's configiq data is pinned to one
dataset revision and moves only when that pin is moved on purpose, so a nightly would score the same units again. The class
file it writes is committed by hand as data/supplemental/classes/configiq.json, which the nightly's classes step reads.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORCH = HERE.parent
sys.path.insert(0, str(ORCH / "baseline"))
sys.path.insert(0, str(ORCH / "ingest"))
import sources as src  # noqa: E402
import stack as sk  # noqa: E402

DATASET = "redhat-performance/configiq-performance-upstream-data"
URL = "https://huggingface.co/datasets/" + DATASET + "/resolve/{ref}/{name}"
NOTE = ("Red Hat's configiq dataset (CC BY 4.0), scored by simulation: each row is simulated as a closed loop at its recorded "
        "concurrency and request count, with the substitutions named below. configiq is anchor-only: every row is an anchor row "
        "and none is fit, selected, validated, held or withheld as a test set. Provisional: graded no better than G3 and "
        "outside the headline. TPOT is GuideLLM's median (it counts the first token) and ITL its mean (the per-request time per "
        "output token after the first). First-token time (TTFT) is not shown as an accuracy figure, because its definition "
        "(client-side delay) is unconfirmed; that was decided on the clarity of the data, before any error was looked at, and "
        "nothing else is hidden.")


class NightError(RuntimeError):
    pass


def pins(sources_yaml: Path) -> tuple[str, list[tuple[str, str]]]:
    """The revision and the (name, sha256) of every file sources.yaml pins for configiq."""
    import yaml
    doc = yaml.safe_load(Path(sources_yaml).read_text())
    rows = [s for s in doc.get("sources", []) if s.get("id") == "configiq"]
    if len(rows) != 1:
        raise NightError(f"{sources_yaml}: expected one configiq source, found {len(rows)}")
    rev = rows[0]["revision"]
    ref, assets = str(rev["ref"]), [(a["name"], a["sha256"]) for a in rev["assets"]]
    if any(not isinstance(h, str) or len(h) != 64 for _, h in assets):
        raise NightError("a configiq asset hash in sources.yaml is not a 64-hex string")
    if len(ref) != 40 or not assets:
        raise NightError("the configiq pin is not a full revision with asset hashes")
    return ref, assets


def fetch(ref: str, assets, dest: Path, opener=urllib.request.urlopen) -> None:
    """Download each pinned file and check its sha256; a mismatch deletes the file and stops the run."""
    for name, want in assets:
        out = Path(dest) / name
        out.parent.mkdir(parents=True, exist_ok=True)
        with opener(URL.format(ref=ref, name=name)) as r:
            data = r.read()
        got = hashlib.sha256(data).hexdigest()
        if got != want:
            raise NightError(f"{name}: sha256 {got} is not the pinned {want}")
        out.write_bytes(data)


def _run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), file=sys.stderr)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    for k in ("substrate", "blis", "catalog", "registry", "fields", "substrate-version", "sim-build", "harness-commit", "out"):
        ap.add_argument(f"--{k}", required=True)
    ap.add_argument("--substrate-commit", default="", help="stack.json's commit for blis-substrate (resolve_stack.py)")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--published", help="a directory of published unit lists (fit.yaml, select.yaml, ...); default: the "
                    "substrate's catalog/ledger/published when it exists")
    a = ap.parse_args(argv)
    sub, out = Path(a.substrate), Path(a.out)
    led = sub / "catalog" / "ledger"
    out.mkdir(parents=True, exist_ok=True)
    try:
        release, bad = sk.pin_of(a.substrate_version, a.substrate_commit or None)
        if bad:
            raise NightError("blis-substrate is not an exact pin: " + "; ".join(bad))
        ref, assets = pins(led / "sources.yaml")
        data = out / "dataset"
        fetch(ref, assets, data)
        with (out / "rows.jsonl").open("w") as f:
            _run([sys.executable, "-I", sub / "ledger" / "configiq" / "export.py", data], stdout=f)
        score = out / "score"
        _run([sys.executable, ORCH / "ingest" / "score_configiq.py", "--ledger", led, "--rows", out / "rows.jsonl",
              "--data-dir", data, "--blis", a.blis, "--catalog", a.catalog, "--registry", a.registry, "--fields", a.fields,
              "--catalog-release", release, "--registry-release", release, "--sim-build", a.sim_build,
              "--harness-commit", a.harness_commit, "--ledger-yaml", led / "ledger.yaml", "--workers", a.workers,
              "--out", score])
        (out / "classes").mkdir(exist_ok=True)
        meta = out / "meta.json"
        prov = json.loads((score / "summary.json").read_text())["provenance"]
        meta.write_text(json.dumps({
            "command": "orchestrator/nightly/configiq_night.py: score_configiq.py over every configiq anchor unit, then "
                       "build_classes.py derive-configiq",
            "heads": {"blis": prov["blis"]["commit_sha"], "catalog": release, "registry": release,
                      "harness": a.harness_commit, "dataset": ref},
            "pulled_at": datetime.date.today().isoformat()}))
        _run([sys.executable, ORCH / "build_classes.py", "derive-configiq", score, "--id", "configiq",
              "--label", "Red Hat configiq (scored by simulation)", "--note", NOTE, "--meta", meta,
              "--withhold-figure", "ttft=first-token time awaits the team's definition",
              "--plain-line", "The remaining rows wait on dataset clarifications from the configiq team.",
              "--out", out / "classes" / "configiq.json"])
        cmd = [sys.executable, ORCH / "baseline" / "funnel.py", "--configiq-ledger", led,
               "--configiq-points", score / "configiq-points.jsonl", "--ledger-yaml", led / "ledger.yaml",
               "--out", out / "funnel.json"]
        published = a.published or (str(led / "published") if (led / "published").is_dir() else None)
        _run(cmd + (["--published", published] if published else []))
    except (NightError, src.SourcesError, OSError, subprocess.CalledProcessError, KeyError, ValueError) as e:
        print(f"configiq_night: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
