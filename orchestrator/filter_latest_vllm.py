#!/usr/bin/env python3
"""Filter the direct-extractor corpus to the vLLM versions worth scoring, BEFORE the gen_direct_*
scripts and signedprobe run (RFC discussion #2, point 2 — replaces the on-target-v0.31.0 rule).

Two reductions, both applied to inferencex_direct.json (the superset every gen_direct_* reads, and
the only file still carrying the container `image` → the real vLLM version):

  1. latest-N relevance filter — keep only sweeps whose vLLM version is one of the N newest NUMBERED
     versions PRESENT IN THIS DUMP (the window moves with each dump). Unnumbered/custom builds
     (nightly-*, model-specific tags like deepseekv4-cu130) are excluded — they have no comparable
     version ordering. For the 2026-09-28 dump, N=5 → 0.25.1 … 0.21.0.

  2. dedup-to-latest — BLIS's prediction does NOT depend on the vLLM version (verified: identical
     `pred` across every vLLM build at a given concurrency). So for each distinct BLIS-input identity
     (model, gpu, precision, serving, spec_method, parallelism, stated_config, workload) we keep only
     the sweep measured on the NEWEST surviving vLLM version. The BLIS number is thus reported ONCE
     per target, against the latest version's measurement — no redundant replays, no expand step.

This is glue, not scoring: it only selects which sweeps to pass downstream. signedprobe and
build_summary are unchanged and simply see a smaller corpus. Fail-loud: prints the before/after
counts and the chosen version window to stderr (RFC D4).

The vLLM version is parsed with build_summary._parse_vllm_version so the filter and the UI labels
can never disagree.
"""
from __future__ import annotations

import argparse
import json
import sys

from build_summary import _parse_vllm_version

DEFAULT_N = 5


def _is_numbered(version: str | None) -> bool:
    """A version is 'numbered' iff _parse_vllm_version returned a dotted numeric (e.g. '0.25.1',
    '0.21'). 'nightly' and custom build tags (e.g. 'deepseekv4-cu130') are not numbered."""
    if not version:
        return False
    parts = version.split(".")
    return 2 <= len(parts) <= 3 and all(p.isdigit() for p in parts)


def _version_key(version: str) -> tuple[int, ...]:
    """Sort key for a numbered version. '0.25.1' -> (0,25,1); '0.21' -> (0,21)."""
    return tuple(int(p) for p in version.split("."))


def _identity(sw: dict) -> str:
    """Canonical BLIS-input identity for a sweep — everything that drives the prediction EXCEPT the
    vLLM version/image. Two sweeps with the same identity get the same BLIS number, so only the
    newest-vLLM one is kept."""
    # stated_config.model is a LOAD PATH / alias (e.g. 'nvidia/MiniMax-M2.5-NVFP4' vs
    # '/scratch/models/MiniMax-M2.5-NVFP4') — the same model fetched from a different location. It
    # never changes BLIS's latency physics (verified: such pairs produce byte-identical predictions),
    # so it must NOT make two sweeps count as distinct deployments. Drop it from the identity; the
    # real model identity is the top-level sw["model"]. All other stated_config fields (block_size,
    # prefix_caching, expert_parallel, speculative_*, gpu_memory_utilization) are kept.
    stated = {k: v for k, v in (sw.get("stated_config") or {}).items() if k != "model"}
    return json.dumps(
        {
            "model": sw.get("model"),
            "gpu": sw.get("gpu"),
            "precision": sw.get("precision"),
            "serving": sw.get("serving"),
            "spec_method": sw.get("spec_method"),
            "framework": sw.get("framework"),
            "workload": sw.get("workload"),
            "parallelism": sw.get("parallelism"),
            "stated_config": stated,
        },
        sort_keys=True,
    )


def _image_of(sw: dict) -> str | None:
    img = sw.get("image")
    if isinstance(img, list):
        img = img[0] if img else None
    return img


def filter_sweeps(sweeps: list[dict], n: int) -> tuple[list[dict], dict]:
    """Return (kept_sweeps, report). Pure — no I/O — so it is unit-testable."""
    # Parse each sweep's version once.
    parsed = [(sw, _parse_vllm_version(_image_of(sw))) for sw in sweeps]

    # 1. The latest-N numbered-version window present in THIS dump.
    numbered = sorted({v for _, v in parsed if _is_numbered(v)}, key=_version_key, reverse=True)
    window = set(numbered[:n])

    stage1 = [(sw, v) for sw, v in parsed if v in window]

    # 2. Dedup to the newest surviving version per BLIS identity.
    best: dict[str, tuple[dict, str]] = {}
    for sw, v in stage1:
        ident = _identity(sw)
        cur = best.get(ident)
        if cur is None or _version_key(v) > _version_key(cur[1]):
            best[ident] = (sw, v)
    kept = [sw for sw, _ in best.values()]

    report = {
        "n": n,
        "sweeps_in": len(sweeps),
        "numbered_versions_present": numbered,
        "window_kept": sorted(window, key=_version_key, reverse=True),
        "excluded_unnumbered": sorted({v for _, v in parsed if v and not _is_numbered(v)}),
        "sweeps_after_window": len(stage1),
        "sweeps_after_dedup": len(kept),
    }
    return kept, report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="inp", required=True, help="inferencex_direct.json (superset)")
    ap.add_argument("--out", required=True, help="filtered inferencex_direct.json")
    ap.add_argument("-n", "--latest", type=int, default=DEFAULT_N,
                    help=f"keep the latest N numbered vLLM versions (default {DEFAULT_N})")
    args = ap.parse_args()

    with open(args.inp) as fh:
        doc = json.load(fh)
    sweeps = doc.get("sweeps", [])
    if not sweeps:
        print("[filter-vllm] FATAL: input has no sweeps — nothing to filter", file=sys.stderr)
        return 2

    kept, rep = filter_sweeps(sweeps, args.latest)
    if not kept:
        print(f"[filter-vllm] FATAL: no sweeps survived (N={rep['n']}, numbered present="
              f"{rep['numbered_versions_present']}) — refusing to emit an empty corpus", file=sys.stderr)
        return 3

    doc["sweeps"] = kept
    # Record the selection in the doc so provenance downstream can see what was applied.
    doc["vllm_filter"] = rep
    with open(args.out, "w") as fh:
        json.dump(doc, fh, indent=1)

    npts_in = sum(len(s.get("points", [])) for s in sweeps)
    npts_out = sum(len(s.get("points", [])) for s in kept)
    print(f"[filter-vllm] latest-{rep['n']} window: {rep['window_kept']}", file=sys.stderr)
    print(f"[filter-vllm] excluded unnumbered builds: {rep['excluded_unnumbered']}", file=sys.stderr)
    print(f"[filter-vllm] sweeps {rep['sweeps_in']} → window {rep['sweeps_after_window']} "
          f"→ dedup {rep['sweeps_after_dedup']}; points {npts_in} → {npts_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
