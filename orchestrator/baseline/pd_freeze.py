#!/usr/bin/env python3
"""Freeze the paired prefill/decode points into a pull of their own (the P/D half of the matched comparison, #88).

    pd_freeze.py --pairs PAIRS.json --dump-rows ROWS.jsonl --ledger LEDGER --git-dir INFERENCEX.git
                 --vllm-git-dir VLLM.git --rest-cache DIR
                 --out PULL --cache CACHE --units-out UNITS.txt --errors-out ERRORS.json [--min-core 1000]

PAIRS.json is pd_pairing.py's output. Each pair's record is mapped to its ledger unit; the units are written to
UNITS.txt and frozen through the harness's own pull (matched.freeze), with the run's recipes read from a clone of the
InferenceX repository (GitRecipes) and the vLLM build placed on a vLLM clone (pd_net.GitCompare), every remaining
REST answer cached on disk and paced (pd_net.install_cache), so no tree, blob or compare read goes to the API and a
rerun resumes (PROCESS section 16). The pull stops, before it
starts, when `gh api rate_limit` shows the shared token's core quota below --min-core.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ingest"))


class FreezeError(RuntimeError):
    pass


def units_of_pairs(pairs: list[dict], by_record: dict) -> list[dict]:
    """Each pair with its ledger unit (`unit`), or why it has none (`why`: no_unit, several_units)."""
    out = []
    for p in pairs:
        units = sorted({by_record[r].unit.unit_id for r in p["records"] if r in by_record})
        e = {"records": list(p["records"]), "unit": units[0] if len(units) == 1 else None}
        if not units:
            e["why"] = "no_unit"
        elif len(units) > 1:
            e["why"] = "several_units"
        out.append(e)
    return out


def core_remaining() -> int:
    r = subprocess.run(["gh", "api", "rate_limit", "--jq", ".resources.core.remaining"], capture_output=True, text=True)
    if r.returncode != 0:
        raise FreezeError(f"cannot read the REST quota: {r.stderr.strip()[:200]}")
    return int(r.stdout.strip())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for k in ("pairs", "dump-rows", "ledger", "git-dir", "out", "cache", "units-out", "errors-out"):
        ap.add_argument(f"--{k}", required=True, type=Path)
    ap.add_argument("--vllm-git-dir", required=True, type=Path, help="a clone of vllm-project/vllm (build placement)")
    ap.add_argument("--rest-cache", required=True, type=Path, help="the disk cache of every REST answer")
    ap.add_argument("--min-core", type=int, default=1000)
    ap.add_argument("--min-interval", type=float, default=2.4, help="seconds between uncached REST calls (1,500 an hour)")
    ap.add_argument("--download-workers", type=int, default=2)
    a = ap.parse_args(argv)
    left = core_remaining()
    if left < a.min_core:
        raise FreezeError(f"core quota {left} is below {a.min_core}: not starting (PROCESS section 16)")
    import build
    import clients
    import ledger as ldg
    import matched as mt
    from pd_net import GitCompare, install_cache
    import recipes as rcp
    from git_recipes import GitRecipes
    lg = ldg.load(a.ledger)
    pairs = json.loads(a.pairs.read_text())["points"]
    matched = units_of_pairs(pairs, lg.by_record)
    units = sorted({e["unit"] for e in matched if e["unit"]})
    a.units_out.write_text("\n".join(units) + "\n")
    rows = [json.loads(line) for line in a.dump_rows.read_text().splitlines() if line.strip()]
    counts = install_cache(clients, a.rest_cache, min_interval=a.min_interval, min_core=a.min_core,
                           core_remaining=core_remaining)
    real, real_resolver = rcp.GitHubRecipes, build.Resolver
    rcp.GitHubRecipes = lambda get, repo: GitRecipes(get, repo, a.git_dir)
    build.Resolver = lambda **kw: real_resolver(**{**kw, "github": GitCompare({build.VLLM_REPO: a.vllm_git_dir})})
    try:
        rc = mt.freeze(matched, rows, ledger_dir=a.ledger, out=a.out, cache=a.cache, workers=a.download_workers,
                       errors_out=a.errors_out)
    finally:
        rcp.GitHubRecipes, build.Resolver = real, real_resolver
    print(json.dumps({"units": len(units), "pairs": len(pairs), "core_before": left, "core_after": core_remaining(), "rest_calls": counts["rest"],
                      "cache_hits": counts["hits"],
                      "rc": rc}))
    return rc


if __name__ == "__main__":
    sys.exit(main())
