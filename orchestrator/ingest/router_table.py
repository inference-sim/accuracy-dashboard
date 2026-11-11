"""The router table (blis-substrate `catalog/routers`) as the dashboard reads it (design §11.3, §11.4;
dashboard router-table reader).

BLIS hosts llm-d's router only. A run measured behind another router is simulated with an llm-d policy
only where the table maps that router, mode, session-affinity setting and **build** to a policy, and the
entry has a measured bound for the regime the point is in; the point then names the router the run used,
the policy BLIS used, the build, the entry's difference statements and its bound, and is G2 at best
(`router_differs`), whatever the bound's ratios are: the reader decides from them. Where no entry maps it,
or the bound says nothing of the point's regime, the point stays G5 `router_unsupported`, with the
outcome named.

This module reads the substrate's entries and holds none (X7). The shape is the substrate's
(contracts/spec/routertable): `router`, `mode`, optional `session_affinity_ttl_s`, `revisions` (the router
builds, as full commits, the entry is shown for), `policy` (an llm-d policy or `none`), `reason`,
`difference` (statements `{aspect, text, evidence}`), `bound` (`evidence`, `ratios`, `not_measured`) and
`evidence`. The outcome of looking a run up is the substrate's `Resolve`: `mapped`, `no_policy`,
`revision_not_covered` or `no_entry`, and a mapped entry adds one more, `no_bound_for_regime`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# The router a framework label or a row names, as the table spells it.
ROUTER_ALIASES = {"dynamo-router": "dynamo"}
MAPPED, NO_POLICY, REVISION_NOT_COVERED, NO_ENTRY, NO_BOUND = (
    "mapped", "no_policy", "revision_not_covered", "no_entry", "no_bound_for_regime")
OUTCOMES = (MAPPED, NO_POLICY, REVISION_NOT_COVERED, NO_ENTRY, NO_BOUND)
# A ratio above this makes the point's bound wide: the choice of policy can move a figure by a quarter.
WIDE_RATIO = 1.25
HEX40 = re.compile(r"^[0-9a-f]{40}$")

# The workloads a bound can name (routertable.WorkloadKinds), by (prompt tokens, output tokens).
WORKLOADS = {(1024, 1024): "balanced", (8192, 16): "prefill-bound", (256, 2048): "decode-bound"}


def router_key(name: str | None) -> str | None:
    """The table's name for the router a row, a launch configuration or a label names."""
    if not name:
        return None
    n = str(name).split("/", 1)[0]
    return ROUTER_ALIASES.get(n, n.removesuffix("-router"))


def workload_kind(isl, osl) -> str | None:
    """The workload kind of a point's request lengths, or None where no kind has them."""
    return WORKLOADS.get((isl, osl))


@dataclass
class Entry:
    name: str
    router: str
    mode: str
    ttl: int | None
    policy: str
    revisions: list = field(default_factory=list)
    reason: str = ""
    difference: list = field(default_factory=list)      # [{aspect, text, evidence}]
    bound: dict | None = None
    evidence: list = field(default_factory=list)

    def maps(self) -> bool:
        return self.policy != "none"

    def covers(self, revision: str | None) -> bool:
        return revision is not None and revision in self.revisions


class Table:
    def __init__(self, entries: list[Entry] | None = None, problems: list[str] | None = None):
        self.entries = entries or []
        self.problems = problems or []

    def resolve(self, router: str | None, mode: str | None, ttl: int | None, revision: str | None):
        """(entry or None, outcome), as the substrate's routertable.Resolve: the entry of this router, mode
        and session-affinity setting is returned whenever there is one, covered or not."""
        if router is None or mode is None:
            return None, NO_ENTRY
        for e in self.entries:
            if e.router == router and e.mode == mode and e.ttl == ttl:
                if not e.covers(revision):
                    return e, REVISION_NOT_COVERED
                return e, (NO_POLICY if not e.maps() else MAPPED)
        return None, NO_ENTRY


def load(catalog: Path | None, routers_dir: Path | None = None) -> Table:
    """The entries of `<catalog>/routers/*.yaml` (or of `routers_dir`, a candidate table for an
    experiment); none when there is no such directory. A file that is not a RouterMapping, or does not
    parse, is a problem listed on the table and is not used."""
    t = Table()
    d = Path(routers_dir) if routers_dir else (Path(catalog) / "routers" if catalog else None)
    if d is None or not d.is_dir():
        return t
    for f in sorted(d.glob("*.yaml")):
        try:
            doc = yaml.safe_load(f.read_text())
        except yaml.YAMLError:
            t.problems.append(f"{f.name}: not YAML")
            continue
        if not isinstance(doc, dict) or doc.get("kind") != "RouterMapping":
            t.problems.append(f"{f.name}: not a RouterMapping")
            continue
        ttl = doc.get("session_affinity_ttl_s")
        t.entries.append(Entry(
            name=f.stem, router=str(doc.get("router")), mode=str(doc.get("mode")),
            ttl=ttl if isinstance(ttl, int) and not isinstance(ttl, bool) else None, policy=str(doc.get("policy")),
            revisions=[r for r in (doc.get("revisions") or []) if isinstance(r, str) and HEX40.match(r)],
            reason=str(doc.get("reason") or "").strip(),
            difference=[d for d in (doc.get("difference") or []) if isinstance(d, dict)],
            bound=doc.get("bound") if isinstance(doc.get("bound"), dict) else None,
            evidence=list(doc.get("evidence") or [])))
    return t


def evidence_text(e: Entry) -> str:
    """The entry's evidence as one line: each citation `repository@commit:path:lines`."""
    out = []
    for c in e.evidence:
        if isinstance(c, dict):
            out.append(f"{c.get('repository')}@{c.get('commit')}:{c.get('path')}:{c.get('lines')}")
    return "; ".join(out) or e.reason


def matched_ratios(e: Entry, *, workload: str | None, conc: int, model: str, hardware: str, shape: str) -> list[dict]:
    """The entry's bound ratios whose regime holds the point: its workload kind, a concurrency in the
    regime's range, the point's catalog model and hardware part, and its pool shape (`<n>P<m>D`)."""
    out = []
    for r in ((e.bound or {}).get("ratios") or []):
        g = r.get("regime") or {}
        if workload is None or g.get("workload") != workload or g.get("model") != model or g.get("hardware") != hardware:
            continue
        lo, hi = g.get("concurrency_min"), g.get("concurrency_max")
        if not (isinstance(lo, int) and isinstance(hi, int) and lo <= conc <= hi) or shape not in (g.get("shapes") or []):
            continue
        out.append({"metric": r.get("metric"), "against": list(r.get("against") or []), "max_ratio": r.get("max_ratio")})
    return out


def substitution(e: Entry, router: str, revision: str, matched: list[dict], *, assumed: bool = False) -> dict:
    """The router_differs substitution of a mapped entry whose bound covers the point: the router, entry, policy,
    evidence and build, the entry's difference statements (aspect and text) and its bound, as it states them."""
    detail = f"the run's {router} router ran mode {e.mode}; BLIS ran llm-d's {e.policy} policy"
    if assumed:
        detail += (f"; the run records its router build as a wheel version, not a commit, and the build {revision} "
                   f"was ASSUMED for this experiment")
    return {"kind": "router_differs", "subject": router, "entry": e.name, "policy": e.policy,
            "evidence": evidence_text(e), "revision": revision,
            "difference": [{"aspect": d.get("aspect"), "text": d.get("text")} for d in e.difference],
            "bound": e.bound, "detail": detail}


def bound_wide(matched: list[dict]) -> bool:
    return any(isinstance(m.get("max_ratio"), (int, float)) and m["max_ratio"] > WIDE_RATIO for m in matched)
