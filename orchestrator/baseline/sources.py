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
reports it; the dashboard does not pick one silently. It scores and reports every configiq unit as D9 says, and prints
the disagreement until row 26's partition version replaces the cut-points. The disagreement is a fact about a file; it
is never resolved here by guessing a role, which needs the partition secret.
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
    CONFIGIQ: "every unit (D9), less the units the partition-prep report leaves out; none is fit, selected, validated or held",
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
                    "text": f"ledger.yaml (partition version {version}) gives configiq the roles {_roles(cq)}; D9 (v4.2.0) makes "
                            f"every configiq unit an anchor unit (anchor 0 to 99). Row 26's new partition version changes it "
                            f"(a maintainer step). Until then the dashboard scores and reports every configiq unit as an anchor "
                            f"and does not use ledger.yaml's draw for it"})
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
