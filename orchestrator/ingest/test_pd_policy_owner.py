"""The endpoint-picker configuration the dashboard writes for a router policy is the policy its owner defines.

The owner of the policy list and of each policy's composition is blis-substrate's router table
(`routertable.Policies()`: the name, the plugin types and the scorer weights it states). The dashboard selects a
policy by name and writes the configuration file BLIS runs (pd.epp_config); it must not define a different policy
under the owner's name. This check reads the owner's list from a substrate checkout (BLIS_SUBSTRATE_ROUTER_BOUNDS,
the layer the `simulator` job of `checks` fetches) and fails when what the dashboard writes differs from what the
owner states: a policy the dashboard cannot write, a plugin the owner does not name, a plugin the owner names that is
missing, a scorer weight that differs, or a different picker.

What the owner does not state (the filters, the decider, the producers' parameters, a weight it leaves out) is not
checked here; it is a gap in the owner's interface, listed in docs/m2/policy-table-owner.md.

Run: BLIS_SUBSTRATE_ROUTER_BOUNDS=<substrate checkout> python3 -m pytest orchestrator/ingest/test_pd_policy_owner.py
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pd as pdm  # noqa: E402

OWNER = os.environ.get("BLIS_SUBSTRATE_ROUTER_BOUNDS")
GO = Path(OWNER or "x") / "contracts" / "spec" / "routertable" / "routertable.go"
pytestmark = pytest.mark.skipif(not GO.is_file(), reason="BLIS_SUBSTRATE_ROUTER_BOUNDS (a blis-substrate checkout with the router table) is needed")

PICKERS = {"max-score-picker", "random-picker"}


def owner_policies() -> dict[str, dict]:
    """{policy: {"plugins": [type, ...], "weights": {type: weight}}} as `Policies()` states them."""
    src = GO.read_text()
    body = src[src.index("func Policies()"):src.index("func PolicyNames()")]
    consts = dict(re.findall(r"(Policy\w+)\s+Policy\s*=\s*\"([a-z-]+)\"", src))
    out = {}
    for const, text in re.findall(r"\{(Policy\w+),\s*\"([^\"]*)\"", body):
        plugins, weights = [], {}
        for item in (i.strip() for i in text.split(";")):
            if not item or item.startswith("no scorer"):
                continue
            m = re.fullmatch(r"([a-z-]+)(?: \((\d+)\))?", item)
            assert m, f"the owner's composition {text!r} has an item this check cannot read: {item!r}"
            plugins.append(m.group(1))
            if m.group(2):
                weights[m.group(1)] = int(m.group(2))
        out[consts[const]] = {"plugins": plugins, "weights": weights}
    return out


def written(policy: str) -> dict:
    doc = yaml.safe_load(pdm.epp_config(policy))
    types = [p["type"] for p in doc["plugins"]]
    weights, pickers = {}, set()
    for prof in doc["schedulingProfiles"]:
        for ref in prof["plugins"]:
            if ref["pluginRef"] in PICKERS:
                pickers.add(ref["pluginRef"])
            elif "weight" in ref:
                weights.setdefault(ref["pluginRef"], set()).add(ref["weight"])
    return {"types": types, "weights": weights, "pickers": pickers}


def test_the_dashboard_writes_exactly_the_policies_the_owner_offers():
    owned = owner_policies()
    assert owned, "the owner's list could not be read"
    for policy in owned:
        pdm.epp_config(policy)                       # raises for a policy the dashboard cannot write
    # and no policy the owner does not offer is written
    with pytest.raises(ValueError):
        pdm.epp_config("not-a-policy")


def test_each_policy_has_the_owners_plugins_scorers_weights_and_picker():
    for policy, own in owner_policies().items():
        got = written(policy)
        stated_scorers = {p for p in own["plugins"] if p.endswith("-scorer")}
        assert {t for t in got["types"] if t.endswith("-scorer")} == stated_scorers, policy
        for plugin in own["plugins"]:
            assert plugin in got["types"], (policy, plugin)
        for plugin, weight in own["weights"].items():
            assert got["weights"].get(plugin) == {weight}, (policy, plugin)
        assert got["pickers"] == {p for p in own["plugins"] if p in PICKERS}, policy
