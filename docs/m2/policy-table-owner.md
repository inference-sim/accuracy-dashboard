# Who owns the router policies

[Contents](#contents)

## Contents

1. [The rule](#the-rule)
2. [What the owner states, what the dashboard still writes itself](#what-the-owner-states-what-the-dashboard-still-writes-itself)
3. [The mechanical check](#the-mechanical-check)
4. [What is missing in the owner](#what-is-missing-in-the-owner)

## The rule

A router policy (`round-robin`, `random-picker`, `least-active-requests`, `default`) is a composition of llm-d's router
plugins. The substrate's router table names the policy an entry maps a router to (`routertable.Policies()` in
`contracts/spec/routertable/routertable.go` of blis-substrate), so the table, and not the dashboard, says what each
policy is. The dashboard selects the policy the table names and writes the endpoint-picker configuration BLIS runs
(`orchestrator/ingest/pd.py`, `epp_config`); it must not define a different policy under the owner's name (design X7).

## What the owner states, what the dashboard still writes itself

| Part of the configuration | Stated by the owner | Written by the dashboard |
|---|---|---|
| The list of policy names | yes (`Policies()`, closed) | no |
| The plugin types of a policy (producer, scorers, picker) | yes, as one text per policy | from the text's meaning |
| A scorer's weight | only for `default` (2, 2, 3) | `active-request-scorer` weight 1 |
| The picker | yes | from the text |
| The prefill and decode filters, `disagg-profile-handler`, `always-disagg-pd-decider` | no | yes |
| The producers' parameters (`approx-prefix-cache-producer`: 16384 tokens, 31250 entries per server) | no | yes |
| Which file of llm-d's router defines each policy | yes (`Sources`) | no |

## The mechanical check

`orchestrator/ingest/test_pd_policy_owner.py` reads `Policies()` from a substrate checkout (`BLIS_SUBSTRATE_ROUTER_BOUNDS`;
the `simulator` job of `checks` fetches the pinned commit) and fails when the configuration the dashboard writes for a
policy differs from what the owner states: a policy the dashboard cannot write, a scorer the owner does not name, a plugin
the owner names that is missing, a different weight, or a different picker. Changing the weight of one scorer in `pd.py`
makes it fail. Without a checkout it is skipped with the reason.

## What is missing in the owner

The owner's interface carries the composition as a sentence, not as a configuration. For the dashboard to select and not
write, the owner should publish, for each policy, the complete endpoint-picker configuration it runs: every plugin with its
parameters, the scorer weights, the picker, and for a prefill/decode deployment the filters, the profile handler and the
decider. The natural place is the substrate's router catalog (`catalog/routers/`, beside the entries that name the
policies), generated from llm-d's router fork at the pinned commit that `Sources` already cites, with a check that fails
when the fork changes. The dashboard would then copy a file, and `epp_config` would be removed. Until the owner publishes
it, the filters, the decider and the parameters are the dashboard's copy and are not checked.
