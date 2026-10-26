/**
 * Load and validate the published snapshots. The site and its data ship on one Pages branch
 * (RFC §4.2), so these are plain same-origin fetches. Validation is loud, never a silent
 * fallback: a wrong schema_version or a malformed body throws with a clear message, which the
 * ErrorBoundary renders verbatim rather than letting the page show NaN/blank (RFC B1/C3).
 *
 * data/index.json lists every retained nightly run (newest first) so the run-picker can let a
 * user view an older run's full results (no re-run, just that snapshot's data), or pick a second
 * run for the explicit A-vs-B Compare view (RFC discussion #2 point 3).
 */
import type { Summary } from './types'

export class SummaryLoadError extends Error {}

/** The current snapshot (CI keeps data/latest/ pointing at the newest run). */
export const SUMMARY_URL = 'data/latest/summary.json'
/** The manifest of retained runs for the picker. */
export const INDEX_URL = 'data/index.json'

/** One retained run, as listed in data/index.json. */
export interface RunRef {
  snapshot_id: string
  generated_at: string | null
  blis_release: string | null
  ix_release: string | null
  /** Which ingest produced the run: 'api' (the live InferenceX API) or 'db-dump' (the legacy
   *  weekly dump). The picker labels a run · API / · dump from this, and Compare refuses to diff
   *  across ingests. Absent on an index published before the field existed → treated as 'db-dump'. */
  ingest?: 'api' | 'db-dump'
  /** path relative to data/ for this run's summary.json */
  path: string
}

export interface RunIndex {
  schema_version: 1
  latest: string | null
  /** How many API-release snapshots the index keeps (#15's count-based last-5 rule). */
  keep_api?: number
  /** Legacy: the old dump pipeline's single day-based retention. Kept optional so an old index
   *  still loads; the new index is count-based (keep_api). */
  retention_days?: number
  runs: RunRef[]
}

export function validateSummary(raw: unknown): Summary {
  if (raw == null || typeof raw !== 'object') {
    throw new SummaryLoadError('summary.json is not a JSON object')
  }
  const doc = raw as Record<string, unknown>
  if (doc.schema_version !== 1 && doc.schema_version !== 2) {
    throw new SummaryLoadError(
      `summary.json schema_version is ${JSON.stringify(doc.schema_version)}, this build renders versions 1 and 2`,
    )
  }
  for (const key of ['snapshot_id', 'provenance', 'coverage', 'totals', 'matrix']) {
    if (!(key in doc)) throw new SummaryLoadError(`summary.json is missing required field "${key}"`)
  }
  if (!Array.isArray(doc.matrix)) {
    throw new SummaryLoadError('summary.json "matrix" is not an array')
  }
  // Validate NESTED shape, not just top-level keys (PR #3 review UI-b). The rail dereferences
  // provenance.blis.* and provenance.ground_truth.*; a summary with `provenance` present but those
  // sub-objects missing used to pass here and then throw during render → a blank page outside the
  // ErrorBoundary. Fail loud HERE instead, so the load-error view renders the message verbatim.
  const obj = (v: unknown, path: string): Record<string, unknown> => {
    if (v == null || typeof v !== 'object' || Array.isArray(v)) {
      throw new SummaryLoadError(`summary.json "${path}" is missing or not an object`)
    }
    return v as Record<string, unknown>
  }
  const need = (o: Record<string, unknown>, keys: string[], path: string) => {
    for (const k of keys) if (!(k in o)) throw new SummaryLoadError(`summary.json "${path}.${k}" is missing`)
  }
  const prov = obj(doc.provenance, 'provenance')
  need(obj(prov.blis, 'provenance.blis'), ['release', 'commit_sha', 'catalog', 'registry', 'extractor_version'], 'provenance.blis')
  need(obj(prov.ground_truth, 'provenance.ground_truth'), ['source', 'release_tag', 'measurement_sha256'], 'provenance.ground_truth')
  const totals = obj(doc.totals, 'totals')
  for (const tier of ['measured_or_resolved', 'all']) obj(totals[tier], `totals.${tier}`)
  need(obj(doc.coverage, 'coverage'), ['scored', 'not_scored'], 'coverage')
  if (doc.schema_version === 2) {
    // v2 (#30): every point carries its identity and fidelity record, and the snapshot says it
    // came from the API ingest. Checked here so a half-v2 file fails loud, not mid-render.
    if (prov.ingest !== 'api') throw new SummaryLoadError('summary.json v2 "provenance.ingest" is not "api"')
    if (!Array.isArray(doc.not_scored)) throw new SummaryLoadError('summary.json v2 "not_scored" is not an array')
    type Rows = { rows?: Rows[] } & Record<string, unknown>
    for (const m of doc.matrix as Rows[]) {
      for (const w of m.rows ?? []) for (const g of w.rows ?? []) for (const t of g.rows ?? []) for (const p of t.rows ?? []) {
        for (const k of ['point_id', 'identity', 'measured_date', 'fidelity']) {
          if (!(k in p)) throw new SummaryLoadError(`summary.json v2 point is missing "${k}"`)
        }
      }
    }
  }
  return doc as unknown as Summary
}

async function fetchJson(url: string, fetchImpl: typeof fetch): Promise<unknown> {
  let resp: Response
  try {
    resp = await fetchImpl(url, { cache: 'no-cache' })
  } catch (e) {
    throw new SummaryLoadError(`could not fetch ${url}: ${(e as Error).message}`)
  }
  if (!resp.ok) {
    throw new SummaryLoadError(`fetching ${url} returned HTTP ${resp.status}`)
  }
  try {
    return await resp.json()
  } catch (e) {
    throw new SummaryLoadError(`${url} is not valid JSON: ${(e as Error).message}`)
  }
}

export async function loadSummary(fetchImpl: typeof fetch = fetch, url = SUMMARY_URL): Promise<Summary> {
  return validateSummary(await fetchJson(url, fetchImpl))
}

/**
 * Load the run index. Returns null (not an error) when the site has no index yet — e.g. a repo
 * published before the picker existed, which still has data/latest/summary.json. The caller then
 * just shows the latest run with no picker.
 */
export async function loadIndex(fetchImpl: typeof fetch = fetch, url = INDEX_URL): Promise<RunIndex | null> {
  let raw: unknown
  try {
    raw = await fetchJson(url, fetchImpl)
  } catch {
    return null // no index published — degrade to latest-only, no picker
  }
  if (raw == null || typeof raw !== 'object' || !Array.isArray((raw as RunIndex).runs)) return null
  return raw as RunIndex
}

/** Load one run's summary by its data/-relative path (from a RunRef). */
export async function loadSummaryAt(path: string, fetchImpl: typeof fetch = fetch): Promise<Summary> {
  return validateSummary(await fetchJson(`data/${path}`, fetchImpl))
}

/**
 * Resolves a run selection (null = "latest", or a snapshot_id) to a summary, caching so each
 * distinct run is fetched once and always resolves to the SAME object. Two subtleties it exists to
 * get right:
 *   - The newest snapshot id and "latest" are the same bytes (CI keeps data/latest mirroring
 *     runs[0]), so they share one cache key. Entering/leaving the Compare view on the newest run —
 *     which toggles the hash between ?run=<newest> and no run — must not refetch or hand React a
 *     new-but-identical object, or the Overview headline flickers as its useMemos recompute.
 *   - A failed load is not cached, so a transient fetch error is retryable on the next navigation.
 * `want` must be in `index` unless it's null; an unknown id resolves to a loud "not in the index"
 * error (it may have aged out of retention).
 */
export class RunLoader {
  private readonly cache = new Map<string, Promise<Summary>>()
  constructor(
    private readonly index: RunIndex | null,
    private readonly loaders: { latest: () => Promise<Summary>; at: (path: string) => Promise<Summary> } = {
      latest: loadSummary,
      at: loadSummaryAt,
    },
  ) {}

  /** A stable cache key: null and the newest snapshot id both → 'latest'; unknown id → 'missing:<id>'. */
  keyFor(want: string | null): string {
    if (!want || (this.index && want === this.index.runs[0]?.snapshot_id)) return 'latest'
    return this.index && this.index.runs.some((r) => r.snapshot_id === want) ? want : `missing:${want}`
  }

  load(want: string | null): Promise<Summary> {
    const key = this.keyFor(want)
    const hit = this.cache.get(key)
    if (hit) return hit
    const p =
      key === 'latest'
        ? this.loaders.latest()
        : key.startsWith('missing:')
          ? Promise.reject(
              new SummaryLoadError(
                `run "${want}" is not in the published index (it may have aged out of the retention window)`,
              ),
            )
          : this.loaders.at(this.index!.runs.find((r) => r.snapshot_id === want)!.path)
    this.cache.set(key, p)
    p.catch(() => this.cache.delete(key)) // don't cache a rejection — let the next navigation retry
    return p
  }
}
