"""Tests for build resolution and the distance gate (orchestrator/ingest/build.py).

Run: python3 orchestrator/ingest/test_build.py
"""
import json
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build as b  # noqa: E402
import clients  # noqa: E402

MAIN_BASE = "3d5f4d4c" + "0" * 32          # v0.31.0's branch point on main
ON_MAIN = "ac9126e58aa7bbab1856ba6593ba4d5003fea516"
OLDER = "cd10ed6f9f6b37a8ace9cf380007e66fe12ec0c3"
FAR = "aaaa" * 10
FORK = "8b00f4123" + "f" * 31          # a branch build: on vLLM, but off main
RELEASE_BRANCH = "db9527a46873454610df6dbedf79a36d6bf1a7f6"   # the v0.31.0 tag itself
DIGEST = "sha256:" + "9" * 64


class FakeRegistry:
    def __init__(self, labels):
        self.labels = labels            # (repository, reference) -> label
        self.calls = []

    def revision_label(self, repository, reference):
        self.calls.append((repository, reference))
        return self.labels.get((repository, reference))


class FakeGitHub:
    """A small model of vLLM's history. ON_MAIN / OLDER / FAR are on main at the given signed
    distance from MAIN_BASE. RELEASE_BRANCH (the v0.31.0 tag) sits 27 commits up a release branch
    cut at MAIN_BASE; FORK sits on a branch cut 16 commits after MAIN_BASE. Neither is on main,
    yet both are strictly "ahead" of MAIN_BASE, which is the case a naive check gets wrong."""
    ON = {ON_MAIN: 207, OLDER: -738, FAR: 2001, MAIN_BASE: 0}
    BRANCHED = {RELEASE_BRANCH: (MAIN_BASE, 27), FORK: ("f0" * 20, 5)}   # sha -> (cut point, commits up)
    CUT_DISTANCE = {MAIN_BASE: 0, "f0" * 20: 16}

    def __init__(self):
        self.resolved, self.compares, self.merge_bases, self.tag_checks = [], [], [], []

    def resolve_commit(self, repo, sha):
        self.resolved.append(sha)
        hits = [c for c in (*self.ON, *self.BRANCHED) if c.startswith(sha)]
        return hits[0] if len(hits) == 1 else None

    def _pos(self, sha):
        if sha in self.ON:
            return self.ON[sha]
        return self.CUT_DISTANCE[sha]

    def compare(self, repo, base, head):
        self.compares.append((base, head))
        if head == "main":   # is base contained in main?
            return ("ahead", 1, 0) if base in self.ON else ("diverged", 1, 1)
        assert base == MAIN_BASE and head in (*self.ON, *self.CUT_DISTANCE), (base, head)
        d = self._pos(head)
        return ("ahead", d, 0) if d > 0 else ("behind", 0, -d) if d < 0 else ("identical", 0, 0)

    def merge_base(self, repo, a, b_):
        self.merge_bases.append(a)
        return self.BRANCHED[a][0] if a in self.BRANCHED else MAIN_BASE

    def is_on_release_tag(self, repo, sha):
        self.tag_checks.append(sha)
        return sha == RELEASE_BRANCH


def _resolver(labels=None):
    return b.Resolver(registry=FakeRegistry(labels or {}), github=FakeGitHub())


def _log(sha_part, suffix=""):
    return f"INFO … Initializing a V1 LLM engine (v0.30.1rc1.dev493+g{sha_part}{suffix}) with config: …"


# ------------------------------------------------------------------ parsing

def test_parse_image_splits_repository_tag_and_digest():
    img = b.parse_image("vllm/vllm-openai:nightly-ac9126e58aa7@" + DIGEST)
    assert (img.repository, img.tag, img.digest) == ("vllm/vllm-openai", "nightly-ac9126e58aa7", DIGEST)
    assert img.reference == DIGEST
    assert b.parse_image("vllm/vllm-openai:v0.31.0").reference == "v0.31.0"
    assert b.parse_image("vllm/vllm-openai").tag is None
    assert b.parse_image("") is None
    assert b.parse_image("vllm/vllm-openai:x@sha256:short") is None


def test_parse_image_keeps_a_registry_port_in_the_repository():
    img = b.parse_image("registry.example:5000/vllm/vllm-openai")
    assert (img.repository, img.tag) == ("registry.example:5000/vllm/vllm-openai", None)


def test_banner_sha_reads_the_engine_line_and_its_build_tree_suffix():
    assert b.banner_sha(_log("ac9126e58")) == ("ok", "ac9126e58", False)
    assert b.banner_sha(_log("49cb2bbf7", ".d20261016")) == ("ok", "49cb2bbf7", True)
    assert b.banner_sha("transformers version 4.57.0+g1234567") == (b.BANNER_NONE, None, False)
    assert b.banner_sha(None) == (b.BANNER_NONE, None, False)


def test_banner_sha_reports_ranks_that_disagree():
    assert b.banner_sha(_log("ac9126e58") + "\n" + _log("ac9126e58")) == ("ok", "ac9126e58", False)
    assert b.banner_sha(_log("ac9126e58") + "\n" + _log("cd10ed6f9"))[0] == b.BANNER_CONFLICT


def test_tag_sha_takes_the_trailing_hex_run():
    assert b.tag_sha("nightly-" + ON_MAIN) == ON_MAIN
    assert b.tag_sha("nightly-dev-x86_64-cu130-ac9126e58aa7") == "ac9126e58aa7"
    assert b.tag_sha("cu134-nightly-x86_64-dev-20261019-mk") is None
    assert b.tag_sha("v0.31.0") is None
    assert b.tag_sha("kimi-k3") is None


# ------------------------------------------------------------------ the gate

def test_non_official_images_are_custom_builds():
    for image in ("vllm/vllm-openai-dev:nightly-" + ON_MAIN, "lmsysorg/sglang:v0.5.9", "", None,
                  "us-central1-docker.pkg.dev/x/torchtpu-vllm/torchtpu-vllm-prod:sa-oct-01"):
        assert _resolver().resolve(image).reasons == ["custom_build"], image


def test_label_by_digest_wins_and_is_recorded_as_image_label():
    r = _resolver({("vllm/vllm-openai", DIGEST): ON_MAIN})
    got = r.resolve("vllm/vllm-openai:nightly-dev-x86_64-cu130-ac9126e58aa7@" + DIGEST)
    assert got.reasons == [] and got.commit == ON_MAIN and got.source == "image_label" and got.distance == 207


def test_label_read_by_tag_is_recorded_as_label_by_tag():
    tag = "cu134-nightly-x86_64-dev-20261019-mk"
    got = _resolver({("vllm/vllm-openai", tag): ON_MAIN}).resolve(f"vllm/vllm-openai:{tag}")
    assert (got.source, got.commit, got.reasons) == ("label_by_tag", ON_MAIN, [])


def test_unknown_label_falls_through_to_the_banner():
    tag = "nightly-dev-x86_64-cu13.0.1-zzzz"
    r = _resolver({("vllm/vllm-openai", tag): "unknown"})
    got = r.resolve(f"vllm/vllm-openai:{tag}", server_log=_log("cd10ed6f9"))
    assert (got.source, got.commit, got.distance, got.reasons) == ("server_log_banner", OLDER, -738, [])


def test_missing_label_and_banner_fall_through_to_the_tag_sha():
    got = _resolver().resolve("vllm/vllm-openai:nightly-" + OLDER)
    assert (got.source, got.commit, got.distance) == ("image_tag", OLDER, -738)


def test_build_tree_suffix_is_accepted_when_the_label_agrees():
    tag = "cu134-nightly-x86_64-dev-20261019-mk"
    got = _resolver({("vllm/vllm-openai", tag): ON_MAIN}).resolve(
        f"vllm/vllm-openai:{tag}", server_log=_log("ac9126e58", ".d20261016"))
    assert got.reasons == [] and got.commit == ON_MAIN


def test_build_tree_suffix_without_a_confirming_label_is_unresolvable():
    for labels in ({}, {("vllm/vllm-openai", "t"): "unknown"}):
        got = _resolver(labels).resolve("vllm/vllm-openai:t", server_log=_log("ac9126e58", ".d20261016"))
        assert got.reasons == ["build_commit_unresolvable"], labels


def test_banners_that_disagree_across_ranks_conflict_even_with_a_label():
    log = _log("ac9126e58") + "\n" + _log("cd10ed6f9")
    got = _resolver({("vllm/vllm-openai", "t"): ON_MAIN}).resolve("vllm/vllm-openai:t", server_log=log)
    assert got.reasons == ["build_commit_conflict"]


def test_a_banner_commit_unknown_to_vllm_conflicts_with_the_label():
    # A patched local build: the label says ON_MAIN, the banner names a commit vLLM doesn't have.
    got = _resolver({("vllm/vllm-openai", "t"): ON_MAIN}).resolve("vllm/vllm-openai:t", server_log=_log("1234567"))
    assert got.reasons == ["build_commit_conflict"]


def test_a_tag_ending_in_a_date_is_not_mistaken_for_a_commit():
    got = _resolver().resolve("vllm/vllm-openai:nightly-20261019", server_log=_log("cd10ed6f9"))
    assert (got.source, got.commit, got.reasons) == ("server_log_banner", OLDER, [])


def test_sources_naming_different_commits_conflict():
    got = _resolver({("vllm/vllm-openai", "nightly-x"): ON_MAIN}).resolve(
        "vllm/vllm-openai:nightly-x", server_log=_log("cd10ed6f9"))
    assert got.reasons == ["build_commit_conflict"] and got.commit is None


def test_a_commit_that_is_not_in_vllm_is_unresolvable():
    got = _resolver({("vllm/vllm-openai", "nightly-dev-x86_64-cu13.0.1-20ebb28"): "unknown"}).resolve(
        "vllm/vllm-openai:nightly-dev-x86_64-cu13.0.1-20ebb28", server_log=_log("1234567"))
    assert got.reasons == ["build_commit_unresolvable"] and got.distance is None


def test_a_full_sha_label_that_github_expands_differently_is_rejected():
    class Liar(FakeGitHub):
        def resolve_commit(self, repo, sha):
            return OLDER
    r = b.Resolver(registry=FakeRegistry({("vllm/vllm-openai", "t"): ON_MAIN}), github=Liar())
    assert r.resolve("vllm/vllm-openai:t").reasons == ["build_commit_unresolvable"]


def test_off_main_commit_is_a_custom_build():
    got = _resolver().resolve("vllm/vllm-openai:vllm-minimax-m3-perf-x86_64-13.0.1-8b00f41",
                              server_log=_log("8b00f4123"))
    assert got.reasons == ["custom_build"] and got.commit == FORK and got.distance is None


def test_release_branch_commit_is_measured_from_its_branch_point():
    # The v0.31.0 tag is 27 commits up its release branch; its distance is 0, not +27.
    got = _resolver({("vllm/vllm-openai", "v0.31.0"): RELEASE_BRANCH}).resolve("vllm/vllm-openai:v0.31.0")
    assert got.reasons == [] and got.commit == RELEASE_BRANCH and got.distance == 0


def test_branch_cut_after_the_reference_is_still_a_custom_build():
    # Strictly "ahead" of the branch point, but not on main and not on a release tag.
    got = _resolver().resolve("vllm/vllm-openai:x", server_log=_log("8b00f4123"))
    assert got.reasons == ["custom_build"] and got.distance is None


def test_distance_limit_is_inclusive_and_symmetric():
    r = b.Resolver(registry=FakeRegistry({}), github=FakeGitHub(), max_distance=738)
    assert r.resolve("vllm/vllm-openai:nightly-" + OLDER).reasons == []          # -738: at the limit
    r = b.Resolver(registry=FakeRegistry({}), github=FakeGitHub(), max_distance=737)
    assert r.resolve("vllm/vllm-openai:nightly-" + OLDER).reasons == ["outside_distance"]
    got = _resolver().resolve("vllm/vllm-openai:nightly-" + FAR)                   # +2001 > 2000
    assert got.reasons == ["outside_distance"] and got.distance == 2001 and got.commit == FAR


def test_rocm_images_are_official():
    got = _resolver().resolve("vllm/vllm-openai-rocm:nightly-rocm100-" + ON_MAIN)
    assert got.reasons == [] and got.distance == 207


def test_lookups_are_cached_per_image_and_per_commit():
    tag = "vllm-minimax-m3-perf-x86_64-13.0.1-8b00f41"
    r = _resolver({("vllm/vllm-openai", "nightly-" + OLDER): OLDER})
    for _ in range(5):                                    # five concurrency points, two images
        r.resolve("vllm/vllm-openai:nightly-" + OLDER)
        r.resolve(f"vllm/vllm-openai:{tag}", server_log=_log("8b00f4123"))
    assert r.registry.calls == [("vllm/vllm-openai", "nightly-" + OLDER), ("vllm/vllm-openai", tag)]
    assert sorted(set(r.github.resolved)) == sorted(r.github.resolved)       # each SHA expanded once
    assert r.github.tag_checks == [FORK]                                     # off-main check once
    assert len(r.github.compares) == 3      # OLDER: on-main + distance; FORK: on-main only
    assert r.github.merge_bases == ["v0.31.0"]                               # branch point once


def test_record_matches_the_fidelity_build_shape():
    got = _resolver().resolve("vllm/vllm-openai:nightly-" + OLDER)
    assert got.record() == {"image": "vllm/vllm-openai:nightly-" + OLDER, "commit": OLDER,
                            "source": "image_tag", "ref": "v0.31.0", "distance": -738}


# ------------------------------------------------------------------ the registry client

class _Resp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return json.dumps(self.body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(handler):
    def urlopen(req, timeout=None):
        url = req.full_url
        auth = req.headers.get("Authorization", "")
        status, body = handler(url, auth)
        if status != 200:
            raise urllib.error.HTTPError(url, status, "x", {}, None)
        return _Resp(body)
    return urlopen


def test_registry_refreshes_an_expired_token_and_retries_a_401_once():
    calls = {"token": 0}
    now = [0.0]

    def handler(url, auth):
        if url.startswith("https://auth.docker.io/"):
            calls["token"] += 1
            return 200, {"token": f"t{calls['token']}", "expires_in": 300}
        if auth == "Bearer t1" and "/blobs/" in url:
            return 401, None                                  # t1 rejected mid-run
        if "/manifests/" in url:
            return 200, {"config": {"digest": "sha256:" + "c" * 64}}
        return 200, {"config": {"Labels": {"org.opencontainers.image.revision": ON_MAIN}}}

    orig = clients.urllib.request.urlopen
    clients.urllib.request.urlopen = _fake_urlopen(handler)
    try:
        reg = clients.DockerHubRegistry(clock=lambda: now[0])
        assert reg.revision_label("vllm/vllm-openai", "t") == ON_MAIN
        assert calls["token"] == 2                            # one refresh after the 401
        now[0] = 10_000                                       # far past expiry
        reg.revision_label("vllm/vllm-openai", "t")
        assert calls["token"] == 3
    finally:
        clients.urllib.request.urlopen = orig


def test_registry_treats_404_as_no_label_but_raises_on_other_errors():
    orig = clients.urllib.request.urlopen
    try:
        for code, expect_raise in ((404, False), (429, True), (500, True)):
            def handler(url, auth, code=code):
                if url.startswith("https://auth.docker.io/"):
                    return 200, {"token": "t", "expires_in": 300}
                return code, None
            clients.urllib.request.urlopen = _fake_urlopen(handler)
            reg = clients.DockerHubRegistry()
            try:
                got = reg.revision_label("vllm/vllm-openai", "t")
                assert not expect_raise and got is None, code
            except urllib.error.HTTPError:
                assert expect_raise, code
    finally:
        clients.urllib.request.urlopen = orig


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
