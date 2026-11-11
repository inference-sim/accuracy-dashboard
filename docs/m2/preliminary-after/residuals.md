# Residuals on the train split

Scored points on the train split: 89. Signed error is predicted / measured - 1 in percent; a group is a facet value with at least five points and, for a metric, five measured values. Validation, test and prospective points are not read. These figures are the input to model development, not an evaluation.

## The ten largest systematic biases

| # | Facet | Group | Metric | n | Series | Median signed error % | IQR % | Hypothesis |
|---|---|---|---|---|---|---|---|---|
| 1 | hardware | b200 | TTFT | 16 | 2 | +39.9 | 50.0 | The b200 prefill is over-priced: its attention and GEMM coefficients are transferred from another part (fidelity: coefficient_method transferred), and the host admission terms are assumed. Check the transferred prefill rates against a b200 kernel sweep. |
| 2 | regime | shallow queue, long prompt | TTFT | 16 | 4 | +36.9 | 102.3 | With a shallow queue and a prompt over 4096 tokens TTFT is the prefill itself: long-sequence attention (or the chunk size set by max_num_batched_tokens) is priced too high. The wide spread (IQR above 100) says it depends on the model. |
| 3 | concurrency band | 3-8 | TTFT | 26 | 9 | +32.0 | 49.9 | The same prefill over-pricing as the shallow-queue row, seen by concurrency: nine series share the band, so it is not one model. |
| 4 | model | kimi-k2.5 | TTFT | 25 | 4 | +31.3 | 44.0 | Kimi-K2.5 is int4 on these points: the dequantizing MoE and projection kernels are probably priced as the fp8 ones, which are slower. Price the int4 weight path (quantization is a modelled field now). |
| 5 | precision | int4 | TTFT | 25 | 4 | +31.3 | 44.0 | The same four series as the Kimi-K2.5 row (int4 is only Kimi-K2.5): one cause, counted twice. |
| 6 | model | kimi-k2.5-nvfp4 | TTFT | 22 | 2 | +28.6 | 28.0 | fp4 GEMMs are priced at rates transferred from fp8; Blackwell fp4 tensor-core throughput is about twice fp8, so prefill is over-predicted. |
| 7 | precision | fp4 | TTFT | 22 | 2 | +28.6 | 28.0 | The same two series as the Kimi-K2.5 NVFP4 row: one cause, counted twice. |
| 8 | hardware | b300 | TTFT | 21 | 2 | +28.2 | 49.6 | The b300 points are the NVFP4 ones above, on a part whose coefficients are mostly transferred from b200; the fp4 rate and the b300 transfer compound. |
| 9 | model | deepseek-v4-pro | TTFT | 36 | 2 | -28.1 | 52.1 | The only large under-prediction: DeepSeek-V4-Pro prefill is under-priced. Sparse-attention indexer cost and the expert-parallel all-to-all are the terms an MoE with a custom indexer adds; check that both are charged and not overlapped away. |
| 10 | hardware | h100 | TPOT | 6 | 1 | -21.8 | 13.2 | Decode on h100 (one series, MiniMax-M2.5) is under-predicted by about 22 percent: the HBM derate may be too optimistic or the per-step host launch cost (assumed, CUDA graph off or partial) is not charged. One series: low confidence. |

## All groups

| Facet | Group | Metric | n | Series | Median signed error % | IQR % |
|---|---|---|---|---|---|---|
| concurrency band | 1-2 | TPOT | 16 | 4 | +6.5 | 10.1 |
| concurrency band | 1-2 | TTFT | 16 | 4 | +1.4 | 66.5 |
| concurrency band | 3-8 | TPOT | 26 | 9 | +12.6 | 18.4 |
| concurrency band | 3-8 | TTFT | 26 | 9 | +32.0 | 49.9 |
| concurrency band | 33-128 | TPOT | 19 | 9 | -6.2 | 38.3 |
| concurrency band | 33-128 | TTFT | 19 | 9 | -10.1 | 82.9 |
| concurrency band | 9-32 | TPOT | 24 | 9 | +13.5 | 33.6 |
| concurrency band | 9-32 | TTFT | 24 | 9 | +13.9 | 47.9 |
| hardware | b200 | TPOT | 16 | 2 | +10.4 | 9.9 |
| hardware | b200 | TTFT | 16 | 2 | +39.9 | 50.0 |
| hardware | b300 | TPOT | 21 | 2 | +16.2 | 8.7 |
| hardware | b300 | TTFT | 21 | 2 | +28.2 | 49.6 |
| hardware | h100 | TPOT | 6 | 1 | -21.8 | 13.2 |
| hardware | h100 | TTFT | 6 | 1 | -4.2 | 31.8 |
| hardware | h200 | TPOT | 46 | 4 | +0.7 | 37.8 |
| hardware | h200 | TTFT | 46 | 4 | -9.8 | 66.9 |
| model | deepseek-v4-pro | TPOT | 36 | 2 | -7.8 | 25.8 |
| model | deepseek-v4-pro | TTFT | 36 | 2 | -28.1 | 52.1 |
| model | kimi-k2.5 | TPOT | 25 | 4 | +16.9 | 12.7 |
| model | kimi-k2.5 | TTFT | 25 | 4 | +31.3 | 44.0 |
| model | kimi-k2.5-nvfp4 | TPOT | 22 | 2 | +11.0 | 10.9 |
| model | kimi-k2.5-nvfp4 | TTFT | 22 | 2 | +28.6 | 28.0 |
| model | minimax-m2.5 | TPOT | 6 | 1 | -21.8 | 13.2 |
| model | minimax-m2.5 | TTFT | 6 | 1 | -4.2 | 31.8 |
| precision | fp4 | TPOT | 22 | 2 | +11.0 | 10.9 |
| precision | fp4 | TTFT | 22 | 2 | +28.6 | 28.0 |
| precision | fp8 | TPOT | 42 | 3 | -13.1 | 27.9 |
| precision | fp8 | TTFT | 42 | 3 | -14.5 | 46.4 |
| precision | int4 | TPOT | 25 | 4 | +16.9 | 12.7 |
| precision | int4 | TTFT | 25 | 4 | +31.3 | 44.0 |
| regime | deep queue, long prompt | TPOT | 22 | 4 | +16.1 | 33.9 |
| regime | deep queue, long prompt | TTFT | 22 | 4 | -12.3 | 85.3 |
| regime | deep queue, short prompt | TPOT | 25 | 5 | -8.4 | 32.5 |
| regime | deep queue, short prompt | TTFT | 25 | 5 | +16.8 | 47.2 |
| regime | shallow queue, long prompt | TPOT | 16 | 4 | +13.3 | 18.3 |
| regime | shallow queue, long prompt | TTFT | 16 | 4 | +36.9 | 102.3 |
| regime | shallow queue, short prompt | TPOT | 26 | 5 | +6.5 | 16.4 |
| regime | shallow queue, short prompt | TTFT | 26 | 5 | +15.8 | 37.1 |
| serving | aggregated | TPOT | 89 | 9 | +9.8 | 30.8 |
| serving | aggregated | TTFT | 89 | 9 | +10.6 | 53.5 |
| speculation | none | TPOT | 89 | 9 | +9.8 | 30.8 |
| speculation | none | TTFT | 89 | 9 | +10.6 | 53.5 |
