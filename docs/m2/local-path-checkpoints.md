# Checkpoints and draft models that a run names by a local path

Measured 2026-11-10 over the baseline's frozen pull (1734 points) and the public InferenceX repository. Nothing here changes the scorer; the proposal in section 1 is for a ruling.

## 1. The 235 eagle3 points whose draft model is a local path

All 235 are single-turn vLLM points on b200 (118) and b300 (117), served MiniMax-M3, from 6 InferenceX runs. Each run names its draft model by a path such as `/scratch/fsw/models/MiniMax-M3-EAGLE3`, so `hf_repo` finds no repository and the served model's own graph, which has no eagle3, decides.

The benchmark script each run executed names the Hugging Face repository. The run's `head_sha` pins the tree (`gh api repos/SemiAnalysisAI/InferenceX/actions/runs/<id>`), and the single-node recipe for the run's chip and precision sets `DRAFT_MODEL` and builds the local path from its last component (`${DRAFT_MODEL##*/}`; for NVFP4 B300 `/data/models/${DRAFT_MODEL##*/}`). For every one of the 235 points the last component of the logged path equals that of the recipe's `DRAFT_MODEL`.

| InferenceX run | Commit | Recipe at that commit | `DRAFT_MODEL` | Points |
|---|---|---|---|---|
| 27805367644 | `e855d84c0b30712128a855be7c3476babffac7ca` | `benchmarks/single_node/fixed_seq_len/minimaxm3_fp8_b300_mtp.sh:61` | `Inferact/MiniMax-M3-EAGLE3` | 31 |
| 27805369633 | `8eb52820089f19306cc45c4349e9e508e3a5b2b6` | `benchmarks/single_node/fixed_seq_len/minimaxm3_fp8_b200_mtp.sh:63` | `Inferact/MiniMax-M3-EAGLE3` | 31 |
| 28689732075 | `0523519b93f68fbf4bd76d640ffdc3f880875c47` | `benchmarks/single_node/fixed_seq_len/minimaxm3_fp4_b300_mtp.sh:23` | `Inferact/MiniMax-M3-EAGLE3` | 30 |
| 28725010174 | `8769caf3b26fd77c39433a25f36fdc40efbd3ea0` | `benchmarks/single_node/fixed_seq_len/minimaxm3_fp4_b200_mtp.sh:23` | `Inferact/MiniMax-M3-EAGLE3` | 30 |
| 29984401390 | `0b896e92f975d0ef8e374fdc284b06444fc95242` | `minimaxm3_fp4_b200_mtp.sh:23` and `minimaxm3_fp4_b300_mtp.sh:23` (same directory) | `Inferact/MiniMax-M3-EAGLE3` | 29 + 28 |
| 30216094952 | `315b9a01786560b6d33ea3133c13ad5bc0f672b5` | `minimaxm3_fp8_b200_mtp.sh:30` and `minimaxm3_fp8_b300_mtp.sh:28` (same directory) | `Inferact/MiniMax-M3-EAGLE3-GQA` | 28 + 28 |

The recipes' own comments say the same in words (for example `minimaxm3_fp8_b200_mtp.sh:6` at `315b9a01…`: "Inferact/MiniMax-M3-EAGLE3-GQA draft head via --speculative-config with 3 speculative tokens"). 179 points use the EAGLE3 drafter and 56 the GQA one.

**Proposed rule (for a ruling; not implemented).** A fact the run's own record lacks (the Hugging Face repository of a draft model the log names by a path) is taken from the benchmark's recipe at the run's own commit: the recipe file and line, and the commit, are named on the point. `later_record` is for cluster facts and for a record written after the run, and this is neither: the recipe is the run's own, at the commit it ran. Suggested kind and wording: **`recipe_fact`**, subject `speculative_config.model`, with `record` = the recipe path and line at the commit, `date` = the commit's date, a G2 condition ("a fact of the run's configuration its own record lacks was taken from the benchmark's recipe at the run's commit; the point names the field, the recipe and its commit"). It needs a design sentence in 11.3 and a kind in the point record, so I have not added it. With it, all 235 points pass the drafter check, because the catalog's `minimax-m3-eagle3` and `minimax-m3-eagle3-gqa` list the base and MXFP8 models as targets and the models list them back. Without it they stay G5 with `drafter_not_in_catalog:eagle3`, which says the catalog has no such drafter; a more exact code would be `value_not_recorded:speculative_config.model` (the run records a path, not a repository). Say which.

The same pattern applies to the 5 Kimi-K3 DSpark points (b300): target `/scratch/models/Kimi-K3`, draft `/data/models/Kimi-K3-DSpark`, K = 7 and 3; I did not look up their recipe.

## 2. The 23 DeepSeek-V4-Pro NVFP4 points

All 23 are one InferenceX run, 33554397154, on b200, `vllm`, fp4, served `/scratch/models/DeepSeek-V4-Pro-NVFP4`. The pull holds no recipe checkpoint for them (`checkpoint: null`) and no fingerprint note, so the scorer's candidates for the served checkpoint are empty (a path is not a repository). The recipe does not help: at the run's commit `f31882621fccbde14ff09f9f01c86f00a63c0341`, `configs/nvidia-master.yaml:904` (`dsv4-fp4-b200-vllm`) says `model: deepseek-ai/DeepSeek-V4-Pro`, not the NVFP4 repository, and the script uses the runner-staged path. The catalog now has `deepseek-v4-pro-nvfp4` (`nvidia/DeepSeek-V4-Pro-NVFP4`). So the repository the run served is stated by nothing in the run's record or the recipe I read; only the local path's last component says NVFP4. They stay `not_in_catalog` and I will not match by file name.

The other 61 fp4 points on `/scratch/models/DeepSeek-V4-Pro` and 71 fp8 on `deepseek-ai/DeepSeek-V4-Pro` resolve to `deepseek-v4-pro` (no change).

## 3. The 35 Kimi-K3 points

They are not `not_in_catalog`. In the baseline all 35 are `value_not_recorded`: 25 h200 agentic points have no artifact at all (and `no_recipe_fingerprint`), 10 have artifacts but no server log. (My earlier ad-hoc check, which listed them as `model_not_in_catalog`, ignored the scorer's own checkpoint sources.) The 5 b300 Kimi-K3 points are different: they stay `not_in_catalog:dspark` because both their target and their draft model are named by local path (section 1).

## 4. Kimi-K3.1

No kimik3.1 row has a ledger unit yet (all 96 window rows are newer than the ledger's source revision), so none is in the pull. The InferenceX configuration names `moonshotai/Kimi-K3.1-Pro` (`inferencex-e2e/configs/nvidia-master.yaml:4833` at `b860054f7b56c920a0e3902add7d0c662499ed67`), and the server logs of the b300 vLLM rows (11) and mi355x rows (6) I fetched print exactly `moonshotai/Kimi-K3.1-Pro`, the catalog entry's `source.repo`. The b200 (11) and gb200 (10) vLLM logs print no Kimi string I could read. So no alias is needed; my earlier probe `moonshotai/Kimi-K3.1` was my guess, not the rows' string.

## Implemented

Ruling: no new kind. The freezer records the recipe's `DRAFT_MODEL` (script, line, commit) as `draft_checkpoint` for a run whose log names the draft by a local path, and the scorer takes it when the path's last component equals the repo's name (`support.resolve_draft`). A mismatch is `value_conflict:speculative_config.model`, and no recipe draft is `value_not_recorded:speculative_config.model`. A served path that disagrees with the run's one recipe checkpoint is `value_conflict:model` naming both. In the second freeze, `draft_checkpoint` is recorded for exactly the 235 points and `checkpoint_conflict` for the 23; with the layer 10 catalog all 235 resolve to a drafter entry.
