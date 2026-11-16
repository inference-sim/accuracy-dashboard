# Evaluation log

Every evaluation of the development split's test set (and the prospective set) is one row, so repeated peeking is visible. A candidate release is evaluated once. See [the protocol](evaluation-protocol.md). `compare.py --evaluate-test --log` appends rows to the table below. The committed M2 tables withhold their test figures; each row below is an evaluation made since.

The Release column is the simulator release each evaluation scored with. It was added on 2026-11-16; every row before it evaluated inference-sim v0.17.0, the release the matched comparison's contract names, and was given that release. No row was removed.

- Repeated: v0.17.0, 4 test evaluations: `matched.py report --evaluate-test` was run four times on 2026-11-16 while the pre-review findings of accuracy-dashboard#96 were fixed (the first three counted 155 test points; the fourth counted 159, once every point had its split); one pair of rows was first removed in error and has been restored. Each run counts as an evaluation of v0.17.0, so v0.17.0's test set is spent.

| Date | Commit | Release | Estimator | Split | Points | Scored |
|---|---|---|---|---|---|---|
| 2026-11-16 | 26c22e3b1868fa8311eef3bd32ce194b359c629a | v0.17.0 | BLIS v0.17.0 on the matched points | test | 155 | 71 |
| 2026-11-16 | 26c22e3b1868fa8311eef3bd32ce194b359c629a | v0.17.0 | BLIS v0.17.0 on the matched points | prospective | 0 | 0 |
| 2026-11-16 | 26c22e3b1868fa8311eef3bd32ce194b359c629a | v0.17.0 | BLIS v0.17.0 on the matched points | test | 155 | 71 |
| 2026-11-16 | 26c22e3b1868fa8311eef3bd32ce194b359c629a | v0.17.0 | BLIS v0.17.0 on the matched points | prospective | 0 | 0 |
| 2026-11-16 | 26c22e3b1868fa8311eef3bd32ce194b359c629a | v0.17.0 | BLIS v0.17.0 on the matched points | test | 155 | 71 |
| 2026-11-16 | 26c22e3b1868fa8311eef3bd32ce194b359c629a | v0.17.0 | BLIS v0.17.0 on the matched points | prospective | 0 | 0 |
| 2026-11-16 | 26c22e3b1868fa8311eef3bd32ce194b359c629a | v0.17.0 | BLIS v0.17.0 on the matched points | test | 159 | 71 |
| 2026-11-16 | 26c22e3b1868fa8311eef3bd32ce194b359c629a | v0.17.0 | BLIS v0.17.0 on the matched points | prospective | 0 | 0 |
