#!/usr/bin/env python3
"""Shared helpers for the direct InferenceX corpus extractor.

Two things the direct extractor needs and that are small enough to own here rather than
import from a larger script:

  CHIPS, MODELS       the catalog maps: an InferenceX model/GPU slug -> the blis-catalog
                      name the registry has coefficients for. A slug absent from these is
                      skipped, because the catalog has no graph (or the registry no
                      coefficients) for it, so it cannot be priced.
  parse_args_line     reads a vLLM server log's `non-default args` line into the fields
                      the corpus keys a deployment on. The parse is depth-aware: the args
                      dict nests a `speculative_config` dict whose own keys include
                      `model`, and a depth-blind search would read the DRAFT checkpoint
                      there and report it as the served model.

These were factored out of the kernel's development scripts so the dashboard owns the
code it runs (issue #20). The maps' VALUES are the catalog's own names and must not drift;
only the surrounding prose is this repo's.
"""

import re

# InferenceX model slug -> blis-catalog model name. A slug absent here is skipped: the
# catalog has no graph for it, so it cannot be priced.
MODELS = {
    "gptoss120b": "gpt-oss-120b",
    "minimaxm2.5": "minimax-m2.5",
    "qwen3.5": "qwen3.5-397b-a17b",
    "glm5": "glm-5",
    # The snapshot measures meta-llama/Meta-Llama-3.1-70B; the catalog carries the Instruct
    # variant. The mapping is VERIFIED rather than assumed on the grounds that instruction
    # tuning changes no shape: the base config is gated on HuggingFace, so it was read from
    # two independent mirrors (unsloth/Meta-Llama-3.1-70B and
    # NousResearch/Meta-Llama-3.1-70B) and compared field by field against the committed
    # Instruct config. All thirteen shape fields agree -- 80 layers, 8192 hidden, 28672
    # intermediate, 64 q heads over 8 kv, 128256 vocab, bfloat16, rope_theta 500000,
    # 131072 positions, silu, rms_norm_eps 1e-05, tie_word_embeddings false,
    # LlamaForCausalLM, no head_dim -- with zero differences.
    #
    # It is the corpus's largest model at 408 points and its only DENSE one; the other four
    # are all MoE, so without it the comparison says nothing about dense architectures.
    "llama70b": "llama-3.1-70b-instruct",
    # Added to blis-catalog this cycle, each with its graph DERIVED by the catalog's own
    # scripts/derive_graph.py rather than written: deepseek-v3 prices as MLA plus routed
    # experts with a three-layer dense prologue, and kimi-k2.5 as the same family -- vLLM
    # instantiates its text decoder as DeepseekV2ForCausalLM over config.text_config, and the
    # text_config names DeepseekV3ForCausalLM itself.
    #
    # DeepSeek-V4-Pro and MiniMax-M3 are deliberately absent. Both carry a learned
    # block-sparse indexer (index_n_heads / sparse_attention_config), which the schema names
    # as sparse_mla but blis-registry has no coefficients for; the kernel would fall back to
    # the generic attention rate and misprice them silently.
    "dsr1": "deepseek-v3",
    "kimik2.5": "kimi-k2.5",
    # MiniMax-M3 is MiniMaxM3SparseForConditionalGeneration, a vision-language checkpoint
    # whose text decoder the artifact measures. Its attention is block-sparse: the read is
    # bounded by sparse_topk_blocks * sparse_block_size and a separate indexer scores which
    # blocks to read. The catalog derives it from the published config at revision
    # f0e1c1e0, with every shape cross-checked against the safetensors headers.
    "minimaxm3": "minimax-m3",
    # DeepSeek-V4-Pro: compressed sparse attention at two ratios with a top-k indexer.
    # The catalog derives it from the published config at revision b5968e91, with every
    # bound read from vLLM's own compressor and sparse_mla rather than from field names.
    "dsv4": "deepseek-v4-pro",
}

# InferenceX GPU slug -> blis-catalog hardware name.
CHIPS = {"h100": "h100", "h200": "h200", "b200": "b200", "b300": "b300"}

# Settings read from the args line. Each is a vLLM CLI flag; the value is whatever the run
# passed, or null when it passed nothing.
ARG_FIELDS = (
    "max_num_seqs",
    "max_num_batched_tokens",
    "max_model_len",
    "block_size",
    "enable_prefix_caching",
    "gpu_memory_utilization",
    "cuda_graph_sizes",
    "max_cudagraph_capture_size",
    # Fields that identify WHICH DEPLOYMENT a run is, not how it was tuned. Without them
    # two rows at the same (model, hardware, tp, isl, osl, concurrency) can be different
    # deployments and get pooled as repeated measurements of one. On MiniMax-M3 h200 tp8
    # at concurrency 4 that pooling spans 4,862 to 10,085 us: two of the five runs serve
    # Inferact/MiniMax-M3-EAGLE3 with eagle3 speculation at 3 draft tokens, and three
    # serve the plain MXFP8 checkpoint. Grouping by these as well takes the median
    # within-cell spread from 1.384x to 1.016x over 630 cells.
    "model",
    "speculative_config",
    "num_speculative_tokens",
    "enable_expert_parallel",
)


def args_body(log: str) -> str | None:
    r"""The text inside the `non-default args` braces, matched by balance rather than by
    the first closing brace.

    A non-greedy `\{(.*?)\}` stops at the first `}`, which on this corpus is inside the
    nested speculative_config dict rather than at the end of the args: 2,628 of the
    9,192 args lines in the dump carry a nested dict, and every field after it was
    silently dropped -- max_cudagraph_capture_size on 757, block_size and four
    others on 83.
    """
    i = log.find("non-default args: {")
    if i < 0:
        return None
    start = log.index("{", i)
    depth = 0
    for k in range(start, len(log)):
        if log[k] == "{":
            depth += 1
        elif log[k] == "}":
            depth -= 1
            if depth == 0:
                return log[start + 1:k]
    return None


def top_level_fields(body: str) -> dict[str, str]:
    """Split the args body into its TOP-LEVEL `key: value` pairs.

    Split by brace depth rather than by comma, because `speculative_config` holds a
    nested dict whose own keys include `model`. A depth-blind search finds the DRAFT
    checkpoint there and reports it as the served model: on a MiniMax-M3 MTP run the
    served MiniMax-M3-MXFP8 came back as Inferact/MiniMax-M3-EAGLE3, which is a
    different model with a different graph. Nested values are returned whole, so a
    caller that wants a field inside one reads it from the returned text.
    """
    out: dict[str, str] = {}
    depth = 0
    part = ""
    parts = []
    for ch in body:
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(part)
            part = ""
        else:
            part += ch
    parts.append(part)
    for piece in parts:
        m = re.match(r"\s*'([A-Za-z_0-9]+)':\s*(.+)$", piece, re.S)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def parse_args_line(log: str) -> dict:
    """The `non-default args` dict, as a mapping of the fields this project reads."""
    body = args_body(log)
    if body is None:
        return {}
    fields = top_level_fields(body)
    found = {}
    for field in ARG_FIELDS:
        if field not in fields:
            continue
        raw = fields[field].strip().strip("'\"")
        if raw == "None":
            # The run passed the flag with a literal None, which is the absence of a
            # setting. Recording the string makes it look like a value: a reader asking
            # whether a capture size was set would get "None" and read it as one.
            continue
        if raw in ("True", "False"):
            found[field] = raw == "True"
        elif re.fullmatch(r"-?\d+", raw):
            found[field] = int(raw)
        elif re.fullmatch(r"-?\d*\.\d+", raw):
            found[field] = float(raw)
        else:
            found[field] = raw
    # num_speculative_tokens and the draft method live INSIDE speculative_config on the
    # runs that carry one, so they are read from there rather than from the top level.
    # Recorded because they change tokens per step: a step that accepts drafts serves
    # more than one token per request, so an ITL read against it is not a step time.
    nested = found.get("speculative_config")
    if isinstance(nested, str):
        n = re.search(r"'num_speculative_tokens':\s*(\d+)", nested)
        if n:
            found["num_speculative_tokens"] = int(n.group(1))
        meth = re.search(r"'method':\s*'([A-Za-z_0-9]+)'", nested)
        if meth:
            found["speculative_method"] = meth.group(1)
        draft = re.search(r"'model':\s*'([^']+)'", nested)
        if draft:
            found["draft_model"] = draft.group(1)
    return found
