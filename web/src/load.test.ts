/**
 * load.ts rejection paths (PR #3 review T-c): validateSummary must fail LOUD (throw SummaryLoadError)
 * on malformed input — including the deep provenance shape (UI-b) that previously slipped through and
 * blanked the page — and loadIndex must degrade to null (never throw) on an absent/garbage index.
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { validateSummary, loadIndex, SummaryLoadError, RunLoader, type RunIndex } from './load'
import type { Summary } from './types'

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
    const d = clone(); d.schema_version = 3
    expect(() => validateSummary(d)).toThrow(/schema_version/)
  })
  it('accepts the v2 fixture, and refuses a v1 body labelled v2 (#30)', () => {
    const v2 = JSON.parse(readFileSync(fileURLToPath(new URL('../testdata/render-fixture.v2.summary.json', import.meta.url)), 'utf8'))
    expect(() => validateSummary(v2)).not.toThrow()
    const d = clone(); d.schema_version = 2
    expect(() => validateSummary(d)).toThrow(/ingest/)
    const missing = JSON.parse(JSON.stringify(v2))
    delete missing.matrix[0].rows[0].rows[0].rows[0].rows[0].fidelity
    expect(() => validateSummary(missing)).toThrow(/fidelity/)
    const noList = JSON.parse(JSON.stringify(v2))
    delete noList.not_scored
    expect(() => validateSummary(noList)).toThrow(/not_scored/)
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

describe('RunLoader caches so a revisited run keeps one object identity (flicker fix)', () => {
  const sum = (id: string) => ({ schema_version: 2, snapshot_id: id } as unknown as Summary)
  const idx = (ids: string[]): RunIndex => ({
    schema_version: 1,
    latest: ids[0] ?? null,
    runs: ids.map((snapshot_id) => ({
      snapshot_id, generated_at: null, blis_release: null, ix_release: null,
      path: `snapshots/${snapshot_id}/summary.json`,
    })),
  })

  function counting(index: RunIndex | null) {
    const calls = { latest: 0, at: [] as string[] }
    const loaders = {
      latest: async () => { calls.latest++; return sum('LATEST') },
      at: async (path: string) => { calls.at.push(path); return sum(path) },
    }
    return { loader: new RunLoader(index, loaders), calls }
  }

  it('null and the newest snapshot id share the "latest" key and one fetch', async () => {
    const index = idx(['new', 'old'])
    const { loader, calls } = counting(index)
    expect(loader.keyFor(null)).toBe('latest')
    expect(loader.keyFor('new')).toBe('latest') // newest id mirrors data/latest
    const a = await loader.load(null)
    const b = await loader.load('new')
    expect(a).toBe(b) // SAME object — this is what stops the headline flicker
    expect(calls.latest).toBe(1) // fetched once, not twice
    expect(calls.at).toEqual([])
  })

  it('revisiting the same older run returns the identical object without refetching', async () => {
    const index = idx(['new', 'old'])
    const { loader, calls } = counting(index)
    const first = await loader.load('old')
    const second = await loader.load('old')
    expect(first).toBe(second)
    expect(calls.at).toEqual(['snapshots/old/summary.json']) // one fetch only
  })

  it('an id not in the index rejects loudly (aged out of retention)', async () => {
    const { loader } = counting(idx(['new']))
    expect(loader.keyFor('gone')).toBe('missing:gone')
    await expect(loader.load('gone')).rejects.toThrow(/not in the published index/)
  })

  it('a failed load is not cached — the next navigation retries', async () => {
    let attempts = 0
    const loaders = {
      latest: async () => { attempts++; if (attempts === 1) throw new Error('flaky'); return sum('LATEST') },
      at: async () => sum('x'),
    }
    const loader = new RunLoader(idx(['new']), loaders)
    await expect(loader.load(null)).rejects.toThrow('flaky')
    await expect(loader.load(null)).resolves.toBeDefined() // retried, not a cached rejection
    expect(attempts).toBe(2)
  })

  it('with no index, null still loads latest (degraded, no picker)', async () => {
    const { loader, calls } = counting(null)
    await loader.load(null)
    expect(calls.latest).toBe(1)
  })

  it('a null-index loader cannot resolve a named id — it is "missing" (why main.tsx gates on index readiness)', () => {
    // main.tsx starts with new RunLoader(null) and swaps in RunLoader(idx) once the index lands.
    // Against the null loader a VALID newest id resolves to missing:<id>, so a hashchange that
    // fired before the index settled would wrongly render "not in the published index". main.tsx's
    // indexReady gate holds loadForHash() until the index's .then() installs the real loader.
    const nullLoader = new RunLoader(null)
    expect(nullLoader.keyFor('2026-10-23_blis-v0.12.0_ix-api')).toBe('missing:2026-10-23_blis-v0.12.0_ix-api')
    // ...and the same id against the real index collapses to 'latest' (it's the newest run).
    const real = new RunLoader(idx(['2026-10-23_blis-v0.12.0_ix-api', 'old']))
    expect(real.keyFor('2026-10-23_blis-v0.12.0_ix-api')).toBe('latest')
  })
})
