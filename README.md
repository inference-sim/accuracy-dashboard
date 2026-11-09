# BLIS Accuracy Dashboard

How accurately BLIS predicts real inference latency, scored nightly against
[SemiAnalysis InferenceX](https://inferencex.semianalysis.com). v0.1.0 — see
[`docs/RFC-0001.md`](docs/RFC-0001.md) for the full design.

**BLIS only. End-to-end only. Tables only, no plots.** Every number is a full `blis replay`
through the whole stack (router/admission → scheduler → batch → kernel), scored against the
pinned weekly InferenceX dump. v0.1.0 reports **mean TTFT and TPOT, each MAPE + shape**. E2E,
tail p99 and throughput are out of scope for v0.1.0.

Points are scored by `orchestrator/ingest/score.py`. For a single-turn point it writes the
requests the InferenceX client sent (`orchestrator/ingest/inferencex_client.py`), runs
`blis replay` on them, and computes the client's mean TTFT and TPOT from the per-request rows of
the Result document blis prints. For an agentic point it runs `blis replay --agentic-scenario`
and reads `ttft_mean_ms` and `tpot_mean_ms` from the Result. The Go command `signedprobe`, which
scored single-turn points before, has been removed; the pipeline sketch below predates the API
ingest.

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

## Scoring harness image

The scoring harness is the one place a BLIS simulation is compared with a measured end-to-end
benchmark (design §2.2, §11.7). It is released as a container image, built from each release
tag by `.github/workflows/harness-release.yml`, published to
`ghcr.io/inference-sim/accuracy-dashboard-harness`, and signed by digest with cosign keyless
signing. The job summary and the `harness-digest` artifact give the digest.

The image takes three inputs, as flags to its entrypoint `harness/run.sh`:

- a simulator build: `--sim`, a release tag or a full 40-hex commit of inference-sim, which the
  harness clones and builds (a branch name is refused, because it moves);
- the data: `--catalog` and `--registry` (both required until the simulator can report the data it embeds);
- a set of ledger units: `--units`, with `--pull`, the frozen recorded runs of those units.

A repository whose pull requests run the harness pins one digest in one pin file, as it pins
any dependency, pulls the image by that digest, and passes it to the run as `HARNESS_DIGEST`.
The release bot moves the pin. Every figure records the digest of the harness that produced it
(X8). A run without `HARNESS_DIGEST` records `unreleased`, and its figures are labelled
experimental: they may be posted on a pull request, never published as BLIS's accuracy.

## Layout

| Path | What |
|---|---|
| `docs/RFC-0001.md` | The complete v0.1.0 design (the spec). |
| `docs/mockups/` | The approved Overview mockup (`.png` + `.html`). |
| `schemas/summary.v1.json` | Local JSON schema `summary.json` is validated against (RFC §4.4). |
| `orchestrator/` | The glue: resolve inputs, build from source, run `blis replay` per point (`ingest/score.py`), shape the CSV into `summary.json`, validate. |
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

The real numbers come from CI; both inputs are resolved live. The nightly streams the resolved
weekly dump into a Postgres service container, restoring only the 3 tables the extractor reads.

## Deployment (GitHub Pages via Actions — RFC §4.2)

Two separate concerns:

1. **Data** — the nightly `publish` job commits `data/` (the run **index**, `data/latest/`, and
   every retained `data/snapshots/<id>/`) to the default branch; a failed/partial run publishes
   nothing and the prior snapshot stands.
2. **Site** — `.github/workflows/pages.yml` builds the SPA and deploys it to GitHub Pages via the
   Actions artifact path. The build **stages the full committed `data/`** (index + latest + all
   snapshots) into the bundle, so the live site's **run-picker and A/B compare** work — not just a
   single `data/latest`. It runs on push to `main` (paths `web/`, `data/`, `schemas/`) and on
   demand; `vite`'s `base: './'` makes the bundle work under the project-pages subpath
   (`…/accuracy-dashboard/`). No server, no container, no gh-pages branch, no built assets in git.

**One-time setup:** Settings → Pages → Build and deployment → **Source = "GitHub Actions"**. Until
that's set the deploy step can't publish (the build still runs). Least-privilege: the workflow is
`contents: read` by default; only the deploy job gets `pages: write` + `id-token: write`.

### Fits a GitHub-hosted runner — streaming selective restore (RFC D3)

`db-dump/2026-09-28` is **~31 GB compressed / ~323 GB decompressed** (Postgres custom format v1.16,
needs `pg_restore` from PostgreSQL 17+) — far more than a hosted runner's disk if restored whole.
But the direct extractor reads only **3 tables** (`benchmark_results`, `configs`, `server_logs`),
so `stream_restore.sh` streams the release parts straight through `zstd -d` into
`pg_restore -t <those tables>`: **neither the 31 GB compressed nor the 323 GB decompressed archive
ever lands on disk**, and only **~6 GB of restored tables** sit in the Postgres service container.
So the real dump runs on a **standard GitHub-hosted runner** — no self-hosted runner, no on-disk
dump. (`pg_restore -t` reads only until it has those 3 tables, then closes the pipe; the resulting
upstream "zstd: Broken pipe" is the expected early-close, not an error — see `stream_restore.sh`.)

### vLLM-version filter — latest N (RFC discussion #2 point 2)

BLIS's prediction is a function of topology + engine-settings + concurrency; it is **independent of
the vLLM version**. The dump measures each deployment on many vLLM builds. So before scoring,
the nightly reduces the corpus to the **latest N = 5 numbered vLLM
versions present in the dump** (window moves with each dump; unnumbered/custom builds excluded),
then — since BLIS predicts identically across versions — keeps only the **newest surviving version
per BLIS-input identity**. Each prediction is scored once, against the latest build. This replaces
the earlier on-target-version rule.

### First real run (RFC D4) — against `db-dump/2026-09-28`, latest-5 filter

- **Corpus (after the latest-5 filter + dedup):** 87 sweeps / **481 points**, 4 models
  (deepseek-v4-pro, gpt-oss-120b, kimi-k2.5, minimax-m2.5), on vLLM `0.21.0 … 0.25.1`. Extraction
  skipped AMD parts (no catalog coefficients) and <3-concurrency sweeps — counted, not hidden.
- **signedprobe:** real `blis replay` per point; **382 scored**, **99 not_scored** (chiefly
  `no_acceptance_rate` — mtp/speculative, tier UNSCORABLE — plus a few run-errors for concurrencies
  absent from the seed-0 workload fixture). Coverage is asserted to balance (`scored + not_scored
  == corpus points`), fail-loud, in `evaluate.sh`.
- **Headline (all tier):** TTFT MAPE **~33%** / shape ~30%; TPOT MAPE **~17%** / shape ~13% — TTFT,
  the queue-dominated metric, runs higher than TPOT, as expected.
- **Tier fallback:** the direct path leaves engine-settings resolved, so every point lands in the
  `all` tier (zero `measured·resolved`); the UI defaults to `measured·resolved` and falls back to
  `all` with a banner.
- **metricscore (logged, never gated — A6):** run on the same corpus as a non-blocking diagnostic;
  signedprobe's points ship regardless — exactly why the RFC makes signedprobe the single source of
  truth and metricscore a diagnostic.
- **Compare any two runs (RFC discussion #2 point 3):** every retained snapshot is kept
  (`data/snapshots/`); the UI's "Compare against" slot shows the per-metric Δ (B − A) over the
  points both runs scored.

## Metrics & scope (v0.1.0)

- **In:** mean **TTFT** and **TPOT**, each **MAPE** (absolute level error) and **shape**
  (normalized concurrency-curve error). Tiers: `measured-or-resolved` and `all`.
- **Out (named as future work, not shown):** E2E, tail p99, throughput.
- **No quality exclusions:** every point `signedprobe` emits is scored; known measurement
  artefacts are *noted*, not dropped. Speculative (`mtp`) points without an acceptance rate are
  `not_scored`.
- **Default view:** all vLLM versions in the latest-N window (the on-target-version rule is
  replaced by the latest-N filter, RFC discussion #2 point 2).
