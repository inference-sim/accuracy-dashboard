# Who owns the router policies

[Contents](#contents)

## Contents

1. [The rule](#the-rule)
2. [How a point gets its file](#how-a-point-gets-its-file)
3. [The check](#the-check)
4. [State of the router's index](#state-of-the-routers-index)

## The rule

A router policy is a configuration of llm-d's router. The substrate's router table names the policy an entry maps a router to; the
router (llm-d's router fork, at a pinned commit) publishes the endpoint-picker file of each policy and an index of them. The
dashboard holds no policy table and writes no configuration: it selects the policy the table names and passes the router's file to
the simulator unchanged (design X1, X7).

## How a point gets its file

`score --router-checkout DIR` names the router checkout. `pd.epp_file(policy, DIR, form)` reads the checkout's index
(`reference-configs/policies.json`, `pd.INDEX_PATH`) and returns the bytes of the policy's file for the form asked, which the
prefill/decode writer takes as `"pd"` (`round-robin-pd.yaml` and the like); they are copied into the point's scenario directory under
`pd-<policy>.epp.yaml` byte for byte. A policy the index does not list is G5
`router_unsupported:<router>:policy_config_not_published:<policy>`; a policy listed without the form needed (`default` has no prefill/decode
form) is `...:policy_form_missing:<policy>:pd`; no checkout given is `...:router_checkout_not_given`; an index that is missing or names a file
outside the checkout is `router_index_missing` or `router_index_unreadable`. The simulator is not asked in any of these cases.

## The check

`orchestrator/ingest/test_router_configs.py` fails when a policy the router table names has no prefill/decode file in the router's index.
Removing any policy from a fixture index makes it fail; with `BLIS_ROUTER_CHECKOUT` and `BLIS_SUBSTRATE_ROUTER_BOUNDS` set it runs against
the real router and table (the `simulator` job of `checks` fetches the router at the pinned commit).

## State of the router's index

The router fork publishes the files and the index at commit `98c38c04de494e4e64fe23c4532074c6df95a898` (branch `m2/3-host-guide-plugins`, pull request 8 of
inference-sim/llm-d-router), pinned as `router_sha` in `.github/workflows/checks.yml`. The index records, per policy, the files of its
colocated and prefill/decode forms, a knob list (the file's value or "not stated", the router's default, the source line) and that rotation
is not strict per request for any policy; the dashboard reads only the files. The scored prefill/decode runs in `docs/m2/` were made before
this change (the dashboard then rendered the file itself) and are scored again at the final pins.
