/**
 * Load and validate data/latest/summary.json. The site and its data ship on one Pages branch
 * (RFC §4.2), so this is a plain same-origin fetch. Validation is loud, never a silent
 * fallback: a wrong schema_version or a malformed body throws with a clear message, which the
 * ErrorBoundary renders verbatim rather than letting the page show NaN/blank (RFC B1/C3).
 */
import type { Summary } from './types'

export class SummaryLoadError extends Error {}

/** The committed snapshot path, relative to the site base (works under the Pages subpath). */
export const SUMMARY_URL = 'data/latest/summary.json'

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

export async function loadSummary(fetchImpl: typeof fetch = fetch, url = SUMMARY_URL): Promise<Summary> {
  let resp: Response
  try {
    resp = await fetchImpl(url, { cache: 'no-cache' })
  } catch (e) {
    throw new SummaryLoadError(`could not fetch ${url}: ${(e as Error).message}`)
  }
  if (!resp.ok) {
    throw new SummaryLoadError(`fetching ${url} returned HTTP ${resp.status}`)
  }
  let json: unknown
  try {
    json = await resp.json()
  } catch (e) {
    throw new SummaryLoadError(`${url} is not valid JSON: ${(e as Error).message}`)
  }
  return validateSummary(json)
}
