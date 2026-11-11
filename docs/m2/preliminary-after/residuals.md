# Residuals on the train split

Scored points on the train split: 286. Signed error is predicted / measured - 1 in percent; a group is a facet value with at least five points and, for a metric, five measured values. Validation, test and prospective points are not read. These figures are the input to model development, not an evaluation.

## The ten largest systematic biases

| # | Facet | Group | Metric | n | Series | Median signed error % | IQR % | Hypothesis |
|---|---|---|---|---|---|---|---|---|
| 1 | hardware | h200 | TTFT | 106 | 2 | -48.4 | 32.7 |  |
| 2 | regime | shallow queue, long prompt | TTFT | 54 | 7 | -47.1 | 55.0 |  |
| 3 | model | kimi-k2.5-nvfp4 | TTFT | 11 | 1 | +35.7 | 30.1 |  |
| 4 | hardware | h100 | TTFT | 45 | 2 | -33.0 | 32.3 |  |
| 5 | regime | deep queue, long prompt | TTFT | 77 | 7 | -29.7 | 45.1 |  |
| 6 | precision | fp4 | TTFT | 20 | 2 | +27.0 | 18.9 |  |
| 7 | hardware | b300 | TTFT | 90 | 2 | +26.4 | 48.8 |  |
| 8 | model | minimax-m3-mxfp8 | TTFT | 174 | 3 | -25.9 | 68.5 |  |
| 9 | concurrency band | >128 | TTFT | 43 | 7 | -23.0 | 62.3 |  |
| 10 | precision | fp8 | TTFT | 266 | 7 | -22.8 | 68.4 |  |

## All groups

| Facet | Group | Metric | n | Series | Median signed error % | IQR % |
|---|---|---|---|---|---|---|
| concurrency band | 1-2 | TPOT | 50 | 6 | +5.5 | 21.3 |
| concurrency band | 1-2 | TTFT | 50 | 6 | -11.3 | 78.0 |
| concurrency band | 3-8 | TPOT | 65 | 9 | -2.2 | 22.3 |
| concurrency band | 3-8 | TTFT | 65 | 9 | -14.7 | 70.9 |
| concurrency band | 33-128 | TPOT | 65 | 9 | -2.0 | 19.3 |
| concurrency band | 33-128 | TTFT | 65 | 9 | -18.6 | 57.9 |
| concurrency band | 9-32 | TPOT | 63 | 9 | -0.5 | 22.6 |
| concurrency band | 9-32 | TTFT | 63 | 9 | -19.9 | 74.1 |
| concurrency band | >128 | TPOT | 43 | 7 | -18.4 | 15.9 |
| concurrency band | >128 | TTFT | 43 | 7 | -23.0 | 62.3 |
| hardware | b200 | TPOT | 45 | 3 | +2.5 | 10.3 |
| hardware | b200 | TTFT | 45 | 3 | +17.9 | 60.7 |
| hardware | b300 | TPOT | 90 | 2 | +6.6 | 41.1 |
| hardware | b300 | TTFT | 90 | 2 | +26.4 | 48.8 |
| hardware | h100 | TPOT | 45 | 2 | -12.9 | 19.3 |
| hardware | h100 | TTFT | 45 | 2 | -33.0 | 32.3 |
| hardware | h200 | TPOT | 106 | 2 | -9.2 | 21.6 |
| hardware | h200 | TTFT | 106 | 2 | -48.4 | 32.7 |
| model | deepseek-v4-pro | TPOT | 45 | 2 | -0.7 | 26.0 |
| model | deepseek-v4-pro | TTFT | 45 | 2 | -14.8 | 69.6 |
| model | kimi-k2.5-nvfp4 | TPOT | 11 | 1 | +6.0 | 7.5 |
| model | kimi-k2.5-nvfp4 | TTFT | 11 | 1 | +35.7 | 30.1 |
| model | minimax-m2.5 | TPOT | 56 | 3 | -10.4 | 16.6 |
| model | minimax-m2.5 | TTFT | 56 | 3 | -10.5 | 79.2 |
| model | minimax-m3-mxfp8 | TPOT | 174 | 3 | -0.9 | 29.1 |
| model | minimax-m3-mxfp8 | TTFT | 174 | 3 | -25.9 | 68.5 |
| precision | fp4 | TPOT | 20 | 2 | +5.7 | 2.1 |
| precision | fp4 | TTFT | 20 | 2 | +27.0 | 18.9 |
| precision | fp8 | TPOT | 266 | 7 | -4.0 | 24.4 |
| precision | fp8 | TTFT | 266 | 7 | -22.8 | 68.4 |
| regime | deep queue, long prompt | TPOT | 77 | 7 | -4.9 | 21.0 |
| regime | deep queue, long prompt | TTFT | 77 | 7 | -29.7 | 45.1 |
| regime | deep queue, short prompt | TPOT | 94 | 9 | -5.4 | 25.7 |
| regime | deep queue, short prompt | TTFT | 94 | 9 | -7.2 | 63.3 |
| regime | shallow queue, long prompt | TPOT | 54 | 7 | -1.2 | 27.4 |
| regime | shallow queue, long prompt | TTFT | 54 | 7 | -47.1 | 55.0 |
| regime | shallow queue, short prompt | TPOT | 61 | 9 | +2.5 | 20.5 |
| regime | shallow queue, short prompt | TTFT | 61 | 9 | -6.2 | 70.4 |
| serving | aggregated | TPOT | 286 | 9 | -1.8 | 23.2 |
| serving | aggregated | TTFT | 286 | 9 | -18.2 | 71.9 |
| speculation | none | TPOT | 286 | 9 | -1.8 | 23.2 |
| speculation | none | TTFT | 286 | 9 | -18.2 | 71.9 |
