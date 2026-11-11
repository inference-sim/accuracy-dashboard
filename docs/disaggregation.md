# Disaggregated serving and routers

Contents: [What a disaggregated point is](#what-a-disaggregated-point-is) · [How BLIS expresses it](#how-blis-expresses-it) · [What the harness does](#what-the-harness-does) · [Named refusals](#named-refusals) · [Where the pools' engine arguments come from](#where-the-pools-engine-arguments-come-from) · [Routers and the router substitution](#routers-and-the-router-substitution) · [What it shows and what it does not](#what-it-shows-and-what-it-does-not) · [Reproducing](#reproducing)

## What a disaggregated point is

In prefill/decode (P/D) serving the prompt is processed by one pool of engines and the generation by another, with the KV cache moved between them by a connector (NIXL, Mooncake and others), usually behind a router. An InferenceX row records this as `disagg = true` (or `is_multinode`), the number of workers of each pool, the tensor, expert and data parallelism of each pool, the number of GPUs of each pool, and in some rows the router's name. The row does not record the connector, any engine cap (`max_num_batched_tokens`, `max_num_seqs`), the router's mode or the placement. Those are in the server log, which for a P/D run is one worker's and is usually gone, or in the recipe the run launched from.

## How BLIS expresses it

The substrate's Deployment document has `pools`, each with a role (`colocated`, `prefill`, `decode`), a node count, a parallelism layout and its own engine settings, and a `pd_transfer` block naming the connector. The router is a separate part of the scenario, and the number of instances of each pool are flags of `blis replay` (`--prefill-instances`, `--decode-instances`, `--num-instances`); the pool's node count only bounds them. The reference pages are the substrate's, at the pinned commit: [Deployment](https://github.com/inference-sim/blis-substrate/blob/0182c0ef42b08ef5a0b196b3e413c21c16b6d28d/docs/contracts/reference/deployment.md), [Connectors](https://github.com/inference-sim/blis-substrate/blob/0182c0ef42b08ef5a0b196b3e413c21c16b6d28d/docs/contracts/reference/connectors.md), [Routing](https://github.com/inference-sim/blis-substrate/blob/0182c0ef42b08ef5a0b196b3e413c21c16b6d28d/docs/contracts/reference/routing.md).

## What the harness does

A row with `disagg` is scored by `score.score_pd` (`orchestrator/ingest/pd.py`, `pd_recipe.py`, `router_table.py`):

1. **Shape.** The row's two pools are read (workers, GPUs per worker, tensor and expert parallel size, DP attention). A pool on DP attention runs data-parallel size above one; the row spells it as `tp` equal to the pool's GPUs, and the recipe's `data-parallel-size` decides where it states one. A shape the stack cannot run is refused by name (next section) before anything is simulated.
2. **Recipe.** The recipe the run launched from is found at the run's commit by the pull and kept with the point (below). Its absence is a named `value_not_recorded` reason.
3. **Two pools.** Each pool's recipe arguments are decided by the engine's field list like any recorded setting (`settings.decide`), and written to that pool's engine block: its own `max_num_batched_tokens`, KV dtype, prefix caching, cudagraph size. The pool's role is `prefill` or `decode`, its node count is the recipe's (never fewer than hold its workers), `pd_transfer.connector` is the recipe's `kv-transfer-config` connector (NIXL), and the cluster states a fabric class and the registry's fabric coefficient (`cost-model-fabric`), because two pools never share a node in BLIS.
4. **Router.** The endpoint picker file is the llm-d policy the router table maps the run's router to (below); with none, the point is `router_unsupported`, named by the outcome, and BLIS is not asked.
5. **Replay.** The single-turn replay of [the scoring pipeline](scoring-pipeline.md), with the instance counts as flags. TTFT and TPOT are the client's means over the Result's request rows.

Facets of a scored P/D point say `serving: disaggregated`, and the tables' *serving* split ([reading the table](before-after.md)) shows it apart from the aggregated points.

## Named refusals

A P/D row the stack cannot run is G5 `topology_unsupported` with the part of the layout as the subject. The code stays the closed list's (design §11.4); the subject says whether the gap is the writer's or the engine's, and the coverage tables count each subject apart ([coverage accounting](coverage-accounting.md)).

| Subject | Meaning | What removes it |
|---|---|---|
| `pd_pool_data_parallel` | a pool runs data-parallel size above 1 | blis-vllm#47 (M3): the engine accepts a KV transfer with data parallelism |
| `pd_unequal_data_parallel` | the two pools differ in data-parallel size (DEP prefill with TEP decode, or the reverse) | inference-sim#1952 (M3): the placement allows pools of different data-parallel size |
| `pd_pool_not_recorded` | the row records a pool with no workers or GPUs | nothing: the row does not describe a P/D run |
| `pd_agentic` | an agentic replay of a P/D deployment | the agentic replay for two pools and the router's session affinity (accuracy-dashboard#64, M3) |

A row that is both (a DEP pool beside a TEP pool) carries both subjects. Design §11.4 says `topology_unsupported` is "cleared when the harness can write that topology"; for the first two the harness can write it and the engine refuses it, so the subject names the engine issue, and the code stays so that the closed list does not grow.

## Where the pools' engine arguments come from

The server log of a P/D run is one worker's, and the API serves none for most rows (404 or 413). The recipe the run launched from states each pool's arguments, so the pull recovers it (`pd_recipe.py`):

1. The InferenceX master configuration at the run's commit lists, per model, runner and precision, the search-space items the sweep ran: the concurrencies, each pool's workers, tensor and expert parallel size and DP-attention flag, and the recipe (`CONFIG_FILE=`). The row must be **exactly one** such item (`no_master_entry` or `ambiguous` otherwise).
2. The runner's launch script overlays InferenceX's own recipes onto the srt-slurm checkout (`cp -rT SRC DST`). The file is the source of the overlay that holds the recipe's path, else the same path in InferenceX's tree. A path in neither came from the srt-slurm repository's own, unpinned branch (`not_in_tree`).
3. The recipe is checked against the row (workers, GPUs per worker, sequence lengths, concurrency, precision); a disagreement is a conflict and nothing is recovered.

The point names the recovery (`estimated`, subject `engine.prefill.recipe` and `engine.decode.recipe`): recipe path, commit, and the fields it states. Only fields the recipe states are written; a tensor, pipeline or data-parallel size it leaves at vLLM's default is written only where the pool's GPUs equal their product. A recipe is what the launcher was told, which is not proof of what ran; the substitution says so. Design §11.3 has no recipe clause among its G2 conditions; the substitution rests on its clause "a recorded value was missing and replaced" (the rule lives in `score.py` and `pd.py`, and a dedicated kind needs a design change).

The recipe's benchmark is srt-slurm's `sa-bench`, not InferenceX's client. Every P/D point names `benchmark_client` ([comparability](comparability.md)).

## Routers and the router substitution

BLIS hosts one router: llm-d's. A run measured behind another (Dynamo's frontend, TileRT's PD router, vLLM's router) is G5 `router_unsupported` unless the router table maps it; it is never scored as if llm-d had routed it (design §11.4, X4).

The router table is the substrate's `catalog/routers`: one entry per router, mode and session-affinity setting, each with a policy (or `none`: no llm-d policy is close enough) and the evidence for the match. The format and the validator's rules are the substrate's page, [Router table](https://github.com/inference-sim/blis-substrate/blob/0182c0ef42b08ef5a0b196b3e413c21c16b6d28d/docs/contracts/reference/router-table.md); this repository does not copy them.

The dashboard reads the table (`router_table.py`) for the catalog it is given, and asks it what the substrate's `Resolve` asks: the router (`dynamo`), its mode (the run's recipe sets it in the `frontend` block; a recipe that sets none ran the frontend's default, `round-robin`, and the point says so), the session-affinity time to live, and the router **build**, a full commit that the entry lists in `revisions`. The answer is one of five outcomes:

| Outcome | Point |
|---|---|
| `mapped`, and the entry's bound has a ratio whose regime holds the point | G2 `router_differs` |
| `mapped`, and no ratio's regime holds the point (`no_bound_for_regime`) | G5 `router_unsupported:<router>:no_bound_for_regime` |
| `no_policy` (the entry says no llm-d policy is close enough) | G5, subject `...:no_policy` |
| `revision_not_covered` (the entry does not list the run's build, or the run records none) | G5, subject `...:revision_not_covered` |
| `no_entry` (nothing has the router, mode and affinity) | G5, subject `...:no_entry` |

A regime holds a point when all of these are the regime's, exactly: the workload kind of its request lengths (1024/1024 `balanced`, 8192/16 `prefill-bound`, 256/2048 `decode-bound`; any other length has no kind), its client count (one of the regime's `concurrencies`, the counts the sweep ran: a count between two of them is not covered and nothing is interpolated), its catalog model, its hardware part, the engine release, the cluster fabric the run recorded (an assumed class is not a recorded one, so such a point is not covered), the per-instance parallelism of each pool (tensor, pipeline and data parallel size, expert parallelism), and its pool shape (`<n>P<m>D`: workers of each pool). There is no cutoff on the ratios: a mapped point whose regime has a bound is G2 whatever the ratios say, carries the entry's policy, build, difference statements (`aspect` and `text`) and bound as it states them, and the fidelity record's `router` block lists the matched ratios and a `bound_wide` flag when any exceeds 1.25. A reader decides from those; the grade is G2 either way.

**The run's router build is a gap.** The entries list commits. Every recipe read pins Dynamo by a wheel or a version (`1.2.0.dev20260526`, `1.3.0.dev20260713`), which maps to no commit in any source the dashboard reads, so no recipe gives a build and every Dynamo point is `revision_not_covered` until the build is recorded or the table lists wheel versions. An experiment can assume one (`cli.py score --assume-router-revision COMMIT`: the point says the build was assumed, and the run is experimental). With it and the substrate's layer 12 entries (`--router-table`), the points whose regime has a bound score; the others name `no_bound_for_regime`.

At the audited substrate (layer 10) the table's only entry is `dynamo-round-robin` with policy `none`, so **every Dynamo point is `router_unsupported` today**, and the dashboard's published coverage of Dynamo P/D points is zero. The entries with a policy, a difference and a bound are the substrate's layer 12.

What Dynamo did in the runs is in [the router evidence](m2/dynamo-router-evidence.md): the single-turn recipes set no router mode, so Dynamo's default, `round-robin`; the agentic recipes set `kv` or `least-loaded` with a session-affinity time to live. The mode is the recipe's, not the framework label's.

## What it shows and what it does not

[P/D coverage](m2/pd-coverage.md) has the counts, the accuracy on train and validation points, and the limits. In short: the TPOT of a dp-free P/D point is close; the TTFT is close at low load and far where the prefill pool saturates; no figure is a ranking result; TTFT's definition under Dynamo, the handoff's transport and price, and the router's behaviour are assumptions named on the point or listed there.

## Reproducing

[P/D coverage](m2/pd-coverage.md), "How to reproduce", has the commands and pins. The checks: `python3 -m pytest -q orchestrator/ingest/test_pd.py orchestrator/ingest/test_engines.py orchestrator/ingest/test_server_log.py`.
