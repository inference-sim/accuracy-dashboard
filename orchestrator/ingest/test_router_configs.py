"""The router publishes an endpoint-picker file for every policy the router table names.

The dashboard holds no policy table. The substrate's router table names the policy each Dynamo mode maps to; the router (llm-d's
router fork at a pinned commit) publishes the file of each policy and an index of them. This check fails when a policy the table
names has no file in the router's index (a policy removed from the index, or a table entry for a policy the router does not
publish). Run with BLIS_ROUTER_CHECKOUT (the router at its pinned commit) and BLIS_SUBSTRATE_ROUTER_BOUNDS (the substrate
checkout whose catalog holds the table).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pd as pdm  # noqa: E402
import router_table as rt  # noqa: E402
import test_pd as P  # noqa: E402


def unpublished(router: Path, table_policies: set[str]) -> list[str]:
    """The policies the table names that the router's index does not carry in the prefill/decode form the dashboard's
    writer passes (a policy missing, or listed with no pd file)."""
    index = pdm.router_index(router)
    return sorted(p for p in table_policies if p not in index or index[p]["pd"] is None)


def table_policies(substrate: Path) -> set[str]:
    return {e.policy for e in rt.load(Path(substrate) / "catalog").entries if e.policy != "none"}


def test_a_policy_removed_from_the_routers_index_fails_the_drift_check(tmp_path):
    named = {p for p in P.POLICIES if p != "default"}          # the policies a table maps a P/D deployment to
    assert unpublished(P.router_checkout(tmp_path / "a"), named) == []
    for gone in sorted(named):
        d = P.router_checkout(tmp_path / gone, tuple(p for p in P.POLICIES if p != gone))
        assert unpublished(d, named) == [gone]
    assert unpublished(P.router_checkout(tmp_path / "d"), P.POLICIES) == ["default"]      # an entry mapped to default has no P/D file


ROUTER, SUBSTRATE = os.environ.get("BLIS_ROUTER_CHECKOUT"), os.environ.get("BLIS_SUBSTRATE_ROUTER_BOUNDS")


@pytest.mark.skipif(not (ROUTER and SUBSTRATE), reason="BLIS_ROUTER_CHECKOUT and BLIS_SUBSTRATE_ROUTER_BOUNDS are not set")
def test_the_routers_index_carries_every_policy_the_table_names():
    named = table_policies(Path(SUBSTRATE))
    assert named, "the table names no policy"
    assert unpublished(Path(ROUTER), named) == []
