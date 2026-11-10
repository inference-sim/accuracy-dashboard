# Dynamo router evidence for the dynamo-vllm rows

For the router table of the substrate (`catalog/routers`, point-record kind `router_differs`; blis-substrate #40, #41). This file is evidence only; it writes no table.

Measured 2026-11-10. A `dynamo-vllm` row names a GitHub Actions run in its `run_url`. Each run's `head_sha` pins the InferenceX tree it ran, and that tree's `nvidia-master.yaml` names the recipe files (`CONFIG_FILE=`) the run's configuration used. The recipe's `frontend:` block is where srt-slurm sets the Dynamo frontend and its router flags. A citation below is `repository@commit:path:line`.

## Result for the 496 single-turn rows

- The 496 single-turn `dynamo-vllm` rows (2026-05-19 to 2026-11-08) come from 28 InferenceX runs.
- 223 distinct recipe files were resolved at the run's pinned commit (all under `benchmarks/multi_node/srt-slurm-recipes/vllm/` of InferenceX). **None sets a router mode, a router flag, a session-affinity setting or a `DYN_ROUTER_*` variable.** Each has `frontend:` with `type: dynamo` and `enable_multiple_frontends`, and three of them `num_additional_frontends`; nothing else.
- So these runs used the Dynamo frontend's default router. Dynamo's frontend defaults to `round-robin`: `ai-dynamo/dynamo@33cfa1271c08f1660fc156ab2bc50647a268b87e:components/src/dynamo/frontend/frontend_args.py:604` (`default_router_mode="round-robin"`) and, at tag `v1.2.0`, `components/src/dynamo/frontend/main.py:10` ("Router, defaulting to round-robin. Use --router-mode to switch"). The recipes pin Dynamo `1.2.0.dev20260426` (for example `dynamo: "1.2.0.dev20260426"` in the dsv4 gb200 recipe, line 131) and later dev builds; I read the default at `v1.2.0` and at main, not at each dev build.
- 30 recipe files named by the configurations of 2 runs (commits `6a5a0690` and `97bcbdd9`) could not be fetched: they are `recipes/vllm/minimax-m2.5/...` and `recipes/vllm/minimax-m2.5-gb200/...` of NVIDIA/srt-slurm, which the configuration names with no branch, and which are in neither the InferenceX tree at that commit nor `NVIDIA/srt-slurm@08e6023fee4a15087a2f7b9abc04665c1d47d673` (main). Their router mode is unknown, not assumed. The rows of those runs are marked below.
- "Round-robin" is a statement about a missing flag plus a default, not about a log line: no server log in the pull prints the frontend's router mode (the b300 minimaxm3 log shows the workers only).

## Per run

| Run | Workflow name | InferenceX commit | Rows | Models and chips | Recipes resolved / named | Router setting in resolved recipes | Citation of a recipe's `frontend:` block |
|---|---|---|---|---|---|---|---|
| 25948327237 | Run Sweep - Update DSV4 GB200 MTP 8k/1k vLLM 1p1d-dep8-dep8 recipe | `6ed44ffb7f967c7f345c078ed16dc6fb276f21c6` | 9 | dsv4 gb200 | 9 / 9 | none set (Dynamo default, round-robin) | `SemiAnalysisAI/InferenceX@6ed44ffb7f96:benchmarks/multi_node/srt-slurm-recipes/vllm/deepseek-v4/8k1k/disagg-gb200-high-tpt-megamoe.yaml:49` |
| 26842607912 | Run Sweep - [NV] Add MiniMax-M2.5 FP4 B200 Dynamo vLLM recipes | `00ef06af0527b1ca28bf042ce4a42a3528e1c231` | 42 | minimaxm2.5 b200 | 17 / 17 | none set (Dynamo default, round-robin) | `SemiAnalysisAI/InferenceX@00ef06af0527:benchmarks/multi_node/srt-slurm-recipes/vllm/minimax-m2.5-b200-fp4/1k1k/dep2-1p2d.yaml:24` |
| 26843662304 | Run Sweep - [NV] Add MiniMax-M2.5 FP4 GB200 Dynamo vLLM recipes | `9f1003ecd802ef4382024d5e24f92c585117285b` | 42 | minimaxm2.5 gb200 | 17 / 17 | none set (Dynamo default, round-robin) | `SemiAnalysisAI/InferenceX@9f1003ecd802:benchmarks/multi_node/srt-slurm-recipes/vllm/minimax-m2.5-gb200/1k1k/dep2-1p2d.yaml:25` |
| 26849272767 | Run Sweep - [NV] Add MiniMax-M2.5 FP8 B200 Dynamo vLLM recipes | `c2bc3d9bf9e6f2f813787e9204c34067ac5be51d` | 18 | minimaxm2.5 b200 | 10 / 10 | none set (Dynamo default, round-robin) | `SemiAnalysisAI/InferenceX@c2bc3d9bf9e6:benchmarks/multi_node/srt-slurm-recipes/vllm/minimax-m2.5-b200-fp8/1k1k/dep8.yaml:27` |
| 26857293503 | Run Sweep - [B300][vLLM] Add MiniMax-M2.5 FP4 disagg Dynamo configs | `6a5a06901b41cf772641619931ef8f2517470e03` | 35 | minimaxm2.5 b300 | 0 / 15 | unknown (no recipe fetched) | - |
| 26883183237 | Run Sweep - [NV] Add MiniMax-M2.5 FP4 GB300 Dynamo vLLM recipes | `66b7e04d5977f8e8c5e204b6fcfb97178504ee7f` | 34 | minimaxm2.5 gb300 | 12 / 12 | none set (Dynamo default, round-robin) | `SemiAnalysisAI/InferenceX@66b7e04d5977:benchmarks/multi_node/srt-slurm-recipes/vllm/minimax-m2.5/1k1k/dep2-2p3d-c6144.yaml:25` |
| 26906115049 | Run Sweep - [NV] Add MiniMax-M2.5 FP8 GB200 Dynamo vLLM recipes | `e060d417b3493ba41aa8a352476af02456604bd3` | 30 | minimaxm2.5 gb200 | 26 / 26 | none set (Dynamo default, round-robin) | `SemiAnalysisAI/InferenceX@e060d417b349:benchmarks/multi_node/srt-slurm-recipes/vllm/minimax-m2.5-gb200-fp8/1k1k/disagg-gb200-1p1d-tp4.yaml:24` |
| 26906377482 | Run Sweep - [NV] Add MiniMax-M2.5 FP8 GB300 Dynamo vLLM recipes | `57da6fed191028d1760a4191952ccc2c89f422c0` | 40 | minimaxm2.5 gb300 | 27 / 27 | none set (Dynamo default, round-robin) | `SemiAnalysisAI/InferenceX@57da6fed1910:benchmarks/multi_node/srt-slurm-recipes/vllm/minimax-m2.5/1k1k/dep2-2p3d-c6144.yaml:25` |
| 26962351977 | Run Sweep - [NV] Add MiniMax-M2.5 FP8 B300 Dynamo vLLM recipes | `97bcbdd9a94a99e8aa7e738c7fd4d292584edec0` | 40 | minimaxm2.5 b300 | 12 / 30 | none set (Dynamo default, round-robin); the rest unknown | `SemiAnalysisAI/InferenceX@97bcbdd9a94a:benchmarks/multi_node/srt-slurm-recipes/vllm/minimax-m2.5/1k1k/dep2-2p3d-c6144.yaml:25` |
| 27848011161 | Run Sweep - [NV] Kimi-K2.5 NVFP4 GB300 disagg multinode dynamo-vllm be | `9d1dc9c2cd8f80528c74454e3d23173770bec782` | 17 | kimik2.5 gb300 | 11 / 11 | none set (Dynamo default, round-robin) | `SemiAnalysisAI/InferenceX@9d1dc9c2cd8f:benchmarks/multi_node/srt-slurm-recipes/vllm/kimi-k2.5-fp4/1k1k/disagg-gb300-1p1d-dep4-dep16.yaml:22` |
| 27885061956 | Run Sweep - [NV] Kimi-K2.5 NVFP4 GB200 dynamo-vllm disagg benchmark re | `d54e9e549968cae149ea7dc7e4178fdee51e7709` | 17 | kimik2.5 gb200 | 8 / 8 | none set (Dynamo default, round-robin) | `SemiAnalysisAI/InferenceX@d54e9e549968:benchmarks/multi_node/srt-slurm-recipes/vllm/kimi-k2.5-fp4/1k1k/disagg-gb200-1p1d-dep4-dep16.yaml:22` |
| 28028985088 | Run Sweep - [NV] update B300 disagg recipes (same-repo sweep copy) | `6b9fe1e850671d4b1ef60ddb7d1192c74963672d` | 15 | minimaxm3 b300 | 15 / 15 | none set (Dynamo default, round-robin) | `SemiAnalysisAI/InferenceX@6b9fe1e85067:benchmarks/multi_node/srt-slurm-recipes/vllm/minimax-m3/b300-fp8/1k1k/1p1d-dep2-tep8-1k1k.yaml:22` |
| 28202535361 | Run Sweep - [NV] Refresh Minimax M3 FP8 submission with new recipes fo | `8e59bb77a35a8765e55469ccfdce8f06bdd5fdcc` | 11 | minimaxm3 gb300 | 15 / 15 | none set (Dynamo default, round-robin) | `SemiAnalysisAI/InferenceX@8e59bb77a35a:benchmarks/multi_node/srt-slurm-recipes/vllm/minimax-m3-gb300-fp8/1k1k/1p1d-dep2-dep4-1k1k.yaml:38` |
| 28205303704 | Run Sweep - [NV] initial submission for minimax-m3 fp8 GB200 disagg re | `752562ae07a0179a8a44431ed24c25f1856e3c43` | 10 | minimaxm3 gb200 | 11 / 11 | none set (Dynamo default, round-robin) | `SemiAnalysisAI/InferenceX@752562ae07a0:benchmarks/multi_node/srt-slurm-recipes/vllm/minimax-m3-gb200-fp8/1k1k/1p1d-dep4-dep8-1k1k.yaml:38` |
| 28214046079 | Run Sweep - Add MiniMax-M3 NVFP4 B300 Dynamo vLLM benchmarks | `8602631ba00c7fefd683991258a7d9d9695a466c` | 15 | minimaxm3 b300 | 30 / 30 | none set (Dynamo default, round-robin) | `SemiAnalysisAI/InferenceX@8602631ba00c:benchmarks/multi_node/srt-slurm-recipes/vllm/minimax-m3/b300-fp8/1k1k/1p1d-dep2-tep8-1k1k.yaml:22` |
| 28380189316 | Run Sweep - Bump vLLM version for DSV4 B300 disagg | `127b53037c718bce1911550f7375c99e77ac3391` | 7 | dsv4 b300 | 3 / 3 | none set (Dynamo default, round-robin) | `SemiAnalysisAI/InferenceX@127b53037c71:benchmarks/multi_node/srt-slurm-recipes/vllm/deepseek-v4/8k1k/disagg-b300-high-tpt-megamoe.yaml:36` |
| 28728578034 | Run Sweep - Update DSV4 GB300 Dynamo vLLM Recipes | `db1e794ed577f07f70577f30519f1709d5424b2a` | 6 | dsv4 gb300 | 0 / 0 | unknown (no recipe fetched) | - |
| 30118489668 | Run Sweep - Refresh DeepSeek-V4-Pro GB200 Dynamo vLLM stack / 更新 DeepS | `9dd8cd1b10ab7060a35e7711a2b1e10ef5dcecbc` | 6 | dsv4 gb200 | 0 / 0 | unknown (no recipe fetched) | - |
| 30208342156 | Run Sweep - [NV] minimax-m3-B300-dynamo: use vLLM nightly image | `666f505239e914b98432d3b535145ebeff7346ad` | 16 | minimaxm3 b300 | 0 / 0 | unknown (no recipe fetched) | - |
| 30208358162 | Run Sweep - [NV] minimax-m3-gb200-dynamo: use vLLM nightly image  | `49a611e94305f6d055c62e693474e1eb97509486` | 11 | minimaxm3 gb200 | 0 / 0 | unknown (no recipe fetched) | - |
| 30208366514 | Run Sweep - [NV] minimax-m3-gb300-dynamo: nightly image + 2xDEP8 decod | `fa24e0b0fa37b3553d3105e884c1095d77d8ac43` | 11 | minimaxm3 gb300 | 0 / 0 | unknown (no recipe fetched) | - |
| 30669586535 | Run Sweep - Run Kimi K2.6 NVFP4 Dynamo vLLM on b200-new / 在 b200-new 上 | `fc2609111631afc2363f1133fad5a960e9638845` | 6 | kimik2.6 b200 | 0 / 0 | unknown (no recipe fetched) | - |
| 30828231519 | Run Sweep - feat(minimaxm3-fp4-b300-dynamo-vllm-tp1): bump vLLM nightl | `c561626b06d2fc2000691f132024f8aad203d7bf` | 17 | minimaxm3 b300 | 0 / 0 | unknown (no recipe fetched) | - |
| 30828238642 | Run Sweep - feat(minimaxm3-fp4-b200-dynamo-vllm): bump vLLM nightly to | `f4bf44a8f14e51d008f44604ef28c26233ebca5f` | 9 | minimaxm3 b200 | 0 / 0 | unknown (no recipe fetched) | - |
| 30860526083 | Run Sweep - feat(minimaxm3-fp4-b300-dynamo-vllm-mtp-legacy-dep4): bump | `fa04264f6a3518754e8005f86cccc39c8fdf7b68` | 2 | minimaxm3 b300 | 0 / 0 | unknown (no recipe fetched) | - |
| 30933463657 | Run Sweep - [Klaud Cold] minimaxm3-fp4-b200-dynamo-vllm-mtp: day-zero  | `84ae2160b947e47675fca3e8d7246b3c15cbcc8d` | 17 | minimaxm3 b200 | 0 / 0 | unknown (no recipe fetched) | - |
| 30933638204 | Run Sweep - [Klaud Cold] minimaxm3-fp8-gb300-dynamo-vllm-mtp: day-zero | `1f1b743ae1ea2761062c6464125daebf7e8de78f` | 11 | minimaxm3 gb300 | 0 / 0 | unknown (no recipe fetched) | - |
| 33012183714 | Run Sweep - [Power] Require B200 and B300 multinode telemetry / 强制启用 B | `9e62605e82fdc5c1e66ad24a7eb74bec5eceb13d` | 2 | dsv4 b200 | 0 / 0 | unknown (no recipe fetched) | - |

Rows in runs with at least one resolved recipe: 347 of 496; rows in runs with none resolved: 149.

## The agentic recipes do set a mode

The 116 agentic `dynamo-vllm` rows come from AgentX recipes that do. At `SemiAnalysisAI/InferenceX@b860054f7b56c920a0e3902add7d0c662499ed67` (2026-11-10), under `inferencex-e2e/benchmarks/multi_node/srt-slurm-recipes/`:

| Recipe | router-mode | router-session-affinity-ttl-secs | Other router variable |
|---|---|---|---|
| `dsv41flash/vllm/gb300-fp4/agentx/agg-variants.yaml` | `"kv"` (line 43) | 14400 (44) | `DYN_ROUTER_ACTIVE_REQUEST_EXPIRY_SECS` 3600 (55) |
| `dsv41flash/vllm/gb300-fp4/agentx/disagg-variants.yaml` | `"kv"` (47) | 14400 (48) | expiry 3600 (62); `DYN_ROUTER_DECODE_ACTIVE_REQUEST_WEIGHT` 10000000 (63) |
| `kimik3.1/vllm/gb300-fp4/agentx/agg-variants.yaml` | `"least-loaded"` (65) | 1 (66) | expiry 3600 (68) |
| `kimik3.1/vllm/gb300-fp4/agentx/disagg-variants.yaml` | `"least-loaded"` (64) | 1 (65) | expiry 3600 (67) |
| `kimik3.1/vllm/gb300-fp4/agentx/disagg-dep16.yaml` | `"least-loaded"` (64) | 1 (65) | expiry 3600 (67) |
| `minimaxm31flash/vllm/gb200-fp4/agentx/agg-variants.yaml` | `kv` (36) | 14400 (37) | expiry 3600 (39) |
| `minimaxm31flash/vllm/gb200-fp4/agentx/disagg-mooncake.yaml` | `kv` (58) | 14400 (59) | expiry 3600 (61) |
| `minimaxm31flash/vllm/gb300-fp4/agentx/agg-variants.yaml` | `kv` (38) | 14400 (39) | expiry 3600 (41) |
| `minimaxm31flash/vllm/gb300-fp4/agentx/disagg-mooncake.yaml` | `kv` (58) | 14400 (59) | expiry 3600 (61) |

These are today's recipes at HEAD. I did not map each agentic row to its run's pinned commit as I did for the single-turn rows; the mapping method above applies unchanged (`run_url` to `head_sha` to the configuration's `CONFIG_FILE`).

The mode names are Dynamo's (`ai-dynamo/dynamo@33cfa1271c08f1660fc156ab2bc50647a268b87e:.agents/skills/dynamo-router-starter/references/router-modes.md:7-12`): `round-robin` (simplest baseline), `kv` (routes by KV overlap and active load), `least-loaded` (simple load-aware fallback), `random`, `direct`, `device-aware-weighted`.

## What this means for the table

Over the 496 single-turn rows the router is round-robin where a recipe was fetched. Over the agentic rows it is `kv` or `least-loaded`, with a session-affinity time-to-live. The mode is the recipe's, not the framework label's, so a `router_differs` entry cannot be keyed by the label `dynamo-vllm`; it needs the recipe's mode, which is in no API row and no server log I fetched, only in the pinned recipe.

## How to regenerate

For a run id in the row's `run_url`: `gh api repos/SemiAnalysisAI/InferenceX/actions/runs/<id> --jq .head_sha`; fetch `.github/configs/nvidia-master.yaml` at that commit; take each `CONFIG_FILE=` under the entries whose `framework` is `dynamo-vllm` and whose `model-prefix` and `runner` match the row; fetch the file under `benchmarks/multi_node/srt-slurm-recipes/` at the same commit; read its `frontend:` block.
