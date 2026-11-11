# Disaggregated serving and routers

## What a disaggregated point is

In prefill/decode (P/D) serving the prompt is processed by one pool of engines and the generation by another, with the KV cache moved between them by a connector (NIXL, Mooncake and others), usually behind a router. An InferenceX row records this as `disagg = true` (or `is_multinode`), the number of workers of each pool, the tensor, expert and data parallelism of each pool, the number of GPUs of each pool, and in some rows the router's name.

## How BLIS expresses it

The substrate's Deployment document has `pools`, each with a role (`colocated`, `prefill`, `decode`), a node count, a parallelism layout and its own engine settings, and a `pd_transfer` block naming the connector. The router is a separate part of the scenario. The reference pages are the substrate's, at the pinned commit: [Deployment](https://github.com/inference-sim/blis-substrate/blob/0182c0ef42b08ef5a0b196b3e413c21c16b6d28d/docs/contracts/reference/deployment.md), [Connectors](https://github.com/inference-sim/blis-substrate/blob/0182c0ef42b08ef5a0b196b3e413c21c16b6d28d/docs/contracts/reference/connectors.md), [Routing](https://github.com/inference-sim/blis-substrate/blob/0182c0ef42b08ef5a0b196b3e413c21c16b6d28d/docs/contracts/reference/routing.md). Placement and the NIXL connector for P/D are delivered by inference-sim PR 2 and blis-vllm PR 5; they are not in the pins of the v0.16.0 baseline.

## What the harness does today

The scenario writer states one colocated pool. A disaggregated or multinode row is therefore decided by its topology fields and ends as **G5 `topology_unsupported`**; nothing is simulated. Which rows these are, by class and with the evidence, is in [InferenceX series classes](m2/series-classes.md). In short:

- `vllm-disagg` (74 rows) is all mi355x: out of scope.
- `llmd-vllm` has 5 in-scope rows (gb200). None has a server log in the pull, so the engine settings are unrecorded: they cannot be scored before a pooled scenario writer exists *and* the record is available.
- Plain `vllm` rows that are multinode (kimik3, kimik3.1 on h200, b200, gb200) need two pools too.
- `dynamo-vllm` (612 rows, in scope) runs behind Dynamo's router, below.

A P/D scenario writer (two pools from the row's per-pool fields, the connector and role from a log or launch configuration, a simulator that places the pools) is the next work item after inference-sim PR 2 and blis-vllm PR 5 are pinned. A test that the generated scenario states exactly the recorded topology can use the fake simulator of the scorer's tests, but a faithful run needs the real one. Every table has a *serving* split so a change in P/D modelling shows ([reading the table](before-after.md)); today every scored point is aggregated.

## Routers and the router substitution

BLIS hosts one router: llm-d's. A run measured behind another (Dynamo's frontend, TileRT's PD router, vLLM's router) is G5 `router_unsupported`; it is never scored as if llm-d had routed it (design §11.4, X4).

The maintainer has ruled that a router BLIS does not host may be replaced by an llm-d policy named in a **router table** (design §11.3 as merged: the point is simulated with that policy and names the router the run used, the policy BLIS used and the table's evidence). The table is in the substrate, `catalog/routers`: one entry per router and mode, each with a policy and the evidence for the match, and the point-record kind `router_differs` names the table entry, the llm-d policy BLIS used, and the evidence. The format and the validator's rules are the substrate's page, [Router table](https://github.com/inference-sim/blis-substrate/blob/0182c0ef42b08ef5a0b196b3e413c21c16b6d28d/docs/contracts/reference/router-table.md); this repository does not copy them.

At the audited substrate the table's only entry is `dynamo-round-robin`, with policy `none`: the entry records that no llm-d policy is close enough (the two keep their rotation counters in different places, which decides which worker serves which request), so a Dynamo run **stays `router_unsupported`**, and the dashboard writes no `router_differs` yet. `grade.py` accepts and checks the substitution (the entry's name begins with the router, and the policy is one llm-d offers) for when an entry with a policy exists.

What Dynamo did in the runs is in [the router evidence](m2/dynamo-router-evidence.md): the 496 single-turn dynamo-vllm rows ran recipes that set no router mode, so Dynamo's default, `round-robin`, in every build whose code was read; the agentic recipes set `kv` or `least-loaded` with a session-affinity time to live. The mode is the recipe's, not the framework label's, and it is in no API row or server log, so a substitution keyed by mode needs the recipe.

## Sensitivity

When the router table has an entry with a policy and disaggregated points are scored, the sensitivity of a point's figures to the routing policy (the same scenario under each policy llm-d offers) is the check that the substitution is not decisive. No such result exists yet.
