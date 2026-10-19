/**
 * load.ts rejection paths (PR #3 review T-c): validateSummary must fail LOUD (throw SummaryLoadError)
 * on malformed input — including the deep provenance shape (UI-b) that previously slipped through and
 * blanked the page — and loadIndex must degrade to null (never throw) on an absent/garbage index.
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { validateSummary, loadIndex, SummaryLoadError } from './load'

function fixtureObj(): Record<string, unknown> {
  const path = fileURLToPath(new URL('../testdata/render-fixture.summary.json', import.meta.url))
  return JSON.parse(readFileSync(path, 'utf8'))
}
// deep clone so each test mutates its own copy
const clone = () => JSON.parse(JSON.stringify(fixtureObj())) as any

describe('validateSummary rejects malformed input loudly', () => {
  it('accepts the real fixture', () => {
    expect(() => validateSummary(fixtureObj())).not.toThrow()
  })
  it('throws on non-object', () => {
    expect(() => validateSummary(null)).toThrow(SummaryLoadError)
    expect(() => validateSummary(42)).toThrow(SummaryLoadError)
  })
  it('throws on wrong schema_version', () => {
    const d = clone(); d.schema_version = 2
    expect(() => validateSummary(d)).toThrow(/schema_version/)
  })
  it('throws on a missing top-level field', () => {
    const d = clone(); delete d.matrix
    expect(() => validateSummary(d)).toThrow(/matrix/)
  })
  it('throws when matrix is not an array', () => {
    const d = clone(); d.matrix = {}
    expect(() => validateSummary(d)).toThrow(/matrix/)
  })
  it('throws when provenance.blis is missing (the blank-page bug — UI-b)', () => {
    const d = clone(); delete d.provenance.blis
    expect(() => validateSummary(d)).toThrow(/provenance\.blis/)
  })
  it('throws when a provenance.blis sub-field is missing', () => {
    const d = clone(); delete d.provenance.blis.commit_sha
    expect(() => validateSummary(d)).toThrow(/provenance\.blis\.commit_sha/)
  })
  it('throws when provenance.ground_truth is malformed', () => {
    const d = clone(); d.provenance.ground_truth = null
    expect(() => validateSummary(d)).toThrow(/ground_truth/)
  })
  it('throws when a totals tier is missing', () => {
    const d = clone(); delete d.totals.all
    expect(() => validateSummary(d)).toThrow(/totals\.all/)
  })
})

describe('loadIndex degrades to null (never throws) on bad input', () => {
  const okFetch = (body: unknown): typeof fetch =>
    (async () => ({ ok: true, json: async () => body }) as Response) as unknown as typeof fetch
  const notFound: typeof fetch = (async () => ({ ok: false, status: 404 }) as Response) as unknown as typeof fetch
  const netError: typeof fetch = (async () => { throw new Error('offline') }) as unknown as typeof fetch

  it('absent index (404) → null', async () => {
    expect(await loadIndex(notFound)).toBeNull()
  })
  it('network error → null', async () => {
    expect(await loadIndex(netError)).toBeNull()
  })
  it('garbage body (no runs array) → null', async () => {
    expect(await loadIndex(okFetch({ nope: true }))).toBeNull()
  })
  it('a valid index parses through', async () => {
    const idx = { schema_version: 1, latest: 'a', retention_days: 30, runs: [] }
    expect(await loadIndex(okFetch(idx))).toEqual(idx)
  })
})
