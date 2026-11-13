"""Closeness grades, computed from data alone (design §11.3, §11.4; COV-4, COV-5, COV-6).

Every point gets exactly one grade: the highest-numbered (least close) grade whose conditions
apply.

  G1  exact: the run's engine release is the one the scoring simulator runs, and nothing was
      substituted.
  G2  as G1, with every substitution named on the point (an estimated value, a status allowed
      only during a release plan, a client difference, a resolved value that differs ...).
  G3  the run's engine release is another one, and no upstream function the engine ports
      changed between the two releases.
  G4  as G3, but some ported function changed, or the build is nightly or custom; or the
      engine has not published its list of ported functions, so that cannot be told.
  G5  not scored, for one of the reasons in G5_CODES only.

A point's figures count toward the headline when its grade is G1 to G4 (COV-11).

The grade reads the point's recorded engine build (build.py's record), the simulator's engine
release (stack.json, through the Result's engine block), and the substitutions the scorer
named. It holds no table of settings: field statuses come from the engine's fields.json.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

G1, G2, G3, G4, G5 = "G1", "G2", "G3", "G4", "G5"
GRADES = (G1, G2, G3, G4, G5)
GRADED = (G1, G2, G3, G4)

# The closed list of design §11.4 (COV-5). Any other G5 reason is an error.
G5_CODES = (
    "code_not_visible",
    "router_unsupported",
    "topology_unsupported",
    "value_not_recorded",
    "field_not_modelled",
    "field_unclassified",
    "engine_unsupported",
    "not_in_catalog",
    "field_not_in_release",
    "value_conflict",
    "build_unparseable",
)

# Substitution kinds (blis-substrate contracts/spec/pointrecord): the G2 conditions, and the G3
# and G4 ones. client_difference is design §11.3's G2 condition "the simulated requests differ
# from the ones the run's client sent" (COV-12), which pointrecord has no kind for yet.
# later_record is §11.3's "a fact of the cluster the run's own record lacks was taken from the
# benchmark's later record of the same runner" (inferencex_runners.py); pointrecord has no kind
# for it yet.
G2_KINDS = ("coefficient_method", "coefficient_range", "execution_mode", "kernel_hash", "value_class",
            "estimated", "interim_status", "resolved_differs", "client_difference",
            "later_record", "router_differs", "unevaluated")
# router_differs is §11.3's "the run's router, which BLIS does not host, was replaced by an llm-d
# policy from the router table" (design change blis-design#1; blis-substrate router table).

# The keys a substitution of a kind names, as blis-substrate's point record requires them: a
# later_record the record and its date, a router_differs the entry, the policy, the router table's
# evidence, the router build (a full commit), and the entry's difference and bound (its subject is the router the run used; the
# difference and bound are copied from the entry as it states them), a client_difference and a resolved_differs
# the detail. A key belongs to its own kind only.
KIND_KEYS = {"later_record": ("record", "date"),
             "router_differs": ("entry", "policy", "evidence", "revision", "difference", "regime", "bound")}
DETAIL_KINDS = ("client_difference", "resolved_differs")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Four of design §11.3's G1 conditions cannot be checked yet, because no source carries the
# datum: a library's kernel hash (the run's server log and launch configuration name library
# versions at most, and the Result's selected-entry report carries set, name, method, scope and
# file only), a coefficient lookup's extrapolated or unidentified range, a modelled field's value
# class, and the resolved values the engine would choose. Each is named on every scored point as
# a G2 substitution of its own kind, so no G1 and no G3 is published for a condition nobody
# graded. A condition is evaluated from data by g1.py; the point names its kind only when the data
# is absent for that point (score.evaluate_g1), or when the condition is false.
# An unevaluated condition is recorded as the substrate records it (pointrecord.SubUnevaluated):
# kind `unevaluated`, whose subject is the condition, named by the kind that would record its failure.
# The kind `kernel_hash` (and the other three) is then only ever a condition found false.
NOT_CHECKED_KIND = "unevaluated"
UNCHECKED_KINDS = ("coefficient_range", "kernel_hash", "resolved_differs", "value_class")
G34_KINDS = ("other_release", "changed_functions", "nightly_or_custom", "ported_functions_unpublished")

PORTED_FUNCTIONS_UNPUBLISHED = "ported-function list not published"
_RELEASE = re.compile(r"^v?(\d+\.\d+\.\d+)$")
_BANNER_RELEASE = re.compile(r"^(\d+\.\d+\.\d+)$")


class GradeError(ValueError):
    """A point's grade inputs break a rule of design §11.3 or §11.4."""


@dataclass
class Release:
    """The engine release a run measured, read from its recorded build."""
    version: str | None             # e.g. "0.32.0"; None for a nightly or custom build
    nightly_or_custom: bool
    why: str = ""                   # the build, named, when it is nightly or custom


def run_release(build: dict, banner_version: str | None) -> Release:
    """The upstream release a point's recorded build is, or that it is nightly or custom.

    A release is an official image whose tag is vX.Y.Z and whose server-log banner, when the
    log prints one, names that same version (build.py resolves the commit vX.Y.Z tags). Any
    other build (a nightly image, a dev build, a fork, a private image) is nightly or custom.
    """
    image = (build or {}).get("image") or ""
    tag = image.rsplit(":", 1)[-1] if ":" in image.rsplit("/", 1)[-1] else ""
    m = _RELEASE.match(tag)
    official = image.split("@", 1)[0].rsplit(":", 1)[0] in ("vllm/vllm-openai", "vllm/vllm-openai-rocm")
    if official and m and (banner_version is None or banner_version.lstrip("v") == m.group(1)):
        return Release(version=m.group(1), nightly_or_custom=False)
    if banner_version and _BANNER_RELEASE.match(banner_version.lstrip("v")) and official:
        return Release(version=banner_version.lstrip("v"), nightly_or_custom=False)
    return Release(version=None, nightly_or_custom=True,
                   why=f"{image or 'no image'} (banner {banner_version or 'none'})")


@dataclass
class Graded:
    grade: str
    substitutions: list = field(default_factory=list)   # [{"kind", "subject", "detail"}], sorted
    g5: dict | None = None                               # {"code", "subject"} when G5


def unchecked(kinds=None) -> list[dict]:
    """The substitutions naming the G1 conditions that are unevaluated: all of UNCHECKED_KINDS, or
    the given ones, the conditions whose data is not present for the point (g1.evaluate)."""
    kinds = UNCHECKED_KINDS if kinds is None else tuple(k for k in UNCHECKED_KINDS if k in kinds)
    return [{"kind": NOT_CHECKED_KIND, "subject": k, "detail": f"{k} is unevaluated"} for k in kinds]


def _sorted(subs: list[dict]) -> list[dict]:
    seen, out = set(), []
    for s in sorted(subs, key=lambda s: (s["kind"], s["subject"], s.get("detail", ""))):
        k = (s["kind"], s["subject"])
        if k not in seen:
            seen.add(k)
            out.append(s)
    return out


# The conditions of G1 a point can leave unevaluated (pointrecord's g1Conditions): the subject of an
# `unevaluated` substitution is one of these, the kind that would record the condition's failure.
G1_CONDITIONS = ("coefficient_method", "coefficient_range", "execution_mode", "kernel_hash", "value_class",
                 "interim_status", "resolved_differs", "client_difference", "other_release")


def _check_keys(s: dict) -> None:
    if s["kind"] == NOT_CHECKED_KIND and s["subject"] not in G1_CONDITIONS:
        raise GradeError(f"an unevaluated substitution names {s['subject']!r}, which is not a condition of G1 "
                         f"({', '.join(G1_CONDITIONS)})")
    need = KIND_KEYS.get(s["kind"], ())
    for k in need:
        if not s.get(k):
            raise GradeError(f"a {s['kind']} substitution on {s['subject']!r} names no {k}")
    if s["kind"] in DETAIL_KINDS and not s.get("detail"):
        raise GradeError(f"a {s['kind']} substitution on {s['subject']!r} names no detail")
    for k in ("record", "date", "entry", "policy", "evidence", "revision", "difference", "regime", "bound"):
        if s.get(k) is not None and k not in need:
            raise GradeError(f"{k} is not a key of {s['kind']} (substitution on {s['subject']!r})")
    if s["kind"] == "router_differs":
        if s["policy"] in ("", "none"):      # the policy is the router table's own; "none" records that no policy is close enough
            raise GradeError(f"a router_differs substitution names policy {s['policy']!r}: the router table maps no policy")
        if not s["entry"].startswith(s["subject"] + "-"):
            raise GradeError(f"router table entry {s['entry']!r} is not an entry of the router {s['subject']!r}")
    if s["kind"] == "router_differs":
        import router_table as _rt
        bad = _rt.carried_bound_covers_point(s)
        if bad:
            raise GradeError(f"router_differs on {s['subject']!r}: {'; '.join(bad)}")
    if s["kind"] == "router_differs" and not re.match(r"^[0-9a-f]{40}$", str(s["revision"])):
        raise GradeError(f"a router_differs revision is a full 40-hex commit, got {s['revision']!r}")
    if s["kind"] == "later_record" and not _DATE.match(s["date"]):
        raise GradeError(f"a later_record date is YYYY-MM-DD, got {s['date']!r}")


def grade(*, engine_version: str, release: Release, substitutions: list[dict],
          g5: list[dict] | None = None, ported: dict | None = None) -> Graded:
    """The point's one grade.

    engine_version  the engine release the scoring simulator runs (stack.json), e.g. "0.32.0".
    release         the run's own release (run_release).
    substitutions   every G2 substitution the scorer named.
    g5              the G5 reasons found, each {"code", "subject"}; the first by code order is
                    the point's reason, and the rest are kept as further reasons.
    ported          the engine's published ported-function list and its function-level diffs:
                    {"functions": [...], "changed": {from_release: [function, ...]}}; None when
                    the engine publishes none, and then another release is G4.
    """
    for s in substitutions:
        if s.get("kind") not in G2_KINDS:
            raise GradeError(f"substitution kind {s.get('kind')!r} is not a G2 condition")
        if not s.get("subject"):
            raise GradeError(f"a {s['kind']} substitution names no subject")
        _check_keys(s)
    if g5:
        for r in g5:
            if r.get("code") not in G5_CODES:
                raise GradeError(f"G5 reason {r.get('code')!r} is not one of design §11.4's (COV-5)")
        first = sorted(g5, key=lambda r: (G5_CODES.index(r["code"]), r.get("subject", "")))[0]
        return Graded(G5, [], {k: v for k, v in first.items() if v})
    subs = list(substitutions)
    if release.nightly_or_custom:
        subs.append({"kind": "nightly_or_custom", "subject": "engine build", "detail": release.why})
        return Graded(G4, _sorted(subs))
    if release.version != engine_version:
        subs.append({"kind": "other_release", "subject": "engine release",
                     "detail": f"{release.version}, scored on {engine_version}"})
        if ported is None:
            subs.append({"kind": "ported_functions_unpublished", "subject": "engine release",
                         "detail": PORTED_FUNCTIONS_UNPUBLISHED})
            return Graded(G4, _sorted(subs))
        changed = (ported.get("changed") or {}).get(release.version)
        if changed is None:
            subs.append({"kind": "ported_functions_unpublished", "subject": "engine release",
                         "detail": f"no function-level diff from {release.version} published"})
            return Graded(G4, _sorted(subs))
        if changed:
            subs.append({"kind": "changed_functions", "subject": "engine release",
                         "detail": ", ".join(sorted(changed))})
            return Graded(G4, _sorted(subs))
        return Graded(G3, _sorted(subs))
    return Graded(G2 if subs else G1, _sorted(subs))


def check(points: list[dict], engine_version: str) -> list[str]:
    """COV-4, COV-5 and COV-6 over a run's points: every point has exactly one grade, every G5
    reason is on the closed list, every G2 to G4 substitution is named, each point's grade
    agrees with its recorded build and the simulator's engine release, and one simulator build,
    running that engine release, scored every point."""
    out = []
    sims = {(json.dumps(p["simulator"], sort_keys=True) if p.get("simulator") else None) for p in points}
    if len(sims) > 1:
        out.append(f"{len(sims)} simulator builds or engine releases scored this run's points; one must score "
                   f"them all (COV-6): {sorted(s or 'none' for s in sims)}")
    for p in points:
        eng = ((p.get("simulator") or {}).get("engine") or {}).get("version")
        if "simulator" in p and eng != engine_version:
            out.append(f"{str(p.get('point_id'))[:12]}: scored by a simulator running {eng!r}, not {engine_version} (COV-6)")
            break
    for p in points:
        pid = str(p.get("point_id"))[:12]
        g = p.get("grade")
        if g not in GRADES:
            out.append(f"{pid}: grade {g!r} is not one of {GRADES}")
            continue
        subs = p.get("substitutions") or []
        if g == G5:
            code = (p.get("g5_reason") or {}).get("code")
            if code not in G5_CODES:
                out.append(f"{pid}: G5 reason {code!r} is not one of design §11.4's (COV-5)")
            continue
        if p.get("g5_reason"):
            out.append(f"{pid}: a {g} point carries a G5 reason")
        if g == G1 and subs:
            out.append(f"{pid}: a G1 point names substitutions")
        if g in (G2, G3, G4) and not subs:
            out.append(f"{pid}: a {g} point names no substitution (COV-4)")
        kinds = {s["kind"] for s in subs}
        if g in (G1, G2) and kinds & set(G34_KINDS):
            out.append(f"{pid}: a {g} point was measured on another release or build")
        if g in (G3, G4) and not kinds & set(G34_KINDS):
            out.append(f"{pid}: a {g} point names no other release or build (COV-6)")
        rel = (p.get("build") or {}).get("release")
        if g in (G1, G2) and rel != engine_version:
            out.append(f"{pid}: graded {g}, but its build's release {rel!r} is not {engine_version} (COV-6)")
    return out
