/**
 * The sources page (data/latest/funnel.json, funnel.py): a table with a row per source and its lanes, taken from the data. The
 * fixture is written by orchestrator/baseline/test_funnel.py (test_the_web_fixture_is_what_funnel_py_writes), so producer and
 * consumer cannot drift.
 */
import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { App } from './App'
import { Sources } from './components/Sources'
import { FunnelLoadError, FunnelNotPublished, fetchFunnel, shouldFetchFunnel, sourceRows, unscoredReasons, validateFunnel, type FunnelDoc } from './sources'
import { parseRoute, routeToHash } from './route'

const raw = JSON.parse(readFileSync(fileURLToPath(new URL('../testdata/funnel-2.fixture.json', import.meta.url)), 'utf8'))
const DOC = validateFunnel(raw)
const clone = () => JSON.parse(JSON.stringify(raw))
const html = (doc: FunnelDoc | null, error: string | null = null) => renderToStaticMarkup(<Sources doc={doc} error={error} />)

describe('the Sources page', () => {
  const rowsOf = (h: string) => [...h.matchAll(/<tr[^>]*>(.*?)<\/tr>/g)].map((m) => m[1]!)
  const tableOf = (h: string) => h.slice(h.indexOf('<table'), h.indexOf('</table>'))

  it('has one table row per source in the data, with its lanes after it, and none for a training-only source', () => {
    const h = tableOf(html(DOC))
    const names = rowsOf(h).slice(1).map((r) => r.replace(/<[^>]+>/g, ' ').trim().split(/\s+/)[0])
    expect(names).toEqual(sourceRows(DOC).map((r) => r.lane ?? r.source))
    expect(html(DOC)).not.toContain('vllm-ci-perf')
    expect(html(DOC)).not.toContain('training')
    expect(html(DOC)).not.toContain('D9')
  })

  it('shows a source that has no data as a row of zeros', () => {
    const d = clone()
    d.funnels.configiq.stages = { rows_held: 0, units: 0, in_scope: 0, recoverable: null, scored: 0 }
    for (const k of ['g5', 'failed', 'no_outcome', 'withheld']) d.funnels.configiq[k] = {}
    d.funnels.configiq.scored_by_grade = {}
    const h = tableOf(html(validateFunnel(d)))
    expect(rowsOf(h).some((r) => r.includes('configiq'))).toBe(true)
  })

  it('says it is loading, and shows a load error as it is', () => {
    expect(html(null)).toContain('Loading the per-source funnels')
    expect(html(null, 'funnel.json answered 404')).toContain('funnel.json answered 404')
  })

  it('is a tab of the app, opened by view=sources and linkable', () => {
    const r = parseRoute('#/?view=sources')
    expect(r.view).toBe('sources')
    expect(routeToHash(r)).toBe('#/?view=sources')
    const h = renderToStaticMarkup(<App summary={null} loadError={null} initialHash="#/?view=sources" funnel={DOC} />)
    expect(h).toContain('sources-table')
  })
})

describe('the funnel data', () => {
  it('lists the reasons of the unscored units largest first', () => {
    const f = DOC.funnels.inferencex!
    const r = unscoredReasons(f)
    expect(r.map((x) => x.units)).toEqual([...r.map((x) => x.units)].sort((a, b) => b - a))
    expect(r.reduce((n, x) => n + x.units, 0)).toBe(f.stages.in_scope - f.stages.scored - f.provisional.units)
  })

  it('refuses a wrong format and a missing part', () => {
    const bad = (mut: (d: any) => void, msg: RegExp) => {
      const d = clone()
      mut(d)
      expect(() => validateFunnel(d)).toThrow(msg)
    }
    bad((d) => (d.format = 'funnel-1'), /renders funnel-2/)
    bad((d) => (d.funnels = {}), /no funnels/)
    bad((d) => delete d.funnels.inferencex.g5, /lacks "g5"/)
    expect(() => validateFunnel(null)).toThrow(FunnelLoadError)
  })

  it('fetches only when the Sources tab is open and nothing is held, and reports a non-OK answer', async () => {
    expect(shouldFetchFunnel('sources', null, null, true)).toBe(true)
    expect(shouldFetchFunnel('classes', null, null, true)).toBe(false)
    expect(shouldFetchFunnel('sources', DOC, null, true)).toBe(false)
    expect(shouldFetchFunnel('sources', null, 'x', true)).toBe(false)
    expect(shouldFetchFunnel('sources', null, null, false)).toBe(false)
    await expect(fetchFunnel((async () => ({ ok: false, status: 404 })) as unknown as typeof fetch)).rejects.toThrow(/404/)
    await expect(fetchFunnel((async () => ({ ok: true, json: async () => raw })) as unknown as typeof fetch)).resolves.toMatchObject({ format: 'funnel-2' })
  })

  it('treats a 200 text/html answer for the funnel (an SPA host serving index.html for a missing file) as not published, and still refuses a bad document', async () => {
    const page = (async () => ({ ok: true, status: 200, json: async () => { throw new SyntaxError('Unexpected token <') } })) as unknown as typeof fetch
    await expect(fetchFunnel(page)).rejects.toBeInstanceOf(FunnelNotPublished)
    const bad = (async () => ({ ok: true, json: async () => ({ format: 'funnel-1' }) })) as unknown as typeof fetch
    expect(await fetchFunnel(bad).catch((e: unknown) => e)).not.toBeInstanceOf(FunnelNotPublished)
  })
})
