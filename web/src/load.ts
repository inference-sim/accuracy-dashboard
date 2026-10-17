/**
 * Load and validate the published snapshots. The site and its data ship on one Pages branch
 * (RFC §4.2), so these are plain same-origin fetches. Validation is loud, never a silent
 * fallback: a wrong schema_version or a malformed body throws with a clear message, which the
 * ErrorBoundary renders verbatim rather than letting the page show NaN/blank (RFC B1/C3).
 *
 * data/index.json lists every retained nightly run (newest first) so the run-picker can let a
 * user view an older run's full results — no delta, no re-run, just that snapshot's data.
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
  /** path relative to data/ for this run's summary.json */
  path: string
}

export interface RunIndex {
  schema_version: 1
  latest: string | null
  retention_days: number
  runs: RunRef[]
}

export function validateSummary(raw: unknown): Summary {
  if (raw == null || typeof raw !== 'object') {
    throw new SummaryLoadError('summary.json is not a JSON object')
  }
  const doc = raw as Record<string, unknown>
  if (doc.schema_version !== 1) {
    throw new SummaryLoadError(
      `summary.json schema_version is ${JSON.stringify(doc.schema_version)}, this build renders version 1`,
    )
  }
  for (const key of ['snapshot_id', 'provenance', 'coverage', 'totals', 'matrix']) {
    if (!(key in doc)) throw new SummaryLoadError(`summary.json is missing required field "${key}"`)
  }
  if (!Array.isArray(doc.matrix)) {
    throw new SummaryLoadError('summary.json "matrix" is not an array')
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
