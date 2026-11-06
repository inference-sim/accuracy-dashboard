"""What one simulator build runs, from its stack.json (design SIM-3, LIF-6; X8).

Each inference-sim release lists in stack.json the exact version of every BLIS module it was
built with and the one upstream release of each engine it runs. The scorer reads the engine
release from here (engine.version, design §11.2). It never parses installation.md's
"Compatible blis-catalog release" lines.

The reader is strict (SUB-12): unknown keys are refused.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_STACK_KEYS = {"kind", "toolchain", "modules", "engines", "router", "guides_commit"}
_MODULE_KEYS = {"path", "version", "commit", "replaces"}
_UPSTREAM_KEYS = {"kind", "version", "commit"}


class StackError(ValueError):
    pass


@dataclass(frozen=True)
class Stack:
    engines: dict          # kind -> {"version", "commit"}
    modules: dict          # path -> {"version", "commit"}
    router: dict
    toolchain: str

    def engine(self, kind: str) -> str:
        e = self.engines.get(kind)
        if e is None:
            raise StackError(f"stack.json lists no {kind!r} engine; it runs {sorted(self.engines)}")
        return e["version"]


def _keys(obj, allowed, where):
    if not isinstance(obj, dict):
        raise StackError(f"{where}: not an object")
    extra = sorted(set(obj) - allowed)
    if extra:
        raise StackError(f"{where}: unknown key {extra[0]!r}")
    return obj


def parse(text: str) -> Stack:
    doc = _keys(json.loads(text), _STACK_KEYS, "stack.json")
    if doc.get("kind") != "Stack":
        raise StackError(f"stack.json kind {doc.get('kind')!r}, want 'Stack'")
    engines = {}
    for i, e in enumerate(doc.get("engines") or []):
        _keys(e, _UPSTREAM_KEYS, f"engines[{i}]")
        if e.get("kind") in engines:
            raise StackError(f"engines[{i}]: a second {e['kind']!r} engine; each release runs one (LIF-6)")
        engines[e["kind"]] = {"version": e["version"], "commit": e.get("commit")}
    modules = {}
    for i, m in enumerate(doc.get("modules") or []):
        _keys(m, _MODULE_KEYS, f"modules[{i}]")
        modules[m["path"]] = {"version": m["version"], "commit": m.get("commit")}
    return Stack(engines=engines, modules=modules, router=_keys(doc.get("router") or {}, _UPSTREAM_KEYS, "router"),
                 toolchain=doc.get("toolchain", ""))


def load(path) -> Stack:
    return parse(Path(path).read_text())


SUBSTRATE = "github.com/inference-sim/blis-substrate"
VLLM_MODULE = "github.com/inference-sim/blis-vllm"


def pins(stack: Stack) -> dict:
    """What the nightly fetches to score one release, all from its stack.json (design §11, X8):
    the commits of the blis-substrate module (whose catalog/, registry/ and catalog/ledger the
    release runs) and of the blis-vllm module (whose root holds fields.json), and the vLLM tag the
    engine release names. A release scored later needs no change here."""
    out = {}
    for key, path in (("substrate_commit", SUBSTRATE), ("vllm_module_commit", VLLM_MODULE)):
        m = stack.modules.get(path)
        if m is None:
            raise StackError(f"stack.json lists no module {path}")
        if not re.fullmatch(r"[0-9a-f]{40}", m["commit"] or ""):
            raise StackError(f"stack.json: module {path} has commit {m['commit']!r}, want 40 hex digits")
        out[key] = m["commit"]
        if key == "substrate_commit":
            version = m["version"]
            if not isinstance(version, str) or not re.fullmatch(r"[0-9A-Za-z._+-]+", version):
                raise StackError(f"stack.json: module {path} has version {version!r}, want letters, digits and . _ + -")
            out["substrate_version"] = version
    out["vllm_ref"] = "v" + stack.engine("vllm")
    return out


_RELEASE_NAME = re.compile(r"^v\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")
_PSEUDO = re.compile(r"(^|[.-])\d{14}-[0-9a-f]{12}$")


def release_name(module_entry: dict) -> str | None:
    """The release a module entry of stack.json names: its version when that is a release tag
    (vX.Y.Z or vX.Y.Z-rc1), None when it is a Go pseudo-version (v0.0.0-<14-digit time>-<12 hex>),
    which a draft build carries and no release does (X8)."""
    version = module_entry.get("version")
    if not isinstance(version, str) or not _RELEASE_NAME.match(version) or _PSEUDO.search(version):
        return None
    return version


def verify_checkout(repo: Path, tag: str, commit: str) -> list[str]:
    """What is wrong with a checkout that should be release `tag` at stack.json's `commit`; empty
    when nothing is. Its HEAD must be the commit the tag resolves to in the repository, and that
    must be `commit`. The tag must exist locally (clone without --depth so tags are fetched)."""
    def rev(ref):
        r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "-q", ref],
                           capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    head, tagged = rev("HEAD^{commit}"), rev(f"refs/tags/{tag}^{{commit}}")
    if head is None:
        return [f"{repo}: no HEAD commit"]
    if tagged is None:
        return [f"{repo}: tag {tag} does not exist"]
    out = []
    if head != tagged:
        out.append(f"{repo} is at {head}, but tag {tag} is commit {tagged}")
    if tagged != commit:
        out.append(f"tag {tag} is commit {tagged}, but stack.json pins {commit}")
    return out


# ------------------------------------------------------------------ COV-9: each release once

_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def _version(tag: str) -> tuple[int, int, int]:
    m = _TAG.match(tag)
    if not m:
        raise StackError(f"{tag!r} is not a stable release tag vX.Y.Z")
    return tuple(int(x) for x in m.groups())


def unscored_releases(tags_in_tag_order: list[str], scored: set[str], first: str) -> list[str]:
    """The releases a nightly run scores (COV-9): every stable release at or after `first`, in
    the order they were tagged, that has no scores yet. Each is scored exactly once. A tag that is
    not vX.Y.Z (a pre-release) is not a release to score. Empty when no such release exists yet."""
    floor = _version(first)
    return [t for t in tags_in_tag_order if _TAG.match(t) and _version(t) >= floor and t not in scored]


SCORED_KIND = "ScoredReleases"


def read_scored(path) -> list[str]:
    """The simulator releases whose scores are published (state/scored-releases.json), in the
    order they were recorded. A missing or malformed file is an error: an empty list would make
    the night score every release again (COV-9)."""
    try:
        doc = json.loads(Path(path).read_text())
    except OSError as e:
        raise StackError(f"{path}: {e.strerror or e}") from e
    except json.JSONDecodeError as e:
        raise StackError(f"{path}: not JSON: {e}") from e
    if not isinstance(doc, dict) or set(doc) != {"kind", "releases"} or doc["kind"] != SCORED_KIND:
        raise StackError(f"{path}: want an object with exactly kind {SCORED_KIND!r} and releases")
    rel = doc["releases"]
    if not isinstance(rel, list) or any(not isinstance(t, str) or not _TAG.match(t) for t in rel):
        raise StackError(f"{path}: releases must be a list of stable release tags vX.Y.Z")
    if len(set(rel)) != len(rel):
        raise StackError(f"{path}: a release is listed twice; each is scored once (COV-9)")
    return rel


def record_scored(path, tag: str) -> bool:
    """Append `tag` to the list of releases whose scores are published, once: False, with the file
    untouched, when it is already there. The list is append-only and independent of the snapshots
    on disk, so pruning old snapshots (update_index.py) never makes a release look unscored. The
    previous release's scores stay published (design §11.5)."""
    _version(tag)
    rel = read_scored(path)
    if tag in rel:
        return False
    Path(path).write_text(json.dumps({"kind": SCORED_KIND, "releases": rel + [tag]}, indent=2) + "\n")
    return True


# The first simulator release scored on graded points and stack.json: every stable release from
# it on is scored once (COV-9); the ones before keep their published snapshots.
FIRST_GRADED_RELEASE = "v0.16.0"


def main(argv=None) -> int:
    """Print, one per line in tag order, the simulator releases a night scores (COV-9): every
    stable release from FIRST_GRADED_RELEASE on that state/scored-releases.json does not list.

        python3 orchestrator/ingest/stack.py --tags TAGS --scored state/scored-releases.json
    """
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("--tags", required=True, help="inference-sim tags, one per line, in the order they were tagged")
    ap.add_argument("--scored", required=True, help="state/scored-releases.json: the releases with published scores")
    a = ap.parse_args(argv)
    tags = [t.strip() for t in Path(a.tags).read_text().splitlines() if t.strip()]
    try:
        scored = set(read_scored(a.scored))
    except StackError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1
    for t in unscored_releases(tags, scored, FIRST_GRADED_RELEASE):
        print(t)
    return 0


if __name__ == "__main__":
    sys.exit(main())
