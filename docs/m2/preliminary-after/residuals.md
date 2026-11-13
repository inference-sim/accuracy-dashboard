# Residuals on the train split

Scored points on the train split: 367. Signed error is predicted / measured - 1 in percent; a group is a facet value with at least five points and, for a metric, five measured values. Validation, test and prospective points are not read. These figures are the input to model development, not an evaluation.

## The ten largest systematic biases

| # | Facet | Group | Metric | n | Series | Median signed error % | IQR % | Hypothesis |
|---|---|---|---|---|---|---|---|---|
| 1 | model | deepseek-v4-pro | TTFT | 53 | 2 | -43.7 | 47.9 |  |
| 2 | hardware | h100 | TTFT | 63 | 3 | -37.8 | 31.1 |  |
| 3 | model | minimax-m3-nvfp4 | TPOT | 55 | 1 | +30.3 | 33.8 |  |
| 4 | model | kimi-k2.5-nvfp4 | TTFT | 11 | 1 | +30.0 | 46.9 |  |
| 5 | precision | fp4 | TPOT | 66 | 2 | +26.7 | 32.7 |  |
| 6 | model | minimax-m2.5 | TTFT | 56 | 3 | -23.3 | 26.5 |  |
| 7 | concurrency band | >128 | TTFT | 48 | 9 | -23.3 | 27.2 |  |
| 8 | hardware | b300 | TPOT | 145 | 3 | +21.2 | 42.7 |  |
| 9 | hardware | h200 | TTFT | 123 | 3 | -19.4 | 35.3 |  |
| 10 | precision | fp8 | TTFT | 301 | 9 | -18.7 | 36.3 |  |

## All groups

| Facet | Group | Metric | n | Series | Median signed error % | IQR % |
|---|---|---|---|---|---|---|
| concurrency band | 1-2 | TPOT | 76 | 8 | +13.0 | 34.5 |
| concurrency band | 1-2 | TTFT | 76 | 8 | -4.4 | 50.4 |
| concurrency band | 3-8 | TPOT | 89 | 11 | +2.9 | 39.8 |
| concurrency band | 3-8 | TTFT | 89 | 11 | -8.4 | 52.7 |
| concurrency band | 33-128 | TPOT | 76 | 11 | -2.3 | 19.2 |
| concurrency band | 33-128 | TTFT | 76 | 11 | -17.7 | 31.7 |
| concurrency band | 9-32 | TPOT | 78 | 11 | +4.0 | 29.7 |
| concurrency band | 9-32 | TTFT | 78 | 11 | -16.7 | 51.1 |
| concurrency band | >128 | TPOT | 48 | 9 | -14.3 | 22.2 |
| concurrency band | >128 | TTFT | 48 | 9 | -23.3 | 27.2 |
| hardware | b200 | TPOT | 36 | 2 | +0.8 | 10.7 |
| hardware | b200 | TTFT | 36 | 2 | -8.7 | 51.6 |
| hardware | b300 | TPOT | 145 | 3 | +21.2 | 42.7 |
| hardware | b300 | TTFT | 145 | 3 | -0.1 | 38.0 |
| hardware | h100 | TPOT | 63 | 3 | -9.6 | 21.5 |
| hardware | h100 | TTFT | 63 | 3 | -37.8 | 31.1 |
| hardware | h200 | TPOT | 123 | 3 | -0.7 | 31.8 |
| hardware | h200 | TTFT | 123 | 3 | -19.4 | 35.3 |
| model | deepseek-v4-pro | TPOT | 53 | 2 | -15.2 | 41.3 |
| model | deepseek-v4-pro | TTFT | 53 | 2 | -43.7 | 47.9 |
| model | kimi-k2.5-nvfp4 | TPOT | 11 | 1 | +6.0 | 7.4 |
| model | kimi-k2.5-nvfp4 | TTFT | 11 | 1 | +30.0 | 46.9 |
| model | minimax-m2.5 | TPOT | 56 | 3 | -10.5 | 16.7 |
| model | minimax-m2.5 | TTFT | 56 | 3 | -23.3 | 26.5 |
| model | minimax-m3-mxfp8 | TPOT | 192 | 4 | +3.7 | 27.8 |
| model | minimax-m3-mxfp8 | TTFT | 192 | 4 | -15.4 | 34.2 |
| model | minimax-m3-nvfp4 | TPOT | 55 | 1 | +30.3 | 33.8 |
| model | minimax-m3-nvfp4 | TTFT | 55 | 1 | -0.1 | 28.5 |
| precision | fp4 | TPOT | 66 | 2 | +26.7 | 32.7 |
| precision | fp4 | TTFT | 66 | 2 | +0.3 | 32.5 |
| precision | fp8 | TPOT | 301 | 9 | -0.6 | 28.0 |
| precision | fp8 | TTFT | 301 | 9 | -18.7 | 36.3 |
| regime | deep queue, long prompt | TPOT | 93 | 10 | -0.5 | 24.6 |
| regime | deep queue, long prompt | TTFT | 93 | 10 | -17.6 | 36.7 |
| regime | deep queue, short prompt | TPOT | 109 | 11 | -4.5 | 28.1 |
| regime | deep queue, short prompt | TTFT | 109 | 11 | -18.0 | 32.6 |
| regime | shallow queue, long prompt | TPOT | 82 | 10 | +7.7 | 47.8 |
| regime | shallow queue, long prompt | TTFT | 82 | 10 | -7.0 | 41.8 |
| regime | shallow queue, short prompt | TPOT | 83 | 11 | +5.6 | 33.6 |
| regime | shallow queue, short prompt | TTFT | 83 | 11 | -2.7 | 55.4 |
| serving | aggregated | TPOT | 367 | 11 | +1.7 | 33.4 |
| serving | aggregated | TTFT | 367 | 11 | -14.4 | 37.7 |
| speculation | mtp | TPOT | 90 | 3 | +12.7 | 50.3 |
| speculation | mtp | TTFT | 90 | 3 | -9.4 | 51.0 |
| speculation | none | TPOT | 277 | 8 | +0.2 | 27.9 |
| speculation | none | TTFT | 277 | 8 | -15.3 | 33.8 |
