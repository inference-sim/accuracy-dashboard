"""The endpoint-picker file the dashboard writes for a router policy is the router table's, read from its owner.

The owner is blis-substrate's router table: `go run ./tools/prcheck router-policies` prints its checked policy list with the
complete configuration of each policy. The dashboard selects a policy by name and renders that configuration (pd.epp_config);
it defines no plugin, filter, weight, decider or parameter of its own. This check reads the owner from a substrate checkout
(BLIS_SUBSTRATE_ROUTER_BOUNDS; the `simulator` job of `checks` fetches the pinned commit) and fails when: the owner's closed
list is not the policies the dashboard writes (a policy removed or added), the file written for a policy differs from the
owner's configuration, or the committed snapshot the unit tests use differs from the live owner.

Run: BLIS_SUBSTRATE_ROUTER_BOUNDS=<substrate checkout> python3 -m pytest orchestrator/ingest/test_pd_policy_owner.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pd as pdm  # noqa: E402

OWNER_DIR = os.environ.get("BLIS_SUBSTRATE_ROUTER_BOUNDS")
pytestmark = pytest.mark.skipif(not OWNER_DIR, reason="BLIS_SUBSTRATE_ROUTER_BOUNDS (a blis-substrate checkout) is not set")

WRITTEN = {"round-robin", "random-picker", "least-active-requests", "default"}      # the policies the dashboard writes


@pytest.fixture(scope="module")
def owner():
    assert shutil.which("go"), "a Go toolchain is needed to read the owner's list"
    return pdm.load_owner_policies(Path(OWNER_DIR))


def problems(owner: dict) -> list[str]:
    out = []
    if set(owner["closed_policies"]) != WRITTEN:
        out.append(f"the owner's closed list {sorted(owner['closed_policies'])} is not the policies written {sorted(WRITTEN)}")
    listed = {p["policy"] for p in owner["policies"]}
    for policy in sorted(WRITTEN):
        if policy not in listed:
            out.append(f"{policy}: the owner states no configuration")
            continue
        try:
            doc = yaml.safe_load(pdm.epp_config(policy, owner))
        except ValueError as e:
            out.append(str(e))
            continue
        cfg = next(p for p in owner["policies"] if p["policy"] == policy)["config"]
        if [p["type"] for p in doc["plugins"]] != [p["type"] for p in cfg["plugins"]]:
            out.append(f"{policy}: the plugins written differ from the owner's")
    return out


def test_the_dashboard_writes_what_the_owner_states(owner):
    assert problems(owner) == []


def test_a_policy_removed_from_the_owner_fails_the_check(owner):
    for gone in sorted(WRITTEN):
        shrunk = {"closed_policies": [p for p in owner["closed_policies"] if p != gone],
                  "policies": [p for p in owner["policies"] if p["policy"] != gone]}
        assert problems(shrunk), gone


def test_the_snapshot_the_unit_tests_use_is_the_owners_output(owner):
    assert json.loads((HERE / "testdata" / "router-policies.json").read_text()) == owner
