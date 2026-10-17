/**
 * Headless render tests (vitest + renderToStaticMarkup, environment: 'node') — the stand-in
 * for "npm run dev and look". They assert the real snapshot renders with ZERO console errors
 * and no NaN/blank cells (RFC B1), and that the deep-link / tier / filter logic behaves.
 */
import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { App } from './App'
import { validateSummary } from './load'
import { flattenPoints, aggregatePair } from './aggregate'
import { applyFilters } from './filter'
import type { Summary } from './types'

function loadFixture(): Summary {
  // A real signedprobe-derived snapshot, committed as a labeled test fixture. The SHIPPED
  // data/latest/summary.json is only ever CI-produced (RFC D2); this is not that file.
  const path = fileURLToPath(new URL('../testdata/render-fixture.summary.json', import.meta.url))
  return validateSummary(JSON.parse(readFileSync(path, 'utf8')))
}

describe('App renders the real CI-shaped snapshot', () => {
  it('renders with zero console errors and no NaN/undefined in the DOM', () => {
    const errors: string[] = []
    const spy = vi.spyOn(console, 'error').mockImplementation((...a) => {
      errors.push(a.map(String).join(' '))
    })
    const html = renderToStaticMarkup(<App summary={loadFixture()} loadError={null} />)
    spy.mockRestore()
    expect(errors.join('\n')).toBe('')
    expect(html).not.toContain('NaN')
    expect(html).not.toContain('undefined')
    expect(html).not.toContain('>null<')
  })

  it('renders a selected topology with REPEAT-concurrency points with zero console errors', () => {
    // Regression: InferenceX has repeat benchmark runs at the same concurrency, so the points
    // table must key rows uniquely (concurrency alone collides → React key warning). This
    // selects a real topology that has 42 points across only 7 distinct concurrencies.
    const summary = loadFixture()
    const m = summary.matrix[0]!
    const w = m.rows[0]!
    const g = w.rows[0]!
    const t = g.rows[0]!
    const sweepKey = `${m.model}|${w.label}|${g.label}|${t.label}`
    const concs = t.rows.map((p) => p.concurrency)
    expect(concs.length).toBeGreaterThan(new Set(concs).size) // the fixture really has repeats
    const errors: string[] = []
    const spy = vi.spyOn(console, 'error').mockImplementation((...a) => {
      errors.push(a.map(String).join(' '))
    })
    renderToStaticMarkup(
      <App summary={summary} loadError={null} initialHash={`#/?sel=${encodeURIComponent(sweepKey)}&tier=all`} />,
    )
    spy.mockRestore()
    expect(errors.join('\n')).toBe('') // no "two children with the same key" warning
  })

  it('shows the headline totals row and the title', () => {
    const html = renderToStaticMarkup(<App summary={loadFixture()} loadError={null} />)
    expect(html).toContain('ALL MODELS')
    expect(html).toContain('End-to-end accuracy — BLIS vs InferenceX')
  })

  it('renders every model when the populated tier is viewed (via deep-link)', () => {
    // The real dump's vLLM runs are all off-target (v0.29.0 vs target v0.31.0), so the
    // on-target default falls back to all versions (RFC §6 open-question 2) — every model must
    // still render. Drive to the "all" tier the way a user's deep-link would.
    const html = renderToStaticMarkup(<App summary={loadFixture()} loadError={null} initialHash="#/?tier=all" />)
    expect(html).toContain('deepseek-v4-pro')
    expect(html).toContain('gpt-oss-120b')
    expect(html).toContain('kimi-k2.5')
    expect(html).toContain('minimax-m2.5')
  })

  it('falls back to all versions (with a banner) when no points are on-target', () => {
    // Default view = on-target; the real snapshot has zero on-target points, so the UI must not
    // show an empty headline — it falls back and says so (RFC §6 open-question 2).
    const html = renderToStaticMarkup(<App summary={loadFixture()} loadError={null} />)
    expect(html).toContain('showing')
    expect(html).toContain('all versions')
    expect(html).toContain('deepseek-v4-pro') // data visible, not an empty table
  })

  it('a deep-linked selected topology populates the points table with measured vs predicted', () => {
    const summary = loadFixture()
    // first topology sweepKey from the fixture
    const m = summary.matrix[0]!
    const w = m.rows[0]!
    const g = w.rows[0]!
    const t = g.rows[0]!
    const sweepKey = `${m.model}|${w.label}|${g.label}|${t.label}`
    const hash = `#/?sel=${encodeURIComponent(sweepKey)}&tier=all`
    const html = renderToStaticMarkup(<App summary={summary} loadError={null} initialHash={hash} />)
    expect(html).toContain('Points — ')
    expect(html).toContain(m.model)
    // the points table header
    expect(html).toContain('meas')
    expect(html).toContain('pred')
  })

  it('shows the provenance rail from the summary (not hardcoded)', () => {
    const html = renderToStaticMarkup(<App summary={loadFixture()} loadError={null} />)
    expect(html).toContain('v0.10.0') // resolved BLIS release
    expect(html).toContain('0.2.1') // catalog
    expect(html).toContain('v0.1.1') // registry
    expect(html).toContain('2026-09-28') // dump tag
  })

  it('shows the future-metrics note and run-wide counts', () => {
    const html = renderToStaticMarkup(<App summary={loadFixture()} loadError={null} />)
    expect(html).toContain('E2E, tail-latency and throughput accuracy are planned for a future release')
    expect(html).toContain('points scored')
    expect(html).toContain('not scored')
    expect(html).toContain('multi-node')
  })

  it('renders a clear error (not a blank page) when loading fails', () => {
    const html = renderToStaticMarkup(<App summary={null} loadError={'fetching data/latest/summary.json returned HTTP 404'} />)
    expect(html).toContain('Could not load the latest snapshot')
    expect(html).toContain('HTTP 404')
  })
})

describe('client-side aggregation keeps filters honest (RFC B3)', () => {
  it('a specific-version filter isolates that version; "all" shows every version', () => {
    const summary = loadFixture()
    const all = flattenPoints(summary)
    const version = all.find((p) => p.engineVersion)!.engineVersion!
    const allVersions = applyFilters(all, { sel: null, tier: 'all', vllm: 'all', multinode: false })
    const pinned = applyFilters(all, { sel: null, tier: 'all', vllm: { version }, multinode: false })
    expect(pinned.length).toBeLessThanOrEqual(allVersions.length)
    expect(pinned.every((p) => p.engineVersion === version)).toBe(true)
  })

  it('totals recompute from visible points (not the stored node metrics)', () => {
    const summary = loadFixture()
    const all = flattenPoints(summary)
    const half = all.slice(0, Math.floor(all.length / 2))
    const full = aggregatePair(all)
    const partial = aggregatePair(half)
    // A different subset generally yields a different mean — proving it's recomputed, not stored.
    expect(partial.all.mape.n).toBeLessThan(full.all.mape.n)
  })
})
