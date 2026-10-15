# RFC-0001: BLIS Accuracy Dashboard

**Status:** Draft / Request for Comments
**Repo:** `inference-sim/accuracy-dashboard`
**Author:** @susiejojo
**Date:** 2026-10-15

---

## 1. Summary

Build a dashboard that reports **how accurately BLIS predicts real inference
latency**, scored nightly against [SemiAnalysis InferenceX](https://inferencex.semianalysis.com)
measurements. We report **MAPE** (absolute level error) and **SHAPE** (normalized
concurrency-curve error) for **TTFT, TPOT/ITL and E2E**, broken down by model,
hardware and workload.

The dashboard reports numbers for **BLIS only** — this is an accuracy report, not a
simulator leaderboard. We score the **latest pinned BLIS release**, never `main`.

A nightly CI job re-runs the evaluation whenever **either** input changes:
- a new **InferenceX weekly db-dump release**, or
- a new **BLIS release tag**.

It publishes a `summary.json` the dashboard renders. InferenceX is the first and only
ground-truth source at launch; the schema leaves room to add **llm-d-prism** and
**vLLM benchmark** data later.

Inspiration: [NVIDIA AISimulate e2e-accuracy dashboard](https://ai-dynamo.org/aisimulate/e2e-accuracy/)
(MAPE matrix, provenance, snapshot discipline) and
[inference-sim/leaderboard](https://github.com/inference-sim/leaderboard)
(Go server + GHCR image + sortable tables, computed-value provenance).

---

## 2. Background and prior art

### 2.1 What already exists (and what we reuse)

Most of the hard evaluation work is **already built** in
[`blis-latency-kernel`](https://github.com/inference-sim/blis-latency-kernel):

| Component | What it does | Reuse |
|---|---|---|
| `cmd/score` | Absolute **MAPE** of predicted ITL vs a measurement corpus, per-point / per-model / aggregate, with every derived input flagged and every out-of-scope point explained. | Core of the **MAPE** panel. |
| `cmd/shape` | **SHAPE** — scores the *normalized* concurrency response (StepTime ratio across two concurrencies) vs AISimulate's published relatives. Needs no scheduler; isolates curvature error from level error. | Core of the **SHAPE** panel. |
| `scripts/extract_inferencex_direct.py` | Pulls a **BLIS-vs-InferenceX** corpus directly from the InferenceX db-dump: absolute `mean_tpot`/`mean_ttft`, configuration keyed by each run's own server-log args (849 distinct deployments resolved), speculative arms kept and marked. | Nightly **ingest** step. |
| `scripts/extract_inferencex_absolutes.py` | Extracts the absolute anchor latency per sweep from the dump, validated by reproducing AISimulate's own published relatives (refuses a sweep where no run matches). | Anchors for absolute MAPE. |
| `internal/harness` | `Open`, `DecodeBatch`, `DefaultCatalog/Registry/Measurements`, replica accounting. | Shared by the evaluator. |

The scoring harness **deliberately scores the kernel only** and refuses TTFT —
TTFT is queue-dominated and the kernel models no scheduler. See §4.3 for how we add TTFT.

### 2.2 Data release schedule for InferenceX

Confirmed from the InferenceX site and the pin already recorded in
`blis-latency-kernel/testdata/measurements/aisimulate_e2e.json`:

- **Cadence:** ~**1,000+ new benchmark datapoints per week**; the full database is
  **published as a public GitHub Release every week**.
- **Location:** `github.com/SemiAnalysisAI/InferenceX-app/releases/tag/db-dump/YYYY-MM-DD`
  (e.g. the currently-pinned `db-dump/2026-09-28`), each pinned by a `measurement_sha256`.
- **Shape:** a restorable Postgres dump; the evaluator needs only `benchmark_results`,
  `configs`, `workflow_runs`.
- **Also available:** a credential-free public JSON/CSV API under
  `https://inferencex.semianalysis.com/api/v1/...` (`/benchmarks`, `/views/*?format=csv`,
  OpenAPI at `/api/openapi.json`). We treat the **weekly release as the source of truth**
  (reproducible, sha-pinned) and keep the API as a fallback / cross-check.

**Trigger implication:** the dashboard tracks the newest `db-dump/*` release tag; a new
tag is one of the two diff signals.

---

## 3. Goals / Non-goals

**Goals**
1. Nightly, reproducible BLIS accuracy numbers vs InferenceX, with full provenance.
2. Headline **MAPE** (absolute) + **SHAPE** (curve) for **TTFT, TPOT/ITL, E2E**.
3. Breakdown by model × hardware × workload, sortable, with per-point drill-down.
4. Re-evaluate automatically on the `(inferencex_release, blis_release)` diff.
5. Score the **latest pinned BLIS release** only; `main` is explicitly excluded.
6. Pluggable ground-truth sources (InferenceX now; prism / vLLM later).

**Non-goals**
- Not a multi-simulator leaderboard — **BLIS only**.
- No universal pass/fail threshold (follow AISimulate: numbers apply only to the exact
  measured operating points in a snapshot).
- Not re-deriving InferenceX measurements; we consume their published dump.

---

## 4. Design

### 4.1 High-level architecture

```
                   ┌──────────────────────────────────────────────────────┐
                   │  Nightly CI (GitHub Actions, scheduled + dispatch)     │
                   │                                                        │
  InferenceX ──────┤  1. detect-diff:  latest db-dump tag  vs  state       │
  weekly release   │                   latest BLIS tag     vs  state       │
                   │                   → noop if unchanged                  │
  BLIS release ────┤  2. ingest:       restore dump → extract_inferencex_* │
  (ghcr/tag)       │                   → corpus.json (sha-pinned)          │
                   │  3. evaluate:     pinned BLIS release                  │
                   │                   → MAPE (score) + SHAPE (shape)       │
                   │                   → TTFT/ITL/E2E end-to-end run        │
                   │  4. publish:      summary.json + points.json          │
                   │                   → commit to `data` branch + release  │
                   └───────────────────────────┬────────────────────────────┘
                                                │  reads summary.json
                   ┌────────────────────────────▼───────────────────────────┐
                   │  Go server (leaderboard pattern)                        │
                   │  - serves embedded Vite SPA + /api/*                    │
                   │  - packaged as ghcr.io/inference-sim/accuracy-dashboard │
                   │  - deployed on OpenShift (PVC for data snapshots)       │
                   └─────────────────────────────────────────────────────────┘
```

### 4.2 Backend — Go server (chosen, mirrors `leaderboard`)

A single Go binary, `cmd/accuracy-dashboard serve`, matching the leaderboard's shape so
the two services stay operationally consistent:

- **Static data model.** The server reads versioned snapshots from a data directory
  (PVC on OpenShift): `snapshots/<run_id>/summary.json` + `points.json`. Each snapshot is
  immutable and self-describing (provenance block).
- **API surface** (small, read-only):
  - `GET /api/version` → pinned BLIS release, InferenceX dump tag, dashboard commit
    (mirrors leaderboard's version rail).
  - `GET /api/snapshots` → list of available snapshots (date, tags, counts).
  - `GET /api/summary?snapshot=latest` → the accuracy matrix + aggregates.
  - `GET /api/points?snapshot=…&model=…&hw=…` → per-point drill-down.
  - `GET /api/summary.json` → raw download (parity with AISimulate's "Download JSON").
- **Packaging.** Multi-arch image `ghcr.io/inference-sim/accuracy-dashboard` built on
  release (reuse leaderboard's `release.yml`); `deploy/openshift/`.
- **Why a server, not just Pages:** keeps parity with `leaderboard` (same deploy target,
  same version-rail UX, same ops), lets us serve multiple historical snapshots and do
  server-side filtering without shipping every snapshot to the client.

### 4.3 Evaluator — `cmd/eval` (new, in this repo)

Orchestrates the pinned BLIS release against a corpus and emits `summary.json`. Three
scorers, each a distinct quantity:

1. **MAPE (level).** Reuse `blis-latency-kernel/cmd/score` logic against
   `inferencex_direct.json` absolutes → absolute % error on **ITL/TPOT**, per point,
   with the harness's existing in-scope/why flags carried through to the UI.
   We also emit **SMAPE** per point for free (symmetric, bounded) as a secondary column.

2. **SHAPE (curve).** Reuse `cmd/shape` → normalized concurrency-response error. Isolates
   curvature error (the kernel's known worst axis) independent of level. Needs no scheduler.

3. **TTFT / ITL / E2E (end-to-end).** The kernel harness refuses TTFT by design. To
   headline it we run the **full inference-sim simulator** (the pinned release) on each
   in-scope InferenceX sweep and read `ttft_mean_ms`, `itl_mean_ms`, `e2e_mean_ms`
   (p50/p99) — the same fields the leaderboard already surfaces — then MAPE each against
   the dump's measured values. This is the one genuinely new piece of evaluation work;
   see Open Questions.

**Pinned-release discipline.** The evaluator never builds `main`. It pulls
`ghcr.io/inference-sim/blis:<latest-stable-tag>` (or `go install …@vX.Y.Z`), records the
exact tag + image digest in the provenance block, and that tag is part of the snapshot id.

### 4.4 `summary.json` schema (draft)

```jsonc
{
  "schema_version": 1,
  "snapshot_id": "2026-10-15_blis-v0.10.0_ix-2026-09-28",
  "generated_at": "2026-10-15T06:00:00Z",
  "provenance": {
    "blis": { "release": "v0.10.0", "image_digest": "sha256:…",
              "catalog": "0.2.1", "registry": "v0.1.1" },
    "ground_truth": {
      "source": "SemiAnalysis InferenceX",
      "release_tag": "db-dump/2026-09-28",
      "source_url": "https://github.com/SemiAnalysisAI/InferenceX-app/releases/tag/db-dump/2026-09-28",
      "measurement_sha256": "9125257c…"
    },
    "evaluator_commit": "…"
  },
  "aggregates": {                       // headline tiles
    "mape":  { "ttft": 0.0, "itl": 0.0, "e2e": 0.0, "n": 0 },
    "smape": { "ttft": 0.0, "itl": 0.0, "e2e": 0.0, "n": 0 },
    "shape": { "median": 0.0, "worst": 0.0, "n": 0 }
  },
  "matrix": [                           // one row per model × hw × workload
    {
      "model": "MiniMax-M3", "hardware": "H200", "precision": "MXFP8",
      "workload": "single_turn 1k/1k", "decode_tp": 8, "points": 24,
      "mape":  { "ttft": 0.0, "itl": 0.0, "e2e": 0.0 },
      "shape": { "median": 0.0, "worst": 0.0 },
      "in_scope": 20, "flagged": 4, "flags": ["ctx derived", "speculative"]
    }
  ],
  "filters": { "exclude": ["outliers", "multinode", "bad_silicon"] }
}
```

`points.json` carries the per-point rows (predicted vs measured, concurrency, derivation
`why`) for drill-down — the same `point`/`resolved` structs the harness already produces.

### 4.5 Frontend — Vite SPA (embedded in the Go binary)

Taking the best of both references:

- **Headline tiles** (AISimulate): MAPE(TTFT), MAPE(ITL/TPOT), MAPE(E2E), SHAPE median —
  big numbers with point counts.
- **Accuracy matrix** (AISimulate): one sortable table, grouped by model → expand a
  workload → pick a GPU for a per-point chart. Every column sorts on click.
- **Views toggle:** `MAPE | SHAPE | E2E`, and a throughput/interactivity axis mirroring
  the reference URL's `?view=interactivity`.
- **Provenance rail** (leaderboard): pinned BLIS release, InferenceX dump tag, snapshot
  date, with a branch/snapshot selector and **Download JSON**.
- **Exclude filters** (AISimulate): outliers / bad-silicon / multi-node toggles.
- **Computed-vs-read provenance** (leaderboard): derived inputs (`ctx derived`,
  `batch=concurrency`, speculative) get a dotted underline revealing the derivation on
  hover — the harness already records this per point.
- **No pass/fail coloring, no composite score** — report, don't assert.

### 4.6 Nightly CI (GitHub Actions)

```yaml
on:
  schedule: [{ cron: "17 6 * * *" }]   # nightly, off the :00 mark
  workflow_dispatch:
jobs:
  detect-diff:   # compare latest db-dump tag + latest BLIS tag to state/last-run.json
  evaluate:      # needs: detect-diff, if: changed. restore dump → ingest → cmd/eval
  publish:       # commit summary.json/points.json to `data` branch + GH Release
```

- **Runner:** standard GitHub-hosted `ubuntu-latest` for ingest/score (BLIS is CPU-only
  and deterministic — no GPU needed, by design). If the full-sim TTFT pass is heavy, move
  `evaluate` to a larger self-hosted runner; the diff/publish stays hosted.
- **Diff mechanism:** a `state/last-run.json` holds the last `(blis_tag, ix_tag)`. The job
  resolves `gh release view --repo SemiAnalysisAI/InferenceX-app` (latest `db-dump/*`) and
  the latest `inference-sim` stable tag; identical pair ⇒ exit noop. This is the
  "pick up on the diff" requirement, as a cheap 2-tuple poll (no webhooks).
- **Dump access:** InferenceX dumps are public GitHub Releases; restore in-CI with
  `pg_restore` into an ephemeral Postgres service container, then run the existing
  `extract_inferencex_*` scripts.

---

## 5. Extensibility: additional ground-truth sources

The corpus format (`point` with stated/derived flags) is source-agnostic. Adding
**llm-d-prism** or **vLLM benchmark** data = a new `extract_<source>.py` producing the same
corpus schema + a `source` tag on each point. The matrix gains a source facet; MAPE/SHAPE
math is unchanged. Out of scope for v1 but the schema reserves it.

---

## 6. Open questions (for discussion)

1. **TTFT fidelity.** The full-sim TTFT pass is the only new evaluation surface. Do we
   gate v1 on it, or ship **MAPE(ITL) + SHAPE** first (reusing the kernel harness verbatim)
   and add TTFT/E2E in v1.1? What InferenceX workload subset is TTFT even in-scope for
   (single_turn only; agentic_traces rows carry NULL isl/osl)?
2. **Server vs. static.** Confirmed as Go server for leaderboard parity — but is OpenShift
   the deploy target here too, or do we want GitHub Pages as a zero-ops fallback for the
   read-only matrix?
3. **Dump restore in CI.** Restoring the full InferenceX Postgres dump nightly may be
   heavy. Cache by `measurement_sha256`; only re-ingest on a new tag. Acceptable?
4. **Historical trend.** Keep every nightly snapshot (trend of MAPE over BLIS releases),
   or only the latest per `(blis_tag, ix_tag)` pair?
5. **Scope filters.** Adopt AISimulate's exact exclude set (outliers / bad-silicon /
   multi-node), or BLIS-specific (speculative arms, derived-context points)?

---

## 7. Proposed milestones

- **M1 — Evaluator & schema:** `cmd/eval` wrapping `score` + `shape`, emit `summary.json`
  for one pinned BLIS release vs the pinned InferenceX dump. (No TTFT yet.)
- **M2 — Nightly CI:** diff detection, dump restore, publish to `data` branch.
- **M3 — Go server + SPA:** matrix, tiles, provenance rail, drill-down, Download JSON.
- **M4 — TTFT/E2E:** full-sim pass; add TTFT/E2E columns.
- **M5 — Deploy:** GHCR image + OpenShift manifests; historical trend view.

---

*Feedback welcome on §4.3 (TTFT), §4.2 (server vs. Pages), and §6 broadly.*
