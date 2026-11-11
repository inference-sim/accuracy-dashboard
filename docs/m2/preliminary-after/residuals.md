# Residuals on the train split

Scored points on the train split: 366. Signed error is predicted / measured - 1 in percent; a group is a facet value with at least five points and, for a metric, five measured values. Validation, test and prospective points are not read. These figures are the input to model development, not an evaluation.

## The ten largest systematic biases

| # | Facet | Group | Metric | n | Series | Median signed error % | IQR % | Hypothesis |
|---|---|---|---|---|---|---|---|---|
| 1 | hardware | h200 | TTFT | 141 | 3 | -47.8 | 37.8 |  |
| 2 | model | kimi-k2.5-nvfp4 | TTFT | 11 | 1 | +35.7 | 30.1 |  |
| 3 | hardware | h100 | TTFT | 45 | 2 | -33.0 | 32.3 |  |
| 4 | regime | shallow queue, long prompt | TTFT | 74 | 10 | -31.3 | 50.0 |  |
| 5 | regime | deep queue, long prompt | TTFT | 97 | 10 | -26.4 | 46.4 |  |
| 6 | model | minimax-m3-mxfp8 | TTFT | 174 | 3 | -25.9 | 68.5 |  |
| 7 | precision | fp8 | TTFT | 301 | 8 | -23.3 | 61.1 |  |
| 8 | concurrency band | >128 | TTFT | 50 | 10 | -23.3 | 46.7 |  |
| 9 | concurrency band | >128 | TPOT | 50 | 10 | -19.7 | 14.9 |  |
| 10 | hardware | b300 | TTFT | 117 | 3 | +19.7 | 40.6 |  |

## All groups

| Facet | Group | Metric | n | Series | Median signed error % | IQR % |
|---|---|---|---|---|---|---|
| concurrency band | 1-2 | TPOT | 70 | 9 | +4.6 | 16.8 |
| concurrency band | 1-2 | TTFT | 70 | 9 | -10.7 | 77.7 |
| concurrency band | 3-8 | TPOT | 85 | 12 | -4.7 | 21.2 |
| concurrency band | 3-8 | TTFT | 85 | 12 | -11.3 | 64.9 |
| concurrency band | 33-128 | TPOT | 82 | 12 | -5.6 | 22.8 |
| concurrency band | 33-128 | TTFT | 82 | 12 | -17.6 | 50.5 |
| concurrency band | 9-32 | TPOT | 79 | 12 | -1.1 | 23.2 |
| concurrency band | 9-32 | TTFT | 79 | 12 | -15.7 | 64.1 |
| concurrency band | >128 | TPOT | 50 | 10 | -19.7 | 14.9 |
| concurrency band | >128 | TTFT | 50 | 10 | -23.3 | 46.7 |
| hardware | b200 | TPOT | 63 | 4 | -0.8 | 16.1 |
| hardware | b200 | TTFT | 63 | 4 | -1.2 | 55.2 |
| hardware | b300 | TPOT | 117 | 3 | +4.4 | 37.7 |
| hardware | b300 | TTFT | 117 | 3 | +19.7 | 40.6 |
| hardware | h100 | TPOT | 45 | 2 | -12.9 | 19.3 |
| hardware | h100 | TTFT | 45 | 2 | -33.0 | 32.3 |
| hardware | h200 | TPOT | 141 | 3 | -10.5 | 23.8 |
| hardware | h200 | TTFT | 141 | 3 | -47.8 | 37.8 |
| model | deepseek-v4-pro | TPOT | 125 | 5 | -9.1 | 24.4 |
| model | deepseek-v4-pro | TTFT | 125 | 5 | -12.5 | 59.1 |
| model | kimi-k2.5-nvfp4 | TPOT | 11 | 1 | +6.0 | 7.5 |
| model | kimi-k2.5-nvfp4 | TTFT | 11 | 1 | +35.7 | 30.1 |
| model | minimax-m2.5 | TPOT | 56 | 3 | -10.4 | 16.6 |
| model | minimax-m2.5 | TTFT | 56 | 3 | -10.5 | 79.2 |
| model | minimax-m3-mxfp8 | TPOT | 174 | 3 | -0.9 | 29.1 |
| model | minimax-m3-mxfp8 | TTFT | 174 | 3 | -25.9 | 68.5 |
| precision | fp4 | TPOT | 65 | 4 | +1.4 | 17.1 |
| precision | fp4 | TTFT | 65 | 4 | +4.8 | 36.6 |
| precision | fp8 | TPOT | 301 | 8 | -4.9 | 25.4 |
| precision | fp8 | TTFT | 301 | 8 | -23.3 | 61.1 |
| regime | deep queue, long prompt | TPOT | 97 | 10 | -9.0 | 22.4 |
| regime | deep queue, long prompt | TTFT | 97 | 10 | -26.4 | 46.4 |
| regime | deep queue, short prompt | TPOT | 114 | 12 | -8.9 | 26.9 |
| regime | deep queue, short prompt | TTFT | 114 | 12 | -13.3 | 61.8 |
| regime | shallow queue, long prompt | TPOT | 74 | 10 | -0.9 | 23.8 |
| regime | shallow queue, long prompt | TTFT | 74 | 10 | -31.3 | 50.0 |
| regime | shallow queue, short prompt | TPOT | 81 | 12 | +2.1 | 18.4 |
| regime | shallow queue, short prompt | TTFT | 81 | 12 | +4.7 | 58.2 |
| serving | aggregated | TPOT | 366 | 12 | -4.0 | 24.0 |
| serving | aggregated | TTFT | 366 | 12 | -14.8 | 64.8 |
| speculation | mtp | TPOT | 80 | 3 | -10.6 | 27.1 |
| speculation | mtp | TTFT | 80 | 3 | -10.6 | 45.7 |
| speculation | none | TPOT | 286 | 9 | -1.8 | 23.2 |
| speculation | none | TTFT | 286 | 9 | -18.2 | 71.9 |
