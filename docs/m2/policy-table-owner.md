# Who owns the router policies

[Contents](#contents)

## Contents

1. [The rule](#the-rule)
2. [How the dashboard reads the owner](#how-the-dashboard-reads-the-owner)
3. [What the owner states, and what it leaves to the deployment](#what-the-owner-states-and-what-it-leaves-to-the-deployment)
4. [The mechanical check](#the-mechanical-check)

## The rule

A router policy (`round-robin`, `random-picker`, `least-active-requests`, `default`) is a composition of llm-d's router plugins.
The substrate's router table names the policy an entry maps a router to, and states the complete endpoint-picker configuration of
each policy (`routertable.Policies()` in blis-substrate). The dashboard selects the policy the table names and renders that
configuration (`orchestrator/ingest/pd.py`, `epp_config`); it defines no plugin, filter, weight, decider or parameter of its own
(design X7).

## How the dashboard reads the owner

`go run ./tools/prcheck router-policies`, run in the blis-substrate checkout the catalog sits in, prints
`{"closed_policies": [...], "policies": [...]}` and exits non-zero, naming the problems, when the owner's list fails its own check.
`pd.load_owner_policies` runs it the first time a prefill/decode point needs a file; `epp_config(policy, owner)` renders the
configuration of the named policy and refuses a policy the owner does not list. The unit tests use a snapshot of the owner's output
(`orchestrator/ingest/testdata/router-policies.json`), which the owner check compares with the live owner.

## What the owner states, and what it leaves to the deployment

Each parameter and weight carries an origin: `source` (the router's code or README states it), `sample` (the router's own sample
deployment sets it; the router's default is another value, named in the owner's claim: `maxPrefixTokensToMatch` is 16384 in the
sample, 131072 by default), or `not-stated` (the router's source does not state it for the policy; the value is what BLIS's
prefill/decode deployments use). The dashboard renders every value. A `not-stated` value, today the choice of the prefill decider
(`always-disagg-pd-decider`) for every policy, is a choice of the deployment and not the router's; it is reported as that here and
not as the router's behaviour.

## The mechanical check

`orchestrator/ingest/test_pd_policy_owner.py` reads the owner from the checkout (`BLIS_SUBSTRATE_ROUTER_BOUNDS`; the `simulator` job
of `checks` fetches the pinned commit) and fails when the owner's closed list is not the four policies the dashboard writes (a policy
removed or added), when the file written for a policy differs from the owner's configuration, or when the snapshot the unit tests use
differs from the live owner. A test removes each policy from the owner's output in turn and requires the check to fail.
