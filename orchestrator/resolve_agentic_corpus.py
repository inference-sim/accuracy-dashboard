#!/usr/bin/env python3
"""Resolve an agentic corpus alias to its catalog workload and a checked local traces.jsonl.

`blis replay --agentic-scenario` needs `--corpus <traces.jsonl>` (a Weka v7 JSONL, one trace
per line), `--corpus-sha256 <hex>` and a workload that describes that corpus. The alias a run's
aiperf command loaded (`--public-dataset`, read by `extract_agentic_replay_args.py`) decides
which catalog replay workload the run is scored with (CATALOG_WORKLOADS):

    semianalysis_cc_traces_weka_062126        -> agentx-mvp-uncapped
    semianalysis_cc_traces_weka_062126_256k   -> agentx-mvp

The entry pins the corpus by Hugging Face revision and full sha256 (X12, D3). This helper
downloads the file at that revision, never at the dataset's moving `main`, and refuses it
unless its sha256 equals the entry's in full.

TEMPORARY until an inference-sim command prints a catalog workload entry: `blis catalog
resolve` takes only --model and --chip (inference-sim 2eff3576), so the entry is read from
the catalog checkout the scorer is given (`--catalog`), at workloads/<name>.yaml, the layout
blis-substrate's catalog/ has (design §3.3). lint_blis_boundary.py lists the site.

This is a LOCAL helper for the agentic path (run by hand, like fetch_agentic_rows.py); it is
not part of the automated pipeline.

Usage:
    python orchestrator/resolve_agentic_corpus.py --catalog $WORK/catalog \\
        --alias semianalysis_cc_traces_weka_062126 -o .work/agentic/corpus
    # -> writes <out>/traces.jsonl and prints the workload, its file, and the sha256
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from extract_agentic_replay_args import CATALOG_WORKLOADS, PINNED_CORPORA  # noqa: E402

HF_BASE = "https://huggingface.co/datasets"
_REVISION = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class CorpusError(SystemExit):
    """The alias, the catalog entry or the downloaded file does not pin one corpus."""


def workload_path(catalog: Path, name: str) -> Path:
    """The file of catalog replay workload `name`. TEMPORARY until a command prints it."""
    return Path(catalog, "workloads", f"{name}.yaml")


def catalog_entry(catalog: Path, alias: str) -> dict:
    """The catalog replay workload for a corpus alias: {"workload", "path", "repo", "revision",
    "file", "sha256"}. Refuses an alias that is not date-pinned, a missing entry, and an entry
    that names another corpus or pins it by anything but a 40-hex revision and a 64-hex sha256."""
    import yaml

    name = CATALOG_WORKLOADS.get(alias)
    if name is None:
        raise CorpusError(
            f"alias {alias!r} is not a known date-pinned corpus (known: {sorted(CATALOG_WORKLOADS)}). "
            f"A rolling alias does not identify a corpus and must not be resolved to a file.")
    path = workload_path(catalog, name)
    if not path.is_file():
        raise CorpusError(f"the catalog {catalog} has no workload {name!r} (looked for {path}); "
                          f"alias {alias!r} is scored only with that entry")
    doc = yaml.safe_load(path.read_text()) or {}
    corpus = ((doc.get("replay") or {}).get("corpus")) or {}
    source = corpus.get("source") or {}
    want = PINNED_CORPORA[alias]
    problems = []
    if corpus.get("loader") != alias:
        problems.append(f"loader {corpus.get('loader')!r}, not {alias!r}")
    if source.get("huggingface") != want:
        problems.append(f"huggingface {source.get('huggingface')!r}, not {want!r}")
    if not _REVISION.fullmatch(str(source.get("revision", ""))):
        problems.append(f"revision {source.get('revision')!r} is not a 40-hex commit (D3)")
    if not _SHA256.fullmatch(str(corpus.get("sha256", ""))):
        problems.append(f"sha256 {corpus.get('sha256')!r} is not a full 64-hex hash")
    if not source.get("file"):
        problems.append("no source file")
    if problems:
        raise CorpusError(f"{path}: the entry does not pin the corpus of {alias!r}: " + "; ".join(problems))
    return {"workload": name, "path": path, "repo": want, "revision": source["revision"],
            "file": source["file"], "sha256": corpus["sha256"]}


def dataset_url(repo: str, revision: str, filename: str) -> str:
    """The public resolve URL of a file in a Hugging Face dataset at a pinned revision."""
    if not _REVISION.fullmatch(revision):
        raise CorpusError(f"revision {revision!r} is not a 40-hex commit; a moving ref such as "
                          f"main does not pin the corpus (D3)")
    return f"{HF_BASE}/{repo}/resolve/{revision}/{filename}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path) -> None:
    # Identity encoding, and the bytes written exactly as served: this file's sha256 is what
    # `blis replay --corpus-sha256` verifies. Streamed, because the uncapped file is 1.8 GB.
    req = urllib.request.Request(url, headers={"Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=600) as resp, open(dest, "wb") as fh:  # noqa: S310 (fixed host)
        shutil.copyfileobj(resp, fh, 1 << 20)


def check(path: Path, entry: dict) -> str:
    """The file's sha256, which must equal the entry's in full."""
    digest = sha256_file(path)
    if digest != entry["sha256"]:
        raise CorpusError(f"corpus sha256 mismatch for {entry['repo']}@{entry['revision']}: {path} is "
                          f"{digest}, the catalog workload {entry['workload']} pins {entry['sha256']}. "
                          f"Refusing a corpus that is not the pinned one.")
    return digest


def resolve(alias: str, catalog: Path, out_dir: Path, download=_download) -> tuple[dict, Path]:
    """Download the alias's corpus at the entry's revision into out_dir and check it.
    Returns (entry, path). A file that fails the check is removed, never left as traces.jsonl."""
    entry = catalog_entry(catalog, alias)
    url = dataset_url(entry["repo"], entry["revision"], entry["file"])
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / entry["file"]
    part = dest.with_name(dest.name + ".part")
    print(f"downloading {url} -> {dest}", file=sys.stderr)
    download(url, part)
    try:
        check(part, entry)
    except CorpusError:
        part.unlink(missing_ok=True)
        raise
    part.replace(dest)
    return entry, dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--alias", required=True,
                    help="the corpus alias the run's aiperf command loaded (--public-dataset)")
    ap.add_argument("--catalog", required=True, help="the catalog checkout the scorer is given")
    ap.add_argument("-o", "--out", required=True, help="output directory for the corpus file")
    args = ap.parse_args()

    entry, dest = resolve(args.alias, Path(args.catalog), Path(args.out))
    print(f"workload:      {entry['workload']} ({entry['path']})")
    print(f"corpus:        {dest}")
    print(f"corpus-sha256: {entry['sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
