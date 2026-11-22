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
        # A module pinned by commit names a full commit (a pseudo-version carries twelve hex digits). A release
        # tag names none: the tag names the commit (LIF-1), so the commit is empty and `<key>_ref` is the tag.
        commit = m["commit"]
        if commit is None and release_name(m) is not None:
            out[key] = ""
            out[key.replace("_commit", "_ref")] = m["version"]
        elif re.fullmatch(r"[0-9a-f]{40}", commit or ""):
            out[key] = commit
            out[key.replace("_commit", "_ref")] = commit
        else:
            raise StackError(f"stack.json: module {path} has commit {commit!r}, want 40 hex digits "
                             f"(or, for a release, no commit and a release tag as its version)")
        if key == "substrate_commit":
            version = m["version"]
            if not isinstance(version, str) or not re.fullmatch(r"[0-9A-Za-z._+-]+", version):
                raise StackError(f"stack.json: module {path} has version {version!r}, want letters, digits and . _ + -")
            out["substrate_version"] = version
    out["vllm_ref"] = vllm_ref(stack)
    return out


def vllm_ref(stack: Stack) -> str:
    """What the engine release is measured from: the vLLM tag v<version>, or, when the version names a build after a release
    (<release>+<12 hex>, the form a stack takes while its engine is a commit), that engine's full commit."""
    version = stack.engine("vllm")
    if "+" in version:
        commit = stack.engines["vllm"].get("commit")
        if not re.fullmatch(r"[0-9a-f]{40}", commit or ""):
            raise StackError(f"stack.json: vllm engine {version} is a build after a release but names no 40-hex commit ({commit!r})")
        return commit
    return "v" + version


def embedded_pins(stack: Stack, sim_commit: str) -> dict:
    """What the nightly fetches to score a simulator COMMIT whose stack.json lists no blis-substrate or blis-vllm module: the
    substrate (catalog/, registry/, catalog/ledger) and the engine field lists are directories of the inference-sim tree itself
    (substrate/, engines/vllm/fields.json), so the one commit pins them all. The output carries `substrate_embedded=true`, which
    the workflow reads to take them from the checkout it already holds, not from a clone of another repository."""
    if not _COMMIT.match(sim_commit):
        raise StackError(f"{sim_commit!r} is not a full 40-hex commit")
    for path in (SUBSTRATE, VLLM_MODULE):
        if path in stack.modules:
            raise StackError(f"stack.json lists module {path}: its release is fetched from it, not from the checkout")
    return {"substrate_embedded": "true", "substrate_ref": sim_commit, "substrate_commit": sim_commit,
            "substrate_version": sim_commit, "vllm_ref": vllm_ref(stack)}


_RELEASE_NAME = re.compile(r"^v\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")
_PSEUDO = re.compile(r"(^|[.-])\d{14}-[0-9a-f]{12}$")


def release_name(module_entry: dict) -> str | None:
    """The release tag a module entry of stack.json names: its version when that is a tag (vX.Y.Z or vX.Y.Z-rc1), None when
    it is a Go pseudo-version (v0.0.0-<14-digit time>-<12 hex>), which names a commit and no tag."""
    version = module_entry.get("version")
    if not isinstance(version, str) or not _RELEASE_NAME.match(version) or _PSEUDO.search(version):
        return None
    return version


_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def pin_of(version: str | None, commit: str | None) -> tuple[str | None, list[str]]:
    """(pin, problems): the name an exact pin of a module goes by, and what is wrong when it has none (design X8).

    A tag pins by its name. A Go pseudo-version, or a version that is the commit itself, pins by the full 40-hex commit stack.json
    records beside it, and that commit must be the one the pseudo-version names (its 12 hex digits are a prefix of it). Anything
    else (no tag, no commit, a short hash, a pseudo-version that names another commit) is no pin and gets a problem."""
    if isinstance(version, str) and release_name({"version": version}) is not None:
        return version, []
    if not isinstance(commit, str) or not _COMMIT.match(commit):
        return None, [f"{version} is not a release tag and stack.json pins no full 40-hex commit for it ({commit!r})"]
    m = _PSEUDO.search(version) if isinstance(version, str) else None
    if m and not commit.startswith(m.group(0)[-12:]):
        return None, [f"{version} names the commit {m.group(0)[-12:]}..., but stack.json pins {commit}"]
    if not m and version != commit:
        return None, [f"{version} is neither a release tag, a pseudo-version nor the pinned commit {commit}"]
    return commit, []


def verify_checkout(repo: Path, pin: str, commit: str) -> list[str]:
    """What is wrong with a checkout that should be exactly `pin` (a release tag, or a full commit) at stack.json's `commit`; empty
    when nothing is. A tag must exist locally (clone without --depth so tags are fetched), HEAD must be the commit it resolves to,
    and that must be `commit` when stack.json states one. A commit pin is HEAD itself, and must equal `commit`."""
    def rev(ref):
        r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "-q", ref],
                           capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    head = rev("HEAD^{commit}")
    if head is None:
        return [f"{repo}: no HEAD commit"]
    if _COMMIT.match(pin):
        out = []
        if head != pin:
            out.append(f"{repo} is at {head}, but the pin is commit {pin}")
        if commit and commit != pin:
            out.append(f"the pin is commit {pin}, but stack.json pins {commit}")
        return out
    tagged = rev(f"refs/tags/{pin}^{{commit}}")
    if tagged is None:
        return [f"{repo}: tag {pin} does not exist"]
    out = []
    if head != tagged:
        out.append(f"{repo} is at {head}, but tag {pin} is commit {tagged}")
    if commit and tagged != commit:
        out.append(f"tag {pin} is commit {tagged}, but stack.json pins {commit}")
    return out


# ------------------------------------------------------------------ COV-9: each release once

_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def _version(tag: str) -> tuple[int, int, int]:
    m = _TAG.match(tag)
    if not m:
        raise StackError(f"{tag!r} is not a stable release tag vX.Y.Z")
    return tuple(int(x) for x in m.groups())


def is_stable_tag(tag: str) -> bool:
    """True for a stable release tag vX.Y.Z: the only builds the list of scored releases holds. A 40-hex commit is a recorded
    pre-release build (a preview run), never listed: the list is append-only, and a commit is not a release."""
    return _TAG.match(tag) is not None


# Releases that can never be scored, each with the patch release that scores its code in its
# place. The night scores a release's anchor units from the substrate its stack.json pins (COV-2),
# and these pin blis-substrate v0.13.0 and v0.14.0, which publish no anchor list. A tag names one
# commit forever (LIF-1), so only a patch release that repins the substrate can be scored. Such a
# release is skipped only once its patch release exists, and it is never recorded as scored.
SUPERSEDED = {"v0.16.0": "v0.17.1", "v0.17.0": "v0.17.1"}


def unscored_releases(tags_in_tag_order: list[str], scored: set[str], first: str,
                      superseded: dict[str, str] = SUPERSEDED) -> list[str]:
    """The releases a nightly run scores (COV-9): every stable release at or after `first`, in
    the order they were tagged, that has no scores yet. Each is scored exactly once, except a release in
    `superseded`, which is never scored: its replacement is scored in its place (CONTRACT.md). A tag that is
    not vX.Y.Z (a pre-release) is not a release to score. A release in `superseded` is left out once
    the release that replaces it is tagged. Empty when no such release exists yet."""
    floor = _version(first)
    tagged = set(tags_in_tag_order)
    return [t for t in tags_in_tag_order if _TAG.match(t) and _version(t) >= floor and t not in scored
            and superseded.get(t) not in tagged]


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
