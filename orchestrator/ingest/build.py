"""Which vLLM build measured a point, and whether it's the build BLIS models (Discussion #28).

A build never stops a point from being scored. It decides whether the point is exact or
estimated: `match` is "exact" only for an official image whose commit is on vLLM's mainline
within VLLM_MAX_DISTANCE of VLLM_REF's branch point. Anything else is "estimated", with `why`:
custom_build, outside_distance, commit_unresolvable or commit_conflict.

Per point, in order:

  1. Official-image gate: the image repository is vllm/vllm-openai or vllm/vllm-openai-rocm.
  2. Build commit, from the first source that yields a commit in vllm-project/vllm:
       a. the image's OCI label org.opencontainers.image.revision (by digest when the row pins
          one, else by tag, which is recorded as label_by_tag);
       b. the +g<sha> in the vLLM server log's version banner;
       c. a SHA embedded in the image tag;
       d. a release image (tag vX.Y.Z): the commit vLLM's own vX.Y.Z git tag names, when the
          server log's banner (if any) prints that same version.
     A label of "unknown" (vLLM's local/dev builds) doesn't count. Sources that name different
     commits are a conflict. A banner with a build-tree suffix (.d<YYYYMMDD>) is fine as long as
     its SHA agrees.
  3. The commit is on vLLM's mainline: reachable from main or from a release tag.
  4. Distance along main from VLLM_REF's branch point; within VLLM_MAX_DISTANCE is exact.

Network access goes through two injected clients (Registry, GitHub) so the logic is testable
with fakes and the results can be cached and frozen per point. Nothing here is used by the
nightly pipeline.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Protocol

VLLM_REF = "v0.32.0"
VLLM_MAX_DISTANCE = 2000
VLLM_REPO = "vllm-project/vllm"
OFFICIAL_IMAGES = ("vllm/vllm-openai", "vllm/vllm-openai-rocm")

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
# vLLM's engine banner, e.g. "V1 LLM engine (v0.30.1rc1.dev493+gac9126e58)" or with a build-tree
# suffix "…+g49cb2bbf7.d20261016". Anchored on vLLM's own engine line: other banners in a server
# log (a dependency's, CUDA's) carry versions too.
_BANNER = re.compile(r"V1 LLM engine \(v[0-9][0-9A-Za-z.]*\+g([0-9a-f]{7,40})(\.d\d{8})?\)")
# A hex run of 7-40 chars at the end of the tag, after "-" or the start: nightly-<sha>,
# nightly-dev-x86_64-cu130-<shortsha>, nightly-rocm100-<sha>.
_TAG_SHA = re.compile(r"(?:^|-)([0-9a-f]{7,40})$")
# A release image's tag: vX.Y.Z, with no build suffix.
_RELEASE_TAG = re.compile(r"^v\d+\.\d+\.\d+$")
# The version vLLM's engine banner prints, e.g. "V1 LLM engine (v0.22.0)" for a release.
_BANNER_VERSION = re.compile(r"V1 LLM engine \((v[0-9][0-9A-Za-z.+]*)\)")


class Registry(Protocol):
    def revision_label(self, repository: str, reference: str) -> str | None:
        """org.opencontainers.image.revision of an image (reference: tag or sha256:<digest>),
        or None when the manifest or label doesn't exist."""


class GitHub(Protocol):
    def resolve_commit(self, repo: str, sha_prefix: str) -> str | None:
        """The full SHA a (possibly short) SHA names in repo, or None if it isn't a commit there."""

    def compare(self, repo: str, base: str, head: str) -> tuple[str, int, int]:
        """(status, ahead_by, behind_by) of head relative to base; status is one of ahead,
        behind, identical, diverged."""

    def merge_base(self, repo: str, a: str, b: str) -> str:
        """The merge base of two refs."""

    def is_on_release_tag(self, repo: str, sha: str) -> bool:
        """Whether sha is reachable from some vX.Y.Z release tag."""

    def tag_commit(self, repo: str, tag: str) -> str | None:
        """The commit a vX.Y.Z release tag names, or None."""


@dataclass(frozen=True)
class Image:
    repository: str
    tag: str | None
    digest: str | None

    @property
    def reference(self) -> str:
        return self.digest or self.tag or ""


def parse_image(image: str | None) -> Image | None:
    """'vllm/vllm-openai:nightly-…@sha256:…' -> Image; None for an empty or tagless reference."""
    if not image:
        return None
    rest, _, digest = image.partition("@")
    digest = digest or None
    if digest and not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        return None
    repo, sep, tag = rest.rpartition(":")
    if not sep or "/" in tag:
        repo, tag = rest, None
    return Image(repository=repo, tag=tag or None, digest=digest)


# What a server log's engine banners say about the build.
BANNER_NONE = "none"            # no vLLM engine banner
BANNER_CONFLICT = "conflict"    # ranks name different commits


def banner_sha(server_log: str | None) -> tuple[str, str | None, bool]:
    """(status, sha, dirty) from vLLM's engine banner(s).

    status is "ok", BANNER_NONE, or BANNER_CONFLICT (DP ranks print one banner each, and they
    must agree). dirty is True when the banner carries a build-tree suffix (.d<YYYYMMDD>): a
    local build of that commit, which counts only when the image's own label confirms it.
    """
    if not server_log:
        return BANNER_NONE, None, False
    found = set(_BANNER.findall(server_log))
    if not found:
        return BANNER_NONE, None, False
    shas = {sha for sha, _ in found}
    if len(shas) > 1:
        return BANNER_CONFLICT, None, False
    return "ok", shas.pop(), any(suffix for _, suffix in found)


def tag_sha(tag: str | None) -> str | None:
    """A commit SHA embedded at the end of an image tag, or None."""
    if not tag:
        return None
    m = _TAG_SHA.search(tag)
    return m.group(1) if m else None


# Why a build is estimated rather than exact (fidelity.schema.json#/definitions/build.why).
CUSTOM_BUILD = "custom_build"                  # not an official image, or its commit is off mainline
                                               # (or not in vllm-project/vllm at all: a fork)
OUTSIDE_DISTANCE = "outside_distance"          # more than max_distance commits from VLLM_REF
COMMIT_UNRESOLVABLE = "commit_unresolvable"    # no source names a commit at all
COMMIT_CONFLICT = "commit_conflict"            # the sources name different commits


@dataclass
class Build:
    """The build record for one point (fidelity.schema.json#/definitions/build)."""
    image: str
    commit: str | None = None
    source: str | None = None
    ref: str = VLLM_REF
    distance: int | None = None
    why: str | None = None          # None: exact

    @property
    def match(self) -> str:
        return "estimated" if self.why else "exact"

    def record(self) -> dict:
        rec = {"image": self.image, "commit": self.commit, "source": self.source,
               "ref": self.ref, "distance": self.distance, "match": self.match}
        if self.why:
            rec["why"] = self.why
        return rec


@dataclass
class Resolver:
    registry: Registry
    github: GitHub
    ref: str = VLLM_REF
    max_distance: int = VLLM_MAX_DISTANCE
    repo: str = VLLM_REPO
    _commits: dict = field(default_factory=dict)       # sha prefix -> full sha | None
    _absent: set = field(default_factory=set)          # shas vllm-project/vllm doesn't have
    _labels: dict = field(default_factory=dict)        # (repository, reference) -> label | None
    _placement: dict = field(default_factory=dict)     # full sha -> (distance | None, why | None)
    _tags: dict = field(default_factory=dict)          # release tag -> commit sha | None
    _ref_base: str | None = None
    # One Resolver is shared across the pull's download-worker pool, so every cache here is read and
    # written concurrently. `_guard` serialises the dict/set bookkeeping; `_locks` hands out one lock
    # per cache key so the first worker to miss does the (network) fetch and the rest wait for and
    # reuse its result, instead of all firing the same API call and racing the write (GitHub #15).
    _guard: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _locks: dict = field(default_factory=dict, repr=False)

    def _keylock(self, kind: str, key) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault((kind, key), threading.Lock())

    def _full(self, sha: str) -> str | None:
        """Expand a SHA through the GitHub API, cached."""
        with self._keylock("commit", sha):
            if sha not in self._commits:
                full = sha if _FULL_SHA.fullmatch(sha) else None
                got = self.github.resolve_commit(self.repo, sha)
                self._commits[sha] = got if got and (full is None or got == full) else None
                if got is None:
                    with self._guard:
                        self._absent.add(sha)
            return self._commits[sha]

    def _is_absent(self, sha: str) -> bool:
        with self._guard:
            return sha in self._absent

    def _tag_commit(self, tag: str) -> str | None:
        """The commit a release tag names, cached: many points share one release image, so the tag
        resolves once per run rather than once per point (the call that exhausted the quota)."""
        with self._keylock("tag", tag):
            if tag not in self._tags:
                self._tags[tag] = self.github.tag_commit(self.repo, tag)
            return self._tags[tag]

    def _label(self, repository: str, reference: str) -> str | None:
        key = (repository, reference)
        with self._keylock("label", key):
            if key not in self._labels:
                self._labels[key] = self.registry.revision_label(repository, reference)
            return self._labels[key]

    def ref_branch_point(self) -> str:
        """Where VLLM_REF's release branch left main."""
        with self._keylock("ref_base", None):
            if self._ref_base is None:
                self._ref_base = self.github.merge_base(self.repo, self.ref, "main")
            return self._ref_base

    def _place(self, commit: str) -> tuple[int | None, str | None]:
        """(distance, why) for a resolved commit, cached per commit; why is None within distance."""
        with self._keylock("place", commit):
            if commit not in self._placement:
                # On main iff main contains the commit. (Comparing against the branch point instead
                # would call a release-branch commit, or a fork cut after that point, "ahead".)
                status, _, _ = self.github.compare(self.repo, commit, "main")
                if status in ("ahead", "identical"):
                    point = commit
                elif self.github.is_on_release_tag(self.repo, commit):
                    # A release-branch commit: measured from where its branch left main.
                    point = self.github.merge_base(self.repo, commit, "main")
                else:
                    self._placement[commit] = (None, CUSTOM_BUILD)
                    return self._placement[commit]
                _, ahead, behind = self.github.compare(self.repo, self.ref_branch_point(), point)
                distance = ahead - behind
                self._placement[commit] = (distance, OUTSIDE_DISTANCE if abs(distance) > self.max_distance else None)
            return self._placement[commit]

    def resolve(self, image: str, server_log: str | None = None) -> Build:
        build = Build(image=image or "", ref=self.ref)
        img = parse_image(image)
        if img is None or img.repository not in OFFICIAL_IMAGES:
            build.why = CUSTOM_BUILD
            return build

        label_commit, label_source = None, None
        label = self._label(img.repository, img.reference) if img.reference else None
        if label and label != "unknown":
            label_commit = self._full(label)
            label_source = "image_label" if img.digest else "label_by_tag"

        status, banner, dirty = banner_sha(server_log)
        if status == BANNER_CONFLICT:
            build.why = COMMIT_CONFLICT
            return build
        banner_commit = None
        if banner:
            if label_commit and not label_commit.startswith(banner):
                # The log names a different (possibly patched, unpublished) commit than the image.
                build.why = COMMIT_CONFLICT
                return build
            banner_commit = self._full(banner)
            if dirty and not label_commit:
                # A build-tree suffix is a local build; it counts only when the label confirms it.
                build.why = COMMIT_UNRESOLVABLE
                return build

        # A tag SHA only counts once it resolves: tags also end in dates (…-20261019) and words.
        tag = tag_sha(img.tag)
        tag_commit = self._full(tag) if tag else None

        # A release image whose label and banner name no commit: vLLM's own release tag does,
        # as long as the banner (if the log has one) prints that release and nothing else.
        release_commit = None
        if img.tag and _RELEASE_TAG.fullmatch(img.tag) and not (label_commit or banner_commit or tag_commit):
            printed = set(_BANNER_VERSION.findall(server_log or ""))
            if printed and printed != {img.tag}:
                build.why = COMMIT_CONFLICT
                return build
            release_commit = self._tag_commit(img.tag)

        # The image label or the log's banner named a commit vllm-project/vllm doesn't have
        # (GitHub answers 422): the build is off vLLM's mainline, i.e. a custom build, not an
        # unknown one. (An image tag's trailing hex is no such statement: it can be a date.)
        named_unknown = (label and label != "unknown" and self._is_absent(label)) or (banner and self._is_absent(banner))
        candidates = [(src, sha) for src, sha in ((label_source, label_commit),
                                                  ("server_log_banner", banner_commit),
                                                  ("image_tag", tag_commit),
                                                  ("release_tag", release_commit)) if sha]
        if len({sha for _, sha in candidates}) > 1:
            build.why = COMMIT_CONFLICT
            return build
        if not candidates or named_unknown:
            build.why = CUSTOM_BUILD if named_unknown else COMMIT_UNRESOLVABLE
            return build
        build.source, build.commit = candidates[0]
        build.distance, build.why = self._place(build.commit)
        return build
