"""Which units each ledger source draws accuracy from (design D9, §10.2; plan Table 1.4 and rows 16, 17 and 26).

The dashboard publishes accuracy on anchor units only. D9 sets the rule per source:

  inferencex    held and anchor shares. Anchor units are the published anchor list; held units only judge pre-registered
                changes and return aggregates. vLLM and SGLang are two lanes of this one source.
  configiq      anchor-only: EVERY unit is an anchor unit, never fit, selected, validated or held. The units a
                partition-prep report found read under a training role are left out (rules.configiq.left_out of the next
                ledger.yaml), not made anchors.
  every other   (vllm-ci-perf, sglang-nightly, sglang-traces) training roles only: never accuracy. The dashboard may
                show how the fitted model reproduces them, labelled a training diagnostic.

`check_cut_points` reads a ledger.yaml and returns every way it disagrees with that rule. Today's ledger.yaml
(partition version 1) still gives configiq InferenceX's cut-points (fit, select, validate, held, anchor), so the check
reports it. The plan (blis-design m32/plan.html, Terms, 1.4, 3A.6 and 3C) is the rule where this repository, ledger.yaml
or an earlier finding disagrees: configiq is anchor-only. The dashboard scores and reports every configiq unit as an
anchor unit and prints the disagreement until row 26's partition version replaces the cut-points. It never reads the
draw ledger.yaml gives configiq, and `configiq_in_training` fails when a published fit, select or validate list holds a
configiq unit (a unit read that way is left out of the anchors, never made one).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

INFERENCEX, CONFIGIQ = "inferencex", "configiq"
TRAINING_ONLY = ("sglang-nightly", "sglang-traces", "vllm-ci-perf")
TRAINING_ROLES = ("fit", "select", "validate")
ANCHOR_SOURCES = (CONFIGIQ, INFERENCEX)
LANES = ("sglang", "vllm")           # the engines whose InferenceX units are scored; other frameworks are out of scope

ANCHOR_RULE = {
    INFERENCEX: "the published anchor list (role anchor); held units judge pre-registered changes and are never reported",
    CONFIGIQ: "every unit (plan: anchor-only), less the units the D2 join found read under a training role; none is fit, "
              "selected, validated, held or withheld as a test split",
}
TRAINING_LABEL = "training only: never accuracy; a diagnostic of the fit, labelled as such"


class SourcesError(ValueError):
    pass


def _roles(rule: dict) -> list[str]:
    return [c["role"] for c in rule.get("cut_points") or []]


def _covers_all(rule: dict, role: str) -> bool:
    cps = rule.get("cut_points") or []
    return len(cps) == 1 and cps[0]["role"] == role and cps[0]["from"] == 0 and cps[0]["to"] == 99


def check_cut_points(doc: dict) -> list[dict]:
    """The disagreements of a parsed ledger.yaml with D9, each {"source", "code", "text"}. Empty when it agrees."""
    if not isinstance(doc, dict) or doc.get("kind") != "Ledger" or not isinstance(doc.get("rules"), dict):
        raise SourcesError("not a Ledger document (kind: Ledger with rules)")
    rules, out = doc["rules"], []
    version = doc.get("partition_version")
    held = sorted(s for s, r in rules.items() if "held" in _roles(r))
    anchor = sorted(s for s, r in rules.items() if "anchor" in _roles(r))
    for s in held:
        if s != INFERENCEX:
            out.append({"source": s, "code": "held_outside_inferencex",
                        "text": f"{s} has a held cut-point; only InferenceX may (D9)"})
    if INFERENCEX not in held:
        out.append({"source": INFERENCEX, "code": "inferencex_not_held", "text": "InferenceX has no held cut-point (D9)"})
    for s in anchor:
        if s not in ANCHOR_SOURCES:
            out.append({"source": s, "code": "anchor_outside_anchor_sources",
                        "text": f"{s} has an anchor cut-point; only InferenceX and configiq may (D9)"})
    cq = rules.get(CONFIGIQ)
    if cq is None:
        out.append({"source": CONFIGIQ, "code": "configiq_no_rule", "text": "the ledger has no rule for configiq"})
    elif not _covers_all(cq, "anchor"):
        out.append({"source": CONFIGIQ, "code": "configiq_cut_points_not_anchor_only",
                    "text": f"the plan is the rule: configiq is anchor-only, every unit an anchor unit (anchor 0 to 99), never fit, "
                            f"selected, validated or held. ledger.yaml (partition version {version}) gives configiq the roles "
                            f"{_roles(cq)} and is wrong to that extent; row 26's new partition version corrects it (a maintainer "
                            f"step). Until then the dashboard scores and reports every configiq unit as an anchor and does not "
                            f"use ledger.yaml's draw for it"})
    for s in TRAINING_ONLY:
        r = rules.get(s)
        if r is None:
            out.append({"source": s, "code": "training_source_no_rule", "text": f"the ledger has no rule for {s}"})
        elif set(_roles(r)) - set(TRAINING_ROLES):
            out.append({"source": s, "code": "training_source_not_training_only",
                        "text": f"{s} has the roles {_roles(r)}; a training-only source draws {list(TRAINING_ROLES)} only (D9)"})
    return out


def configiq_left_out(doc: dict) -> set[str]:
    """The unit ids ledger.yaml leaves out of configiq's anchors (rules.configiq.left_out); none before row 26."""
    rule = (doc.get("rules") or {}).get(CONFIGIQ) or {}
    ids = rule.get("left_out") or []
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise SourcesError("rules.configiq.left_out is not a list of unit ids")
    return set(ids)


def configiq_anchor_ids(unit_ids, doc: dict | None = None) -> list[str]:
    """The configiq units to score: every ledger id minus the left-out list (rules.configiq.left_out of a ledger.yaml, none
    before row 26). Never read from anchor.yaml, which holds no configiq id until row 26's release. A left-out id the ledger
    does not hold is refused."""
    ids = set(unit_ids)
    out = configiq_left_out(doc) if doc else set()
    gone = sorted(out - ids)
    if gone:
        raise SourcesError(f"rules.configiq.left_out names {len(gone)} units the configiq ledger does not hold, "
                           f"the first {gone[0]}")
    return sorted(ids - out)


def configiq_in_training(published, configiq_ids) -> list[dict]:
    """Every configiq id found in a published list of a training role: [{"file", "role", "units": [ids]}]. `published` is a
    directory of PublishedUnits files (fit.yaml, select.yaml, validate.yaml, ...) or one file; a list of any other role is
    not read. An empty result is what D9 needs; a hit is a unit that was read under a training role, and the answer is to
    leave it out of the anchors (rules.configiq.left_out), never to make it one."""
    import yaml
    p, ids, hits = Path(published), set(configiq_ids), []
    for f in ([p] if p.is_file() else sorted(p.glob("*.yaml"))):
        doc = yaml.safe_load(f.read_text())
        if not isinstance(doc, dict) or doc.get("kind") != "PublishedUnits" or doc.get("role") not in TRAINING_ROLES:
            continue
        found = sorted(ids & set(doc.get("units") or []))
        if found:
            hits.append({"file": f.name, "role": doc["role"], "units": found})
    return hits


def read_ledger_yaml(path: Path) -> dict:
    import yaml
    return yaml.safe_load(Path(path).read_text())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--ledger-yaml", required=True, type=Path, help="blis-substrate's catalog/ledger/ledger.yaml")
    ap.add_argument("--strict", action="store_true", help="exit 1 when the file disagrees with D9 (for after row 26)")
    a = ap.parse_args(argv)
    try:
        found = check_cut_points(read_ledger_yaml(a.ledger_yaml))
    except (SourcesError, OSError, ValueError) as e:
        print(f"sources: {e}", file=sys.stderr)
        return 2
    print(json.dumps(found, indent=1, sort_keys=True))
    for d in found:
        print(f"WARNING: {d['source']}: {d['text']}", file=sys.stderr)
    return 1 if (found and a.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
