# BLIS Accuracy Dashboard

How accurately BLIS predicts real inference latency, scored nightly against
[SemiAnalysis InferenceX](https://inferencex.semianalysis.com). v0.1.0 — see
[`docs/RFC-0001.md`](docs/RFC-0001.md) for the full design.

**BLIS only. End-to-end only. Tables only, no plots.** Every number is a full `blis replay`
through the whole stack (router/admission → scheduler → batch → kernel), scored against the
pinned weekly InferenceX dump. v0.1.0 reports **mean TTFT and TPOT, each MAPE + shape** — exactly
what `cmd/signedprobe` emits. E2E, tail p99 and throughput are out of scope for v0.1.0.

## How it fits together

```
Nightly CI (.github/workflows/nightly.yml)
  1. detect-diff   resolve latest stable BLIS release + latest weekly InferenceX db-dump,
                   live (never hardcoded); no-op if unchanged vs state/last-run.json
  2. evaluate      build blis + signedprobe + metricscore FROM SOURCE at the resolved tag;
                   derive catalog/registry from the release's installation.md;
                   ingest the dump via the direct extractor (vLLM-filtered);
                   signedprobe → per-point CSV → orchestrator/build_summary.py → summary.json
  3. publish       commit data/latest/summary.json to the Pages-served branch; nothing on a
                   failed/partial run; no-op when inputs are unchanged
Static site (web/)  a Vite + React SPA (built on inference-sim/leaderboard/web's stack) that
                   fetches data/latest/summary.json and renders the Overview — two tables.
```

### This repo is glue + presentation only

It computes MAPE / shape / aggregates from `signedprobe`'s CSV — the **single source of truth** —
and holds **no other scoring logic**, no copied extractors, no log parsing, and does not
reimplement the scorer's exclusions (RFC §4.3/§4.4). `signedprobe`, `metricscore`, `blis` and the
extractors are all built/run from source at the CI-resolved release tag.

## Layout

| Path | What |
|---|---|
| `docs/RFC-0001.md` | The complete v0.1.0 design (the spec). |
| `docs/mockups/` | The approved Overview mockup (`.png` + `.html`). |
| `schemas/summary.v1.json` | Local JSON schema `summary.json` is validated against (RFC §4.4). |
| `orchestrator/` | The glue: resolve inputs, build from source, run `signedprobe`, shape the CSV into `summary.json`, validate. No scoring logic. |
| `web/` | The static Overview SPA (two tables, no plots). |
| `data/latest/summary.json` | The current snapshot (CI-produced; the site fetches it). |
| `data/snapshots/<id>/` | Immutable history, one per run. |
| `state/last-run.json` | The `(blis_tag, ix_tag)` diff key. |

## Local development

```bash
cd web && npm ci && npm run dev     # the SPA against data/latest/summary.json
npm run test                        # headless render tests (zero console errors on real data)
python3 orchestrator/test_build_summary.py   # orchestrator arithmetic + self-consistency oracle
```

The real numbers come from CI (`orchestrator/evaluate.sh`), which needs a restored InferenceX
dump; both inputs are resolved live. `budget_mode` runs the full pipeline on a hosted runner
against a small staged corpus (no 34 GB dump) to prove the machinery end to end.

## Deployment (GitHub Pages, one branch — RFC §4.2)

The built site is self-contained: `web/` copies `data/latest/summary.json` into the bundle, so
`vite build` emits a `dist/` carrying the SPA **and** its data. For production, enable GitHub
Pages once (Settings → Pages) — no server, no container, no RITS/OpenShift. The nightly `publish`
job commits the fresh snapshot to that same branch; a failed/partial run publishes nothing and
the prior snapshot stands.

The runner-budget reality (RFC D3), measured on the real dump: `db-dump/2026-09-28` is **~31 GB
compressed** and **~323 GB decompressed** (Postgres custom format v1.16 — needs `pg_restore` from
PostgreSQL 17+). It does **not** fit a GitHub-hosted runner's ~14 GB disk, so a production nightly
run targets a **self-hosted `evaluate`** runner (`runs-on: [self-hosted, blis-eval]`) while
`detect-diff` and `publish` stay hosted; the pre-flight step STOPs loudly and keeps the prior
snapshot if the budget isn't met. The `ci-verify.yml` workflow proves the whole pipeline on a
hosted runner in **budget mode** (a small real staged corpus, no dump).

### First real run (RFC D4) — against `db-dump/2026-09-28`, sha-verified

The full pipeline was run end-to-end against the actual dump (restored locally; the evaluate step
is machine-portable to a self-hosted runner). From that run:

- **Corpus:** 590 sweeps / **3,345 points**, vLLM-only, 5 models (deepseek-v4-pro, gpt-oss-120b,
  kimi-k2.5, minimax-m2.5, minimax-m3), 4 GPUs (b200/b300/h100/h200). Extraction skipped AMD parts
  (no catalog coefficients) and <3-concurrency sweeps — counted, not hidden.
- **signedprobe:** **3,315 points emitted** from real `blis replay` (~73 min); **2,497 scored**,
  **848 not_scored** = 821 `no_acceptance_rate` (mtp/speculative, tier UNSCORABLE) + 27 run-errors
  (concurrencies absent from the seed-0 workload fixture, e.g. 4096).
- **Headline (all tier):** TTFT MAPE **31.1%** / shape 28.1%; TPOT MAPE **19.7%** / shape 12.7%
  over 2,497 points — the RFC-predicted shape holds (TTFT, the queue-dominated metric, ~1.6× TPOT;
  cf. the AISimulate reference 22.4% TPOT / 45.3% TTFT).
- **On-target count (settles §6.3 / open-question 2):** **zero** — every scored point ran vLLM
  `0.29.0`, not the target `0.31.0`. So the on-target default would be empty; the UI falls back to
  all versions with a banner (and the measured·resolved tier is likewise empty on the direct path,
  so it falls back to the all tier). This is the freshness-fallback the RFC flagged as needed.
- **metricscore gap, by §4.4's three edge-sets:** (a) 23 partially-failing sweeps → signedprobe
  keeps 79 points metricscore drops whole-sweep; (b) measured-TPOT-without-TTFT: **0** (this dump
  always carries both); (c) prefix-caching points: **0** (this dump disables prefix caching
  entirely — a concrete answer to the RFC's open question). The comparison is logged, never gated.

## Metrics & scope (v0.1.0)

- **In:** mean **TTFT** and **TPOT**, each **MAPE** (absolute level error) and **shape**
  (normalized concurrency-curve error). Tiers: `measured-or-resolved` and `all`.
- **Out (named as future work, not shown):** E2E, tail p99, throughput.
- **No quality exclusions:** every point `signedprobe` emits is scored; known measurement
  artefacts are *noted*, not dropped. Speculative (`mtp`) points without an acceptance rate are
  `not_scored`.
- **Default view:** on-target vLLM (the default state *is* the headline).
