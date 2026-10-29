# signedprobe

The dashboard's single-turn scorer: it replays each InferenceX single-turn benchmark through
`blis replay` and writes one CSV row per point (measured vs predicted TTFT / TPOT).

**Origin.** Copied from inference-sim **v0.14.0** (`tools/signedprobe` and `tools/harness`, plus
`testdata/inferencex-workloads/{seed0,prompt-lengths}.json`), so a BLIS refactor no longer moves
or breaks the dashboard's scorer. inference-sim keeps its own harness for `kernelscore`,
`metricscore` and `sensitivity`.

**Changes from upstream** (everything else is byte-for-byte the v0.14.0 source):
- Import paths point at this module's `harness`.
- `repoRoot()` is this module's directory, which holds the vendored `testdata/`.
- `-blis-dir` names the inference-sim checkout `blis` runs in (it reads `defaults.yaml`
  relative to its working directory); before, that was the repo the harness lived in.
- Tests that simulate need `BLIS_SIM_DIR` (an inference-sim checkout to build `blis` from) and
  skip without it. Only seed 0 is vendored (seeds 1–4 serve inference-sim's `sensitivity`).

**Still uses BLIS's code** (as a Go dependency, not copied): `inference-sim/sim` and
`sim/workload` (trace and metrics types), `sim/vendored`, and blis-vllm's `compat/build` and
`compat/kernelmodel` (defaults and scenario construction). When blis-vllm removes `compat/`,
this and `orchestrator/blisdefaults` need updating together.

**Build** against the release being scored (what the nightly does):

```bash
bash orchestrator/build_signedprobe.sh <inference-sim checkout at a release tag> <out-binary>
```

**Test:**

```bash
cd orchestrator/signedprobe
go test ./...                                    # simulation tests skip
BLIS_SIM_DIR=<inference-sim checkout> go test ./... # all tests
```

**Verified:** on a 180-day InferenceX pull (1,697 single-turn rows), this copy built against
v0.14.0 produced `points.csv`, `fidelity.jsonl`, `not_scored.jsonl`, `facets.json` and
`provenance.json` byte-identical to inference-sim v0.14.0's own `tools/signedprobe`
(724 scored, 973 not scored).
