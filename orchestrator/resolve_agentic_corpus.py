#!/usr/bin/env python3
"""Resolve an agentic corpus alias to a local traces.jsonl and its sha256.

`blis replay --agentic-scenario` needs `--corpus <traces.jsonl>` (a Weka v7 JSONL, one
trace per line) and `--corpus-sha256 <hex>`; the replay refuses a corpus whose hash does
not match, so the pair is what pins the exact input. `extract_agentic_replay_args.py`
reads the corpus ALIAS a row's benchmark used (e.g. `semianalysis_cc_traces_weka_062126`)
but deliberately leaves resolving it to a file to the caller -- this is that caller.

It reuses PR #19's `PINNED_CORPORA` (alias -> HuggingFace dataset repo) rather than keeping
a second copy, so only date-pinned aliases resolve; a rolling alias is refused upstream.
The dataset's `traces.jsonl` is downloaded (public, no auth), its sha256 computed, and -- if
an expected hash is known -- checked, failing loud on a mismatch rather than scoring against
the wrong corpus.

This is a LOCAL helper for the agentic path (run by hand, like fetch_agentic_rows.py); it
is not part of the automated pipeline.

Usage:
    python orchestrator/resolve_agentic_corpus.py \
        --alias semianalysis_cc_traces_weka_062126 -o .work/agentic/corpus
    # -> writes <out>/traces.jsonl and prints its sha256
"""

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from extract_agentic_replay_args import PINNED_CORPORA  # noqa: E402

# The corpus file inside each pinned HuggingFace dataset, and the sha256 it must have.
# Recorded here so a download is checked against a known-good hash rather than trusted.
# cc-traces-weka-062126's traces.jsonl is 29b6a19e751f… (recorded in PR #19).
CORPUS_FILE = "traces.jsonl"
EXPECTED_SHA256 = {
    "semianalysisai/cc-traces-weka-062126":
        "29b6a19e751f",  # prefix; full hash verified on first real download (see --expect)
}

HF_BASE = "https://huggingface.co/datasets"


def dataset_url(repo: str, filename: str) -> str:
    """The public resolve URL for a file in a HuggingFace dataset's main revision."""
    return f"{HF_BASE}/{repo}/resolve/main/{filename}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve(alias: str, out_dir: Path, expect: str | None) -> tuple[Path, str]:
    """Download the alias's traces.jsonl into out_dir; return (path, sha256).

    Refuses an alias that is not a known date-pinned one (same rule as PR #19), and fails
    loud if a stated expected hash does not match what was downloaded.
    """
    repo = PINNED_CORPORA.get(alias)
    if repo is None:
        raise SystemExit(
            f"alias {alias!r} is not a known date-pinned corpus "
            f"(known: {sorted(PINNED_CORPORA)}). A rolling alias does not identify a "
            f"corpus and must not be resolved to an arbitrary file.")
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / CORPUS_FILE
    url = dataset_url(repo, CORPUS_FILE)
    print(f"downloading {url} -> {dest}", file=sys.stderr)
    # Identity encoding, and write the bytes EXACTLY as served: this file's sha256 is what
    # `blis replay --corpus-sha256` verifies, so it must hash the raw file. (Unlike the JSON
    # API, HuggingFace serves the dataset file uncompressed; forcing identity makes that
    # explicit so a transfer-encoding change upstream can never silently alter the hash.)
    req = urllib.request.Request(url, headers={"Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=600) as resp:  # noqa: S310 (fixed host)
        dest.write_bytes(resp.read())
    digest = sha256_file(dest)

    want = expect or EXPECTED_SHA256.get(repo)
    if want and not digest.startswith(want) and digest != want:
        raise SystemExit(
            f"corpus sha256 mismatch for {repo}: downloaded {digest}, expected {want!r}. "
            f"Refusing to use a corpus that does not match the pinned hash.")
    return dest, digest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--alias", required=True,
                    help="the corpus alias a benchmark used, e.g. "
                         "semianalysis_cc_traces_weka_062126")
    ap.add_argument("-o", "--out", required=True, help="output directory for traces.jsonl")
    ap.add_argument("--expect", default=None,
                    help="an expected sha256 (or prefix) to check the download against")
    args = ap.parse_args()

    dest, digest = resolve(args.alias, Path(args.out), args.expect)
    print(f"corpus:        {dest}")
    print(f"corpus-sha256: {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
