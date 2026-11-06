"""The harness image a gate runs, named by the digest in harness/image.pin (design §11.7, X8).

The pin file holds one line: the image reference by digest,
`ghcr.io/inference-sim/accuracy-dashboard-harness@sha256:<64 hex>`, or the word `unpublished`
while no image has been released. A gate that does not run is a failure (X16): `unpublished`
and every line that is not such a reference raise PinError, and the caller stops. Nothing falls
back to running the scorer from the source tree.

    python3 harness_pin.py check FILE      print the reference, or the reason on standard error
                                           and exit 1
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

IMAGE = "ghcr.io/inference-sim/accuracy-dashboard-harness"
UNPUBLISHED = "unpublished"
_REFERENCE = re.compile(re.escape(IMAGE) + r"@(sha256:[0-9a-f]{64})")

# Container paths of the mounted data. The units file and the catalog and registry are read-only.
MOUNT = "/data"


class PinError(RuntimeError):
    """The pin file does not name a harness image that can run."""


def read(path) -> str:
    """The image reference in the pin file."""
    lines = [ln.strip() for ln in Path(path).read_text().splitlines() if ln.strip()]
    if len(lines) != 1:
        raise PinError(f"{path}: want one line, the image reference by digest or `{UNPUBLISHED}`; found {len(lines)}")
    line = lines[0]
    if line == UNPUBLISHED:
        raise PinError(f"{path} says {UNPUBLISHED}: no harness image has been released, so the scoring gate "
                       f"cannot run. It is not run from the source tree (X16). Release the image "
                       f"(harness-release.yml) and pin its digest")
    if not _REFERENCE.fullmatch(line):
        raise PinError(f"{path}: {line!r} is not {IMAGE}@sha256:<64 hex>")
    return line


def digest(reference: str) -> str:
    """The sha256:<64 hex> digest of a reference `read` returned."""
    m = _REFERENCE.fullmatch(reference)
    if not m:
        raise PinError(f"{reference!r} is not {IMAGE}@sha256:<64 hex>")
    return m.group(1)


def docker_command(reference: str, *, sim: str, units, pull, out, catalog, registry,
                   corpus_dir, catalog_release: str, registry_release: str, max_rss_mb: int = 0) -> list[str]:
    """The `docker run` that scores through the image, with harness/run.sh's flags. The data is
    mounted under /data, and HARNESS_DIGEST is the pin's digest, so the figures record the image
    that produced them. The mounted data carries no git history, so the releases it is at are
    passed by name (`catalog_release`, `registry_release`, the substrate release stack.json names)."""
    d = digest(reference)
    cmd = ["docker", "run", "--rm", "-e", f"HARNESS_DIGEST={d}",
           "-v", f"{Path(units).resolve()}:{MOUNT}/units.json:ro",
           "-v", f"{Path(pull).resolve()}:{MOUNT}/pull:ro",
           "-v", f"{Path(out).resolve()}:{MOUNT}/out",
           "-v", f"{Path(catalog).resolve()}:{MOUNT}/catalog:ro",
           "-v", f"{Path(registry).resolve()}:{MOUNT}/registry:ro",
           "-v", f"{Path(corpus_dir).resolve()}:{MOUNT}/corpora:ro"]
    cmd += [reference, "--sim", sim, "--units", f"{MOUNT}/units.json", "--pull", f"{MOUNT}/pull",
            "--out", f"{MOUNT}/out", "--catalog", f"{MOUNT}/catalog", "--registry", f"{MOUNT}/registry",
            "--corpus-dir", f"{MOUNT}/corpora",
            "--catalog-release", catalog_release, "--registry-release", registry_release]
    if max_rss_mb:
        cmd += ["--max-rss-mb", str(max_rss_mb)]
    return cmd


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "check":
        print(__doc__, file=sys.stderr)
        return 2
    try:
        print(read(argv[1]))
    except (PinError, OSError) as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
